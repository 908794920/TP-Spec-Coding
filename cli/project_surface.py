# -*- coding: utf-8 -*-
"""Deterministic project-facing TP-Spec-Coding entrypoint maintenance.

The project root README/AGENTS managed block and ``.ai-work/README.md`` are a
portable integration surface.  They describe stable resolver behavior only;
machine-specific paths stay in the installation profile and are never rendered
into project files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from cli.environment import load_project_binding

BASE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = BASE_ROOT / "project-entry"
MANAGED_START = "<!-- ai-work-base:managed:start -->"
MANAGED_END = "<!-- ai-work-base:managed:end -->"


class ProjectSurfaceError(ValueError):
    pass


def _render(name: str, *, project_id: str) -> str:
    path = TEMPLATE_ROOT / name
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("{{PROJECT_ID}}", project_id).rstrip() + "\n"


def _managed_block(*, project_id: str) -> str:
    body = _render("root-managed-block.md", project_id=project_id).rstrip()
    return f"{MANAGED_START}\n{body}\n{MANAGED_END}\n"


def _replace_managed(text: str, block: str) -> tuple[str, str]:
    starts = text.count(MANAGED_START)
    ends = text.count(MANAGED_END)
    if starts != ends or starts > 1:
        raise ProjectSurfaceError(f"malformed managed block markers: starts={starts}, ends={ends}")
    if starts == 1:
        left, rest = text.split(MANAGED_START, 1)
        _, right = rest.split(MANAGED_END, 1)
        rendered = left.rstrip() + ("\n\n" if left.strip() else "") + block.rstrip() + ("\n\n" if right.strip() else "\n") + right.lstrip()
        return rendered.rstrip() + "\n", "REPLACE_MANAGED_BLOCK"
    rendered = text.rstrip()
    if rendered:
        rendered += "\n\n"
    rendered += block.rstrip() + "\n"
    return rendered, "APPEND_MANAGED_BLOCK"


def _project_id(workspace: Path, explicit: str = "") -> str:
    if explicit:
        return explicit
    binding = load_project_binding(workspace)
    return binding.project_id or workspace.name


def project_surface_plan(workspace_root: "str | Path", *, project_id: str = "") -> Dict[str, Any]:
    workspace = Path(workspace_root).resolve(strict=False)
    pid = _project_id(workspace, project_id)
    block = _managed_block(project_id=pid)
    rows: List[Dict[str, Any]] = []
    blockers: List[str] = []

    for rel in ("AGENTS.md", "README.md"):
        path = workspace / rel
        before = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
        try:
            after, action = _replace_managed(before, block)
        except ProjectSurfaceError as exc:
            blockers.append(f"{rel}: {exc}")
            rows.append({"path": str(path), "state": "BLOCKED", "action": "NONE", "changed": False})
            continue
        if not path.is_file():
            action = "CREATE_WITH_MANAGED_BLOCK"
            if rel == "README.md":
                after = f"# {pid}\n\n{block}"
        changed = before.replace("\r\n", "\n") != after.replace("\r\n", "\n")
        rows.append({"path": str(path), "state": "STALE" if changed else "CURRENT", "action": action if changed else "NONE", "changed": changed, "content": after})

    runtime_readme = workspace / ".ai-work" / "README.md"
    desired = _render("ai-work-readme.md", project_id=pid)
    before = runtime_readme.read_text(encoding="utf-8-sig") if runtime_readme.is_file() else ""
    changed = before.replace("\r\n", "\n") != desired.replace("\r\n", "\n")
    rows.append({"path": str(runtime_readme), "state": "STALE" if changed else "CURRENT", "action": "WRITE_BASE_MANAGED_README" if changed else "NONE", "changed": changed, "content": desired})

    return {
        "schema": "ai-work.project-surface-plan/v1",
        "workspace_root": str(workspace),
        "project_id": pid,
        "status": "BLOCKED" if blockers else ("SYNC_AVAILABLE" if any(r.get("changed") for r in rows) else "CURRENT"),
        "blockers": blockers,
        "files": rows,
    }


def sync_project_surface(workspace_root: "str | Path", *, project_id: str = "", apply: bool = False) -> Dict[str, Any]:
    plan = project_surface_plan(workspace_root, project_id=project_id)
    if plan["status"] == "BLOCKED" or not apply:
        return {**plan, "apply": bool(apply), "changes": []}
    changes: List[Dict[str, Any]] = []
    for row in plan["files"]:
        if not row.get("changed"):
            continue
        path = Path(row["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(row["content"]), encoding="utf-8", newline="\n")
        changes.append({"path": str(path), "action": row["action"]})
    final = project_surface_plan(workspace_root, project_id=project_id)
    return {**final, "apply": True, "changes": changes}
