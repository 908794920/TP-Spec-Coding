# -*- coding: utf-8 -*-
"""V5.1.3 定向修复 P0：crash recovery / reconcile consistency / handoff round-trip 测试。

覆盖（任务书 §11.1/§11.2/§11.3）：
- Crash recovery：journal PREPARED/FILES_REPLACED + DB 未变 → 恢复备份；
  DB_COMMITTED + 文件未完成 → 按 DB 完成投影；backup 缺失 → 无法判定不清理；
  digest 不一致 → 重建；重复执行幂等；无法判定保留备份。
- Reconcile consistency：DB event 写失败/文件替换失败 → 回滚无残留；
  成功后 journal 清理；历史事件不修改。
- Handoff：完整字段 round-trip（多 action/constraint、中文）、幂等。

模拟强制终止方式：手工构造 durable journal + 备份 + 篡改文件（等价崩溃残留），
再运行 reconcile 验证恢复判定。纯 stdlib unittest、tempfile 隔离。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))

from cli import db as dbmod  # noqa: E402
from cli import main as climain  # noqa: E402
from cli import transaction_journal  # noqa: E402

from test_v511_commit_reliability import build_task, commit_new_to_developing, run  # noqa: E402

TASK_ID = "TASK-20260804-101"


def reconcile(task_dir, db_path, *extra):
    return run(["reconcile", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path, *extra])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _simulate_crash(task_dir, db_path, phase, rev_before, rev_after,
                    tamper_text=None, drop_backup=False):
    """构造崩溃残留：journal + 备份快照 + 篡改正式文件。返回 (tx_id, bak_dir)。"""
    task_dir = Path(task_dir)
    tx_id = transaction_journal.new_transaction_id()
    bak_dir = task_dir / f".v511-bak-{tx_id}"
    status_path = task_dir / "status.yaml"
    # 崩溃前 digest（无论是否 drop_backup 都记录：drop 表示“备份文件丢失”而非“原本不存在”）
    before_digest = sha256_bytes(status_path.read_bytes()) if status_path.is_file() else None
    bak_status = None
    if status_path.is_file() and not drop_backup:
        bak_dir.mkdir(parents=True, exist_ok=True)
        bak_status = bak_dir / "status.yaml"
        bak_status.write_bytes(status_path.read_bytes())
    if tamper_text is not None:
        status_path.write_text(tamper_text, encoding="utf-8", newline="\n")
    journal = {
        "schema": "ai-work.transaction/v1",
        "transaction_id": tx_id,
        "task_id": TASK_ID,
        "operation": "commit",
        "phase": phase,
        "db_state_before": "NEW",
        "target_state": "DEVELOPING",
        "db_revision_before": rev_before,
        "expected_revision_after": rev_after,
        "backup_dir": str(bak_dir),
        "temp_dir": "",
        "files": [
            {
                "path": "status.yaml",
                "backup": str(bak_status) if bak_status is not None else None,
                "temp": None,
                "before_digest": before_digest,
                "target_digest": sha256_bytes(status_path.read_bytes()) if status_path.is_file() else None,
            },
        ],
        "created_at": "2026-08-04T00:00:00+08:00",
        "updated_at": "2026-08-04T00:00:00+08:00",
    }
    transaction_journal.write_journal(task_dir, journal)
    return tx_id, bak_dir


class TestCrashRecovery(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-crash-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _conn(self, db_path):
        return dbmod.connect(db_path)

    def _prepared(self):
        task_dir, db_path = build_task(self.work)
        rc, _, err = commit_new_to_developing(task_dir, db_path, TASK_ID)
        self.assertEqual(rc, 0, f"prepare commit failed: {err}")
        return task_dir, db_path

    def _revision(self, db_path):
        conn = self._conn(db_path)
        try:
            return transaction_journal.current_revision(conn)
        finally:
            conn.close()

    def _event_count(self, db_path):
        conn = self._conn(db_path)
        try:
            return conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()

    def _journal_exists(self, task_dir, tx_id):
        return transaction_journal.read_journal(Path(task_dir), tx_id) is not None

    def _status_text(self, task_dir):
        return (Path(task_dir) / "status.yaml").read_text(encoding="utf-8")

    # ---- §11.1-1/2：PREPARED / FILES_REPLACED + DB 未变 → 恢复备份 ----
    def test_prepared_db_not_advanced_restores_backup(self):
        for phase in ("PREPARED", "FILES_REPLACED"):
            with self.subTest(phase=phase):
                work = tempfile.mkdtemp(prefix="v511-crash-sub-")
                self.addCleanup(shutil.rmtree, work, ignore_errors=True)
                task_dir, db_path = build_task(work)
                rc, _, err = commit_new_to_developing(task_dir, db_path, TASK_ID)
                self.assertEqual(rc, 0, err)
                rev = self._revision(db_path)
                original = self._status_text(task_dir)
                tx_id, bak_dir = _simulate_crash(
                    task_dir, db_path, phase, rev_before=rev, rev_after=rev,
                    tamper_text='current_state: "COMPLETED"  # tampered\n',
                )
                rc, out, err = reconcile(task_dir, db_path)
                self.assertEqual(rc, 0, f"[{phase}] reconcile failed: {err}")
                # 备份恢复：正式文件回到崩溃前内容
                self.assertEqual(self._status_text(task_dir), original, f"[{phase}] backup not restored")
                # journal 与备份清理
                self.assertFalse(self._journal_exists(task_dir, tx_id), f"[{phase}] journal not removed")
                self.assertFalse(bak_dir.exists(), f"[{phase}] backup dir not removed")
                # DB 无新事件（恢复不追加事件）
                self.assertEqual(self._event_count(db_path), rev)

    # ---- §11.1-3：DB_COMMITTED + 文件未完成 → 按 DB 完成投影 ----
    def test_db_committed_completes_projection(self):
        task_dir, db_path = self._prepared()
        rev = self._revision(db_path)
        tx_id, bak_dir = _simulate_crash(
            task_dir, db_path, "DB_COMMITTED", rev_before=rev - 2, rev_after=rev,
            tamper_text='current_state: "BLOCKED"  # stale tamper\n',
        )
        # 模拟“文件未完成”：删除 events.jsonl
        (Path(task_dir) / "events.jsonl").unlink()
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, f"reconcile failed: {err}")
        # 以 DB 权威重建：status 回到 DB 投影（DEVELOPING）
        self.assertIn('current_state: "DEVELOPING"', self._status_text(task_dir))
        self.assertTrue((Path(task_dir) / "events.jsonl").is_file())
        # journal/备份清理
        self.assertFalse(self._journal_exists(task_dir, tx_id))
        self.assertFalse(bak_dir.exists())
        # events.jsonl 缺失属于 journal 未覆盖的新漂移 → 修复留痕（追加 1 条 RECONCILIATION）
        self.assertEqual(self._event_count(db_path), rev + 1)
        # 修复后自校验一致
        rc2, _, err2 = run(["projection", "validate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc2, 0, err2)

    # ---- §11.1-4：backup 缺失且原本存在 → 无法判定，不得删除 ----
    def test_backup_missing_undecidable(self):
        task_dir, db_path = self._prepared()
        rev = self._revision(db_path)
        tx_id, bak_dir = _simulate_crash(
            task_dir, db_path, "FILES_REPLACED", rev_before=rev, rev_after=rev,
            tamper_text='current_state: "COMPLETED"  # tampered\n', drop_backup=True,
        )
        rc, out, err = reconcile(task_dir, db_path)
        self.assertNotEqual(rc, 0, "undecidable journal must fail")
        self.assertIn("PROJECTION_RECONCILIATION_REQUIRED", err)
        self.assertIn(tx_id, err, "journal path/transaction id must be reported")
        # 篡改文件保留、journal 保留、无备份目录（原本就没有）
        self.assertIn("COMPLETED", self._status_text(task_dir))
        self.assertTrue(self._journal_exists(task_dir, tx_id), "journal must be kept")
        # 第二次仍无法判定（幂等保留）
        rc2, _, _ = reconcile(task_dir, db_path)
        self.assertNotEqual(rc2, 0)

    # ---- §11.1-5：digest 不一致 → 按 DB 重建 ----
    def test_digest_mismatch_completed_from_db(self):
        task_dir, db_path = self._prepared()
        rev = self._revision(db_path)
        tx_id, bak_dir = _simulate_crash(
            task_dir, db_path, "DB_COMMITTED", rev_before=rev - 2, rev_after=rev,
            tamper_text='current_state: "BLOCKED"  # digest mismatch\n',
        )
        rc, _, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        self.assertIn('current_state: "DEVELOPING"', self._status_text(task_dir))
        self.assertFalse(self._journal_exists(task_dir, tx_id))

    # ---- §11.1-6：恢复后重复执行幂等 ----
    def test_reconcile_rerun_after_recovery(self):
        task_dir, db_path = self._prepared()
        rev = self._revision(db_path)
        _simulate_crash(
            task_dir, db_path, "FILES_REPLACED", rev_before=rev, rev_after=rev,
            tamper_text='current_state: "COMPLETED"  # tampered\n',
        )
        rc, _, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        rc2, out2, _ = reconcile(task_dir, db_path)
        self.assertEqual(rc2, 0)
        self.assertNotIn("repaired", out2)
        self.assertNotIn("recovered", out2)

    # ---- §11.1-7：无法判定（revision 区间外）→ 保留备份 ----
    def test_undecidable_keeps_backup(self):
        task_dir, db_path = self._prepared()
        rev = self._revision(db_path)
        tx_id, bak_dir = _simulate_crash(
            task_dir, db_path, "FILES_REPLACED", rev_before=rev - 5, rev_after=rev + 5,
            tamper_text='current_state: "COMPLETED"  # tampered\n',
        )
        rc, _, err = reconcile(task_dir, db_path)
        self.assertNotEqual(rc, 0)
        self.assertIn("PROJECTION_RECONCILIATION_REQUIRED", err)
        # 备份与 journal 均保留
        self.assertTrue(bak_dir.exists(), "backup must be kept when undecidable")
        self.assertTrue(self._journal_exists(task_dir, tx_id))


class TestReconcileConsistency(unittest.TestCase):
    """§11.2：reconcile 自身一致性（复用统一 transaction/journal 机制）。"""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-reccons-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _conn(self, db_path):
        return dbmod.connect(db_path)

    def _prepared(self):
        task_dir, db_path = build_task(self.work)
        rc, _, err = commit_new_to_developing(task_dir, db_path, TASK_ID)
        self.assertEqual(rc, 0, f"prepare commit failed: {err}")
        return task_dir, db_path

    def _tamper_status(self, task_dir):
        p = Path(task_dir) / "status.yaml"
        text = p.read_text(encoding="utf-8")
        text = text.replace('current_state: "DEVELOPING"', 'current_state: "NEW"')
        p.write_text(text, encoding="utf-8", newline="\n")

    # ---- §11.2-1：DB event 写失败 → 回滚，无残留，可重跑 ----
    def test_db_event_failure_rolls_back(self):
        task_dir, db_path = self._prepared()
        self._tamper_status(task_dir)
        real_connect = dbmod.connect

        class _FailInsertConn:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def execute(self, sql, *args, **kwargs):
                if isinstance(sql, str) and "INSERT INTO task_event" in sql and "RECONCILIATION" in str(args):
                    raise sqlite3.OperationalError("injected RECONCILIATION insert failure")
                return self._real.execute(sql, *args, **kwargs)

        with mock.patch.object(dbmod, "connect", lambda p: _FailInsertConn(real_connect(p))):
            rc, _, err = reconcile(task_dir, db_path)
        self.assertNotEqual(rc, 0, "injected DB failure must fail reconcile")
        self.assertIn("PROJECTION_COMMIT_FAILED", err)
        # 无 RECONCILIATION 事件；文件回到修复前（漂移仍在）；journal 已清理
        conn = self._conn(db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event WHERE task_id=? AND event_type='RECONCILIATION'", (TASK_ID,)
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 0)
        self.assertIn('current_state: "NEW"', self._status_text(task_dir), "file must be restored to pre-repair state")
        jdir = Path(task_dir) / ".ai-work" / "transactions"
        self.assertFalse(any(jdir.glob("*.json")))
        # 重跑（无注入）→ 修复成功
        rc2, _, err2 = reconcile(task_dir, db_path)
        self.assertEqual(rc2, 0, f"second reconcile failed: {err2}")
        self.assertIn('current_state: "DEVELOPING"', self._status_text(task_dir))

    def _status_text(self, task_dir):
        return (Path(task_dir) / "status.yaml").read_text(encoding="utf-8")

    # ---- §11.2-2：文件替换失败 → 回滚，无残留，可重跑 ----
    def test_file_replace_failure_rolls_back(self):
        task_dir, db_path = self._prepared()
        self._tamper_status(task_dir)
        gen = Path(task_dir) / "generated"
        gen.mkdir(parents=True, exist_ok=True)
        cont = gen / "continuation.md"
        cont.unlink()  # commit 已生成该文件，先移除再以目录占用
        cont.mkdir(parents=True, exist_ok=True)
        rc, _, err = reconcile(task_dir, db_path)
        self.assertNotEqual(rc, 0)
        self.assertIn("PROJECTION_COMMIT_FAILED", err)
        conn = self._conn(db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event WHERE task_id=? AND event_type='RECONCILIATION'", (TASK_ID,)
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 0, "no RECONCILIATION event on file replace failure")
        self.assertIn('current_state: "NEW"', self._status_text(task_dir))
        # 移除占用目录后重跑 → 修复成功。
        # Final Hardening（strict_restore）：恢复已按 before_digest 将注入目录
        # 恢复为"确实不存在"，故此处容错（目录可能已被严格恢复删除）。
        shutil.rmtree(cont, ignore_errors=True)
        rc2, _, err2 = reconcile(task_dir, db_path)
        self.assertEqual(rc2, 0, f"second reconcile failed: {err2}")
        self.assertIn('current_state: "DEVELOPING"', self._status_text(task_dir))

    # ---- §11.2-5：成功后 journal 清理 ----
    def test_success_cleans_journal_and_backup(self):
        task_dir, db_path = self._prepared()
        self._tamper_status(task_dir)
        rc, _, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        jdir = Path(task_dir) / ".ai-work" / "transactions"
        self.assertFalse(any(jdir.glob("*.json")), "journal must be removed after successful reconcile")
        leftovers = [n for n in os.listdir(task_dir) if n.startswith(".v511-bak-")]
        self.assertEqual(leftovers, [])
        # 自校验通过
        rc2, _, err2 = run(["projection", "validate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc2, 0, err2)


class TestHandoffRoundtrip(unittest.TestCase):
    """§11.3：handoff 无损重建（完整字段 round-trip、中文、幂等）。"""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-handoff-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _prepared_with_rich_handoff(self):
        task_dir, db_path = build_task(self.work)
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING",
                          "--summary", "架构移交：开始开发",
                          "--action", "读取 implementation.md 并实现 W-001",
                          "--action", "实现完成后更新 acceptance.md 的 AC-01 证据",
                          "--constraint", "禁止修改基座与共享规则",
                          "--constraint", "正式事实以任务工件为准",
                          "--evidence", "evidence/ac01.md"])
        self.assertEqual(rc, 0, f"commit failed: {err}")
        return task_dir, db_path

    def test_roundtrip_full_fields(self):
        task_dir, db_path = self._prepared_with_rich_handoff()
        handoff_path = Path(task_dir) / "handoff.json"
        original = json.loads(handoff_path.read_text(encoding="utf-8"))
        handoff_path.unlink()
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, f"reconcile failed: {err}")
        rebuilt = json.loads(handoff_path.read_text(encoding="utf-8"))
        # 完整字段 round-trip：多 action/constraint、中文 summary、evidence、next_prompt
        self.assertEqual(rebuilt["next_prompt"]["actions"],
                         original["next_prompt"]["actions"])
        self.assertEqual(rebuilt["next_prompt"]["actions"], ["读取 implementation.md 并实现 W-001", "实现完成后更新 acceptance.md 的 AC-01 证据"])
        self.assertEqual(rebuilt["next_prompt"]["constraints"], ["禁止修改基座与共享规则", "正式事实以任务工件为准"])
        self.assertEqual(rebuilt["summary"], "架构移交：开始开发")
        self.assertEqual(rebuilt["evidence"], ["evidence/ac01.md"])
        self.assertEqual(rebuilt["next"]["state"], "DEVELOPING")
        self.assertEqual(rebuilt["next"]["owner"], "tp-development-engineering")
        # 语义等价（剥离 reconstructed 元数据后与原 record 完全一致）
        cleaned = {k: v for k, v in rebuilt.items() if not str(k).startswith("reconstructed")}
        original_clean = {k: v for k, v in original.items() if not str(k).startswith("reconstructed")}
        self.assertEqual(cleaned, original_clean)
        self.assertTrue(rebuilt.get("reconstructed"))

    def test_reconcile_idempotent_after_rebuild(self):
        task_dir, db_path = self._prepared_with_rich_handoff()
        (Path(task_dir) / "handoff.json").unlink()
        rc, _, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        rc2, out2, _ = reconcile(task_dir, db_path)
        self.assertEqual(rc2, 0)
        self.assertNotIn("repaired", out2, "rebuilt handoff must be stable across reconciles")

    def test_no_handoff_event_handoff_file_ignored(self):
        """无 HANDOFF 事件（任务未提交过）时模板 handoff.json 不判漂移。"""
        task_dir, db_path = build_task(self.work)
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        # 模板 status.yaml 与 DB 投影不一致会触发一次修复（正常）；修复后与 DB 一致
        self.assertIn('current_state: "NEW"', (Path(task_dir) / "status.yaml").read_text(encoding="utf-8"))
        # 无 HANDOFF 事件时不追加 RECONCILIATION 之外的错误
        self.assertNotIn("handoff.json differs", out)


if __name__ == "__main__":
    unittest.main()
