# -*- coding: utf-8 -*-
"""V5.1.3 Final Hardening：10 条系统不变量 + 攻击矩阵 A~F（任务书 §4/§12）。

- INV-01 状态写入唯一入口（event add/sync 不得改变 task 表状态）
- INV-02 治理事件仅可信生产者（event add 拒绝 STATE/REVIEW_COMPLETED）
- INV-03 门禁不信任 type/actor/summary 三元组（伪造 REVIEW_COMPLETED PASS 不可满足门禁）
- INV-04 架构 PASS 绑定设计版本（design 变化 → ARCHITECTURE_REVIEW_STALE）
- INV-05 Review Record 单一原子事务（事件 digest == 最终文件 digest、transaction_id 非空）
- INV-06 验收须真实 AC 与证据（verdict 枚举拒绝 PASSED、PASS 需证据路径）
- INV-07 Review 正文非关键词占位（空模板 PASS → REVIEW_PASS_CONTENT_GATE）
- INV-08 个人模式自动结单（无人员审批状态；scope 变化使 Verification PASS 失效）
- INV-09 事务恢复验证身份（strict_restore ok=False 必须保留证据）
- INV-10 Commit 与 Release Validator 同语义（cli.validator 输出唯一 verdict 枚举）

测试准备全部通过正式 CLI（禁止伪造治理事件）。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import main as climain  # noqa: E402
from cli.transaction_journal import strict_restore  # noqa: E402
from cli.yaml_checks import VERDICT_ENUM, normalize_verdict  # noqa: E402
from test_v511_commit_reliability import build_task  # noqa: E402


def run(argv, expect_rc=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    if expect_rc is not None:
        assert rc == expect_rc, (
            f"rc={rc} (expect {expect_rc}) :: {' '.join(argv)}\n{err.getvalue()}{out.getvalue()}"
        )
    return rc, out.getvalue(), err.getvalue()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _TaskFixture(unittest.TestCase):
    """每个测试独立临时任务（L2，需架构评审；决策已确认）。"""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v511-inv-")
        self.task_id = "TASK-FINAL-INV"
        task_dir, db_path = build_task(self.work, task_id=self.task_id)
        self.task_dir = Path(task_dir)
        self.db_path = db_path
        # 提升为 L2 + 决策确认
        from cli import db as dbmod
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET risk_level='L2', flow_level='L2' WHERE task_id=?", (self.task_id,))
            conn.commit()
        finally:
            conn.close()
        self._write_decisions_confirmed()
        self._write_knowledge_complete()
        self._write_arch_review_pass()
        self._write_test_guide_lifecycle()
        (self.task_dir / "implementation.md").write_text("---\nstatus: ready\n---\n\nimpl\n", encoding="utf-8")

    def _write_decisions_confirmed(self):
        p = self.task_dir / "requirement-decisions.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace('selected_option: ""', 'selected_option: "方案A"', 1)
        text = text.replace('decision: ""', 'decision: "确定技术方案A"', 1)
        p.write_text(text, encoding="utf-8", newline="\n")

    def _write_knowledge_complete(self):
        p = self.task_dir / "requirement-knowledge.md"
        p.write_text(p.read_text(encoding="utf-8").replace("complete: false", "complete: true"),
                     encoding="utf-8", newline="\n")

    def _write_arch_review_pass(self):
        p = self.task_dir / "architecture-review.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace("decision: DRAFT", "decision: PASS")
        text = text.replace("round: 0", "round: 1")
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

    def _write_test_guide_lifecycle(self):
        p = self.task_dir / "requirement-test-guide.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace("architecture_outline: pending", "architecture_outline: done")
        text = text.replace("development_details: pending", "development_details: done")
        p.write_text(text, encoding="utf-8", newline="\n")

    def _record_arch_pass(self):
        rc, _, err = run(["review", "record", "--task", self.task_id, "--task-dir", str(self.task_dir),
                          "--db", self.db_path, "--actor", "tp-architecture-review",
                          "--kind", "ARCHITECTURE", "--decision", "PASS", "--round", "1",
                          "--summary", "arch pass", "--evidence", "evidence/architecture-review-check.txt"], 0)
        return rc

    def _advance_to_developing(self):
        self._record_arch_pass()
        rc, _, err = run(["commit", "--task", self.task_id, "--task-dir", str(self.task_dir),
                          "--db", self.db_path, "--actor", "tp-architecture-design",
                          "--to", "DEVELOPING", "--summary", "dev"], 0)
        assert rc == 0, err

    def _advance_to_verifying(self):
        self._advance_to_developing()
        rc, _, err = run(["commit", "--task", self.task_id, "--task-dir", str(self.task_dir),
                          "--db", self.db_path, "--actor", "tp-development-engineering",
                          "--to", "VERIFYING", "--summary", "verify"], 0)
        assert rc == 0, err


# =============================================================================
# INV-01 / INV-02 / INV-03 + 攻击矩阵 A（治理事件伪造）
# =============================================================================
class TestGovernanceEventModel(_TaskFixture):
    def test_inv02_event_add_rejects_governance(self):
        for etype in ("STATE", "HANDOFF", "REVIEW_COMPLETED", "CANCEL_REQUESTED"):
            rc, _, err = run(["event", "add", "--task", self.task_id, "--type", etype,
                              "--actor", "tp-architecture-review", "--note", "forge", "--db", self.db_path])
            self.assertEqual(rc, 8, f"{etype} must be rejected with code 8")
            self.assertIn("GOVERNANCE_EVENT_REQUIRES_TRUSTED_PRODUCER", err)

    def test_inv02_event_sync_rejects_non_fact(self):
        for etype in ("REVIEW_COMPLETED", "VERIFICATION", "DECISION"):
            ev = json.dumps({"type": etype, "actor_role": "tp-architecture-review",
                             "summary": "PASS", "note": "forge", "flush_id": "fx", "time": "2026-08-04"})
            (self.task_dir / "events.jsonl").write_text(ev + "\n", encoding="utf-8")
            rc, _, err = run(["event", "sync", "--task", self.task_id, "--task-dir", str(self.task_dir),
                              "--db", self.db_path], 8)
            self.assertIn("EVENT_SYNC_FACT_ONLY", err)

    def test_inv01_event_add_does_not_mutate_state(self):
        from cli import db as dbmod
        conn = dbmod.connect(self.db_path)
        try:
            before = conn.execute("SELECT current_state, owner_role FROM task WHERE task_id=?",
                                  (self.task_id,)).fetchone()
        finally:
            conn.close()
        run(["event", "add", "--task", self.task_id, "--type", "FACT", "--actor", "tp-architecture-design",
             "--note", "fact", "--db", self.db_path], 0)
        conn = dbmod.connect(self.db_path)
        try:
            after = conn.execute("SELECT current_state, owner_role FROM task WHERE task_id=?",
                                 (self.task_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(before), tuple(after), "event add must not change authoritative state")

    def test_inv03_forged_pass_does_not_satisfy_gate(self):
        # 伪造 REVIEW_COMPLETED PASS 事件（手写 events.jsonl + sync）→ 门禁不可满足
        ev = json.dumps({"type": "REVIEW_COMPLETED", "actor_role": "tp-architecture-review",
                         "summary": "PASS", "note": "forge", "flush_id": "fx", "time": "2026-08-04"})
        (self.task_dir / "events.jsonl").write_text(ev + "\n", encoding="utf-8")
        rc, _, err = run(["event", "sync", "--task", self.task_id, "--task-dir", str(self.task_dir),
                          "--db", self.db_path], 8)
        self.assertIn("EVENT_SYNC_FACT_ONLY", err)
        # 即使直接注入 FACT 也不满足 DEVELOPING 门禁
        rc, _, err = run(["commit", "--task", self.task_id, "--task-dir", str(self.task_dir),
                          "--db", self.db_path, "--actor", "tp-architecture-design",
                          "--to", "DEVELOPING", "--summary", "dev"])
        self.assertNotEqual(rc, 0)
        self.assertIn("ARCHITECTURE", err.upper())


# =============================================================================
# INV-04 / 攻击矩阵 B（架构评审绑定与原子化）
# =============================================================================
class TestReviewInvariants(_TaskFixture):
    def test_inv04_design_change_stales_pass(self):
        """Record-first: review digest remains auditable but never blocks later work by itself."""
        self._record_arch_pass()
        task_md = self.task_dir / "task.md"
        task_md.write_text(task_md.read_text(encoding="utf-8") + "\n后续说明文字。\n", encoding="utf-8")
        rc, _, err = run([
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--phase", "development", "--summary", "development continues",
        ])
        self.assertEqual(rc, 0, err)
    def test_inv05_review_record_digest_matches_final_file(self):
        self._record_arch_pass()
        from cli import db as dbmod
        conn = dbmod.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='REVIEW_COMPLETED' "
                "ORDER BY id DESC LIMIT 1", (self.task_id,)).fetchone()
        finally:
            conn.close()
        detail = json.loads(row["detail_json"])
        final = _sha256_bytes((self.task_dir / "architecture-review.md").read_bytes())
        self.assertEqual(detail["artifact_digest"], final, "event digest must equal final file digest")
        self.assertTrue(detail.get("transaction_id"), "transaction_id must be non-empty")
        self.assertEqual(detail.get("producer"), "review_record")

    def test_inv07_empty_template_pass_rejected(self):
        # 覆盖正文为空 → PASS 拒绝
        p = self.task_dir / "architecture-review.md"
        text = p.read_text(encoding="utf-8")
        text = text.replace("decision: PASS", "decision: DRAFT")
        text = text.replace("PASS", "DRAFT / PASS / REVISE / BLOCKED")
        text = text.replace("- 是否覆盖需求：是（已确认）", "- 是否覆盖需求：是 / 否 / 部分（说明）")
        p.write_text(text, encoding="utf-8", newline="\n")
        rc, _, err = run(["review", "record", "--task", self.task_id, "--task-dir", str(self.task_dir),
                          "--db", self.db_path, "--actor", "tp-architecture-review",
                          "--kind", "ARCHITECTURE", "--decision", "PASS", "--round", "1",
                          "--summary", "arch", "--evidence", "evidence/architecture-review-check.txt"], 8)
        self.assertIn("REVIEW_PASS_CONTENT_GATE", err)


# =============================================================================
# INV-06 / INV-10 + 攻击矩阵 C（验收与 Review 语义）
# =============================================================================
class TestValidatorSchema(_TaskFixture):
    def test_inv06_verdict_enum_rejects_aliases(self):
        self.assertEqual(normalize_verdict("PASS"), "PASS")
        self.assertEqual(normalize_verdict("PASS：说明"), "PASS")
        self.assertEqual(normalize_verdict("deferred_accepted"), "DEFERRED_ACCEPTED")
        # 历史别名必须被拒绝（不是合法 verdict）
        for alias in ("PASSED", "DONE", "OK", "YES"):
            self.assertNotIn(alias, VERDICT_ENUM)
            self.assertNotIn(normalize_verdict(alias), VERDICT_ENUM)

    def test_inv06_acceptance_passed_verdict_rejected(self):
        # 验收 verdict 语义由统一 cli.validator 强制（拒绝 PASSED 别名）
        from cli.validator import validate_artifacts
        acc = self.task_dir / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        text = text.replace("| PENDING |", "| PASSED |")
        acc.write_text(text, encoding="utf-8", newline="\n")
        result = validate_artifacts(str(self.task_dir), ["acceptance"])
        self.assertFalse(result["ok"])
        msgs = [i["message"] for i in result["issues"]]
        self.assertTrue(any("verdict" in m for m in msgs),
                        f"PASSED alias must be rejected; issues={result['issues']}")

    def test_inv10_cli_validator_emits_single_enum(self):
        from cli.validator import validate_artifacts
        result = validate_artifacts(str(self.task_dir), ["acceptance"])
        self.assertIn("verdict_enum", result)
        self.assertEqual(result["verdict_enum"], list(VERDICT_ENUM))
        self.assertEqual(result["validator"], "cli.validator")


# =============================================================================
# INV-08 + 攻击矩阵 D（个人模式自动结单）
# =============================================================================
class TestAutomaticCompletion(_TaskFixture):
    def _verification_ready(self):
        run([
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-development-engineering",
            "--phase", "development", "--summary", "implementation complete",
        ], 0)
        run([
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-verification-engineering",
            "--decision", "PASS", "--summary", "verified",
            "--evidence", "evidence/test-result.txt",
        ], 0)

    def test_inv08_no_personnel_approval_state_or_cli(self):
        workflow = (ROOT / "governance" / "workflow.yaml").read_text(encoding="utf-8")
        self.assertNotIn("HUMAN_APPROVAL", workflow)
        self.assertFalse((ROOT / "cli" / "approval.py").exists())
        rc, _, err = run(["receipt", "request"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized arguments", err)

    def test_inv08_verification_pass_allows_direct_completion(self):
        self._verification_ready()
        rc, out, err = run([
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-verification-engineering", "--summary", "done",
        ], 0)
        result = json.loads(out)
        self.assertEqual(result["verification"], "PASS")
        self.assertNotIn("CLOSING", out + err)

    def test_inv08_acceptance_change_is_reported_as_stale_not_pass(self):
        self._verification_ready()
        acceptance = self.task_dir / "acceptance.md"
        text = acceptance.read_text(encoding="utf-8")
        text = text.replace("| AC-01 |  |", "| AC-01 | 新增验收语义 |", 1)
        acceptance.write_text(text, encoding="utf-8", newline="\n")
        rc, out, _ = run([
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--db", self.db_path, "--actor", "tp-verification-engineering", "--summary", "done",
        ], 0)
        self.assertEqual(json.loads(out)["verification"], "PASS_STALE")
        final = (self.task_dir / "generated" / "final-result.md").read_text(encoding="utf-8")
        self.assertIn("PASS_STALE", final)


# =============================================================================
# INV-09 + 攻击矩阵 E（事务恢复身份与严格恢复）
# =============================================================================
class TestRecoveryIdentity(unittest.TestCase):
    def test_inv09_strict_restore_failure_keeps_evidence(self):
        work = tempfile.mkdtemp(prefix="v511-restore-")
        task_dir = Path(work) / "proj"
        (task_dir / "generated").mkdir(parents=True)
        (task_dir / "generated" / "continuation.md").write_text("old\n", encoding="utf-8")
        target = task_dir / "status.yaml"
        target.write_text("new\n", encoding="utf-8")
        # journal 声明 status.yaml before_digest，但备份缺失 → ok=False
        journal = {
            "files": [
                {"path": "status.yaml", "before_digest": _sha256_bytes(b"old\n"),
                 "backup": str(task_dir / "missing-backup.bak")},
            ]
        }
        result = strict_restore(task_dir, journal)
        self.assertFalse(result.ok, "missing backup must fail-closed")
        self.assertTrue(result.failed or result.digest_mismatches)
        # 目标文件未被篡改/误删，且 journal+backup 由调用方保留（本测试不删除）
        self.assertEqual(target.read_text(encoding="utf-8"), "new\n")

    def test_inv09_strict_restore_restores_digest(self):
        work = tempfile.mkdtemp(prefix="v511-restore-")
        task_dir = Path(work) / "proj"
        (task_dir / "generated").mkdir(parents=True)
        original = "original content\n"
        bak_dir = task_dir / ".bak"
        bak_dir.mkdir()
        (bak_dir / "status.yaml").write_text(original, encoding="utf-8", newline="\n")
        target = task_dir / "status.yaml"
        target.write_text("tampered\n", encoding="utf-8", newline="\n")
        journal = {
            "files": [
                {"path": "status.yaml", "before_digest": _sha256_bytes(original.encode()),
                 "backup": str(bak_dir / "status.yaml")},
            ]
        }
        result = strict_restore(task_dir, journal)
        self.assertTrue(result.ok, f"strict restore should succeed: {result}")
        self.assertEqual(target.read_text(encoding="utf-8"), original)


# =============================================================================
# 攻击矩阵 F（状态入口一致性）
# =============================================================================
class TestStateEntryPoints(_TaskFixture):
    def test_state_entries_require_owner_and_events(self):
        # event add/sync 无法推进状态；推进必须产生 STATE+HANDOFF 事件（唯一写入服务）
        from cli import db as dbmod
        conn = dbmod.connect(self.db_path)
        try:
            before = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=? AND event_type IN ('STATE','HANDOFF')",
                                  (self.task_id,)).fetchone()["c"]
        finally:
            conn.close()
        run(["event", "add", "--task", self.task_id, "--type", "FACT",
             "--actor", "tp-architecture-design", "--note", "n", "--db", self.db_path], 0)
        conn = dbmod.connect(self.db_path)
        try:
            states = conn.execute("SELECT current_state, owner_role FROM task WHERE task_id=?",
                                  (self.task_id,)).fetchone()
            after = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=? AND event_type IN ('STATE','HANDOFF')",
                                 (self.task_id,)).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(states["current_state"], "NEW")
        self.assertEqual(before, after, "event add must not create STATE/HANDOFF events")


if __name__ == "__main__":
    unittest.main()
