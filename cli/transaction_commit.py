# -*- coding: utf-8 -*-
"""Neutral durable transaction/projection primitives for V5.2.5 Record-first Runtime.

This module contains no legacy long-state workflow or Action-role policy.  Migration-only
compatibility remains under :mod:`cli.migrations.v5_2_3`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import db as dbmod
from . import projection_cmd
from . import transaction_journal
from .commit_errors import ProjectionCommitFailedError, ReconciliationRequiredError
from .encoding_guard import EncodingValidationError
from .path_identity import same_path
from .transaction_journal import JOURNAL_SCHEMA, PHASE_DB_COMMITTED, PHASE_FILES_REPLACED, PHASE_PREPARED
from .version import active_version

ACTIVE_CONTRACT = active_version()

def _read(path: Path) -> str:
    # Preserve CRLF/LF exactly: generated-view digests must agree with the
    # PowerShell validator, whose Get-Content -Raw does not normalize line ends.
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return handle.read()

def _continuation_sources(task_dir: Path, state: str) -> List[Path]:
    """Return the formal artifacts completed before the current owner starts work."""
    names = ["status.yaml", "events.jsonl", "task.md", "acceptance.md"]
    if state in {"CLOSING", "COMPLETED"}:
        names.extend(["implementation.md", "codex-review.md"])
    elif state == "VERIFYING":
        names.append("implementation.md")
    # V5.2.5 §3.8/§10.2：新工件经集中注册表纳入 source digest（存在才纳入）
    names.extend(projection_cmd.projection_source_names())
    return [task_dir / name for name in names if (task_dir / name).is_file()]

def _source_digest(paths: List[Path], task_dir: Path) -> str:
    parts: List[str] = []
    for path in sorted(paths):
        rel = path.relative_to(task_dir).as_posix()
        parts.append(rel + "\n" + hashlib.sha256(_read(path).encode("utf-8")).hexdigest() + "\n")
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()

def _generated_view_text(task_dir: Path, name: str, body: str, sources: List[Path], flush_id: str) -> str:
    """渲染 generated view 文本（不落盘）。"""
    digest = _source_digest(sources, task_dir)
    source_lines = "\n".join(f'  - "{p.relative_to(task_dir).as_posix()}"' for p in sorted(sources))
    return (
        "---\n"
        "generated_view: true\n"
        f'generator_version: "{ACTIVE_CONTRACT}"\n'
        f'generated_at: "{dbmod.now_iso()}"\n'
        "source_files:\n" + source_lines + "\n"
        f'source_digest: "sha256:{digest}"\n'
        f'flush_id: "{flush_id}"\n'
        f'content_digest: "sha256:{hashlib.sha256(body.encode("utf-8")).hexdigest()}"\n'
        "---\n\n" + body
    )

def _deferred_acceptance_items(task_dir: Path) -> List[str]:
    """返回验收矩阵中 verdict 为 DEFERRED_ACCEPTED 且已在 deferred_acceptance
    YAML 中登记的 AC 编号（P1-4：不再仅按正则提取，YAML 登记为准）。"""
    path = task_dir / "acceptance.md"
    if not path.is_file():
        return []
    text = _read(path)
    # 1) 真实解析 deferred_acceptance YAML（fail-closed；解析失败视为无登记）
    from . import yaml_checks
    registered: set = set()
    try:
        result = yaml_checks.check_acceptance_yaml(text)
        for entry in result.deferred_entries:
            ac = entry.get("ac")
            if ac:
                registered.add(str(ac))
    except Exception:
        registered = set()
    # 2) 表格 DEFERRED_ACCEPTED 且已登记
    items: List[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        verdict = cells[8] if len(cells) > 8 else ""
        ac_id = match.group(1)
        if re.match(r"^DEFERRED_ACCEPTED\b", verdict) and ac_id in registered:
            items.append(ac_id)
    return items

def _current_view_rel(state: str) -> str:
    """当前视图投影的相对路径（按状态选择 continuation/final-result）。"""
    return "generated/final-result.md" if state == "COMPLETED" else "generated/continuation.md"

def _latest_projected_verification(task_dir: Path) -> str:
    """Return the latest verification fact and mark subject changes as stale."""
    path = task_dir / "events.jsonl"
    if not path.is_file():
        return "NOT_RECORDED"
    latest = "NOT_RECORDED"
    latest_subject = ""
    try:
        for line in _read(path).splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("type") in {"REVIEW_COMPLETED", "VERIFICATION"} and obj.get("actor") == "tp-test-engineer":
                latest = str(obj.get("decision") or "NOT_RECORDED").upper()
                latest_subject = str(obj.get("subject_digest") or "")
        if latest_subject:
            from .digest import compute_verification_subject_digest
            if compute_verification_subject_digest(task_dir) != latest_subject:
                return f"{latest}_STALE"
    except Exception:
        return "UNKNOWN"
    return latest

def _rebuild_current_view_text(task_dir: Path, task, summary: str, flush_id: str) -> str:
    """Render the readable current view from ledger facts.

    V5.2.5 intentionally exposes state/phase/result facts, not handoff bureaucracy.
    """
    state = str(task["current_state"] or "NEW")
    owner = str(task["owner_role"] or "unknown")
    phase = str(task["current_stage"] or "intake")
    sources = _continuation_sources(task_dir, state)
    verification = _latest_projected_verification(task_dir)
    if state == "COMPLETED":
        body = (
            "# 生成的结项摘要\n\n"
            f"- 任务状态：COMPLETED\n"
            f"- 最后阶段：{phase}\n"
            f"- 最后执行角色：{owner}\n"
            f"- 技术验证事实：{verification}\n"
            f"- 结论：{summary}\n"
        )
        deferred = _deferred_acceptance_items(task_dir)
        if deferred:
            body += "- 延期验收项：" + "、".join(deferred) + "（见 acceptance.md）\n"
        if verification != "PASS":
            body += "- 提示：COMPLETED 表示任务工作已结束，不代表未记录/失败/延期的验证被改写为 PASS。\n"
        return _generated_view_text(task_dir, "final-result.md", body, sources, flush_id)
    body = (
        "# 任务接续区\n\n"
        f"- 状态：{state}\n"
        f"- 当前阶段：{phase}\n"
        f"- 最近执行角色：{owner}\n"
        f"- 最近记录：{summary}\n"
        "\n> V5.2.5：phase 是查询事实，不是流程门禁；继续完成业务工作即可。\n"
    )
    return _generated_view_text(task_dir, "continuation.md", body, sources, flush_id)

def _probe_writable(task_dir: Path) -> None:
    """任务目录可写探测（探测文件立即删除，无持久副作用）。"""
    probe = task_dir / f".v511-write-probe-{uuid.uuid4().hex[:8]}"
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("")
    except OSError as e:
        raise ValueError(f"task-dir is not writable: {e}")
    finally:
        try:
            probe.unlink()
        except OSError:
            pass

def _backup(task_dir: Path, bak_dir: Path, rel_paths: List[str]) -> None:
    """备份现有投影到 bak_dir（保持相对路径结构）。

    仅备份常规文件（目录等异常占用不备份，交由替换阶段失败并回滚）。
    原不存在的文件在恢复时按删除目标处理。
    """
    for rel in rel_paths:
        src = task_dir / rel
        if src.is_file():
            dst = bak_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

def _restore(task_dir: Path, bak_dir: Path, rel_paths: List[str], journal: Optional[dict] = None) -> None:
    """从备份严格恢复（Final Hardening Task 6 / P0-8）。

    统一复用 transaction_journal.strict_restore：逐文件核验 before_digest/备份存在/
    删除目标；恢复失败抛出异常（调用方必须保留 journal+backup，禁止声称恢复成功）。
    """
    if journal is not None:
        result = transaction_journal.strict_restore(task_dir, journal)
        if not result.ok:
            raise RuntimeError(
                "strict restore failed: " + "; ".join(result.failed + result.digest_mismatches)
            )
        return
    # 无 journal 的兼容路径（正常流程不触发；保留原语义）
    for rel in rel_paths:
        src = task_dir / rel
        bak = bak_dir / rel
        if bak.is_file():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak, src)
        elif src.exists():
            try:
                src.unlink()
            except OSError:
                pass

def _stage_and_replace(task_dir: Path, texts: Dict[str, str], rel_paths: List[str]) -> None:
    """写全部临时文件后逐个 os.replace 原子替换；中途失败清理未替换的临时文件。

    texts 中不存在的 rel 跳过（reconcile 修复集是动态的；commit 的 texts 恒含全部 rel）。
    """
    staged: List[Tuple[Path, Path]] = []
    try:
        for rel in rel_paths:
            if rel not in texts:
                continue
            target = task_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(texts[rel])
            staged.append((tmp, target))
        for tmp, target in staged:
            os.replace(tmp, target)
    except Exception:
        for tmp, _ in staged:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        raise

def _sha256_file(path: Path) -> Optional[str]:
    """文件字节 sha256；不存在返回 None。"""
    if not path.is_file():
        return None
    import hashlib
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()

def _assert_task_workspace_identity(conn, task_dir: Path, task_id: str) -> None:
    """Fail closed when a canonical task directory belongs to another project root.

    This is the mutation-time defense for stale or externally corrupted registry
    state.  Custom task directories that do not prove a canonical workspace root are
    left to their existing explicit-path semantics rather than guessed about.
    """
    if not task_id:
        return
    resolved = task_dir.resolve()
    parent = resolved.parent
    if parent.name != "tasks" or parent.parent.name != ".tp-spec":
        return
    workspace_root = parent.parent.parent.resolve()
    task = conn.execute("SELECT project_id FROM task WHERE task_id=?", (task_id,)).fetchone()
    if task is None:
        return
    project_id = str(task["project_id"] or "")
    project = conn.execute("SELECT root_path FROM project WHERE project_id=?", (project_id,)).fetchone()
    stored_root = str(project["root_path"] or "").strip() if project is not None else ""
    if not stored_root or not os.path.isabs(stored_root) or not same_path(stored_root, workspace_root):
        raise ValueError(
            f"PROJECT_WORKSPACE_MISMATCH: Runtime project '{project_id}' is bound to "
            f"{stored_root or '<missing>'}, but task directory belongs to workspace {workspace_root}; "
            "refusing cross-workspace mutation"
        )

def _commit_with_recovery(task_dir: Path, conn, rel_paths: List[str], db_and_render: Callable,
                         task_id: str = "", operation: str = "commit",
                         db_state_before: str = "", target_state: str = "",
                         owner_before: str = "", owner_after: str = "",
                         flush_id: str = "") -> Dict[str, str]:
    """一致性提交核心（V5.2.5 durable journal 版）：

    1. BEGIN IMMEDIATE 获取 SQLite writer serialization；2. 读取 revision 并备份现有投影；
    3. 写 durable journal（PREPARED）；4. db_and_render(conn) 写 DB 并渲染投影；
    5. 暂存并原子替换文件；6. journal(FILES_REPLACED)；7. COMMIT；
    8. journal(DB_COMMITTED)；成功后清理并删除 journal。

    任一步失败：未提交时 ROLLBACK；只有正式投影已进入 journal 管理后才执行严格恢复。
    该机制用于进程被 kill、解释器崩溃等 process-crash recovery；由于没有对文件和目录
    执行 fsync/等价持久化屏障，不保证突然断电或存储缓存丢失后的 power-loss durability。
    返回渲染文本（供调用方打印摘要）。
    """
    tx_id = transaction_journal.new_transaction_id()
    bak_dir = task_dir / f".v511-bak-{tx_id}"
    journal: Dict[str, Any] = {}
    journal_prepared = False
    db_committed = False
    transaction_started = False
    texts: Dict[str, str] = {}

    try:
        try:
            # Acquire SQLite's single-writer lock before reading revision or copying
            # projection backups.  Concurrent writers therefore cannot prepare file
            # recovery state against a DB snapshot that another writer may advance.
            conn.execute("BEGIN IMMEDIATE")
            transaction_started = True
            _assert_task_workspace_identity(conn, task_dir, task_id)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise ValueError(
                    "TASK_WRITER_BUSY: Runtime is already being updated by another writer; retry after it finishes"
                ) from exc
            raise

        rev_before = transaction_journal.current_revision(conn, task_id)
        _backup(task_dir, bak_dir, rel_paths)
        journal = {
            "schema": JOURNAL_SCHEMA,
            "transaction_id": tx_id,
            "task_id": task_id,
            "operation": operation,
            "phase": PHASE_PREPARED,
            "db_state_before": db_state_before,
            "target_state": target_state,
            "owner_before": owner_before,
            "owner_after": owner_after,
            "flush_id": flush_id,
            "db_revision_before": rev_before,
            "expected_revision_after": None,
            "expected_event_ids": [],
            "expected_event_types": [],
            "expected_state_event_id": None,
            "expected_handoff_event_id": None,
            "backup_dir": str(bak_dir),
            "temp_dir": "",
            "files": [
                transaction_journal.make_files_entry(
                    rel_path=rel,
                    backup=str(bak_dir / rel) if (bak_dir / rel).is_file() else None,
                    temp=None,
                    before_digest=_sha256_file(bak_dir / rel),
                    target_digest=None,
                )
                for rel in rel_paths
            ],
            "created_at": dbmod.now_iso(),
            "updated_at": dbmod.now_iso(),
        }
        transaction_journal.write_journal(task_dir, journal)
        journal_prepared = True

        texts = db_and_render(conn, transaction_id=tx_id)
        journal["expected_revision_after"] = transaction_journal.current_revision(conn, task_id)
        _stage_and_replace(task_dir, texts, rel_paths)
        journal["phase"] = PHASE_FILES_REPLACED
        for entry in journal["files"]:
            entry["target_digest"] = _sha256_file(task_dir / entry["path"])
        if flush_id:
            rows = conn.execute(
                "SELECT id, event_type FROM task_event WHERE task_id=? "
                "AND detail_json LIKE ? ORDER BY id",
                (task_id, f'%"{flush_id}"%'),
            ).fetchall()
            for row in rows:
                journal["expected_event_ids"].append(row["id"])
                journal["expected_event_types"].append(row["event_type"])
                if row["event_type"] == "STATE" and journal["expected_state_event_id"] is None:
                    journal["expected_state_event_id"] = row["id"]
                if row["event_type"] == "HANDOFF" and journal["expected_handoff_event_id"] is None:
                    journal["expected_handoff_event_id"] = row["id"]
        transaction_journal.write_journal(task_dir, journal)
        conn.execute("COMMIT")
        transaction_started = False
        db_committed = True
        journal["phase"] = PHASE_DB_COMMITTED
        transaction_journal.write_journal(task_dir, journal)
    except BaseException as exc:
        if transaction_started and not db_committed:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            transaction_started = False

        if db_committed:
            raise ReconciliationRequiredError(
                f"DB committed but post-commit step failed: {exc}; "
                f"evidence preserved (journal={tx_id}, backup={bak_dir}); "
                "run 'tp-spec reconcile' to resolve"
            ) from exc

        if journal_prepared:
            try:
                _restore(task_dir, bak_dir, rel_paths, journal)
            except Exception as restore_err:
                raise ReconciliationRequiredError(
                    f"DB rolled back but file restore FAILED: {restore_err}; "
                    f"evidence preserved (journal={tx_id}, backup={bak_dir}); "
                    "run 'tp-spec reconcile' to resolve"
                ) from exc
            transaction_journal.remove_journal(task_dir, tx_id)
        else:
            # No formal projection replacement could have occurred before PREPARED;
            # cleanup only copied backup/journal preparation artifacts.
            transaction_journal.remove_journal(task_dir, tx_id)

        shutil.rmtree(bak_dir, ignore_errors=True)
        if isinstance(exc, (ValueError, EncodingValidationError)):
            raise
        raise ProjectionCommitFailedError(
            f"commit write failed and was rolled back (db restored, files restored): {exc}"
        ) from exc

    transaction_journal.remove_journal(task_dir, tx_id)
    shutil.rmtree(bak_dir, ignore_errors=True)
    return texts

def _warn_projection(warnings: List[str]) -> None:
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)

def _finalize_texts(task_dir: Path, texts: Dict[str, str], view_rel: str, render_view: Callable[[], str]) -> Dict[str, str]:
    """先行落盘非 view 投影，再渲染 view 并入 texts。

    current view 的 source_digest 基于 source_files 的最终文件内容；
    若与其他投影同批替换前渲染，会读到旧内容导致
    GENERATED_SOURCE_DIGEST_MISMATCH（PowerShell 校验器逐文件重算）。
    先替换 status/events/handoff/front matter 工件，再渲染 view，digest 才自洽。
    """
    non_view = {k: v for k, v in texts.items() if k != view_rel}
    _stage_and_replace(task_dir, non_view, list(non_view))
    texts[view_rel] = render_view()
    return texts
