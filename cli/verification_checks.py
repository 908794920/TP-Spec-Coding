from __future__ import annotations

import json

from .evidence import validate_evidence_path
from .yaml_checks import check_acceptance_yaml


_TEXT_FIELDS = ("id", "ac", "description", "evidence", "owner_statement",
                "reverify_owner", "trigger", "residual_risk")


def normalize_deferred_checks(values):
    """Validate the explicit scope and owner-source assertion before request replay."""
    checks = []
    ids = set()
    for value in values or ():
        if not isinstance(value, dict) or set(value) != {*_TEXT_FIELDS, "source_event"}:
            raise ValueError("DEFERRED_CHECK_INVALID: required fields are " + ", ".join((*_TEXT_FIELDS, "source_event")))
        if any(not isinstance(value[field], str) or not value[field].strip() for field in _TEXT_FIELDS):
            raise ValueError("DEFERRED_CHECK_INVALID: text fields must be non-empty")
        event_id = value["source_event"]
        if type(event_id) is not int or event_id <= 0:
            raise ValueError("DEFERRED_CHECK_INVALID: source_event must be a positive event ID")
        check = {field: value[field].strip() for field in _TEXT_FIELDS}
        if check["id"] in ids:
            raise ValueError(f"DEFERRED_CHECK_INVALID: duplicate check ID {check['id']}")
        ids.add(check["id"])
        checks.append({**check, "source_event": event_id})
    return checks


def bind_deferred_checks(conn, task_id, task_dir, checks, acceptance_text):
    """Bind the owner's direct FACT or its explicit project-manager transcription."""
    declared = check_acceptance_yaml(acceptance_text, enforce_completion=False, allow_human_pending=True).acceptance_ids
    bound = []
    for check in checks:
        if declared.count(check["ac"]) != 1:
            raise ValueError(f"DEFERRED_CHECK_INVALID: expected one declared acceptance ID {check['ac']}")
        row = conn.execute(
            "SELECT actor_role, detail_json, evidence_path FROM task_event WHERE id=? AND task_id=? AND event_type='FACT'",
            (check["source_event"], task_id),
        ).fetchone()
        if row is None or row["actor_role"] not in {"human_owner", "tp-project-manager"}:
            raise ValueError(f"DEFERRED_CHECK_SOURCE_INVALID: expected an Owner or project manager FACT in {task_id}")
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except json.JSONDecodeError:
            detail = None
        if not isinstance(detail, dict) or detail.get("producer") != "event_add":
            raise ValueError("DEFERRED_CHECK_SOURCE_INVALID: expected a recorded FACT")
        evidence = validate_evidence_path(task_dir, check["evidence"], require_evidence_dir=True)
        if not evidence.ok:
            raise ValueError(f"DEFERRED_CHECK_SOURCE_INVALID: {evidence.error}")
        if evidence.path != row["evidence_path"]:
            raise ValueError("DEFERRED_CHECK_SOURCE_INVALID: evidence must match the source FACT")
        bound.append({**check, "status": "DEFERRED", "evidence": evidence.item, "source_actor": row["actor_role"]})
    return bound
