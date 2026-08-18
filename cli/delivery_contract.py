from __future__ import annotations
import hashlib
from typing import Any, Dict, List

DELIVERY_STATUSES = {"READY", "BLOCKED"}
DELIVERY_BLOCKER_KINDS = {
    "INTEGRATION_CONFLICT", "VERIFICATION_STALE", "WORKSPACE_DIRTY",
    "GIT_STATE_INVALID", "HUMAN_DECISION", "OTHER",
}


def _concrete_reason(value: Any) -> bool:
    text = str(value or "").strip()
    generic = {"ready", "blocked", "done", "ok", "none", "n/a"}
    return len(text) >= 12 and text.lower() not in generic


def validate_delivery_result(detail: Dict[str, Any]) -> List[str]:
    """Validate Integration-owned delivery facts.

    Knowledge convergence is deliberately not part of this contract. A READY
    delivery may complete the Task while tp-knowledge processes its compact
    handoff separately.
    """
    errors: List[str] = []
    status = str(detail.get("delivery_status") or "").upper()
    if status not in DELIVERY_STATUSES:
        return ["delivery_status must be READY|BLOCKED"]
    if not _concrete_reason(detail.get("reason")):
        errors.append("concrete reason is required")
    try:
        if int(detail.get("verification_event_id") or 0) <= 0:
            errors.append("verification_event_id is required")
    except (TypeError, ValueError):
        errors.append("verification_event_id is invalid")
    if not str(detail.get("verification_subject_digest") or "").strip():
        errors.append("verification_subject_digest is required")
    snap = detail.get("repo_snapshot")
    if snap is not None:
        if not isinstance(snap, dict):
            errors.append("repo_snapshot must be an object")
        else:
            for key in ("before_head", "after_head", "merge_commit"):
                value = snap.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"repo_snapshot.{key} must be a string")
    handoff = detail.get("knowledge_handoff")
    if handoff is not None and not isinstance(handoff, dict):
        errors.append("knowledge_handoff must be an object")
    if status == "BLOCKED":
        kind = str(detail.get("blocker_kind") or "").upper()
        if kind not in DELIVERY_BLOCKER_KINDS:
            errors.append("BLOCKED blocker_kind must be one of: " + ", ".join(sorted(DELIVERY_BLOCKER_KINDS)))
        if not str(detail.get("recovery_condition") or "").strip():
            errors.append("recovery_condition is required for BLOCKED delivery")
        if not str(detail.get("responsibility") or "").strip():
            errors.append("responsibility is required for BLOCKED delivery")
    return errors


def delivery_result_matches_verification(detail: Dict[str, Any], event_id: int, subject_digest: str) -> bool:
    try:
        recorded_id = int(detail.get("verification_event_id") or 0)
    except (TypeError, ValueError):
        return False
    return recorded_id == int(event_id) and str(detail.get("verification_subject_digest") or "") == str(subject_digest or "")


def disposition_allows_pipeline_completion(detail: Dict[str, Any], *, deferred_accepted: bool = False) -> bool:
    # Compatibility function name retained inside the current module; the
    # semantics are now delivery readiness, not Knowledge disposition.
    return not validate_delivery_result(detail) and str(detail.get("delivery_status") or "").upper() == "READY"


def find_delivery_completion_event(events: List[Dict[str, Any]], *, verification_event: Dict[str, Any],
                                   current_subject_digest: str) -> Dict[str, Any] | None:
    from .workflow_controls import trusted_event_detail

    verification_detail = trusted_event_detail(
        verification_event, event_type="VERIFICATION_COMPLETED", producer="record-first", actor="tp-test-engineer"
    )
    if verification_detail is None or str(verification_detail.get("decision") or "").upper() != "PASS":
        return None
    if str(verification_detail.get("subject_digest") or "") != str(current_subject_digest or ""):
        return None
    verification_id = int(verification_event.get("id") or 0)
    if not verification_id:
        return None
    for event in reversed(events):
        detail = trusted_event_detail(
            event, event_type="DELIVERY_RESULT", producer="delivery_converge", actor="tp-integration-engineer"
        )
        if detail is None or validate_delivery_result(detail):
            continue
        if not delivery_result_matches_verification(detail, verification_id, current_subject_digest):
            continue
        return event if str(detail.get("delivery_status") or "").upper() == "READY" else None
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
