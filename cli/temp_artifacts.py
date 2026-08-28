# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.2.8 临时工件所有权与安全清理。"""
from __future__ import annotations

import json
import os
import re
import stat
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import db as dbmod
from .environment import user_tp_spec_root

SCHEMA = "tp-spec.temporary-artifact/v1"
STATUS_ACTIVE = "ACTIVE"
STATUS_CLEANED = "CLEANED"
STATUS_CLEANUP_PENDING = "CLEANUP_PENDING"

_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TASK_ID_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]*$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPARSE_POINT = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _abs_path(value: "str | Path") -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(value))))


def temp_base_root(temp_root: "str | Path | None" = None) -> Path:
    """返回 TP-Spec 受控系统临时根，不创建目录。"""
    raw = temp_root or os.environ.get("TP_SPEC_TEMP_ROOT") or tempfile.gettempdir()
    return _abs_path(raw) / "tp-spec"


def manifest_root(user_root: "str | Path | None" = None) -> Path:
    """返回机器本地临时工件清单根。"""
    base = _abs_path(user_root) if user_root is not None else user_tp_spec_root()
    return base / "temp-artifacts" / "manifests"


def _validate_identity(project_id: str, task_id: str, run_id: str) -> None:
    if not _PROJECT_ID_RE.fullmatch(project_id or ""):
        raise ValueError(f"invalid project_id for temporary artifact: {project_id!r}")
    if not _TASK_ID_RE.fullmatch(task_id or ""):
        raise ValueError(f"invalid task_id for temporary artifact: {task_id!r}")
    if not _RUN_ID_RE.fullmatch(run_id or "") or run_id in {".", ".."}:
        raise ValueError(f"invalid run_id for temporary artifact: {run_id!r}")


def _manifest_path(project_id: str, task_id: str, run_id: str, *, user_root=None) -> Path:
    _validate_identity(project_id, task_id, run_id)
    return manifest_root(user_root) / project_id / task_id / f"{run_id}.json"


def _expected_run_root(project_id: str, task_id: str, run_id: str, *, temp_root=None) -> Path:
    _validate_identity(project_id, task_id, run_id)
    return temp_base_root(temp_root) / project_id / task_id / run_id


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_manifest(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"temporary artifact manifest not found: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"temporary artifact manifest unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError(f"temporary artifact manifest schema invalid: {path}")
    return data


def _ensure_safe_parent_tree(base: Path, project_id: str, task_id: str) -> None:
    """逐级创建受控父目录，拒绝软链接、Junction/reparse point 和非目录节点。"""
    base.mkdir(parents=True, exist_ok=True)
    chain = [base, base / project_id, base / project_id / task_id]
    for pos, path in enumerate(chain):
        if pos > 0:
            try:
                path.mkdir()
            except FileExistsError:
                # 并发运行可能同时创建同一 project/task 父目录；随后 lstat 再校验节点类型。
                pass
        try:
            st = os.lstat(path)
        except FileNotFoundError as exc:
            raise ValueError(f"temporary artifact parent disappeared during creation: {path}") from exc
        if stat.S_ISLNK(st.st_mode) or _is_reparse_stat(st):
            raise ValueError(f"temporary artifact parent must not be symlink/reparse point: {path}")
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError(f"temporary artifact parent is not a directory: {path}")


def _validate_safe_cleanup_ancestors(base: Path, project_id: str, task_id: str) -> Optional[str]:
    """清理前再次验证中间父目录，避免 TOCTOU 把受控路径替换为链接。"""
    for path in (base, base / project_id, base / project_id / task_id):
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode) or _is_reparse_stat(st):
            return f"cleanup ancestor is symlink/reparse point: {path}"
        if not stat.S_ISDIR(st.st_mode):
            return f"cleanup ancestor is not a directory: {path}"
    return None


def create_run_root(
    *,
    project_id: str,
    task_id: str,
    creator_role: str,
    creator_agent: str = "",
    run_id: Optional[str] = None,
    user_root: "str | Path | None" = None,
    temp_root: "str | Path | None" = None,
) -> Dict[str, Any]:
    """创建并登记一个受控运行临时根；先登记所有权，再创建目录。"""
    rid = str(run_id or f"RUN-{uuid.uuid4().hex}")
    _validate_identity(project_id, task_id, rid)
    base = temp_base_root(temp_root)
    root = _expected_run_root(project_id, task_id, rid, temp_root=temp_root)
    mpath = _manifest_path(project_id, task_id, rid, user_root=user_root)

    if mpath.is_file():
        existing = _read_manifest(mpath)
        expected_identity = (project_id, task_id, rid)
        actual_identity = (
            str(existing.get("project_id") or ""),
            str(existing.get("task_id") or ""),
            str(existing.get("run_id") or ""),
        )
        if actual_identity != expected_identity:
            raise ValueError(f"temporary artifact manifest identity mismatch: {mpath}")
        if existing.get("status") == STATUS_CLEANED:
            raise ValueError(f"temporary artifact run already cleaned; use a new run_id: {rid}")
        if existing.get("status") == STATUS_CLEANUP_PENDING:
            raise ValueError(f"temporary artifact cleanup is pending; retry cleanup before reuse: {rid}")
        if str(existing.get("creator_role") or "") != str(creator_role or ""):
            raise ValueError(f"temporary artifact owner role mismatch for run_id: {rid}")
        if str(existing.get("creator_agent") or "") != str(creator_agent or ""):
            raise ValueError(f"temporary artifact owner agent mismatch for run_id: {rid}")
        if _lexical_key(existing.get("root_path")) != _lexical_key(root):
            raise ValueError(f"temporary artifact manifest root mismatch: {mpath}")
        _ensure_safe_parent_tree(base, project_id, task_id)
        try:
            root_stat = os.lstat(root)
        except FileNotFoundError:
            root.mkdir(parents=False, exist_ok=False)
        else:
            if stat.S_ISLNK(root_stat.st_mode) or _is_reparse_stat(root_stat):
                raise ValueError(f"temporary artifact owned root must not be symlink/reparse point: {root}")
            if not stat.S_ISDIR(root_stat.st_mode):
                raise ValueError(f"temporary artifact owned root is not a directory: {root}")
        out = dict(existing)
        out["manifest_path"] = str(mpath)
        return out

    now = dbmod.now_iso()
    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "project_id": project_id,
        "task_id": task_id,
        "run_id": rid,
        "creator_role": str(creator_role or ""),
        "creator_agent": str(creator_agent or ""),
        "temp_base": str(base),
        "root_path": str(root),
        "status": STATUS_ACTIVE,
        "created_at": now,
        "cleanup_at": "",
        "cleanup_error": "",
    }
    _atomic_write_json(mpath, payload)
    try:
        _ensure_safe_parent_tree(base, project_id, task_id)
        root.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        payload["status"] = STATUS_CLEANUP_PENDING
        payload["cleanup_error"] = "owned run root already exists before creation"
        _atomic_write_json(mpath, payload)
        raise ValueError(f"temporary artifact run root already exists: {root}")
    except ValueError as exc:
        payload["status"] = STATUS_CLEANUP_PENDING
        payload["cleanup_error"] = f"create rejected: {exc}"
        _atomic_write_json(mpath, payload)
        raise
    except OSError as exc:
        payload["status"] = STATUS_CLEANUP_PENDING
        payload["cleanup_error"] = f"create failed: {type(exc).__name__}: {exc}"
        _atomic_write_json(mpath, payload)
        raise
    out = dict(payload)
    out["manifest_path"] = str(mpath)
    return out


def _lexical_key(value: "str | Path | None") -> str:
    if value in (None, ""):
        return ""
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(value))))


def _is_reparse_stat(st: os.stat_result) -> bool:
    return bool(int(getattr(st, "st_file_attributes", 0)) & _REPARSE_POINT)


def _remove_leaf(path: Path, st: os.stat_result) -> None:
    if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
        os.rmdir(path)
    else:
        os.unlink(path)


def _remove_tree_no_follow(path: Path) -> None:
    """递归删除受控根，但绝不跟随软链接或 Windows reparse point。"""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode) or _is_reparse_stat(st):
        _remove_leaf(path, st)
        return
    if not stat.S_ISDIR(st.st_mode):
        os.unlink(path)
        return
    with os.scandir(path) as it:
        entries = list(it)
    for entry in entries:
        _remove_tree_no_follow(Path(entry.path))
    os.rmdir(path)


def _set_cleanup_status(path: Path, payload: Dict[str, Any], *, status: str, error: str = "") -> Dict[str, Any]:
    updated = dict(payload)
    updated["status"] = status
    updated["cleanup_at"] = dbmod.now_iso()
    updated["cleanup_error"] = error
    _atomic_write_json(path, updated)
    out = dict(updated)
    out["manifest_path"] = str(path)
    out["error"] = error
    return out


def cleanup_run(
    *,
    project_id: str,
    task_id: str,
    run_id: str,
    user_root: "str | Path | None" = None,
    temp_root: "str | Path | None" = None,
) -> Dict[str, Any]:
    """幂等清理一个已登记运行；任何身份或路径异常都 fail-closed。"""
    mpath = _manifest_path(project_id, task_id, run_id, user_root=user_root)
    payload = _read_manifest(mpath)
    if payload.get("status") == STATUS_CLEANED:
        out = dict(payload)
        out["manifest_path"] = str(mpath)
        out["error"] = ""
        return out

    expected_base = temp_base_root(temp_root)
    expected_root = _expected_run_root(project_id, task_id, run_id, temp_root=temp_root)
    actual_identity = (
        str(payload.get("project_id") or ""),
        str(payload.get("task_id") or ""),
        str(payload.get("run_id") or ""),
    )
    if actual_identity != (project_id, task_id, run_id):
        return _set_cleanup_status(mpath, payload, status=STATUS_CLEANUP_PENDING, error="ownership identity mismatch")
    if _lexical_key(payload.get("temp_base")) != _lexical_key(expected_base):
        return _set_cleanup_status(mpath, payload, status=STATUS_CLEANUP_PENDING, error="controlled temp base mismatch")
    if _lexical_key(payload.get("root_path")) != _lexical_key(expected_root):
        return _set_cleanup_status(mpath, payload, status=STATUS_CLEANUP_PENDING, error="owned root mismatch")
    ancestor_error = _validate_safe_cleanup_ancestors(expected_base, project_id, task_id)
    if ancestor_error:
        return _set_cleanup_status(mpath, payload, status=STATUS_CLEANUP_PENDING, error=ancestor_error)

    try:
        _remove_tree_no_follow(expected_root)
    except OSError as exc:
        return _set_cleanup_status(
            mpath,
            payload,
            status=STATUS_CLEANUP_PENDING,
            error=f"cleanup failed: {type(exc).__name__}: {exc}",
        )
    return _set_cleanup_status(mpath, payload, status=STATUS_CLEANED)


def cleanup_run_if_registered(
    *,
    project_id: str,
    task_id: str,
    run_id: str,
    user_root: "str | Path | None" = None,
    temp_root: "str | Path | None" = None,
) -> Dict[str, Any]:
    """仅当 ownership manifest 已存在时清理；未登记运行保持无副作用。"""
    path = _manifest_path(project_id, task_id, run_id, user_root=user_root)
    if not path.is_file():
        return {
            "project_id": project_id,
            "task_id": task_id,
            "run_id": run_id,
            "status": "NOT_REGISTERED",
            "error": "",
        }
    return cleanup_run(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        user_root=user_root,
        temp_root=temp_root,
    )


def list_records(*, user_root: "str | Path | None" = None) -> List[Dict[str, Any]]:
    """读取全部机器本地 ownership manifest；损坏清单以问题记录返回。"""
    root = manifest_root(user_root)
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = _read_manifest(path)
            row = dict(payload)
            row["manifest_path"] = str(path)
            out.append(row)
        except ValueError as exc:
            # 损坏 manifest 仍按机器本地目录键保留 project/task/run 归属，便于收口报告且绝不据此删除。
            rel = path.relative_to(root)
            parts = rel.parts
            row = {"manifest_path": str(path), "status": "INVALID", "error": str(exc)}
            if len(parts) == 3 and path.suffix == ".json":
                row.update({"project_id": parts[0], "task_id": parts[1], "run_id": path.stem})
            out.append(row)
    return out


def records_for_task(
    *,
    task_id: str,
    project_id: Optional[str] = None,
    user_root: "str | Path | None" = None,
) -> List[Dict[str, Any]]:
    return [
        row for row in list_records(user_root=user_root)
        if row.get("task_id") == task_id and (not project_id or row.get("project_id") == project_id)
    ]


def cleanup_task(
    *,
    task_id: str,
    project_id: Optional[str] = None,
    user_root: "str | Path | None" = None,
    temp_root: "str | Path | None" = None,
) -> Dict[str, Any]:
    """幂等清理指定 Task 已登记的全部临时运行。"""
    rows = records_for_task(task_id=task_id, project_id=project_id, user_root=user_root)
    results: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("status") == "INVALID":
            results.append(row)
            continue
        results.append(
            cleanup_run(
                project_id=str(row["project_id"]),
                task_id=str(row["task_id"]),
                run_id=str(row["run_id"]),
                user_root=user_root,
                temp_root=temp_root,
            )
        )
    return summarize_records(results)


def summarize_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(records)
    return {
        "created": len(rows),
        "active": sum(1 for row in rows if row.get("status") == STATUS_ACTIVE),
        "cleaned": sum(1 for row in rows if row.get("status") == STATUS_CLEANED),
        "pending": sum(1 for row in rows if row.get("status") in {STATUS_CLEANUP_PENDING, "INVALID"}),
        "runs": rows,
    }


def _runtime_orphan_context(db_path: "str | Path", task_id: Optional[str]) -> Dict[str, Any]:
    """只读提取 Task 与 Work Session 事实，用于 orphan 分类，不修改 Runtime。"""
    path = _abs_path(db_path)
    conn = dbmod.connect_readonly(str(path))
    try:
        if task_id:
            task_rows = conn.execute(
                "SELECT task_id, project_id, current_state FROM task WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        else:
            task_rows = conn.execute(
                "SELECT task_id, project_id, current_state FROM task"
            ).fetchall()
        rows = conn.execute(
            "SELECT task_id, event_type, detail_json FROM task_event "
            "WHERE (? IS NULL OR task_id = ?) "
            "AND event_type IN ('WORK_SESSION_STARTED','WORK_SESSION_ENDED') ORDER BY id",
            (task_id, task_id),
        ).fetchall()
    finally:
        conn.close()

    tasks = {str(row["task_id"]): dict(row) for row in task_rows}
    sessions: Dict[str, Dict[str, Dict[str, bool]]] = {}
    for row in rows:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            detail = {}
        sid = str(detail.get("session_id") or "")
        event_task = str(row["task_id"] or "")
        if not sid or not event_task:
            continue
        task_sessions = sessions.setdefault(event_task, {})
        state = task_sessions.setdefault(sid, {"started": False, "ended": False})
        if row["event_type"] == "WORK_SESSION_STARTED":
            state["started"] = True
        elif row["event_type"] == "WORK_SESSION_ENDED":
            state["ended"] = True
    return {"tasks": tasks, "sessions": sessions}


def orphan_report(
    *,
    workspace_root: "str | Path | None" = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    user_root: "str | Path | None" = None,
    db_path: "str | Path | None" = None,
) -> Dict[str, Any]:
    """只报告已登记残留和工作区 `.tmp` 候选；该接口永不删除。"""
    runtime_context: Optional[Dict[str, Any]] = None
    runtime_error = ""
    if db_path is not None:
        try:
            runtime_context = _runtime_orphan_context(db_path, task_id)
        except (OSError, ValueError, sqlite3.Error) as exc:
            runtime_error = f"{type(exc).__name__}: {exc}"

    records = [
        row for row in list_records(user_root=user_root)
        if (not project_id or row.get("project_id") == project_id)
        and (not task_id or row.get("task_id") == task_id)
        and row.get("status") != STATUS_CLEANED
    ]
    owned_candidates = []
    for row in records:
        item = dict(row)
        status = str(row.get("status") or "")
        if status in {STATUS_CLEANUP_PENDING, "INVALID"}:
            classification = "CLEANUP_PENDING"
        elif runtime_context is None:
            classification = "ACTIVE_OWNED"
        else:
            row_task_id = str(row.get("task_id") or "")
            task = (runtime_context.get("tasks") or {}).get(row_task_id)
            run_id = str(row.get("run_id") or "")
            sessions = runtime_context.get("sessions") or {}
            session = (sessions.get(row_task_id) or {}).get(run_id) or {}
            if task is None:
                classification = "ORPHAN_TASK_MISSING"
            elif str(task.get("current_state") or "") in {"COMPLETED", "CANCELLED"}:
                classification = "ORPHAN_TASK_TERMINAL"
            elif run_id.startswith("WORK-") and session.get("ended"):
                classification = "ORPHAN_SESSION_ENDED"
            elif run_id.startswith("WORK-") and session.get("started"):
                classification = "ACTIVE_SESSION_OPEN"
            elif run_id.startswith("WORK-"):
                classification = "ORPHAN_SESSION_MISSING"
            else:
                classification = "ACTIVE_OWNED"
        item["classification"] = classification
        owned_candidates.append(item)

    unmanaged: List[Dict[str, Any]] = []
    if workspace_root is not None:
        workspace = _abs_path(workspace_root)
        legacy_tmp = workspace / ".tmp"
        if legacy_tmp.is_dir():
            for child in sorted(legacy_tmp.iterdir(), key=lambda p: p.name.casefold()):
                unmanaged.append({
                    "classification": "UNMANAGED_WORKSPACE_TEMP",
                    "path": str(child),
                    "reason": "workspace .tmp entry has no TP-Spec ownership manifest",
                })

    return {
        "schema": "tp-spec.temporary-artifact-orphan-report/v1",
        "owned_candidates": owned_candidates,
        "unmanaged_candidates": unmanaged,
        "runtime_error": runtime_error,
        "auto_deleted": 0,
    }
