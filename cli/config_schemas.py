# -*- coding: utf-8 -*-
"""TP-Spec-Coding governed-YAML schema registry (V5.2.2 C-01.4, decision D-07/T5).

Schemas are plain Python dicts co-versioned with the loader: no external
schema files (the ``.schema.yaml`` approach was retired by human_owner
decision T5). Each governed file type registers one entry keyed by schema
name; ``version_field`` supports dotted paths (e.g. artifact_contract.version)
and version gating is FULL EXACT MATCH against ``supported_versions``
(ruling 8.6-M2: any differing component, patch included, is rejected).

Field entries support: type (Python type), required (bool), enum (list).
Top-level fields must be exhaustive: unknown top-level keys are rejected in
strict mode (UNKNOWN_FIELD). Deep structures are typed at the container
level only; business semantics stay with the consumers.
"""

from __future__ import annotations

from typing import Any, Dict

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "workflow": {
        "file": "governance/workflow.yaml",
        "version_field": "version",
        "supported_versions": ["5.2.2"],
        "properties": {
            "version": {"type": str, "required": True},
            "workflow": {"type": dict, "required": True},
            "states": {"type": dict, "required": True},
            "levels": {"type": dict, "required": True},
            "transitions": {"type": dict, "required": True},
            "rules": {"type": dict, "required": True},
        },
    },
    "ai-role": {
        "file": "governance/ai-role.yaml",
        "version_field": "version",
        "supported_versions": ["5.2.2"],
        "properties": {
            "version": {"type": str, "required": True},
            "team": {"type": dict, "required": True},
            "human_owner": {"type": dict, "required": True},
            "agents": {"type": dict, "required": True},
            "collaboration": {"type": dict, "required": True},
            "human_owner_skills": {"type": dict, "required": False},
            "priority": {"type": dict, "required": True},
        },
    },
    "risk-rule": {
        "file": "governance/risk-rule.yaml",
        "version_field": "version",
        "supported_versions": ["2.0.0"],
        "properties": {
            "version": {"type": str, "required": True},
            "risk": {"type": dict, "required": True},
            "dimensions": {"type": dict, "required": True},
            "escalation_rules": {"type": dict, "required": True},
            "evaluation": {"type": dict, "required": True},
            "suggested_escalation_signals": {"type": dict, "required": False},
            # automated_validation.*.pattern is a plain string field; the
            # loader never compiles or validates the regex (decision D-04)
            "automated_validation": {"type": dict, "required": True},
            "architecture_risk_evaluation": {"type": dict, "required": False},
            "principles": {"type": dict, "required": True},
        },
    },
    "knowledge-rule": {
        "file": "governance/knowledge-rule.yaml",
        "version_field": "version",
        "supported_versions": ["2.1.0"],
        "properties": {
            "version": {"type": str, "required": True},
            # Physical Knowledge paths live in Content Systems; this governance rule
            # only defines value/responsibility/quality semantics.
            "knowledge": {"type": dict, "required": True},
            "should_save": {"type": dict, "required": True},
            "should_not_save": {"type": dict, "required": True},
            "responsibility": {"type": dict, "required": True},
            "workflow": {"type": dict, "required": True},
            "quality": {"type": dict, "required": True},
            "editor_experience": {"type": dict, "required": True},
            "principles": {"type": dict, "required": True},
        },
    },
    "orchestration": {
        "file": "governance/orchestration.yaml",
        "version_field": "version",
        "supported_versions": ["5.2.2"],
        "properties": {
            "version": {"type": str, "required": True},
            "entry_role": {"type": str, "required": True},
            "level_resolution": {"type": dict, "required": True},
            "confirmation": {"type": dict, "required": True},
            "runtime": {"type": dict, "required": True},
            "execution": {"type": dict, "required": True},
            "signals": {"type": dict, "required": True},
            "pipelines": {"type": dict, "required": True},
        },
    },
    "role-catalog": {
        "file": "agents/role-catalog.yaml",
        "version_field": "catalog_version",
        "supported_versions": ["5.2.2"],
        "properties": {
            "catalog_version": {"type": str, "required": True},
            "base_version": {"type": str, "required": True},
            "generated_utc": {"type": str, "required": False},
            "generated_by": {"type": str, "required": False},
            "human_actor": {"type": dict, "required": False},
            "roles": {"type": list, "required": True},
            "state_owner_map": {"type": dict, "required": True},
            "completion_chain": {"type": dict, "required": False},
            "page_verification_modes": {"type": list, "required": False},
        },
    },
    "status-template": {
        "file": "templates/5.2.2/status.yaml",
        "version_field": "artifact_contract.version",
        "supported_versions": ["5.2.2"],
        "properties": {
            "task_id": {"type": str, "required": True},
            "task_name": {"type": str, "required": False},
            "created": {"type": str, "required": False},
            "base_version": {"type": str, "required": True},
            "artifact_contract": {"type": dict, "required": True},
            "current_state": {"type": str, "required": True},
            "current_phase": {"type": str, "required": False},
            "current_owner": {"type": str, "required": True},
            "risk_level": {"type": str, "required": False},
            "flow_level": {"type": str, "required": False},
            "blockers": {"type": list, "required": False},
            "findings": {"type": list, "required": False},
            "scope_changes": {"type": list, "required": False},
            "artifacts": {"type": dict, "required": False},
        },
    },
    "compat-matrix": {
        "file": "governance/compat-matrix.yaml",
        "version_field": "version",
        "supported_versions": ["1.0.0"],
        "properties": {
            "version": {"type": str, "required": True},
            "contracts": {"type": dict, "required": True},
        },
    },
}

# governance dump set: schema name -> repo-relative file (order is load order)
GOVERNANCE_FILES: Dict[str, str] = {
    "workflow": "governance/workflow.yaml",
    "ai-role": "governance/ai-role.yaml",
    "risk-rule": "governance/risk-rule.yaml",
    "knowledge-rule": "governance/knowledge-rule.yaml",
    "role-catalog": "agents/role-catalog.yaml",
    "orchestration": "governance/orchestration.yaml",
}


def register_schema(name: str, schema: Dict[str, Any]) -> None:
    """Register (or replace) a schema definition."""
    SCHEMAS[name] = schema


def get_schema(name: str) -> Dict[str, Any]:
    if name not in SCHEMAS:
        raise KeyError(f"unknown schema: {name}")
    return SCHEMAS[name]
