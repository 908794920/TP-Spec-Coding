#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify or refresh governance/role-catalog.yaml deterministically.

The catalog remains the single Domain Agent / Formal Role -> Skill authority.
This helper validates front matter, normalized bytes, repository boundaries,
version alignment, state ownership, content_sha256, and the generated
Agent/Role/Skill topology projection.  --write refreshes generated metadata,
content hashes, and topology only; it never invents roles or ownership mappings.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BASE = Path(__file__).resolve().parent.parent
CATALOG = BASE / "governance" / "role-catalog.yaml"
WORKFLOW = BASE / "governance" / "workflow.yaml"
VERSION = BASE / "VERSION"
TOPOLOGY_SCHEMA = "tp-spec.role-topology/v1"
TOPOLOGY_ROOT = "tp-spec-coding"


def _norm_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return normalized.encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(_norm_bytes(path)).hexdigest().upper()


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not m:
        raise ValueError("missing or invalid YAML front matter")
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        raise ValueError("front matter must be a mapping")
    return data


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(BASE)} must be a mapping")
    return data


def _inside_base(path: Path) -> bool:
    try:
        path.resolve().relative_to(BASE.resolve())
        return True
    except ValueError:
        return False


def _catalog_node_kind(skill_path: str) -> str:
    normalized = skill_path.replace("\\", "/")
    if normalized.startswith("entry/"):
        return "product-entry"
    if normalized.startswith("agents/"):
        return "domain-agent"
    if normalized.startswith("skills/roles/"):
        return "formal-role"
    raise ValueError(f"unsupported catalog skill_path for topology: {skill_path}")


def _subskill_identity(sub: dict[str, Any]) -> tuple[str, str, str]:
    sub_id = str(sub.get("id") or "").strip()
    rel = str(sub.get("path") or "").strip()
    if not sub_id or not rel:
        raise ValueError(f"invalid subskill metadata {sub!r}")
    path = (BASE / rel).resolve()
    if not _inside_base(path) or not path.is_file():
        raise ValueError(f"subskill path missing/unsafe: {rel}")
    fm = _frontmatter(path)
    declared_id = str(fm.get("id") or fm.get("name") or "").strip()
    if declared_id != sub_id:
        raise ValueError(f"subskill {sub_id}: front matter identity={declared_id!r}")
    display_name = str(fm.get("display_name") or fm.get("name") or fm.get("id") or "").strip()
    if not display_name:
        raise ValueError(f"subskill {sub_id}: missing display name")
    return sub_id, display_name, rel


def build_topology(catalog: dict[str, Any]) -> dict[str, Any]:
    """Build the deterministic topology projection from catalog-declared facts."""
    roles = catalog.get("roles") or []
    if not isinstance(roles, list):
        raise ValueError("roles must be a list")

    nodes: dict[str, dict[str, Any]] = {}
    catalog_rows: list[dict[str, Any]] = []
    subskill_rows: list[tuple[str, dict[str, Any]]] = []

    for role in roles:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("workflow_role") or "").strip()
        skill_path = str(role.get("skill_path") or "").strip()
        if not role_id or not skill_path:
            continue
        node = {
            "id": role_id,
            "name": str(role.get("display_name") or role_id).strip(),
            "kind": _catalog_node_kind(skill_path),
            "path": skill_path,
            "domain": str(role.get("domain") or "").strip(),
        }
        if not node["name"]:
            raise ValueError(f"{role_id}: missing display_name")
        nodes[role_id] = node
        catalog_rows.append(role)
        for field in ("subskills", "domain_skills"):
            for sub in role.get(field) or []:
                if isinstance(sub, dict):
                    subskill_rows.append((role_id, sub))

    for _parent_id, sub in subskill_rows:
        sub_id, display_name, rel = _subskill_identity(sub)
        candidate = {
            "id": sub_id,
            "name": display_name,
            "kind": "capability-skill",
            "path": rel,
        }
        existing = nodes.get(sub_id)
        if existing is not None and existing != candidate:
            raise ValueError(f"subskill {sub_id}: conflicting topology metadata")
        nodes[sub_id] = candidate

    if TOPOLOGY_ROOT not in nodes or nodes[TOPOLOGY_ROOT].get("kind") != "product-entry":
        raise ValueError(f"topology root {TOPOLOGY_ROOT!r} is missing or not product-entry")

    edges: list[dict[str, Any]] = []
    domain_agents = [
        role for role in catalog_rows
        if nodes[str(role.get("workflow_role") or "")]["kind"] == "domain-agent"
    ]
    for agent in domain_agents:
        edges.append({
            "from": TOPOLOGY_ROOT,
            "to": str(agent["workflow_role"]),
            "relation": "routes-to",
        })

    agents_by_domain: dict[str, list[str]] = {}
    for agent in domain_agents:
        domain = str(agent.get("domain") or "").strip()
        agents_by_domain.setdefault(domain, []).append(str(agent["workflow_role"]))

    for role in catalog_rows:
        role_id = str(role.get("workflow_role") or "")
        if nodes[role_id]["kind"] != "formal-role":
            continue
        domain = str(role.get("domain") or "").strip()
        owners = agents_by_domain.get(domain) or []
        if len(owners) != 1:
            raise ValueError(f"{role_id}: expected exactly one Domain Agent for domain={domain!r}, got {owners}")
        edges.append({"from": owners[0], "to": role_id, "relation": "owns-role"})

    for parent_id, sub in subskill_rows:
        sub_id = str(sub.get("id") or "").strip()
        edge = {"from": parent_id, "to": sub_id, "relation": "uses-skill"}
        mode = str(sub.get("mode") or "").strip()
        if mode:
            edge["mode"] = mode
        edges.append(edge)

    return {
        "schema": TOPOLOGY_SCHEMA,
        "generated": True,
        "root_id": TOPOLOGY_ROOT,
        "nodes": nodes,
        "edges": edges,
    }


def _validate_topology_shape(topology: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(topology, dict):
        return ["topology must be a mapping"]
    if topology.get("schema") != TOPOLOGY_SCHEMA:
        errors.append(f"topology.schema={topology.get('schema')!r} != {TOPOLOGY_SCHEMA!r}")
    if topology.get("generated") is not True:
        errors.append("topology.generated must be true")
    if topology.get("root_id") != TOPOLOGY_ROOT:
        errors.append(f"topology.root_id={topology.get('root_id')!r} != {TOPOLOGY_ROOT!r}")
    nodes = topology.get("nodes")
    edges = topology.get("edges")
    if not isinstance(nodes, dict) or not nodes:
        errors.append("topology.nodes must be a non-empty mapping")
        return errors
    if not isinstance(edges, list):
        errors.append("topology.edges must be a list")
        return errors

    allowed_kinds = {"product-entry", "domain-agent", "formal-role", "capability-skill"}
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"topology.nodes[{node_id}] must be a mapping")
            continue
        if str(node.get("id") or "") != str(node_id):
            errors.append(f"topology.nodes[{node_id}] id mismatch")
        if not str(node.get("name") or "").strip():
            errors.append(f"topology.nodes[{node_id}] missing name")
        if node.get("kind") not in allowed_kinds:
            errors.append(f"topology.nodes[{node_id}] invalid kind={node.get('kind')!r}")

    incoming: dict[str, int] = {str(node_id): 0 for node_id in nodes}
    for idx, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"topology.edges[{idx}] must be a mapping")
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source not in nodes:
            errors.append(f"topology.edges[{idx}] references missing source {source!r}")
        if target not in nodes:
            errors.append(f"topology.edges[{idx}] references missing target {target!r}")
        elif target != TOPOLOGY_ROOT:
            incoming[target] = incoming.get(target, 0) + 1
    for node_id, count in incoming.items():
        if node_id != TOPOLOGY_ROOT and count == 0:
            errors.append(f"topology orphan node: {node_id}")
    return errors


def validate(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    version = VERSION.read_text(encoding="utf-8").strip()
    if str(catalog.get("catalog_version")) != version:
        errors.append(f"catalog_version={catalog.get('catalog_version')!r} != VERSION={version!r}")
    if str(catalog.get("base_version")) != version:
        errors.append(f"base_version={catalog.get('base_version')!r} != VERSION={version!r}")

    roles = catalog.get("roles")
    if not isinstance(roles, list) or not roles:
        return errors + ["roles must be a non-empty list"]

    seen: set[str] = set()
    declared: dict[str, dict[str, Any]] = {}
    for idx, role in enumerate(roles):
        if not isinstance(role, dict):
            errors.append(f"roles[{idx}] must be a mapping")
            continue
        role_id = str(role.get("workflow_role") or "")
        if not role_id:
            errors.append(f"roles[{idx}] missing workflow_role")
            continue
        if role_id in seen:
            errors.append(f"duplicate workflow_role: {role_id}")
            continue
        seen.add(role_id)
        declared[role_id] = role
        if not str(role.get("display_name") or "").strip():
            errors.append(f"{role_id}: missing display_name")
        rel = str(role.get("skill_path") or "")
        if not rel:
            errors.append(f"{role_id}: missing skill_path")
            continue
        skill = (BASE / rel).resolve()
        if not _inside_base(skill):
            errors.append(f"{role_id}: skill_path escapes Base: {rel}")
            continue
        if not skill.is_file():
            errors.append(f"{role_id}: skill_path missing: {rel}")
            continue
        raw = skill.read_bytes()
        if raw != _norm_bytes(skill):
            errors.append(f"{role_id}: SKILL.md is not UTF-8 no-BOM/LF/single-trailing-newline normalized")
        try:
            fm = _frontmatter(skill)
        except Exception as exc:
            errors.append(f"{role_id}: invalid front matter: {exc}")
            continue
        if str(fm.get("id") or "") != role_id:
            errors.append(f"{role_id}: front matter id={fm.get('id')!r}")
        if str(fm.get("type") or "") != str(role.get("type") or ""):
            errors.append(f"{role_id}: type catalog={role.get('type')!r} frontmatter={fm.get('type')!r}")
        if str(fm.get("version") or "") != version:
            errors.append(f"{role_id}: Skill version={fm.get('version')!r} != VERSION={version!r}")
        phases = role.get("phases") or []
        capabilities = role.get("capabilities") or []
        if not isinstance(phases, list) or not phases:
            errors.append(f"{role_id}: phases must be a non-empty list")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"{role_id}: capabilities must be a non-empty list")
        for relation_field, required_prefix in (("subskills", "skills/capabilities/"), ("domain_skills", "skills/")):
            for sub in role.get(relation_field) or []:
                label = "subskill" if relation_field == "subskills" else "domain skill"
                if not isinstance(sub, dict) or not sub.get("id") or not sub.get("path"):
                    errors.append(f"{role_id}: invalid {label} metadata {sub!r}")
                    continue
                relpath = str(sub.get("path") or "").replace("\\", "/")
                if not relpath.startswith(required_prefix):
                    errors.append(f"{role_id}: {label} path outside {required_prefix}: {relpath}")
                mode = str(sub.get("mode") or "")
                if mode not in {"default", "conditional"}:
                    errors.append(f"{role_id}: {label} {sub.get('id')} invalid mode={mode!r}")
                subpath = (BASE / relpath).resolve()
                if not _inside_base(subpath) or not subpath.is_file():
                    errors.append(f"{role_id}: {label} path missing/unsafe: {relpath}")
                    continue
                try:
                    subfm = _frontmatter(subpath)
                except Exception as exc:
                    errors.append(f"{role_id}: {label} {sub.get('id')} invalid front matter: {exc}")
                    continue
                declared_sub_id = str(subfm.get("id") or subfm.get("name") or "")
                if declared_sub_id != str(sub.get("id") or ""):
                    errors.append(f"{role_id}: {label} {sub.get('id')} front matter identity={declared_sub_id!r}")
                if str(subfm.get("version") or "") != version:
                    errors.append(f"{role_id}: {label} {sub.get('id')} version={subfm.get('version')!r} != VERSION={version!r}")
                if not str(subfm.get("display_name") or subfm.get("name") or subfm.get("id") or "").strip():
                    errors.append(f"{role_id}: {label} {sub.get('id')} missing display name")
        actual = _sha(skill)
        if str(role.get("content_sha256") or "").upper() != actual:
            errors.append(f"{role_id}: content_sha256 mismatch catalog={role.get('content_sha256')} actual={actual}")

    owner_map = catalog.get("state_owner_map") or {}
    if not isinstance(owner_map, dict):
        errors.append("state_owner_map must be a mapping")
        owner_map = {}
    for state, owner in owner_map.items():
        if owner != "human_owner" and owner not in declared:
            errors.append(f"state_owner_map[{state}] references undeclared owner {owner!r}")
    for role_id, role in declared.items():
        expected = sorted(str(s) for s, o in owner_map.items() if o == role_id)
        actual = sorted(str(s) for s in (role.get("owns_states") or []))
        if actual != expected:
            errors.append(f"{role_id}: owns_states={actual} != reverse state_owner_map={expected}")

    workflow = _load_yaml(WORKFLOW)
    states = workflow.get("states") or {}
    if isinstance(states, dict):
        for state, info in states.items():
            if isinstance(info, dict) and info.get("owner"):
                if owner_map.get(state) != info.get("owner"):
                    errors.append(
                        f"state owner mismatch {state}: catalog={owner_map.get(state)!r} workflow={info.get('owner')!r}"
                    )
        for state in owner_map:
            if state not in states:
                errors.append(f"state_owner_map contains unknown workflow state {state}")

    topology = catalog.get("topology")
    errors.extend(_validate_topology_shape(topology))
    try:
        expected_topology = build_topology(catalog)
    except Exception as exc:
        errors.append(f"topology build failed: {exc}")
    else:
        if topology != expected_topology:
            errors.append("topology drift: generated projection does not match catalog/Skill metadata; run update_role_catalog.py --write")
    return errors


def _topology_yaml(topology: dict[str, Any]) -> str:
    return yaml.safe_dump(
        {"topology": topology},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    ).rstrip("\n") + "\n"


def refresh_text(catalog: dict[str, Any]) -> str:
    text = CATALOG.read_text(encoding="utf-8")
    version = VERSION.read_text(encoding="utf-8").strip()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = re.sub(r'(?m)^catalog_version:\s*.*$', f'catalog_version: "{version}"', text, count=1)
    text = re.sub(r'(?m)^base_version:\s*.*$', f'base_version: "{version}"', text, count=1)
    text = re.sub(r'(?m)^generated_utc:\s*.*$', f'generated_utc: {now}', text, count=1)
    text = re.sub(
        r'(?m)^generated_by:\s*.*$',
        'generated_by: update_role_catalog.py deterministic metadata/hash/topology refresh',
        text,
        count=1,
    )
    for role in catalog.get("roles") or []:
        rel = str(role.get("skill_path") or "")
        if not rel or not (BASE / rel).is_file():
            continue
        digest = _sha(BASE / rel)
        role_id = re.escape(str(role.get("workflow_role") or ""))
        pattern = re.compile(
            rf'(?ms)(^- workflow_role:\s*{role_id}\s*$.*?^  content_sha256:\s*)\S+'
        )
        text, count = pattern.subn(lambda m: m.group(1) + digest, text, count=1)
        if count != 1:
            raise ValueError(f"cannot locate catalog hash field for {role.get('workflow_role')}")

    topology_text = _topology_yaml(build_topology(catalog))
    existing = re.compile(r"(?ms)^topology:\n.*?(?=^state_owner_map:)")
    if existing.search(text):
        text = existing.sub(topology_text, text, count=1)
    else:
        text, count = re.subn(r"(?m)^state_owner_map:", topology_text + "state_owner_map:", text, count=1)
        if count != 1:
            raise ValueError("cannot locate state_owner_map insertion point for topology")
    return text.rstrip("\n") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="verify/refresh role catalog metadata and generated topology")
    ap.add_argument("--write", action="store_true", help="refresh generated metadata, Skill hashes, and topology")
    ap.add_argument("--verify", action="store_true", help="explicit read-only verify (default)")
    args = ap.parse_args()
    try:
        catalog = _load_yaml(CATALOG)
        if args.write:
            CATALOG.write_text(refresh_text(catalog), encoding="utf-8", newline="\n")
            catalog = _load_yaml(CATALOG)
        errors = validate(catalog)
    except Exception as exc:
        print(f"ROLE_CATALOG_FAIL: {exc}", file=sys.stderr)
        return 1
    if errors:
        for item in errors:
            print(f"ROLE_CATALOG_FAIL: {item}", file=sys.stderr)
        return 1
    topology = catalog.get("topology") or {}
    print(
        f"ROLE_CATALOG_PASS: {len(catalog.get('roles') or [])} roles, "
        f"{len(topology.get('nodes') or {})} topology nodes verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
