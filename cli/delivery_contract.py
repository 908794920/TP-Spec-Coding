from __future__ import annotations
import hashlib
from typing import Any, Dict, List

DELIVERY_DISPOSITIONS = {'CREATED', 'UPDATED', 'NO_CHANGE', 'DEFERRED', 'BLOCKED'}
DEFERRED_BLOCKER_KINDS = {'RESOLVER_UNAVAILABLE', 'CANONICAL_CONFLICT', 'DESTRUCTIVE_MERGE', 'INSUFFICIENT_EVIDENCE', 'HUMAN_DECISION'}


def _list(detail: Dict[str, Any], key: str) -> List[Any]:
    value = detail.get(key)
    return value if isinstance(value, list) else []


def _concrete_reason(value: Any) -> bool:
    text = str(value or '').strip()
    generic = {'无需更新', '无知识价值', '没有知识价值', 'no change', 'none', 'n/a'}
    return len(text) >= 12 and text.lower() not in generic


def validate_delivery_result(detail: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    disposition = str(detail.get('knowledge_disposition') or '').upper()
    if disposition not in DELIVERY_DISPOSITIONS:
        return ['knowledge_disposition must be CREATED|UPDATED|NO_CHANGE|DEFERRED|BLOCKED']
    if not _concrete_reason(detail.get('reason')):
        errors.append('concrete reason is required')
    if disposition in {'CREATED', 'UPDATED'}:
        required_lists = {
            'knowledge_refs': 'canonical knowledge ref', 'search_receipts': 'targeted search receipt',
            'lint_receipts': 'lint receipt', 'index_receipts': 'index update/verify receipt',
            'evidence': 'task evidence', 'source_refs': 'current source ref',
        }
        for key, label in required_lists.items():
            if not _list(detail, key):
                errors.append(f'{label} is required for {disposition}')
        for ref in _list(detail, 'knowledge_refs'):
            normalized = str(ref or '').replace('\\', '/').lower()
            if '.tp-spec/memory/' in normalized or normalized.startswith('memory/'):
                errors.append('Project Memory cannot substitute for a canonical Knowledge ref')
                break
        for receipt in _list(detail, 'search_receipts'):
            errors.extend(validate_receipt_payload('search', receipt))
        for receipt in _list(detail, 'lint_receipts'):
            errors.extend(validate_receipt_payload('lint', receipt))
        for receipt in _list(detail, 'index_receipts'):
            errors.extend(validate_receipt_payload('index', receipt))
    elif disposition == 'NO_CHANGE':
        if not _list(detail, 'search_receipts'):
            errors.append('targeted search receipt is required for NO_CHANGE')
        for receipt in _list(detail, 'search_receipts'):
            errors.extend(validate_receipt_payload('search', receipt))
    elif disposition == 'DEFERRED':
        blocker_kind = str(detail.get('blocker_kind') or '').upper()
        if blocker_kind not in DEFERRED_BLOCKER_KINDS:
            errors.append('DEFERRED blocker_kind must be one of: ' + ', '.join(sorted(DEFERRED_BLOCKER_KINDS)))
        if not str(detail.get('recovery_condition') or '').strip():
            errors.append('recovery_condition is required for DEFERRED')
        if not str(detail.get('responsibility') or '').strip():
            errors.append('responsibility is required for DEFERRED')
    return errors


def delivery_result_matches_verification(detail: Dict[str, Any], event_id: int, subject_digest: str) -> bool:
    try:
        recorded_id = int(detail.get('verification_event_id') or 0)
    except (TypeError, ValueError):
        return False
    return recorded_id == int(event_id) and str(detail.get('verification_subject_digest') or '') == str(subject_digest or '')


def disposition_allows_pipeline_completion(detail: Dict[str, Any], *, deferred_accepted: bool = False) -> bool:
    disposition = str(detail.get('knowledge_disposition') or '').upper()
    if validate_delivery_result(detail):
        return False
    if disposition in {'CREATED', 'UPDATED', 'NO_CHANGE'}:
        return True
    if disposition == 'DEFERRED':
        return bool(deferred_accepted)
    return False


def find_delivery_completion_event(events: List[Dict[str, Any]], *, verification_event: Dict[str, Any],
                                   current_subject_digest: str) -> Dict[str, Any] | None:
    from .workflow_controls import event_digest, trusted_event_detail

    verification_detail = trusted_event_detail(
        verification_event,
        event_type='VERIFICATION_COMPLETED',
        producer='record-first',
        actor='tp-verification-engineering',
    ) or trusted_event_detail(
        verification_event,
        event_type='VERIFICATION_COMPLETED',
        producer='commit',
        actor='tp-verification-engineering',
    )
    if verification_detail is None:
        return None
    if str(verification_detail.get('decision') or '').upper() != 'PASS':
        return None
    if str(verification_detail.get('subject_digest') or '') != str(current_subject_digest or ''):
        return None
    verification_id = int(verification_event.get('id') or 0)
    if not verification_id:
        return None

    for event in reversed(events):
        detail = trusted_event_detail(
            event,
            event_type='DELIVERY_RESULT',
            producer='delivery_converge',
            actor='tp-delivery-convergence',
        )
        if detail is None:
            continue
        if validate_delivery_result(detail):
            continue
        if not delivery_result_matches_verification(detail, verification_id, current_subject_digest):
            continue
        disposition = str(detail.get('knowledge_disposition') or '').upper()
        if disposition in {'CREATED', 'UPDATED', 'NO_CHANGE'}:
            return event
        if disposition == 'BLOCKED':
            return None
        if disposition == 'DEFERRED':
            target_id = int(event.get('id') or 0)
            target_digest = event_digest(event)
            for later in reversed(events):
                if int(later.get('id') or 0) <= target_id:
                    continue
                accepted = trusted_event_detail(
                    later,
                    event_type='DELIVERY_DEFERRED_ACCEPTED',
                    producer='delivery_deferred_accept',
                    actor='human_owner',
                )
                if accepted is None:
                    continue
                if int(accepted.get('delivery_event_id') or 0) == target_id and str(accepted.get('delivery_event_digest') or '') == target_digest:
                    return event
            return None
    return None



def validate_canonical_binding(frontmatter: Dict[str, Any], *, task_id: str,
                               evidence_paths: List[str], source_refs: List[str]) -> List[str]:
    """Validate that one exact canonical note carries this Task's traceability.

    This is deliberately local: the caller resolves the exact canonical path/ID first,
    so validation never needs a full Knowledge scan.
    """
    errors: List[str] = []
    if not isinstance(frontmatter, dict):
        return ['canonical frontmatter must be a mapping']
    if frontmatter.get('canonical') is not True:
        errors.append('knowledge ref must resolve to canonical: true')
    evidence_refs = frontmatter.get('evidence_refs') or []
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    evidence_refs = [x for x in evidence_refs if isinstance(x, dict)]
    task_refs = [x for x in evidence_refs if str(x.get('type') or '') == 'task' and str(x.get('ref') or '') == task_id]
    if not task_refs:
        errors.append(f'canonical must bind task evidence ref {task_id}')
    normalized_evidence = {str(x or '').replace('\\', '/').strip() for x in evidence_paths if str(x or '').strip()}
    if normalized_evidence:
        locators = {str(x.get('locator') or '').replace('\\', '/').strip() for x in task_refs}
        if not (normalized_evidence & locators):
            errors.append('canonical task evidence ref must bind at least one current Task evidence locator')
    declared_source_refs = {str(x or '').strip() for x in (frontmatter.get('source_refs') or []) if str(x or '').strip()}
    evidence_tokens = set(declared_source_refs)
    for item in evidence_refs:
        for key in ('ref', 'locator'):
            value = str(item.get(key) or '').strip()
            if value:
                evidence_tokens.add(value)
    for ref in source_refs:
        if str(ref or '').strip() not in evidence_tokens:
            errors.append(f'canonical missing source/code ref: {ref}')
    return errors

def validate_receipt_payload(kind: str, payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(payload, dict):
        return [f'{kind} receipt must be a JSON object']
    kind0 = str(kind or '').lower()
    if kind0 == 'search':
        if payload.get('schema') != 'tp-spec.knowledge-search/v1':
            errors.append('search receipt schema must be tp-spec.knowledge-search/v1')
        if str(payload.get('status') or '').upper() != 'PASS':
            errors.append('search receipt status must be PASS')
        if str(payload.get('scope') or '').lower() not in {'project', 'project+shared'}:
            errors.append('search receipt must use project/current project + shared scope, not global')
        query = str(payload.get('query') or '').strip()
        if not query:
            errors.append('search receipt must include the executed query')
        expected_hash = hashlib.sha256(query.encode('utf-8')).hexdigest() if query else ''
        if not expected_hash or str(payload.get('query_hash') or '') != expected_hash:
            errors.append('search receipt query_hash must match the executed query')
        results = payload.get('results')
        if not isinstance(results, list):
            errors.append('search receipt results must be a list')
        try:
            count = int(payload.get('count'))
        except (TypeError, ValueError):
            count = -1
        if isinstance(results, list) and count != len(results):
            errors.append('search receipt count must match results length')
    elif kind0 == 'lint':
        if payload.get('schema') != 'tp-spec.knowledge-lint/v1':
            errors.append('lint receipt schema must be tp-spec.knowledge-lint/v1')
        if str(payload.get('status') or '').upper() != 'PASS':
            errors.append('lint receipt status must be PASS')
    elif kind0 == 'index':
        if str(payload.get('status') or '').upper() != 'PASS':
            errors.append('index receipt status must be PASS')
        if payload.get('fresh') is not True:
            errors.append('index receipt must prove fresh=true')
    else:
        errors.append(f'unknown receipt kind: {kind}')
    return errors
