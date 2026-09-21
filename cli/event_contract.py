# -*- coding: utf-8 -*-
"""Structured task-event semantic contract.

Runtime/event_policies remains authoritative for who may write an event.  This
module only normalizes machine result semantics used by workflow and workbench.
Human summaries are intentionally absent from this API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import config_loader

EVENT_SCHEMA = "tp-spec.event-semantics/v1"


def _upper(value: object) -> str:
    return str(value or "").strip().upper()


def load_event_semantics_contract() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    data = config_loader.load_config(
        "governance/event-semantics.yaml", schema_name="event-semantics", base_root=root, use_cache=True
    )
    if data.get("event_schema") != EVENT_SCHEMA:
        raise ValueError("event semantics schema mismatch")
    return data


def _controlled(name: str) -> set[str]:
    contract = load_event_semantics_contract()
    return {_upper(v) for v in ((contract.get("controlled") or {}).get(name) or [])}


def normalize_event_semantics(event_type: str, detail: Dict[str, Any] | None) -> Dict[str, str]:
    """Return deterministic machine semantics without inspecting summary text."""
    d = dict(detail or {})
    et = _upper(event_type)
    operation = _upper(d.get("operation"))
    decision = _upper(d.get("decision"))
    result_status = _upper(d.get("result_status"))
    producer = str(d.get("producer") or "").strip()
    schema = str(d.get("schema") or "").strip()

    source_kind = "structured" if schema == EVENT_SCHEMA else "legacy_untyped"

    # Deterministic legacy adapters use machine fields from the old contract,
    # never human-readable summary text.
    if source_kind != "structured":
        if et == "FACT" and operation == "CHECKPOINT" and producer == "record-first":
            source_kind = "legacy_contract"
            if not result_status:
                result_status = "COMPLETED"
        elif et in {"VERIFICATION_COMPLETED", "REVIEW_COMPLETED"} and decision:
            source_kind = "legacy_contract"
            if not result_status:
                result_status = "BLOCKED" if decision == "BLOCKED" else "COMPLETED"
        elif et == "WORK_SESSION_STARTED":
            source_kind = "legacy_contract"
            if not result_status:
                result_status = "STARTED"
        elif et == "WORK_SESSION_ENDED" and producer == "work_session":
            source_kind = "legacy_contract"
            if not result_status:
                result_status = "COMPLETED"
        elif et == "BLOCKER" and operation == "BLOCK":
            source_kind = "legacy_contract"
            if not result_status:
                result_status = "BLOCKED"

    if not result_status:
        result_status = "NOT_RECORDED"
    if not decision:
        decision = ""

    return {
        "schema": schema,
        "operation": operation,
        "phase": str(d.get("phase") or "").strip(),
        "milestone_id": str(d.get("milestone_id") or "").strip(),
        "result_status": result_status,
        "decision": decision,
        "reason_code": str(d.get("reason_code") or "").strip(),
        "producer": producer,
        "source_kind": source_kind,
    }


def inapplicable_prerequisite_binding(event_type: str, detail: Dict[str, Any], field: str) -> bool:
    """Zero IDs mean an explicitly inapplicable P5A prerequisite, never a PASS.

    The current-delivery resolver separately checks these declarations against
    the effective route. Legacy requests still require both positive bindings.
    """
    kind = {"verification_event_id": "verification", "review_event_id": "review",
            "verification_change_set_id": "verification", "review_change_set_id": "review"}.get(field)
    adopted = (_upper(event_type) == "KNOWLEDGE_CONVERGENCE_REQUEST"
               and detail.get("learning_schema") == "tp-spec.task-learning/v1") or (
                   _upper(event_type) == "DELIVERY_RESULT" and detail.get("closeout_schema") == "tp-spec.closeout/v1")
    if not kind or not adopted or not isinstance(detail.get("applicability"), dict):
        return False
    event_id = detail.get(kind + "_event_id")
    expected = 0 if field.endswith("_event_id") else ""
    return (type(event_id) is int and event_id == 0 and detail.get(field) == expected
            and detail["applicability"].get(kind) == "NOT_REQUIRED")



def validate_event_semantics(event_type: str, detail: Dict[str, Any] | None) -> List[str]:
    d = dict(detail or {})
    errors: List[str] = []
    if d.get("schema") != EVENT_SCHEMA:
        errors.append(f"schema must be {EVENT_SCHEMA}")
    result_status = _upper(d.get("result_status"))
    decision = _upper(d.get("decision"))
    operation = _upper(d.get("operation"))
    if result_status and result_status not in _controlled("result_status"):
        errors.append(f"invalid result_status: {result_status}")
    if decision and decision not in _controlled("decision"):
        errors.append(f"invalid decision: {decision}")
    if operation and operation not in _controlled("operations"):
        errors.append(f"invalid operation: {operation}")

    family = (load_event_semantics_contract().get("event_families") or {}).get(_upper(event_type)) or {}
    required = list(family.get("required") or [])
    if _upper(event_type) == "FACT" and operation == "CHECKPOINT":
        required = list(family.get("checkpoint_required") or [])
    if _upper(event_type) == "REVIEW_COMPLETED":
        review_kind = _upper(d.get("review_kind"))
        if review_kind in {"CODE", "IMPLEMENTATION", "ULTRA_REVIEW"}:
            required.extend(["change_set_id", "verification_event_id"])
    for field in required:
        if not str(d.get(field) or "").strip() and not inapplicable_prerequisite_binding(event_type, d, field):
            errors.append(f"{_upper(event_type)} requires {field}")
    expected_operation = _upper(family.get("operation"))
    if expected_operation and operation and operation != expected_operation:
        errors.append(f"{_upper(event_type)} operation must be {expected_operation}")
    return errors


def add_event_semantics(detail: Dict[str, Any] | None, *, event_type: str, operation: str,
                        result_status: str, decision: str | None = None,
                        producer: str | None = None, phase: str | None = None,
                        milestone_id: str | None = None, reason_code: str | None = None) -> Dict[str, Any]:
    """Attach the current semantic envelope to an existing event detail."""
    out = dict(detail or {})
    out["schema"] = EVENT_SCHEMA
    out["operation"] = _upper(operation)
    out["result_status"] = _upper(result_status)
    if decision is not None:
        out["decision"] = _upper(decision)
    if producer and not out.get("producer"):
        out["producer"] = producer
    if phase is not None:
        out["phase"] = str(phase)
    if milestone_id is not None:
        out["milestone_id"] = str(milestone_id)
    if reason_code is not None:
        out["reason_code"] = str(reason_code)
    errors = validate_event_semantics(event_type, out)
    if errors:
        raise ValueError("invalid event semantics: " + "; ".join(errors))
    return out


def event_result_status(event_type: str, detail: Dict[str, Any] | None) -> str:
    return normalize_event_semantics(event_type, detail)["result_status"]
