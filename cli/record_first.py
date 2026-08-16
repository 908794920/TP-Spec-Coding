# -*- coding: utf-8 -*-
"""V5.2.3 Record-first task operations.

The public workflow records business facts instead of forcing role-authored
workflow bookkeeping. SQLite remains authoritative; readable projections are
rebuilt automatically after each fact write.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import db as dbmod
from . import projection_cmd
from .version import active_version

PHASES = (
    "intake", "requirement", "product", "architecture", "discovery",
    "development", "verification", "delivery", "other",
)
ACTORS = (
    "tp-requirement-analysis", "tp-product-design", "tp-architecture-design",
    "tp-architecture-review", "tp-development-engineering",
    "tp-verification-engineering", "tp-delivery-convergence", "tp-knowledge",
    "tp-wiki", "human_owner",
)
PUBLIC_STATES = {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"}
TERMINAL_STATES = {"COMPLETED", "CANCELLED"}


def _task_dir(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_dir():
        raise ValueError(f"task-dir not found: {path}")
    return path


def _load(conn, task_id: str):
    task = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
    if task is None:
        raise ValueError(f"task not found: {task_id}")
    if str(task["base_version"] or "") != active_version():
        raise ValueError(
            f"task contract {task['base_version']!r} is not active {active_version()}; "
            "run project upgrade-contract + task migrate first"
        )
    return task


def _detail(operation: str, flush_id: str, **extra) -> str:
    data: Dict[str, Any] = {
        "operation": operation,
        "flush_id": flush_id,
        "producer": "record-first",
        "schema_version": active_version(),
    }
    data.update({k: v for k, v in extra.items() if v not in (None, [], "")})
    return json.dumps(data, ensure_ascii=False)


def _write_with_projection(conn, task_dir: Path, task, *, operation: str,
                           target_state: str, owner_after: str, flush_id: str,
                           writer, summary: str) -> None:
    """Reuse the durable journal without exposing commit/handoff semantics."""
    from . import commit_cmd

    current = str(task["current_state"] or "")
    view_rel = commit_cmd._current_view_rel(target_state)

    def db_and_render(dbconn, transaction_id=""):
        writer(dbconn, transaction_id)
        refreshed = dbconn.execute("SELECT * FROM task WHERE task_id=?", (task["task_id"],)).fetchone()
        status_yaml, events_jsonl, warnings = projection_cmd.render_projection(dbconn, refreshed)
        commit_cmd._warn_projection(warnings)
        return commit_cmd._finalize_texts(
            task_dir,
            {"status.yaml": status_yaml, "events.jsonl": events_jsonl},
            view_rel,
            lambda: commit_cmd._rebuild_current_view_text(task_dir, refreshed, summary, flush_id),
        )

    commit_cmd._commit_with_recovery(
        task_dir, conn, ["status.yaml", "events.jsonl", view_rel], db_and_render,
        task_id=str(task["task_id"]), operation=operation,
        db_state_before=current, target_state=target_state,
        owner_before=str(task["owner_role"] or ""), owner_after=owner_after,
        flush_id=flush_id,
    )


def _normalize_knowledge_signals(values: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in values or []:
        if not isinstance(raw, dict):
            raise ValueError("knowledge signal must be a mapping")
        item = dict(raw)
        if not str(item.get("type") or "").strip() or not str(item.get("summary") or "").strip():
            raise ValueError("knowledge signal requires type + summary")
        for key in ("evidence", "source_refs"):
            if key in item and not isinstance(item[key], list):
                raise ValueError(f"knowledge signal {key} must be a list")
        out.append(item)
    return out


def _normalize_delivery_signals(values: Optional[Iterable[str]]) -> List[str]:
    out: List[str] = []
    for raw in values or []:
        value = str(raw or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def checkpoint(*, task_id: str, task_dir: str, actor: str, phase: str,
               summary: str, evidence: Optional[Iterable[str]] = None,
               knowledge_signals: Optional[Iterable[Dict[str, Any]]] = None,
               delivery_signals: Optional[Iterable[str]] = None,
               context_usage: Optional[Iterable[Dict[str, Any]]] = None,
               db: Optional[str] = None) -> Dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"invalid phase {phase!r}; choose one of: {', '.join(PHASES)}")
    if actor not in ACTORS:
        raise ValueError(f"invalid actor: {actor}")
    tdir = _task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = _load(conn, task_id)
        current = str(task["current_state"] or "")
        if current in TERMINAL_STATES:
            raise ValueError(f"terminal task cannot accept checkpoint: {current}")
        if current == "BLOCKED":
            raise ValueError("task is BLOCKED; use 'task resume' after the blocker is resolved")
        target = "ACTIVE"
        now = dbmod.now_iso()
        flush_id = f"CHECKPOINT-{uuid.uuid4().hex}"
        ev = list(evidence or [])
        knowledge = _normalize_knowledge_signals(knowledge_signals)
        delivery = _normalize_delivery_signals(delivery_signals)
        from . import context_usage as context_usage_mod
        usage, context_warnings = context_usage_mod.normalize_context_usage(context_usage)
        context_usage_mod.emit_warnings(context_warnings)
        risk_escalation = None
        effective_risk = str(task["risk_level"] or "L1")
        if actor == "tp-architecture-design" and phase == "architecture":
            from . import risk_signals
            scan = risk_signals.scan_task_artifacts(tdir)
            order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
            floor = str(scan.get("floor") or "")
            if order.get(floor, -1) > order.get(effective_risk, -1):
                risk_escalation = {
                    "from": effective_risk, "to": floor,
                    "signals": list(scan.get("signals") or []),
                }
                effective_risk = floor

        def writer(dbconn, transaction_id=""):
            if current != "ACTIVE":
                dbconn.execute(
                    "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, "STATE", current or None, "ACTIVE", task["current_stage"], phase,
                     actor, "task activated", _detail("ACTIVATE", flush_id, transaction_id=transaction_id, phase=phase), active_version(), now),
                )
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,summary,detail_json,evidence_path,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (task_id, "FACT", task["current_stage"], phase, actor, summary,
                 _detail("CHECKPOINT", flush_id, transaction_id=transaction_id, phase=phase, evidence=ev, risk_escalation=risk_escalation, knowledge_signals=knowledge, delivery_signals=delivery, context_usage=usage),
                 ev[0] if ev else None, active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='ACTIVE', current_stage=?, owner_role=?, risk_level=?, updated_at=? WHERE task_id=?",
                (phase, actor, effective_risk, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="checkpoint", target_state=target,
                               owner_after=actor, flush_id=flush_id, writer=writer, summary=summary)
        return {"task_id": task_id, "state": target, "phase": phase, "actor": actor,
                "risk_level": effective_risk, "flush_id": flush_id, "summary": summary}
    finally:
        conn.close()


def block(*, task_id: str, task_dir: str, actor: str, reason: str,
          phase: Optional[str] = None, db: Optional[str] = None) -> Dict[str, Any]:
    if actor not in ACTORS:
        raise ValueError(f"invalid actor: {actor}")
    if phase is not None and phase not in PHASES:
        raise ValueError(f"invalid phase: {phase}")
    tdir = _task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = _load(conn, task_id)
        current = str(task["current_state"] or "")
        if current in TERMINAL_STATES:
            raise ValueError(f"terminal task cannot be blocked: {current}")
        if current == "BLOCKED":
            raise ValueError("task is already BLOCKED")
        phase0 = phase or str(task["current_stage"] or "other")
        if phase0 not in PHASES:
            phase0 = "other"
        now = dbmod.now_iso(); flush_id = f"BLOCK-{uuid.uuid4().hex}"

        def writer(dbconn, transaction_id=""):
            detail = _detail("BLOCK", flush_id, transaction_id=transaction_id, phase=phase0, reason=reason)
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, "BLOCKER", actor, reason, detail, active_version(), now),
            )
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, "STATE", current, "BLOCKED", task["current_stage"], phase0, actor, reason, detail, active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='BLOCKED', current_stage=?, owner_role=?, updated_at=? WHERE task_id=?",
                (phase0, actor, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="block", target_state="BLOCKED",
                               owner_after=actor, flush_id=flush_id, writer=writer, summary=reason)
        return {"task_id": task_id, "state": "BLOCKED", "phase": phase0, "reason": reason, "flush_id": flush_id}
    finally:
        conn.close()


def resume(*, task_id: str, task_dir: str, actor: str, summary: str,
           phase: Optional[str] = None, db: Optional[str] = None) -> Dict[str, Any]:
    if actor not in ACTORS:
        raise ValueError(f"invalid actor: {actor}")
    tdir = _task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = _load(conn, task_id)
        if str(task["current_state"] or "") != "BLOCKED":
            raise ValueError("task resume requires current state BLOCKED")
        phase0 = phase or str(task["current_stage"] or "other")
        if phase0 not in PHASES:
            raise ValueError(f"invalid phase: {phase0}")
        now = dbmod.now_iso(); flush_id = f"RESUME-{uuid.uuid4().hex}"

        def writer(dbconn, transaction_id=""):
            detail = _detail("RESUME", flush_id, transaction_id=transaction_id, phase=phase0)
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, "STATE", "BLOCKED", "ACTIVE", task["current_stage"], phase0, actor, summary, detail, active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='ACTIVE', current_stage=?, owner_role=?, updated_at=? WHERE task_id=?",
                (phase0, actor, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="resume", target_state="ACTIVE",
                               owner_after=actor, flush_id=flush_id, writer=writer, summary=summary)
        return {"task_id": task_id, "state": "ACTIVE", "phase": phase0, "summary": summary, "flush_id": flush_id}
    finally:
        conn.close()


def _latest_verification(conn, task_id: str, task_dir: Optional[Path] = None) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT actor_role,summary,detail_json,created_at FROM task_event WHERE task_id=? AND event_type IN ('VERIFICATION_COMPLETED','REVIEW_COMPLETED') ORDER BY id DESC",
        (task_id,),
    ).fetchall()
    for row in rows:
        if str(row["actor_role"] or "") != "tp-verification-engineering":
            continue
        detail = {}
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except Exception:
            pass
        recorded = str(detail.get("decision") or "").upper()
        if recorded:
            decision = recorded
            subject = str(detail.get("subject_digest") or "")
            if task_dir is not None and subject:
                from .digest import compute_verification_subject_digest
                if compute_verification_subject_digest(task_dir) != subject:
                    decision = f"{recorded}_STALE"
            return {
                "decision": decision, "recorded_decision": recorded,
                "time": str(row["created_at"] or ""), "summary": str(row["summary"] or ""),
            }
    return {"decision": "NOT_RECORDED", "recorded_decision": "NOT_RECORDED", "time": "", "summary": ""}


def verify(*, task_id: str, task_dir: str, actor: str, decision: str,
           summary: str, evidence: Optional[Iterable[str]] = None,
           knowledge_signals: Optional[Iterable[Dict[str, Any]]] = None,
           delivery_signals: Optional[Iterable[str]] = None,
           context_usage: Optional[Iterable[Dict[str, Any]]] = None,
           db: Optional[str] = None) -> Dict[str, Any]:
    """Record an actual technical verification result without adding a workflow gate."""
    if actor != "tp-verification-engineering":
        raise ValueError("technical verification must be recorded by tp-verification-engineering")
    decision0 = str(decision or "").upper()
    if decision0 not in {"PASS", "FAIL", "NEEDS_FIX"}:
        raise ValueError("decision must be PASS, FAIL or NEEDS_FIX")
    tdir = _task_dir(task_dir)
    from .evidence import validate_evidence_path
    from .digest import compute_verification_subject_digest
    items = []
    for raw in evidence or []:
        checked = validate_evidence_path(tdir, raw, require_evidence_dir=True)
        if not checked.ok:
            raise ValueError(f"verification evidence invalid: {checked.error}")
        items.append(checked.item)
    if decision0 == "PASS" and not items:
        raise ValueError("verification PASS requires at least one real evidence/* file")
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = _load(conn, task_id)
        current = str(task["current_state"] or "")
        if current in TERMINAL_STATES:
            raise ValueError(f"terminal task cannot accept verification: {current}")
        if current == "BLOCKED":
            raise ValueError("task is BLOCKED; resolve the blocker before verification")
        now = dbmod.now_iso(); flush_id = f"VERIFY-{uuid.uuid4().hex}"
        subject_digest = compute_verification_subject_digest(tdir)
        knowledge = _normalize_knowledge_signals(knowledge_signals)
        delivery = _normalize_delivery_signals(delivery_signals)
        from . import context_usage as context_usage_mod
        usage, context_warnings = context_usage_mod.normalize_context_usage(context_usage)
        context_usage_mod.emit_warnings(context_warnings)

        def writer(dbconn, transaction_id=""):
            if current != "ACTIVE":
                dbconn.execute(
                    "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, "STATE", current or None, "ACTIVE", task["current_stage"], "verification",
                     actor, "task activated for verification",
                     _detail("ACTIVATE", flush_id, transaction_id=transaction_id, phase="verification"), active_version(), now),
                )
            detail_obj = {
                "operation": "VERIFY", "flush_id": flush_id, "transaction_id": transaction_id,
                "producer": "record-first", "schema_version": active_version(),
                "task_id": task_id, "actor_role": actor, "created_at": now,
                "decision": decision0, "review_kind": "VERIFICATION",
                "subject_digest": subject_digest, "evidence": [i["path"] for i in items],
                "evidence_items": items, "knowledge_signals": knowledge, "delivery_signals": delivery,
            }
            if usage:
                detail_obj["context_usage"] = usage
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,summary,detail_json,evidence_path,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (task_id, "VERIFICATION_COMPLETED", task["current_stage"], "verification", actor,
                 summary, json.dumps(detail_obj, ensure_ascii=False), items[0]["path"] if items else None,
                 active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='ACTIVE', current_stage='verification', owner_role=?, updated_at=? WHERE task_id=?",
                (actor, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="verify", target_state="ACTIVE",
                               owner_after=actor, flush_id=flush_id, writer=writer, summary=summary)
        return {"task_id": task_id, "state": "ACTIVE", "phase": "verification",
                "decision": decision0, "evidence_count": len(items), "flush_id": flush_id,
                "summary": summary}
    finally:
        conn.close()



def acceptance_truth_issues(conn, task_id: str, task_dir: Path) -> List[str]:
    """Validate only acceptance claims that would become false history if forged.

    V5.2.3 deliberately does *not* require every AC to be complete.  PENDING is a
    valid factual outcome.  This check therefore ignores completeness/formality and
    protects only positive/owner-authority claims: PASS evidence, human witness, and
    DEFERRED_ACCEPTED/OWNER_WAIVED ledger authority.
    """
    path = task_dir / "acceptance.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig")
    from . import event_policies, yaml_checks
    from .evidence import validate_evidence_path

    parsed = yaml_checks.check_acceptance_yaml(
        text, enforce_completion=False, allow_human_pending=True
    )
    deferred_entries = {str(x.get("ac") or "") for x in parsed.deferred_entries}
    waiver_entries = {str(x.get("ac") or "") for x in parsed.owner_waiver_entries}
    trusted_pairs = set()
    for item in event_policies.load_owner_acceptance_decisions(conn, task_id):
        mode = str(item.get("mode") or "").lower()
        for ac in item.get("acs") or []:
            trusted_pairs.add((str(ac), mode))

    witness_confirmed = bool(
        __import__("re").search(r"(?m)^\s*human_witness:\s*[\"']?confirmed[\"']?\s*$", text)
    )
    issues: List[str] = []
    for line in text.splitlines():
        m = __import__("re").match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) <= 8:
            continue
        ac = m.group(1)
        evidence = cells[6]
        witness = cells[7].lower()
        verdict = yaml_checks.normalize_verdict(cells[8])
        if verdict == "PASS":
            if not evidence:
                issues.append(f"{ac} PASS has no evidence")
            else:
                checked = validate_evidence_path(task_dir, evidence)
                if not checked.ok:
                    issues.append(f"{ac} PASS evidence invalid: {checked.error}")
            if witness == "human" and not witness_confirmed:
                issues.append(f"{ac} human PASS requires confirmed human witness")
        elif verdict == "DEFERRED_ACCEPTED":
            if ac not in deferred_entries or (ac, "defer") not in trusted_pairs:
                issues.append(f"{ac} DEFERRED_ACCEPTED lacks trusted human_owner decision")
        elif verdict == "OWNER_WAIVED":
            if ac not in waiver_entries or (ac, "waive") not in trusted_pairs:
                issues.append(f"{ac} OWNER_WAIVED lacks trusted human_owner decision")
    return issues

def complete(*, task_id: str, task_dir: str, actor: Optional[str], summary: str,
             db: Optional[str] = None) -> Dict[str, Any]:
    tdir = _task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = _load(conn, task_id)
        actor0 = str(actor or task["owner_role"] or "").strip()
        if actor0 not in ACTORS:
            raise ValueError(f"invalid actor: {actor0 or '<missing>'}")
        current = str(task["current_state"] or "")
        if current == "BLOCKED":
            raise ValueError("INTEGRITY_BLOCKED: explicit task blocker must be resolved before COMPLETED")
        if current in TERMINAL_STATES:
            raise ValueError(f"task is already terminal: {current}")
        # Zero-token invariant: a role may never bypass remaining workflow stages.
        from . import orchestration
        route = orchestration.resolve_route(task_id, db_path=db_path)
        if route.get("recommended_action") != "task_complete" or route.get("next_stage") != "complete":
            raise ValueError(
                "INTEGRITY_PIPELINE_PENDING: "
                f"next_stage={route.get('next_stage')} role={route.get('role_id')} "
                f"reason={','.join(route.get('reason_codes') or [])}"
            )
        # Completion is a factual terminal record, not a quality claim. It does not
        # require every AC to be PASS, but any positive/owner-authority claim that is
        # present must be truthful and ledger-backed.
        truth_issues = acceptance_truth_issues(conn, task_id, tdir)
        if truth_issues:
            raise ValueError("INTEGRITY_ACCEPTANCE: " + "; ".join(truth_issues))
        verification = _latest_verification(conn, task_id, tdir)
        now = dbmod.now_iso(); flush_id = f"COMPLETE-{uuid.uuid4().hex}"
        phase0 = str(task["current_stage"] or "delivery")

        def writer(dbconn, transaction_id=""):
            detail = _detail(
                "COMPLETE", flush_id, transaction_id=transaction_id, phase=phase0,
                verification=verification,
            )
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, "STATE", current, "COMPLETED", task["current_stage"], phase0,
                 actor0, summary, detail, active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='COMPLETED', owner_role=?, updated_at=?, completed_at=? WHERE task_id=?",
                (actor0, now, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="complete", target_state="COMPLETED",
                               owner_after=actor0, flush_id=flush_id, writer=writer, summary=summary)
        return {"task_id": task_id, "state": "COMPLETED", "phase": phase0,
                "verification": verification["decision"], "flush_id": flush_id, "summary": summary}
    finally:
        conn.close()


def cancel(*, task_id: str, task_dir: str, actor: str, reason: str,
           db: Optional[str] = None) -> Dict[str, Any]:
    if actor != "human_owner":
        raise ValueError("CANCELLED requires human_owner")
    tdir = _task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = _load(conn, task_id)
        current = str(task["current_state"] or "")
        if current in TERMINAL_STATES:
            raise ValueError(f"task is already terminal: {current}")
        now = dbmod.now_iso(); flush_id = f"CANCEL-{uuid.uuid4().hex}"

        def writer(dbconn, transaction_id=""):
            detail = _detail("CANCEL", flush_id, transaction_id=transaction_id, reason=reason)
            dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_state,to_state,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (task_id, "STATE", current, "CANCELLED", actor, reason, detail, active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='CANCELLED', owner_role=?, updated_at=? WHERE task_id=?",
                (actor, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="cancel", target_state="CANCELLED",
                               owner_after=actor, flush_id=flush_id, writer=writer, summary=reason)
        return {"task_id": task_id, "state": "CANCELLED", "reason": reason, "flush_id": flush_id}
    finally:
        conn.close()
