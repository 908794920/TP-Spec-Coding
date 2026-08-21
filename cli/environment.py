# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.2.6 installation/project binding resolver.

This module separates four authorities:

- Base installation: immutable program/rule assets.
- Wiki system root: central Code Intelligence storage.
- Knowledge system root: central long-lived knowledge storage.
- Project-local ``.tp-spec``: runtime/task state only.

Project-side Junctions remain compatibility-only.  Runtime code resolves physical
roots from the user installation + project binding + registries instead of relying
on linked directories under ``.tp-spec``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import os

import yaml

from cli.config_loader import load_config
from cli.path_identity import canonical_path, path_identity_key

INSTALLATION_SCHEMA = "tp-spec.installation/v1"
BINDING_SCHEMA = "tp-spec.project-binding/v1"
INVENTORY_SCHEMA = "tp-spec.workspace-inventory/v1"


class EnvironmentConfigError(ValueError):
    pass


def _home(home: "str | Path | None" = None) -> Path:
    return canonical_path(Path(home).expanduser()) if home else canonical_path(Path.home())


def user_tp_spec_root(home: "str | Path | None" = None) -> Path:
    env = os.environ.get("TP_SPEC_USER_ROOT")
    if env:
        return canonical_path(env)
    return canonical_path(_home(home) / ".tp-spec")


def default_installation_path(home: "str | Path | None" = None) -> Path:
    env = os.environ.get("TP_SPEC_INSTALLATION_CONFIG")
    if env:
        return canonical_path(env)
    return user_tp_spec_root(home) / "installation.yaml"


def default_inventory_path(home: "str | Path | None" = None) -> Path:
    env = os.environ.get("TP_SPEC_WORKSPACE_INVENTORY")
    if env:
        return canonical_path(env)
    return user_tp_spec_root(home) / "workspaces.yaml"


def default_binding_path(workspace_root: "str | Path") -> Path:
    return canonical_path(workspace_root) / ".tp-spec" / "config" / "project-binding.yaml"


def _as_abs(value: Any, *, anchor: Path) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    text = os.path.expandvars(os.path.expanduser(text))
    p = Path(text)
    if not p.is_absolute():
        p = anchor / p
    return canonical_path(p)


def _read_optional_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return load_config(path, use_cache=False)


def _validate_installation(data: Dict[str, Any], path: Path) -> None:
    if not data:
        return
    if data.get("schema") != INSTALLATION_SCHEMA:
        raise EnvironmentConfigError(f"{path}: schema must be {INSTALLATION_SCHEMA}")
    base = data.get("base")
    systems = data.get("systems")
    if not isinstance(base, dict) or not isinstance(systems, dict):
        raise EnvironmentConfigError(f"{path}: base and systems must be mappings")
    for name in ("wiki", "knowledge"):
        val = systems.get(name, {})
        if val is not None and not isinstance(val, dict):
            raise EnvironmentConfigError(f"{path}: systems.{name} must be a mapping")


def _validate_binding(data: Dict[str, Any], path: Path) -> None:
    if not data:
        return
    if data.get("schema") != BINDING_SCHEMA:
        raise EnvironmentConfigError(f"{path}: schema must be {BINDING_SCHEMA}")
    project = data.get("project")
    if not isinstance(project, dict):
        raise EnvironmentConfigError(f"{path}: project must be a mapping")
    for key in ("id", "wiki_id", "knowledge_id"):
        value = project.get(key)
        if value is not None and not isinstance(value, str):
            raise EnvironmentConfigError(f"{path}: project.{key} must be a string")
    base = data.get("base")
    if base is not None and not isinstance(base, dict):
        raise EnvironmentConfigError(f"{path}: base must be a mapping when present")


def _validate_inventory(data: Dict[str, Any], path: Path) -> None:
    if not data:
        return
    if data.get("schema") != INVENTORY_SCHEMA:
        raise EnvironmentConfigError(f"{path}: schema must be {INVENTORY_SCHEMA}")
    if not isinstance(data.get("workspaces"), list):
        raise EnvironmentConfigError(f"{path}: workspaces must be a list")


@dataclass(frozen=True)
class InstallationConfig:
    path: Path
    exists: bool
    data: Dict[str, Any]
    base_root: Optional[Path]
    wiki_root: Optional[Path]
    knowledge_root: Optional[Path]


@dataclass(frozen=True)
class ProjectBinding:
    path: Path
    exists: bool
    data: Dict[str, Any]
    project_id: str
    wiki_id: str
    knowledge_id: str
    base_root_override: Optional[Path]
    base_version: str


@dataclass(frozen=True)
class WorkspaceInventory:
    path: Path
    exists: bool
    data: Dict[str, Any]
    workspaces: List[Dict[str, Any]]


def load_installation_config(path: "str | Path | None" = None, *, home: "str | Path | None" = None) -> InstallationConfig:
    p = canonical_path(path) if path else default_installation_path(home)
    data = _read_optional_yaml(p)
    _validate_installation(data, p)
    anchor = p.parent
    base = data.get("base") or {}
    systems = data.get("systems") or {}
    return InstallationConfig(
        path=p,
        exists=p.is_file(),
        data=data,
        base_root=_as_abs(base.get("root"), anchor=anchor),
        wiki_root=_as_abs((systems.get("wiki") or {}).get("root"), anchor=anchor),
        knowledge_root=_as_abs((systems.get("knowledge") or {}).get("root"), anchor=anchor),
    )


def load_project_binding(workspace_root: "str | Path", path: "str | Path | None" = None) -> ProjectBinding:
    workspace = canonical_path(workspace_root)
    p = canonical_path(path) if path else default_binding_path(workspace)
    data = _read_optional_yaml(p)
    _validate_binding(data, p)
    project = data.get("project") or {}
    base = data.get("base") or {}
    return ProjectBinding(
        path=p,
        exists=p.is_file(),
        data=data,
        project_id=str(project.get("id") or "").strip(),
        wiki_id=str(project.get("wiki_id") or "").strip(),
        knowledge_id=str(project.get("knowledge_id") or "").strip(),
        base_root_override=_as_abs(base.get("root"), anchor=p.parent),
        base_version=str(data.get("base_version") or "").strip(),
    )


def load_workspace_inventory(path: "str | Path | None" = None, *, home: "str | Path | None" = None) -> WorkspaceInventory:
    p = canonical_path(path) if path else default_inventory_path(home)
    data = _read_optional_yaml(p)
    _validate_inventory(data, p)
    workspaces = [dict(v) for v in (data.get("workspaces") or []) if isinstance(v, dict)]
    return WorkspaceInventory(path=p, exists=p.is_file(), data=data, workspaces=workspaces)


def current_base_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_base_root(
    workspace_root: "str | Path" = ".",
    *,
    explicit: "str | Path | None" = None,
    installation_path: "str | Path | None" = None,
    binding_path: "str | Path | None" = None,
) -> Path:
    workspace = canonical_path(workspace_root)
    if explicit:
        return canonical_path(explicit)
    env = os.environ.get("TP_SPEC_BASE_ROOT")
    if env:
        return canonical_path(env)
    binding = load_project_binding(workspace, binding_path)
    if binding.base_root_override:
        return binding.base_root_override
    installation = load_installation_config(installation_path)
    if installation.base_root:
        return installation.base_root
    return current_base_root()


def validate_base_root(path: Path) -> Dict[str, Any]:
    required = ["VERSION", "cli/main.py", "governance/workflow.yaml", "governance/role-catalog.yaml"]
    missing = [rel for rel in required if not (path / rel).is_file()]
    version = ""
    try:
        version = (path / "VERSION").read_text(encoding="utf-8-sig").strip() if not missing or (path / "VERSION").is_file() else ""
    except OSError:
        version = ""
    return {
        "root": str(path),
        "valid": not missing,
        "version": version,
        "missing": missing,
    }


def write_installation_config(
    *,
    base_root: "str | Path",
    wiki_root: "str | Path | None" = None,
    knowledge_root: "str | Path | None" = None,
    path: "str | Path | None" = None,
    home: "str | Path | None" = None,
) -> Path:
    p = canonical_path(path) if path else default_installation_path(home)
    payload: Dict[str, Any] = {
        "schema": INSTALLATION_SCHEMA,
        "base": {"root": str(canonical_path(base_root))},
        "systems": {
            "wiki": {"root": str(canonical_path(wiki_root)) if wiki_root else ""},
            "knowledge": {"root": str(canonical_path(knowledge_root)) if knowledge_root else ""},
        },
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)
    return p


def write_project_binding(
    workspace_root: "str | Path",
    *,
    project_id: str,
    wiki_id: str = "",
    knowledge_id: str = "",
    base_version: str = "",
    path: "str | Path | None" = None,
) -> Path:
    workspace = canonical_path(workspace_root)
    p = canonical_path(path) if path else default_binding_path(workspace)
    project: Dict[str, Any] = {"id": project_id}
    if wiki_id:
        project["wiki_id"] = wiki_id
    if knowledge_id:
        project["knowledge_id"] = knowledge_id
    payload: Dict[str, Any] = {"schema": BINDING_SCHEMA, "project": project}
    if base_version:
        payload["base_version"] = base_version
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)
    return p


def write_workspace_inventory(rows: Iterable[Dict[str, Any]], path: "str | Path | None" = None, *, home: "str | Path | None" = None) -> Path:
    p = canonical_path(path) if path else default_inventory_path(home)
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        root = str(row.get("root") or row.get("workspace_root") or "").strip()
        if not root:
            continue
        rp = canonical_path(root)
        key = path_identity_key(rp)
        if key in seen:
            continue
        seen.add(key)
        out = {"root": str(rp), "enabled": bool(row.get("enabled", True))}
        if row.get("id"):
            out["id"] = str(row["id"])
        normalized.append(out)
    normalized.sort(key=lambda x: path_identity_key(x["root"]))
    payload = {"schema": INVENTORY_SCHEMA, "workspaces": normalized}
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)
    return p
