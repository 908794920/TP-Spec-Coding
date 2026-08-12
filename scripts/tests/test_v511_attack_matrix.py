# -*- coding: utf-8 -*-
"""V5.1.3 Final Hardening 攻击矩阵（真实 CLI subprocess，任务书 §4/§12）。

矩阵 A~F：
- A 治理事件伪造：event add/sync 注入 STATE/REVIEW_COMPLETED
- B 架构评审：空模板 PASS、design 变化 stale
- C 验收与 Review：PASSED 别名、无证据 PASS
- D 自动结单：人员审批 CLI 已移除，可信 Verification PASS 后直接结单
- E Transaction/Crash：事务恢复身份（strict_restore 保留证据）
- F 状态入口：event 不可推进状态

全部通过真实 ``python -m cli.main`` 子进程 + 临时 SQLite 执行。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v511_commit_reliability import build_task  # noqa: E402

PYTHON = sys.executable


def run_cli(db, task_dir, *argv, expect=None):
    """真实 CLI 子进程（--db/--task-dir 追加在子命令后，与 CLI 参数约定一致）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    args = list(argv)
    sub = args[0] if args else ""
    is_event_add = sub == "event" and len(args) > 1 and args[1] == "add"
    args.append("--db")
    args.append(str(db))
    if not is_event_add:
        args.append("--task-dir")
        args.append(str(task_dir))
    proc = subprocess.run(
        [PYTHON, "-m", "cli.main", *args],
        capture_output=True, env=env,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    if expect is not None:
        assert proc.returncode == expect, (
            f"rc={proc.returncode} (expect {expect}) :: {' '.join(argv)}\n{out}{err}"
        )
    return proc.returncode, out, err


class _AttackFixture(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-atk-")
        self.task_id = "TASK-ATK-FINAL"
        task_dir, db_path = build_task(self.work, task_id=self.task_id)
        self.task_dir = Path(task_dir)
        self.db = db_path
        from cli import db as dbmod
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET risk_level='L2', flow_level='L2' WHERE task_id=?",
                         (self.task_id,))
            conn.commit()
        finally:
            conn.close()
        self._fill_design_artifacts()

    def _fill_design_artifacts(self):
        """架构评审前置：knowledge/decisions/arch 正文（正式准备，非伪造事件）。"""
        p = self.task_dir / "requirement-knowledge.md"
        p.write_text(p.read_text(encoding="utf-8").replace("complete: false", "complete: true"),
                     encoding="utf-8", newline="\n")
        p = self.task_dir / "requirement-decisions.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace('selected_option: ""', 'selected_option: "方案A"', 1)
        text = text.replace('decision: ""', 'decision: "确定技术方案A"', 1)
        p.write_text(text, encoding="utf-8", newline="\n")
        p = self.task_dir / "architecture-review.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace("decision: DRAFT", "decision: PASS")
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
        # test-guide 骨架（DEVELOPING/VERIFYING 前置）
        p = self.task_dir / "requirement-test-guide.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace("architecture_outline: pending", "architecture_outline: done")
        text = text.replace("development_details: pending", "development_details: done")
        p.write_text(text, encoding="utf-8", newline="\n")

    def _record_arch_pass(self):
        rc, _, err = run_cli(self.db, self.task_dir, "review", "record",
                             "--task", self.task_id, "--actor", "tp-architecture-review",
                             "--kind", "ARCHITECTURE", "--decision", "PASS", "--round", "1",
                             "--summary", "arch pass", "--evidence", "evidence/architecture-review-check.txt",
                             expect=0)

    def _advance_to_developing(self):
        self._record_arch_pass()
        run_cli(self.db, self.task_dir, "commit", "--task", self.task_id,
                "--actor", "tp-architecture-design", "--to", "DEVELOPING",
                "--summary", "dev", expect=0)

    def _advance_to_verifying(self):
        self._advance_to_developing()
        run_cli(self.db, self.task_dir, "commit", "--task", self.task_id,
                "--actor", "tp-development-engineering", "--to", "VERIFYING",
                "--summary", "verify", expect=0)


# ============================== A 治理事件伪造 ==============================
class TestAttackA_GovernanceForge(_AttackFixture):
    def test_a1_event_add_state_rejected(self):
        rc, _, err = run_cli(self.db, self.task_dir, "event", "add",
                             "--task", self.task_id, "--type", "STATE",
                             "--actor", "tp-architecture-design", "--note", "forge")
        self.assertEqual(rc, 8)
        self.assertIn("GOVERNANCE_EVENT_REQUIRES_TRUSTED_PRODUCER", err)

    def test_a2_event_sync_review_completed_rejected(self):
        ev = json.dumps({"type": "REVIEW_COMPLETED", "actor_role": "tp-architecture-review",
                         "summary": "PASS", "note": "forge", "flush_id": "fA", "time": "2026-08-04"})
        (self.task_dir / "events.jsonl").write_text(ev + "\n", encoding="utf-8")
        rc, _, err = run_cli(self.db, self.task_dir, "event", "sync", "--task", self.task_id)
        self.assertEqual(rc, 8)
        self.assertIn("EVENT_SYNC_FACT_ONLY", err)

    def test_a3_forged_pass_cannot_advance(self):
        ev = json.dumps({"type": "REVIEW_COMPLETED", "actor_role": "tp-architecture-review",
                         "summary": "PASS", "note": "forge", "flush_id": "fA", "time": "2026-08-04"})
        (self.task_dir / "events.jsonl").write_text(ev + "\n", encoding="utf-8")
        run_cli(self.db, self.task_dir, "event", "sync", "--task", self.task_id, expect=8)
        rc, _, err = run_cli(self.db, self.task_dir, "commit", "--task", self.task_id,
                             "--actor", "tp-architecture-design", "--to", "DEVELOPING",
                             "--summary", "dev")
        self.assertNotEqual(rc, 0)
        self.assertIn("ARCHITECTURE", err.upper())


# ============================== B 架构评审 ==============================
class TestAttackB_ArchitectureReview(_AttackFixture):
    def test_b1_empty_template_pass_rejected(self):
        p = self.task_dir / "architecture-review.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace("decision: PASS", "decision: DRAFT")
        text = text.replace("PASS", "DRAFT / PASS / REVISE / BLOCKED")
        p.write_text(text, encoding="utf-8", newline="\n")
        rc, _, err = run_cli(self.db, self.task_dir, "review", "record",
                             "--task", self.task_id, "--actor", "tp-architecture-review",
                             "--kind", "ARCHITECTURE", "--decision", "PASS", "--round", "1",
                             "--summary", "arch", "--evidence", "evidence/architecture-review-check.txt")
        self.assertEqual(rc, 8)
        self.assertIn("REVIEW_PASS_CONTENT_GATE", err)

    def test_b2_design_change_stale(self):
        """V5.1.3: an old architecture review is historical evidence, not a development license."""
        self._record_arch_pass()
        task_md = self.task_dir / "task.md"
        task_md.write_text(task_md.read_text(encoding="utf-8") + "\n补充业务说明。\n", encoding="utf-8")
        rc, _, err = run_cli(
            self.db, self.task_dir, "task", "checkpoint", "--task", self.task_id,
            "--actor", "tp-development-engineering", "--phase", "development",
            "--summary", "continue development after later wording change",
        )
        self.assertEqual(rc, 0, err)
class TestAttackC_AcceptanceReview(_AttackFixture):
    def test_c1_passed_alias_rejected(self):
        acc = self.task_dir / "acceptance.md"
        acc.write_text(acc.read_text(encoding="utf-8").replace("| PENDING |", "| PASSED |"),
                       encoding="utf-8", newline="\n")
        from cli.validator import validate_artifacts
        result = validate_artifacts(str(self.task_dir), ["acceptance"])
        msgs = [i["message"] for i in result["issues"]]
        self.assertFalse(result["ok"])
        self.assertTrue(any("verdict" in m for m in msgs), f"issues={result['issues']}")

    def test_c2_pass_without_evidence_rejected(self):
        acc = self.task_dir / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        text = text.replace(
            "| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |",
            "| AC-01 | 目标 | task.md | L2 | 验证 |  | verification | PASS |",
        )
        acc.write_text(text, encoding="utf-8", newline="\n")
        from cli.validator import validate_artifacts
        result = validate_artifacts(str(self.task_dir), ["acceptance"])
        msgs = [i["message"] for i in result["issues"]]
        self.assertFalse(result["ok"])
        self.assertTrue(any("evidence" in m for m in msgs), f"issues={result['issues']}")


# ============================== D 自动结单质量门禁 ==============================
class TestAttackD_AutomaticCompletion(_AttackFixture):
    def _verification_ready(self):
        # Record-first verification is a fact; no DEVELOPING/VERIFYING/CLOSING route is required.
        run_cli(
            self.db, self.task_dir, "task", "checkpoint", "--task", self.task_id,
            "--actor", "tp-development-engineering", "--phase", "development",
            "--summary", "implementation complete", expect=0,
        )
        run_cli(
            self.db, self.task_dir, "task", "verify", "--task", self.task_id,
            "--actor", "tp-verification-engineering", "--decision", "PASS",
            "--summary", "verified", "--evidence", "evidence/test-result.txt", expect=0,
        )

    def test_d1_personnel_approval_cli_is_removed(self):
        rc, _, err = run_cli(self.db, self.task_dir, "receipt", "request", "--task", self.task_id)
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized arguments", err)

    def test_d2_trusted_verification_can_complete_without_closing(self):
        self._verification_ready()
        rc, out, err = run_cli(
            self.db, self.task_dir, "task", "complete", "--task", self.task_id,
            "--actor", "tp-verification-engineering", "--summary", "done", expect=0,
        )
        result = json.loads(out)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["verification"], "PASS")
        self.assertNotIn("CLOSING", out + err)

    def test_d3_acceptance_change_marks_verification_stale_without_fake_pass(self):
        self._verification_ready()
        acceptance = self.task_dir / "acceptance.md"
        text = acceptance.read_text(encoding="utf-8")
        text = text.replace("| AC-01 |  |", "| AC-01 | 新增一个需要验证的语义条件 |", 1)
        acceptance.write_text(text, encoding="utf-8", newline="\n")
        rc, out, err = run_cli(
            self.db, self.task_dir, "task", "complete", "--task", self.task_id,
            "--actor", "tp-verification-engineering", "--summary", "done after subject change", expect=0,
        )
        result = json.loads(out)
        self.assertEqual(result["verification"], "PASS_STALE")
        final = (self.task_dir / "generated" / "final-result.md").read_text(encoding="utf-8")
        self.assertIn("PASS_STALE", final)



# ============================== E Transaction/Crash ==============================
class TestAttackE_TransactionIdentity(unittest.TestCase):
    def test_e1_strict_restore_fail_closed(self):
        from cli.transaction_journal import strict_restore
        work = tempfile.mkdtemp(prefix="v511-atkE-")
        task_dir = Path(work) / "proj"
        (task_dir / "generated").mkdir(parents=True)
        target = task_dir / "status.yaml"
        target.write_text("new\n", encoding="utf-8", newline="\n")
        journal = {"files": [
            {"path": "status.yaml", "before_digest": "a" * 64,
             "backup": str(task_dir / "missing.bak")},
        ]}
        result = strict_restore(task_dir, journal)
        self.assertFalse(result.ok, "missing backup must fail-closed")
        self.assertEqual(target.read_text(encoding="utf-8"), "new\n", "target must not be touched")


# ============================== F 状态入口 ==============================
class TestAttackF_StateEntryPoints(_AttackFixture):
    def test_f1_event_add_does_not_advance_state(self):
        from cli import db as dbmod
        conn = dbmod.connect(self.db)
        try:
            before = conn.execute("SELECT current_state, owner_role FROM task WHERE task_id=?",
                                  (self.task_id,)).fetchone()
        finally:
            conn.close()
        run_cli(self.db, self.task_dir, "event", "add", "--task", self.task_id,
                "--type", "FACT", "--actor", "tp-architecture-design", "--note", "n", expect=0)
        conn = dbmod.connect(self.db)
        try:
            after = conn.execute("SELECT current_state, owner_role FROM task WHERE task_id=?",
                                 (self.task_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(before), tuple(after))

    def test_f2_record_first_does_not_enforce_canonical_phase_owner_but_rejects_unknown_actor(self):
        rc, out, err = run_cli(
            self.db, self.task_dir, "task", "checkpoint", "--task", self.task_id,
            "--actor", "tp-architecture-design", "--phase", "verification",
            "--summary", "cross-role factual checkpoint", expect=0,
        )
        self.assertEqual(json.loads(out)["phase"], "verification")
        rc, _, err = run_cli(
            self.db, self.task_dir, "task", "checkpoint", "--task", self.task_id,
            "--actor", "unknown-role", "--phase", "verification", "--summary", "bad actor",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("invalid choice", err)


if __name__ == "__main__":
    unittest.main()
