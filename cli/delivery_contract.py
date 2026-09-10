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


def validate_task_temp_artifacts(records: List[Dict[str, Any]]) -> List[str]:
    """Delivery READY 前校验由 TP-Spec 登记的机器本地临时工件。"""
    statuses = {str(row.get("status") or "").upper() for row in records}
    errors: List[str] = []
    if "ACTIVE" in statuses:
        errors.append("TEMP_ARTIFACT_ACTIVE")
    if statuses & {"CLEANUP_PENDING", "INVALID"}:
        errors.append("TEMP_ARTIFACT_CLEANUP_PENDING")
    return errors


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
    for key in ("verification_change_set_id", "review_change_set_id", "change_set_id"):
        if not str(detail.get(key) or "").strip():
            errors.append(f"{key} is required")
    try:
        if int(detail.get("review_event_id") or 0) <= 0:
            errors.append("review_event_id is required")
    except (TypeError, ValueError):
        errors.append("review_event_id is invalid")
    ids = {
        str(detail.get("verification_change_set_id") or ""),
        str(detail.get("review_change_set_id") or ""),
        str(detail.get("change_set_id") or ""),
    }
    if "" not in ids and len(ids) != 1:
        errors.append("verification/review/delivery change_set_id must match")
    snap = detail.get("repo_snapshot")
    if snap is not None:
        if not isinstance(snap, dict):
            errors.append("repo_snapshot must be an object")
        else:
            for key in ("before_head", "after_head", "merge_commit"):
                value = snap.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"repo_snapshot.{key} must be a string")
    if status == "BLOCKED":
        kind = str(detail.get("blocker_kind") or "").upper()
        if kind not in DELIVERY_BLOCKER_KINDS:
            errors.append("BLOCKED blocker_kind must be one of: " + ", ".join(sorted(DELIVERY_BLOCKER_KINDS)))
        if not str(detail.get("recovery_condition") or "").strip():
            errors.append("recovery_condition is required for BLOCKED delivery")
        if not str(detail.get("responsibility") or "").strip():
            errors.append("responsibility is required for BLOCKED delivery")
    return errors


def delivery_result_matches_verification(detail: Dict[str, Any], event_id: int, subject_digest: str,
                                         change_set_id: str | None = None) -> bool:
    try:
        recorded_id = int(detail.get("verification_event_id") or 0)
    except (TypeError, ValueError):
        return False
    if recorded_id != int(event_id) or str(detail.get("verification_subject_digest") or "") != str(subject_digest or ""):
        return False
    if change_set_id is not None and str(detail.get("change_set_id") or "") != str(change_set_id):
        return False
    return True


def disposition_allows_pipeline_completion(detail: Dict[str, Any], *, deferred_accepted: bool = False) -> bool:
    # Compatibility function name retained inside the current module; the
    # semantics are now delivery readiness, not Knowledge disposition.
    return not validate_delivery_result(detail) and str(detail.get("delivery_status") or "").upper() == "READY"


def delivery_evidence_matches(detail: Dict[str, Any], task_dir) -> bool:
    """Recheck the original optional delivery attachments, never just their receipt."""
    from .evidence import validate_evidence_path
    paths, items = detail.get("evidence", []), detail.get("evidence_items", [])
    if not isinstance(paths, list) or not isinstance(items, list) or len(paths) != len(items):
        return False
    for path, item in zip(paths, items):
        if not isinstance(path, str) or not isinstance(item, dict) or item.get("path") != path or not item.get("sha256"):
            return False
        checked = validate_evidence_path(task_dir, item, require_evidence_dir=True)
        if not checked.ok or checked.sha256 != item["sha256"]:
            return False
    return True


def find_delivery_completion_event(events: List[Dict[str, Any]], *, verification_event: Dict[str, Any],
                                   current_subject_digest: str, task_dir=None) -> Dict[str, Any] | None:
    from .workflow_controls import trusted_event_detail

    verification_detail = trusted_event_detail(
        verification_event, event_type="VERIFICATION_COMPLETED", producer="record-first", actor="tp-test-engineer"
    )
    if verification_detail is None or str(verification_detail.get("decision") or "").upper() != "PASS":
        return None
    if str(verification_detail.get("subject_digest") or "") != str(current_subject_digest or ""):
        return None
    verification_id = int(verification_event.get("id") or 0)
    change_set_id = str(verification_detail.get("change_set_id") or "")
    if not verification_id or not change_set_id:
        return None
    for event in reversed(events):
        if event.get("event_type") != "DELIVERY_RESULT" or event.get("actor_role") != "tp-integration-engineer":
            continue
        detail = trusted_event_detail(
            event, event_type="DELIVERY_RESULT", producer="delivery_converge", actor="tp-integration-engineer"
        )
        if detail is None or validate_delivery_result(detail):
            return None
        if not delivery_result_matches_verification(detail, verification_id, current_subject_digest, change_set_id):
            return None
        if task_dir is not None and not delivery_evidence_matches(detail, task_dir):
            return None
        return event if str(detail.get("delivery_status") or "").upper() == "READY" else None
    return None


def repository_scope(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Known task scope, not a natural-language inference or an operation grant.

    Local checkpoints add known repositories. Only an explicit owner repository
    list on the existing SCOPE_CHANGE command replaces the current set. A plain
    scope note, public event or AC waiver must never erase repository history.
    """
    import json
    from pathlib import Path
    from .path_identity import canonical_path, path_identity_key
    from .workflow_controls import trusted_event_detail
    from . import event_contract

    roots: Dict[str, str] = {}
    scope_event_id = 0
    for event in events:
        essential = (event.get("event_type") == "SCOPE_CHANGE"
                     or (event.get("event_type") == "FACT" and event.get("actor_role") == "tp-development-engineer"))
        try:
            detail = json.loads(event.get("detail_json") or "{}")
        except (TypeError, ValueError) as exc:
            if essential:
                raise ValueError("DELIVERY_SCOPE_INVALID: unreadable scope record") from exc
            continue
        if not isinstance(detail, dict):
            if essential:
                raise ValueError("DELIVERY_SCOPE_INVALID: scope record is not an object")
            continue
        is_scope = event.get("event_type") == "SCOPE_CHANGE" and "repo_roots" in detail
        if is_scope:
            if trusted_event_detail(event, event_type="SCOPE_CHANGE", producer="task_scope_change", actor="human_owner") is None:
                raise ValueError("DELIVERY_SCOPE_INVALID: invalid owner repository scope identity")
            if not detail.get("scope_id") or not detail.get("summary"):
                raise ValueError("DELIVERY_SCOPE_INVALID: owner repository scope lacks its reason/source")
            values = detail.get("repo_roots")
        elif (event.get("event_type") == "FACT" and event.get("actor_role") == "tp-development-engineer"
              and detail.get("producer") == "record-first" and detail.get("transaction_id")
              and detail.get("schema_version") and detail.get("operation") == "CHECKPOINT"
              and detail.get("phase") == "development"
              and event_contract.normalize_event_semantics("FACT", detail)["result_status"] == "COMPLETED"):
            # Prefer canonical locators actually captured by Git, not caller aliases.
            snapshot = detail.get("change_set") or {}
            if not isinstance(snapshot, dict):
                raise ValueError("DELIVERY_SCOPE_INVALID: development snapshot is not an object")
            repos = snapshot.get("repositories") or []
            if not isinstance(repos, list) or any(not isinstance(r, dict) for r in repos):
                raise ValueError("DELIVERY_SCOPE_INVALID: development repositories are invalid")
            values = [r.get("root_locator") for r in repos] or detail.get("repo_roots") or []
            if not values:
                continue  # Existing legacy/no-ChangeSet gate remains responsible.
        else:
            continue
        if not isinstance(values, list) or not values or any(
            not isinstance(r, str) or not r.strip() or not Path(r).is_absolute() for r in values
        ):
            raise ValueError("DELIVERY_SCOPE_INVALID: repository scope needs non-empty absolute locators")
        if is_scope:
            roots = {}
            scope_event_id = int(event["id"])
        if not is_scope and scope_event_id and any(path_identity_key(value) not in roots for value in values):
            raise ValueError("REPOSITORY_SCOPE_MISMATCH: a development record exceeds the owner repository scope")
        for value in values:
            roots[path_identity_key(value)] = str(canonical_path(value))
    return {"repo_roots": [roots[key] for key in sorted(roots)], "scope_event_id": scope_event_id}


def load_repository_scope(conn, task_id: str) -> Dict[str, Any]:
    events = [dict(row) for row in conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type IN ('FACT','SCOPE_CHANGE') ORDER BY id", (task_id,)
    )]
    return repository_scope(events)


def full_scope_matches(scope: Dict[str, Any], detail: Dict[str, Any], *, development_event_id: int) -> bool:
    from .change_set import repository_keys
    roots = detail.get("repo_roots")
    return bool(isinstance(roots, list) and roots and all(isinstance(r, str) and r.strip() for r in roots)
                and repository_keys(roots) == repository_keys(scope["repo_roots"])
                and development_event_id > int(scope["scope_event_id"]))


def require_full_scope(conn, task_id: str, detail: Dict[str, Any], *, development_event_id: int) -> None:
    if not full_scope_matches(load_repository_scope(conn, task_id), detail, development_event_id=development_event_id):
        raise ValueError("FULL_SCOPE_CHECKPOINT_REQUIRED: record the complete effective repository scope before full verification/delivery; a local checkpoint is not whole-task coverage")


def require_scope_checkpoint(conn, task_id: str, *, development_event_id: int) -> None:
    scope = load_repository_scope(conn, task_id)
    if development_event_id <= scope["scope_event_id"]:
        raise ValueError("SCOPE_CHECKPOINT_REQUIRED: owner repository scope changed; record current development before verification")



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
