from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tests.runtime_testutil import run
from cli import db as dbmod
from cli import event_contract
from cli import orchestration


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return cp.stdout.strip()


class V529ChangeSetWorkflowCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v529-change-set-flow-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / "project"
        self.registry = self.root / "registry.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        self.user_root = self.root / "user"
        self.env = patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(self.user_root)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project),
            "--registry", str(self.registry),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.db = self.project / ".tp-spec" / "db" / "demo.db"
        git(self.project, "init", "-q")
        git(self.project, "config", "user.name", "test")
        git(self.project, "config", "user.email", "test@example.com")
        (self.project / "src").mkdir()
        (self.project / "src" / "app.txt").write_text("v1\n", encoding="utf-8")
        git(self.project, "add", "src/app.txt")
        git(self.project, "commit", "-qm", "baseline")

    def call(self, *args):
        return run(list(args) + ["--db", str(self.db)])

    def create_task(self, task_id: str) -> Path:
        task_dir = self.project / ".tp-spec" / "tasks" / task_id
        rc, out, err = self.call(
            "task", "create", "--id", task_id, "--project", "demo", "--risk", "L2", "--flow", "L2",
            "--scaffold", "--task-dir", str(task_dir),
        )
        self.assertEqual(rc, 0, (out, err))
        return task_dir

    def checkpoint(self, task_id: str, task_dir: Path, actor: str, phase: str, *, repo: bool = False):
        args = [
            "task", "checkpoint", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", actor, "--phase", phase, "--summary", f"{phase} done",
        ]
        if repo:
            args += ["--repo-root", str(self.project)]
        rc, out, err = self.call(*args)
        self.assertEqual(rc, 0, (out, err))
        return json.loads(out)

    def prepare_development(self, task_id: str, task_dir: Path):
        self.checkpoint(task_id, task_dir, "tp-product-manager", "requirement")
        self.checkpoint(task_id, task_dir, "tp-software-architect", "architecture")
        self.checkpoint(task_id, task_dir, "tp-tech-lead", "planning")
        rc, out, err = self.call("workflow", "confirm", "--task", task_id, "--task-dir", str(task_dir), "--json")
        self.assertEqual(rc, 0, (out, err))
        return self.checkpoint(task_id, task_dir, "tp-development-engineer", "development", repo=True)

    def verify(self, task_id: str, task_dir: Path):
        evidence = task_dir / "evidence" / "verification.txt"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text("verified\n", encoding="utf-8")
        rc, out, err = self.call(
            "task", "verify", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "verified",
            "--evidence", "evidence/verification.txt",
        )
        self.assertEqual(rc, 0, (out, err))
        return json.loads(out)

    def review(self, task_id: str, task_dir: Path):
        rc, out, err = self.call(
            "review", "record", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS", "--summary", "reviewed",
        )
        self.assertEqual(rc, 0, (out, err))
        return out

    def latest_detail(self, task_id: str, event_type: str) -> dict:
        conn = dbmod.connect(str(self.db))
        try:
            row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type=? ORDER BY id DESC LIMIT 1",
                (task_id, event_type),
            ).fetchone()
            self.assertIsNotNone(row)
            return json.loads(row["detail_json"])
        finally:
            conn.close()

    def test_development_verification_and_review_bind_same_change_set(self):
        task_id = "TASK-V529-BIND"
        task_dir = self.create_task(task_id)
        development = self.prepare_development(task_id, task_dir)
        self.assertTrue(development["change_set_id"].startswith("sha256:"))
        verification = self.verify(task_id, task_dir)
        self.review(task_id, task_dir)
        verify_detail = self.latest_detail(task_id, "VERIFICATION_COMPLETED")
        review_detail = self.latest_detail(task_id, "REVIEW_COMPLETED")
        self.assertEqual(verification["change_set_id"], development["change_set_id"])
        self.assertEqual(verify_detail["change_set_id"], development["change_set_id"])
        self.assertEqual(review_detail["change_set_id"], development["change_set_id"])

    def test_repo_mutation_after_review_routes_to_development(self):
        task_id = "TASK-V529-STALE"
        task_dir = self.create_task(task_id)
        self.prepare_development(task_id, task_dir)
        self.verify(task_id, task_dir)
        self.review(task_id, task_dir)
        (self.project / "src" / "app.txt").write_text("v2\n", encoding="utf-8")

        route = orchestration.resolve_route(task_id, db_path=str(self.db), allowed_effects=["repo_mutation"])

        self.assertEqual(route["next_stage"], "development")
        self.assertIn("CHANGE_SET_STALE", route["reason_codes"])

    def test_history_only_commit_does_not_invalidate_verified_content(self):
        task_id = "TASK-V529-HISTORY"
        task_dir = self.create_task(task_id)
        self.prepare_development(task_id, task_dir)
        self.verify(task_id, task_dir)
        self.review(task_id, task_dir)
        git(self.project, "commit", "--allow-empty", "-qm", "history only")

        route = orchestration.resolve_route(task_id, db_path=str(self.db), allowed_effects=["repo_mutation"])

        self.assertEqual(route["next_stage"], "delivery")

    def test_code_review_rejects_stale_verification(self):
        task_id = "TASK-V529-REVIEW-STALE"
        task_dir = self.create_task(task_id)
        self.prepare_development(task_id, task_dir)
        self.verify(task_id, task_dir)
        (self.project / "src" / "app.txt").write_text("v2\n", encoding="utf-8")

        rc, out, err = self.call(
            "review", "record", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS", "--summary", "reviewed",
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("VERIFICATION_STALE", err)

    def test_delivery_rejects_mismatched_current_change_set(self):
        task_id = "TASK-V529-DELIVERY-STALE"
        task_dir = self.create_task(task_id)
        self.prepare_development(task_id, task_dir)
        self.verify(task_id, task_dir)
        self.review(task_id, task_dir)
        (self.project / "src" / "app.txt").write_text("v2\n", encoding="utf-8")

        rc, out, err = self.call(
            "task", "delivery-converge", "--task", task_id, "--task-dir", str(task_dir),
            "--delivery-status", "READY",
            "--reason", "Verified and reviewed change is ready for integration without blockers.",
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("DELIVERY_CHANGE_SET_MISMATCH", err)

    def test_reverification_requires_fresh_code_review_before_delivery(self):
        task_id = "TASK-V529-REVERIFY"
        task_dir = self.create_task(task_id)
        self.prepare_development(task_id, task_dir)
        self.verify(task_id, task_dir)
        self.review(task_id, task_dir)

        # 产品内容未变化，但新的 Verification 已替代旧结果；旧 Review 不得继续支撑 Delivery。
        self.verify(task_id, task_dir)

        route = orchestration.resolve_route(task_id, db_path=str(self.db), allowed_effects=["repo_mutation"])
        self.assertEqual(route["next_stage"], "review")
        self.assertEqual(route["role_id"], "tp-code-reviewer")

        rc, out, err = self.call(
            "task", "delivery-converge", "--task", task_id, "--task-dir", str(task_dir),
            "--delivery-status", "READY",
            "--reason", "Verified and reviewed change is ready for integration without blockers.",
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("DELIVERY_CHANGE_SET_MISMATCH", err)

        # 新 Verification 之后必须产生新的 Code Review；刷新后才重新进入 Delivery。
        self.review(task_id, task_dir)
        refreshed = orchestration.resolve_route(
            task_id, db_path=str(self.db), allowed_effects=["repo_mutation"]
        )
        self.assertEqual(refreshed["next_stage"], "delivery")


class V529CodeReviewSemanticContractCase(unittest.TestCase):
    def test_code_review_requires_change_set_and_verification_binding(self):
        detail = {
            "schema": event_contract.EVENT_SCHEMA,
            "operation": "REVIEW",
            "review_kind": "CODE",
            "decision": "PASS",
            "result_status": "COMPLETED",
        }

        errors = event_contract.validate_event_semantics("REVIEW_COMPLETED", detail)

        self.assertIn("REVIEW_COMPLETED requires change_set_id", errors)
        self.assertIn("REVIEW_COMPLETED requires verification_event_id", errors)

    def test_architecture_review_does_not_require_code_change_set(self):
        detail = {
            "schema": event_contract.EVENT_SCHEMA,
            "operation": "REVIEW",
            "review_kind": "ARCHITECTURE",
            "decision": "PASS",
            "result_status": "COMPLETED",
        }

        errors = event_contract.validate_event_semantics("REVIEW_COMPLETED", detail)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
