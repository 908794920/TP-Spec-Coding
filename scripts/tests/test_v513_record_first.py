# -*- coding: utf-8 -*-
"""V5.1.3 Record-first acceptance regressions.

These are the active product invariants. Historical test files may continue to
exercise compatibility/recovery surfaces, but they must not re-introduce the
old governance-first daily workflow.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from cli import db as dbmod
from cli import main as climain
from cli import event_policies
from cli.version import active_version


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class RecordFirstCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v513-record-first-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / "project"
        self.db = self.project / ".tp-spec" / "db" / "demo.db"
        self.registry = self.root / "registry.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project),
            "--registry", str(self.registry),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.task_id = "TASK-V513-RECORD-FIRST"
        self.task_dir = self.project / ".tp-spec" / "tasks" / self.task_id
        rc, out, err = run([
            "task", "create", "--id", self.task_id, "--project", "demo",
            "--risk", "L0", "--flow", "L0", "--db", str(self.db),
            "--scaffold", "--task-dir", str(self.task_dir),
        ])
        self.assertEqual(rc, 0, (out, err))

    def call(self, *args):
        return run(list(args) + ["--db", str(self.db)])

    def events(self):
        conn = dbmod.connect(str(self.db))
        try:
            return conn.execute(
                "SELECT * FROM task_event WHERE task_id=? ORDER BY id", (self.task_id,)
            ).fetchall()
        finally:
            conn.close()

    def task(self):
        conn = dbmod.connect(str(self.db))
        try:
            return conn.execute("SELECT * FROM task WHERE task_id=?", (self.task_id,)).fetchone()
        finally:
            conn.close()

    def test_public_workflow_is_small_and_phases_are_facts(self):
        wf = yaml.safe_load((Path(__file__).parents[2] / "governance" / "workflow.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(wf["states"]), {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"})
        for level in ("L0", "L1", "L2", "L3"):
            self.assertEqual([x["state"] for x in wf["levels"][level]["flow"]], ["NEW", "ACTIVE", "COMPLETED"])
        self.assertEqual(wf["rules"]["architecture_review"]["default"], "optional")

    def test_scaffold_contains_only_core_business_files(self):
        root_files = {p.name for p in self.task_dir.iterdir() if p.is_file()}
        self.assertTrue({"task.md", "acceptance.md", "status.yaml", "events.jsonl"}.issubset(root_files))
        for absent in ("implementation.md", "architecture-review.md", "codex-review.md", "quality-and-knowledge.md", "handoff.json"):
            self.assertNotIn(absent, root_files)

    def test_checkpoint_auto_activates_and_phase_changes_without_handoff_noise(self):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-software-architect", "--phase", "architecture", "--summary", "设计完成",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--summary", "开发完成",
        )
        self.assertEqual(rc, 0, (out, err))
        task = self.task()
        self.assertEqual(task["current_state"], "ACTIVE")
        self.assertEqual(task["current_stage"], "development")
        types = [e["event_type"] for e in self.events()]
        self.assertEqual(types.count("HANDOFF"), 0)
        self.assertEqual(types.count("PHASE_EXIT"), 0)
        self.assertEqual(types.count("ARTIFACT_REFRESH"), 0)
        self.assertEqual(types.count("FACT"), 2)

    def test_block_is_real_and_must_resume_before_complete(self):
        rc, out, err = self.call(
            "task", "block", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--reason", "等待用户提供测试账号",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--summary", "完成",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("explicit task blocker", err)
        rc, out, err = self.call(
            "task", "resume", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--summary", "账号已提供",
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(self.task()["current_state"], "ACTIVE")

    def test_verification_pass_requires_real_evidence(self):
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "测试通过",
        )
        self.assertNotEqual(rc, 0)
        evidence = self.task_dir / "evidence" / "test.txt"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text("pytest: pass\n", encoding="utf-8")
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "测试通过",
            "--evidence", "evidence/test.txt",
        )
        self.assertEqual(rc, 0, (out, err))
        ev = [e for e in self.events() if e["event_type"] == "VERIFICATION_COMPLETED"][-1]
        detail = json.loads(ev["detail_json"])
        self.assertEqual(detail["decision"], "PASS")
        self.assertTrue(detail["transaction_id"])
        self.assertTrue(detail["subject_digest"])
        self.assertEqual(detail["producer"], "record-first")
        self.assertTrue(event_policies.event_allowed_for_producer("VERIFICATION_COMPLETED", "record-first"))

    def test_complete_is_truthful_even_without_verification(self):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--summary", "实现完成",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--summary", "任务结束",
        )
        self.assertEqual(rc, 0, (out, err))
        final = (self.task_dir / "generated" / "final-result.md").read_text(encoding="utf-8")
        self.assertIn("NOT_RECORDED", final)
        self.assertIn("不代表", final)
        self.assertIn("PASS", final)
        types = [e["event_type"] for e in self.events()]
        self.assertNotIn("CLOSING", [e["to_state"] for e in self.events() if e["event_type"] == "STATE"])
        self.assertNotIn("HANDOFF", types)
        self.assertNotIn("ARTIFACT_REFRESH", types)

    def test_complete_after_pass_reports_pass(self):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--summary", "implemented",
        )
        self.assertEqual(rc, 0, (out, err))
        evidence = self.task_dir / "evidence" / "test.txt"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text("pass\n", encoding="utf-8")
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "verified",
            "--evidence", "evidence/test.txt",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-test-engineer", "--summary", "done",
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("PASS", (self.task_dir / "generated" / "final-result.md").read_text(encoding="utf-8"))

    def test_record_first_validator_ignores_optional_artifact_absence(self):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--summary", "working",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "validate", "--task", self.task_id, "--task-dir", str(self.task_dir),
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("Task validate OK", out)

    def test_simple_verified_flow_has_small_event_budget(self):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development", "--summary", "implemented",
        )
        self.assertEqual(rc, 0, (out, err))
        evidence = self.task_dir / "evidence" / "test.txt"; evidence.parent.mkdir(exist_ok=True); evidence.write_text("pass", encoding="utf-8")
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "verified",
            "--evidence", "evidence/test.txt",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-test-engineer", "--summary", "done",
        )
        self.assertEqual(rc, 0, (out, err))
        events = self.events()
        # Includes the initial NEW state written at task creation.
        self.assertLessEqual(len(events), 6)
        forbidden = {"HANDOFF", "PHASE_EXIT", "ARTIFACT_REFRESH"}
        self.assertFalse(forbidden.intersection({e["event_type"] for e in events}))


class TestRecordFirstStaticContracts(unittest.TestCase):
    def test_runtime_owns_bookkeeping(self):
        base = Path(__file__).parents[2]
        api = yaml.safe_load((base / "governance" / "runtime-api.yaml").read_text(encoding="utf-8"))
        self.assertEqual(api["mode"], "record-first")
        self.assertIn("commit --refresh", api["do_not_use_in_normal_role_flow"])
        self.assertIn("hand-authored stage_handoff / intended_next / next_prompt", api["do_not_use_in_normal_role_flow"])
        self.assertIn("work_sessions", api["optional_capabilities"])

    def test_optional_templates_have_no_stage_handoff(self):
        base = Path(__file__).parents[2] / "templates" / active_version()
        for name in (
            "requirement.md", "requirement-clarifications.md", "requirement-decisions.md",
            "architecture-review.md", "implementation.md", "requirement-test-guide.md",
            "codex-review.md", "quality-and-knowledge.md",
        ):
            self.assertNotIn("stage_handoff", (base / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
