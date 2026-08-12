# -*- coding: utf-8 -*-
"""Dependency + topology aware Wiki rebuild planner."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set
import json

from .manifest import load_manifest
from .coverage import classify_wiki_eligible_sources
from .snapshot import snapshot_paths, utc_now
from .topology import analyze_topology

PLAN_SCHEMA = "ai-work.wiki-rebuild-plan/v1"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def build_plan(
    wiki_repo_root: Path,
    *,
    allow_mass_change: bool = False,
    mass_change_reason: str = "",
    repo_root: Path | None = None,
    source_cfg: Dict[str, Any] | None = None,
    coverage_cfg: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    paths = snapshot_paths(wiki_repo_root)
    if not paths["changeset"].is_file():
        raise ValueError("no staged scan; run wiki scan first")
    changeset = json.loads(paths["changeset"].read_text(encoding="utf-8"))
    guard = (changeset.get("guard") or {}).get("status")
    if guard == "MASS_CHANGE_REVIEW_REQUIRED" and not allow_mass_change:
        raise ValueError("mass change guard requires review; rerun plan with --allow-mass-change only after confirming a real large change")
    if guard == "MASS_CHANGE_REVIEW_REQUIRED" and allow_mass_change and not mass_change_reason.strip():
        raise ValueError("mass change approval requires a non-empty review reason")
    manifest = load_manifest(wiki_repo_root)
    docs = manifest.get("documents", []) if isinstance(manifest, dict) else []
    topology_summary = analyze_topology(changeset)

    # Optional eligibility annotation is injected by the real CLI, which already has
    # resolved repo/config context.  Keeping it optional preserves planner use in small
    # unit tests and migration helpers.  The scanner remains broad; this metadata only
    # tells the semantic model which topology items are expected to have durable Wiki
    # representation, avoiding both one-file-one-doc bloat and unexplained uncovered files.
    eligibility_available = bool(repo_root is not None and source_cfg is not None and coverage_cfg is not None)
    eligible_files: Set[str] = set()
    exclusion_reason: Dict[str, str] = {}
    coverage_expectation: Dict[str, Any] = {
        "available": False,
        "rule": "scanner scope is broad; wiki-eligible sources should have meaningful durable Wiki representation after build/maintenance",
    }
    if eligibility_available:
        classified = classify_wiki_eligible_sources(repo_root, source_cfg or {}, coverage_cfg or {})
        eligible_files = set(classified.get("eligible") or [])
        exclusion_reason = {
            str(row.get("file") or ""): str(row.get("reason") or "")
            for row in (classified.get("excluded") or [])
            if isinstance(row, dict) and row.get("file")
        }
        coverage_expectation = {
            "available": True,
            "discovered_source_files": len(classified.get("discovered") or []),
            "wiki_eligible_files": len(eligible_files),
            "excluded_files": len(classified.get("excluded") or []),
            "excluded_by_reason": classified.get("excluded_by_reason") or {},
            "rule": "eligible source must be meaningfully represented; group by capability/subsystem rather than creating one Wiki document per file",
        }

    dep_to_docs: Dict[str, List[Dict[str, Any]]] = {}
    for doc in docs if isinstance(docs, list) else []:
        if not isinstance(doc, dict):
            continue
        for dep in doc.get("dependencies") or []:
            if not isinstance(dep, dict) or not dep.get("file"):
                continue
            dep_to_docs.setdefault(str(dep["file"]).replace("\\", "/"), []).append({
                "document": doc.get("path"),
                "role": dep.get("role", "primary"),
                "sections": dep.get("sections") or [],
            })

    affected: Dict[str, Dict[str, Any]] = {}
    topology: List[Dict[str, Any]] = []
    cosmetic: List[str] = []
    uncertain: List[str] = []
    for change in changeset.get("changes", []):
        file = str(change.get("file") or "")
        kind = change.get("kind")
        if kind in {"TOUCHED_ONLY", "COSMETIC"}:
            if kind == "COSMETIC":
                cosmetic.append(file)
            continue
        if kind == "UNCERTAIN":
            uncertain.append(file)
        refs = dep_to_docs.get(file, [])
        if refs:
            for ref in refs:
                doc_path = str(ref.get("document") or "")
                row = affected.setdefault(doc_path, {"document": doc_path, "reasons": [], "sections": set(), "roles": set()})
                row["reasons"].append({"file": file, "change_kind": kind, "role": ref["role"]})
                row["sections"].update(ref.get("sections") or [])
                row["roles"].add(ref["role"])
        else:
            # New/unbound/deleted source topology cannot disappear simply because the old
            # dependency graph has no edge to it.
            item: Dict[str, Any] = {"file": file, "change_kind": kind, "action": "AI_TOPOLOGY_REVIEW"}
            if eligibility_available:
                if file in eligible_files:
                    item["wiki_eligibility"] = "eligible"
                    item["expected_semantic_action"] = "MAP_TO_EXISTING_OR_GROUPED_WIKI"
                elif file in exclusion_reason:
                    item["wiki_eligibility"] = "excluded"
                    item["eligibility_reason"] = exclusion_reason[file]
                    item["expected_semantic_action"] = "NO_DURABLE_WIKI_REQUIRED_UNLESS_NEEDED_AS_CONTEXT"
                else:
                    # Typically a deleted source no longer present in current discovery.
                    # Do not mislabel it as excluded; its prior Wiki significance must be
                    # reviewed from the old dependency/topology evidence.
                    item["wiki_eligibility"] = "unknown"
                    item["expected_semantic_action"] = "REVIEW_DELETED_OR_OUT_OF_SCOPE_SOURCE_SIGNIFICANCE"
            topology.append(item)

    affected_list = []
    for row in affected.values():
        row["sections"] = sorted(row["sections"])
        row["roles"] = sorted(row["roles"])
        affected_list.append(row)
    affected_list.sort(key=lambda x: str(x.get("document")))

    requires_ai = bool(affected_list or topology or uncertain)
    plan = {
        "schema": PLAN_SCHEMA,
        "created_at": utc_now(),
        "change_set_id": changeset.get("change_set_id"),
        "repo_id": changeset.get("repo_id"),
        "guard": changeset.get("guard"),
        "mass_change_approved": bool(guard != "MASS_CHANGE_REVIEW_REQUIRED" or allow_mass_change),
        "mass_change_review_reason": mass_change_reason.strip() if guard == "MASS_CHANGE_REVIEW_REQUIRED" and allow_mass_change else "",
        "requires_ai_update": requires_ai,
        "affected_documents": affected_list,
        "source_topology": topology_summary,
        "wiki_coverage_expectation": coverage_expectation,
        "topology_review": topology,
        "semantic_guardrails": [
            "classify CURRENT vs COMPATIBILITY/RECOVERY/DEPRECATED/HISTORICAL before describing active architecture",
            "existence does not imply authority or recommended/current status",
            "attribute guarantees/ownership to the concrete enforcement layer supported by source",
            "keep pipeline stage owners distinct: discovery, fingerprint, classification, eligibility, topology, planning, update, verify, coverage, audit, baseline",
        ],
        "uncertain_files": uncertain,
        "cosmetic_files": cosmetic,
        "instructions": {
            "cosmetic": "provenance-only; do not rewrite Wiki prose",
            "semantic": "update only affected semantics/sections unless topology requires broader correction",
            "structural": "review topology and add/merge/restructure Wiki only when source facts require it; cluster eligible files by capability/subsystem rather than one-file-one-doc",
            "uncertain": "do not advance baseline until resolved",
        },
    }
    _write_json(paths["plan"], plan)
    return plan
