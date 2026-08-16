# -*- coding: utf-8 -*-
"""Trusted Task facts owned by the Autonomous Maintenance control plane.

Autonomy adds provenance/decision/boundary facts to the existing task_event
ledger; it does not add database tables or public Task states.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from . import autonomy_cycle, autonomy_profile
from . import db as dbmod
from . import record_first, workflow_controls
from .version import active_version


def _runtime(profile_id: str) -> tuple[Dict[str, Any], Path, str]:
    profile = autonomy_profile.load_profile(profile_id)
    root = Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    db_path = root / ".tp-spec" / "db" / f"{runtime_id}.db"
    if not db_path.is_file():
        raise ValueError(f"AUTONOMY_RUNTIME_NOT_READY: {db_path}")
    return profile, root, str(db_path)


def task_dir(profile_id: str, task_id: str) -> Path:
    _, root, _ = _runtime(profile_id)
    path = root / ".tp-spec" / "tasks" / task_id
    if not path.is_dir():
        raise ValueError(f"AUTONOMY_TASK_NOT_FOUND: {task_id}")
    return path


def _events(conn, task_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    return [dict(r) for r in rows]


def _detail(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("detail_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_fact(profile_id: str, task_id: str, task_dir_value: str, *, operation: str,
                event_type: str, summary: str, detail: Dict[str, Any], target_state: Optional[str] = None,
                owner_after: Optional[str] = None) -> Dict[str, Any]:
    _, _, db_path = _runtime(profile_id)
    tdir = record_first._task_dir(task_dir_value)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task["current_state"] or "")
        state_after = target_state or current
        owner = owner_after or str(task["owner_role"] or "human_owner")
        now = dbmod.now_iso()
        flush_id = f"AUTO-{operation.upper()}-{uuid.uuid4().hex}"

        def writer(dbconn, transaction_id=""):
            payload = dict(detail)
            payload.update({
                "operation": operation,
                "producer": "autonomy",
                "profile_id": profile_id,
                "task_id": task_id,
                "flush_id": flush_id,
                "transaction_id": transaction_id,
                "schema_version": active_version(),
                "created_at": now,
            })
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, event_type, "human_owner" if operation == "DECISION" else "tp-project-autonomy",
                 summary, json.dumps(payload, ensure_ascii=False), active_version(), now),
            )
            if state_after != current:
                dbconn.execute(
                    "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, "STATE", current, state_after, task["current_stage"], task["current_stage"],
                     owner, summary, json.dumps(payload, ensure_ascii=False), active_version(), now),
                )
            completed_at = now if state_after == "COMPLETED" else None
            if state_after == "CANCELLED":
                dbconn.execute("UPDATE task SET current_state=?, owner_role=?, updated_at=? WHERE task_id=?",
                               (state_after, owner, now, task_id))
            elif state_after != current:
                dbconn.execute("UPDATE task SET current_state=?, owner_role=?, updated_at=?, completed_at=COALESCE(?,completed_at) WHERE task_id=?",
                               (state_after, owner, now, completed_at, task_id))
            else:
                dbconn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, task_id))

        record_first._write_with_projection(
            conn, tdir, task, operation=f"autonomy_{operation.lower()}", target_state=state_after,
            owner_after=owner, flush_id=flush_id, writer=writer, summary=summary,
        )
        return {"task_id": task_id, "state": state_after, "flush_id": flush_id, **detail}
    finally:
        conn.close()


def record_discovered(profile_id: str, task_id: str, task_dir_value: str, *, discovery_key: str,
                      cycle_id: Optional[str] = None, generation: Optional[int] = None) -> Dict[str, Any]:
    return _write_fact(
        profile_id, task_id, task_dir_value, operation="DISCOVERED", event_type="AUTONOMY_DISCOVERED",
        summary=f"autonomy discovery: {discovery_key}",
        detail={"discovery_key": discovery_key, "cycle_id": cycle_id, "generation": generation},
    )


def latest_decision(profile_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    _, _, db_path = _runtime(profile_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM task_event WHERE task_id=? AND event_type='AUTONOMY_DECISION' ORDER BY id DESC",
            (task_id,),
        ).fetchall()
        for row in rows:
            event = dict(row); detail = _detail(event)
            if detail.get("profile_id") == profile_id:
                return {"event": event, **detail}
        return None
    finally:
        conn.close()


def record_decision(profile_id: str, task_id: str, *, decision: str, reason: str) -> Dict[str, Any]:
    decision0 = str(decision or "").upper()
    if decision0 not in {"APPROVED", "REJECTED"}:
        raise ValueError("AUTONOMY_DECISION_INVALID: APPROVED|REJECTED")
    tdir = task_dir(profile_id, task_id)
    status = autonomy_cycle.cycle_status(profile_id)
    current_generation = int(status.get("generation") or 0)
    effective = current_generation + 1
    detail = {
        "decision": decision0,
        "reason": str(reason or "").strip(),
        "effective_after_generation": effective,
    }
    target = "CANCELLED" if decision0 == "REJECTED" else None
    result = _write_fact(
        profile_id, task_id, str(tdir), operation="DECISION", event_type="AUTONOMY_DECISION",
        summary=f"autonomy decision {decision0}: {reason}", detail=detail,
        target_state=target, owner_after="human_owner",
    )
    return result


def allowed_effects(profile_id: str, task_id: str, cycle_generation: int) -> Set[str]:
    decision = latest_decision(profile_id, task_id)
    if not decision or decision.get("decision") != "APPROVED":
        return set()
    if int(decision.get("effective_after_generation") or 0) > int(cycle_generation):
        return set()
    return {"repo_mutation"}


def _latest_boundary(conn, task_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type='BLOCKER' ORDER BY id DESC", (task_id,)
    ).fetchall()
    for row in rows:
        event = dict(row); detail = _detail(event)
        if detail.get("operation") == "AUTONOMY_BOUNDARY" and detail.get("profile_id") == profile_id:
            return {"event": event, **detail}
    return None


def block_for_route(profile_id: str, task_id: str, route: Dict[str, Any], *, cycle_id: str, generation: int) -> Dict[str, Any]:
    tdir = task_dir(profile_id, task_id)
    _, _, db_path = _runtime(profile_id)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task["current_state"] or "")
        if current == "BLOCKED":
            out = dict(route)
            boundary = _latest_boundary(conn, task_id, profile_id)
            if boundary:
                out["autonomy_waiting_reason"] = boundary.get("waiting_reason")
            return out
        if current in record_first.TERMINAL_STATES:
            return dict(route)
        waiting = "awaiting_autonomy_decision" if route.get("decision") == "BOUNDARY_REACHED" else "awaiting_human_confirmation"
        now = dbmod.now_iso(); flush_id = f"AUTO-BOUNDARY-{uuid.uuid4().hex}"
        detail = {
            "operation": "AUTONOMY_BOUNDARY", "producer": "autonomy", "schema_version": active_version(),
            "profile_id": profile_id, "task_id": task_id, "cycle_id": cycle_id, "generation": int(generation),
            "waiting_reason": waiting, "workflow_decision": route.get("decision"),
            "required_effects": list(route.get("required_effects") or []),
            "confirmation_reason": route.get("confirmation_reason"),
            "confirmation_binding": route.get("confirmation_binding"),
        }

        def writer(dbconn, transaction_id=""):
            payload = dict(detail); payload["transaction_id"] = transaction_id; payload["flush_id"] = flush_id
            reason = waiting if waiting == "awaiting_autonomy_decision" else f"{waiting}:{route.get('confirmation_reason') or 'workflow'}"
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, "BLOCKER", "human_owner", reason, json.dumps(payload, ensure_ascii=False), active_version(), now),
            )
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, "STATE", current, "BLOCKED", task["current_stage"], task["current_stage"], "human_owner", reason,
                 json.dumps(payload, ensure_ascii=False), active_version(), now),
            )
            dbconn.execute("UPDATE task SET current_state='BLOCKED', owner_role='human_owner', updated_at=? WHERE task_id=?", (now, task_id))

        record_first._write_with_projection(
            conn, tdir, task, operation="autonomy_boundary", target_state="BLOCKED", owner_after="human_owner",
            flush_id=flush_id, writer=writer, summary=waiting,
        )
        out = dict(route); out["autonomy_waiting_reason"] = waiting; out["next_cycle_effective"] = True
        return out
    finally:
        conn.close()


def pending_autonomy_decision(profile_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    _, _, db_path = _runtime(profile_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        task = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()
        if task is None or str(task["current_state"] or "") != "BLOCKED":
            return None
        boundary = _latest_boundary(conn, task_id, profile_id)
        if not boundary or boundary.get("waiting_reason") != "awaiting_autonomy_decision":
            return None
        return boundary
    finally:
        conn.close()


def pending_workflow_confirmation(profile_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    _, _, db_path = _runtime(profile_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        task = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()
        if task is None or str(task["current_state"] or "") != "BLOCKED":
            return None
        boundary = _latest_boundary(conn, task_id, profile_id)
        if not boundary or boundary.get("waiting_reason") != "awaiting_human_confirmation":
            return None
        binding = boundary.get("confirmation_binding")
        if not isinstance(binding, dict) or not binding:
            return None
        return boundary
    finally:
        conn.close()


def pending_workflow_confirmation_any(task_id: str, db_path: str) -> Optional[Dict[str, Any]]:
    conn = dbmod.connect_readonly(db_path)
    try:
        rows = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='BLOCKER' ORDER BY id DESC", (task_id,)).fetchall()
        for row in rows:
            event = dict(row); detail = _detail(event)
            if detail.get("operation") == "AUTONOMY_BOUNDARY" and detail.get("waiting_reason") == "awaiting_human_confirmation":
                binding = detail.get("confirmation_binding")
                if isinstance(binding, dict) and binding:
                    return {"event": event, **detail}
        return None
    finally:
        conn.close()


def resume_if_satisfied(profile_id: str, task_id: str, cycle_generation: int) -> bool:
    _, _, db_path = _runtime(profile_id)
    tdir = task_dir(profile_id, task_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        task = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()
        if task is None or str(task["current_state"] or "") != "BLOCKED":
            return False
        boundary = _latest_boundary(conn, task_id, profile_id)
        if not boundary:
            return False
        if int(boundary.get("generation") or 0) >= int(cycle_generation):
            return False
        events = _events(conn, task_id)
        waiting = boundary.get("waiting_reason")
        satisfied = False
        if waiting == "awaiting_autonomy_decision":
            decision = latest_decision(profile_id, task_id)
            satisfied = bool(
                decision and decision.get("decision") == "APPROVED"
                and int(decision.get("effective_after_generation") or 0) <= int(cycle_generation)
            )
        elif waiting == "awaiting_human_confirmation":
            binding = boundary.get("confirmation_binding")
            satisfied = isinstance(binding, dict) and workflow_controls.find_matching_confirmation(events, binding) is not None
        if not satisfied:
            return False
    finally:
        conn.close()
    record_first.resume(
        task_id=task_id, task_dir=str(tdir), actor="human_owner",
        summary=f"autonomy blocker satisfied for cycle generation {cycle_generation}", db=db_path,
    )
    return True
