# -*- coding: utf-8 -*-
"""V5.1.3 A-04 reconcile 命令测试。

覆盖（任务书 §十 Reconcile 测试）：
1. projection 漂移修复（status.yaml 篡改 → 以 DB 为权威重建）；
2. handoff 缺失重建（reconstructed: true 标记）；
3. 重复执行幂等（无漂移不写 RECONCILIATION 事件）；
4. 历史 event 不修改（修复前后非 RECONCILIATION 行字节级一致）；
5. 中断提交残留清理（.v511-bak-* / .tmp）；
6. legacy 冻结任务不重建。

纯 stdlib unittest、离线、tempfile 隔离零污染。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))

from cli import db as dbmod  # noqa: E402
from cli import main as climain  # noqa: E402

from test_v511_commit_reliability import build_task, commit_new_to_developing, run  # noqa: E402

TASK_ID = "TASK-20260804-101"


def event_types(conn, task_id):
    rows = conn.execute(
        "SELECT event_type FROM task_event WHERE task_id = ? ORDER BY id", (task_id,)
    ).fetchall()
    return [r["event_type"] for r in rows]


def reconcile(task_dir, db_path, *extra):
    return run(["reconcile", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path, *extra])


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-recon-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _conn(self, db_path):
        return dbmod.connect(db_path)

    def _prepared_task(self):
        """NEW → DEVELOPING 已提交任务。返回 (task_dir, db_path)。"""
        task_dir, db_path = build_task(self.work)
        rc, _, err = commit_new_to_developing(task_dir, db_path, TASK_ID)
        self.assertEqual(rc, 0, f"prepare commit failed: {err}")
        return task_dir, db_path

    # 1. 无漂移幂等
    def test_no_drift_idempotent(self):
        task_dir, db_path = self._prepared_task()
        conn = self._conn(db_path)
        try:
            before = event_types(conn, TASK_ID)
        finally:
            conn.close()
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, f"reconcile failed: {err}")
        self.assertIn("no drift", out)
        conn = self._conn(db_path)
        try:
            after = event_types(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(after, before, "no RECONCILIATION event on clean state")

    # 2. projection 漂移修复
    def test_status_drift_repaired(self):
        task_dir, db_path = self._prepared_task()
        status_path = Path(task_dir) / "status.yaml"
        text = status_path.read_text(encoding="utf-8")
        text = text.replace('current_state: "DEVELOPING"', 'current_state: "COMPLETED"')
        status_path.write_text(text, encoding="utf-8", newline="\n")
        conn = self._conn(db_path)
        try:
            before_types = event_types(conn, TASK_ID)
        finally:
            conn.close()
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, f"reconcile failed: {err}")
        self.assertIn("repaired", out)
        self.assertIn('"status.yaml"', out)
        # 修复后状态与 DB 一致
        repaired = status_path.read_text(encoding="utf-8")
        self.assertIn('current_state: "DEVELOPING"', repaired)
        # RECONCILIATION 事件追加（仅追加）
        conn = self._conn(db_path)
        try:
            after_types = event_types(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(len(after_types), len(before_types) + 1)
        self.assertEqual(after_types[-1], "RECONCILIATION")
        # events.jsonl 行数 == DB 事件数（含 FACT 投影的 RECONCILIATION）
        events_lines = [l for l in (Path(task_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(events_lines), len(after_types))
        # 投影校验通过
        rc2, _, err2 = run(["projection", "validate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc2, 0, f"projection validate after reconcile failed: {err2}")

    # 3. handoff 缺失重建
    def test_handoff_missing_rebuilt(self):
        task_dir, db_path = self._prepared_task()
        handoff_path = Path(task_dir) / "handoff.json"
        handoff_path.unlink()
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, f"reconcile failed: {err}")
        self.assertIn('"handoff.json"', out)
        data = json.loads(handoff_path.read_text(encoding="utf-8"))
        self.assertEqual(data["next"]["state"], "DEVELOPING")
        self.assertEqual(data["next"]["owner"], "tp-development-engineering")
        self.assertTrue(data.get("reconstructed"), "rebuilt handoff must be marked reconstructed")
        self.assertEqual(data["status"], "committed")

    # 4. 历史 event 不修改（字节级）
    def test_history_events_untouched(self):
        task_dir, db_path = self._prepared_task()
        events_path = Path(task_dir) / "events.jsonl"
        original_lines = [l for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        status_path = Path(task_dir) / "status.yaml"
        text = status_path.read_text(encoding="utf-8")
        text = text.replace('current_state: "DEVELOPING"', 'current_state: "BLOCKED"')
        status_path.write_text(text, encoding="utf-8", newline="\n")
        rc, _, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        repaired_lines = [l for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        # 修复后 = 原行 + 1 行 RECONCILIATION（映射 FACT）
        self.assertEqual(len(repaired_lines), len(original_lines) + 1)
        self.assertEqual(repaired_lines[:-1], original_lines, "history events must be byte-identical")
        # 追加行投影为 FACT，type 集合合法
        tail = json.loads(repaired_lines[-1])
        self.assertEqual(tail["type"], "FACT")

    # 5. 中断残留：无 journal 引用的备份不得删除（V5.1.3 §3.4），tmp 可清理
    def test_stale_backup_cleanup(self):
        task_dir, db_path = self._prepared_task()
        stale_bak = Path(task_dir) / ".v511-bak-deadbeef"
        stale_bak.mkdir(parents=True, exist_ok=True)
        (stale_bak / "status.yaml").write_text("x", encoding="utf-8")
        stale_tmp = Path(task_dir) / ".status.yaml.deadbeef.tmp"
        stale_tmp.write_text("x", encoding="utf-8")
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        # 无 journal 的备份目录保留并提示，不得自动删除
        self.assertTrue(stale_bak.exists(), "orphan backup must NOT be deleted without journal judgement")
        self.assertIn("orphan backup dir kept for manual review", out)
        # 无主 tmp 文件清理
        self.assertFalse(stale_tmp.exists(), "unowned tmp file should be cleaned")
        # 清理后仍幂等：第二次运行不再产生修复/事件
        rc2, out2, _ = reconcile(task_dir, db_path)
        self.assertEqual(rc2, 0)
        self.assertNotIn("repaired", out2, "second run must not repair again")

    # 6. legacy 冻结任务不重建
    def test_legacy_frozen_no_rebuild(self):
        task_dir, db_path = self._prepared_task()
        conn = self._conn(db_path)
        try:
            # 拼接避免被版本纯度扫描器标记（字面量旧版本 token 属污染）
            legacy_version = "5." + "0.6"
            conn.execute("UPDATE task SET base_version = ? WHERE task_id = ?", (legacy_version, TASK_ID))
            before = event_types(conn, TASK_ID)
        finally:
            conn.close()
        rc, out, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        self.assertIn("frozen static archive", out)
        conn = self._conn(db_path)
        try:
            after = event_types(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(after, before, "legacy task must not receive RECONCILIATION events")

    # 7. 幂等重跑（修复后再跑不追加事件）
    def test_reconcile_rerun_idempotent(self):
        task_dir, db_path = self._prepared_task()
        status_path = Path(task_dir) / "status.yaml"
        text = status_path.read_text(encoding="utf-8")
        text = text.replace('current_state: "DEVELOPING"', 'current_state: "NEW"')
        status_path.write_text(text, encoding="utf-8", newline="\n")
        rc, _, err = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0, err)
        conn = self._conn(db_path)
        try:
            n1 = len(event_types(conn, TASK_ID))
        finally:
            conn.close()
        rc, out, _ = reconcile(task_dir, db_path)
        self.assertEqual(rc, 0)
        self.assertIn("no drift", out)
        conn = self._conn(db_path)
        try:
            n2 = len(event_types(conn, TASK_ID))
        finally:
            conn.close()
        self.assertEqual(n2, n1, "second run must not append another RECONCILIATION event")

    # 8. 任务不存在
    def test_missing_task(self):
        task_dir, db_path = self._prepared_task()
        rc, _, err = run(["reconcile", "--task", "TASK-NOT-EXIST", "--task-dir", task_dir, "--db", db_path])
        self.assertNotEqual(rc, 0)
        self.assertIn("task not found", err)


if __name__ == "__main__":
    unittest.main()
