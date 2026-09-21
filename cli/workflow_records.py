from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .delivery_contract import validate_delivery_result
from . import event_contract


def build_confirmation_detail(*, task_id: str, binding: Dict[str, Any], transaction_id: str,
                              flush_id: str, created_at: str, schema_version: str) -> Dict[str, Any]:
    return {
        'schema': event_contract.EVENT_SCHEMA,
        'operation': 'WORKFLOW_CONFIRM',
        'result_status': 'COMPLETED',
        'flush_id': flush_id,
        'transaction_id': transaction_id,
        'producer': 'workflow_confirm',
        'schema_version': schema_version,
        'task_id': task_id,
        'actor_role': 'human_owner',
        'created_at': created_at,
        **binding,
    }


def build_delivery_detail(*, task_id: str, transaction_id: str, flush_id: str,
                          created_at: str, schema_version: str,
                          verification_event_id: int, verification_subject_digest: str,
                          verification_change_set_id: str, review_event_id: int,
                          review_change_set_id: str, change_set_id: str,
                          delivery_status: str, reason: str,
                          evidence: Optional[Iterable[str]] = None,
                          residual_risks: Optional[Iterable[str]] = None,
                          evidence_items: Optional[Iterable[Dict[str, Any]]] = None,
                          context_usage: Optional[Iterable[Dict[str, Any]]] = None,
                          repo_snapshot: Optional[Dict[str, Any]] = None,
                          recovery_condition: Optional[str] = None,
                          blocker_kind: Optional[str] = None,
                          responsibility: Optional[str] = None,
                          delivery_mode: str = "full", applicability: Optional[Dict[str, str]] = None,
                          acceptance_digest: str = "",
                          acceptance_evidence_items: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    delivery_status0 = str(delivery_status or '').upper()
    detail: Dict[str, Any] = {
        'schema': event_contract.EVENT_SCHEMA,
        'operation': 'DELIVERY_CONVERGE',
        'result_status': 'BLOCKED' if delivery_status0 == 'BLOCKED' else 'COMPLETED',
        'flush_id': flush_id,
        'transaction_id': transaction_id,
        'producer': 'delivery_converge',
        'schema_version': schema_version,
        'task_id': task_id,
        'actor_role': 'tp-integration-engineer',
        'created_at': created_at,
        'verification_event_id': int(verification_event_id),
        'verification_subject_digest': str(verification_subject_digest),
        'verification_change_set_id': str(verification_change_set_id),
        'review_event_id': int(review_event_id),
        'review_change_set_id': str(review_change_set_id),
        'change_set_id': str(change_set_id),
        'delivery_status': delivery_status0,
        'delivery_mode': delivery_mode,
        'closeout_schema': 'tp-spec.closeout/v1',
        'acceptance_digest': acceptance_digest,
        'acceptance_evidence_items': list(acceptance_evidence_items or []),
        'reason': str(reason or '').strip(),
    }
    if applicability is not None:
        detail["applicability"] = dict(applicability)
    for key, values in {
        'evidence': evidence, 'residual_risks': residual_risks,
        'evidence_items': evidence_items, 'context_usage': context_usage,
    }.items():
        items = list(values or [])
        if items:
            detail[key] = items
    if repo_snapshot is not None:
        detail['repo_snapshot'] = dict(repo_snapshot)
    if str(recovery_condition or '').strip():
        detail['recovery_condition'] = str(recovery_condition).strip()
    if str(blocker_kind or '').strip():
        detail['blocker_kind'] = str(blocker_kind).strip().upper()
    if str(responsibility or '').strip():
        detail['responsibility'] = str(responsibility).strip()
    errors = validate_delivery_result(detail)
    if errors:
        raise ValueError('invalid delivery result: ' + '; '.join(errors))
    return detail

def _checked_evidence_items(task_dir: Path, values: Optional[Iterable[str]]) -> tuple[list[str], list[Dict[str, Any]]]:
    from .evidence import validate_evidence_path

    paths: list[str] = []
    items: list[Dict[str, Any]] = []
    for raw in values or []:
        checked = validate_evidence_path(task_dir, raw, require_evidence_dir=True)
        if not checked.ok:
            raise ValueError(f'delivery evidence invalid: {checked.error}')
        paths.append(str(checked.item['path']))
        items.append(dict(checked.item))
    return paths, items


def _latest_trusted_verification(conn, task_id: str, task_dir: Path):
    from . import event_policies
    from .change_set import capture_change_set
    from .digest import compute_verification_subject_digest

    current_subject = compute_verification_subject_digest(task_dir)
    trusted = event_policies.load_current_verification(conn, task_id, task_dir, require_full=True)
    if trusted is None:
        raise ValueError('DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS')
    detail = dict(trusted.detail or {})
    change_set_id = str(detail.get('change_set_id') or '').strip()
    repo_roots = [str(value).strip() for value in (detail.get('repo_roots') or []) if str(value).strip()]
    if not change_set_id or not repo_roots:
        raise ValueError('DELIVERY_CHANGE_SET_MISMATCH: verification is not bound to a product change set')
    current_change_set = capture_change_set(repo_roots)
    from .change_set import same_bound_product_content
    if not same_bound_product_content(detail, current_change_set):
        raise ValueError('DELIVERY_CHANGE_SET_MISMATCH: current product content differs from verification')
    return trusted, current_subject, current_change_set, repo_roots


def _latest_trusted_code_review(conn, task_id: str, *, subject_digest: str,
                                change_set_id: str, verification_event_id: int, task_dir: Path):
    from . import event_policies
    from .digest import compute_text_artifact_file_digest
    from .evidence import validate_evidence_path

    # CODE aliases share one outcome history. Filtering for PASS/kind first would
    # revive an older approval after a new finding or BLOCKED result.
    trusted = event_policies.load_trusted_governance_event(
        conn, task_id, event_type='REVIEW_COMPLETED', actor='tp-code-reviewer',
        decision='PASS', evidence_dir=task_dir, latest_only=True,
    )
    if trusted is not None:
        detail = trusted.detail
        count = detail.get('findings_count')
        checked = validate_evidence_path(task_dir, detail.get('artifact'))
        artifact_ok = checked.ok and compute_text_artifact_file_digest(task_dir / checked.path) == detail.get('artifact_digest')
        try:
            bound_id = int(detail.get('verification_event_id') or 0)
            # A later full result can supplement an unchanged technical review.
            # Revalidate its original evidence; a newer failure/changed subject
            # cannot be erased by recording PASS again.
            history = event_policies.load_trusted_governance_events(
                conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer",
                decision="PASS", evidence_dir=task_dir,
            )
            original = next((item for item in history if int(item.row["id"]) == bound_id), None)
            scope = detail.get("verification_scope", "full")
            from .change_set import same_bound_product_content
            from .delivery_contract import load_repository_scope
            scope_event_id = load_repository_scope(conn, task_id)["scope_event_id"]
            current_verification = next((item for item in history if int(item.row["id"]) == int(verification_event_id)), None)
            current_snapshot = (current_verification.detail.get("change_set") or {}) if current_verification else {}
            valid_ids = {int(item.row["id"]) for item in history
                         if event_policies.verification_subject_matches(item.detail, task_dir)
                         and item.detail.get("change_set_id") == change_set_id
                         and int(item.row["id"]) > scope_event_id
                         and same_bound_product_content(item.detail, current_snapshot)}
            later_ids = {int(row[0]) for row in conn.execute(
                "SELECT id FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED' "
                "AND actor_role='tp-test-engineer' AND id>? AND id<=?",
                (task_id, bound_id, int(verification_event_id)),
            )}
            verification_matches = bool(
                original and 0 < bound_id <= int(verification_event_id)
                # Q02 permits supplementing an explicitly technical review, not
                # changing the existing review policy for ordinary full results.
                and (bound_id == int(verification_event_id) or scope == "technical")
                and bound_id in valid_ids and int(verification_event_id) in valid_ids
                and later_ids.issubset(valid_ids)
                and scope == event_policies.verification_scope(original.detail)
                and detail.get("subject_digest") == original.detail.get("subject_digest")
            )
        except (TypeError, ValueError):
            verification_matches = False
        if (str(detail.get('review_kind') or '').upper() in {'CODE', 'IMPLEMENTATION', 'ULTRA_REVIEW'}
                and type(count) is int and count >= 0 and artifact_ok
                and str(detail.get('change_set_id') or '') == change_set_id and verification_matches):
            return trusted
    raise ValueError('DELIVERY_CHANGE_SET_MISMATCH: current code review PASS is missing, invalid or stale')


def confirm_boundary(*, task_id: str, task_dir: str, db: Optional[str] = None,
                     confirmation_policy: Optional[str] = None) -> Dict[str, Any]:
    from . import db as dbmod
    from . import orchestration, record_first
    from .version import active_version

    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    route = orchestration.resolve_route(task_id, db_path=db_path, confirmation_policy=confirmation_policy)
    autonomy_pending = None
    if route.get('recommended_action') != 'await_confirmation':
        try:
            from . import autonomy_records
            autonomy_pending = autonomy_records.pending_workflow_confirmation_any(task_id, db_path)
        except Exception:
            autonomy_pending = None
    if autonomy_pending:
        confirmation_reason = str(autonomy_pending.get('confirmation_reason') or '')
        binding = autonomy_pending.get('confirmation_binding')
    else:
        confirmation_reason = str(route.get('confirmation_reason') or '')
        binding = route.get('confirmation_binding')
    if confirmation_reason not in {'EACH_STAGE_POLICY', 'MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION'}:
        raise ValueError('workflow confirm requires an active bound ordinary/material workflow confirmation')
    if not isinstance(binding, dict) or not binding:
        raise ValueError('workflow confirmation binding missing')

    tdir = record_first._task_dir(task_dir)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task['current_state'] or '')
        if current in record_first.TERMINAL_STATES:
            raise ValueError(f'terminal task cannot accept workflow confirmation: {current}')
        if current == 'BLOCKED' and not autonomy_pending:
            raise ValueError("task is BLOCKED; use 'task resume' after the blocker is resolved")
        now = dbmod.now_iso()
        flush_id = f'WF-CONFIRM-{uuid.uuid4().hex}'
        owner = str(task['owner_role'] or '')

        def writer(dbconn, transaction_id=''):
            detail = build_confirmation_detail(
                task_id=task_id, binding=binding, transaction_id=transaction_id,
                flush_id=flush_id, created_at=now, schema_version=active_version(),
            )
            if autonomy_pending:
                detail['autonomy_next_cycle_effective'] = True
                detail['autonomy_blocked_generation'] = autonomy_pending.get('generation')
            kind = str(binding.get('confirmation_kind') or 'ordinary')
            dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (task_id, 'WORKFLOW_CONFIRMATION', 'human_owner', confirmation_reason,
                 f"confirmed {kind} role boundary {binding['source_role']} -> {binding['target_role']}",
                 json.dumps(detail, ensure_ascii=False), active_version(), now),
            )
            dbconn.execute('UPDATE task SET updated_at=? WHERE task_id=?', (now, task_id))

        record_first._write_with_projection(
            conn, tdir, task, operation='workflow_confirm', target_state=current,
            owner_after=owner, flush_id=flush_id, writer=writer,
            summary=f"confirmed {binding.get('confirmation_kind', 'ordinary')} role boundary {binding['source_role']} -> {binding['target_role']}",
        )
    finally:
        conn.close()

    if autonomy_pending:
        return {
            'schema': 'tp-spec.workflow-route/v1', 'task_id': task_id,
            'recommended_action': 'next_cycle_resume', 'next_cycle_effective': True,
            'confirmation_reason': confirmation_reason, 'confirmation_binding': binding,
            'decision_schema': 'tp-spec.workflow-decision/v1', 'decision': 'AWAIT_NEXT_CYCLE',
            'requires_human': False, 'required_effects': [], 'reason': 'confirmed_next_cycle',
        }
    resolved = orchestration.resolve_route(task_id, db_path=db_path, confirmation_policy=confirmation_policy)
    if resolved.get('recommended_action') != 'dispatch_role':
        raise ValueError('workflow confirmation was recorded but current route no longer dispatches; re-run workflow next')
    return resolved

def _normalize_knowledge_reason_code(value: object) -> str:
    import re
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_").upper()
    return text or "KNOWLEDGE_SIGNAL"


def _task_knowledge_request_input(conn, *, task_id: str, verification_detail: Dict[str, Any],
                                  delivery_evidence: Iterable[str], task_dir: Optional[Path] = None,
                                  delivery_detail: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Signals are optional hints; each new READY delivery must assess Task inputs."""
    triggers: list[Dict[str, Any]] = []
    source_refs: list[str] = []
    verified_facts: list[str] = []

    def add_ref(value: object) -> None:
        ref = str(value or "").replace("\\", "/").strip()
        if ref and ref not in source_refs:
            source_refs.append(ref)

    rows = conn.execute(
        "SELECT id,event_type,actor_role,detail_json FROM task_event WHERE task_id=? ORDER BY id",
        (task_id,),
    ).fetchall()
    for row in rows:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except Exception:
            continue
        if not isinstance(detail, dict):
            continue
        event_type = str(row["event_type"] or "")
        actor = str(row["actor_role"] or "")
        producer = str(detail.get("producer") or "")
        trusted_source = False
        if event_type == "FACT" and producer == "record-first" and detail.get("transaction_id"):
            trusted_source = str(detail.get("operation") or "").upper() == "CHECKPOINT"
        elif event_type == "VERIFICATION_COMPLETED" and actor == "tp-test-engineer":
            trusted_source = producer == "record-first" and bool(detail.get("transaction_id"))
        elif event_type == "REVIEW_COMPLETED" and actor in {"tp-code-reviewer", "tp-software-architect"}:
            trusted_source = producer == "review_record" and bool(detail.get("transaction_id"))
        if trusted_source:
            for raw in detail.get("knowledge_signals") or []:
                if not isinstance(raw, dict):
                    continue
                code = _normalize_knowledge_reason_code(raw.get("type"))
                summary = str(raw.get("summary") or "").strip()
                if not summary:
                    continue
                triggers.append({
                    "reason_code": code,
                    "summary": summary,
                    "source_event_id": int(row["id"] or 0),
                })
                for value in raw.get("evidence") or []:
                    add_ref(value)
                for value in raw.get("source_refs") or []:
                    add_ref(value)
        if event_type == "DECISION" and actor == "human_owner":
            values = [str(detail.get("signal") or "").strip()]
            values.extend(str(x or "").strip() for x in (detail.get("signals") or []))
            if "workflow:knowledge-required" in values:
                triggers.append({
                    "reason_code": "HUMAN_OWNER_REQUIRED",
                    "summary": "human_owner 明确要求执行 Knowledge 收敛",
                    "source_event_id": int(row["id"] or 0),
                })

    for value in verification_detail.get("evidence") or []:
        add_ref(value)
    for item in verification_detail.get("evidence_items") or []:
        if isinstance(item, dict):
            add_ref(item.get("path"))
    for value in delivery_evidence or []:
        add_ref(value)
    for value in verification_detail.get("delivery_signals") or []:
        text = str(value or "").strip()
        if text and text not in verified_facts:
            verified_facts.append(text)

    if task_dir is not None and delivery_detail is not None:
        from .knowledge import convergence
        index = convergence.load_index(conn, task_id, task_dir, delivery_detail)
        # Missing explicit inputs are visible in the request; they do not become
        # an empty no-value success. task-inputs explains the recovery work.
        source_refs = [item["ref"] for item in index["items"] if item["id"].startswith("file:")]
        return {"learning_schema": convergence.SCHEMA, "input_index": index,
                "applicability": dict(delivery_detail.get("applicability") or {}),
                "trigger_reason_codes": sorted({"TASK_DELIVERY_REQUIRED", *[x["reason_code"] for x in triggers]}),
                "triggers": triggers, "source_refs": source_refs, "verified_facts": verified_facts}
    if not triggers:
        return None  # Compatibility-only callers without a new delivery context.
    # Request 需要可追溯来源。Verification PASS 本身应提供 evidence；若没有则 fail-closed。
    if not source_refs:
        raise ValueError("knowledge convergence request requires task/evidence source refs")
    reason_codes = sorted({str(x["reason_code"]) for x in triggers})
    return {
        "trigger_reason_codes": reason_codes,
        "triggers": triggers,
        "source_refs": source_refs,
        "verified_facts": verified_facts,
    }


def build_knowledge_request_detail(*, task_id: str, transaction_id: str, created_at: str,
                                   schema_version: str, delivery_event_id: int,
                                   verification_event_id: int, review_event_id: int,
                                   change_set_id: str, request_input: Dict[str, Any]) -> Dict[str, Any]:
    detail = {
        "transaction_id": transaction_id,
        "producer": "delivery_converge",
        "schema_version": schema_version,
        "task_id": task_id,
        "actor_role": "tp-integration-engineer",
        "created_at": created_at,
        "delivery_event_id": int(delivery_event_id),
        "verification_event_id": int(verification_event_id),
        "review_event_id": int(review_event_id),
        "change_set_id": str(change_set_id),
        "trigger_reason_codes": list(request_input.get("trigger_reason_codes") or []),
        "triggers": list(request_input.get("triggers") or []),
        "search_scope": "project+shared",
        "source_refs": list(request_input.get("source_refs") or []),
        "verified_facts": list(request_input.get("verified_facts") or []),
    }
    if request_input.get("learning_schema"):
        detail["learning_schema"] = request_input["learning_schema"]
        detail["input_index"] = request_input["input_index"]
        detail["applicability"] = dict(request_input["applicability"])
    return event_contract.add_event_semantics(
        detail,
        event_type="KNOWLEDGE_CONVERGENCE_REQUEST",
        operation="KNOWLEDGE_REQUEST",
        result_status="PENDING",
        producer="delivery_converge",
    )


def _delivery_prerequisites(conn, task_id: str, task_dir: Path, db_path: str):
    """Resolve actual duties once; L0/L1 don't inherit the full L2/L3 review chain."""
    from . import orchestration, record_first
    from .change_set import capture_change_set, same_bound_product_content
    from .digest import compute_verification_subject_digest
    from .delivery_contract import require_full_scope
    facts = orchestration._load_task_facts(task_id, db_path, connection=conn, task_dir=task_dir)
    route = orchestration.resolve_route(task_id, db_path=db_path, _facts=facts, task_dir=task_dir)
    selected = set(route.get("included_stages") or [])
    if not selected:
        raise ValueError("DELIVERY_APPLICABILITY_UNKNOWN: current routing did not resolve obligations")
    level = route["effective_level"]
    need_verify, need_review = bool(selected & {"verification", "review"}), "review" in selected
    verification = review = None
    development = record_first._latest_development_change_set(conn, task_id)
    if not development or not development["repo_roots"]:
        raise ValueError("DELIVERY_CHANGE_SET_REQUIRED: a development candidate must be recorded")
    require_full_scope(conn, task_id, development["detail"], development_event_id=development["event_id"])
    snapshot = capture_change_set(development["repo_roots"])
    if not same_bound_product_content(development["detail"], snapshot):
        raise ValueError("DELIVERY_CHANGE_SET_MISMATCH: current product differs from development candidate")
    subject = compute_verification_subject_digest(task_dir)
    if need_verify:
        verification, subject, snapshot, _ = _latest_trusted_verification(conn, task_id, task_dir)
    if need_review:
        review = _latest_trusted_code_review(conn, task_id, task_dir=task_dir, subject_digest=subject,
            change_set_id=snapshot["content_digest"], verification_event_id=int(verification.row["id"]))
    return {"verification": verification, "review": review, "subject_digest": subject,
            "snapshot": snapshot, "mode": "full" if level in {"L2", "L3"} else "lightweight",
            "applicability": {"verification": "REQUIRED" if need_verify else "NOT_REQUIRED",
                              "review": "REQUIRED" if need_review else "NOT_REQUIRED"}}


def record_delivery_result(*, task_id: str, task_dir: str, delivery_status: str,
                           reason: str, evidence: Optional[Iterable[str]] = None,
                           before_head: Optional[str] = None, after_head: Optional[str] = None,
                           merge_commit: Optional[str] = None,
                           recovery_condition: Optional[str] = None,
                           blocker_kind: Optional[str] = None,
                           responsibility: Optional[str] = None,
                           residual_risks: Optional[Iterable[str]] = None,
                           context_usage: Optional[Iterable[Dict[str, Any]]] = None,
                           db: Optional[str] = None) -> Dict[str, Any]:
    """Record/reuse the same verified delivery, without re-running professional work.

    The receipt's identity includes the effective prerequisites, acceptance outcomes,
    optional evidence bytes and current knowledge inputs. A later BLOCKED result is
    never skipped to find an older READY. No second receipt store is created.
    """
    from . import db as dbmod, record_first, recording, context_usage as usage_mod
    from .digest import compute_text_artifact_file_digest
    from .version import active_version
    from .delivery_contract import _concrete_reason
    status = str(delivery_status or "").upper()
    errors = []
    if status not in {"READY", "BLOCKED"}:
        errors.append("delivery_status must be READY|BLOCKED")
    if not _concrete_reason(reason):
        errors.append("concrete reason is required")
    if status == "BLOCKED":
        from .delivery_contract import DELIVERY_BLOCKER_KINDS
        if str(blocker_kind or "").upper() not in DELIVERY_BLOCKER_KINDS:
            errors.append("BLOCKED blocker_kind is required")
        if not str(recovery_condition or "").strip():
            errors.append("BLOCKED recovery_condition is required")
        if not str(responsibility or "").strip():
            errors.append("BLOCKED responsibility is required")
    if errors:
        raise ValueError("invalid Delivery Result: " + "; ".join(errors))
    paths = list(evidence or [])
    risks = list(residual_risks or [])
    if any(not isinstance(v, str) or not v.strip() for v in risks):
        raise ValueError("residual_risks must contain non-empty strings")
    usage, warnings = usage_mod.normalize_context_usage(context_usage)
    usage_mod.emit_warnings(warnings)
    tdir = record_first._task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        if task["current_state"] in record_first.TERMINAL_STATES or task["current_state"] == "BLOCKED":
            raise ValueError(f"task cannot accept delivery result in {task['current_state']}")
        now, flush_id = dbmod.now_iso(), f"DELIVERY-{uuid.uuid4().hex}"

        def inputs(dbconn):
            refreshed = record_first._load(dbconn, task_id)
            if refreshed["current_state"] not in {"NEW", "ACTIVE"}:
                raise ValueError(f"DELIVERY_STATE_CHANGED: {refreshed['current_state']}")
            prerequisites = _delivery_prerequisites(dbconn, task_id, tdir, db_path)
            verification, review = prerequisites["verification"], prerequisites["review"]
            cs = str(prerequisites["snapshot"]["content_digest"])
            evidence_paths, items = _checked_evidence_items(tdir, paths)
            if status == "READY":
                from .temp_artifacts import records_for_task
                from .delivery_contract import validate_task_temp_artifacts
                from .workitem_cmd import summarize_work_items
                problems = validate_task_temp_artifacts(records_for_task(task_id=task_id, project_id=task["project_id"]))
                works = summarize_work_items(dbconn, refreshed)
                problems.extend(works["issues"])
                from .work_units import integration_status
                problems.extend(integration_status(dbconn, refreshed)["issues"])
                problems.extend(f"WORK_PENDING: {w['item_id']}" for w in works["items"] if w["status"] != "COMPLETED")
                if problems:
                    raise ValueError("; ".join(problems))
                record_first.validate_final_acceptance(dbconn, task_id, tdir)
            from .delivery_contract import acceptance_evidence_items
            # BLOCKED can report an incomplete matrix; READY binds its actual
            # positive claims and executed SQL/results, including implicit refs.
            acceptance_items = acceptance_evidence_items(tdir) if status == "READY" else []
            args = dict(task_id=task_id, flush_id=flush_id, created_at=now, schema_version=active_version(),
                verification_event_id=int(verification.row["id"]) if verification else 0,
                verification_subject_digest=prerequisites["subject_digest"],
                verification_change_set_id=cs if verification else "",
                review_event_id=int(review.row["id"]) if review else 0, review_change_set_id=cs if review else "",
                change_set_id=cs, delivery_status=status, reason=reason, evidence=evidence_paths,
                evidence_items=items, residual_risks=risks, context_usage=usage,
                repo_snapshot={"before_head": before_head, "after_head": after_head, "merge_commit": merge_commit},
                recovery_condition=recovery_condition, blocker_kind=blocker_kind, responsibility=responsibility,
                delivery_mode=prerequisites["mode"], applicability=prerequisites["applicability"],
                acceptance_digest=compute_text_artifact_file_digest(tdir / "acceptance.md"),
                acceptance_evidence_items=acceptance_items)
            preview = build_delivery_detail(transaction_id="preview", **args)
            request = _task_knowledge_request_input(dbconn, task_id=task_id,
                verification_detail=dict(verification.detail) if verification else {},
                delivery_evidence=evidence_paths, task_dir=tdir, delivery_detail=preview) if status == "READY" else None
            stable = {k: v for k, v in preview.items() if k not in {
                "created_at", "flush_id", "transaction_id", "context_usage"}}
            # Knowledge source contents also participate in delivery-request reuse.
            sources = []
            if request and not request.get("learning_schema"):
                from .evidence import validate_evidence_path
                for ref in request["source_refs"]:
                    item = validate_evidence_path(tdir, ref)
                    if not item.ok:
                        raise ValueError(f"KNOWLEDGE_SOURCE_INVALID: {ref}: {item.error}")
                    sources.append(item.item)
            stable["knowledge_request_input"], stable["knowledge_source_items"] = request, sources
            digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return args, request, digest

        args, request_input, digest = inputs(conn)
        def replay(dbconn, current_digest):
            from .workflow_controls import trusted_event_detail
            row = dbconn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='DELIVERY_RESULT' "
                                 "AND actor_role='tp-integration-engineer' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
            if row is None:
                return None
            detail = trusted_event_detail(dict(row), event_type="DELIVERY_RESULT", producer="delivery_converge", actor="tp-integration-engineer")
            if detail is None or validate_delivery_result(detail) or detail.get("delivery_input_digest") != current_digest:
                return None
            from .delivery_contract import delivery_evidence_matches
            if not isinstance(detail.get("receipt"), dict) or not delivery_evidence_matches(detail, tdir):
                return None
            return {**detail["receipt"], "replayed": True, "facts_committed": False,
                    "delivery_event_id": int(row["id"]), "view_status": "NOT_REFRESHED"}

        previous = replay(conn, digest)
        if previous is not None:
            return previous
        written = {}
        response = {"task_id": task_id, "state": "ACTIVE", "phase": "delivery", "delivery_status": status,
                    "delivery_mode": args["delivery_mode"], "verification_event_id": args["verification_event_id"],
                    "verification_subject_digest": args["verification_subject_digest"], "review_event_id": args["review_event_id"],
                    "change_set_id": args["change_set_id"], "flush_id": flush_id}

        def recheck(dbconn):
            _, _, current_digest = inputs(dbconn)
            saved = replay(dbconn, current_digest)
            if saved is not None:
                raise recording.RequestReplay(saved)
            if current_digest != digest:
                raise ValueError("DELIVERY_INPUT_CHANGED: re-read prerequisites before convergence")

        def writer(dbconn, transaction_id=""):
            recheck(dbconn)
            detail = build_delivery_detail(transaction_id=transaction_id, **args)
            detail["delivery_input_digest"] = digest
            # Insert the request in this same transaction; the receipt never claims
            # Knowledge execution or Memory persistence merely from dispatching it.
            cursor = dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,evidence_path,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (task_id, 'DELIVERY_RESULT', task['current_stage'], 'delivery', 'tp-integration-engineer', status,
                 f"delivery status: {status} — {detail['reason']}", json.dumps(detail, ensure_ascii=False),
                 (detail.get('evidence') or [None])[0], active_version(), now))
            eid = int(cursor.lastrowid)
            request_id = None
            if request_input is not None:
                kd = build_knowledge_request_detail(task_id=task_id, transaction_id=transaction_id, created_at=now,
                    schema_version=active_version(), delivery_event_id=eid,
                    verification_event_id=args["verification_event_id"], review_event_id=args["review_event_id"],
                    change_set_id=args["change_set_id"], request_input=request_input)
                req = dbconn.execute(
                    'INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (task_id, 'KNOWLEDGE_CONVERGENCE_REQUEST', 'delivery', 'delivery', 'tp-integration-engineer',
                     'KNOWLEDGE_REQUIRED', 'Knowledge convergence requested from verified delivery facts',
                     json.dumps(kd, ensure_ascii=False), active_version(), now))
                request_id = int(req.lastrowid)
            written.update(response, knowledge_request_event_id=request_id, delivery_event_id=eid)
            detail["receipt"] = dict(written)
            dbconn.execute("UPDATE task_event SET detail_json=? WHERE id=?", (json.dumps(detail, ensure_ascii=False), eid))
            dbconn.execute("UPDATE task SET current_state='ACTIVE', current_stage='delivery', owner_role='tp-integration-engineer', updated_at=? WHERE task_id=?", (now, task_id))

        projection = record_first._write_with_projection(conn, tdir, task, operation="delivery_converge",
            target_state="ACTIVE", owner_after="tp-integration-engineer", flush_id=flush_id, writer=writer,
            summary=f"delivery status: {status}", before_prepare=recheck)
        return projection if projection.get("replayed") else {**written, **projection}
    finally:
        conn.close()
