# -*- coding: utf-8 -*-
"""Canonical content-system write fence for Autonomous Workspaces."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .environment import load_project_binding


class AutonomyContextError(RuntimeError):
    pass


_KNOWLEDGE_READ_ONLY = {"doctor", "lint", "status", "search", "telemetry", "eval", "migrate-plan"}
_WIKI_READ_ONLY = {"doctor", "coverage", "anchors-doctor", "status"}


def context_mode(workspace_root: str | Path) -> str:
    binding = load_project_binding(workspace_root)
    meta = binding.data.get("autonomy") if isinstance(binding.data, dict) else None
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("context_mode") or "")


def guard_content_cli(args: Any) -> None:
    group = str(getattr(args, "group", "") or "")
    if group not in {"knowledge", "wiki"}:
        return
    workspace = getattr(args, "workspace_root", None)
    if not workspace or context_mode(workspace) != "canonical_read_only":
        return

    if group == "knowledge":
        command = str(getattr(args, "knowledge_cmd", "") or "")
        # Nested read-only status commands remain safe.
        if command in _KNOWLEDGE_READ_ONLY:
            return
        if command == "index" and str(getattr(args, "index_cmd", "") or "") == "status":
            return
        if command == "ingest" and str(getattr(args, "ingest_cmd", "") or "") == "status":
            return
        if command == "migrate-normalize" and not bool(getattr(args, "apply", False)):
            return
    else:
        command = str(getattr(args, "wiki_cmd", "") or "")
        if command in _WIKI_READ_ONLY:
            return

    raise AutonomyContextError(
        f"AUTONOMY_CANONICAL_CONTEXT_READ_ONLY: {group} mutation is not allowed from Autonomous Workspace {Path(workspace).resolve()}"
    )
