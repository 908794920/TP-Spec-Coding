# -*- coding: utf-8 -*-
"""V5.3.1 Record-first task operations.

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
from . import event_contract
from .version import active_version

PHASES = (
    "intake", "requirement", "product", "discovery", "architecture", "planning",
    "development", "verification", "review", "delivery", "other",
)
ACTORS = (
    "tp-spec-coding", "tp-software-lifecycle", "tp-product-manager",
    "tp-software-architect", "tp-tech-lead", "tp-security-engineer",
    "tp-development-engineer", "tp-database-engineer", "tp-test-engineer",
    "tp-code-reviewer", "tp-integration-engineer", "tp-knowledge",
    "tp-wiki", "tp-base-maintenance", "tp-project-autonomy", "human_owner",
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


def _semantic_detail(event_type: str, operation: str, flush_id: str, result_status: str, **extra) -> str:
    data = json.loads(_detail(operation, flush_id, **extra))
    data = event_contract.add_event_semantics(
        data, event_type=event_type, operation=operation, result_status=result_status,
        producer="record-first", phase=extra.get("phase"),
        milestone_id=extra.get("milestone_id"), reason_code=extra.get("reason_code"),
    )
    return json.dumps(data, ensure_ascii=False)


def _write_with_projection(conn, task_dir: Path, task, *, operation: str,
                           target_state: str, owner_after: str, flush_id: str,
                           writer, summary: str) -> None:
    """Reuse the durable journal without exposing commit/handoff semantics."""
    from . import transaction_commit

    current = str(task["current_state"] or "")
    view_rel = transaction_commit._current_view_rel(target_state)

    def db_and_render(dbconn, transaction_id=""):
        writer(dbconn, transaction_id)
        refreshed = dbconn.execute("SELECT * FROM task WHERE task_id=?", (task["task_id"],)).fetchone()
        status_yaml, events_jsonl, warnings = projection_cmd.render_projection(dbconn, refreshed)
        transaction_commit._warn_projection(warnings)
        return transaction_commit._finalize_texts(
            task_dir,
            {"status.yaml": status_yaml, "events.jsonl": events_jsonl},
            view_rel,
            lambda: transaction_commit._rebuild_current_view_text(task_dir, refreshed, summary, flush_id),
        )

    transaction_commit._commit_with_recovery(
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


def _change_set_roots(conn, task, explicit: Optional[Iterable[str]]) -> List[str]:
    roots = [str(value).strip() for value in (explicit or []) if str(value).strip()]
    if roots:
        return roots
    row = conn.execute("SELECT root_path FROM project WHERE project_id=?", (task["project_id"],)).fetchone()
    root = str(row["root_path"] or "").strip() if row is not None else ""
    if not root:
        raise ValueError("Development checkpoint requires an explicit --repo-root or project root binding")
    # 自主维护的 workspace 根目录本身不是 Git 仓库，而是承载多个独立仓库。
    # 这里必须通过已有 project binding/profile 解析声明过的仓库，不能扫描相邻目录猜测范围。
    from .environment import load_project_binding
    binding = load_project_binding(root)
    autonomy = (binding.data.get("autonomy") or {}) if binding.exists else {}
    profile_id = str(autonomy.get("profile_id") or "").strip()
    if not profile_id:
        return [root]

    from . import autonomy_profile
    from .path_identity import canonical_path, same_path
    profile = autonomy_profile.load_profile(profile_id)
    workspace_root = canonical_path((profile.get("autonomous") or {}).get("workspace_root") or "")
    if not same_path(root, workspace_root):
        raise ValueError(
            f"Autonomy project binding root mismatch: project={root} profile={workspace_root}"
        )
    repo_groups = ((profile.get("canonical") or {}).get("repositories") or {})
    resolved: List[str] = []
    for scope in ("mutable", "support"):
        for item in repo_groups.get(scope) or []:
            rel = str((item or {}).get("path") or "").strip()
            if rel:
                resolved.append(str(canonical_path(workspace_root / rel)))
    if not resolved:
        raise ValueError(f"Autonomy profile {profile_id} has no bound repositories")
    return resolved


def _compact_change_set(change_set: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": str(change_set.get("schema") or ""),
        "content_digest": str(change_set.get("content_digest") or ""),
        "snapshot_digest": str(change_set.get("snapshot_digest") or ""),
        "repositories": [
            {
                key: repo.get(key)
                for key in ("root_locator", "head", "head_tree", "tracked_patch_sha256")
                if repo.get(key) not in (None, "")
            }
            for repo in (change_set.get("repositories") or [])
            if isinstance(repo, dict)
        ],
    }


def checkpoint(*, task_id: str, task_dir: str, actor: str, phase: str,
               summary: str, evidence: Optional[Iterable[str]] = None,
               knowledge_signals: Optional[Iterable[Dict[str, Any]]] = None,
               delivery_signals: Optional[Iterable[str]] = None,
               context_usage: Optional[Iterable[Dict[str, Any]]] = None,
               repo_roots: Optional[Iterable[str]] = None,
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
        if actor == "tp-software-architect" and phase == "architecture":
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

        change_set = None
        roots: List[str] = []
        if phase == "development":
            from . import transaction_commit
            from .change_set import capture_change_set
            # 先验证 Task 目录仍属于 Runtime 绑定的 workspace，再读取 Git。
            # 否则 registry 污染会把跨 workspace 写入误报为 ChangeSet/Git 错误。
            transaction_commit._assert_task_workspace_identity(conn, tdir, task_id)
            roots = _change_set_roots(conn, task, repo_roots)
            change_set = capture_change_set(roots)

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
                 _semantic_detail(
                     "FACT", "CHECKPOINT", flush_id, "COMPLETED",
                     transaction_id=transaction_id, phase=phase, evidence=ev,
                     risk_escalation=risk_escalation, knowledge_signals=knowledge,
                     delivery_signals=delivery, context_usage=usage,
                     change_set_id=(change_set or {}).get("content_digest"),
                     change_set=_compact_change_set(change_set) if change_set else None,
                     repo_roots=roots if change_set else None,
                 ),
                 ev[0] if ev else None, active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='ACTIVE', current_stage=?, owner_role=?, risk_level=?, updated_at=? WHERE task_id=?",
                (phase, actor, effective_risk, now, task_id),
            )

        _write_with_projection(conn, tdir, task, operation="checkpoint", target_state=target,
                               owner_after=actor, flush_id=flush_id, writer=writer, summary=summary)
        result = {"task_id": task_id, "state": target, "phase": phase, "actor": actor,
                  "risk_level": effective_risk, "flush_id": flush_id, "summary": summary}
        if change_set:
            result["change_set_id"] = str(change_set["content_digest"])
            result["change_set_snapshot_digest"] = str(change_set["snapshot_digest"])
        return result
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
            detail = _semantic_detail("BLOCKER", "BLOCK", flush_id, "BLOCKED", transaction_id=transaction_id, phase=phase0, reason=reason, reason_code="BLOCKED")
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


def _latest_development_change_set(conn, task_id: str) -> Optional[Dict[str, Any]]:
    """返回最近一次可信 Development checkpoint 绑定的产品 Change Set。"""
    rows = conn.execute(
        "SELECT id, actor_role, detail_json FROM task_event "
        "WHERE task_id=? AND event_type='FACT' ORDER BY id DESC",
        (task_id,),
    ).fetchall()
    for row in rows:
        if str(row["actor_role"] or "") != "tp-development-engineer":
            continue
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except Exception:
            continue
        if not isinstance(detail, dict):
            continue
        semantics = event_contract.normalize_event_semantics("FACT", detail)
        if str(detail.get("producer") or "") != "record-first":
            continue
        if str(detail.get("operation") or "").upper() != "CHECKPOINT":
            continue
        if str(detail.get("phase") or "") != "development":
            continue
        if str(semantics.get("result_status") or "").upper() != "COMPLETED":
            continue
        change_set_id = str(detail.get("change_set_id") or "").strip()
        roots = [str(value).strip() for value in (detail.get("repo_roots") or []) if str(value).strip()]
        if not roots:
            for repo in ((detail.get("change_set") or {}).get("repositories") or []):
                if isinstance(repo, dict) and str(repo.get("root_locator") or "").strip():
                    roots.append(str(repo["root_locator"]).strip())
        if not change_set_id or not roots:
            return {"event_id": int(row["id"]), "change_set_id": change_set_id, "repo_roots": roots, "detail": detail}
        return {"event_id": int(row["id"]), "change_set_id": change_set_id, "repo_roots": roots, "detail": detail}
    return None


def _latest_verification(conn, task_id: str, task_dir: Optional[Path] = None) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT actor_role,summary,detail_json,created_at FROM task_event WHERE task_id=? AND event_type IN ('VERIFICATION_COMPLETED','REVIEW_COMPLETED') ORDER BY id DESC",
        (task_id,),
    ).fetchall()
    for row in rows:
        if str(row["actor_role"] or "") != "tp-test-engineer":
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
    if actor != "tp-test-engineer":
        raise ValueError("technical verification must be recorded by tp-test-engineer")
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
        development = _latest_development_change_set(conn, task_id)
        current_change_set = None
        if development and development.get("repo_roots"):
            from .change_set import capture_change_set
            current_change_set = capture_change_set(development["repo_roots"])
        visual_summary = None
        if decision0 == "PASS":
            if not development or not development.get("change_set_id") or not development.get("repo_roots"):
                raise ValueError("DEVELOPMENT_CHANGE_SET_REQUIRED")
            if not current_change_set or str(current_change_set.get("content_digest") or "") != development["change_set_id"]:
                raise ValueError("DEVELOPMENT_CHANGE_SET_STALE")

            acceptance_path = tdir / "acceptance.md"
            if acceptance_path.is_file():
                from . import yaml_checks, artifact_validation
                acceptance = yaml_checks.check_acceptance_yaml(
                    acceptance_path.read_text(encoding="utf-8-sig"),
                    enforce_completion=False,
                    allow_human_pending=True,
                )
                visual_issues = [
                    issue for issue in acceptance.issues
                    if issue.startswith("page_verification.visual")
                ]
                if visual_issues:
                    raise ValueError("VISUAL_VERIFICATION_INVALID: " + "; ".join(visual_issues))
                page = acceptance.page_verification or {}
                visual = page.get("visual") if isinstance(page, dict) else None
                if isinstance(visual, dict) and visual.get("required") is True:
                    manifest_path = str(visual.get("evidence_manifest") or "").strip()
                    checked_visual = artifact_validation.validate_visual_verification_manifest(
                        tdir, manifest_path,
                        expected_change_set_id=str(current_change_set.get("content_digest") or ""),
                        acceptance_ids=set(acceptance.acceptance_ids),
                    )
                    if not checked_visual.ok:
                        raise ValueError("VISUAL_VERIFICATION_INVALID: " + "; ".join(checked_visual.errors))
                    existing = {str(item.get("path") or "") for item in items}
                    for path in checked_visual.evidence_paths:
                        if path in existing:
                            continue
                        evidence_checked = validate_evidence_path(tdir, path, require_evidence_dir=True)
                        if not evidence_checked.ok:
                            raise ValueError(f"VISUAL_VERIFICATION_INVALID: {evidence_checked.error}")
                        items.append(evidence_checked.item)
                        existing.add(path)
                    auth = checked_visual.manifest.get("auth") or {}
                    visual_summary = {
                        "manifest": manifest_path,
                        "case_count": len(checked_visual.manifest.get("cases") or []),
                        "temporary_bypass_used": bool(auth.get("temporary_bypass_used")),
                    }
            if not items:
                raise ValueError("verification PASS requires at least one real evidence/* file")
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
                "schema": event_contract.EVENT_SCHEMA,
                "operation": "VERIFY", "result_status": "COMPLETED",
                "flush_id": flush_id, "transaction_id": transaction_id,
                "producer": "record-first", "schema_version": active_version(),
                "task_id": task_id, "actor_role": actor, "created_at": now,
                "decision": decision0, "review_kind": "VERIFICATION",
                "subject_digest": subject_digest, "evidence": [i["path"] for i in items],
                "evidence_items": items, "knowledge_signals": knowledge, "delivery_signals": delivery,
            }
            if development and current_change_set:
                detail_obj["development_event_id"] = int(development["event_id"])
                detail_obj["change_set_id"] = str(current_change_set["content_digest"])
                detail_obj["change_set"] = _compact_change_set(current_change_set)
                detail_obj["repo_roots"] = list(development["repo_roots"])
            if visual_summary:
                detail_obj["visual_verification"] = visual_summary
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
        result = {"task_id": task_id, "state": "ACTIVE", "phase": "verification",
                  "decision": decision0, "evidence_count": len(items), "flush_id": flush_id,
                  "summary": summary}
        if current_change_set:
            result["change_set_id"] = str(current_change_set["content_digest"])
            result["change_set_snapshot_digest"] = str(current_change_set["snapshot_digest"])
        return result
    finally:
        conn.close()



def acceptance_truth_issues(conn, task_id: str, task_dir: Path) -> List[str]:
    """Validate only acceptance claims that would become false history if forged.

    V5.3.1 deliberately does *not* require every AC to be complete.  PENDING is a
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

def _cleanup_terminal_temp_artifacts(task) -> Dict[str, Any]:
    """终态写入成功后做机器本地临时工件清理；失败只进入清理摘要。"""
    from . import temp_artifacts
    try:
        return temp_artifacts.cleanup_task(
            project_id=str(task["project_id"] or "") or None,
            task_id=str(task["task_id"]),
        )
    except Exception as exc:
        return {
            "created": 0,
            "active": 0,
            "cleaned": 0,
            "pending": 1,
            "runs": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


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
        # 结单前先验证所有 AC 均有明确处置；未执行项必须保持真实并由 human_owner defer/waive。
        acceptance_path = tdir / "acceptance.md"
        if acceptance_path.is_file():
            from . import yaml_checks
            completion_check = yaml_checks.check_acceptance_yaml(
                acceptance_path.read_text(encoding="utf-8-sig"),
                enforce_completion=True,
                allow_human_pending=False,
            )
            if not completion_check.ok:
                raise ValueError("INTEGRITY_ACCEPTANCE: " + "; ".join(completion_check.issues))
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
        temp_summary = _cleanup_terminal_temp_artifacts(task)
        return {"task_id": task_id, "state": "COMPLETED", "phase": phase0,
                "verification": verification["decision"], "flush_id": flush_id, "summary": summary,
                "temp_artifacts": temp_summary}
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
        temp_summary = _cleanup_terminal_temp_artifacts(task)
        return {"task_id": task_id, "state": "CANCELLED", "reason": reason, "flush_id": flush_id,
                "temp_artifacts": temp_summary}
    finally:
        conn.close()
