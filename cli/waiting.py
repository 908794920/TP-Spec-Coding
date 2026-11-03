# -*- coding: utf-8 -*-
"""Typed waiting facts over the existing BLOCK/RESUME ledger, not a scheduler.

Summaries are display text only. Dependency completion is read from this Runtime;
external/environmental recovery requires new evidence, and owner-controlled waits
require an explicit human_owner resolution. None of these actions records PASS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from . import event_contract
from .evidence import validate_evidence_path

KINDS = ("unspecified", "human_acceptance", "permission", "environment", "dependency")
_OWNER_KINDS = {"human_acceptance", "permission"}


def active_wait(events: Iterable, state: str, *, actors: Iterable[str] | None = None) -> dict[str, Any]:
    if state != "BLOCKED":
        return {}
    for raw in reversed(list(events)):
        row = dict(raw)
        if row.get("event_type") != "STATE":
            continue
        try:
            detail = json.loads(row.get("detail_json") or "{}")
        except (TypeError, ValueError):
            raise ValueError("WAIT_FACT_INVALID: malformed latest state detail")
        if row.get("to_state") != "BLOCKED":
            return {}
        if not isinstance(detail, dict):
            raise ValueError("WAIT_FACT_INVALID: state detail must be an object")
        if "waiting" not in detail:
            return {}  # Legacy free text is never guessed into a new condition.
        if detail.get("producer") != "record-first" or not detail.get("transaction_id") or detail.get("schema") != event_contract.EVENT_SCHEMA:
            raise ValueError("WAIT_FACT_INVALID: typed wait has no trusted BLOCK identity")
        wait = detail["waiting"]
        from .role_registry import actor_ids
        if (not isinstance(wait, dict) or wait.get("kind") not in KINDS[1:]
                or wait.get("responsibility") not in (actor_ids() if actors is None else actors)
                or not isinstance(wait.get("condition"), str) or not wait["condition"].strip()):
            raise ValueError("WAIT_FACT_INVALID: malformed waiting fields")
        if wait["kind"] in _OWNER_KINDS and wait["responsibility"] != "human_owner":
            raise ValueError("WAIT_FACT_INVALID: owner-controlled wait lost its owner")
        deps = wait.get("requires_tasks")
        proof = wait.get("prerequisite_evidence")
        if (not isinstance(deps, list) or any(not isinstance(dep, str) or not dep.strip() for dep in deps)
                or (wait["kind"] == "dependency") != bool(deps)):
            raise ValueError("WAIT_FACT_INVALID: malformed dependency condition")
        if not isinstance(proof, list) or any(
            not isinstance(item, dict) or item.get("type") != "local_file"
            or not isinstance(item.get("path"), str) or not item["path"].startswith("evidence/")
            or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            for item in proof
        ):
            raise ValueError("WAIT_FACT_INVALID: malformed prerequisite evidence identity")
        return {**wait, "block_event_id": int(row["id"])}
    return {}


def load_wait(conn, task_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"dependency task not found: {task_id}")
    events = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='STATE' ORDER BY id", (task_id,)).fetchall()
    return active_wait(events, str(row["current_state"] or ""))


def _evidence(task_dir: Path, values: Iterable[str] | None) -> list[dict]:
    items = []
    for path in values or []:
        checked = validate_evidence_path(task_dir, path, require_evidence_dir=True)
        if not checked.ok:
            raise ValueError(f"WAIT_EVIDENCE_INVALID: {checked.error}")
        if checked.item not in items:
            items.append(checked.item)
    return items


def build_wait(conn, task, task_dir: Path, *, kind: str | None, responsibility: str | None,
               condition: str | None, requires_tasks: Iterable[str] | None,
               prerequisite_evidence: Iterable[str] | None) -> dict[str, Any]:
    kind = kind or "unspecified"
    deps = sorted(set(str(value).strip() for value in requires_tasks or [] if str(value).strip()))
    if kind == "unspecified":
        if responsibility or condition or deps or prerequisite_evidence:
            raise ValueError("WAIT_KIND_REQUIRED: typed conditions require --kind")
        return {}
    if kind not in KINDS:
        raise ValueError(f"unknown waiting kind: {kind}")
    from .role_registry import actor_ids
    owner = responsibility or ("human_owner" if kind in _OWNER_KINDS else str(task["owner_role"] or "tp-test-engineer"))
    if owner not in actor_ids():
        raise ValueError("invalid waiting responsibility")
    if kind in _OWNER_KINDS and owner != "human_owner":
        raise ValueError("OWNER_RESOLUTION_REQUIRED: owner-controlled wait must name human_owner")
    if kind == "dependency":
        if not deps:
            raise ValueError("DEPENDENCY_REQUIRED: provide --requires-task")
        # Follow only declared active edges. Do not infer dependencies from names.
        def visit(node: str, path: set[str]) -> None:
            if node in path:
                raise ValueError("DEPENDENCY_CYCLE")
            row = conn.execute("SELECT project_id FROM task WHERE task_id=?", (node,)).fetchone()
            if row is None or row["project_id"] != task["project_id"]:
                raise ValueError(f"DEPENDENCY_NOT_BOUND: {node}")
            for child in load_wait(conn, node).get("requires_tasks") or []:
                visit(str(child), path | {node})
        for dep in deps:
            visit(dep, {str(task["task_id"])})
    elif deps:
        raise ValueError("--requires-task is only valid for dependency waits")
    condition = str(condition or ("all declared dependency tasks are COMPLETED" if kind == "dependency" else "")).strip()
    if not condition:
        raise ValueError("WAIT_CONDITION_REQUIRED")
    return {
        "kind": kind, "responsibility": owner, "condition": condition,
        "requires_tasks": deps,
        "prerequisite_evidence": _evidence(task_dir, prerequisite_evidence),
    }


def validate_resolution(conn, task_id: str, task_dir: Path, *, actor: str,
                        resolution_evidence: Iterable[str] | None) -> dict[str, Any]:
    wait = load_wait(conn, task_id)
    if not wait:
        legacy = pending_legacy_confirmation(conn, task_id)
        if legacy:
            from .workflow_controls import find_matching_confirmation
            events = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
            confirmation = find_matching_confirmation([dict(row) for row in events], legacy["confirmation_binding"])
            if confirmation is None:
                raise ValueError("WORKFLOW_CONFIRMATION_REQUIRED: confirm the active historical boundary before resume")
            return {"kind": "legacy_confirmation", "block_event_id": legacy["block_event_id"],
                    "confirmation_event_id": int(confirmation["id"])}
        if resolution_evidence:
            raise ValueError("untyped legacy wait does not accept a typed resolution")
        return {}
    if wait["kind"] in _OWNER_KINDS and actor != "human_owner":
        raise ValueError("OWNER_RESOLUTION_REQUIRED")
    if wait["kind"] == "dependency":
        for task in wait.get("requires_tasks") or []:
            row = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task,)).fetchone()
            if row is None or row["current_state"] != "COMPLETED":
                raise ValueError(f"DEPENDENCY_NOT_COMPLETE: {task}")
        items = _evidence(task_dir, resolution_evidence)
    else:
        items = _evidence(task_dir, resolution_evidence)
        if not items:
            raise ValueError("RESOLUTION_EVIDENCE_REQUIRED")
        if wait["kind"] == "environment":
            previous = {item["sha256"] for item in wait.get("prerequisite_evidence") or []}
            if {item["sha256"] for item in items}.issubset(previous):
                raise ValueError("PREREQUISITE_UNCHANGED: do not repeat the same failed prerequisite")
    return {"block_event_id": wait["block_event_id"], "kind": wait["kind"], "evidence": items}


def _result_resolved(conn, task_id: str, events: list[dict], result, stage: str,
                     task_dir: Path | None) -> bool:
    """A new subject or a typed, same-stage resolution permits reevaluation only."""
    from . import event_policies
    from .record_first import _latest_development_change_set

    result_id, detail = int(result.row["id"]), result.detail
    owner_required = (str(detail.get("blocker_kind") or "").upper() == "HUMAN_DECISION"
                      or detail.get("responsibility") == "human_owner")
    phase = "review" if stage == "architecture_review" else stage
    # Generic/legacy resume text is not evidence that a professional prerequisite
    # was solved. Bind the existing typed resolution to the actual preceding BLOCK.
    states = event_policies.load_trusted_governance_events(conn, task_id, event_type="STATE")
    by_id = {int(event["id"]): event for event in events}
    for state in states:
        row, resolution = state.row, state.detail.get("resolution")
        if (int(row["id"]) <= result_id or state.detail.get("operation") != "RESUME"
                or row["from_state"] != "BLOCKED" or row["to_state"] != "ACTIVE"
                or not isinstance(resolution, dict)):
            continue
        block_id = resolution.get("block_event_id")
        if not isinstance(block_id, int) or not result_id < block_id < int(row["id"]):
            continue
        block = by_id.get(block_id)
        if (not block or block.get("event_type") != "STATE" or block.get("to_state") != "BLOCKED"
                or block.get("to_stage") != phase or row["from_stage"] != phase):
            continue
        prior_states = [event for event in events if event.get("event_type") == "STATE"
                        and int(event["id"]) < int(row["id"])]
        wait = active_wait(prior_states, "BLOCKED")
        if wait.get("block_event_id") != block_id or resolution.get("kind") != wait.get("kind"):
            continue
        if (owner_required or wait["kind"] in _OWNER_KINDS) and (
                wait["kind"] not in _OWNER_KINDS or row["actor_role"] != "human_owner"):
            continue
        proof = resolution.get("evidence")
        if not isinstance(proof, list) or (wait["kind"] != "dependency" and not proof):
            continue
        if task_dir is None:
            continue
        valid = True
        for item in proof:
            if not isinstance(item, dict):
                valid = False
                break
            checked = validate_evidence_path(task_dir, item, require_evidence_dir=True)
            if not checked.ok or checked.sha256 != item.get("sha256"):
                valid = False
                break
        if not valid:
            continue
        if wait["kind"] == "dependency" and any(
            (conn.execute("SELECT current_state FROM task WHERE task_id=?", (dep,)).fetchone() or [None])[0] != "COMPLETED"
            for dep in wait["requires_tasks"]
        ):
            continue
        if wait["kind"] == "environment" and {item["sha256"] for item in proof}.issubset(
                {item["sha256"] for item in wait["prerequisite_evidence"]}):
            continue
        return True
    # A later checkpoint of identical content is not a retry trigger; event ids,
    # summary edits and incidental documents cannot discharge an owner decision.
    if not owner_required and stage != "architecture_review":
        development = _latest_development_change_set(conn, task_id)
        if (development and development["event_id"] > result_id and development["repo_roots"]
                and detail.get("change_set_id") and development["change_set_id"]
                and development["change_set_id"] != detail["change_set_id"]):
            return True
    if not owner_required and task_dir is not None:
        from .digest import compute_architecture_subject_digest, compute_verification_subject_digest
        if stage == "architecture_review":
            try:
                current_subject = compute_architecture_subject_digest(
                    task_dir, design_inputs=detail.get("design_inputs"))
            except (OSError, UnicodeError, ValueError, TypeError):
                return False  # 读取失败不是新的有效设计；保留等待并诊断来源。
            return bool(detail.get("subject_digest") and detail["subject_digest"] != current_subject)
        current_subject = compute_verification_subject_digest(
            task_dir, scope=detail.get("verification_scope", "full")
        )
        original_subject = detail.get("subject_digest") or detail.get("verification_subject_digest")
        if original_subject and original_subject != current_subject:
            return True
        verified = event_policies.load_trusted_governance_events(
            conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer",
        )
        original = next((item for item in verified
                         if int(item.row["id"]) == detail.get("verification_event_id")), None)
        current = event_policies.load_trusted_governance_event(
            conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer",
            evidence_dir=task_dir, latest_only=True,
        )
        if current and not event_policies.verification_subject_matches(current.detail, task_dir):
            current = None
        if original and current and int(current.row["id"]) > result_id:
            def identity(fact):
                return (fact.get("decision"), fact.get("change_set_id"), fact.get("subject_digest"),
                        fact.get("verification_scope", "full"),
                        sorted({item.get("sha256") for item in fact.get("evidence_items") or []
                                if isinstance(item, dict) and item.get("sha256")}))
            # Re-recording the same PASS or copying/renaming the same bytes is not
            # a new prerequisite. Actual new evidence/failure reopens evaluation.
            return identity(current.detail) != identity(original.detail)
    return False


def result_wait(conn, task_id: str, events: Iterable, *, task_dir: Path | None = None) -> dict[str, Any]:
    """Project an unresolved professional BLOCKED result without inventing a defect.

    No state/event is written. Review aliases share one lane; a later result in
    that lane supersedes the earlier one. Free text is displayed, never used to
    infer permission, completion or a recovery trigger.
    """
    from . import event_policies

    # A BLOCKED review may have no inspection evidence yet. Keep the registered
    # identity/artifact/subject requirements, but do not demand PASS evidence to
    # display a wait. This reader never grants a review or delivery PASS.
    fields = tuple(key for key in event_policies.EVENT_POLICIES["REVIEW_COMPLETED"]["required_fields"] if key != "evidence")
    candidates = event_policies.load_trusted_governance_events(
        conn, task_id, event_type="REVIEW_COMPLETED", detail_required=fields,
    )
    candidates += event_policies.load_trusted_governance_events(conn, task_id, event_type="DELIVERY_RESULT")
    candidates.sort(key=lambda item: int(item.row["id"]), reverse=True)
    if task_dir is None and candidates:
        project = conn.execute(
            "SELECT p.root_path FROM task t JOIN project p ON p.project_id=t.project_id WHERE t.task_id=?",
            (task_id,),
        ).fetchone()
        if project and project["root_path"]:
            task_dir = Path(project["root_path"]) / ".tp-spec" / "tasks" / task_id
    facts = [dict(event) for event in events]
    seen: set[str] = set()
    for candidate in candidates:
        row, detail = dict(candidate.row), candidate.detail
        event_type, actor = row.get("event_type"), row.get("actor_role")
        if event_type == "REVIEW_COMPLETED" and actor in {"tp-code-reviewer", "tp-software-architect"}:
            lane = str(actor)
        elif event_type == "DELIVERY_RESULT" and actor == "tp-integration-engineer":
            lane = "delivery"
        else:
            continue
        if lane in seen:
            continue
        if event_type == "REVIEW_COMPLETED":
            kind = str(detail.get("review_kind") or "").upper()
            expected = {"ARCHITECTURE"} if actor == "tp-software-architect" else {"CODE", "IMPLEMENTATION", "ULTRA_REVIEW"}
            if kind not in expected:
                continue
        status = str(detail.get("delivery_status") if lane == "delivery" else detail.get("decision") or "").upper()
        if lane != "delivery" and status != "BLOCKED" and not detail.get("evidence"):
            continue
        seen.add(lane)
        if lane != "delivery" and task_dir is not None:
            from . import security_authority as authority
            try:
                if not authority.formal_record_current(authority.read(conn, task_id, task_dir), task_dir, detail):
                    continue
            except (ValueError, OSError, KeyError, TypeError):
                continue
        if status != "BLOCKED":
            continue
        stage = "delivery" if lane == "delivery" else ("architecture_review" if actor == "tp-software-architect" else "review")
        if _result_resolved(conn, task_id, facts, candidate, stage, task_dir):
            continue
        return {
            "kind": str(detail.get("blocker_kind") or "review_prerequisite"),
            "responsibility": str(detail.get("responsibility") or actor),
            "condition": str(detail.get("recovery_condition") or
                "具体恢复条件尚未结构化记录；由原审查者核实前置，以 task block/resume 留存解决证据，或记录新的实际审查结论。"),
            "requires_tasks": [],
            "reason": str(detail.get("reason") or detail.get("summary") or row.get("summary") or "BLOCKED"),
            "source_event_id": int(row["id"]),
            "source_stage": stage,
            "reason_code": "DELIVERY_BLOCKED" if lane == "delivery" else "REVIEW_BLOCKED",
        }
    return {}


def _legacy_detail(event: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(event.get("detail_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def pending_legacy_confirmation(conn, task_id: str) -> dict[str, Any] | None:
    """Read a paired historical confirmation wait; never starts an executor."""
    task = conn.execute('SELECT current_state FROM task WHERE task_id=?', (task_id,)).fetchone()
    if task is None or task['current_state'] != 'BLOCKED':
        return None
    latest_state = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='STATE' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    if latest_state is None or latest_state['to_state'] != 'BLOCKED':
        return None
    state_detail = _legacy_detail(dict(latest_state))
    rows = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='BLOCKER' ORDER BY id DESC LIMIT 1", (task_id,)).fetchall()
    for row in rows:
        event = dict(row); detail = _legacy_detail(event)
        if (detail == state_detail and detail.get('producer') == 'autonomy'
                and detail.get('transaction_id') and detail.get('flush_id')
                and detail.get('task_id') == task_id and detail.get('schema_version') == event['workflow_version']
                and detail.get("operation") == "AUTONOMY_BOUNDARY" and detail.get("waiting_reason") == "awaiting_human_confirmation"):
            binding = detail.get("confirmation_binding")
            if isinstance(binding, dict) and binding:
                return {"event": event, "block_event_id": int(latest_state["id"]), **detail}
    return None


def retired_confirmation_resolution(conn, task_id: str) -> dict[str, Any]:
    """Only the active, paired legacy ordinary policy blocker can be retired."""
    from . import workflow_controls
    task = conn.execute('SELECT current_state FROM task WHERE task_id=?', (task_id,)).fetchone()
    if task is None or task['current_state'] != 'BLOCKED':
        raise ValueError('RETIRED_CONFIRMATION_NOT_ACTIVE')
    state = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='STATE' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    blocker = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='BLOCKER' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    if state is None or blocker is None:
        raise ValueError('RETIRED_CONFIRMATION_SOURCE_UNPROVEN')
    detail = _legacy_detail(dict(blocker))
    binding = detail.get('confirmation_binding')
    if (state['to_state'] != 'BLOCKED' or int(state['id']) <= int(blocker['id'])
            or _legacy_detail(dict(state)) != detail or state['actor_role'] != 'human_owner' or blocker['actor_role'] != 'human_owner'
            or detail.get('operation') != 'AUTONOMY_BOUNDARY' or detail.get('producer') != 'autonomy'
            or not detail.get('transaction_id') or not detail.get('flush_id') or not detail.get('profile_id')
            or detail.get('task_id') != task_id or detail.get('schema_version') != state['workflow_version']
            or detail.get('schema_version') != blocker['workflow_version']
            or detail.get('waiting_reason') != 'awaiting_human_confirmation'
            or detail.get('confirmation_reason') != 'EACH_STAGE_POLICY'
            or not isinstance(binding, dict) or binding.get('confirmation_kind') != 'ordinary'):
        raise ValueError('RETIRED_CONFIRMATION_SOURCE_UNPROVEN: current wait is not retired ordinary policy')
    try:
        rebuilt = workflow_controls.build_boundary_binding(task_id=task_id, **{key: binding[key] for key in (
            'source_stage','source_role','source_event_id','source_event_digest','target_stage','target_role','execution_mode','confirmation_kind')})
        source = conn.execute('SELECT * FROM task_event WHERE task_id=? AND id=?', (task_id, binding['source_event_id'])).fetchone()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('RETIRED_CONFIRMATION_SOURCE_UNPROVEN') from exc
    if (rebuilt != binding or source is None or int(source['id']) >= int(blocker['id'])
            or source['actor_role'] != binding['source_role']
            or workflow_controls.event_digest(dict(source)) != binding['source_event_digest']):
        raise ValueError('RETIRED_CONFIRMATION_SOURCE_UNPROVEN: boundary source changed')
    source_detail = _legacy_detail(dict(source))
    if source['event_type'] == 'FACT':
        trusted_source = (source_detail.get('producer') == 'record-first' and source_detail.get('transaction_id')
            and source_detail.get('operation') == 'CHECKPOINT' and source['from_stage']
            and source['to_stage'] == binding['source_stage'] and source_detail.get('phase') == binding['source_stage'])
    else:
        trusted_source = workflow_controls.trusted_event_detail(dict(source), event_type=source['event_type'],
            producer=str(source_detail.get('producer') or ''), actor=binding['source_role']) is not None
        from .event_policies import event_allowed_for_producer
        trusted_source = trusted_source and event_allowed_for_producer(source['event_type'], source_detail.get('producer'))
    if not trusted_source:
        raise ValueError('RETIRED_CONFIRMATION_SOURCE_UNPROVEN: source is not a formal completion fact')
    return {'kind': 'policy_retirement', 'block_event_id': int(state['id']),
            'blocker_event_id': int(blocker['id']), 'retired_policy': 'each_stage',
            'reason_code': 'EACH_STAGE_POLICY_RETIRED', 'human_approval': False}
