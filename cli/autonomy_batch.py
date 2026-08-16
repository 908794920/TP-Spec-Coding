# -*- coding: utf-8 -*-
"""Thin Batch/commit binding for Autonomous Maintenance.

A Batch groups ordinary approved Tasks that execute during one autonomy cycle.
It does not own workflow state: Task Runtime remains authoritative and Git is the
code-change truth.  Batch manifests are disposable/rebuildable control-plane
projections stored under the isolated Autonomous Workspace.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from . import autonomy_cycle, autonomy_git, autonomy_profile, autonomy_records
from . import db as dbmod


SCHEMA = "tp-spec.autonomy-batch/v1"


class AutonomyBatchError(RuntimeError):
    pass


def _runtime(profile_id: str) -> Tuple[Dict[str, Any], Path, str]:
    profile = autonomy_profile.load_profile(profile_id)
    root = Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    db_path = root / ".tp-spec" / "db" / f"{runtime_id}.db"
    if not db_path.is_file():
        raise AutonomyBatchError(f"AUTONOMY_RUNTIME_NOT_READY: {db_path}")
    return profile, root, str(db_path)


def _mutable_repos(profile: Dict[str, Any], root: Path) -> List[Tuple[str, Path]]:
    out: List[Tuple[str, Path]] = []
    repos = ((profile.get("canonical") or {}).get("repositories") or {}).get("mutable") or []
    for row in repos:
        rel = str(row.get("path") or "")
        rid = str(row.get("id") or Path(rel).name)
        repo = (root / rel).resolve()
        if not autonomy_git.is_git_repo(repo):
            raise AutonomyBatchError(f"AUTONOMY_MUTABLE_REPO_INVALID: {rid}: {repo}")
        out.append((rid, repo))
    return out


def _dir(root: Path) -> Path:
    return root / ".tp-spec" / "autonomy" / "batches"


def _path(root: Path, batch_id: str) -> Path:
    return _dir(root) / f"{batch_id}.json"


def _atomic_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def load_batch(profile_id: str, batch_id: str) -> Dict[str, Any]:
    _, root, _ = _runtime(profile_id)
    path = _path(root, batch_id)
    if not path.is_file():
        raise AutonomyBatchError(f"AUTONOMY_BATCH_NOT_FOUND: {batch_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("profile_id") != profile_id:
        raise AutonomyBatchError(f"AUTONOMY_BATCH_INVALID: {batch_id}")
    return data


def _save(root: Path, batch: Dict[str, Any]) -> Dict[str, Any]:
    batch["updated_at"] = dbmod.now_iso()
    _atomic_json(_path(root, str(batch["batch_id"])), batch)
    return batch


def _next_batch_id(root: Path) -> str:
    date = dbmod.now_iso()[:10].replace("-", "")
    prefix = f"BATCH-{date}-"
    maximum = 0
    d = _dir(root)
    if d.is_dir():
        for p in d.glob(f"{prefix}*.json"):
            try:
                maximum = max(maximum, int(p.stem.rsplit("-", 1)[1]))
            except (ValueError, IndexError):
                continue
    return f"{prefix}{maximum + 1}"


def _task_row(db_path: str, task_id: str) -> Dict[str, Any]:
    conn = dbmod.connect_readonly(db_path)
    try:
        row = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise AutonomyBatchError(f"AUTONOMY_TASK_NOT_FOUND: {task_id}")
        return dict(row)
    finally:
        conn.close()


def _assert_cycle(profile_id: str, cycle_id: str, generation: int) -> None:
    autonomy_cycle.require_cycle_token(profile_id, cycle_id, generation)


def create_batch(profile_id: str, cycle_id: str, generation: int, task_ids: Iterable[str]) -> Dict[str, Any]:
    _assert_cycle(profile_id, cycle_id, generation)
    profile, root, db_path = _runtime(profile_id)
    tasks: List[str] = []
    for raw in task_ids:
        task_id = str(raw or "").strip()
        if not task_id or task_id in tasks:
            continue
        row = _task_row(db_path, task_id)
        if str(row.get("current_state") or "") in {"COMPLETED", "CANCELLED"}:
            raise AutonomyBatchError(f"AUTONOMY_BATCH_TASK_TERMINAL: {task_id}")
        if "repo_mutation" not in autonomy_records.allowed_effects(profile_id, task_id, generation):
            raise AutonomyBatchError(f"AUTONOMY_TASK_NOT_APPROVED_FOR_CYCLE: {task_id}")
        tasks.append(task_id)
    if not tasks:
        raise AutonomyBatchError("AUTONOMY_BATCH_EMPTY")

    # Batch selection is part of the unattended cycle work budget.  Validate
    # the union before mutating the marker so an oversized Batch cannot leave a
    # half-claimed safety budget behind.
    marker = autonomy_cycle.cycle_status(profile_id)
    claimed = {str(x) for x in (marker.get("claimed_tasks") or []) if str(x)}
    limit = int((profile.get("safety") or {}).get("max_existing_tasks_per_cycle") or 5)
    requested = claimed | set(tasks)
    if len(requested) > limit:
        raise AutonomyBatchError(f"CYCLE_TASK_LIMIT_REACHED: claimed={len(claimed)} requested={len(tasks)} max={limit}")
    for task_id in tasks:
        autonomy_cycle.claim_task(profile_id, cycle_id, generation, task_id)

    repos: Dict[str, Dict[str, Any]] = {}
    for rid, repo in _mutable_repos(profile, root):
        if autonomy_git.dirty(repo):
            raise AutonomyBatchError(f"AUTONOMY_STAGING_DIRTY_BEFORE_BATCH: {rid}")
        h = autonomy_git.head(repo)
        repos[rid] = {"path": str(repo), "base_head": h, "head": h}

    now = dbmod.now_iso()
    batch = {
        "schema": SCHEMA,
        "batch_id": _next_batch_id(root),
        "profile_id": profile_id,
        "cycle_id": cycle_id,
        "generation": int(generation),
        "status": "RUNNING",
        "tasks": tasks,
        "task_runs": {},
        "repositories": repos,
        "created_at": now,
        "updated_at": now,
    }
    return _save(root, batch)


def _assert_running(batch: Dict[str, Any], cycle_id: str, generation: int) -> None:
    if batch.get("status") != "RUNNING":
        raise AutonomyBatchError(f"AUTONOMY_BATCH_NOT_RUNNING: {batch.get('batch_id')}")
    if batch.get("cycle_id") != cycle_id or int(batch.get("generation") or 0) != int(generation):
        raise AutonomyBatchError("AUTONOMY_BATCH_CYCLE_MISMATCH")


def start_task(profile_id: str, batch_id: str, task_id: str, cycle_id: str, generation: int) -> Dict[str, Any]:
    _assert_cycle(profile_id, cycle_id, generation)
    profile, root, _ = _runtime(profile_id)
    batch = load_batch(profile_id, batch_id)
    _assert_running(batch, cycle_id, generation)
    if task_id not in batch.get("tasks", []):
        raise AutonomyBatchError(f"AUTONOMY_BATCH_TASK_NOT_MEMBER: {task_id}")
    existing = (batch.get("task_runs") or {}).get(task_id)
    if isinstance(existing, dict) and existing.get("status") in {"STARTED", "COMMITTED", "NO_CODE_CHANGE"}:
        return existing

    repos: Dict[str, str] = {}
    for rid, repo in _mutable_repos(profile, root):
        if autonomy_git.dirty(repo):
            raise AutonomyBatchError(f"AUTONOMY_STAGING_DIRTY_BEFORE_TASK: {rid}")
        repos[rid] = autonomy_git.head(repo)
    run = {"status": "STARTED", "started_at": dbmod.now_iso(), "repositories": repos}
    batch.setdefault("task_runs", {})[task_id] = run
    _save(root, batch)
    return run


def _ensure_git_identity(repo: Path) -> None:
    try:
        name = autonomy_git.git(repo, "config", "user.name", check=False).strip()
        email = autonomy_git.git(repo, "config", "user.email", check=False).strip()
    except Exception:
        name = email = ""
    if not name:
        autonomy_git.git(repo, "config", "user.name", "TP-Spec Autonomy")
    if not email:
        autonomy_git.git(repo, "config", "user.email", "tp-spec-autonomy@local.invalid")


def commit_task(profile_id: str, batch_id: str, task_id: str, cycle_id: str, generation: int) -> Dict[str, Any]:
    _assert_cycle(profile_id, cycle_id, generation)
    profile, root, db_path = _runtime(profile_id)
    batch = load_batch(profile_id, batch_id)
    _assert_running(batch, cycle_id, generation)
    if task_id not in batch.get("tasks", []):
        raise AutonomyBatchError(f"AUTONOMY_BATCH_TASK_NOT_MEMBER: {task_id}")
    row = _task_row(db_path, task_id)
    if str(row.get("current_state") or "") != "COMPLETED":
        raise AutonomyBatchError(f"AUTONOMY_TASK_NOT_COMPLETED: {task_id}")
    run = (batch.get("task_runs") or {}).get(task_id)
    if not isinstance(run, dict):
        raise AutonomyBatchError(f"AUTONOMY_TASK_NOT_STARTED: {task_id}")
    if run.get("status") in {"COMMITTED", "NO_CODE_CHANGE"}:
        return run

    result_repos: Dict[str, Dict[str, Any]] = {}
    start_heads = run.get("repositories") or {}
    for rid, repo in _mutable_repos(profile, root):
        expected = str(start_heads.get(rid) or "")
        if not expected:
            raise AutonomyBatchError(f"AUTONOMY_TASK_START_HEAD_MISSING: {task_id}:{rid}")
        current_head = autonomy_git.head(repo)
        if current_head != expected:
            raise AutonomyBatchError(
                f"AUTONOMY_UNBOUND_GIT_COMMIT: {task_id}:{rid}: HEAD {current_head} != task start {expected}"
            )
        if autonomy_git.dirty(repo):
            _ensure_git_identity(repo)
            autonomy_git.git(repo, "add", "-A")
            title = str(row.get("title") or task_id).strip()
            autonomy_git.git(repo, "commit", "-m", f"{task_id}: {title}")
            commit = autonomy_git.head(repo)
            result_repos[rid] = {"start_head": expected, "commit": commit, "head": commit, "no_code_change": False}
        else:
            result_repos[rid] = {"start_head": expected, "commit": expected, "head": expected, "no_code_change": True}
        batch["repositories"][rid]["head"] = result_repos[rid]["head"]

    run.update({
        "status": "NO_CODE_CHANGE" if all(r["no_code_change"] for r in result_repos.values()) else "COMMITTED",
        "completed_at": dbmod.now_iso(),
        "repositories": result_repos,
    })
    _save(root, batch)
    return run


def abort_task(profile_id: str, batch_id: str, task_id: str, cycle_id: str, generation: int) -> Dict[str, Any]:
    _assert_cycle(profile_id, cycle_id, generation)
    profile, root, _ = _runtime(profile_id)
    batch = load_batch(profile_id, batch_id)
    _assert_running(batch, cycle_id, generation)
    run = (batch.get("task_runs") or {}).get(task_id)
    if not isinstance(run, dict):
        raise AutonomyBatchError(f"AUTONOMY_TASK_NOT_STARTED: {task_id}")
    starts = run.get("repositories") or {}
    restored: Dict[str, str] = {}
    for rid, repo in _mutable_repos(profile, root):
        value = starts.get(rid)
        if isinstance(value, dict):
            value = value.get("start_head")
        start = str(value or "")
        if not start:
            raise AutonomyBatchError(f"AUTONOMY_TASK_START_HEAD_MISSING: {task_id}:{rid}")
        autonomy_git.git(repo, "reset", "--hard", start)
        autonomy_git.git(repo, "clean", "-fd")
        restored[rid] = autonomy_git.head(repo)
        batch["repositories"][rid]["head"] = restored[rid]
    run.update({"status": "ABORTED", "aborted_at": dbmod.now_iso(), "restored_heads": restored})
    _save(root, batch)
    return run


def finalize_batch(profile_id: str, batch_id: str, cycle_id: str, generation: int) -> Dict[str, Any]:
    _assert_cycle(profile_id, cycle_id, generation)
    profile, root, db_path = _runtime(profile_id)
    batch = load_batch(profile_id, batch_id)
    _assert_running(batch, cycle_id, generation)
    ready_tasks: List[str] = []
    deferred_tasks: List[str] = []
    for task_id in batch.get("tasks", []):
        row = _task_row(db_path, task_id)
        run = (batch.get("task_runs") or {}).get(task_id)
        state = str(row.get("current_state") or "")
        run_status = str((run or {}).get("status") or "") if isinstance(run, dict) else ""
        if state == "COMPLETED" and run_status in {"COMMITTED", "NO_CODE_CHANGE"}:
            ready_tasks.append(task_id)
            continue
        # A task that was never started, or whose unverified work was explicitly
        # aborted/reset, remains an ordinary Task for a later cycle.
        if run is None or run_status == "ABORTED":
            deferred_tasks.append(task_id)
            continue
        # STARTED work may still contain changes or unresolved workflow facts.
        # Never silently drop it at cycle close.
        raise AutonomyBatchError(f"AUTONOMY_BATCH_TASK_UNRESOLVED: {task_id}: state={state} run={run_status}")

    for rid, repo in _mutable_repos(profile, root):
        if autonomy_git.dirty(repo):
            raise AutonomyBatchError(f"AUTONOMY_STAGING_DIRTY_AT_FINALIZE: {rid}")
        batch["repositories"][rid]["head"] = autonomy_git.head(repo)

    batch["ready_tasks"] = ready_tasks
    batch["deferred_tasks"] = deferred_tasks
    if ready_tasks and deferred_tasks:
        batch["status"] = "PARTIAL_READY"
    elif ready_tasks:
        batch["status"] = "READY_FOR_INTEGRATION"
    else:
        batch["status"] = "NO_READY_CHANGES"
    batch["finalized_at"] = dbmod.now_iso()
    return _save(root, batch)


def list_batches(profile_id: str) -> List[Dict[str, Any]]:
    _, root, _ = _runtime(profile_id)
    out: List[Dict[str, Any]] = []
    d = _dir(root)
    if not d.is_dir():
        return out
    for path in sorted(d.glob("BATCH-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("profile_id") == profile_id:
                out.append(data)
        except Exception:
            continue
    return out
