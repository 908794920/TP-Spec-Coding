# -*- coding: utf-8 -*-
"""Wiki workspace/repository registry compatibility layer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import os

import yaml

from cli.config_loader import load_config
from cli.environment import load_project_binding
from .config import ResolvedConfig, same_path


@dataclass(frozen=True)
class RepoTarget:
    workspace_id: str
    repo_id: str
    repo_root: Path
    wiki_repo_root: Path
    enabled: bool = True
    group: str = ""
    frontend: bool = False
    multimodule: bool = False
    coverage: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "repo_id": self.repo_id,
            "repo_root": str(self.repo_root),
            "wiki_repo_root": str(self.wiki_repo_root),
            "enabled": self.enabled,
            "group": self.group,
            "frontend": self.frontend,
            "multimodule": self.multimodule,
            "coverage": dict(self.coverage or {}),
        }


def _legacy_repo_output(config: ResolvedConfig, workspace_id: str, repo: Dict[str, Any]) -> Path:
    template = str(config.data["systems"]["wiki"].get("workspace_dir_template") or "projects/{workspace_id}")
    base = config.paths.wiki_system_root / template.format(workspace_id=workspace_id)
    group = str(repo.get("group") or "").strip()
    if group:
        base = base / group
    return (base / str(repo["id"])).resolve(strict=False)


def _workspace_repo_output(config: ResolvedConfig, repo_id: str, group: str = "") -> Path:
    base = config.paths.wiki_system_root
    if group:
        base = base / group
    return (base / repo_id).resolve(strict=False)


def load_registry(config: ResolvedConfig) -> Dict[str, Any]:
    path = config.paths.wiki_registry
    if not path.is_file():
        return {"version": 1, "workspaces": []}
    data = load_config(path, use_cache=False)
    if "workspaces" not in data or not isinstance(data["workspaces"], list):
        raise ValueError(f"wiki registry missing workspaces list: {path}")
    return data


def _matching_workspace(registry: Dict[str, Any], workspace_root: Path) -> Optional[Dict[str, Any]]:
    matches = []
    for ws in registry.get("workspaces", []):
        root = ws.get("workspace_root")
        if root and same_path(Path(str(root)), workspace_root):
            matches.append(ws)
    if len(matches) > 1:
        raise ValueError(f"multiple registry workspaces match {workspace_root}")
    return matches[0] if matches else None


def resolve_targets(
    config: ResolvedConfig,
    *,
    repo_id: Optional[str] = None,
    repo_root: "str | Path | None" = None,
    include_disabled: bool = False,
) -> List[RepoTarget]:
    registry = load_registry(config)
    ws = _matching_workspace(registry, config.paths.workspace_root)
    targets: List[RepoTarget] = []

    if ws:
        ws_id = str(ws.get("id") or "workspace")
        for repo in ws.get("repos", []):
            if not isinstance(repo, dict) or not repo.get("id") or not repo.get("repo_root"):
                continue
            enabled = bool(repo.get("enabled", True))
            if not enabled and not include_disabled:
                continue
            rid = str(repo["id"])
            if repo_id and rid != repo_id:
                continue
            rroot = Path(str(repo["repo_root"])).resolve(strict=False)
            group = str(repo.get("group") or "")
            if config.paths.wiki_layout == "legacy-central":
                out = _legacy_repo_output(config, ws_id, repo)
            else:
                out = _workspace_repo_output(config, rid, group)
            targets.append(RepoTarget(
                workspace_id=ws_id,
                repo_id=rid,
                repo_root=rroot,
                wiki_repo_root=out,
                enabled=enabled,
                group=group,
                frontend=bool(repo.get("frontend", False)),
                multimodule=bool(repo.get("multimodule", False)),
                coverage=dict(repo.get("coverage") or {}),
            ))
    elif registry.get("workspaces") and not repo_root:
        raise ValueError(f"workspace not registered in wiki registry: {config.paths.workspace_root}")
    elif repo_root or repo_id:
        rid = repo_id or Path(str(repo_root)).name
        rroot = Path(str(repo_root or config.paths.workspace_root)).resolve(strict=False)
        targets.append(RepoTarget(
            workspace_id=config.paths.workspace_root.name or "workspace",
            repo_id=rid,
            repo_root=rroot,
            wiki_repo_root=_workspace_repo_output(config, rid),
        ))
    else:
        # Zero-config local mode: the opened workspace itself is one repo.
        rid = config.paths.workspace_root.name or "workspace"
        targets.append(RepoTarget(
            workspace_id=rid,
            repo_id=rid,
            repo_root=config.paths.workspace_root,
            wiki_repo_root=_workspace_repo_output(config, rid),
        ))

    if repo_id and not targets:
        raise ValueError(f"repo not found in matched workspace registry: {repo_id}")
    return targets




def resolve_workspace_identity(config: ResolvedConfig) -> Dict[str, Any]:
    registry = load_registry(config)
    ws = _matching_workspace(registry, config.paths.workspace_root)
    if ws:
        return {"resolved": True, "workspace_id": str(ws.get("id") or "workspace"), "source": "wiki-registry"}
    binding = load_project_binding(config.paths.workspace_root)
    if binding.wiki_id:
        return {"resolved": True, "workspace_id": binding.wiki_id, "source": "project-binding"}
    if registry.get("workspaces"):
        return {"resolved": False, "workspace_id": "", "source": "unmapped"}
    return {"resolved": False, "workspace_id": "", "source": "zero-config"}

def resolve_workspace_wiki_root(config: ResolvedConfig) -> Path:
    """Resolve the current workspace's Wiki container root without a Junction.

    In legacy-central layout this is usually ``projects/<workspace-id>`` and may
    contain multiple repository Wiki roots.  In workspace-root layout the system
    root itself is the workspace container.  Project binding ``wiki_id`` is a
    fail-closed fallback when a central registry is intentionally absent.
    """
    registry = load_registry(config)
    ws = _matching_workspace(registry, config.paths.workspace_root)
    if ws:
        ws_id = str(ws.get("id") or "workspace")
        if config.paths.wiki_layout == "legacy-central":
            template = str(config.data["systems"]["wiki"].get("workspace_dir_template") or "projects/{workspace_id}")
            return (config.paths.wiki_system_root / template.format(workspace_id=ws_id)).resolve(strict=False)
        return config.paths.wiki_system_root.resolve(strict=False)
    binding = load_project_binding(config.paths.workspace_root)
    if binding.wiki_id:
        if config.paths.wiki_layout == "legacy-central":
            template = str(config.data["systems"]["wiki"].get("workspace_dir_template") or "projects/{workspace_id}")
            return (config.paths.wiki_system_root / template.format(workspace_id=binding.wiki_id)).resolve(strict=False)
        return (config.paths.wiki_system_root / binding.wiki_id).resolve(strict=False)
    if registry.get("workspaces"):
        raise ValueError(f"workspace not registered in wiki registry and no project-binding wiki_id: {config.paths.workspace_root}")
    return config.paths.wiki_system_root.resolve(strict=False)

def write_local_registry(config: ResolvedConfig, workspace_id: str, repos: List[Dict[str, Any]]) -> Path:
    path = config.paths.wiki_registry
    if config.paths.wiki_layout == "legacy-central" and path.is_file():
        raise ValueError("refusing to overwrite legacy central registry; edit it explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "workspaces": [{
            "id": workspace_id,
            "workspace_root": str(config.paths.workspace_root),
            "repos": repos,
        }],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    return path
