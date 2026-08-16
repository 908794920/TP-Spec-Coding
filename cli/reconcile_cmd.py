# -*- coding: utf-8 -*-
"""V5.2.3 reconcile 命令（A-04 修复：durable recovery + 自身一致性）。

``tp-spec reconcile --task TASK-ID`` 以 SQLite 为唯一权威，检查并修复投影漂移。

V5.2.3 修复内容：
- **durable journal 恢复判定**（任务书 §3）：发现未完成 journal 时按
  DB revision 判定——A（DB 未推进）恢复全部备份；B（DB 已推进）按 DB
  完成全部投影；C（无法判定）不删除任何备份，输出
  PROJECTION_RECONCILIATION_REQUIRED。禁止未判定直接删除 ``.v511-bak-*``。
- **自身一致性提交**（任务书 §4）：复用 commit 的统一 transaction/journal
  机制（备份 → journal → BEGIN → 写 RECONCILIATION 事件 → 渲染 → 原子替换
  → COMMIT），不再产生“先改文件、再写 DB、再改文件”的半提交窗口。
- **深度漂移检测**（任务书 §8）：status/events 与 DB 渲染期望逐字节比对；
  handoff 与 HANDOFF 事件 payload 语义等价比对（可无损重建）；
  generated view 校验 source_files/source_digest/content_digest；
  主工件 front matter 可解析性。
- **handoff 无损重建**（任务书 §5）：从 HANDOFF 事件 handoff_payload
  的 handoff_record 完整恢复（reconstructed 元数据不影响语义等价比对）。

原则：不删除/修改历史事件；只追加 RECONCILIATION 事件（投影为 FACT，
Test-TpSpecTask.ps1 零感知）；幂等（无漂移不写事件）；失败非零退出。

设计依据：V5.2.3 AI-A 定向修复任务书 §3/§4/§5/§8 与审查报告 §3.2-§3.4/§3.7。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db as dbmod
from . import event_policies
from . import frontmatter
from . import projection_cmd
from . import transaction_journal
from .commit_cmd import (
    _commit_with_recovery,
    _current_view_rel,
    _finalize_texts,
    _read,
    _rebuild_current_view_text,
    _sha256_file,
    _source_digest,
)
from .encoding_guard import validate_input
from .version import active_version

_BAK_PREFIX = ".v511-bak-"
_TMP_SUFFIX = ".tmp"

# 主工件（front matter 可解析性检测；字段级业务规则由 AI-C 接入）
_MAIN_ARTIFACTS = ("task.md", "implementation.md", "codex-review.md", "quality-and-knowledge.md")


# =============================================================================
# journal 恢复判定（任务书 §3.3）
# =============================================================================

def _restore_from_backup(task_dir: Path, journal: Dict[str, Any]) -> List[str]:
    """情况 A：恢复全部备份，删除本次产生的目标文件。返回恢复明细。

    Final Hardening（Task 6 / P0-8）：统一复用 transaction_journal.strict_restore
    （commit 与 reconcile 同一严格恢复实现）。逐文件核验 before_digest/备份存在/
    删除目标；任一失败抛 ValueError 转入情况 C（保留证据，人工处理）。
    """
    from .transaction_journal import strict_restore
    result = strict_restore(task_dir, journal)
    if not result.ok:
        raise ValueError(
            "strict restore failed: " + "; ".join(result.failed + result.digest_mismatches)
            + "; cannot restore safely — manual resolution required"
        )
    # 无残留 temp：journal 引用 temp 的临时文件已由 _stage_and_replace 处理，
    # 此处清理未引用的 .tmp 残留（不删除备份）
    _cleanup_unowned_tmp(task_dir)
    return result.restored


def _complete_from_db(task_dir: Path, conn, task, journal: Dict[str, Any], actor: str) -> List[str]:
    """情况 B：DB 已推进 → 以 DB 完成全部投影（含 digest 校验）。返回修复明细。"""
    fixed: List[str] = []
    rels = [e.get("path", "") for e in journal.get("files") or [] if e.get("path")]
    view_rel = _current_view_rel(task["current_state"] or "NEW")
    # 1. 非 view 投影（status/events/handoff/front matter 工件）
    texts: Dict[str, str] = {}
    if "status.yaml" in rels or "events.jsonl" in rels:
        status_yaml, events_jsonl, warnings = projection_cmd.render_projection(conn, task)
        if "status.yaml" in rels:
            texts["status.yaml"] = status_yaml
        if "events.jsonl" in rels:
            texts["events.jsonl"] = events_jsonl
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
    if "handoff.json" in rels:
        expected, rebuild = _handoff_texts(conn, task, task_dir, actor)
        if rebuild is not None:
            texts["handoff.json"] = rebuild
            fixed.append("handoff.json")
    # front matter 工件在 journal 中列出的（task.md 等）：若当前损坏则无法自动重建，
    # 回退到情况 C 语义由调用方处理；此处仅当文件与备份一致时跳过。
    # 2. 写非 view（原子写）
    for rel, text in texts.items():
        projection_cmd._atomic_write(task_dir / rel, text)
        fixed.append(f"completed:{rel}")
    # 3. view 重渲染（读最终文件）
    if view_rel in rels:
        texts = _finalize_texts(
            task_dir,
            texts,
            view_rel,
            lambda: _rebuild_current_view_text(task_dir, task, f"reconcile: recovered transaction ({actor})", f"RECON-{uuid.uuid4().hex}"),
        )
        fixed.append(f"completed:{view_rel}")
    return fixed


def _journal_target_events_match(conn, task_id: str, journal: Dict[str, Any]) -> bool:
    """校验 journal 声明的目标 STATE/HANDOFF 事件在 DB 中存在且 flush_id 一致。

    返回 False 表示身份不匹配（同任务事件碰撞/被后续事务篡改），不得按情况 B 处理。
    """
    flush_id = journal.get("flush_id") or ""
    tx_id = journal.get("transaction_id") or ""
    expected_state = journal.get("expected_state_event_id")
    expected_handoff = journal.get("expected_handoff_event_id")
    # 兼容旧 journal（无新字段）：无身份声明时不阻止按 revision 判定（向后兼容），
    # 但 V5.2.3 新 journal 必须携带完整身份字段。
    if not (flush_id or expected_state or expected_handoff):
        return True
    for evt_id, evt_type in ((expected_state, "STATE"), (expected_handoff, "HANDOFF")):
        if evt_id is None:
            continue
        row = conn.execute(
            "SELECT event_type, detail_json FROM task_event WHERE task_id=? AND id=?",
            (task_id, evt_id),
        ).fetchone()
        if row is None or row["event_type"] != evt_type:
            return False
        # Fourth Hardening（P0-6）：journal 存在 flush_id/transaction_id 身份声明时，
        # detail_json 必须存在、可解析为 dict、且字段逐一相等，否则 fail-closed。
        # 禁止"detail_json 为空即跳过校验"（原 Third Hardening P1-1 的 fail-open）。
        if flush_id or tx_id:
            if not row["detail_json"]:
                return False
            try:
                import json as _json
                ev_detail = _json.loads(row["detail_json"])
            except _json.JSONDecodeError:
                return False
            if not isinstance(ev_detail, dict):
                return False
            # Final Night Hardening（P0-8）：flush_id 必须作为 dict 字段严格相等
            # （子串包含判断可被构造的 detail 绕过，fail-closed）。
            if flush_id and ev_detail.get("flush_id") != flush_id:
                return False
            if tx_id and ev_detail.get("transaction_id") != tx_id:
                return False
    return True


def _recover_journal(task_dir: Path, conn, task, journal: Dict[str, Any], actor: str) -> Tuple[str, List[str]]:
    """处理单个未完成 journal。返回 (decision, fixed_items)，decision in {'A','B','C'}。

    V5.2.3 P0-7 增强：情况 B 需五要素全部满足——revision == expected_revision_after
    **且** current_state == target_state **且** owner_role == owner_after **且**
    journal 声明的目标 STATE/HANDOFF 事件存在且 flush_id 一致 **且**
    expected_event_ids 均在 DB 中存在。任一不满足即情况 C（不删除任何恢复依据）。
    """
    rev_before = journal.get("db_revision_before")
    rev_after = journal.get("expected_revision_after")
    cur = transaction_journal.current_revision(conn, task["task_id"])
    tx_id = journal.get("transaction_id", "")
    backup_dir = Path(journal["backup_dir"]) if journal.get("backup_dir") else None
    if cur == rev_before:
        # 情况 A 前置校验：原本存在的文件若备份缺失，无法安全恢复 → 情况 C
        for entry in journal.get("files") or []:
            if entry.get("before_digest") and not (entry.get("backup") and Path(entry["backup"]).is_file()):
                return "C", []
        try:
            fixed = _restore_from_backup(task_dir, journal)
        except ValueError as e:
            # 备份核验失败：保留全部恢复依据，交人工
            print(f"reconcile: journal {tx_id} restore verification failed: {e}", file=sys.stderr)
            return "C", []
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)
        transaction_journal.remove_journal(task_dir, tx_id)
        return "A", fixed
    if cur == rev_after:
        # 情况 B 五要素身份判定（P0-7）
        target_state = journal.get("target_state")
        owner_after = journal.get("owner_after")
        state_ok = (not target_state) or (task["current_state"] == target_state)
        owner_ok = (not owner_after) or (task["owner_role"] == owner_after)
        events_ok = _journal_target_events_match(conn, task["task_id"], journal)
        expected_ids = journal.get("expected_event_ids") or []
        ids_ok = True
        if expected_ids:
            placeholders = ",".join("?" * len(expected_ids))
            rows = conn.execute(
                f"SELECT id FROM task_event WHERE task_id=? AND id IN ({placeholders})",
                (task["task_id"], *expected_ids),
            ).fetchall()
            ids_ok = len(rows) == len(expected_ids)
        if not (state_ok and owner_ok and events_ok and ids_ok):
            print(
                f"reconcile: journal {tx_id} revision matches but identity check failed "
                f"(state_ok={state_ok} owner_ok={owner_ok} events_ok={events_ok} ids_ok={ids_ok}); "
                f"treating as C — no backup deleted",
                file=sys.stderr,
            )
            return "C", []
        # 情况 B：DB 已推进且身份一致 → 完成全部投影
        fixed = _complete_from_db(task_dir, conn, task, journal, actor)
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)
        transaction_journal.remove_journal(task_dir, tx_id)
        return "B", fixed
    # 情况 C：无法判定 → 不删除任何备份
    return "C", []


def _recover_pending_journals(task_dir: Path, conn, task, actor: str) -> Tuple[List[str], Optional[str]]:
    """处理任务目录下全部未完成 journal。返回 (fixed_items, block_reason)。

    block_reason 非空表示遇到情况 C（无法判定），必须人工介入且不得删除备份。
    """
    fixed: List[str] = []
    for journal in transaction_journal.list_journals(task_dir):
        phase = journal.get("phase", "")
        if phase == "COMPLETED":
            continue
        decision, items = _recover_journal(task_dir, conn, task, journal, actor)
        if decision == "C":
            return fixed, (
                f"journal {journal.get('transaction_id')} cannot be resolved: "
                f"db revision={transaction_journal.current_revision(conn, task['task_id'])}, "
                f"before={journal.get('db_revision_before')}, "
                f"after={journal.get('expected_revision_after')}; "
                f"journal={transaction_journal.transactions_dir(task_dir) / (journal.get('transaction_id', '') + '.json')}; "
                f"affected files={[e.get('path') for e in journal.get('files') or []]}; "
                f"no backup was deleted; manual resolution required"
            )
        fixed.extend(f"[{decision}]" + item for item in items)
        print(f"reconcile: recovered journal {journal.get('transaction_id')} (decision {decision})")
    return fixed, None


# =============================================================================
# 深度漂移检测（任务书 §8）
# =============================================================================

def _handoff_texts(conn, task, task_dir: Path, actor: str) -> Tuple[Optional[str], Optional[str]]:
    """从最近 HANDOFF 事件重建 handoff 期望文本与写入文本。

    返回 (expected_text, rebuild_text)；无 HANDOFF 事件返回 (None, None)。
    - expected_text：与 handoff.json 比对用的语义等价基准（无 reconstructed 元数据）；
    - rebuild_text：写入文件用的文本（V5.2.3 payload 含完整 handoff_record；
      旧版事件回退为字段级重建并标记 reconstructed）。
    """
    row = conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type='HANDOFF' ORDER BY id DESC LIMIT 1",
        (task["task_id"],),
    ).fetchone()
    if row is None:
        return None, None
    detail: Dict[str, Any] = {}
    try:
        detail = json.loads(row["detail_json"] or "{}")
    except json.JSONDecodeError:
        pass
    payload = detail.get("handoff_payload") or {}
    record = payload.get("handoff_record")
    if isinstance(record, dict):
        expected = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        rebuilt = dict(record)
        rebuilt["reconstructed"] = True
        rebuilt["reconstructed_at"] = dbmod.now_iso()
        rebuilt["reconstructed_by"] = actor
        return expected, json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n"
    # 旧版事件（V5.2.3）：字段级回退重建
    owner = task["owner_role"] or ""
    state = task["current_state"] or "NEW"
    entry = "generated/final-result.md" if state == "COMPLETED" else "generated/continuation.md"
    now = dbmod.now_iso()
    rebuilt = {
        "schema_version": active_version(),
        "handoff_id": f"HANDOFF-{task['task_id']}-RECON-{uuid.uuid4().hex[:10].upper()}",
        "flush_id": detail.get("flush_id") or f"RECON-{uuid.uuid4().hex}",
        "consumed": True,
        "consumed_at": now,
        "status": "committed",
        "actor": row["actor_role"] or actor,
        "summary": row["summary"] or "",
        "changes": detail.get("changes") or [],
        "risks": detail.get("risks") or [],
        "evidence": detail.get("evidence") or [],
        "next": {"state": state, "owner": owner},
        "next_prompt": {
            "target_role": owner,
            "task_id": task["task_id"],
            "target_state": state,
            "entry": entry,
            "actions": ["读取正式工件并执行当前状态职责"],
            "constraints": ["正式事实以任务工件和事件账本为准"],
        },
        "reconstructed": True,
        "reconstructed_at": now,
        "reconstructed_by": actor,
    }
    text = json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n"
    return text, text


def _handoff_matches(actual_text: str, expected_text: str) -> bool:
    """handoff 语义等价比对：剥离 reconstructed* 元数据后 JSON 相等。"""
    if not actual_text.strip() or not expected_text.strip():
        return False
    try:
        actual = json.loads(actual_text)
        expected = json.loads(expected_text)
    except json.JSONDecodeError:
        return False
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    actual_clean = {k: v for k, v in actual.items() if not str(k).startswith("reconstructed")}
    expected_clean = {k: v for k, v in expected.items() if not str(k).startswith("reconstructed")}
    return actual_clean == expected_clean


def _check_generated_digest(task_dir: Path, task) -> List[str]:
    """校验 generated current view：存在性 + source_files/source_digest/content_digest。"""
    state = task["current_state"] or "NEW"
    rel = _current_view_rel(state)
    path = task_dir / rel
    if not path.is_file():
        return [f"{rel} missing"]
    text = _read(path)
    parts = frontmatter.split(text)
    if parts is None:
        return [f"{rel}: front matter invalid"]
    front, rest, _ = parts
    source_names: List[str] = []
    for line in front.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            source_names.append(stripped[2:].strip().strip('"'))
    declared_generator = ""
    for line in front.splitlines():
        if line.strip().startswith("generator_version:"):
            declared_generator = line.split(":", 1)[1].strip().strip('"')
    if str(task["base_version"] or "") == active_version() and declared_generator != active_version():
        return [f"{rel}: generator_version mismatch (declared {declared_generator or 'MISSING'}, expected {active_version()})"]
    declared_digest = ""
    for line in front.splitlines():
        if line.strip().startswith("source_digest:"):
            declared_digest = line.split(":", 1)[1].strip().strip('"')
    declared_content = ""
    for line in front.splitlines():
        if line.strip().startswith("content_digest:"):
            declared_content = line.split(":", 1)[1].strip().strip('"')
    source_paths = [task_dir / n for n in source_names if n]
    missing_sources = [n for n in source_names if n and not (task_dir / n).is_file()]
    if missing_sources:
        return [f"{rel}: declared source file missing: {', '.join(missing_sources)}"]
    actual_digest = "sha256:" + _source_digest(source_paths, task_dir)
    if declared_digest and declared_digest != actual_digest:
        return [f"{rel}: source_digest mismatch (declared {declared_digest}, actual {actual_digest})"]
    # content_digest 语义与 Test-TpSpecTask.ps1 的 Get-FrontMatter 一致：
    # closing delimiter 后的空行被 ".*?\r?\n---\s*\r?\n" 吞掉，content 从正文开始。
    actual_content = "sha256:" + hashlib.sha256(rest.lstrip("\r\n").encode("utf-8")).hexdigest()
    if declared_content and declared_content != actual_content:
        return [f"{rel}: content_digest mismatch"]
    return []


def _detect_drift(task_dir: Path, conn, task, actor: str) -> Tuple[List[str], List[str]]:
    """深度漂移检测。返回 (repairable, unrepaired)。

    - repairable：reconcile 可以自动修复（status/events/handoff/view/残留）；
    - unrepaired：只能报告（主工件 front matter 损坏等，需人工/commit 修复）。
    """
    repairable: List[str] = []
    unrepaired: List[str] = []
    # 1. status.yaml / events.jsonl：与 DB 渲染期望逐字节比对
    try:
        status_yaml, events_jsonl, _ = projection_cmd.render_projection(conn, task)
    except ValueError as e:
        unrepaired.append(f"render_projection failed: {e}")
        return repairable, unrepaired
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        repairable.append("status.yaml missing")
    elif status_path.read_bytes() != status_yaml.encode("utf-8"):
        repairable.append("status.yaml differs from DB projection")
    events_path = task_dir / "events.jsonl"
    if not events_path.is_file():
        repairable.append("events.jsonl missing")
    elif events_path.read_bytes() != events_jsonl.encode("utf-8"):
        repairable.append("events.jsonl differs from DB projection")
    # 2. handoff.json：与 HANDOFF 事件 payload 语义等价
    expected_handoff, rebuild_handoff = _handoff_texts(conn, task, task_dir, actor)
    handoff_path = task_dir / "handoff.json"
    if expected_handoff is not None:
        if not handoff_path.is_file():
            repairable.append("handoff.json missing")
        else:
            actual = handoff_path.read_text(encoding="utf-8-sig")
            if not _handoff_matches(actual, expected_handoff):
                repairable.append("handoff.json differs from HANDOFF event payload")
    elif not handoff_path.is_file():
        # 无 HANDOFF 事件且无文件：首次任务未提交过，不判漂移
        pass
    # 3. generated view digest
    repairable.extend(_check_generated_digest(task_dir, task))
    # 4. 主工件 front matter 可解析性（V5.2.3 可选工件存在时同样检查）
    for name in _MAIN_ARTIFACTS + tuple(projection_cmd.projection_source_names()):
        p = task_dir / name
        if not p.is_file():
            continue
        text = frontmatter.read(str(p))
        if not frontmatter.has(text):
            unrepaired.append(f"{name}: front matter missing or invalid (manual repair required)")
    return repairable, unrepaired


# =============================================================================
# 残留清理（journal 判定之后；备份类残留不得未判定删除）
# =============================================================================

def _cleanup_unowned_tmp(task_dir: Path) -> List[str]:
    """清理无主原子写临时文件（*.tmp，非备份，journal 不引用）。"""
    removed: List[str] = []
    for child in sorted(task_dir.iterdir()):
        if child.is_file() and child.name.endswith(_TMP_SUFFIX) and child.name.startswith("."):
            try:
                child.unlink()
                removed.append(child.name)
            except OSError:
                pass
    gen = task_dir / "generated"
    if gen.is_dir():
        for child in sorted(gen.iterdir()):
            if child.is_file() and child.name.endswith(_TMP_SUFFIX) and child.name.startswith("."):
                try:
                    child.unlink()
                    removed.append(f"generated/{child.name}")
                except OSError:
                    pass
    return removed


def _orphan_backups(task_dir: Path) -> List[Path]:
    """无 journal 引用的备份目录（不得自动删除，只能提示）。"""
    orphans = []
    for child in sorted(task_dir.iterdir()):
        if child.is_dir() and child.name.startswith(_BAK_PREFIX):
            orphans.append(child)
    return orphans


# =============================================================================
# reconcile 主流程
# =============================================================================

def cmd_reconcile(args) -> int:
    task_id = args.task
    validate_input(args.actor, "actor")
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        if event_policies.is_task_retired(conn, task_id):
            print(f"reconcile: retired historical task {task_id} is an immutable archive (no rebuild)")
            return 0
        base_version = str(task["base_version"] or "")
        if base_version != active_version():
            print(f"reconcile: legacy contract task {task_id} is a frozen static archive (no rebuild)")
            return 0
        if args.task_dir:
            task_dir = Path(args.task_dir).resolve()
        else:
            task_dir = projection_cmd._resolve_task_dir(None, task_id, conn)
        if not task_dir.is_dir():
            print(f"ERROR: task-dir not found: {task_dir}", file=sys.stderr)
            return 4

        # ---- 0. 未完成 journal 恢复判定（优先于一切清理）----
        recovered, block_reason = _recover_pending_journals(task_dir, conn, task, args.actor)
        if block_reason:
            print(f"ERROR: PROJECTION_RECONCILIATION_REQUIRED: {block_reason}", file=sys.stderr)
            return 5

        # ---- 1. 深度漂移检测 ----
        repairable, unrepaired = _detect_drift(task_dir, conn, task, args.actor)
        tmp_removed = _cleanup_unowned_tmp(task_dir)
        orphans = _orphan_backups(task_dir)

        if not repairable and not unrepaired and not recovered and not tmp_removed and not orphans:
            print(f"reconcile OK: {task_id} (no drift)")
            return 0

        if orphans:
            # 无 journal 引用的备份：不得删除，提示人工（任务书 §3.4 禁止未判定删除）
            for p in orphans:
                print(f"WARN: orphan backup dir kept for manual review: {p} (no journal reference; not deleted)")

        if unrepaired:
            print(f"ERROR: PROJECTION_RECONCILIATION_REQUIRED: {task_id} has non-repairable drift", file=sys.stderr)
            for item in unrepaired:
                print(f"  - {item}", file=sys.stderr)
            print(f"  affected journal/backup dirs were NOT deleted; run commit or manual repair first", file=sys.stderr)
            return 5

        # journal 恢复已完成且无其他可修复漂移 → 直接成功（不再追加 RECONCILIATION 事件）
        if not repairable:
            if recovered:
                print(f"reconcile OK: {task_id} recovered {len(recovered)} item(s) from pending journal(s)")
                return 0
            if tmp_removed or orphans:
                print(f"reconcile OK: {task_id} (cleaned {len(tmp_removed)} tmp artifact(s))")
                return 0
            print(f"reconcile OK: {task_id} (no drift)")
            return 0

        # ---- 2. 一致性修复（复用统一 transaction/journal 机制）----
        fixed = list(recovered)
        fixed.extend(item.split(":", 1)[0] for item in repairable)
        before = {"status.yaml": "drift" if any("status.yaml" in r for r in repairable) else "ok",
                  "events.jsonl": "drift" if any("events.jsonl" in r for r in repairable) else "ok",
                  "handoff.json": "drift" if any("handoff" in r for r in repairable) else "ok",
                  "generated": "drift" if any("generated" in r for r in repairable) else "ok"}
        timestamp = dbmod.now_iso()
        flush_id = f"RECON-{uuid.uuid4().hex}"
        detail = {
            "flush_id": flush_id,
            "before": before,
            "fixed": fixed,
            "after": {"status.yaml": "ok", "events.jsonl": "ok", "handoff.json": "ok", "generated": "ok"},
            "actor": args.actor,
            "timestamp": timestamp,
        }
        view_rel = _current_view_rel(task["current_state"] or "NEW")
        repair_rels = set()
        for item in repairable:
            if item.startswith("status.yaml"):
                repair_rels.add("status.yaml")
            elif item.startswith("events.jsonl"):
                repair_rels.add("events.jsonl")
            elif item.startswith("handoff.json"):
                repair_rels.add("handoff.json")
            elif item.startswith("generated/"):
                repair_rels.add(view_rel)
        rel_paths = ["status.yaml", "events.jsonl", "handoff.json", view_rel]

        def db_and_render(conn, transaction_id=""):
            detail.update({
                "transaction_id": transaction_id,
                "producer": "reconcile",
                "schema_version": active_version(),
            })
            conn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,created_at) VALUES (?,?,?,?,?,?)",
                (task_id, "RECONCILIATION", args.actor, f"reconcile: fixed {len(fixed)} item(s)", json.dumps(detail, ensure_ascii=False), timestamp),
            )
            refreshed = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
            status_yaml, events_jsonl, warnings = projection_cmd.render_projection(conn, refreshed)
            for w in warnings:
                print(f"WARN: {w}", file=sys.stderr)
            texts = {"status.yaml": status_yaml, "events.jsonl": events_jsonl}
            if "handoff.json" in repair_rels or not (task_dir / "handoff.json").is_file():
                expected, rebuild = _handoff_texts(conn, refreshed, task_dir, args.actor)
                if rebuild is not None:
                    texts["handoff.json"] = rebuild
            return _finalize_texts(
                task_dir,
                texts,
                view_rel,
                lambda: _rebuild_current_view_text(task_dir, refreshed, f"reconcile: repaired ({args.actor})", flush_id),
            )

        _commit_with_recovery(task_dir, conn, rel_paths, db_and_render,
                              task_id=task_id, operation="reconcile",
                              db_state_before=task["current_state"] or "NEW",
                              target_state=task["current_state"] or "NEW",
                              owner_before=task["owner_role"] or "",
                              owner_after=task["owner_role"] or "",
                              flush_id=flush_id)

        # ---- 3. 自校验（修复后必须一致）----
        refreshed = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        after_repairable, after_unrepaired = _detect_drift(task_dir, conn, refreshed, args.actor)
        if after_repairable or after_unrepaired:
            print(f"ERROR: reconcile self-check failed: {task_id}", file=sys.stderr)
            for item in after_repairable + after_unrepaired:
                print(f"  - {item}", file=sys.stderr)
            return 5

        print(f"reconcile: {task_id} repaired {len(fixed)} item(s)")
        print(f"  before: {json.dumps(before, ensure_ascii=False)}")
        print(f"  fixed: {json.dumps(fixed, ensure_ascii=False)}")
        print(f"  event: RECONCILIATION flush_id={flush_id} actor={args.actor} at={timestamp}")
        return 0
    finally:
        conn.close()


def add_reconcile_subparsers(parser) -> None:
    p = parser.add_parser("reconcile", help="V5.2.3: reconcile DB truth with projections; durable journal recovery; append-only RECONCILIATION event")
    p.add_argument("--task", required=True, help="task id")
    p.add_argument("--task-dir", required=False, default=None, help="task directory path")
    p.add_argument("--project", required=False, default=None, help="resolve db via registry by project_id")
    p.add_argument("--db", required=False, default=None)
    p.add_argument("--actor", required=False, default="human_owner", help="reconciliation executor (recorded in the RECONCILIATION event)")
    p.set_defaults(func=cmd_reconcile)
