from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .delivery_contract import validate_delivery_result


def build_confirmation_detail(*, task_id: str, binding: Dict[str, Any], transaction_id: str,
                              flush_id: str, created_at: str, schema_version: str) -> Dict[str, Any]:
    return {
        'operation': 'WORKFLOW_CONFIRM',
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
                          delivery_status: str, reason: str,
                          evidence: Optional[Iterable[str]] = None,
                          residual_risks: Optional[Iterable[str]] = None,
                          evidence_items: Optional[Iterable[Dict[str, Any]]] = None,
                          context_usage: Optional[Iterable[Dict[str, Any]]] = None,
                          repo_snapshot: Optional[Dict[str, Any]] = None,
                          knowledge_handoff: Optional[Dict[str, Any]] = None,
                          recovery_condition: Optional[str] = None,
                          blocker_kind: Optional[str] = None,
                          responsibility: Optional[str] = None) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        'operation': 'DELIVERY_CONVERGE',
        'flush_id': flush_id,
        'transaction_id': transaction_id,
        'producer': 'delivery_converge',
        'schema_version': schema_version,
        'task_id': task_id,
        'actor_role': 'tp-integration-engineer',
        'created_at': created_at,
        'verification_event_id': int(verification_event_id),
        'verification_subject_digest': str(verification_subject_digest),
        'delivery_status': str(delivery_status or '').upper(),
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
    if knowledge_handoff is not None:
        detail['knowledge_handoff'] = dict(knowledge_handoff)
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
    from .digest import compute_verification_subject_digest

    current_subject = compute_verification_subject_digest(task_dir)
    trusted = event_policies.load_trusted_governance_event(
        conn,
        task_id,
        event_type='VERIFICATION_COMPLETED',
        actor='tp-test-engineer',
        decision='PASS',
        expected_subject_digest=current_subject,
        evidence_dir=task_dir,
    )
    if trusted is None:
        raise ValueError('DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS')
    return trusted, current_subject


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

def _compact_knowledge_handoff(*, task_id: str, verification_event_id: int,
                               verification_subject_digest: str,
                               verification_detail: Dict[str, Any],
                               evidence: Iterable[str], residual_risks: Iterable[str]) -> Dict[str, Any]:
    """Build the small verified fact package handed from Delivery to Knowledge.

    Integration does not decide durable Knowledge disposition.  It merely binds
    already-trusted verification facts so tp-knowledge can cheaply decide
    NO_CHANGE versus deferred synthesis without re-reading the Task/repository.
    """
    return {
        'schema': 'tp-spec.knowledge-task-handoff/v1',
        'task_id': task_id,
        'verification_event_id': int(verification_event_id),
        'verification_subject_digest': str(verification_subject_digest),
        'verified_facts': list(verification_detail.get('delivery_signals') or []),
        'reusable_findings': list(verification_detail.get('knowledge_signals') or []),
        'evidence': list(evidence or []),
        'residual_risks': list(residual_risks or []),
    }


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

    Knowledge convergence is deliberately handed off rather than executed here;
    delivery completion must never wait for an expensive Knowledge synthesis.
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

        verification, subject_digest = _latest_trusted_verification(conn, task_id, tdir)
        evidence_paths, evidence_items = _checked_evidence_items(tdir, evidence)
        residual_risk_list = list(residual_risks or [])
        now = dbmod.now_iso()
        flush_id = f'DELIVERY-{uuid.uuid4().hex}'
        verification_id = int(verification.row['id'])
        verification_detail = dict(verification.detail or {})
        repo_snapshot = {
            'before_head': str(before_head).strip() if before_head else None,
            'after_head': str(after_head).strip() if after_head else None,
            'merge_commit': str(merge_commit).strip() if merge_commit else None,
        }
        knowledge_handoff = _compact_knowledge_handoff(
            task_id=task_id,
            verification_event_id=verification_id,
            verification_subject_digest=subject_digest,
            verification_detail=verification_detail,
            evidence=evidence_paths,
            residual_risks=residual_risk_list,
        )
        detail_args = dict(
            task_id=task_id,
            flush_id=flush_id,
            created_at=now,
            schema_version=active_version(),
            verification_event_id=verification_id,
            verification_subject_digest=subject_digest,
            delivery_status=delivery_status,
            reason=reason,
            evidence=evidence_paths,
            residual_risks=residual_risk_list,
            evidence_items=evidence_items,
            context_usage=caller_usage,
            repo_snapshot=repo_snapshot,
            knowledge_handoff=knowledge_handoff,
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

        def writer(dbconn, transaction_id=''):
            detail = build_delivery_detail(transaction_id=transaction_id, **detail_args)
            status = str(detail['delivery_status']).upper()
            dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,evidence_path,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (task_id, 'DELIVERY_RESULT', task['current_stage'], 'delivery', 'tp-integration-engineer',
                 status,
                 f"delivery status: {status} — {detail['reason']}",
                 json.dumps(detail, ensure_ascii=False),
                 (detail.get('evidence') or [None])[0],
                 active_version(), now),
            )
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
            'knowledge_handoff': knowledge_handoff,
            'flush_id': flush_id,
        }
    finally:
        conn.close()

