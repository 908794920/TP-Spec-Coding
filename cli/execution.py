# -*- coding: utf-8 -*-
"""Versioned execution facts, projected from the existing task_event ledger.

A recorded step completion is history, not a Verification/Review/Delivery PASS.
No plan, participation, role name or scope reference grants execution authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "tp-spec.execution/v1"
PLAN = "EXECUTION_PLAN_RECORDED"
STEP = "EXECUTION_STEP_RECORDED"
SESSION_EVENTS = {"WORK_SESSION_STARTED", "WORK_SESSION_UPDATED", "WORK_SESSION_ENDED"}
TERMINAL = {"COMPLETED", "CANCELLED"}
STEP_ACTIONS = {"start": "ACTIVE", "wait": "WAITING", "resume": "ACTIVE", "complete": "COMPLETED"}


def detail_of(row) -> dict:
    try:
        value = json.loads(dict(row).get("detail_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def read_events(conn, task_id: str) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,))]


def _trusted(row: dict, detail: dict, producer: str) -> bool:
    """Validate a registered writer's identity fields, not cryptographic human identity."""
    from . import event_policies, event_contract
    return (not event_contract.validate_event_semantics(row.get("event_type"), detail)
            and detail.get("execution_schema") == SCHEMA
            and event_policies.event_allowed_for_producer(row.get("event_type"), producer)
            and detail.get("producer") == producer
            and all(detail.get(key) for key in ("transaction_id", "schema_version", "task_id", "actor_role", "created_at"))
            and all(detail.get(key) == row.get(key) for key in ("task_id", "actor_role", "created_at")))


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value) -> bool:
    return isinstance(value, list) and all(_nonempty(item) for item in value) and len(set(value)) == len(value)


def _valid_plan(body) -> bool:
    if not isinstance(body, dict) or body.get("effect_scope") != "record_only":
        return False
    coordinator, assessment = body.get("coordinator"), body.get("assessment")
    if (not isinstance(coordinator, dict) or not _nonempty(coordinator.get("role"))
            or not isinstance(coordinator.get("agent"), str) or not isinstance(assessment, dict)
            or not _nonempty(assessment.get("summary")) or not _string_list(assessment.get("source_refs"))
            or not assessment["source_refs"] or not isinstance(assessment.get("omissions"), dict)
            or not all(key in {"verification", "review"} and _nonempty(value) for key, value in assessment["omissions"].items())
            or body.get("effective_level") not in ("L0", "L1", "L2", "L3")
            or not _nonempty(body.get("reason")) or not _string_list(body.get("scope_refs")) or not body["scope_refs"]
            or not isinstance(body.get("steps"), list) or not body["steps"]):
        return False
    seen = set()
    for step in body["steps"]:
        if (not isinstance(step, dict) or not _nonempty(step.get("id"))
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", step["id"]) or step["id"] in seen
                or not all(_nonempty(step.get(field)) for field in ("title", "phase", "scope"))
                or not all(_string_list(step.get(field)) for field in ("roles", "depends_on", "work_item_ids"))
                or not step["roles"] or set(step["depends_on"]) - seen):
            return False
        try:
            from .security_authority import step_context
            step_context(step)
        except ValueError:
            return False
        seen.add(step["id"])
    return True


def _valid_boundary(detail) -> bool:
    return (all(_string_list(detail.get(field, [])) for field in ("findings", "decisions", "evidence_refs", "waiting_work_items"))
            and all(isinstance(detail.get(field, ""), str) for field in ("result", "scope", "wait_reason", "expected_next_actor")))


def _step_view(step: dict) -> dict:
    return {**step, "status": "PLANNED", "started_at": None, "completed_at": None,
            "last_recorded_at": None, "last_event_id": None, "wait_reason": "",
            "expected_next_actor": "", "waiting_work_items": [], "summary": "",
            "evidence_refs": [], "history_event_ids": [], "participation_ids": []}


def _activity(row: dict, detail: dict) -> dict:
    return {"event_id": row["id"], "created_at": row.get("created_at"),
            "event_type": row.get("event_type"), "action": detail.get("action") or detail.get("reason") or "start",
            "plan_version": detail.get("plan_version"), "step_id": detail.get("step_id"),
            "participation_id": detail.get("session_id"), "actor": row.get("actor_role"),
            "actor_agent": row.get("actor_agent"), "work_item_id": row.get("work_item_id"),
            "summary": row.get("summary") or "", "result": detail.get("result") or "",
            "findings": detail.get("findings") or [], "decisions": detail.get("decisions") or [],
            "evidence_refs": detail.get("evidence_refs") or [], "wait_reason": detail.get("wait_reason") or "",
            "expected_next_actor": detail.get("expected_next_actor") or ""}


def project_execution(task, rows, *, retired: bool = False) -> dict:
    """Deterministic replay, shared by CLI, workflow recovery and the read-only UI.

    Invalid new facts are reported, not silently interpreted as legacy records.
    Time is never synthesized from the task creation time or the last actor.
    """
    from .work_session_cmd import _session_time
    task = dict(task)
    rows = list(rows)
    from .work_units import project_units
    scoped_work = project_units(rows)
    plan, version = None, 0
    steps: dict[str, dict] = {}
    participations: dict[str, dict] = {}
    history, activities, issues, legacy, legacy_issues = [], [], [], [], []
    for raw in rows:
        row = dict(raw)
        if row.get("task_id") != task.get("task_id"):
            continue
        kind, detail = row.get("event_type"), detail_of(row)
        if kind not in {PLAN, STEP} | SESSION_EVENTS:
            continue
        if kind in SESSION_EVENTS and "execution_schema" not in detail:
            from .work_session_cmd import _event_detail
            if _event_detail(row) is None or kind == "WORK_SESSION_UPDATED":
                # Old unscoped damage stays a historical diagnostic, not a new closeout duty.
                # After adoption, an unreadable participation cannot masquerade as legacy.
                target = issues if plan is not None or kind == "WORK_SESSION_UPDATED" else legacy_issues
                target.append(f"PARTICIPATION_METADATA_INVALID:{row['id']}")
            legacy.append(row["id"])
            continue
        producer = "execution" if kind in {PLAN, STEP} else "work_session"
        if not _trusted(row, detail, producer):
            issues.append(f"EXECUTION_EVENT_INVALID:{row['id']}")
            continue
        if kind == PLAN:
            body = detail.get("plan")
            try:
                if (not _valid_plan(body) or type(detail.get("plan_version")) is not int
                        or detail["plan_version"] != version + 1 or digest(body) != detail.get("plan_digest")
                        or not isinstance(body.get("steps"), list) or not body["steps"]):
                    raise ValueError("invalid plan chain")
                definitions = body["steps"]
                ids = [item["id"] for item in definitions]
                if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
                    raise ValueError("invalid step identities")
                if not isinstance(body.get("coordinator"), dict):
                    raise ValueError("invalid coordinator")
                # A revision may change future work, never rewrite the meaning of begun work.
                begun = [key for key, value in steps.items() if value["status"] != "PLANNED"]
                for key in begun:
                    old = next(item for item in plan["steps"] if item["id"] == key)
                    if key not in ids or definitions[ids.index(key)] != old or ids.index(key) != list(steps).index(key):
                        raise ValueError("started history changed")
                steps = {item["id"]: steps[item["id"]] if item["id"] in begun else _step_view(item)
                         for item in definitions}
            except (ValueError, KeyError, TypeError):
                issues.append(f"EXECUTION_PLAN_INVALID:{row['id']}")
                continue
            plan, version = body, detail["plan_version"]
            history.append({"version": version, "event_id": row["id"], "created_at": row.get("created_at"),
                            "reason": body.get("reason"), "scope_refs": body.get("scope_refs"),
                            "assessment": body.get("assessment"), "plan_digest": detail["plan_digest"]})
            continue
        step_id = detail.get("step_id")
        if not _valid_boundary(detail) or not isinstance(step_id, str) or step_id not in steps or type(detail.get("plan_version")) is not int or not 1 <= detail["plan_version"] <= version:
            issues.append(f"EXECUTION_STEP_BINDING_INVALID:{row['id']}")
            continue
        step = steps[step_id]
        if kind == STEP:
            action = detail.get("action")
            allowed = {"PLANNED": {"start"}, "ACTIVE": {"wait", "complete"}, "WAITING": {"resume"}}
            if (detail["plan_version"] != version or not isinstance(action, str)
                    or action not in allowed.get(step["status"], set())
                    or row.get("actor_role") not in set(step["roles"]) | {plan["coordinator"]["role"]}
                    or (action == "wait" and not (detail.get("wait_reason") and detail.get("expected_next_actor")))
                    or (action == "complete" and any(p["step_id"] == step_id and p["ended_at"] is None for p in participations.values()))):
                issues.append(f"EXECUTION_STEP_TRANSITION_INVALID:{row['id']}")
                continue
            if action == "start" and step_id != next((key for key, value in steps.items() if value["status"] != "COMPLETED"), None):
                issues.append(f"EXECUTION_STEP_ORDER_INVALID:{row['id']}")
                continue
            step.update(status=STEP_ACTIONS[action], last_recorded_at=row.get("created_at"), last_event_id=row["id"],
                        summary=row.get("summary") or "", wait_reason=detail.get("wait_reason") or "",
                        expected_next_actor=detail.get("expected_next_actor") or "",
                        waiting_work_items=detail.get("waiting_work_items") or [], evidence_refs=detail.get("evidence_refs") or [])
            if action == "start":
                step["started_at"] = row.get("created_at")
            if action == "complete":
                step["completed_at"] = row.get("created_at")
            step["history_event_ids"].append(row["id"])
            activities.append(_activity(row, detail))
            continue
        sid = detail.get("session_id")
        if not isinstance(sid, str) or not sid:
            issues.append(f"PARTICIPATION_ID_MISSING:{row['id']}")
            continue
        if kind == "WORK_SESSION_STARTED":
            unit = scoped_work["units"].get(row.get("work_item_id"))
            linked = bool(unit and unit["create_event_id"] < row["id"] and (
                unit["spec"]["step_id"] == step_id or any(h.get("action") == "retry" and h.get("step_id") == step_id
                    and h["event_id"] < row["id"] for h in unit["history"])))
            fix = linked and unit["spec"].get("kind") == "FIX"
            allowed_roles = unit["spec"]["roles"] if linked else step["roles"]
            if (sid in participations or step["status"] not in ({"ACTIVE", "WAITING"} if fix else {"ACTIVE"})
                    or detail["plan_version"] != version or row.get("actor_role") not in allowed_roles
                    or (row.get("work_item_id") and row["work_item_id"] not in step["work_item_ids"] and not linked)):
                issues.append(f"PARTICIPATION_START_INVALID:{row['id']}")
                continue
            participation = {"participation_id": sid, "session_id": sid, "plan_version": detail["plan_version"],
                "step_id": step_id, "role": row.get("actor_role"), "agent": row.get("actor_agent") or "",
                "work_item_id": row.get("work_item_id"), "scope": detail.get("scope") or step.get("scope") or "",
                "started_at": row.get("created_at"), "ended_at": None, "duration_seconds": None,
                "status": "ACTIVE", "runtime_status": "UNKNOWN", "start_event_id": row["id"],
                "last_event_id": row["id"], "history": [], "result": "", "findings": [],
                "decisions": [], "evidence_refs": [], "wait_reason": "", "expected_next_actor": ""}
            participations[sid] = participation
            step["participation_ids"].append(sid)
        else:
            participation = participations.get(sid)
            if (participation is None or participation["ended_at"] is not None
                    or participation["step_id"] != step_id or detail["plan_version"] != participation["plan_version"]
                    or detail.get("start_event_id") != participation["start_event_id"]
                    or participation["role"] != row.get("actor_role")
                    or participation["agent"] != (row.get("actor_agent") or "")
                    or participation["work_item_id"] != row.get("work_item_id")):
                issues.append(f"PARTICIPATION_BINDING_INVALID:{row['id']}")
                continue
            if kind == "WORK_SESSION_UPDATED":
                action = detail.get("action")
                if ((action == "wait" and participation["status"] != "ACTIVE")
                        or (action == "resume" and participation["status"] != "WAITING")
                        or action not in ("wait", "resume")
                        or (action == "resume" and step["status"] != "ACTIVE" and not (
                            step["status"] == "WAITING" and scoped_work["units"].get(row.get("work_item_id"), {}).get("spec", {}).get("kind") == "FIX"))
                        or (action == "wait" and not (detail.get("wait_reason") and detail.get("expected_next_actor")))):
                    issues.append(f"PARTICIPATION_TRANSITION_INVALID:{row['id']}")
                    continue
                participation["status"] = "WAITING" if action == "wait" else "ACTIVE"
            else:
                reason = detail.get("reason")
                from .work_session_cmd import _REASON_CODES
                if not isinstance(reason, str) or reason not in _REASON_CODES:
                    issues.append(f"PARTICIPATION_END_INVALID:{row['id']}")
                    continue
                participation["status"] = str(reason).upper()
                participation["ended_at"] = row.get("created_at")
                start, end = _session_time(participation["started_at"]), _session_time(participation["ended_at"])
                if start is not None and end is not None and end >= start:
                    participation["duration_seconds"] = (end - start).total_seconds()
        activity = _activity(row, detail)
        participation.update(last_event_id=row["id"], last_recorded_at=row.get("created_at"),
                             summary=row.get("summary") or "")
        for field in ("result", "findings", "decisions", "evidence_refs", "wait_reason", "expected_next_actor"):
            # Keep earlier findings/results when a later resume carries no replacement.
            if detail.get(field):
                if isinstance(participation[field], list):
                    participation[field] = list(dict.fromkeys(participation[field] + detail[field]))
                else:
                    participation[field] = detail[field]
        if kind == "WORK_SESSION_UPDATED" and detail.get("action") == "resume":
            participation["wait_reason"] = ""
            participation["expected_next_actor"] = ""
        elif kind == "WORK_SESSION_ENDED":
            # An old wait remains in history, not as a current blocker after completion.
            participation["wait_reason"] = detail.get("wait_reason") or ""
            participation["expected_next_actor"] = detail.get("expected_next_actor") or ""
        participation["history"].append(activity)
        activities.append(activity)

    for step in steps.values():
        linked = [u for u in scoped_work["units"].values() if step["id"] in
                  {u["spec"]["step_id"], u["waiting_step_id"], *(h.get("step_id") for h in u["history"])}]
        step["linked_work_items"] = [u["item_id"] for u in linked]
        step["fix_work_items"] = [u["item_id"] for u in linked if u["spec"]["kind"] == "FIX"]
        if step["status"] == "WAITING":
            current_fixes = [u["item_id"] for u in linked if u["spec"]["kind"] == "FIX"
                             and u["waiting_step_id"] == step["id"] and not u["receipt"]]
            step["waiting_work_items"] = list(dict.fromkeys(step["waiting_work_items"] + current_fixes))
    terminal = retired or task.get("current_state") in TERMINAL
    current = next((item for item in steps.values() if item["status"] in {"ACTIVE", "WAITING"}), None)
    next_step = next((item for item in steps.values() if item["status"] == "PLANNED"), None)
    current_participations = [p for p in participations.values() if p["ended_at"] is None
                              and current and p["step_id"] == current["id"]]
    for participation in participations.values():
        participation["current"] = not terminal and participation in current_participations
        participation["time_status"] = "RECORDED" if participation["duration_seconds"] is not None else "UNKNOWN"
    if terminal:
        current, next_step = None, None
    latest_record = max([*activities, *history], key=lambda item: item.get("event_id", 0), default={})
    return {"schema": SCHEMA, "status": "INVALID" if issues else "RECORDED" if plan else "NOT_RECORDED",
            "source": "task_event", "plan_version": version, "plan": plan, "plan_history": history,
            "coordinator": (plan or {}).get("coordinator"), "terminal": terminal,
            "current_step": current, "next_step": next_step, "steps": list(steps.values()),
            "participations": list(participations.values()), "timeline": activities,
            "current_roles": [] if terminal else list(dict.fromkeys(p["role"] for p in current_participations)),
            "last_recorded_at": latest_record.get("created_at"),
            "issues": issues, "legacy_event_ids": legacy, "legacy_issues": legacy_issues,
            "note": "步骤完成是发生历史，不是质量门禁通过；未结束参与不证明 Agent 在线。"}


def read_execution(conn, task, *, rows=None, retired=False) -> dict:
    return project_execution(task, rows if rows is not None else read_events(conn, task["task_id"]), retired=retired)


def recorded_coordinator(conn, task) -> dict | None:
    """Absence preserves legacy owner semantics; a valid explicit plan opts in."""
    facts = read_execution(conn, task)
    return facts.get("coordinator")


def completion_blockers(conn, task) -> list[str]:
    """Adopted plans must close their actual records; no retroactive duty for legacy tasks."""
    facts = read_execution(conn, task)
    if facts["issues"]:
        return ["EXECUTION_FACTS_INVALID: " + "; ".join(facts["issues"])]
    if facts["plan"] is None:
        return []
    pending = [step["id"] for step in facts["steps"] if step["status"] != "COMPLETED"]
    opened = [p["participation_id"] for p in facts["participations"] if p["ended_at"] is None]
    return (["EXECUTION_STEPS_PENDING: " + ", ".join(pending)] if pending else []) + (
        ["EXECUTION_PARTICIPATIONS_OPEN: " + ", ".join(opened)] if opened else [])


def progress_view(facts: dict, *, effective_level: str, role_map: dict, route: dict | None = None) -> dict:
    from .orchestration import _role_display
    def present(item):
        if not item:
            return {}
        roles = item.get("roles") or []
        return {**item, "stage": item["id"], "stage_display": {"label": item["title"], "configured": True, "source": "execution_plan"},
                "role": roles[0] if roles else "", "role_display": _role_display(role_map, roles[0] if roles else ""),
                "definition_source": "execution_plan", "completion_source": "execution_step" if item["status"] == "COMPLETED" else ""}
    return {"effective_level": effective_level, "execution": facts,
            "steps": [present(item) for item in facts["steps"]],
            "completed_steps": [present(item) for item in facts["steps"] if item["status"] == "COMPLETED"],
            "current_step": present(facts["current_step"]), "next_step": present(facts["next_step"]),
            "current_step_source": "task_event.execution" if facts["current_step"] else "none",
            "next_step_source": "execution_plan" if facts["next_step"] else "none",
            "route": route or {}, "conditional_roles": [], "reference_steps": []}
