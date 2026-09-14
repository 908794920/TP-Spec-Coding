# -*- coding: utf-8 -*-
"""Deterministic project-facing TP-Spec-Coding entrypoint maintenance.

The project root README/AGENTS managed block and ``.tp-spec/README.md`` are a
portable integration surface. They describe stable resolver behavior only;
machine-specific paths stay in the installation profile and are never rendered
into project files. ``.tp-spec/memory`` is bootstrapped create-once and remains
project-owned after creation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Dict, List, Optional

from cli.environment import load_project_binding

BASE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = BASE_ROOT / "project-entry"
MANAGED_START = "<!-- tp-spec-base:managed:start -->"
MANAGED_END = "<!-- tp-spec-base:managed:end -->"


class ProjectSurfaceError(ValueError):
    pass


def project_path_issue(path: Path, workspace: Path, *, directory: bool = False) -> Optional[str]:
    """Reject links/junctions and wrong target kinds before managed writes."""
    if not path.is_relative_to(workspace) or not path.resolve().is_relative_to(workspace):
        return f"refusing project write outside workspace: {path}"
    # 大小写不一致会在不同文件系统上变成覆盖或第二真源，不能替用户选边/重命名。
    if path == workspace / "AGENTS.md" and workspace.is_dir():
        aliases = sorted(p.name for p in workspace.iterdir()
                         if p.name.casefold() == "agents.md" and p.name != "AGENTS.md")
        if aliases:
            return f"ambiguous project rule filename: {', '.join(aliases)}; confirm exact AGENTS.md before sync"
    current = path
    while current != workspace:
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            return f"refusing linked project write: {current}"
        current = current.parent
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        return f"unexpected project target kind: {path}"
    return None


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
    newline = "\r\n" if "\r\n" in text else "\n"
    body = block.rstrip("\n").replace("\n", newline)
    if starts == 1:
        start, end = text.index(MANAGED_START), text.index(MANAGED_END)
        if end < start:
            raise ProjectSurfaceError("managed block end precedes its start")
        # Outside the markers belongs to the project: preserve BOM, whitespace,
        # line endings and trailing content rather than normalizing the document.
        return text[:start] + body + text[end + len(MANAGED_END):], "REPLACE_MANAGED_BLOCK"
    separator = "" if not text or text.endswith(newline * 2) else (newline if text.endswith(newline) else newline * 2)
    return text + separator + body + newline, "APPEND_MANAGED_BLOCK"


def _project_id(workspace: Path, explicit: str = "") -> str:
    if explicit:
        return explicit
    binding = load_project_binding(workspace)
    return binding.project_id or workspace.name


def _memory_bootstrap_rows(workspace: Path, *, project_id: str) -> List[Dict[str, Any]]:
    """Return create-once project Memory rows; existing content is never managed by Base."""
    rows: List[Dict[str, Any]] = []
    for rel, template in (("INDEX.md", "memory-index.md"), ("PROJECT.md", "memory-project.md")):
        path = workspace / ".tp-spec" / "memory" / rel
        exists = path.is_file()
        rows.append({
            "path": str(path),
            "state": "CURRENT" if exists else "MISSING",
            "action": "NONE" if exists else "CREATE_PROJECT_MEMORY",
            "changed": not exists,
            "content": None if exists else _render(template, project_id=project_id),
        })
    return rows


def project_surface_plan(workspace_root: "str | Path", *, project_id: str = "") -> Dict[str, Any]:
    workspace = Path(workspace_root).resolve(strict=False)
    pid = _project_id(workspace, project_id)
    block = _managed_block(project_id=pid)
    rows: List[Dict[str, Any]] = []
    blockers: List[str] = []

    for rel in ("AGENTS.md", "README.md"):
        path = workspace / rel
        try:
            issue = project_path_issue(path, workspace)
            if issue:
                raise ProjectSurfaceError(issue)
            before_bytes = path.read_bytes() if path.is_file() else None
            before = before_bytes.decode("utf-8") if before_bytes is not None else ""
            after, action = _replace_managed(before, block)
        except (ProjectSurfaceError, OSError, UnicodeError) as exc:
            blockers.append(f"{rel}: {exc}")
            rows.append({"path": str(path), "state": "BLOCKED", "action": "NONE", "changed": False})
            continue
        if not path.is_file():
            action = "CREATE_WITH_MANAGED_BLOCK"
            if rel == "README.md":
                after = f"# {pid}\n\n{block}"
        changed = before != after
        rows.append({"path": str(path), "state": "STALE" if changed else "CURRENT", "action": action if changed else "NONE", "changed": changed, "content": after,
                     "before_sha256": hashlib.sha256(before_bytes).hexdigest() if before_bytes is not None else None})

    runtime_readme = workspace / ".tp-spec" / "README.md"
    desired = _render("tp-spec-readme.md", project_id=pid)
    before_bytes = runtime_readme.read_bytes() if runtime_readme.is_file() else None
    before = before_bytes.decode("utf-8-sig") if before_bytes is not None else ""
    changed = before.replace("\r\n", "\n") != desired.replace("\r\n", "\n")
    rows.append({"path": str(runtime_readme), "state": "STALE" if changed else "CURRENT", "action": "WRITE_BASE_MANAGED_README" if changed else "NONE", "changed": changed, "content": desired,
                 "before_sha256": hashlib.sha256(before_bytes).hexdigest() if before_bytes is not None else None})
    rows.extend(_memory_bootstrap_rows(workspace, project_id=pid))
    for row in rows:
        path = Path(row["path"])
        if row.get("changed"):
            issue = project_path_issue(path, workspace)
            if issue:
                blockers.append(issue)
    issue = project_path_issue(workspace / ".tp-spec" / "memory" / "skills", workspace, directory=True)
    if issue:
        blockers.append(issue)


    return {
        "schema": "tp-spec.project-surface-plan/v1",
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
    workspace = Path(plan["workspace_root"])
    changes: List[Dict[str, Any]] = []
    try:
        for row in plan["files"]:
            if not row.get("changed"):
                continue
            path = Path(row["path"])

            def check_unchanged():
                issue = project_path_issue(path, workspace)
                if issue:
                    raise ProjectSurfaceError(issue)
                before = path.read_bytes() if path.is_file() else None
                digest = hashlib.sha256(before).hexdigest() if before is not None else None
                if digest != row.get("before_sha256"):
                    raise ProjectSurfaceError(f"PROJECT_SURFACE_CHANGED: replan before writing {path}")

            check_unchanged()
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tp-spec-surface-", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(str(row["content"]).encode("utf-8"))
                os.chmod(temporary, mode)
                check_unchanged()
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            changes.append({"path": str(path), "action": row["action"]})
        skills = workspace / ".tp-spec" / "memory" / "skills"
        issue = project_path_issue(skills, workspace, directory=True)
        if issue:
            raise ProjectSurfaceError(issue)
        skills.mkdir(parents=True, exist_ok=True)
    except (OSError, ProjectSurfaceError) as exc:
        # Per-file replacement is atomic, not a multi-file database transaction.
        # Report completed managed writes; replan/retry, never roll back user edits.
        return {**plan, "status": "BLOCKED", "apply": True, "changes": changes,
                "blockers": [f"{type(exc).__name__}: {exc}"],
                "recovery": "Recheck ownership and current files, then repeat sync-project --apply; completed writes are idempotent."}
    final = project_surface_plan(workspace, project_id=project_id)
    return {**final, "apply": True, "changes": changes}
