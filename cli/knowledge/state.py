# -*- coding: utf-8 -*-
"""Knowledge deterministic change set, verification, audit and trusted baseline."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib

import yaml

from .common import (
    classify_snapshot,
    collect_notes,
    knowledge_truth_snapshot,
    load_source_registry,
    meta_paths,
    now_iso,
    read_json,
    source_accountability,
    stable_hash,
    write_json,
)
from .lint import lint_knowledge
from .projection import projection_status


def stage_scan(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    baseline = read_json(paths["snapshot"], None)
    current = knowledge_truth_snapshot(cfg)
    diff = classify_snapshot(baseline, current)
    changeset = {
        "schema": "ai-work.knowledge-change-set/v1",
        "created_at": now_iso(),
        "baseline_snapshot_id": str((baseline or {}).get("snapshot_id") or ""),
        "current_snapshot_id": current["snapshot_id"],
        **diff,
    }
    changeset["change_set_id"] = stable_hash({k: v for k, v in changeset.items() if k not in {"created_at", "change_set_id"}})
    write_json(paths["changeset"], changeset)
    return changeset


def maintain(cfg) -> Dict[str, Any]:
    changeset = stage_scan(cfg)
    proj = projection_status(cfg)
    changed = changeset["changed"]
    baseline_exists = bool(changeset.get("baseline_snapshot_id"))
    if not baseline_exists:
        status = "INITIAL_BASELINE_REQUIRED"
    elif not changed and proj.get("fresh"):
        status = "NO_CHANGE"
    elif not changed:
        status = "INDEX_ONLY"
    elif changeset.get("deleted"):
        status = "WAITING_FOR_AI"
    else:
        scopes = set((changeset.get("counts_by_scope") or {}).keys())
        if scopes <= {"canonical"}:
            status = "VALIDATE_AND_INDEX"
        else:
            status = "WAITING_FOR_AI"
    return {
        "schema": "ai-work.knowledge-maintain/v1",
        "status": status,
        "change_set": changeset,
        "projection": proj,
        "baseline_advanced": False,
    }


_BASE_QUALITY_POLICY = Path(__file__).resolve().parents[2] / "knowledge" / "rules" / "quality-policy.yaml"


def load_quality_policy(cfg) -> Dict[str, Any]:
    """Load the Knowledge quality policy (Base default + workspace override).

    The policy decides how lint facts map to the deterministic verify gate
    (block/warn/backlog). lint.py only produces facts; verify() consumes this
    policy to execute the gate.
    """
    policy = yaml.safe_load(_BASE_QUALITY_POLICY.read_text(encoding="utf-8")) or {}
    override = cfg.paths.ai_work_root / "config" / "quality-policy.yaml"
    if override.is_file():
        extra = yaml.safe_load(override.read_text(encoding="utf-8")) or {}
        rules = dict(policy.get("rules") or {})
        rules.update(extra.get("rules") or {})
        policy = dict(policy)
        policy["rules"] = rules
        policy["override_source"] = str(override)
    return policy


def apply_quality_policy(lint: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """Map lint facts through the quality policy into gate counters and backlog.

    - violations bucket: default gate=block; warn moves to gate_warnings; backlog moves out of gate.
    - warnings bucket: default gate=warn; backlog moves out of gate.
    - advisories bucket: not part of the gate; only gate=backlog enters the backlog report.
    Original lint counts remain untouched in the receipt.
    """
    rules = {str(k): (v or {}) for k, v in (policy.get("rules") or {}).items()}
    gate_errors = 0
    gate_warnings = 0
    backlog: Dict[str, Dict[str, int]] = {}
    for rec in lint.get("violations") or []:
        key = str(rec.get("rule_id") or "")
        gate = (rules.get(key) or {}).get("gate", "block")
        if gate == "backlog":
            backlog.setdefault(key, {"errors": 0, "warnings": 0, "advisories": 0})["errors"] += 1
        elif gate == "warn":
            gate_warnings += 1
        else:
            gate_errors += 1
    for rec in lint.get("warning_records") or []:
        key = str(rec.get("rule_id") or "")
        gate = (rules.get(key) or {}).get("gate", "warn")
        if gate == "backlog":
            backlog.setdefault(key, {"errors": 0, "warnings": 0, "advisories": 0})["warnings"] += 1
        else:
            gate_warnings += 1
    for rec in lint.get("advisory_records") or []:
        key = str(rec.get("rule_id") or "")
        gate = (rules.get(key) or {}).get("gate", "advisory")
        if gate == "backlog":
            backlog.setdefault(key, {"errors": 0, "warnings": 0, "advisories": 0})["advisories"] += 1
    return {"gate_errors": gate_errors, "gate_warnings": gate_warnings, "backlog": backlog}


def verify(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    current = knowledge_truth_snapshot(cfg)
    lint = lint_knowledge(cfg)
    policy = load_quality_policy(cfg)
    gate = apply_quality_policy(lint, policy)
    accountability = source_accountability(cfg)
    proj = projection_status(cfg)
    errors: List[str] = []
    warnings: List[str] = []
    if gate["gate_errors"]:
        errors.append(f"canonical/evidence lint gate errors: {gate['gate_errors']}")
    if gate["gate_warnings"]:
        warnings.append(f"canonical/evidence lint gate warnings: {gate['gate_warnings']}")
    if not proj.get("fresh"):
        errors.append("knowledge projection is stale or missing")
    for issue in proj.get("issues") or []:
        if "vector_mode=" in issue and "embedding rows" in issue:
            warnings.append(issue)
        elif issue != "projection subject is stale":
            errors.append(issue)
    if accountability["registered"]:
        if accountability["invalid_records"]:
            errors.append(f"invalid source-registry records: {len(accountability['invalid_records'])}")
        if accountability["pending"]:
            warnings.append(f"registered sources still pending: {accountability['pending']}")
    status = "PASS" if not errors and not warnings else ("WARN" if not errors else "FAIL")
    receipt = {
        "schema": "ai-work.knowledge-verification/v1",
        "verified_at": now_iso(),
        "status": status,
        "truth_snapshot_id": current["snapshot_id"],
        "lint": lint,
        "quality_policy": policy,
        "gate": gate,
        "source_accountability": accountability,
        "projection": proj,
        "errors": errors,
        "warnings": warnings,
    }
    receipt["verification_id"] = stable_hash({k: v for k, v in receipt.items() if k not in {"verified_at", "verification_id"}})
    write_json(paths["verification"], receipt)
    return receipt


def _affected_canonical(cfg, changeset: Dict[str, Any]) -> List[str]:
    canonical, sources = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    changed = set(changeset.get("changed") or [])
    direct = {n["rel_path"] for n in canonical if n["rel_path"] in changed}
    changed_source_ids = {n["id"] for n in sources if n["rel_path"] in changed and n.get("id")}
    source_registry = load_source_registry(cfg)
    for sid, rec in source_registry.items():
        if str(rec.get("content_path") or "").replace("\\", "/") in changed:
            changed_source_ids.add(sid)
    for n in canonical:
        refs = set(n.get("source_refs") or [])
        for ev in n.get("evidence_refs") or []:
            if isinstance(ev, dict) and ev.get("ref"):
                refs.add(str(ev["ref"]))
        if refs & changed_source_ids:
            direct.add(n["rel_path"])
    # Registry/dictionary changes affect interpretation broadly. Audit a deterministic sample
    # rather than all docs during incremental maintenance; initial build remains full.
    if any((p.startswith("00-system/project-registry") or p.startswith("00-system/dictionaries/")) for p in changed):
        sample_n = int(cfg.knowledge_quality.get("semantic_audit_sample_docs") or 3)
        direct.update(n["rel_path"] for n in canonical[:sample_n])
    return sorted(direct)


AUDIT_CHALLENGES = [
    "Does the evidence actually support the canonical wording and precision?",
    "Is a historical/time-bound observation incorrectly presented as timeless current fact?",
    "Is a retired/compatibility mechanism incorrectly described as current authority?",
    "Is responsibility/enforcement attributed to the correct layer?",
    "Should this update merge into an existing canonical instead of creating a duplicate?",
    "Did a changed source materially change long-lived knowledge, or is no canonical change needed?",
    "Are numeric/API/config assertions copied from real evidence rather than inferred?",
]


def create_audit_plan(cfg, *, full: bool = False) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    current = knowledge_truth_snapshot(cfg)
    changeset = read_json(paths["changeset"], None) or stage_scan(cfg)
    if changeset.get("current_snapshot_id") != current["snapshot_id"]:
        raise ValueError("knowledge change set is stale; run knowledge scan after final content updates")
    canonical, _ = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    initial = not bool(changeset.get("baseline_snapshot_id"))
    mandatory = [n["rel_path"] for n in canonical] if (full or initial) else _affected_canonical(cfg, changeset)
    required = bool(mandatory) and (full or initial or bool(changeset.get("semantic_audit_required")))
    plan = {
        "schema": "ai-work.knowledge-semantic-audit-plan/v1",
        "created_at": now_iso(),
        "truth_snapshot_id": current["snapshot_id"],
        "change_set_id": changeset.get("change_set_id", ""),
        "mode": "full" if (full or initial) else "affected",
        "required": required,
        "mandatory_documents": mandatory,
        "challenge_questions": AUDIT_CHALLENGES,
    }
    plan["plan_id"] = stable_hash({k: v for k, v in plan.items() if k not in {"created_at", "plan_id"}})
    write_json(paths["audit_plan"], plan)
    return plan


def record_audit(cfg, *, result: str, summary: str, documents: List[str]) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    plan = read_json(paths["audit_plan"], None)
    if not plan:
        raise ValueError("knowledge audit plan missing; run knowledge audit first")
    current = knowledge_truth_snapshot(cfg)
    if plan.get("truth_snapshot_id") != current["snapshot_id"]:
        raise ValueError("knowledge truth changed after audit plan; regenerate audit plan")
    reviewed = sorted(set(documents))
    missing = sorted(set(plan.get("mandatory_documents") or []) - set(reviewed))
    normalized = result.upper()
    if normalized == "PASS" and missing:
        raise ValueError("audit PASS blocked: mandatory documents not reviewed: " + ", ".join(missing[:10]))
    receipt = {
        "schema": "ai-work.knowledge-semantic-audit-receipt/v1",
        "recorded_at": now_iso(),
        "result": normalized,
        "summary": summary,
        "plan_id": plan["plan_id"],
        "truth_snapshot_id": current["snapshot_id"],
        "reviewed_documents": reviewed,
        "missing_mandatory": missing,
    }
    receipt["audit_id"] = stable_hash({k: v for k, v in receipt.items() if k not in {"recorded_at", "audit_id"}})
    write_json(paths["audit_receipt"], receipt)
    return receipt


def commit_snapshot(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    current = knowledge_truth_snapshot(cfg)
    changeset = read_json(paths["changeset"], None)
    if not changeset:
        raise ValueError("snapshot blocked: knowledge change set missing; run knowledge scan/maintain")
    if changeset.get("current_snapshot_id") != current["snapshot_id"]:
        raise ValueError("snapshot blocked: Knowledge truth changed after staged scan")
    verification = read_json(paths["verification"], None)
    if not verification or verification.get("truth_snapshot_id") != current["snapshot_id"]:
        raise ValueError("snapshot blocked: current truth has no bound verification")
    if verification.get("status") != "PASS":
        raise ValueError(f"snapshot blocked: verification status is {verification.get('status')}")
    if not (verification.get("projection") or {}).get("fresh"):
        raise ValueError("snapshot blocked: retrieval projection is not fresh")
    if changeset.get("semantic_audit_required") or not changeset.get("baseline_snapshot_id"):
        plan = read_json(paths["audit_plan"], None)
        receipt = read_json(paths["audit_receipt"], None)
        if not plan or not receipt or receipt.get("result") != "PASS":
            raise ValueError("snapshot blocked: semantic audit PASS required")
        if receipt.get("plan_id") != plan.get("plan_id") or receipt.get("truth_snapshot_id") != current["snapshot_id"]:
            raise ValueError("snapshot blocked: semantic audit does not bind current truth")
    current["committed_at"] = now_iso()
    write_json(paths["snapshot"], current)
    return {"schema":"ai-work.knowledge-snapshot-commit/v1","status":"PASS","snapshot_id":current["snapshot_id"],"baseline_advanced":True}


def status(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    baseline = read_json(paths["snapshot"], None)
    current = knowledge_truth_snapshot(cfg)
    return {
        "schema":"ai-work.knowledge-status/v1",
        "baseline_snapshot_id":str((baseline or {}).get("snapshot_id") or ""),
        "current_snapshot_id":current["snapshot_id"],
        "baseline_current":bool(baseline and baseline.get("snapshot_id")==current["snapshot_id"]),
        "change_set":read_json(paths["changeset"], None),
        "verification":read_json(paths["verification"], None),
        "audit_plan":read_json(paths["audit_plan"], None),
        "audit_receipt":read_json(paths["audit_receipt"], None),
        "projection":projection_status(cfg),
        "source_accountability":source_accountability(cfg),
    }
