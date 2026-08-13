# -*- coding: utf-8 -*-
"""V5.1.3 A-01/A-02/A-03/A-05/A-06 commit 可靠性测试。

覆盖（任务书 §十 Commit 测试 + 编码测试）：
1. 正常提交（LF / CRLF / BOM 工件）；
2. front matter 错误拒绝（数据库/事件/投影零变化）；
3. YAML 错误拒绝；
4. projection 写失败（原子替换目标被目录占用）→ DB 回滚 + 文件恢复；
5. handoff 写失败 → 同上；
6. DB 写失败（只读数据库）→ 投影零变化；
7. --payload-json 中文输入 + 乱码拒绝；
8. --refresh / --review-only 一致性；
9. 成功提交无备份残留。

纯 stdlib unittest、离线、tempfile 隔离零污染。
强断言：退出码、STDERR 文案、DB 状态终值、事件数、文件 hash、副作用文件存在性。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent.parent  # tp-spec-base
sys.path.insert(0, str(BASE))

from cli import db as dbmod  # noqa: E402
from cli import main as climain  # noqa: E402
from cli.version import active_version  # noqa: E402

TPL = BASE / "templates" / (BASE / "VERSION").read_text(encoding="utf-8").strip()
PROJECT_ID = "p511"


def sha256_file(path) -> str | None:
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def db_state(conn, task_id):
    row = conn.execute("SELECT current_state FROM task WHERE task_id = ?", (task_id,)).fetchone()
    count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id = ?", (task_id,)).fetchone()["c"]
    return (row["current_state"] if row else None), count


def run(argv):
    """执行 CLI，返回 (rc, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def build_task(work, task_id="TASK-20260804-101", eol="\n", bom=False, db_name="t.db", seed=0):
    """构建真实 V5.1.3 任务 fixture（模板 + task create）。返回 (task_dir, db_path)。"""
    proj_root = os.path.join(work, "proj")
    task_dir = os.path.join(proj_root, ".tp-spec", "tasks", task_id)
    os.makedirs(task_dir, exist_ok=True)
    db_path = os.path.join(proj_root, ".tp-spec", "db", db_name)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = dbmod.connect(db_path)
    dbmod.init_schema(conn)
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO project (project_id, project_name, root_path, base_version, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (PROJECT_ID, PROJECT_ID, proj_root, active_version(), dbmod.now_iso(), dbmod.now_iso()),
        )
    conn.close()
    for fn in os.listdir(TPL):
        src = TPL / fn
        if src.is_file():
            (Path(task_dir) / fn).write_bytes(src.read_bytes())
    sp = Path(task_dir) / "status.yaml"
    text = sp.read_text(encoding="utf-8")
    text = text.replace('task_id: "TASK-YYYYMMDD-XXX"', f'task_id: "{task_id}"')
    text = text.replace('created: "YYYY-MM-DD"', 'created: "2026-08-04"')
    sp.write_text(text, encoding="utf-8", newline="\n")
    evidence_dir = Path(task_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "test-result.txt").write_text("verification test passed\n", encoding="utf-8", newline="\n")
    (evidence_dir / "architecture-review-check.txt").write_text("architecture review checklist passed\n", encoding="utf-8", newline="\n")
    if eol == "\r\n" or bom:
        for name in ("status.yaml", "task.md", "acceptance.md", "codex-review.md", "implementation.md", "quality-and-knowledge.md"):
            p = Path(task_dir) / name
            t = p.read_text(encoding="utf-8")
            if eol == "\r\n":
                t = t.replace("\r\n", "\n").replace("\n", "\r\n")
            if bom:
                t = "\ufeff" + t
            p.write_text(t, encoding="utf-8", newline="")
    rc, out, err = run(["task", "create", "--id", task_id, "--project", PROJECT_ID,
                        "--title", "v511", "--risk", "L1", "--flow", "L1", "--db", db_path])
    assert rc == 0, f"task create failed: rc={rc} err={err}"
    return task_dir, db_path


def commit_new_to_developing(task_dir, db_path, task_id, *extra):
    return run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "to dev", *extra])


class TestCommitReliability(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-commit-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _conn(self, db_path):
        return dbmod.connect(db_path)

    # ---- 1. 正常提交 ----
    def test_normal_commit_lf(self):
        task_dir, db_path = build_task(self.work)
        before_status = sha256_file(os.path.join(task_dir, "status.yaml"))
        rc, out, err = commit_new_to_developing(task_dir, db_path, "TASK-20260804-101")
        self.assertEqual(rc, 0, f"commit failed: {err}")
        self.assertIn("commit: NEW -> DEVELOPING", out)
        conn = self._conn(db_path)
        try:
            state, count = db_state(conn, "TASK-20260804-101")
        finally:
            conn.close()
        self.assertEqual(state, "DEVELOPING")
        self.assertGreater(count, 1)  # STATE/HANDOFF 已追加
        # 投影齐全
        self.assertTrue(os.path.isfile(os.path.join(task_dir, "handoff.json")))
        self.assertTrue(os.path.isfile(os.path.join(task_dir, "generated", "continuation.md")))
        self.assertIsNotNone(sha256_file(os.path.join(task_dir, "events.jsonl")))
        # 原子写未破坏 status.yaml（新渲染）
        self.assertNotEqual(before_status, sha256_file(os.path.join(task_dir, "status.yaml")))
        # 无备份残留
        leftovers = [n for n in os.listdir(task_dir) if n.startswith(".v511-bak-")]
        self.assertEqual(leftovers, [])
        # projection validate 通过
        rc2, _, err2 = run(["projection", "validate", "--task", "TASK-20260804-101", "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc2, 0, f"projection validate failed: {err2}")
        # handoff 与 DB 一致
        import json as _json
        handoff = _json.load(open(os.path.join(task_dir, "handoff.json"), encoding="utf-8"))
        self.assertEqual(handoff["next"]["state"], "DEVELOPING")
        self.assertEqual(handoff["next"]["owner"], "tp-development-engineering")

    def test_commit_crlf_artifacts(self):
        task_dir, db_path = build_task(self.work, eol="\r\n")
        rc, _, err = commit_new_to_developing(task_dir, db_path, "TASK-20260804-101")
        self.assertEqual(rc, 0, f"CRLF commit failed: {err}")
        # 注意：必须用 newline="" 读取以保留 \r\n（read_text 默认通用模式会归一化）
        with open(Path(task_dir) / "task.md", "r", encoding="utf-8", newline="") as handle:
            task_md = handle.read()
        self.assertIn("\r\n", task_md, "front matter rewrite must preserve CRLF")
        self.assertIn('status: "ready"', task_md)
        conn = self._conn(db_path)
        try:
            state, _ = db_state(conn, "TASK-20260804-101")
        finally:
            conn.close()
        self.assertEqual(state, "DEVELOPING")

    def test_commit_bom_artifacts(self):
        task_dir, db_path = build_task(self.work, bom=True)
        rc, _, err = commit_new_to_developing(task_dir, db_path, "TASK-20260804-101")
        self.assertEqual(rc, 0, f"BOM commit failed: {err}")
        task_md = (Path(task_dir) / "task.md").read_text(encoding="utf-8")
        self.assertTrue(task_md.startswith("\ufeff"), "BOM must be preserved after front matter rewrite")
        self.assertIn('status: "ready"', task_md)

    # ---- 2. front matter 错误拒绝（零副作用）----
    def test_broken_frontmatter_rejected_no_side_effects(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        # 破坏 task.md front matter
        (Path(task_dir) / "task.md").write_text("no front matter here\n", encoding="utf-8")
        status_before = sha256_file(os.path.join(task_dir, "status.yaml"))
        events_before = sha256_file(os.path.join(task_dir, "events.jsonl"))
        handoff_before = sha256_file(os.path.join(task_dir, "handoff.json"))  # 模板自带
        conn = self._conn(db_path)
        try:
            state_before, count_before = db_state(conn, task_id)
        finally:
            conn.close()
        rc, _, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertNotEqual(rc, 0)
        self.assertIn("missing YAML front matter", err)
        conn = self._conn(db_path)
        try:
            state_after, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        # 数据库不变化、事件不新增、投影不变化、handoff 不被改写
        self.assertEqual(state_after, state_before)
        self.assertEqual(count_after, count_before)
        self.assertEqual(sha256_file(os.path.join(task_dir, "status.yaml")), status_before)
        self.assertEqual(sha256_file(os.path.join(task_dir, "events.jsonl")), events_before)
        self.assertEqual(sha256_file(os.path.join(task_dir, "handoff.json")), handoff_before)

    # ---- 3. YAML 错误拒绝 ----
    def test_invalid_yaml_rejected(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        (Path(task_dir) / "task.md").write_text("---\nstatus: [unclosed\nintended_next: \"x\"\n---\n\nbody\n", encoding="utf-8")
        conn = self._conn(db_path)
        try:
            _, count_before = db_state(conn, task_id)
        finally:
            conn.close()
        rc, _, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertNotEqual(rc, 0)
        self.assertIn("YAML front matter is not parseable", err)
        conn = self._conn(db_path)
        try:
            _, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(count_after, count_before, "events must not be appended on YAML failure")

    # ---- 4. projection 写失败 → DB 回滚 + 文件恢复 ----
    def test_projection_write_failure_rolls_back(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        # generated/continuation.md 位置用目录占用，使 os.replace 失败
        gen = Path(task_dir) / "generated"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "continuation.md").mkdir(parents=True, exist_ok=True)
        status_before = sha256_file(os.path.join(task_dir, "status.yaml"))
        handoff_before = sha256_file(os.path.join(task_dir, "handoff.json"))  # 模板自带
        conn = self._conn(db_path)
        try:
            state_before, count_before = db_state(conn, task_id)
        finally:
            conn.close()
        rc, out, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertNotEqual(rc, 0)
        self.assertIn("PROJECTION_COMMIT_FAILED", err, f"expected baseline-blocked semantics, got: {err}")
        conn = self._conn(db_path)
        try:
            state_after, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        # DB 回滚：状态与事件数不变
        self.assertEqual(state_after, state_before)
        self.assertEqual(count_after, count_before)
        # 文件恢复：status.yaml 未被替换，handoff 未被改写，无备份残留
        self.assertEqual(sha256_file(os.path.join(task_dir, "status.yaml")), status_before)
        self.assertEqual(sha256_file(os.path.join(task_dir, "handoff.json")), handoff_before)
        leftovers = [n for n in os.listdir(task_dir) if n.startswith(".v511-bak-")]
        self.assertEqual(leftovers, [])

    # ---- 5. handoff 写失败 → 回滚 ----
    def test_handoff_write_failure_rolls_back(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        # 移除模板 handoff.json，再用目录占用该位置使 os.replace 失败
        (Path(task_dir) / "handoff.json").unlink()
        Path(task_dir, "handoff.json").mkdir(parents=True, exist_ok=True)
        status_before = sha256_file(os.path.join(task_dir, "status.yaml"))
        conn = self._conn(db_path)
        try:
            state_before, count_before = db_state(conn, task_id)
        finally:
            conn.close()
        rc, _, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertNotEqual(rc, 0)
        self.assertIn("PROJECTION_COMMIT_FAILED", err)
        conn = self._conn(db_path)
        try:
            state_after, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(state_after, state_before)
        self.assertEqual(count_after, count_before)
        self.assertEqual(sha256_file(os.path.join(task_dir, "status.yaml")), status_before)
        leftovers = [n for n in os.listdir(task_dir) if n.startswith(".v511-bak-")]
        self.assertEqual(leftovers, [])

    # ---- 6. DB 写失败（确定性注入：connection wrapper 拦截 COMMIT，禁止依赖文件权限）----
    def test_db_write_failure_no_projection_change(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        status_before = sha256_file(os.path.join(task_dir, "status.yaml"))
        handoff_before = sha256_file(os.path.join(task_dir, "handoff.json"))
        real_connect = dbmod.connect

        class _FailCommitConn:
            """包装真实连接：execute('COMMIT') 注入确定性失败（跨环境一致）。"""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def execute(self, sql, *args, **kwargs):
                if isinstance(sql, str) and sql.strip().upper() == "COMMIT":
                    raise sqlite3.OperationalError("injected commit failure")
                return self._real.execute(sql, *args, **kwargs)

        with mock.patch.object(dbmod, "connect", lambda p: _FailCommitConn(real_connect(p))):
            rc, _, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertNotEqual(rc, 0, "injected DB COMMIT failure must fail the commit")
        self.assertIn("PROJECTION_COMMIT_FAILED", err, f"expected baseline-blocked semantics, got: {err}")
        conn = self._conn(db_path)
        try:
            state_after, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        # DB 回滚：状态与事件数不变（COMMIT 失败后事务已终止）
        self.assertEqual(state_after, "NEW")
        self.assertEqual(count_after, 1, "events must not be appended on DB commit failure")
        # 文件恢复：status.yaml/handoff.json 与提交前一致
        self.assertEqual(sha256_file(os.path.join(task_dir, "status.yaml")), status_before)
        self.assertEqual(sha256_file(os.path.join(task_dir, "handoff.json")), handoff_before)
        # journal 已清除（恢复成功），无备份残留
        leftovers = [n for n in os.listdir(task_dir) if n.startswith(".v511-bak-")]
        self.assertEqual(leftovers, [])
        jdir = Path(task_dir) / ".tp-spec" / "transactions"
        self.assertFalse(any(jdir.glob("*.json")), "journal must be removed after successful recovery")

    # ---- 7. payload-json 中文 + 乱码拒绝 ----
    def test_payload_json_chinese_summary(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        payload = os.path.join(self.work, "payload.json")
        with open(payload, "w", encoding="utf-8", newline="\n") as handle:
            handle.write('{"summary": "中文摘要：架构移交", "changes": ["改了任务文档", "更新验收矩阵"]}')
        rc, _, err = run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--payload-json", payload])
        self.assertEqual(rc, 0, f"payload commit failed: {err}")
        import json as _json
        handoff = _json.load(open(os.path.join(task_dir, "handoff.json"), encoding="utf-8"))
        self.assertEqual(handoff["summary"], "中文摘要：架构移交")
        self.assertEqual(handoff["changes"], ["改了任务文档", "更新验收矩阵"])
        events = (Path(task_dir) / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("中文摘要", events)
        conn = self._conn(db_path)
        try:
            state, _ = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(state, "DEVELOPING")

    def test_mojibake_summary_rejected(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        conn = self._conn(db_path)
        try:
            _, count_before = db_state(conn, task_id)
        finally:
            conn.close()
        rc, _, err = commit_new_to_developing(task_dir, db_path, task_id, "--summary", "bad \ufffd summary")
        self.assertNotEqual(rc, 0)
        self.assertIn("ENCODING_VALIDATION_FAILED", err)
        conn = self._conn(db_path)
        try:
            _, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(count_after, count_before, "events must not be appended on encoding failure")

    def test_payload_invalid_json_rejected(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        payload = os.path.join(self.work, "bad.json")
        with open(payload, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        rc, _, err = run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--payload-json", payload])
        self.assertNotEqual(rc, 0)
        self.assertIn("invalid JSON", err)
        conn = self._conn(db_path)
        try:
            state, _ = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(state, "NEW")

    def test_payload_bad_decision_value_rejected(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        payload = os.path.join(self.work, "payload2.json")
        with open(payload, "w", encoding="utf-8", newline="\n") as handle:
            handle.write('{"summary": "x", "decision": "MAYBE"}')
        rc, _, err = run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--payload-json", payload])
        self.assertNotEqual(rc, 0)
        self.assertIn("must be PASS, FAIL or NEEDS_FIX", err)

    # ---- 8. --refresh / --review-only ----
    def test_refresh_reliable(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        rc, _, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertEqual(rc, 0, err)
        conn = self._conn(db_path)
        try:
            _, count_before = db_state(conn, task_id)
        finally:
            conn.close()
        rc, out, err = run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                            "--actor", "tp-development-engineering", "--refresh", "--summary", "refresh artifacts"])
        self.assertEqual(rc, 0, f"refresh failed: {err}")
        self.assertIn("refresh:", out)
        conn = self._conn(db_path)
        try:
            _, count_after = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(count_after, count_before + 1, "ARTIFACT_REFRESH event expected")
        self.assertTrue(os.path.isfile(os.path.join(task_dir, "generated", "continuation.md")))

    def test_review_only_reliable(self):
        task_dir, db_path = build_task(self.work)
        task_id = "TASK-20260804-101"
        rc, _, err = commit_new_to_developing(task_dir, db_path, task_id)
        self.assertEqual(rc, 0, err)
        rc, _, err = run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                          "--actor", "tp-development-engineering", "--to", "VERIFYING", "--summary", "dev done"])
        self.assertEqual(rc, 0, f"to VERIFYING failed: {err}")
        review_path = Path(task_dir) / "codex-review.md"
        review_path.write_text(
            review_path.read_text(encoding="utf-8") +
            "\n## 结论\n已实际执行技术验证并核对任务目标、实现范围、关键边界、异常路径和回归范围。"
            "实现与当前任务目标一致，关键行为已通过测试。该段仅用于验证 legacy review-only 兼容入口，"
            "V5.1.3 日常角色应使用 task verify。\n\n"
            "## 证据\nevidence/test-result.txt 是本次验证的真实本地测试输出，文件存在且由 Runtime 绑定摘要。"
            "该证据覆盖本测试所声明的技术验证结论，不使用 events/status 等固定投影充当证据。\n\n"
            "## 残余风险\n本兼容性样例未声明额外残余风险；后续若验证 subject 发生变化，原 PASS 应标记 stale，不能继续冒充当前有效 PASS。\n",
            encoding="utf-8", newline="\n",
        )
        rc, out, err = run(["commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                            "--actor", "tp-verification-engineering", "--review-only", "--decision", "PASS",
                            "--summary", "review pass", "--evidence", "evidence/test-result.txt"])
        self.assertEqual(rc, 0, f"review-only failed: {err}")
        self.assertIn("review-only:", out)
        review_md = (Path(task_dir) / "codex-review.md").read_text(encoding="utf-8")
        self.assertIn('decision: "PASS"', review_md)
        conn = self._conn(db_path)
        try:
            state, _ = db_state(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(state, "VERIFYING", "review-only must not change state")


if __name__ == "__main__":
    unittest.main()
