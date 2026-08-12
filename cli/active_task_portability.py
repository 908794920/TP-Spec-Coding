# -*- coding: utf-8 -*-
"""Detect actionable legacy Junction references in current task artifacts.

Historical task/evidence content is immutable evidence and intentionally out of
scope.  This scanner only inspects top-level Markdown formal artifacts of tasks
that are still NEW/ACTIVE/BLOCKED under ``.ai-work/tasks``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

ACTIVE_STATES = {"NEW", "ACTIVE", "BLOCKED"}
LEGACY_OPERATIONAL = re.compile(
    r"(?i)(?:\.ai-work[\\/](?:knowledge|wiki|scripts|agents|governance|skills|templates|automation|cli))(?:[\\/]|\b)"
)
NEGATION_OR_HISTORY = re.compile(
    r"(?i)(?:不得|不要|禁止|不再|无需|不依赖|已移除|旧|历史|兼容|legacy|deprecated|removed|do\s+not|must\s+not|no\s+longer)"
)


def _status(task_dir: Path) -> Dict[str, Any]:
    path = task_dir / "status.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def scan_active_task_portability(workspace_root: "str | Path") -> Dict[str, Any]:
    workspace = Path(workspace_root).resolve(strict=False)
    tasks_root = workspace / ".ai-work" / "tasks"
    findings: List[Dict[str, Any]] = []
    scanned_tasks = 0
    scanned_documents = 0
    if not tasks_root.is_dir():
        return {
            "schema": "ai-work.active-task-portability/v1",
            "status": "CURRENT",
            "workspace_root": str(workspace),
            "scanned_tasks": 0,
            "scanned_documents": 0,
            "findings": [],
        }
    for task_dir in sorted((p for p in tasks_root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        status = _status(task_dir)
        state = str(status.get("current_state") or "").strip().upper()
        if state not in ACTIVE_STATES:
            continue
        scanned_tasks += 1
        for doc in sorted(task_dir.glob("*.md"), key=lambda p: p.name.casefold()):
            scanned_documents += 1
            try:
                text = doc.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if not LEGACY_OPERATIONAL.search(line):
                    continue
                if NEGATION_OR_HISTORY.search(line):
                    continue
                findings.append({
                    "task_id": str(status.get("task_id") or task_dir.name),
                    "state": state,
                    "path": str(doc),
                    "line": lineno,
                    "snippet": line.strip()[:320],
                    "classification": "LEGACY_ACTIVE_REFERENCE",
                })
    return {
        "schema": "ai-work.active-task-portability/v1",
        "status": "REVIEW_REQUIRED" if findings else "CURRENT",
        "workspace_root": str(workspace),
        "scanned_tasks": scanned_tasks,
        "scanned_documents": scanned_documents,
        "findings": findings,
        "principle": "current operational artifacts may need targeted repair; tasksHistory/evidence are not rewritten",
    }
