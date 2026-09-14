# -*- coding: utf-8 -*-
"""Project-local portability checks and safe normalization.

Machine installation paths belong to the user installation profile.  Project
configuration may keep semantic overrides, relative paths, or environment-based
paths, but should not duplicate the current machine's global content roots.
"""
from __future__ import annotations

import copy
import hashlib
import stat
import tempfile
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from cli.content_systems import same_path, load_content_systems
from cli.config_loader import load_config
from cli.project_surface import project_path_issue
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
    path = workspace / ".tp-spec" / "config" / "content-systems.yaml"
    installation = load_installation_config(installation_config)
    issue = project_path_issue(path, workspace)
    if issue:
        return {"schema": "tp-spec.project-portability-plan/v1", "workspace_root": str(workspace),
                "config_path": str(path), "status": "BLOCKED", "changes": [], "blockers": [issue],
                "delete_config": False, "normalized": None}
    if not path.is_file():
        return {
            "schema": "tp-spec.project-portability-plan/v1",
            "workspace_root": str(workspace),
            "config_path": str(path),
            "status": "CURRENT",
            "changes": [],
            "blockers": [],
            "delete_config": False,
            "normalized": None,
        }
    try:
        before_bytes = path.read_bytes()
        original = load_config(path, use_cache=False)
        load_content_systems(workspace, installation_config_path=installation_config)
    except Exception as exc:
        return {
            "schema": "tp-spec.project-portability-plan/v1",
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
            "schema": "tp-spec.project-portability-plan/v1",
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
        raw = str(paths.get("tp_spec_root") or "").strip()
        if not raw:
            paths.pop("tp_spec_root", None)
            if "tp_spec_root" in (original.get("paths") or {}):
                changes.append({"action": "REMOVE_EMPTY_OVERRIDE", "field": "paths.tp_spec_root"})

    systems = data.get("systems")
    if isinstance(systems, dict):
        for name, install_root in (("wiki", installation.wiki_root), ("knowledge", installation.knowledge_root)):
            sec = systems.get(name)
            if not isinstance(sec, dict):
                continue
            # Explicit semantic values remain pinned, even when they currently
            # equal Base defaults. Only known machine-path duplicates are removed.
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

    # Prune only containers emptied by the path cleanup above. Recursive pruning
    # would erase deliberate []/false/empty overrides and re-enable Base defaults.
    if isinstance(systems, dict):
        for name in ("wiki", "knowledge"):
            if name in systems and systems[name] == {} and (original.get("systems") or {}).get(name):
                del systems[name]
        if not systems and original.get("systems"):
            data.pop("systems", None)
    if isinstance(paths, dict) and not paths and original.get("paths"):
        data.pop("paths", None)
    normalized = data
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
        "schema": "tp-spec.project-portability-plan/v1",
        "workspace_root": str(workspace),
        "config_path": str(path),
        "status": status,
        "changes": changes,
        "blockers": sorted(set(blockers)),
        "delete_config": delete_config,
        "normalized": normalized,
        "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
    }


def normalize_project_portability(workspace_root: "str | Path", *, installation_config: "str | Path | None" = None, apply: bool = False) -> Dict[str, Any]:
    plan = project_portability_plan(workspace_root, installation_config=installation_config)
    if plan["status"] == "BLOCKED" or not apply or plan["status"] == "CURRENT":
        return {**plan, "apply": bool(apply)}
    path = Path(plan["config_path"])
    workspace = Path(plan["workspace_root"])
    temporary = None
    try:
        def check_unchanged():
            issue = project_path_issue(path, workspace)
            if issue:
                raise ValueError(issue)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != plan["before_sha256"]:
                raise ValueError(f"PROJECT_CONFIG_CHANGED: replan before writing {path}")
        check_unchanged()
        if plan["delete_config"]:
            path.unlink()
            action = "DELETE_REDUNDANT_PROJECT_CONTENT_CONFIG"
        else:
            mode = stat.S_IMODE(path.stat().st_mode)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tp-spec-config-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(yaml.safe_dump(plan["normalized"], allow_unicode=True, sort_keys=False).encode("utf-8"))
            os.chmod(temporary, mode)
            check_unchanged()
            os.replace(temporary, path)
            action = "WRITE_PORTABLE_PROJECT_CONTENT_CONFIG"
    except (OSError, ValueError) as exc:
        return {**plan, "status": "BLOCKED", "apply": True,
                "blockers": [f"{type(exc).__name__}: {exc}"], "recovery": "Recheck the current project override and repeat sync-project --apply."}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    final = project_portability_plan(workspace_root, installation_config=installation_config)
    return {**final, "apply": True, "applied_action": action, "previous_changes": plan["changes"]}
