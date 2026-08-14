# -*- coding: utf-8 -*-
"""One-shot legacy namespace migration into the v5.2.1 tp-spec namespace.

Legacy names exist only in this boundary so normal runtime code never carries a
second namespace fallback. Ambiguous coexistence fails closed.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable

LEGACY_PROJECT_DIR = ".ai-work"
NEW_PROJECT_DIR = ".tp-spec"
LEGACY_USER_DIR = ".ai-work"
NEW_USER_DIR = ".tp-spec"

_TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".jsonl", ".txt"}


def _home(value=None) -> Path:
    return Path(value).expanduser().resolve() if value else Path.home().resolve()


def legacy_user_root(home=None) -> Path:
    return _home(home) / LEGACY_USER_DIR


def new_user_root(home=None) -> Path:
    return _home(home) / NEW_USER_DIR


def _pair_status(legacy: Path, new: Path, label: str) -> Dict[str, Any]:
    if legacy.exists() and new.exists():
        return {"label": label, "status": "BLOCKED", "legacy": str(legacy), "new": str(new),
                "blocker": f"{label}: legacy and new namespace roots both exist"}
    if legacy.exists():
        return {"label": label, "status": "MIGRATION_AVAILABLE", "legacy": str(legacy), "new": str(new)}
    if new.exists():
        return {"label": label, "status": "CURRENT", "legacy": str(legacy), "new": str(new)}
    return {"label": label, "status": "ABSENT", "legacy": str(legacy), "new": str(new)}


def namespace_plan(workspace_root, *, home=None) -> Dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    project = _pair_status(workspace / LEGACY_PROJECT_DIR, workspace / NEW_PROJECT_DIR, "project")
    user = _pair_status(legacy_user_root(home), new_user_root(home), "user")
    blockers = [row["blocker"] for row in (project, user) if row["status"] == "BLOCKED"]
    if blockers:
        status = "BLOCKED"
    elif any(row["status"] == "MIGRATION_AVAILABLE" for row in (project, user)):
        status = "MIGRATION_AVAILABLE"
    elif any(row["status"] == "CURRENT" for row in (project, user)):
        status = "CURRENT"
    else:
        status = "ABSENT"
    legacy_env = sorted(k for k in os.environ if k.startswith("AI_WORK_"))
    return {
        "schema": "tp-spec.namespace-migration/v1",
        "status": status,
        "workspace_root": str(workspace),
        "project": project,
        "user": user,
        "legacy_environment_variables_ignored": legacy_env,
        "blockers": blockers,
    }


_LEGACY_COMMAND_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])ai-work(?=\s+(?:"
    r"base|project|task|workflow|knowledge|wiki|commit|event|projection|receipt|"
    r"review|reconcile|work-session|config|--help|-h)\b)"
)


def _rewrite_namespace_text(text: str) -> str:
    """Rewrite only namespace/control tokens, never arbitrary brand substrings.

    Physical paths and business prose can legitimately contain names such as
    ``ai-work-base`` or ``ai-work-tools``. Rebranding those would corrupt user
    data. The migration therefore limits itself to protocol/schema prefixes,
    state-directory paths, environment/key names, known launcher names and
    actual legacy CLI invocations.
    """
    for old, new in (
        ("AI_WORK_", "TP_SPEC_"),
        (".ai-work", ".tp-spec"),
        ("ai-work.", "tp-spec."),
        ("ai_work_root", "tp_spec_root"),
        ("aiwork.db", "tp-spec.db"),
        ("ai-work-base:managed", "tp-spec:managed"),
        ("Invoke-AiWorkCli.ps1", "tp-spec.ps1"),
        ("Invoke-AiWorkHandoffFlush.ps1", "Invoke-TpSpecHandoffFlush.ps1"),
        ("Invoke-AiWorkHandoff.ps1", "Invoke-TpSpecHandoff.ps1"),
        ("Test-AiWorkTask.ps1", "Test-TpSpecTask.ps1"),
        ("ai-work.ps1", "tp-spec.ps1"),
    ):
        text = text.replace(old, new)
    return _LEGACY_COMMAND_RE.sub("tp-spec", text)


def _rewrite_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
        return False
    raw = path.read_bytes()
    if b"\x00" in raw:
        return False
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    updated = _rewrite_namespace_text(text)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8", newline="\n")
    return True


def _rewrite_user_state(root: Path) -> list[str]:
    changed = []
    for name in ("installation.yaml", "workspaces.yaml", "registry.local.json"):
        path = root / name
        if _rewrite_file(path):
            changed.append(str(path))
    return changed


def _rewrite_project_active_state(root: Path) -> list[str]:
    changed = []
    if not root.is_dir():
        return changed
    # Runtime DB/evidence/history are facts; only active textual control surfaces are mechanically renamed.
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in {"evidence", "tasksHistory", ".flush-journal", ".execution"} for part in rel.parts):
            continue
        if path.name == "events.jsonl":
            continue
        if _rewrite_file(path):
            changed.append(str(path))
    return changed


def migrate_namespace(workspace_root, *, home=None, apply=False) -> Dict[str, Any]:
    plan = namespace_plan(workspace_root, home=home)
    if plan["status"] == "BLOCKED":
        return {**plan, "apply": bool(apply), "actions": []}
    actions = []
    if not apply:
        return {**plan, "apply": False, "actions": ["RENAME_LEGACY_NAMESPACE"] if plan["status"] == "MIGRATION_AVAILABLE" else []}
    workspace = Path(workspace_root).resolve()
    pairs = [
        (workspace / LEGACY_PROJECT_DIR, workspace / NEW_PROJECT_DIR, "project"),
        (legacy_user_root(home), new_user_root(home), "user"),
    ]
    for legacy, new, label in pairs:
        if legacy.exists():
            if new.exists():
                return {**namespace_plan(workspace, home=home), "apply": True, "actions": actions}
            os.replace(legacy, new)
            actions.append({"action": "RENAME_NAMESPACE_ROOT", "scope": label, "from": str(legacy), "to": str(new)})
    user_root = new_user_root(home)
    for path in _rewrite_user_state(user_root):
        actions.append({"action": "REWRITE_NAMESPACE_TEXT", "path": path})
    project_root = workspace / NEW_PROJECT_DIR
    for path in _rewrite_project_active_state(project_root):
        actions.append({"action": "REWRITE_NAMESPACE_TEXT", "path": path})
    for name in ("README.md", "AGENTS.md"):
        path = workspace / name
        if _rewrite_file(path):
            actions.append({"action": "REWRITE_NAMESPACE_TEXT", "path": str(path)})
    final = namespace_plan(workspace, home=home)
    return {**final, "status": "PASS" if final["status"] in {"CURRENT", "ABSENT"} else final["status"],
            "apply": True, "actions": actions}
