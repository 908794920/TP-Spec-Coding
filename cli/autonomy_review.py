# -*- coding: utf-8 -*-
"""Read-only Autonomous Maintenance review/inbox projections.

Git commits and the ordinary Task ledger are authoritative.  This module only
summarizes them; full diffs are returned only when explicitly requested.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import autonomy_batch, autonomy_git, autonomy_profile
from . import db as dbmod


def _runtime(profile_id: str) -> tuple[Dict[str, Any], Path, str]:
    profile = autonomy_profile.load_profile(profile_id)
    root = Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    db_path = root / ".tp-spec" / "db" / f"{runtime_id}.db"
    if not db_path.is_file():
        raise ValueError(f"AUTONOMY_RUNTIME_NOT_READY: {db_path}")
    return profile, root, str(db_path)


def _parse(raw: Any) -> Dict[str, Any]:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _task_counts(db_path: str, profile_id: str) -> Dict[str, int]:
    conn = dbmod.connect_readonly(db_path)
    try:
        rows = conn.execute("SELECT task_id,current_state FROM task ORDER BY task_id").fetchall()
        waiting = 0; progress = 0; failed = 0
        for row in rows:
            state = str(row["current_state"] or "")
            if state == "BLOCKED":
                events = conn.execute(
                    "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='BLOCKER' ORDER BY id DESC",
                    (row["task_id"],),
                ).fetchall()
                for ev in events:
                    d = _parse(ev["detail_json"])
                    if d.get("operation") == "AUTONOMY_BOUNDARY" and d.get("profile_id") == profile_id:
                        waiting += 1; break
            elif state in {"NEW", "ACTIVE"}:
                progress += 1
            elif state == "CANCELLED":
                failed += 1
        return {"awaiting_user_decision": waiting, "in_progress": progress, "failed_or_cancelled": failed}
    finally:
        conn.close()


def review_profile(profile_id: str) -> Dict[str, Any]:
    profile, root, db_path = _runtime(profile_id)
    counts = _task_counts(db_path, profile_id)
    batches = autonomy_batch.list_batches(profile_id)
    ready = [b for b in batches if b.get("status") in {"READY_FOR_INTEGRATION", "PARTIAL_READY"}]
    return {
        "schema": "tp-spec.autonomy-review-profile/v1",
        "profile_id": profile_id,
        "enabled": bool(profile.get("enabled", True)),
        "canonical_root": str((profile.get("canonical") or {}).get("workspace_root") or ""),
        "autonomy_root": str(root),
        **counts,
        "awaiting_integration": len(ready),
        "ready_batches": [str(b.get("batch_id")) for b in ready],
    }


def inbox() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for profile in autonomy_profile.list_profiles(ignore_errors=True):
        pid = str(profile.get("profile_id") or "")
        if not pid:
            continue
        try:
            rows.append(review_profile(pid))
        except Exception as exc:
            errors.append({"profile_id": pid, "error": str(exc)})
    return {"schema": "tp-spec.autonomy-inbox/v1", "profiles": rows, "errors": errors}


def _numstat(repo: Path, base: str, tip: str) -> Tuple[int, int, int, List[str]]:
    if base == tip:
        return 0, 0, 0, []
    raw = autonomy_git.git(repo, "diff", "--numstat", f"{base}..{tip}")
    added = deleted = 0; files: List[str] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        a, d, name = parts
        try: added += int(a)
        except ValueError: pass
        try: deleted += int(d)
        except ValueError: pass
        files.append(name)
    return len(files), added, deleted, files


def review_batch(profile_id: str, batch_id: str) -> Dict[str, Any]:
    batch = autonomy_batch.load_batch(profile_id, batch_id)
    repos_out: Dict[str, Any] = {}
    total_files = total_add = total_del = 0
    for rid, binding in (batch.get("repositories") or {}).items():
        repo = Path(str(binding.get("path") or "")).resolve()
        base = str(binding.get("base_head") or "")
        head = str(binding.get("head") or base)
        n, a, d, files = _numstat(repo, base, head)
        total_files += n; total_add += a; total_del += d
        repos_out[rid] = {"base_head": base, "head": head, "files_changed": n, "insertions": a, "deletions": d, "files": files}

    tasks: List[Dict[str, Any]] = []
    for task_id in batch.get("tasks") or []:
        run = (batch.get("task_runs") or {}).get(task_id) or {}
        task_repos: Dict[str, Any] = {}
        for rid, row in (run.get("repositories") or {}).items():
            if not isinstance(row, dict):
                continue
            task_repos[rid] = {
                "start_head": row.get("start_head"), "commit": row.get("commit"),
                "head": row.get("head"), "no_code_change": bool(row.get("no_code_change")),
            }
        tasks.append({"task_id": task_id, "status": run.get("status"), "repositories": task_repos})
    return {
        "schema": "tp-spec.autonomy-review-batch/v1", "profile_id": profile_id,
        "batch_id": batch_id, "status": batch.get("status"), "cycle_id": batch.get("cycle_id"),
        "files_changed": total_files, "insertions": total_add, "deletions": total_del,
        "repositories": repos_out, "tasks": tasks,
    }


def _find_task_binding(profile_id: str, task_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    for batch in reversed(autonomy_batch.list_batches(profile_id)):
        run = (batch.get("task_runs") or {}).get(task_id)
        if isinstance(run, dict):
            return batch, run
    return None, None


def review_task(profile_id: str, task_id: str, *, include_diff: bool = False) -> Dict[str, Any]:
    profile, root, db_path = _runtime(profile_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            raise ValueError(f"AUTONOMY_TASK_NOT_FOUND: {task_id}")
        task_row = dict(task)
    finally:
        conn.close()
    batch, run = _find_task_binding(profile_id, task_id)
    repos_out: Dict[str, Any] = {}
    if run:
        for rid, row in (run.get("repositories") or {}).items():
            if not isinstance(row, dict):
                continue
            repo_binding = ((batch or {}).get("repositories") or {}).get(rid) or {}
            repo = Path(str(repo_binding.get("path") or "")).resolve()
            start = str(row.get("start_head") or row.get("commit") or "")
            head = str(row.get("head") or row.get("commit") or start)
            n, a, d, files = _numstat(repo, start, head)
            item: Dict[str, Any] = {
                "start_head": start, "commit": row.get("commit"), "head": head,
                "no_code_change": bool(row.get("no_code_change")),
                "files_changed": n, "insertions": a, "deletions": d, "files": files,
            }
            if include_diff and start and head and start != head:
                item["diff"] = autonomy_git.git(repo, "diff", "--no-ext-diff", f"{start}..{head}")
            repos_out[rid] = item
    return {
        "schema": "tp-spec.autonomy-review-task/v1", "profile_id": profile_id,
        "task_id": task_id, "title": str(task_row.get("title") or ""),
        "state": str(task_row.get("current_state") or ""),
        "batch_id": (batch or {}).get("batch_id"), "repositories": repos_out,
    }
