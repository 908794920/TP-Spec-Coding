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
                          responsibility: Optional[str] = None) -> Dict[str, Any]:
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
        'reason': str(reason or '').strip(),
    }
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
    trusted = event_policies.load_trusted_governance_event(
        conn, task_id, event_type='VERIFICATION_COMPLETED', actor='tp-test-engineer',
        decision='PASS', expected_subject_digest=current_subject, evidence_dir=task_dir,
    )
    if trusted is None:
        raise ValueError('DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS')
    detail = dict(trusted.detail or {})
    change_set_id = str(detail.get('change_set_id') or '').strip()
    repo_roots = [str(value).strip() for value in (detail.get('repo_roots') or []) if str(value).strip()]
    if not change_set_id or not repo_roots:
        raise ValueError('DELIVERY_CHANGE_SET_MISMATCH: verification is not bound to a product change set')
    current_change_set = capture_change_set(repo_roots)
    if str(current_change_set.get('content_digest') or '') != change_set_id:
        raise ValueError('DELIVERY_CHANGE_SET_MISMATCH: current product content differs from verification')
    return trusted, current_subject, current_change_set, repo_roots


def _latest_trusted_code_review(conn, task_id: str, *, subject_digest: str,
                                change_set_id: str, verification_event_id: int):
    from . import event_policies

    candidates = []
    for kind in ('CODE', 'IMPLEMENTATION', 'ULTRA_REVIEW'):
        trusted = event_policies.load_trusted_governance_event(
            conn, task_id, event_type='REVIEW_COMPLETED', actor='tp-code-reviewer',
            decision='PASS', review_kind=kind, expected_subject_digest=subject_digest,
        )
        if trusted is not None:
            candidates.append(trusted)
    candidates.sort(key=lambda item: int(item.row['id']), reverse=True)
    for trusted in candidates:
        detail = dict(trusted.detail or {})
        if str(detail.get('change_set_id') or '') != change_set_id:
            continue
        try:
            bound_verification_id = int(detail.get('verification_event_id') or 0)
        except (TypeError, ValueError):
            continue
        if bound_verification_id != int(verification_event_id):
            continue
        return trusted
    raise ValueError('DELIVERY_CHANGE_SET_MISMATCH: current code review PASS is missing or stale')


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
                                  delivery_evidence: Iterable[str]) -> Optional[Dict[str, Any]]:
    """从可信 Runtime 事实提取 Knowledge 请求输入；没有显式信号时返回 None。"""
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

    if not triggers:
        return None
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
    return event_contract.add_event_semantics(
        detail,
        event_type="KNOWLEDGE_CONVERGENCE_REQUEST",
        operation="KNOWLEDGE_REQUEST",
        result_status="PENDING",
        producer="delivery_converge",
    )


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
    """Record Integration-owned delivery facts bound to the latest Test PASS.

    Delivery 只记录已验证的交付事实；存在显式长期知识信号时，同事务写入
    KNOWLEDGE_CONVERGENCE_REQUEST，由 tp-knowledge 独立收敛。
    """
    from . import db as dbmod
    from . import record_first
    from . import context_usage as context_usage_mod
    from .version import active_version

    caller_usage, caller_warnings = context_usage_mod.normalize_context_usage(context_usage)
    context_usage_mod.emit_warnings(caller_warnings)
    tdir = record_first._task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task['current_state'] or '')
        if current in record_first.TERMINAL_STATES:
            raise ValueError(f'terminal task cannot accept delivery result: {current}')
        if current == 'BLOCKED':
            raise ValueError('task is BLOCKED; resolve the blocker before delivery convergence')
        effective_level = max(
            str(task['risk_level'] or 'L0'), str(task['flow_level'] or 'L0'),
            key=lambda value: ('L0', 'L1', 'L2', 'L3').index(value) if value in ('L0', 'L1', 'L2', 'L3') else -1,
        )
        if effective_level not in {'L2', 'L3'}:
            raise ValueError('structured delivery convergence applies only to L2/L3 tasks')

        if str(delivery_status or '').upper() == 'READY':
            from . import temp_artifacts
            from .delivery_contract import validate_task_temp_artifacts
            temp_errors = validate_task_temp_artifacts(
                temp_artifacts.records_for_task(
                    task_id=task_id, project_id=str(task['project_id'] or '') or None
                )
            )
            if temp_errors:
                raise ValueError('; '.join(temp_errors))

        verification, subject_digest, current_change_set, repo_roots = _latest_trusted_verification(conn, task_id, tdir)
        verification_detail = dict(verification.detail or {})
        change_set_id = str(verification_detail.get('change_set_id') or '')
        review = _latest_trusted_code_review(
            conn, task_id, subject_digest=subject_digest, change_set_id=change_set_id,
            verification_event_id=int(verification.row['id']),
        )
        review_detail = dict(review.detail or {})
        evidence_paths, evidence_items = _checked_evidence_items(tdir, evidence)
        residual_risk_list = list(residual_risks or [])
        now = dbmod.now_iso()
        flush_id = f'DELIVERY-{uuid.uuid4().hex}'
        verification_id = int(verification.row['id'])
        review_id = int(review.row['id'])
        repo_snapshot = {
            'before_head': str(before_head).strip() if before_head else None,
            'after_head': str(after_head).strip() if after_head else None,
            'merge_commit': str(merge_commit).strip() if merge_commit else None,
        }
        knowledge_request_input = _task_knowledge_request_input(
            conn, task_id=task_id, verification_detail=verification_detail,
            delivery_evidence=evidence_paths,
        ) if str(delivery_status or '').upper() == 'READY' else None
        detail_args = dict(
            task_id=task_id,
            flush_id=flush_id,
            created_at=now,
            schema_version=active_version(),
            verification_event_id=verification_id,
            verification_subject_digest=subject_digest,
            verification_change_set_id=change_set_id,
            review_event_id=review_id,
            review_change_set_id=str(review_detail.get('change_set_id') or ''),
            change_set_id=str(current_change_set.get('content_digest') or ''),
            delivery_status=delivery_status,
            reason=reason,
            evidence=evidence_paths,
            residual_risks=residual_risk_list,
            evidence_items=evidence_items,
            context_usage=caller_usage,
            repo_snapshot=repo_snapshot,
            recovery_condition=recovery_condition,
            blocker_kind=blocker_kind,
            responsibility=responsibility,
        )

        # Validate before entering the durable write so bad Integration facts do
        # not create half-written state/events.
        preview = build_delivery_detail(transaction_id='preview', **detail_args)
        errors = validate_delivery_result(preview)
        if errors:
            raise ValueError('invalid Delivery Result: ' + '; '.join(errors))

        written: Dict[str, Any] = {}

        def writer(dbconn, transaction_id=''):
            detail = build_delivery_detail(transaction_id=transaction_id, **detail_args)
            status = str(detail['delivery_status']).upper()
            cursor = dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,evidence_path,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (task_id, 'DELIVERY_RESULT', task['current_stage'], 'delivery', 'tp-integration-engineer',
                 status,
                 f"delivery status: {status} — {detail['reason']}",
                 json.dumps(detail, ensure_ascii=False),
                 (detail.get('evidence') or [None])[0],
                 active_version(), now),
            )
            delivery_event_id = int(cursor.lastrowid)
            if status == 'READY' and knowledge_request_input is not None:
                request_detail = build_knowledge_request_detail(
                    task_id=task_id, transaction_id=transaction_id, created_at=now,
                    schema_version=active_version(), delivery_event_id=delivery_event_id,
                    verification_event_id=verification_id, review_event_id=review_id,
                    change_set_id=str(current_change_set.get('content_digest') or ''),
                    request_input=knowledge_request_input,
                )
                request_cursor = dbconn.execute(
                    'INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (task_id, 'KNOWLEDGE_CONVERGENCE_REQUEST', 'delivery', 'delivery',
                     'tp-integration-engineer', 'KNOWLEDGE_REQUIRED',
                     'Knowledge convergence requested from verified delivery facts',
                     json.dumps(request_detail, ensure_ascii=False), active_version(), now),
                )
                written['knowledge_request_event_id'] = int(request_cursor.lastrowid)
            dbconn.execute(
                "UPDATE task SET current_state='ACTIVE', current_stage='delivery', owner_role='tp-integration-engineer', updated_at=? WHERE task_id=?",
                (now, task_id),
            )

        record_first._write_with_projection(
            conn, tdir, task, operation='delivery_converge', target_state='ACTIVE',
            owner_after='tp-integration-engineer', flush_id=flush_id, writer=writer,
            summary=f'delivery status: {str(delivery_status).upper()}',
        )
        return {
            'task_id': task_id,
            'state': 'ACTIVE',
            'phase': 'delivery',
            'delivery_status': str(delivery_status).upper(),
            'verification_event_id': verification_id,
            'verification_subject_digest': subject_digest,
            'review_event_id': review_id,
            'change_set_id': change_set_id,
            'knowledge_request_event_id': written.get('knowledge_request_event_id'),
            'flush_id': flush_id,
        }
    finally:
        conn.close()

