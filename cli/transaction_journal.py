# -*- coding: utf-8 -*-
"""V5.2.6 durable transaction journal（P0：强制终止后可确定性恢复）。

纯 stdlib、离线。commit/reconcile 在正式替换文件前写入持久化 journal。
该机制面向进程被 kill、解释器崩溃等 process-crash recovery，由 reconcile 依据
journal + DB revision 判定恢复；当前未执行文件/目录 fsync，因此不保证突然断电或
存储缓存丢失后的 power-loss durability：

- 阶段：PREPARED → FILES_REPLACED → DB_COMMITTED → COMPLETED（完成后删除 journal）；
- journal 位置：``<task_dir>/.tp-spec/transactions/<transaction_id>.json``；
- journal 本身原子写（临时文件 + os.replace），避免半写；
- revision = task_event 行数（按 task_id 隔离，DB 推进的稳定度量）。

恢复判定（任务书 §3.3）：
- 情况 A（DB 未推进，任务事件数 == db_revision_before）：恢复全部备份、删临时目标；
- 情况 B（DB 已推进，任务事件数 == expected_revision_after **且** current_state/owner
  与 target_state/owner_after 一致 **且** journal 声明的目标 STATE/HANDOFF 事件
  （expected_state_event_id / expected_handoff_event_id）在 DB 中存在且 detail 的
  flush_id 与 journal.flush_id 相同）：按 DB 完成全部投影；
- 情况 C（无法判定）：不得删除任何备份，输出 PROJECTION_RECONCILIATION_REQUIRED。

身份安全（同任务事件碰撞）：仅 revision 相等不足以下结论——同一任务上后来新提交
的 flush 可能使事件数撞上 expected_revision_after。因此情况 B 必须同时满足
state+owner+目标事件+flush_id+revision 五要素，任一不满足即情况 C。

设计依据：V5.2.6 AI-A 定向修复任务书 §3 与审查报告 §3.2。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

JOURNAL_SCHEMA = "tp-spec.transaction/v1"
PHASE_PREPARED = "PREPARED"
PHASE_FILES_REPLACED = "FILES_REPLACED"
PHASE_DB_COMMITTED = "DB_COMMITTED"
PHASE_COMPLETED = "COMPLETED"

# 任务目录下与备份/临时区同盘的 journal 根（与任务书 §3.2 路径约定一致）
JOURNAL_ROOT_NAME = ".tp-spec"
TRANSACTIONS_DIR_NAME = "transactions"


@dataclass
class RestoreResult:
    """严格恢复结果（Final Hardening Task 6 / P0-8）。ok=False 时调用方必须保留
    journal + backup 作为恢复证据，不得声称恢复成功。"""
    ok: bool
    restored: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    digest_mismatches: List[str] = field(default_factory=list)


def _file_sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def strict_restore(task_dir: Path, journal: Dict[str, Any]) -> RestoreResult:
    """统一严格恢复（commit / reconcile 共用，禁止各模块再维护独立 _restore）。

    逐文件核验（任务书 §3.3 / 审查报告 P0-7/P0-8）：
    - 有 before_digest（原文件存在）：必须存在备份，且备份内容 == before_digest；
      恢复后再次核验目标 digest == before_digest；
    - 无 before_digest（原文件不存在）：目标必须恢复为"确实不存在"；
    - 任一核验失败记入 failed/digest_mismatches 并继续其余文件；
      ok=False 时调用方必须保留 journal + backup。
    """
    result = RestoreResult(ok=True)
    for entry in journal.get("files") or []:
        rel = entry.get("path", "")
        if not rel:
            continue
        target = task_dir / rel
        before_digest = entry.get("before_digest")
        bak = Path(entry["backup"]) if entry.get("backup") else None
        if before_digest:
            if bak is None or not bak.is_file():
                result.failed.append(f"{rel}:backup_missing")
                result.ok = False
                continue
            if _file_sha256(bak) != before_digest:
                result.digest_mismatches.append(f"{rel}:backup_digest")
                result.ok = False
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bak, target)
            except OSError as e:
                result.failed.append(f"{rel}:{e}")
                result.ok = False
                continue
            if _file_sha256(target) != before_digest:
                result.digest_mismatches.append(f"{rel}:restored_digest")
                result.ok = False
                continue
            result.restored.append(f"restored:{rel}")
        else:
            # 原文件不存在 → 本次产生的新文件必须删除（恢复"确实不存在"）
            if target.exists():
                try:
                    if target.is_dir():
                        target.rmdir()  # 空目录（如故障注入的目录占用）
                    else:
                        target.unlink()
                    result.restored.append(f"removed:{rel}")
                except OSError as e:
                    result.failed.append(f"{rel}:{e}")
                    result.ok = False
            else:
                result.restored.append(f"absent:{rel}")
    return result


def transactions_dir(task_dir: Path) -> Path:
    """journal 目录：<task_dir>/.tp-spec/transactions/。"""
    return task_dir / JOURNAL_ROOT_NAME / TRANSACTIONS_DIR_NAME


def new_transaction_id() -> str:
    return f"tx-{uuid.uuid4().hex}"


def _write_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def write_journal(task_dir: Path, tx: Dict[str, Any]) -> Path:
    """写入（或更新）journal。返回 journal 路径。

    P1-6/审查报告：每次 phase 更新必须刷新 updated_at 为真实新时间（不得沿用
    created_at），供审计与恢复时序判定。同进程连续写入时强制单调递增
    （不足 1 微秒时补齐），避免同值时间戳破坏时序。
    """
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    prev = tx.get("updated_at") or tx.get("created_at") or ""
    if prev and ts <= prev:
        try:
            dt = datetime.strptime(prev, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            ts = (dt + timedelta(microseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            ts = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ") + "+0"
    tx["updated_at"] = ts
    path = transactions_dir(task_dir) / f"{tx['transaction_id']}.json"
    _write_atomic(path, tx)
    return path


def read_journal(task_dir: Path, transaction_id: str) -> Optional[Dict[str, Any]]:
    path = transactions_dir(task_dir) / f"{transaction_id}.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def list_journals(task_dir: Path) -> List[Dict[str, Any]]:
    """列出任务目录下全部可读 journal（按 created_at 升序）。"""
    result: List[Dict[str, Any]] = []
    d = transactions_dir(task_dir)
    if not d.is_dir():
        return result
    for p in sorted(d.glob("*.json")):
        data = read_journal(task_dir, p.stem)
        if data is not None:
            result.append(data)
    return result


def remove_journal(task_dir: Path, transaction_id: str) -> None:
    """删除 journal（仅恢复/完成成功后调用）。"""
    path = transactions_dir(task_dir) / f"{transaction_id}.json"
    try:
        path.unlink()
    except OSError:
        pass


def current_revision(conn, task_id: Optional[str] = None) -> int:
    """DB 推进度量：task_event 行数（按 task_id 隔离）。

    V5.2.6 P0-3：revision 必须按 task_id 隔离，禁止使用全局 COUNT(*)。
    全局计数会导致任务 A 未提交时任务 B 增加 event 使 A 误判提交成功。
    task_id 为 None 时回退全局计数（仅向后兼容旧调用点）。
    """
    if task_id:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM task_event WHERE task_id = ?", (task_id,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS c FROM task_event").fetchone()
    return int(row["c"]) if row else 0


def make_files_entry(rel_path: str, backup: Optional[str], temp: Optional[str],
                     before_digest: Optional[str], target_digest: Optional[str]) -> Dict[str, Any]:
    return {
        "path": rel_path,
        "backup": backup,
        "temp": temp,
        "before_digest": before_digest,
        "target_digest": target_digest,
    }
