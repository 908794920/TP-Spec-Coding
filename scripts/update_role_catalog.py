#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify or refresh agents/role-catalog.yaml deterministically.

The catalog remains the single role->Skill path authority.  This helper validates
front matter, normalized bytes, repository boundaries, version alignment, state
ownership, and content_sha256.  --write refreshes only generated metadata and
content hashes; it never invents roles or ownership mappings.
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
CATALOG = BASE / "agents" / "role-catalog.yaml"
WORKFLOW = BASE / "governance" / "workflow.yaml"
VERSION = BASE / "VERSION"


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
    return errors


def refresh_text(catalog: dict[str, Any]) -> str:
    text = CATALOG.read_text(encoding="utf-8")
    version = VERSION.read_text(encoding="utf-8").strip()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = re.sub(r'(?m)^catalog_version:\s*.*$', f'catalog_version: "{version}"', text, count=1)
    text = re.sub(r'(?m)^base_version:\s*.*$', f'base_version: "{version}"', text, count=1)
    text = re.sub(r'(?m)^generated_utc:\s*.*$', f'generated_utc: {now}', text, count=1)
    text = re.sub(
        r'(?m)^generated_by:\s*.*$',
        'generated_by: update_role_catalog.py deterministic metadata/hash refresh',
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
    return text.rstrip("\n") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="verify/refresh role catalog metadata")
    ap.add_argument("--write", action="store_true", help="refresh generated metadata and Skill content hashes")
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
    print(f"ROLE_CATALOG_PASS: {len(catalog.get('roles') or [])} roles verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
