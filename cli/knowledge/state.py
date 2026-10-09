# -*- coding: utf-8 -*-
"""Knowledge deterministic change set, verification, audit and trusted baseline."""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional
import hashlib

import yaml

from .common import (
    classify_snapshot,
    collect_notes,
    knowledge_truth_snapshot,
    source_registry_records,
    source_path_ids,
    load_project_registry,
    meta_paths,
    now_iso,
    read_json,
    source_accountability,
    stable_hash,
    write_json,
)
from .lint import lint_knowledge
from .projection import projection_status
from .contracts import quality_contract


def code_dependency_snapshot(cfg) -> Dict[str, Any]:
    """Read only explicitly declared code evidence in one registered workspace.

    Unknown applicability is a stable limitation, not proof of current behavior
    and not a request to inventory every checkout or to reject the whole Vault.
    """
    canonical, _ = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    registry, _ = load_project_registry(cfg)
    projects = {}
    for row in registry.get("projects") or []:
        if isinstance(row, dict) and row.get("id"):
            projects.setdefault(str(row["id"]), []).append(row)
    documents, pending = {}, []
    for note in canonical:
        entries = []
        for evidence in note.get("evidence_refs") or []:
            if evidence.get("type") not in {"code", "external"}:
                continue
            ref = str(evidence.get("ref") or "").replace("\\", "/").strip()
            locator = str(evidence.get("locator") or "").strip()
            entry = {"ref": ref, "locator": locator, "status": "PENDING", "reason": ""}
            rows = projects.get(note["project"], [])
            roots = sorted({str(Path(str(value)).resolve(strict=False)) for row in rows
                            for value in row.get("workspace_roots") or [] if str(value).strip()})
            parts = PurePosixPath(ref).parts
            if evidence.get("type") == "external":
                entry["reason"] = "EXTERNAL_CURRENT_APPLICABILITY_UNVERIFIED"
            elif not locator:
                entry["reason"] = "CODE_LOCATOR_MISSING"
            elif len(rows) != 1 or len(roots) != 1:
                entry["reason"] = "CODE_WORKSPACE_NOT_UNIQUE"
            elif not ref or PureWindowsPath(ref).drive or ref.startswith("/") or ":" in ref or any(p in {"..", "."} for p in parts):
                entry["reason"] = "CODE_REF_NOT_RELATIVE"
            else:
                root = Path(roots[0])
                target = (root / ref).resolve(strict=False)
                if not target.is_relative_to(root):
                    entry["reason"] = "CODE_REF_OUTSIDE_WORKSPACE"
                elif not target.is_file():
                    entry["reason"] = "CODE_SOURCE_UNAVAILABLE"
                else:
                    try:
                        digest = hashlib.sha256()
                        with target.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(block)
                        entry.update(status="RESOLVED", workspace=root.as_posix(), sha256=digest.hexdigest())
                    except OSError:
                        entry["reason"] = "CODE_SOURCE_UNAVAILABLE"
            if entry["status"] != "RESOLVED":
                pending.append({"document": note["rel_path"], "ref": ref, "reason": entry["reason"]})
            entries.append(entry)
        if entries:
            documents[note["rel_path"]] = sorted(entries, key=lambda item: (item["ref"], item["locator"]))
    result = {"documents": documents, "pending": pending}
    result["subject_id"] = stable_hash(documents)
    return result


def _verification_binding(cfg, current, dependencies, contract):
    receipt = read_json(meta_paths(cfg)["verification"], None) or {}
    bound = bool(receipt.get("quality_contract_id"))
    valid = bool(bound and receipt.get("quality_contract_id") == contract["contract_id"]
                 and receipt.get("truth_snapshot_id") == current["snapshot_id"]
                 and receipt.get("code_dependency_subject") == dependencies["subject_id"]
                 and receipt.get("status") == "PASS")
    return {"current": valid, "status": "CURRENT" if valid else "HISTORICAL_UNBOUND" if receipt and not bound else "STALE_OR_MISSING",
            "quality_contract_id": contract["contract_id"], "verification_id": receipt.get("verification_id", "")}


def stage_scan(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    baseline = read_json(paths["snapshot"], None)
    current = knowledge_truth_snapshot(cfg)
    diff = classify_snapshot(baseline, current)
    dependencies = code_dependency_snapshot(cfg)
    old_dependencies = (baseline or {}).get("code_dependencies") or {}
    code_changed = [path for path, entries in dependencies["documents"].items()
                    if entries != old_dependencies.get(path) and
                    (any(item.get("status") == "RESOLVED" for item in entries)
                     or any(item.get("status") == "RESOLVED" for item in old_dependencies.get(path) or []))]
    contract = quality_contract(cfg)
    changeset = {
        "schema": "tp-spec.knowledge-change-set/v1",
        "created_at": now_iso(),
        "baseline_snapshot_id": str((baseline or {}).get("snapshot_id") or ""),
        "current_snapshot_id": current["snapshot_id"],
        **diff,
        "quality_contract_id": contract["contract_id"],
        "code_dependency_subject": dependencies["subject_id"],
        "code_changed_documents": sorted(code_changed),
        "applicability_pending": dependencies["pending"],
    }
    changeset["semantic_audit_required"] = bool(diff["semantic_audit_required"] or code_changed)
    changeset["change_set_id"] = stable_hash({k: v for k, v in changeset.items() if k not in {"created_at", "change_set_id"}})
    write_json(paths["changeset"], changeset)
    return changeset


def maintain(cfg) -> Dict[str, Any]:
    changeset = stage_scan(cfg)
    proj = projection_status(cfg)
    current = knowledge_truth_snapshot(cfg)
    dependencies = code_dependency_snapshot(cfg)
    binding = _verification_binding(cfg, current, dependencies, quality_contract(cfg))
    changed = changeset["changed"]
    baseline_exists = bool(changeset.get("baseline_snapshot_id"))
    if not baseline_exists:
        status = "INITIAL_BASELINE_REQUIRED"
    elif changeset.get("code_changed_documents"):
        status = "WAITING_FOR_AI"
    elif not changed and proj.get("fresh") and binding["current"]:
        status = "NO_CHANGE"
    elif not changed and not proj.get("fresh"):
        status = "INDEX_ONLY"
    elif not changed:
        status = "VALIDATE"
    elif changeset.get("deleted"):
        status = "WAITING_FOR_AI"
    else:
        scopes = set((changeset.get("counts_by_scope") or {}).keys())
        if scopes <= {"canonical"}:
            status = "VALIDATE_AND_INDEX"
        else:
            status = "WAITING_FOR_AI"
    return {
        "schema": "tp-spec.knowledge-maintain/v1",
        "status": status,
        "change_set": changeset,
        "projection": proj,
        "verification_binding": binding,
        "verification_required": not binding["current"],
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
    override = cfg.paths.tp_spec_root / "config" / "quality-policy.yaml"
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
    contract = quality_contract(cfg)
    dependencies = code_dependency_snapshot(cfg)
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
        "schema": "tp-spec.knowledge-verification/v1",
        "verified_at": now_iso(),
        "status": status,
        "truth_snapshot_id": current["snapshot_id"],
        "quality_contract_id": contract["contract_id"],
        "quality_contract": contract,
        "code_dependency_subject": dependencies["subject_id"],
        "applicability_pending": dependencies["pending"],
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
    baseline = read_json(meta_paths(cfg)["snapshot"], None) or {}
    current_files = knowledge_truth_snapshot(cfg).get("files") or {}
    for path in changed:
        old = (baseline.get("files") or {}).get(path) or {}
        if old.get("scope") == "source" and old.get("id"):
            changed_source_ids.add(str(old["id"]))
        new = current_files.get(path) or {}
        if new.get("scope") == "source" and new.get("id"):
            changed_source_ids.add(str(new["id"]))
    for rec in source_registry_records(cfg):
        if str(rec.get("content_path") or "").replace("\\", "/") in changed:
            if rec.get("source_id"):
                changed_source_ids.add(str(rec["source_id"]))
    for n in canonical:
        refs = set(n.get("source_refs") or [])
        for ev in n.get("evidence_refs") or []:
            if isinstance(ev, dict) and ev.get("ref"):
                refs.add(str(ev["ref"]))
        if refs & changed_source_ids:
            direct.add(n["rel_path"])
        if any(str(ref).replace("\\", "/") in changed for ref in refs):
            direct.add(n["rel_path"])
    direct.update(changeset.get("code_changed_documents") or [])
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
    contract = quality_contract(cfg)
    dependencies = code_dependency_snapshot(cfg)
    if changeset.get("quality_contract_id") != contract["contract_id"] or changeset.get("code_dependency_subject") != dependencies["subject_id"]:
        raise ValueError("knowledge change set contracts/dependencies are stale; run knowledge scan")
    canonical, _ = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    initial = not bool(changeset.get("baseline_snapshot_id"))
    mandatory = [n["rel_path"] for n in canonical] if (full or initial) else _affected_canonical(cfg, changeset)
    required = bool(mandatory) and (full or initial or bool(changeset.get("semantic_audit_required")))
    plan = {
        "schema": "tp-spec.knowledge-semantic-audit-plan/v1",
        "created_at": now_iso(),
        "truth_snapshot_id": current["snapshot_id"],
        "quality_contract_id": contract["contract_id"],
        "code_dependency_subject": dependencies["subject_id"],
        "applicability_pending": dependencies["pending"],
        "change_set_id": changeset.get("change_set_id", ""),
        "mode": "full" if (full or initial) else "affected",
        "required": required,
        "mandatory_documents": mandatory,
        "challenge_questions": AUDIT_CHALLENGES,
    }
    plan["plan_id"] = stable_hash({k: v for k, v in plan.items() if k not in {"created_at", "plan_id"}})
    write_json(paths["audit_plan"], plan)
    return plan


def _audit_assertions(assertions, reviewed, current, dependencies, *, source_paths=None):
    files = current.get("files") or {}
    versions = {path: str(item.get("sha256") or "") for path, item in files.items()}
    by_id = {}
    for path, item in files.items():
        if item.get("id"):
            by_id.setdefault(str(item["id"]), {})[path] = versions[path]
        if item.get("scope") == "source":
            for source_id in (source_paths or {}).get(path, []):
                by_id.setdefault(source_id, {})[path] = versions[path]
    recorded = []
    for assertion in assertions or []:
        if not isinstance(assertion, dict):
            raise ValueError("audit assertion must be an object")
        required = ("document", "locator", "assertion", "source_ref", "source_locator", "source_version", "judgment", "reason")
        if any(not isinstance(assertion.get(key), str) or not assertion[key].strip() for key in required):
            raise ValueError("audit assertion needs document/locator/assertion/source/version/judgment/reason")
        if assertion["document"] not in reviewed:
            raise ValueError("audit assertion document was not reviewed")
        source_ref = assertion["source_ref"].replace("\\", "/")
        candidates = {source_ref: versions[source_ref]} if source_ref in versions else by_id.get(source_ref, {})
        if len(candidates) > 1:
            locator = assertion["source_locator"].replace("\\", "/").strip()
            located = {path: value for path, value in candidates.items()
                       if locator == path or locator.startswith(path + ":") or locator.startswith(path + "#")}
            # Exact file prefixes may themselves contain '#'; prefer the full
            # longest matching path rather than admitting another file's hash.
            longest = max((len(path) for path in located), default=0)
            candidates = {path: value for path, value in located.items() if len(path) == longest}
        hashes = set(candidates.values())
        if not candidates and source_ref not in by_id and source_ref not in versions:
            matches = [entry for entry in dependencies["documents"].get(assertion["document"], [])
                       if entry["ref"] == source_ref and entry.get("status") == "RESOLVED"]
            hashes = {entry["sha256"] for entry in matches}
            if len(hashes) != 1:
                hashes.clear()  # Preserve the existing ambiguity guard for code refs.
        if assertion["source_version"] not in hashes:
            raise ValueError("audit assertion source version is unavailable or does not bind current evidence")
        recorded.append({**assertion, "source_ref": source_ref, "source_binding": "CURRENT"})
    return recorded


def record_audit(cfg, *, result: str, summary: str, documents: List[str], audit_scope: str = "", assertions=None) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    plan = read_json(paths["audit_plan"], None)
    if not plan:
        raise ValueError("knowledge audit plan missing; run knowledge audit first")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("knowledge audit summary must describe the actual reasoning")
    current = knowledge_truth_snapshot(cfg)
    if plan.get("truth_snapshot_id") != current["snapshot_id"]:
        raise ValueError("knowledge truth changed after audit plan; regenerate audit plan")
    contract = quality_contract(cfg)
    dependencies = code_dependency_snapshot(cfg)
    if plan.get("quality_contract_id") != contract["contract_id"] or plan.get("code_dependency_subject") != dependencies["subject_id"]:
        raise ValueError("knowledge audit plan contracts/dependencies are stale")
    reviewed = sorted(set(documents))
    files = current.get("files") or {}
    if any((files.get(path) or {}).get("scope") != "canonical" for path in reviewed):
        raise ValueError("audit reviewed document is not a current canonical path")
    missing = sorted(set(plan.get("mandatory_documents") or []) - set(reviewed))
    normalized = result.upper()
    if normalized == "PASS" and missing:
        raise ValueError("audit PASS blocked: mandatory documents not reviewed: " + ", ".join(missing[:10]))
    recorded_assertions = _audit_assertions(assertions, reviewed, current, dependencies, source_paths=source_path_ids(cfg))
    receipt = {
        "schema": "tp-spec.knowledge-semantic-audit-receipt/v1",
        "recorded_at": now_iso(),
        "result": normalized,
        "summary": summary,
        "audit_scope": audit_scope or plan.get("mode", "affected"),
        "representative_assertions": recorded_assertions,
        "evidence_limitation": "No representative assertion trace was supplied" if not recorded_assertions else "",
        "plan_id": plan["plan_id"],
        "truth_snapshot_id": current["snapshot_id"],
        "quality_contract_id": contract["contract_id"],
        "code_dependency_subject": dependencies["subject_id"],
        "reviewed_documents": reviewed,
        "document_versions": {path: files[path]["sha256"] for path in reviewed},
        "missing_mandatory": missing,
    }
    receipt["audit_id"] = stable_hash({k: v for k, v in receipt.items() if k not in {"recorded_at", "audit_id"}})
    write_json(paths["audit_receipt"], receipt)
    return receipt


def commit_snapshot(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    current = knowledge_truth_snapshot(cfg)
    contract = quality_contract(cfg)
    dependencies = code_dependency_snapshot(cfg)
    changeset = read_json(paths["changeset"], None)
    if not changeset:
        raise ValueError("snapshot blocked: knowledge change set missing; run knowledge scan/maintain")
    if changeset.get("current_snapshot_id") != current["snapshot_id"]:
        raise ValueError("snapshot blocked: Knowledge truth changed after staged scan")
    if changeset.get("quality_contract_id") != contract["contract_id"] or changeset.get("code_dependency_subject") != dependencies["subject_id"]:
        raise ValueError("snapshot blocked: staged quality contract or code evidence is stale")
    verification = read_json(paths["verification"], None)
    if not verification or verification.get("truth_snapshot_id") != current["snapshot_id"]:
        raise ValueError("snapshot blocked: current truth has no bound verification")
    if verification.get("status") != "PASS":
        raise ValueError(f"snapshot blocked: verification status is {verification.get('status')}")
    if verification.get("quality_contract_id") != contract["contract_id"] or verification.get("code_dependency_subject") != dependencies["subject_id"]:
        raise ValueError("snapshot blocked: verification quality contract or code evidence is historical/stale")
    if not projection_status(cfg).get("fresh"):
        raise ValueError("snapshot blocked: retrieval projection is not fresh")
    receipt = read_json(paths["audit_receipt"], None)
    plan = read_json(paths["audit_plan"], None)
    if changeset.get("semantic_audit_required") or not changeset.get("baseline_snapshot_id"):
        if not plan or not receipt or receipt.get("result") != "PASS":
            raise ValueError("snapshot blocked: semantic audit PASS required")
        if receipt.get("plan_id") != plan.get("plan_id") or receipt.get("truth_snapshot_id") != current["snapshot_id"]:
            raise ValueError("snapshot blocked: semantic audit does not bind current truth")
        if plan.get("change_set_id") != changeset.get("change_set_id") or receipt.get("quality_contract_id") != contract["contract_id"] or receipt.get("code_dependency_subject") != dependencies["subject_id"]:
            raise ValueError("snapshot blocked: semantic audit contract or code evidence is stale")
        _audit_assertions(receipt.get("representative_assertions"), receipt.get("reviewed_documents") or [], current, dependencies, source_paths=source_path_ids(cfg))
    previous = read_json(paths["snapshot"], None) or {}
    bound_audit = bool(receipt and receipt.get("truth_snapshot_id") == current["snapshot_id"]
                       and receipt.get("quality_contract_id") == contract["contract_id"]
                       and receipt.get("code_dependency_subject") == dependencies["subject_id"])
    current["code_dependencies"] = dependencies["documents"]
    current["completion"] = {"verification_id": verification["verification_id"],
        "quality_contract_id": contract["contract_id"], "code_dependency_subject": dependencies["subject_id"],
        "semantic_audit": receipt if bound_audit else (previous.get("completion") or {}).get("semantic_audit"),
        "audit_binding_status": "CURRENT" if bound_audit else "HISTORICAL_OR_NOT_REQUIRED"}
    current["committed_at"] = now_iso()
    write_json(paths["snapshot"], current)
    return {"schema":"tp-spec.knowledge-snapshot-commit/v1","status":"PASS","snapshot_id":current["snapshot_id"],"baseline_advanced":True}


def status(cfg) -> Dict[str, Any]:
    paths = meta_paths(cfg)
    baseline = read_json(paths["snapshot"], None)
    current = knowledge_truth_snapshot(cfg)
    dependencies = code_dependency_snapshot(cfg)
    return {
        "schema":"tp-spec.knowledge-status/v1",
        "baseline_snapshot_id":str((baseline or {}).get("snapshot_id") or ""),
        "current_snapshot_id":current["snapshot_id"],
        "baseline_current":bool(baseline and baseline.get("snapshot_id")==current["snapshot_id"]),
        "change_set":read_json(paths["changeset"], None),
        "verification":read_json(paths["verification"], None),
        "verification_binding": _verification_binding(cfg, current, dependencies, quality_contract(cfg)),
        "completion": (baseline or {}).get("completion"),
        "applicability_pending": dependencies["pending"],
        "audit_plan":read_json(paths["audit_plan"], None),
        "audit_receipt":read_json(paths["audit_receipt"], None),
        "projection":projection_status(cfg),
        "source_accountability":source_accountability(cfg),
    }


def task_scoped_convergence(handoff: Dict[str, Any]) -> Dict[str, Any]:
    """拒绝旧 compact handoff 快路径；Task Knowledge 必须使用 typed request/result。"""
    raise ValueError(
        "legacy task-scoped Knowledge handoff is retired; use knowledge task-converge --request-event-id"
    )
