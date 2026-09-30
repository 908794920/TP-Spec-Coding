# -*- coding: utf-8 -*-
"""Trusted lightweight coordinator identity on the existing Task creation event."""
from __future__ import annotations

import json
import re

from . import event_contract, event_policies

SCHEMA = "tp-spec.task-coordinator/v1"
CREATION_ACTOR = "tp-software-lifecycle"
DEFAULT_COORDINATOR_ROLE = "tp-project-manager"


def claims_creation_metadata(detail, raw) -> bool:
    """Recognize explicit creation claims, including a damaged JSON object."""
    if isinstance(detail, dict) and (
            "coordinator_schema" in detail or detail.get("producer") == "task_create"):
        return True
    return isinstance(raw, str) and (
        '"coordinator_schema"' in raw
        or (detail is None and re.search(r'"producer"\s*:\s*"task_create"', raw) is not None))


def creation_detail(*, task_id: str, actor_agent: str, created_at: str,
                    transaction_id: str, schema_version: str,
                    invocation_id: str | None = None) -> dict:
    if (not isinstance(actor_agent, str)
            or any(not isinstance(value, str) or not value.strip()
                   for value in (task_id, created_at, transaction_id, schema_version))):
        raise ValueError("TASK_COORDINATOR_INVALID: creation identity requires strings")
    detail = {
        "coordinator_schema": SCHEMA,
        "coordinator": {"role": DEFAULT_COORDINATOR_ROLE, "agent": actor_agent.strip()},
        "transaction_id": transaction_id, "flush_id": "CREATE-" + transaction_id,
        "schema_version": schema_version, "task_id": task_id,
        "actor_role": CREATION_ACTOR, "created_at": created_at,
    }
    if invocation_id:
        detail["cli_invocation_id"] = invocation_id
    return event_contract.add_event_semantics(
        detail, event_type="STATE", operation="STATE", result_status="RECORDED", producer="task_create",
    )


def read_creation_coordinator(task: dict, rows: list[dict]) -> dict:
    """Old markerless creation stays old; malformed claimed adoption is visible."""
    rows = [dict(row) for row in rows]
    states = [row for row in rows
              if row["task_id"] == task["task_id"] and row.get("event_type") == "STATE"]
    states.sort(key=lambda row: row["id"])
    creations = [row for row in states if row.get("from_state") is None and row.get("to_state") == "NEW"]
    coordinator, source, issues = None, None, []
    for row in states:
        raw = row.get("detail_json") or "{}"
        try:
            detail = json.loads(raw)
        except (TypeError, ValueError):
            detail = None
        if not claims_creation_metadata(detail, raw):
            if row in creations and row is not states[0]:
                issues.append(f"TASK_COORDINATOR_INVALID:{row['id']}")
            continue
        owner = detail.get("coordinator") if isinstance(detail, dict) else None
        valid = (
            row is states[0] and len(creations) == 1 and row in creations
            and isinstance(detail, dict) and detail.get("coordinator_schema") == SCHEMA
            and detail.get("producer") == "task_create"
            and event_policies.event_allowed_for_producer("STATE", "task_create")
            and detail.get("schema") == event_contract.EVENT_SCHEMA
            and not event_contract.validate_event_semantics("STATE", detail)
            and detail.get("operation") == "STATE" and detail.get("result_status") == "RECORDED"
            and all(isinstance(detail.get(key), str) and detail[key].strip()
                    for key in ("transaction_id", "flush_id", "schema_version", "task_id", "actor_role", "created_at"))
            and all(detail.get(key) == row.get(key) for key in ("task_id", "actor_role", "created_at"))
            and detail.get("schema_version") == row.get("workflow_version")
            and row.get("actor_role") == CREATION_ACTOR
            and isinstance(owner, dict) and set(owner) == {"role", "agent"}
            and owner.get("role") == DEFAULT_COORDINATOR_ROLE and isinstance(owner.get("agent"), str)
            and (row.get("actor_agent") is None or isinstance(row.get("actor_agent"), str))
            and owner["agent"] == (row.get("actor_agent") or "")
        )
        if not valid:
            issues.append(f"TASK_COORDINATOR_INVALID:{row['id']}")
        else:
            coordinator = dict(owner)
            source = {"kind": "task_create", "event_id": int(row["id"]), "schema": SCHEMA}
    return {"coordinator": None if issues else coordinator,
            "source": None if issues else source, "issues": issues}
