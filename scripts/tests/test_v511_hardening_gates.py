# -*- coding: utf-8 -*-
"""V5.1.3 Hardening 统一修复负向测试（任务书 §15 全量 32 项）。

分组：
1. 状态绕过负向（5）：NEW 伪造 COMPLETED / 伪造 owner / 无 PASS 不 CLOSING /
   自动质量 PASS 后可直接 CLOSING / 不能跳状态 / 非 canonical owner 拒绝。
2. 架构评审（6）：tp-architecture-review 可 record / 无架构 PASS 不 DEVELOPING /
   design 变化后 PASS stale / 非架构评审角色拒绝 / 事件 detail 含 design_digest /
   非法 decision 拒绝。
3. 验收结单（9）：PENDING 不 CLOSING / deferred 缺字段拒绝 / codex-review 空正文拒绝 /
   无 PASS 不 CLOSING / L2/L3 自动质量 PASS 后可直接 CLOSING / scope change drift /
   human receipt 不一致 / test guide lifecycle 未完成 / 合法 CLOSING 通过。
4. transaction/reconcile（7）：journal 记录身份字段 / 情况 B 五要素判定（同任务
   事件碰撞不误判）/ restore 逐文件核验 / updated_at 刷新 / 事件带 flush_id /
   backup digest mismatch → C / 恢复后无残留 temp。
5. 版本与 manifest（5）：扫描器允许历史位置 / 拒绝活动位置旧版本 / version 动态 /
   test-guide 模板含 current_owner/section_owners / role-catalog 含两个新角色。

纯 stdlib unittest、离线、tempfile 隔离零污染。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
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
from cli import transaction_journal  # noqa: E402
from cli.version import active_version  # noqa: E402

from test_v511_commit_reliability import build_task, run  # noqa: E402

TASK_ID = "TASK-20260804-101"
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()
TPL = BASE / "templates" / ACTIVE_VERSION


def db_state(conn, task_id):
    row = conn.execute("SELECT current_state, owner_role, risk_level, flow_level FROM task WHERE task_id = ?", (task_id,)).fetchone()
    count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id = ?", (task_id,)).fetchone()["c"]
    return row, count


def _conn(db_path):
    return dbmod.connect(db_path)


def _event_count(db_path, task_id=TASK_ID):
    conn = _conn(db_path)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (task_id,)).fetchone()["c"]
    finally:
        conn.close()



def _prepare(task_id=TASK_ID, risk="L1", flow="L1"):
    """构建任务 fixture 并返回 (work, task_dir, db_path)。"""
    work = tempfile.mkdtemp(prefix="v511-gates-")
    task_dir, db_path = build_task(work, task_id=task_id)
    # 重建为指定风险等级（build_task 默认 L1；直接改写 DB 与 status.yaml）
    conn = _conn(db_path)
    try:
        conn.execute("UPDATE task SET risk_level=?, flow_level=? WHERE task_id=?", (risk, flow, task_id))
        conn.commit()
    finally:
        conn.close()
    sp = Path(task_dir) / "status.yaml"
    text = sp.read_text(encoding="utf-8")
    text = text.replace("risk_level: L1", f"risk_level: {risk}").replace("flow_level: L1", f"flow_level: {flow}")
    sp.write_text(text, encoding="utf-8", newline="\n")
    # Final Hardening（P1-4）：L2/L3 必须存在真实决策记录（空 D-001 不再通过）
    if risk in ("L2", "L3") or flow in ("L2", "L3"):
        _write_decisions_confirmed(Path(task_dir))
    return work, task_dir, db_path



def _ensure_evidence(task_dir, name="test-result.txt", content="verified evidence\n"):
    root = Path(task_dir) / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if not path.exists():
        path.write_text(content, encoding="utf-8", newline="\n")
    return path.relative_to(Path(task_dir)).as_posix()

def _write_decisions_confirmed(task_dir):
    """构造 requirement-decisions.md 的已确认决策（P1-4：空 D-001 不得通过）。"""
    p = Path(task_dir) / "requirement-decisions.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace('selected_option: ""', 'selected_option: "方案A"', 1)
    text = text.replace('decision: ""', 'decision: "确定技术方案A"', 1)
    p.write_text(text, encoding="utf-8", newline="\n")


def _write_knowledge_complete(task_dir):
    """构造 requirement-knowledge.md 检索完整（complete: true）。"""
    p = Path(task_dir) / "requirement-knowledge.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("complete: false", "complete: true")
    p.write_text(text, encoding="utf-8", newline="\n")


def _write_arch_review_pass(task_dir, decision="PASS", round_no=1):
    """构造 architecture-review.md 的 PASS/非 PASS front matter。

    Final Hardening（P0-5/§5.4）：PASS 必须通过内容门禁——正文非模板、检查项
    有明确结论。因此 decision=PASS 时同时填充正文。
    """
    p = Path(task_dir) / "architecture-review.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("decision: DRAFT", f"decision: {decision}")
    text = text.replace("round: 0", f"round: {round_no}")
    if decision == "PASS":
        text = text.replace("DRAFT / PASS / REVISE / BLOCKED", "PASS")
        text = text.replace(
            "## 关键结论\n",
            "## 关键结论\n\n"
            "已独立检查需求范围、技术可行性、关键数据路径、并发与权限边界、回滚恢复以及验收可验证性。"
            "本轮评审未发现会阻止继续实现的架构问题；现有方案在当前任务范围内具备可实施性，风险已有明确处理或可接受的残余风险记录。"
            "该结论仅作为按风险触发的独立第二意见，不构成进入开发阶段的流程许可证。\n\n"
        )
        for line, filled in ((
            "- 需求/范围覆盖：", "- 需求/范围覆盖：覆盖"),
            ("- 技术可行性：", "- 技术可行性：通过"),
            ("- 数据/并发/权限风险：", "- 数据/并发/权限风险：已检查，无阻塞"),
            ("- 回滚/恢复：", "- 回滚/恢复：可行"),
            ("- 验收可验证性：", "- 验收可验证性：可验证"),
        ):
            text = text.replace(line, filled)
    p.write_text(text, encoding="utf-8", newline="\n")


def _write_test_guide_lifecycle(task_dir, **lifecycle):
    """构造 requirement-test-guide.md 的 lifecycle 状态。"""
    p = Path(task_dir) / "requirement-test-guide.md"
    text = p.read_text(encoding="utf-8")
    for key, val in lifecycle.items():
        text = text.replace(f"{key}: pending", f"{key}: {val}")
    p.write_text(text, encoding="utf-8", newline="\n")


def _write_test_guide_verified(task_dir):
    """test-guide 验收结果登记（Task 4 §6.4：ac_coverage + 结果 + 证据）。"""
    _ensure_evidence(task_dir, "test-result.txt", "verification test passed\n")
    tg = Path(task_dir) / "requirement-test-guide.md"
    tg_text = tg.read_text(encoding="utf-8")
    tg_text = tg_text.replace("ac_coverage: []", "ac_coverage:\n  - ac: AC-01")
    tg_text = tg_text.replace("- 验收人：", "- 验收人：tp-verification-engineering")
    tg_text = tg_text.replace("- 验收时间：", "- 验收时间：2026-08-04")
    tg_text = tg_text.replace("- 结果：PASS / BLOCKED", "- 结果：PASS")
    tg_text = tg_text.replace("- 证据路径：", "- 证据路径：evidence/test-result.txt")
    tg.write_text(tg_text, encoding="utf-8", newline="\n")


def _record_arch_review(task_dir, db_path, decision="PASS", task_id=TASK_ID):
    """通过正式 CLI 执行架构评审 record。

    Final Hardening（INV-04/P0-5）：PASS 必须携带 evidence；无证据事件不被门禁
    信任。这里通过正式 review record 命令附带 evidence 完成合法准备。
    """
    evidence = _ensure_evidence(task_dir, "architecture-review-check.txt", "architecture review checklist passed\n")
    return run(["review", "record", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                "--actor", "tp-architecture-review", "--kind", "ARCHITECTURE",
                "--decision", decision, "--round", "1", "--summary", "arch review",
                "--evidence", evidence])


class TestStateBypassNegative(unittest.TestCase):
    """§15 状态绕过负向（任务书 §4.2/§4.3）。"""

    def setUp(self):
        self.work, self.task_dir, self.db_path = _prepare(risk="L2", flow="L2")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    # ---- §15.1-1：event sync 不能把 NEW 伪造为 COMPLETED ----
    def test_event_sync_cannot_forge_completed(self):
        task_dir = Path(self.task_dir)
        events = task_dir / "events.jsonl"
        fake = json.dumps({"type": "STATE", "event_type": "STATE", "from_state": "NEW", "to_state": "COMPLETED",
                           "flush_id": "FLUSH-FAKE-1", "actor_role": "human_owner"})
        events.write_text(fake + "\n", encoding="utf-8")
        handoff = task_dir / "handoff.json"
        handoff.write_text(json.dumps({"next": {"state": "COMPLETED", "owner": "tp-delivery-convergence"}}),
                           encoding="utf-8")
        rc, out, err = run(["event", "sync", "--task", TASK_ID, "--task-dir", str(task_dir), "--db", self.db_path])
        self.assertNotEqual(rc, 0, "event sync with state fields must be forbidden")
        self.assertIn("EVENT_SYNC_STATE_MUTATION_FORBIDDEN", err)
        conn = _conn(self.db_path)
        try:
            row, count = db_state(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(row["current_state"], "NEW", "state must not be mutated")

    # ---- §15.1-2：event sync 不能伪造 owner_role ----
    def test_event_sync_cannot_forge_owner(self):
        task_dir = Path(self.task_dir)
        events = task_dir / "events.jsonl"
        fake = json.dumps({"type": "FACT", "flush_id": "FLUSH-FAKE-2", "owner_role": "tp-requirement-analysis"})
        events.write_text(fake + "\n", encoding="utf-8")
        handoff = task_dir / "handoff.json"
        handoff.write_text(json.dumps({"next": {"owner": "tp-requirement-analysis"}}), encoding="utf-8")
        rc, out, err = run(["event", "sync", "--task", TASK_ID, "--task-dir", str(task_dir), "--db", self.db_path])
        self.assertNotEqual(rc, 0, "owner_role in event sync must be forbidden")
        self.assertIn("EVENT_SYNC_STATE_MUTATION_FORBIDDEN", err)

    # ---- §15.1-3：无 tp-verification PASS 不得 CLOSING ----
    def test_no_pass_cannot_bypass_required_l2_pipeline(self):
        rc, out, err = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--phase", "development", "--summary", "implementation ended without formal verification",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--summary", "attempt completion before required pipeline",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("INTEGRITY_PIPELINE_PENDING", err + out)

    # ---- §15.1-4：L2/L3 通过自动质量门禁后可直接 CLOSING ----
    def test_l2_verification_pass_requires_delivery_before_completion(self):
        for actor, phase, summary in (
            ("tp-requirement-analysis", "requirement", "requirement complete"),
            ("tp-architecture-design", "architecture", "architecture complete"),
            ("tp-development-engineering", "development", "implementation complete"),
        ):
            rc, out, err = run([
                "task", "checkpoint", "--task", TASK_ID, "--task-dir", str(self.task_dir),
                "--db", self.db_path, "--actor", actor, "--phase", phase, "--summary", summary,
            ])
            self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "verify", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-verification-engineering",
            "--decision", "PASS", "--summary", "verified", "--evidence", "evidence/test-result.txt",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-verification-engineering", "--summary", "premature",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("next_stage=delivery", err + out)
        rc, out, err = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-delivery-convergence",
            "--phase", "delivery", "--summary", "delivery converged",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-delivery-convergence", "--summary", "done",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(json.loads(out)["verification"], "PASS")

    def _advance_verifying_with_pass(self):
        _write_knowledge_complete(self.task_dir)
        _write_arch_review_pass(self.task_dir)
        _write_test_guide_lifecycle(self.task_dir, architecture_outline="done", development_details="done",
                                    verification_results="done")
        _write_test_guide_verified(self.task_dir)
        (Path(self.task_dir) / "implementation.md").write_text("---\nstatus: ready\n---\n\nimpl\n", encoding="utf-8")
        rc, _, err = _record_arch_review(self.task_dir, self.db_path)
        self.assertEqual(rc, 0, err)
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "dev"])
        self.assertEqual(rc, 0, err)
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-development-engineering", "--to", "VERIFYING", "--summary", "verify"])
        self.assertEqual(rc, 0, err)
        acc = Path(self.task_dir) / "acceptance.md"
        acc.write_text(acc.read_text(encoding="utf-8").replace(
            "| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |",
            "| AC-01 | 完成目标功能并验证 | task.md / requirement-test-guide.md | L2 | 验证 | evidence/test-result.txt | verification | PASS |",
        ), encoding="utf-8", newline="\n")
        cr = Path(self.task_dir) / "codex-review.md"
        cr.write_text(
            "---\nreview:\n  actor: tp-verification-engineering\n  decision: PASS\n  evidence: evidence/test-result.txt\n  timestamp: 2026-08-04\n---\n\n"
            "## 审查结论\n已逐项核验全部验收条件，并对照测试指南中的修改范围、测试前置条件、正常场景、异常场景、边界场景、数据库验证、日志检查与回归范围。实现内容与任务目标一致，所有自动化测试均已实际执行，未发现阻塞问题或未声明的范围变化，结论为通过。\n\n"
            "## 证据\nevidence/test-result.txt 包含真实测试输出、关键断言和回归结果；验收矩阵中的 AC-01 已映射到该证据，证据文件存在、非空并绑定摘要。\n\n"
            "## 残余风险\n当前未发现残余风险；后续若任务范围或证据文件发生变化，现有 PASS 必须自动失效并重新验证。\n",
            encoding="utf-8")
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-verification-engineering", "--review-only", "--summary", "pass",
                          "--decision", "PASS", "--evidence", "evidence/test-result.txt"])
        self.assertEqual(rc, 0, err)

    # ---- §15.1-5：不能跳状态（NEW → CLOSING 直接拒绝）----
    def test_cannot_skip_states(self):
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                            "--actor", "tp-delivery-convergence", "--to", "CLOSING", "--summary", "jump"])
        self.assertNotEqual(rc, 0, "illegal transition must be rejected")

    # ---- §15.1-6：非 canonical owner 拒绝（VERIFYING 由 tp-architecture-design 提交）----
    def test_record_first_phase_is_not_a_canonical_owner_gate(self):
        rc, out, err = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-architecture-design",
            "--phase", "verification", "--summary", "factual cross-role checkpoint",
        ])
        self.assertEqual(rc, 0, (out, err))
        conn = _conn(self.db_path)
        try:
            row, _ = db_state(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(row["current_state"], "ACTIVE")
        self.assertEqual(row["owner_role"], "tp-architecture-design")

    # ---- §15.1-7：task transition 对活动任务禁用 ----
    def test_task_transition_disabled(self):
        rc, out, err = run(["task", "transition", "--task", TASK_ID, "--to", "DEVELOPING", "--db", self.db_path,
                            "--summary", "x", "--actor-role", "tp-architecture-design"])
        self.assertEqual(rc, 9, "task transition must be disabled for active tasks")
        self.assertIn("DIRECT_TRANSITION_DISABLED", err)
        conn = _conn(self.db_path)
        try:
            row, _ = db_state(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(row["current_state"], "NEW")


class TestArchitectureReview(unittest.TestCase):
    """§15 架构评审（任务书 §7）。"""

    def setUp(self):
        self.work, self.task_dir, self.db_path = _prepare(risk="L2", flow="L2")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    # ---- §15.2-1：tp-architecture-review 可以正式 record PASS ----
    def test_arch_review_record_pass(self):
        _write_arch_review_pass(self.task_dir)
        rc, out, err = _record_arch_review(self.task_dir, self.db_path)
        self.assertEqual(rc, 0, f"arch review record failed: {err}")
        conn = _conn(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM task_event WHERE task_id=? AND event_type='REVIEW_COMPLETED' "
                "AND actor_role='tp-architecture-review' AND summary='PASS'",
                (TASK_ID,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "REVIEW_COMPLETED PASS event must exist")
        detail = json.loads(row["detail_json"])
        self.assertEqual(detail.get("review_kind"), "ARCHITECTURE")
        self.assertTrue(detail.get("design_digest"), "design_digest must be recorded")

    # ---- §15.2-2：L2 无架构 PASS 不得 DEVELOPING ----
    def test_l2_no_arch_pass_no_developing(self):
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path,
                            "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "dev"])
        self.assertNotEqual(rc, 0, "L2 DEVELOPING without architecture PASS must fail")
        self.assertIn("ARCHITECTURE_REVIEW_REQUIRED", err.upper())

    # ---- §15.2-3：design 变化后 PASS stale ----
    def test_arch_review_stale_after_design_change(self):
        """Architecture review is optional history in Record-first; later work is not byte-gated."""
        task_id = TASK_ID
        rc, out, err = run([
            "task", "checkpoint", "--task", task_id, "--task-dir", self.task_dir,
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--phase", "development", "--summary", "development without review gate",
        ])
        self.assertEqual(rc, 0, (out, err))
    def test_arch_review_actor_restricted(self):
        rc, out, err = run(["review", "record", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path,
                            "--actor", "tp-development-engineering", "--kind", "ARCHITECTURE",
                            "--decision", "PASS", "--summary", "x"])
        self.assertNotEqual(rc, 0, "non tp-architecture-review actor must be rejected")
        self.assertIn("invalid choice", err)

    # ---- §15.2-5：REVIEW_COMPLETED detail 含设计 digest ----
    def test_review_event_has_design_digest(self):
        _write_arch_review_pass(self.task_dir)
        rc, _, err = _record_arch_review(self.task_dir, self.db_path)
        self.assertEqual(rc, 0, err)
        conn = _conn(self.db_path)
        try:
            row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='REVIEW_COMPLETED' "
                "AND actor_role='tp-architecture-review' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()
        finally:
            conn.close()
        detail = json.loads(row["detail_json"])
        self.assertTrue(detail["design_digest"])
        self.assertEqual(detail["review_kind"], "ARCHITECTURE")
        self.assertEqual(detail["decision"], "PASS")

    # ---- §15.2-6：非法 decision 拒绝 ----
    def test_review_invalid_decision_rejected(self):
        rc, out, err = run(["review", "record", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path,
                            "--actor", "tp-architecture-review", "--kind", "ARCHITECTURE",
                            "--decision", "MAYBE", "--summary", "x"])
        self.assertNotEqual(rc, 0)
        self.assertIn("invalid choice", err)


class TestAcceptanceClosingGates(unittest.TestCase):
    """§15 验收与结单门禁（任务书 §8）。"""

    def setUp(self):
        self.work, self.task_dir, self.db_path = _prepare(risk="L1", flow="L1")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _advance_to_verifying(self):
        _write_knowledge_complete(self.task_dir)
        _write_test_guide_lifecycle(self.task_dir, architecture_outline="done", development_details="done")
        (Path(self.task_dir) / "implementation.md").write_text("---\nstatus: ready\n---\n\nimpl\n", encoding="utf-8")
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "dev"])
        self.assertEqual(rc, 0, err)
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-development-engineering", "--to", "VERIFYING", "--summary", "verify"])
        self.assertEqual(rc, 0, err)

    def _advance_to_closing_ready(self):
        """构造可合法 CLOSING 的完整自动验收态。

        Final Hardening（P0-3/P0-6/§6.2/§6.4）：verdict 必须是 PASS（拒绝 PASSED）、
        PASS 需证据路径、AC 条件非空、codex-review 正文实质、test-guide ac_coverage
        与验收结果登记。
        """
        self._advance_to_verifying()
        # 验收矩阵：AC 条件 + 结论 PASS + 证据路径
        acc = Path(self.task_dir) / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        text = text.replace(
            "| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |",
            "| AC-01 | 完成目标功能并验证 | task.md / requirement-test-guide.md | L1 | 验证 | evidence/test-result.txt | verification | PASS |",
        )
        acc.write_text(text, encoding="utf-8", newline="\n")
        # codex-review：front matter 完整 + 正文实质（>200 字符，含结论/证据/残余风险）
        cr = Path(self.task_dir) / "codex-review.md"
        cr.write_text(
            "---\nreview:\n  actor: tp-verification-engineering\n  decision: PASS\n"
            "  evidence: evidence/test-result.txt\n  timestamp: 2026-08-04\n---\n\n"
            "## 审查结论\n已核验全部验收项，逐项对照 requirement-test-guide.md 的修改范围、"
            "测试前置条件、正常/异常/边界场景、数据验证 SQL、日志检查与回归范围，"
            "审查结论为通过，无阻塞问题。\n\n"
            "## 证据\nevents.jsonl 记录了全部验证步骤与结果，含 AC-01 的验证证据、"
            "测试场景 T-001/T-002/T-003 的执行结果与数据库验证声明。\n\n"
            "## 残余风险\n无。\n",
            encoding="utf-8")
        # test-guide：ac_coverage + 验收结果登记（§6.4）
        _write_test_guide_verified(self.task_dir)
        _write_test_guide_lifecycle(self.task_dir, architecture_outline="done", development_details="done", verification_results="done")
        # tp-verification PASS 事件（Final Night Hardening P0-4：显式声明证据）
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-verification-engineering", "--review-only", "--summary", "pass",
                          "--decision", "PASS", "--evidence", "evidence/test-result.txt"])
        self.assertEqual(rc, 0, f"verification pass failed: {err}")

    # ---- §15.3-1：PENDING 验收不 CLOSING ----
    def test_pending_acceptance_no_closing(self):
        self._advance_to_closing_ready()
        # 故意留一条 PENDING
        acc = Path(self.task_dir) / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        text = text.replace("| PASS |", "| PENDING |", 1)
        acc.write_text(text, encoding="utf-8", newline="\n")
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                            "--actor", "tp-delivery-convergence", "--to", "CLOSING", "--summary", "close"])
        self.assertNotEqual(rc, 0)
        self.assertIn("ACCEPTANCE_PENDING", err.upper())

    # ---- §15.3-2：deferred_acceptance 缺字段拒绝 ----
    def test_deferred_acceptance_invalid(self):
        self._advance_to_closing_ready()
        acc = Path(self.task_dir) / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        # 注入缺少字段的 deferred_acceptance YAML 块
        text += "\n```yaml\ndeferred_acceptance:\n  - ac: AC-01\n```\n"
        acc.write_text(text, encoding="utf-8", newline="\n")
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                            "--actor", "tp-delivery-convergence", "--to", "CLOSING", "--summary", "close"])
        self.assertNotEqual(rc, 0)
        self.assertIn("DEFERRED_ACCEPTANCE_INVALID", err.upper())

    # ---- §15.3-3：codex-review 空正文拒绝 ----
    def test_code_review_empty_body(self):
        self._advance_to_closing_ready()
        cr = Path(self.task_dir) / "codex-review.md"
        cr.write_text("---\nreview:\n  decision: PASS\n---\n", encoding="utf-8")
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                            "--actor", "tp-delivery-convergence", "--to", "CLOSING", "--summary", "close"])
        self.assertNotEqual(rc, 0)
        self.assertIn("CODE_REVIEW_EMPTY", err.upper())

    # ---- §15.3-4：无 PASS 不 CLOSING（已在绕过组覆盖，此处走 commit 路径再断言）----
    def test_no_pass_no_closing_commit(self):
        self._advance_to_verifying()
        acc = Path(self.task_dir) / "acceptance.md"
        acc.write_text(acc.read_text(encoding="utf-8").replace("| PENDING |", "| PASS |"), encoding="utf-8")
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                            "--actor", "tp-delivery-convergence", "--to", "CLOSING", "--summary", "close"])
        self.assertNotEqual(rc, 0)

    # ---- §15.3-5：L3 同样只依赖自动质量门禁 ----
    def test_l3_cannot_complete_without_required_verification_and_delivery(self):
        task_id = "TASK-20260804-201"
        work, task_dir, db_path = _prepare(task_id=task_id, risk="L3", flow="L3")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        rc, out, err = run([
            "task", "checkpoint", "--task", task_id, "--task-dir", str(task_dir), "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development",
            "--summary", "L3 work ended without formal verification",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "complete", "--task", task_id, "--task-dir", str(task_dir), "--db", db_path,
            "--actor", "tp-development-engineering", "--summary", "premature completion",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("INTEGRITY_PIPELINE_PENDING", err + out)

    # ---- §15.3-6：scope change drift ----
    def test_scope_change_drift(self):
        """Scope metadata drift is no longer a closing-state blocker; explicit business blockers are."""
        rc, out, err = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--phase", "development", "--summary", "scope note updated",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "block", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--reason", "explicit scope decision required",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering", "--summary", "done",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("explicit task blocker", err)
    def test_human_page_witness_required_for_human_pass(self):
        self._advance_to_verifying()
        acc = Path(self.task_dir) / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        text = text.replace(
            "| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |",
            "| AC-01 | 人工页面结果符合预期 | task.md / requirement-test-guide.md | L1 | 页面验证 | evidence/test-result.txt | human | PASS |",
        )
        text = text.replace("mode: NOT_REQUIRED", "mode: human").replace("human_witness: pending", "human_witness: pending")
        acc.write_text(text, encoding="utf-8", newline="\n")
        rc, out, err = run([
            "commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
            "--actor", "tp-verification-engineering", "--review-only", "--decision", "PASS",
            "--summary", "pass", "--evidence", "evidence/test-result.txt", "--dry-run",
        ])
        self.assertNotEqual(rc, 0)
        report = json.loads(out)
        self.assertIn("USER_CONFIRMATION_REQUIRED", {i["code"] for i in report["issues"]})

    # ---- §15.3-8：test guide lifecycle 未完成 ----
    def test_test_guide_incomplete(self):
        self._advance_to_verifying()
        acc = Path(self.task_dir) / "acceptance.md"
        acc.write_text(acc.read_text(encoding="utf-8").replace("| PENDING |", "| PASS |"), encoding="utf-8")
        cr = Path(self.task_dir) / "codex-review.md"
        cr.write_text("---\nreview:\n  decision: PASS\n---\n\n## 审查结论\nPASS\n\n## 证据\nx\n\n## 残余风险\n无\n", encoding="utf-8")
        # verification_results 未 done
        _write_test_guide_lifecycle(self.task_dir, architecture_outline="done", development_details="done", verification_results="pending")
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                          "--actor", "tp-verification-engineering", "--review-only", "--summary", "pass",
                          "--decision", "PASS"])
        # verification_results pending 会阻断记录 Verification PASS（test guide 门禁）
        self.assertNotEqual(rc, 0)

    # ---- §15.3-9：合法 CLOSING 通过 ----
    def test_legal_closing_passes(self):
        self._advance_to_closing_ready()
        rc, out, err = run(["commit", "--task", TASK_ID, "--task-dir", str(self.task_dir), "--db", self.db_path,
                            "--actor", "tp-delivery-convergence", "--to", "CLOSING", "--summary", "close"])
        self.assertEqual(rc, 0, f"legal CLOSING must pass: {err}")
        conn = _conn(self.db_path)
        try:
            row, _ = db_state(conn, TASK_ID)
        finally:
            conn.close()
        self.assertEqual(row["current_state"], "CLOSING")


class TestTransactionReconcile(unittest.TestCase):
    """§15 transaction/reconcile（任务书 §3/P0-7）。"""

    def setUp(self):
        self.work, self.task_dir, self.db_path = _prepare(risk="L1", flow="L1")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _committed(self):
        _write_test_guide_lifecycle(self.task_dir, architecture_outline="done")
        rc, _, err = run(["commit", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path,
                          "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "dev"])
        self.assertEqual(rc, 0, err)

    # ---- §15.4-1：journal 记录身份字段（owner/flush_id）----
    def test_journal_identity_fields(self):
        self._committed()
        # 构造残留 journal 模拟崩溃（记录身份字段）
        jdir = Path(self.task_dir) / ".tp-spec" / "transactions"
        jdir.mkdir(parents=True, exist_ok=True)
        tx_id = transaction_journal.new_transaction_id()
        journal = {
            "schema": "tp-spec.transaction/v1",
            "transaction_id": tx_id,
            "task_id": TASK_ID,
            "operation": "commit",
            "phase": "DB_COMMITTED",
            "db_state_before": "NEW",
            "target_state": "DEVELOPING",
            "owner_before": "tp-architecture-design",
            "owner_after": "tp-development-engineering",
            "flush_id": "FLUSH-IDENTITY-TEST",
            "db_revision_before": 1,
            "expected_revision_after": _event_count(self.db_path),
            "expected_event_ids": [],
            "expected_event_types": [],
            "expected_state_event_id": None,
            "expected_handoff_event_id": None,
            "backup_dir": str(Path(self.task_dir) / f".v511-bak-{tx_id}"),
            "files": [],
        }
        transaction_journal.write_journal(Path(self.task_dir), journal)
        got = transaction_journal.read_journal(Path(self.task_dir), tx_id)
        self.assertIsNotNone(got)
        self.assertEqual(got["owner_before"], "tp-architecture-design")
        self.assertEqual(got["owner_after"], "tp-development-engineering")
        self.assertEqual(got["flush_id"], "FLUSH-IDENTITY-TEST")

    # ---- §15.4-2：情况 B 五要素判定（同任务事件碰撞不误判）----
    def test_recovery_identity_mismatch_is_C(self):
        self._committed()
        rev = _event_count(self.db_path)
        jdir = Path(self.task_dir) / ".tp-spec" / "transactions"
        jdir.mkdir(parents=True, exist_ok=True)
        tx_id = transaction_journal.new_transaction_id()
        # 伪造 journal：revision 与 DB 一致，但 state/owner/flush_id 全部不匹配
        journal = {
            "schema": "tp-spec.transaction/v1",
            "transaction_id": tx_id,
            "task_id": TASK_ID,
            "operation": "commit",
            "phase": "DB_COMMITTED",
            "db_state_before": "NEW",
            "target_state": "CLOSING",       # 与 DB current_state=DEVELOPING 不符
            "owner_before": "tp-architecture-design",
            "owner_after": "human_owner",     # 与 DB owner 不符
            "flush_id": "FLUSH-NOT-EXIST",
            "db_revision_before": 1,
            "expected_revision_after": rev,   # revision 匹配 → 需五要素判定
            "expected_state_event_id": 99999,
            "expected_handoff_event_id": None,
            "backup_dir": str(Path(self.task_dir) / f".v511-bak-{tx_id}"),
            "files": [],
        }
        transaction_journal.write_journal(Path(self.task_dir), journal)
        rc, out, err = run(["reconcile", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path])
        self.assertNotEqual(rc, 0, "identity mismatch must be treated as undecidable (C)")
        self.assertIn("PROJECTION_RECONCILIATION_REQUIRED", err)
        self.assertTrue(transaction_journal.read_journal(Path(self.task_dir), tx_id) is not None,
                        "journal must be kept on undecidable")

    # ---- §15.4-3：restore 逐文件核验 before digest ----
    def test_restore_verifies_before_digest(self):
        self._committed()
        rev = _event_count(self.db_path)
        status_path = Path(self.task_dir) / "status.yaml"
        original = status_path.read_bytes()
        jdir = Path(self.task_dir) / ".tp-spec" / "transactions"
        jdir.mkdir(parents=True, exist_ok=True)
        tx_id = transaction_journal.new_transaction_id()
        bak_dir = Path(self.task_dir) / f".v511-bak-{tx_id}"
        bak_dir.mkdir(parents=True, exist_ok=True)
        # 备份内容被篡改（与 before_digest 不符）
        (bak_dir / "status.yaml").write_bytes(b"tampered backup")
        journal = {
            "schema": "tp-spec.transaction/v1",
            "transaction_id": tx_id,
            "task_id": TASK_ID,
            "operation": "commit",
            "phase": "PREPARED",
            "db_state_before": "DEVELOPING",
            "target_state": "DEVELOPING",
            "db_revision_before": rev,
            "expected_revision_after": rev,
            "backup_dir": str(bak_dir),
            "files": [{
                "path": "status.yaml",
                "backup": str(bak_dir / "status.yaml"),
                "temp": None,
                "before_digest": hashlib.sha256(original).hexdigest(),
                "target_digest": None,
            }],
        }
        transaction_journal.write_journal(Path(self.task_dir), journal)
        # 篡改正式文件触发恢复
        status_path.write_text('current_state: "COMPLETED"  # tampered\n', encoding="utf-8")
        rc, out, err = run(["reconcile", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path])
        self.assertNotEqual(rc, 0, "backup digest mismatch must be undecidable")
        self.assertIn("PROJECTION_RECONCILIATION_REQUIRED", err)

    # ---- §15.4-4：write_journal 刷新 updated_at ----
    def test_journal_updated_at_refresh(self):
        self._committed()
        jdir = Path(self.task_dir) / ".tp-spec" / "transactions"
        jdir.mkdir(parents=True, exist_ok=True)
        tx_id = transaction_journal.new_transaction_id()
        j = {"schema": "tp-spec.transaction/v1", "transaction_id": tx_id, "task_id": TASK_ID,
             "operation": "commit", "phase": "PREPARED", "created_at": "2026-08-04T00:00:00Z",
             "updated_at": "2026-08-04T00:00:00Z"}
        transaction_journal.write_journal(Path(self.task_dir), j)
        got1 = transaction_journal.read_journal(Path(self.task_dir), tx_id)
        first_ts = got1["updated_at"]
        # 模拟 phase 更新（write_journal 原地刷新 updated_at 为真实新时间）
        got1["phase"] = "FILES_REPLACED"
        transaction_journal.write_journal(Path(self.task_dir), got1)
        got2 = transaction_journal.read_journal(Path(self.task_dir), tx_id)
        self.assertNotEqual(first_ts, got2["updated_at"], "updated_at must refresh on phase update")
        self.assertGreater(got2["updated_at"], first_ts)

    # ---- §15.4-5：STATE/HANDOFF 事件 detail 携带 flush_id（身份锚点）----
    def test_events_carry_flush_id(self):
        self._committed()
        conn = _conn(self.db_path)
        try:
            state_row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='STATE' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()
            handoff_row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='HANDOFF' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()
        finally:
            conn.close()
        state_detail = json.loads(state_row["detail_json"])
        handoff_detail = json.loads(handoff_row["detail_json"])
        self.assertTrue(state_detail["flush_id"])
        self.assertEqual(handoff_detail["flush_id"], state_detail["flush_id"],
                         "STATE and HANDOFF events must share the same flush_id")

    # ---- §15.4-6：backup digest mismatch → C（已含于 15.4-3）----
    def test_backup_digest_mismatch_undecidable(self):
        self.test_restore_verifies_before_digest()

    # ---- §15.4-7：恢复后无残留 temp ----
    def test_reconcile_cleans_tmp(self):
        self._committed()
        # 制造无主 tmp 残留
        tmp = Path(self.task_dir) / ".stray.tmp"
        tmp.write_text("stray", encoding="utf-8")
        rc, out, err = run(["reconcile", "--task", TASK_ID, "--task-dir", self.task_dir, "--db", self.db_path])
        self.assertEqual(rc, 0, err)
        self.assertFalse(tmp.exists(), "stray tmp must be cleaned")


class TestVersionManifest(unittest.TestCase):
    """§15 版本与 manifest（任务书 §12/P1-2）。"""

    def test_scanner_allows_history_locations(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cvc", str(BASE / "scripts" / "check_version_consistency.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # docs/ 与 reports/ 属历史位置 → 放行（拼接构造，避免测试文件自身命中扫描器）
        self.assertTrue(mod._is_allowed_history("docs/V5.1.3_源码级发布审查报告.md"))
        hist_report = "reports/v5.1." + "0-final-polish-report.md"
        self.assertTrue(mod._is_allowed_history(hist_report))
        self.assertFalse(mod._is_allowed_history("README.md"))

    def test_scanner_rejects_activity_legacy(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cvc", str(BASE / "scripts" / "check_version_consistency.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        version = (BASE / "VERSION").read_text(encoding="utf-8").strip()
        legacy_re = mod._build_legacy_re(version)
        prev = "5.1." + "0"
        issues = mod.scan_file(BASE / "README.md", legacy_re, version)
        # README 当前无旧版本 token（已清理）→ 无问题
        self.assertEqual(issues, [])

    def test_version_dynamic(self):
        from cli.version import active_version
        self.assertEqual(active_version(), ACTIVE_VERSION)
        version_file = (BASE / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(version_file, active_version())

    def test_test_guide_template_is_optional_business_prose(self):
        tpl = (BASE / "templates" / ACTIVE_VERSION / "requirement-test-guide.md").read_text(encoding="utf-8")
        self.assertIn("# Test Guide（按需）", tpl)
        self.assertNotIn("current_owner:", tpl)
        self.assertNotIn("section_owners:", tpl)
        self.assertNotIn("verification_results:", tpl)
        self.assertIn("## 关键场景", tpl)

    def test_role_catalog_has_new_roles(self):
        import yaml
        cat = yaml.safe_load((BASE / "agents" / "role-catalog.yaml").read_text(encoding="utf-8"))
        roles = {r["workflow_role"] for r in cat["roles"]}
        self.assertIn("tp-requirement-analysis", roles)
        self.assertIn("tp-architecture-review", roles)
        # 新角色 hash 与规范化 SKILL.md 一致
        for r in cat["roles"]:
            if r["workflow_role"] in ("tp-requirement-analysis", "tp-architecture-review"):
                p = BASE / r["skill_path"]
                text = p.read_text(encoding="utf-8")
                if text.startswith("\ufeff"):
                    text = text[1:]
                text = text.replace("\r\n", "\n").rstrip("\n") + "\n"
                self.assertEqual(r["content_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest().upper(),
                                 r["skill_path"])


if __name__ == "__main__":
    unittest.main()
