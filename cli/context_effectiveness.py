from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, Iterable

from . import context_usage

CONTEXT_EVENT_TYPES = (
    "FACT",
    "REVIEW_COMPLETED",
    "VERIFICATION_COMPLETED",
    "DELIVERY_RESULT",
)
EFFECT_EVENT_TYPES = ("VERIFICATION_COMPLETED", "REWORK")

# Single source of truth for Context capture authority.  Both extraction and
# downstream proxy logic call is_trusted_context_capture_event().
TRUSTED_CAPTURE_RULES: Dict[str, Dict[str, str | None]] = {
    "FACT": {"producer": "record-first", "operation": "CHECKPOINT"},
    "REVIEW_COMPLETED": {"producer": "review_record", "operation": None},
    "VERIFICATION_COMPLETED": {"producer": "record-first", "operation": "VERIFY"},
    "DELIVERY_RESULT": {"producer": "delivery_converge", "operation": None},
}
SOURCE_TYPES = ("wiki", "knowledge", "memory_project", "memory_skill")


def _parse_detail(raw: Any) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def is_trusted_context_capture_event(event_type: str, detail: dict[str, Any]) -> bool:
    rule = TRUSTED_CAPTURE_RULES.get(str(event_type or ""))
    if not rule:
        return False
    if str(detail.get("producer") or "") != str(rule["producer"]):
        return False
    expected_operation = rule.get("operation")
    if expected_operation is not None and str(detail.get("operation") or "") != expected_operation:
        return False
    return True


def fetch_context_event_rows(conn, *, project_id: str, since_iso: str) -> list[Any]:
    placeholders = ",".join("?" for _ in CONTEXT_EVENT_TYPES)
    return conn.execute(
        f"""
        SELECT
          e.id,
          e.task_id,
          e.event_type,
          e.from_stage,
          e.to_stage,
          e.actor_role,
          e.detail_json,
          e.created_at
        FROM task_event e
        JOIN task t ON t.task_id = e.task_id
        WHERE t.project_id = ?
          AND e.created_at >= ?
          AND e.event_type IN ({placeholders})
        ORDER BY e.id
        """,
        (project_id, since_iso, *CONTEXT_EVENT_TYPES),
    ).fetchall()


def fetch_effect_event_rows(conn, *, project_id: str, since_iso: str) -> list[Any]:
    placeholders = ",".join("?" for _ in EFFECT_EVENT_TYPES)
    return conn.execute(
        f"""
        SELECT e.id,e.task_id,e.event_type,e.actor_role,e.detail_json,e.created_at
        FROM task_event e
        JOIN task t ON t.task_id=e.task_id
        WHERE t.project_id=?
          AND e.created_at>=?
          AND e.event_type IN ({placeholders})
        ORDER BY e.id
        """,
        (project_id, since_iso, *EFFECT_EVENT_TYPES),
    ).fetchall()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def context_usage_records(rows: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        event_type = str(_row_value(row, "event_type", "") or "")
        detail = _parse_detail(_row_value(row, "detail_json", ""))
        if not is_trusted_context_capture_event(event_type, detail):
            continue
        usage = context_usage.extract_context_usage(_row_value(row, "detail_json", ""))
        workflow_stage = str(_row_value(row, "to_stage", "") or _row_value(row, "from_stage", "") or "")
        if not workflow_stage and event_type == "REVIEW_COMPLETED":
            kind = str(detail.get("review_kind") or "").upper()
            if kind == "ARCHITECTURE":
                workflow_stage = "architecture_review"
            elif kind == "VERIFICATION":
                # Kept for historical/future compatibility; current review actor
                # contract only exposes architecture review.
                workflow_stage = "verification"
        for item in usage:
            records.append({
                "event_id": int(_row_value(row, "id", 0) or 0),
                "task_id": str(_row_value(row, "task_id", "") or ""),
                "actor_role": str(_row_value(row, "actor_role", "") or ""),
                "workflow_stage": workflow_stage,
                "created_at": str(_row_value(row, "created_at", "") or ""),
                **item,
            })
    return records


def _empty_metric() -> dict[str, Any]:
    return {
        "retrieved": 0,
        "adopted": 0,
        "adoption_rate": 0.0,
        "unique_assets": 0,
        "stale": 0,
        "fallback": 0,
        "source_followup": {"none": 0, "targeted": 0, "broad": 0, "unknown": 0},
        "effective_proxy": {"positive": 0, "negative": 0, "unknown": 0},
    }


def _empty_asset(source_type: str, asset_id: str) -> dict[str, Any]:
    metric = _empty_metric()
    metric.pop("unique_assets", None)
    metric.pop("adoption_rate", None)
    return {"source_type": source_type, "asset_id": asset_id, **metric}


def _trusted_verification_decision(event: Any) -> str:
    if str(_row_value(event, "event_type", "") or "") != "VERIFICATION_COMPLETED":
        return ""
    if str(_row_value(event, "actor_role", "") or "") != "tp-test-engineer":
        return ""
    detail = _parse_detail(_row_value(event, "detail_json", ""))
    if not is_trusted_context_capture_event("VERIFICATION_COMPLETED", detail):
        return ""
    decision = str(detail.get("decision") or "").upper()
    return decision if decision in {"PASS", "FAIL", "NEEDS_FIX"} else ""


def _skill_proxy(record: dict[str, Any], events_by_task: dict[str, list[Any]]) -> str:
    if str(record.get("outcome") or "") == "stale":
        return "negative"
    if str(record.get("stage") or "") != "adopted":
        return "unknown"
    adopted_id = int(record.get("event_id") or 0)
    events = events_by_task.get(str(record.get("task_id") or ""), [])
    pass_event = None
    for event in events:
        event_id = int(_row_value(event, "id", 0) or 0)
        if event_id <= adopted_id:
            continue
        if _trusted_verification_decision(event) == "PASS":
            pass_event = event
            break
    if pass_event is None:
        return "unknown"
    pass_id = int(_row_value(pass_event, "id", 0) or 0)
    for event in events:
        event_id = int(_row_value(event, "id", 0) or 0)
        if not (adopted_id < event_id <= pass_id):
            continue
        if str(_row_value(event, "event_type", "") or "") == "REWORK":
            return "negative"
        if _trusted_verification_decision(event) in {"NEEDS_FIX", "FAIL"}:
            return "negative"
    return "positive"


def _effective_proxy(record: dict[str, Any], events_by_task: dict[str, list[Any]]) -> str:
    source_type = str(record.get("source_type") or "")
    stage = str(record.get("stage") or "")
    outcome = str(record.get("outcome") or "unknown")
    if outcome == "stale":
        return "negative"
    if source_type == "memory_skill":
        return _skill_proxy(record, events_by_task)
    if source_type == "knowledge":
        if stage != "adopted":
            return "unknown"
        if outcome == "success":
            return "positive"
        if outcome == "stale":
            return "negative"
        return "unknown"
    if source_type in {"wiki", "memory_project"}:
        if stage != "adopted":
            return "unknown"
        followup = str(record.get("source_followup") or "unknown")
        if followup in {"none", "targeted"}:
            return "positive"
        if followup == "broad":
            return "negative"
        return "unknown"
    return "unknown"


def aggregate_context_usage(
    records: Iterable[dict[str, Any]],
    task_events: Iterable[Any],
) -> dict[str, Any]:
    records = list(records)
    events_by_task: dict[str, list[Any]] = defaultdict(list)
    for event in task_events:
        events_by_task[str(_row_value(event, "task_id", "") or "")].append(event)
    for events in events_by_task.values():
        events.sort(key=lambda e: int(_row_value(e, "id", 0) or 0))

    sources = {source_type: _empty_metric() for source_type in SOURCE_TYPES}
    assets: dict[tuple[str, str], dict[str, Any]] = {}

    for record in records:
        source_type = str(record.get("source_type") or "")
        asset_id = str(record.get("asset_id") or "")
        if source_type not in sources or not asset_id:
            continue
        source = sources[source_type]
        key = (source_type, asset_id)
        asset = assets.setdefault(key, _empty_asset(source_type, asset_id))
        source["retrieved"] += 1
        asset["retrieved"] += 1
        if str(record.get("stage") or "") == "adopted":
            source["adopted"] += 1
            asset["adopted"] += 1
        outcome = str(record.get("outcome") or "unknown")
        if outcome == "stale":
            source["stale"] += 1
            asset["stale"] += 1
        if outcome == "fallback":
            source["fallback"] += 1
            asset["fallback"] += 1
        followup = str(record.get("source_followup") or "unknown")
        if followup not in source["source_followup"]:
            followup = "unknown"
        source["source_followup"][followup] += 1
        asset["source_followup"][followup] += 1
        proxy = _effective_proxy(record, events_by_task)
        source["effective_proxy"][proxy] += 1
        asset["effective_proxy"][proxy] += 1

    for source_type, source in sources.items():
        source["unique_assets"] = sum(1 for key in assets if key[0] == source_type)
        source["adoption_rate"] = (
            source["adopted"] / source["retrieved"] if source["retrieved"] else 0.0
        )

    asset_rows = [assets[key] for key in sorted(assets)]
    candidates: list[dict[str, Any]] = []
    for asset in asset_rows:
        if asset["stale"] > 0:
            candidates.append({
                "source_type": asset["source_type"], "asset_id": asset["asset_id"],
                "reason": "stale", "retrieved": asset["retrieved"], "adopted": asset["adopted"],
            })
        if asset["retrieved"] >= 3 and asset["adopted"] == 0:
            candidates.append({
                "source_type": asset["source_type"], "asset_id": asset["asset_id"],
                "reason": "repeated-never-adopted", "retrieved": asset["retrieved"], "adopted": 0,
            })
        if asset["source_followup"]["broad"] >= 2:
            candidates.append({
                "source_type": asset["source_type"], "asset_id": asset["asset_id"],
                "reason": "broad-followup", "retrieved": asset["retrieved"], "adopted": asset["adopted"],
            })
    candidates.sort(key=lambda x: (x["reason"], x["source_type"], x["asset_id"]))
    return {
        "sources": sources,
        "assets": asset_rows,
        "candidates": candidates,
        "limitations": [
            "Knowledge retrieval_runs has no project_id/task_id; central retrieval telemetry is not attributed to this project.",
            "Legacy VERIFICATION_COMPLETED events produced by commit are intentionally excluded from the V5.2.6 P0 effectiveness proxy.",
        ],
    }


def build_context_effectiveness_report(
    conn,
    *,
    project_id: str,
    days: int,
    since_iso: str,
    until_iso: str,
) -> dict[str, Any]:
    project = conn.execute("SELECT project_id FROM project WHERE project_id=?", (project_id,)).fetchone()
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    capture_rows = fetch_context_event_rows(conn, project_id=project_id, since_iso=since_iso)
    effect_rows = fetch_effect_event_rows(conn, project_id=project_id, since_iso=since_iso)
    records = context_usage_records(capture_rows)
    aggregated = aggregate_context_usage(records, effect_rows)
    return {
        "schema": "tp-spec.context-effectiveness/v1",
        "project_id": project_id,
        "days": int(days),
        "window": {"since": since_iso, "until": until_iso},
        "events_scanned": len(capture_rows),
        "usage_records": len(records),
        **aggregated,
    }
