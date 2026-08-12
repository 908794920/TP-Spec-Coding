# -*- coding: utf-8 -*-
"""Project-local portability checks and safe normalization.

Machine installation paths belong to the user installation profile.  Project
configuration may keep semantic overrides, relative paths, or environment-based
paths, but should not duplicate the current machine's global content roots.
"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from cli.content_systems import same_path
from cli.environment import load_installation_config

_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_dynamic(text: str) -> bool:
    return "${" in text or "%" in text or text.startswith("~")


def _resolved(raw: str, workspace: Path) -> Optional[Path]:
    text = str(raw or "").strip()
    if not text or _is_dynamic(text):
        return None
    expanded = os.path.expandvars(os.path.expanduser(text))
    p = Path(expanded)
    if not p.is_absolute():
        return None
    return p.resolve(strict=False)


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            cleaned = _prune(child)
            if cleaned in ({}, [], "", None):
                continue
            out[key] = cleaned
        return out
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _walk_machine_paths(value: Any, prefix: str = "") -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_walk_machine_paths(child, name))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            rows.extend(_walk_machine_paths(child, f"{prefix}[{idx}]"))
    elif isinstance(value, str):
        text = value.strip()
        if _DRIVE_ABS_RE.match(text) or text.startswith("/home/") or text.startswith("/Users/"):
            rows.append((prefix, text))
    return rows


def project_portability_plan(workspace_root: "str | Path", *, installation_config: "str | Path | None" = None) -> Dict[str, Any]:
    workspace = Path(workspace_root).resolve(strict=False)
    path = workspace / ".ai-work" / "config" / "content-systems.yaml"
    installation = load_installation_config(installation_config)
    if not path.is_file():
        return {
            "schema": "ai-work.project-portability-plan/v1",
            "workspace_root": str(workspace),
            "config_path": str(path),
            "status": "CURRENT",
            "changes": [],
            "blockers": [],
            "delete_config": False,
            "normalized": None,
        }
    try:
        original = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception as exc:
        return {
            "schema": "ai-work.project-portability-plan/v1",
            "workspace_root": str(workspace),
            "config_path": str(path),
            "status": "BLOCKED",
            "changes": [],
            "blockers": [f"content-systems parse error: {exc}"],
            "delete_config": False,
            "normalized": None,
        }
    if not isinstance(original, dict):
        return {
            "schema": "ai-work.project-portability-plan/v1",
            "workspace_root": str(workspace),
            "config_path": str(path),
            "status": "BLOCKED",
            "changes": [],
            "blockers": ["content-systems root must be a mapping"],
            "delete_config": False,
            "normalized": None,
        }

    data = copy.deepcopy(original)
    changes: List[Dict[str, Any]] = []
    blockers: List[str] = []

    paths = data.get("paths")
    if isinstance(paths, dict):
        raw = str(paths.get("ai_work_root") or "").strip()
        if not raw:
            paths.pop("ai_work_root", None)
            if "ai_work_root" in (original.get("paths") or {}):
                changes.append({"action": "REMOVE_EMPTY_OVERRIDE", "field": "paths.ai_work_root"})

    base_defaults = yaml.safe_load((Path(__file__).resolve().parents[1] / "governance" / "content-systems.yaml").read_text(encoding="utf-8-sig")) or {}
    default_systems = base_defaults.get("systems") or {}
    systems = data.get("systems")
    if isinstance(systems, dict):
        for name, install_root in (("wiki", installation.wiki_root), ("knowledge", installation.knowledge_root)):
            sec = systems.get(name)
            if not isinstance(sec, dict):
                continue
            defaults = default_systems.get(name) or {}
            for field in ("enabled", "layout"):
                if field in sec and sec.get(field) == defaults.get(field):
                    sec.pop(field, None)
                    changes.append({"action": "REMOVE_REDUNDANT_DEFAULT_OVERRIDE", "field": f"systems.{name}.{field}"})
            raw = str(sec.get("root") or "").strip()
            if not raw:
                if "root" in sec:
                    sec.pop("root", None)
                    changes.append({"action": "REMOVE_EMPTY_OVERRIDE", "field": f"systems.{name}.root"})
            elif not _is_dynamic(raw):
                abs_root = _resolved(raw, workspace)
                if abs_root is not None:
                    if install_root and same_path(abs_root, install_root):
                        sec.pop("root", None)
                        changes.append({"action": "REMOVE_MACHINE_ROOT_DUPLICATE", "field": f"systems.{name}.root", "value": raw})
                    else:
                        blockers.append(f"absolute project override {name}.root differs from machine Installation; convert to machine profile, relative path, or environment-based path before sync")
            registry = str(sec.get("registry") or "").strip()
            if "registry" in sec and not registry:
                sec.pop("registry", None)
                changes.append({"action": "REMOVE_EMPTY_OVERRIDE", "field": f"systems.{name}.registry"})

    normalized = _prune(data)
    if not isinstance(normalized, dict):
        normalized = {}
    if original.get("schema"):
        normalized = {"schema": original["schema"], **{k: v for k, v in normalized.items() if k != "schema"}}

    # Any remaining absolute path is project-local machine coupling.  Explicitly
    # block rather than silently deleting semantic overrides we do not understand.
    for field, raw in _walk_machine_paths(normalized):
        blockers.append(f"machine-local absolute path remains at {field}: {raw}")

    meaningful = {k: v for k, v in normalized.items() if k != "schema"}
    delete_config = not meaningful
    changed = normalized != original or delete_config
    status = "BLOCKED" if blockers else ("SYNC_AVAILABLE" if changed else "CURRENT")
    return {
        "schema": "ai-work.project-portability-plan/v1",
        "workspace_root": str(workspace),
        "config_path": str(path),
        "status": status,
        "changes": changes,
        "blockers": sorted(set(blockers)),
        "delete_config": delete_config,
        "normalized": normalized,
    }


def normalize_project_portability(workspace_root: "str | Path", *, installation_config: "str | Path | None" = None, apply: bool = False) -> Dict[str, Any]:
    plan = project_portability_plan(workspace_root, installation_config=installation_config)
    if plan["status"] == "BLOCKED" or not apply or plan["status"] == "CURRENT":
        return {**plan, "apply": bool(apply)}
    path = Path(plan["config_path"])
    if plan["delete_config"]:
        path.unlink(missing_ok=True)
        action = "DELETE_REDUNDANT_PROJECT_CONTENT_CONFIG"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(plan["normalized"], allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
        action = "WRITE_PORTABLE_PROJECT_CONTENT_CONFIG"
    final = project_portability_plan(workspace_root, installation_config=installation_config)
    return {**final, "apply": True, "applied_action": action, "previous_changes": plan["changes"]}
