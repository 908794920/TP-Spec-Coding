# -*- coding: utf-8 -*-
"""Deterministic Knowledge L1/L2 validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import json
import re

import yaml

from .common import (
    ID_PATTERN,
    KINDS,
    SRC_REF_RE,
    TASK_REF_RE,
    WIKILINK_RE,
    base_schema_path,
    collect_notes,
    find_source_ids,
    load_project_registry,
    load_source_registry,
    read_jsonl,
)

ALLOWED_LINK_PREFIXES = ("10-projects/", "20-shared/", "90-archive/")
GENERATED_SEGMENTS = {"generated-indexes", "bases"}


def load_relation_types() -> Dict[str, Dict[str, Any]]:
    data = yaml.safe_load(base_schema_path("relation-types.yaml").read_text(encoding="utf-8")) or {}
    return {str(r.get("name")): r for r in data.get("relations", []) or [] if isinstance(r, dict) and r.get("name")}


def _schema_errors(fm: Dict[str, Any]) -> List[Tuple[str, str]]:
    try:
        import jsonschema
    except ImportError:
        # The rest of the linter still runs. Base CI environments normally have jsonschema.
        return []
    schema = json.loads(base_schema_path("canonical-note.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(fm), key=lambda e: str(list(e.path))):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        out.append((loc, err.message))
    return out


def _cycles(edges: Dict[str, Set[str]]) -> Set[str]:
    bad: Set[str] = set()
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def dfs(node: str, stack: List[str]) -> None:
        if node in visiting:
            if node in stack:
                bad.update(stack[stack.index(node):])
            else:
                bad.add(node)
            return
        if node in visited:
            return
        visiting.add(node); stack.append(node)
        for nxt in sorted(edges.get(node, set())):
            if nxt in edges:
                dfs(nxt, stack)
        stack.pop(); visiting.discard(node); visited.add(node)

    for n in sorted(edges):
        dfs(n, [])
    return bad


def lint_knowledge(cfg) -> Dict[str, Any]:
    root = cfg.paths.knowledge_physical_root
    canonical, sources = collect_notes(root, cfg)
    registry_data, registry_ids = load_project_registry(cfg)
    rels = load_relation_types()
    source_registry = load_source_registry(cfg)
    source_ids = find_source_ids(sources, source_registry)

    violations: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []

    def add(target: List[Dict[str, Any]], note: Dict[str, Any], rule: str, location: str, message: str) -> None:
        target.append({"path": note.get("rel_path", ""), "rule_id": rule, "location": location, "message": message})

    # Registry contracts are data-owned but Base-schema validated. Legacy source
    # catalogs remain compatibility evidence and are not retroactively forced through
    # the new Source Registry schema.
    try:
        import jsonschema
        project_schema = json.loads(base_schema_path("project-registry.schema.json").read_text(encoding="utf-8"))
        for err in sorted(jsonschema.Draft202012Validator(project_schema).iter_errors(registry_data), key=lambda e: str(list(e.path))):
            loc = "/".join(str(x) for x in err.path) or "<root>"
            add(violations, {"rel_path": str(cfg.paths.knowledge_registry)}, "K019", loc, err.message)
        source_schema = json.loads(base_schema_path("source-registry-record.schema.json").read_text(encoding="utf-8"))
        source_registry_path = cfg.paths.knowledge_meta_root / "source-registry.jsonl"
        if source_registry_path.is_file():
            for idx, row in enumerate(read_jsonl(source_registry_path)):
                for err in jsonschema.Draft202012Validator(source_schema).iter_errors(row):
                    loc = f"{idx}/" + ("/".join(str(x) for x in err.path) or "<root>")
                    add(violations, {"rel_path": ".ai-kb/meta/source-registry.jsonl"}, "K020", loc, err.message)
                content_path = str(row.get("content_path") or "").strip()
                if content_path and not (root / content_path.replace("\\", "/")).is_file():
                    add(violations, {"rel_path": ".ai-kb/meta/source-registry.jsonl"}, "K021", f"{idx}/content_path", f"registered content_path does not exist: {content_path}")
    except ImportError:
        pass

    id_map: Dict[str, Dict[str, Any]] = {}
    id_counts: Dict[str, List[str]] = {}
    for note in canonical:
        nid = str(note.get("id") or "")
        if nid:
            id_counts.setdefault(nid, []).append(note["rel_path"])
            id_map[nid] = note

    part_edges: Dict[str, Set[str]] = {}
    supersedes_edges: Dict[str, Set[str]] = {}
    externally_resolvable_task_refs = 0
    traceable = 0

    for note in canonical:
        fm = note.get("frontmatter")
        if not isinstance(fm, dict):
            add(violations, note, "K001", "frontmatter", note.get("parse_error") or "frontmatter missing")
            continue
        for loc, msg in _schema_errors(fm):
            add(violations, note, "K001", loc, msg)

        nid = str(fm.get("id") or "")
        if not ID_PATTERN.match(nid):
            add(violations, note, "K002", "id", f"invalid canonical id: {nid!r}")
        if nid and len(id_counts.get(nid, [])) > 1:
            add(violations, note, "K003", "id", f"duplicate canonical id: {nid}")
        project = str(fm.get("project") or "")
        if project not in registry_ids:
            add(violations, note, "K004", "project", f"project {project!r} not registered")
        kind = str(fm.get("kind") or "")
        if kind not in KINDS:
            add(violations, note, "K005", "kind", f"unknown kind: {kind!r}")
        if nid and not Path(note["rel_path"]).name.startswith(nid + "-"):
            add(violations, note, "K006", "filename", f"filename must start with {nid}-")
        if any(seg in GENERATED_SEGMENTS for seg in Path(note["rel_path"]).parts):
            add(violations, note, "K014", "path", "canonical note is under a generated projection directory")

        source_refs = fm.get("source_refs") or []
        evidence_refs = fm.get("evidence_refs") or []
        if not isinstance(source_refs, list): source_refs = []
        if not isinstance(evidence_refs, list): evidence_refs = []
        if not source_refs and not evidence_refs:
            add(violations, note, "K009", "evidence", "canonical note has no source_refs/evidence_refs")
        else:
            traceable += 1
        for ref in source_refs:
            ref = str(ref)
            if SRC_REF_RE.match(ref):
                if ref not in source_ids:
                    # Legacy symbolic SRC-* references can point to evidence that
                    # predates the local Source Registry. Treat them as a migration
                    # warning rather than fabricating a local-source requirement.
                    add(advisories, note, "K015", "source_refs", f"source ref is not locally resolvable; migrate/register if locally managed: {ref}")
            elif TASK_REF_RE.match(ref):
                externally_resolvable_task_refs += 1
            elif "/" in ref or "\\" in ref:
                # Legacy path evidence is accepted but must resolve inside the Vault when relative.
                p = Path(ref)
                if not p.is_absolute() and not (root / ref.replace("\\", "/")).is_file():
                    add(advisories, note, "K016", "source_refs", f"legacy evidence path does not resolve in Knowledge root: {ref}")
            else:
                add(advisories, note, "K016", "source_refs", f"unclassified legacy evidence ref: {ref}")

        for idx, ev in enumerate(evidence_refs):
            if not isinstance(ev, dict):
                add(violations, note, "K017", f"evidence_refs/{idx}", "evidence entry must be an object")
                continue
            et = str(ev.get("type") or "")
            ref = str(ev.get("ref") or "")
            if et not in {"source", "task", "code", "external"} or not ref:
                add(violations, note, "K017", f"evidence_refs/{idx}", "evidence type/ref invalid")
            if et == "source" and SRC_REF_RE.match(ref) and ref not in source_ids:
                add(violations, note, "K015", f"evidence_refs/{idx}", f"source evidence not found: {ref}")

        for idx, rel in enumerate(fm.get("relations") or []):
            if not isinstance(rel, dict):
                add(violations, note, "K007", f"relations/{idx}", "relation must be an object")
                continue
            rtype = str(rel.get("type") or "")
            target = str(rel.get("target") or "")
            contract = rels.get(rtype)
            if not contract:
                add(violations, note, "K007", f"relations/{idx}/type", f"unknown relation: {rtype}")
                continue
            target_note = id_map.get(target)
            if target_note:
                target_kind = str((target_note.get("frontmatter") or {}).get("kind") or "")
                allowed_source = set(contract.get("allowed_source_kinds") or [])
                allowed_target = set(contract.get("allowed_target_kinds") or [])
                if allowed_source and kind not in allowed_source:
                    add(violations, note, "K008", f"relations/{idx}", f"{rtype} does not allow source kind {kind}")
                if allowed_target and target_kind not in allowed_target:
                    add(violations, note, "K008", f"relations/{idx}", f"{rtype} does not allow target kind {target_kind}")
            elif rtype != "source_refs":
                add(violations, note, "K011", f"relations/{idx}/target", f"relation target not found: {target}")
            if rtype == "related_to" and not str(rel.get("note") or "").strip():
                add(warnings, note, "K018", f"relations/{idx}", "related_to should explain why a more specific relation is insufficient")
            if rtype == "part_of" and nid and target:
                part_edges.setdefault(nid, set()).add(target)
            if rtype == "supersedes" and nid and target:
                supersedes_edges.setdefault(nid, set()).add(target)

        # Wikilinks: basename-only links are unstable; root paths are preferred.
        for raw in WIKILINK_RE.findall(note.get("body") or ""):
            target = raw.split("|", 1)[0].split("#", 1)[0].strip()
            if not target:
                continue
            if "/" not in target:
                # Basename links remain readable in legacy note vaults, but
                # new/changed Knowledge should use vault-root paths for stable
                # machine resolution. Keep migration incremental.
                add(advisories, note, "K010", "wikilink", f"basename-only legacy wikilink; prefer vault-root path: {target}")
                continue
            if not target.startswith(ALLOWED_LINK_PREFIXES):
                add(advisories, note, "K010", "wikilink", f"non-standard vault-root wikilink: {target}")
                continue
            p = root / target
            if not p.suffix:
                p = p.with_suffix(".md")
            if not p.is_file():
                add(violations, note, "K011", "wikilink", f"broken wikilink: {target}")

    for nid in sorted(_cycles(part_edges)):
        note = id_map.get(nid)
        if note: add(violations, note, "K012", "relations", "part_of cycle detected")
    for nid in sorted(_cycles(supersedes_edges)):
        note = id_map.get(nid)
        if note: add(violations, note, "K013", "relations", "supersedes cycle detected")

    violations.sort(key=lambda x: (x["path"], x["rule_id"], x["location"], x["message"]))
    warnings.sort(key=lambda x: (x["path"], x["rule_id"], x["location"], x["message"]))
    advisories.sort(key=lambda x: (x["path"], x["rule_id"], x["location"], x["message"]))
    return {
        "schema": "ai-work.knowledge-lint/v1",
        "status": "PASS" if not violations else "FAIL",
        "canonical_documents": len(canonical),
        "source_documents": len(sources),
        "registered_projects": len(registry_ids),
        "traceable_canonical": traceable,
        "canonical_traceability": (traceable / len(canonical)) if canonical else None,
        "externally_resolvable_task_refs": externally_resolvable_task_refs,
        "errors": len(violations),
        "warnings": len(warnings),
        "advisories": len(advisories),
        "violations": violations,
        "warning_records": warnings,
        "advisory_records": advisories,
    }
