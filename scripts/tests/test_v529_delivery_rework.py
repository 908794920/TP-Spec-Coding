from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

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
        (task_dir / "evidence/code-review.txt").write_text("Synthetic reviewer evidence for the current subject.\n", encoding="utf-8")
        rc, out, err = self.call(
            "review", "record", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS", "--summary", "reviewed",
            "--evidence", "evidence/code-review.txt",
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

# B16: real CLI/Git fixtures; their reports are synthetic evidence, not business acceptance.
def _b16_runtime(tmp_path, monkeypatch, *, level="L2"):
    from scripts.tests.v532_testutil import make_runtime, run_cli, task_args
    from scripts.tests.test_v529_change_set_binding import make_repo
    front, db, original, _ = make_runtime(tmp_path, monkeypatch)
    tid = "TASK-B16"
    tdir = original.parent / tid
    rc, out, err = run_cli(["task", "create", "--id", tid, "--project", "v532-test",
                           "--risk", level, "--flow", level, "--scaffold", "--task-dir", str(tdir), "--db", str(db)])
    assert rc == 0, (out, err)
    (tdir / "acceptance.md").write_bytes((original / "acceptance.md").read_bytes())
    (tdir / "evidence").mkdir(exist_ok=True)
    (tdir / "evidence/check.txt").write_text("Synthetic B16 technical evidence\n", encoding="utf-8")
    (tdir / "evidence/review.txt").write_text("Synthetic B16 reviewer evidence\n", encoding="utf-8")
    roots = [front, make_repo(tmp_path, "backend"), make_repo(tmp_path, "identity")]
    def call(op, *args):
        return run_cli(task_args(db, tdir, tid, op, *args))
    return roots, db, tdir, tid, call


def _b16_cp(call, roots=()):
    args = ["--actor", "tp-development-engineer", "--phase", "development", "--summary", "bounded batch"]
    for root in roots:
        args += ["--repo-root", str(root)]
    rc, out, err = call("checkpoint", *args)
    assert rc == 0, (out, err)
    return json.loads(out)


def _b16_verify(call, scope="full"):
    args = ["--decision", "PASS", "--summary", "synthetic checked result", "--evidence", "evidence/check.txt"]
    if scope == "technical":
        args += ["--scope", scope, "--check", "selected frontend scenario"]
    return call("verify", *args)


def _b16_review(db, tdir, tid):
    from scripts.tests.v532_testutil import run_cli
    rc, out, err = run_cli(["review", "record", "--task", tid, "--task-dir", str(tdir),
        "--db", str(db), "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS",
        "--summary", "synthetic independent role result", "--evidence", "evidence/review.txt"])
    assert rc == 0, (out, err)


def _b16_rows(db, tid):
    with dbmod.connect_readonly(str(db)) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (tid,))]


def test_b16_local_checkpoint_cannot_become_full_verification(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    (roots[0] / "app.txt").write_text("frontend-only revision\n", encoding="utf-8")
    _b16_cp(call, roots[:1])
    before = _b16_rows(db, tid)
    rc, out, err = _b16_verify(call)
    assert rc != 0 and "FULL_SCOPE_CHECKPOINT_REQUIRED" in err, (out, err)
    assert _b16_rows(db, tid) == before
    rc, out, err = _b16_verify(call, "technical")
    assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    route = orchestration.resolve_route(tid, db_path=str(db), allowed_effects=["repo_mutation"])
    assert route["recommended_action"] == "none"
    assert "FULL_SCOPE_CHECKPOINT_REQUIRED" in route["reason_codes"]
    assert route["role_id"] is None


def test_b16_default_checkpoint_restores_known_full_repository_scope(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    _b16_cp(call, roots[:1])
    _b16_cp(call)
    latest = json.loads([r for r in _b16_rows(db, tid) if r["event_type"] == "FACT"][-1]["detail_json"])
    assert set(latest["repo_roots"]) == set(map(str, roots))
    assert all(r.get("product_digest") for r in latest["change_set"]["repositories"])


def test_b16_plain_scope_note_does_not_discard_previous_repositories(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    rc, out, err = call("scope-change", "--scope-id", "local-detail", "--summary", "Owner clarifies wording only")
    assert rc == 0, (out, err)
    _b16_cp(call, roots[:1])
    rc, out, err = _b16_verify(call)
    assert rc != 0 and "FULL_SCOPE_CHECKPOINT_REQUIRED" in err, (out, err)


def test_b16_owner_explicit_scope_can_exclude_repo_without_rewriting_history(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    before = _b16_rows(db, tid)
    rc, out, err = call("scope-change", "--scope-id", "approved-frontend-only", "--summary",
                       "Owner excludes backend and identity from this delivery", "--repo-root", str(roots[0]))
    assert rc == 0, (out, err)
    # Excluded roots may be unavailable; they must not be scanned after the explicit change.
    for root in roots[1:]:
        for path in root.rglob("*"):
            path.chmod(stat.S_IREAD | stat.S_IWRITE | (stat.S_IEXEC if path.is_dir() else 0))
        shutil.rmtree(root)
    _b16_cp(call)
    rc, out, err = _b16_verify(call)
    assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason",
                       "Current authorized frontend scope is verified and reviewed")
    assert rc == 0, (out, err)
    rc, out, err = call("complete", "--summary", "approved reduced scope complete")
    assert rc == 0, (out, err)
    assert _b16_rows(db, tid)[:len(before)] == before


def test_b16_expanding_scope_invalidates_ready_without_product_change(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots[:1])
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "The selected scope is ready for delivery")
    assert rc == 0, (out, err)
    rc, out, err = call("scope-change", "--scope-id", "include-identity", "--summary",
                       "Owner adds the identity repository to the final scope", "--repo-root", str(roots[0]), "--repo-root", str(roots[2]))
    assert rc == 0, (out, err)
    before = _b16_rows(db, tid)
    rc, out, err = call("complete", "--summary", "cannot reuse earlier READY")
    assert rc != 0, (out, err)
    assert _b16_rows(db, tid) == before


def test_b16_delivery_evidence_corruption_blocks_complete(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots[:1])
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    proof = tdir / "evidence/integration.txt"
    proof.write_text("integration observations for this subject", encoding="utf-8")
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "All applicable delivery evidence checked",
                       "--evidence", "evidence/integration.txt")
    assert rc == 0, (out, err)
    proof.write_text("changed integration outcome", encoding="utf-8")
    before = _b16_rows(db, tid)
    rc, out, err = call("complete", "--summary", "must not ignore damaged delivery proof")
    assert rc != 0, (out, err)
    assert _b16_rows(db, tid) == before


def test_b16_swapped_repository_content_invalidates_verification(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    (roots[1] / "app.txt").write_text("backend distinct content\n", encoding="utf-8")
    _b16_cp(call, roots)
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    a, b = roots[0] / "app.txt", roots[1] / "app.txt"
    old_a, old_b = a.read_bytes(), b.read_bytes()
    a.write_bytes(old_b); b.write_bytes(old_a)
    from scripts.tests.v532_testutil import run_cli
    rc, out, err = run_cli(["review", "record", "--task", tid, "--task-dir", str(tdir), "--db", str(db),
        "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS", "--summary", "must refuse swapped product content",
        "--evidence", "evidence/review.txt"])
    assert rc != 0 and "VERIFICATION_STALE" in err, (out, err)


def test_b16_technical_review_cannot_follow_swapped_content_into_full_delivery(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    (roots[1] / "app.txt").write_text("distinct backend\n", encoding="utf-8")
    _b16_cp(call, roots)
    rc, out, err = _b16_verify(call, "technical"); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    a, b = roots[0] / "app.txt", roots[1] / "app.txt"
    old_a, old_b = a.read_bytes(), b.read_bytes()
    a.write_bytes(old_b); b.write_bytes(old_a)
    _b16_cp(call, roots)
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    before = _b16_rows(db, tid)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "Must not reuse an old mapping via technical supplementation")
    assert rc != 0 and "DELIVERY_CHANGE_SET_MISMATCH" in err, (out, err)
    assert _b16_rows(db, tid) == before
    _b16_review(db, tdir, tid)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "New independent review covers the changed mapping")
    assert rc == 0, (out, err)


def test_b16_developer_cannot_expand_explicit_owner_repository_scope(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    rc, out, err = call("scope-change", "--scope-id", "approved-only-frontend", "--summary", "Owner limits the current delivery to frontend",
                       "--repo-root", str(roots[0]))
    assert rc == 0, (out, err)
    before = _b16_rows(db, tid)
    rc, out, err = call("checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", "unapproved new root",
                       "--repo-root", str(roots[1]))
    assert rc != 0 and "REPOSITORY_SCOPE_MISMATCH" in err, (out, err)
    assert _b16_rows(db, tid) == before


def test_b16_scope_change_makes_prior_technical_review_ineligible_for_reuse(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots[:1])
    rc, out, err = _b16_verify(call, "technical"); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    rc, out, err = call("scope-change", "--scope-id", "updated-delivery-conditions", "--summary", "Owner redefines delivery conditions for the same repository",
                       "--repo-root", str(roots[0]))
    assert rc == 0, (out, err)
    _b16_cp(call)
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "Old review must not cross the owner scope boundary")
    assert rc != 0 and "DELIVERY_CHANGE_SET_MISMATCH" in err, (out, err)


def test_b16_full_scope_missing_result_waits_instead_of_dispatching_failing_verify(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    _b16_cp(call, roots[:1])
    route = orchestration.resolve_route(tid, db_path=str(db), allowed_effects=["repo_mutation"])
    # No verification yet: a limited technical route is valid, provided it says so.
    assert (route["recommended_action"] == "none" and "FULL_SCOPE_CHECKPOINT_REQUIRED" in route["reason_codes"]
            or route.get("context", {}).get("validation", {}).get("verification_scope") == "technical"), route


def test_b16_l0_local_scope_cannot_complete_even_with_technical_pass(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch, level="L0")
    _b16_cp(call, roots)
    _b16_cp(call, roots[:1])
    rc, out, err = _b16_verify(call, "technical"); assert rc == 0, (out, err)
    rc, out, err = call("complete", "--summary", "local evidence is not complete task coverage")
    assert rc != 0 and "FULL_SCOPE_CHECKPOINT_REQUIRED" in err, (out, err)


def test_b16_three_repo_final_scope_detects_later_backend_change(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    _b16_cp(call, roots[:1])
    _b16_cp(call)
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "All three repositories have current verification and review")
    assert rc == 0, (out, err)
    before = _b16_rows(db, tid)
    (roots[1] / "app.txt").write_text("changed after integration\n", encoding="utf-8")
    rc, out, err = call("complete", "--summary", "must re-evaluate changed backend")
    assert rc != 0 and "CHANGE_SET_STALE" in err, (out, err)
    assert _b16_rows(db, tid) == before


def test_b16_invalid_latest_delivery_does_not_reactivate_earlier_ready(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots[:1])
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    for reason in ("First integration result is valid for this scope", "Second integration result supersedes the earlier outcome"):
        rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", reason)
        assert rc == 0, (out, err)
    # Fault injection confined to the synthetic DB; no production/history repair.
    with dbmod.connect(str(db)) as conn:
        row = conn.execute("SELECT id,detail_json FROM task_event WHERE task_id=? AND event_type='DELIVERY_RESULT' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
        detail = json.loads(row["detail_json"]); detail.pop("review_event_id")
        conn.execute("UPDATE task_event SET detail_json=? WHERE id=?", (json.dumps(detail), row["id"])); conn.commit()
    rc, out, err = call("complete", "--summary", "do not select an older READY around corrupt latest result")
    assert rc != 0, (out, err)


def test_b16_scope_changed_requires_new_checkpoint_before_technical_pass(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    rc, out, err = call("scope-change", "--scope-id", "approved-reduction", "--summary", "Owner removes backend and identity",
                       "--repo-root", str(roots[0]))
    assert rc == 0, (out, err)
    before = _b16_rows(db, tid)
    rc, out, err = _b16_verify(call, "technical")
    assert rc != 0 and "SCOPE_CHECKPOINT_REQUIRED" in err, (out, err)
    assert _b16_rows(db, tid) == before


def test_b16_projection_marks_repository_swap_stale(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    (roots[1] / "app.txt").write_text("backend distinct\n", encoding="utf-8")
    _b16_cp(call, roots)
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    a, b = roots[0] / "app.txt", roots[1] / "app.txt"
    av, bv = a.read_bytes(), b.read_bytes(); a.write_bytes(bv); b.write_bytes(av)
    from cli import projection_cmd
    with dbmod.connect_readonly(str(db)) as conn:
        quality = projection_cmd._extract_quality_facts(conn, tid)
    assert quality["development"] == "STALE", quality
    assert quality["verification"] == "PASS_STALE", quality
    assert quality["review"] == "PASS_STALE", quality


def test_b16_projection_does_not_show_ready_with_corrupted_delivery_proof(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots[:1]); rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    (tdir / "evidence/integration.txt").write_text("original integration", encoding="utf-8")
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "Integration evidence collected for this subject", "--evidence", "evidence/integration.txt")
    assert rc == 0, (out, err)
    (tdir / "evidence/integration.txt").unlink()
    from cli import projection_cmd
    with dbmod.connect_readonly(str(db)) as conn:
        quality = projection_cmd._extract_quality_facts(conn, tid)
    assert quality["delivery"] != "READY", quality



@pytest.mark.parametrize("operation", ["verify", "delivery-converge", "complete"])
def test_b16_multirepo_changes_at_commit_boundary_are_rejected(tmp_path, monkeypatch, operation):
    from cli import transaction_commit
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    rc, out, err = _b16_verify(call); assert rc == 0, (out, err)
    _b16_review(db, tdir, tid)
    rc, out, err = call("delivery-converge", "--delivery-status", "READY", "--reason", "Final scope preflight is ready")
    assert rc == 0, (out, err)
    before = _b16_rows(db, tid)
    original = transaction_commit._commit_with_recovery
    def change_after_preflight(*args, **kwargs):
        (roots[2] / "app.txt").write_text("identity changed after preflight\n", encoding="utf-8")
        return original(*args, **kwargs)
    monkeypatch.setattr(transaction_commit, "_commit_with_recovery", change_after_preflight)
    if operation == "verify":
        rc, out, err = _b16_verify(call)
    elif operation == "delivery-converge":
        rc, out, err = call(operation, "--delivery-status", "READY", "--reason", "Must reject changed identity after preflight")
    else:
        rc, out, err = call(operation, "--summary", "Must reject changed identity after preflight")
    assert rc != 0, (out, err)
    assert _b16_rows(db, tid) == before
    assert (roots[2] / "app.txt").read_text() == "identity changed after preflight\n"

@pytest.mark.parametrize("when", ["before", "during"])
def test_b16_executor_does_not_report_same_subject_for_repository_swap(tmp_path, monkeypatch, when):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    (roots[1] / 'app.txt').write_text('distinct backend\n', encoding='utf-8')
    a, b = roots[0] / 'app.txt', roots[1] / 'app.txt'
    body = ('from pathlib import Path\ndef test_swap():\n'
            f'    a,b = Path({str(a)!r}),Path({str(b)!r})\n'
            '    av,bv = a.read_bytes(),b.read_bytes()\n'
            '    a.write_bytes(bv); b.write_bytes(av)\n') if when == 'during' else 'def test_swap():\n    assert True\n'
    (roots[2] / 'test_swap.py').write_text(body, encoding='utf-8')
    (tdir / 'evidence/authorization.txt').write_text('Synthetic authorization for selected test on owned fixture only.', encoding='utf-8')
    _b16_cp(call, roots)
    if when == 'before':
        av, bv = a.read_bytes(), b.read_bytes(); a.write_bytes(bv); b.write_bytes(av)
    rc, out, err = call('run-pytest', '--repo-root', str(roots[2]), '--test', 'test_swap.py',
                       '--authorization-evidence', 'evidence/authorization.txt', '--request-id', 'bound-swap', '--summary', 'Synthetic bound subject test')
    if when == 'before':
        assert rc != 0 and 'DEVELOPMENT_CHANGE_SET_STALE' in err, (out, err)
    else:
        assert rc == 0, (out, err)
        result = json.loads(out)
        assert result['execution']['change_set_before'] == result['execution']['change_set_after']
        assert result['execution']['subject_unchanged'] is False, result
        assert result['formal_verification_created'] is False


@pytest.mark.parametrize('broken', ['not-a-map', ['repositories'], 1])
def test_b16_bound_content_malformed_snapshot_is_unusable(tmp_path, broken):
    from cli.change_set import capture_change_set, same_bound_product_content
    from scripts.tests.test_v529_change_set_binding import make_repo
    repo = make_repo(tmp_path)
    current = capture_change_set([repo])
    detail = {'change_set_id': current['content_digest'], 'repo_roots': [str(repo)], 'change_set': broken}
    assert same_bound_product_content(detail, current) is False


def test_b16_legacy_multirepo_requires_new_evidence_but_single_repo_still_valid(tmp_path):
    from cli.change_set import capture_change_set, same_bound_product_content
    from cli.record_first import _compact_change_set
    from scripts.tests.test_v529_change_set_binding import make_repo
    (tmp_path / 'a').mkdir(); (tmp_path / 'b').mkdir()
    a = make_repo(tmp_path / 'a'); b = make_repo(tmp_path / 'b')
    for roots in ([a], [a,b]):
        current = capture_change_set(roots)
        detail = {'change_set_id': current['content_digest'], 'repo_roots': list(map(str,roots)), 'change_set': _compact_change_set(current)}
        assert same_bound_product_content(detail, current)
        for repo in detail['change_set']['repositories']:
            repo.pop('product_digest')
        assert same_bound_product_content(detail, current) is (len(roots) == 1)


@pytest.mark.parametrize('damage', ['unreadable', 'invalid-snapshot'])
def test_b16_corrupt_earlier_development_cannot_silently_shrink_scope(tmp_path, monkeypatch, damage):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots); _b16_cp(call, roots[:1])
    with dbmod.connect(str(db)) as conn:
        row = conn.execute("SELECT id,detail_json FROM task_event WHERE task_id=? AND event_type='FACT' ORDER BY id LIMIT 1", (tid,)).fetchone()
        detail = json.loads(row['detail_json']); detail['change_set'] = 1
        payload = '{' if damage == 'unreadable' else json.dumps(detail)
        conn.execute('UPDATE task_event SET detail_json=? WHERE id=?', (payload,row['id'])); conn.commit()
    before = _b16_rows(db, tid)
    rc, out, err = _b16_verify(call)
    assert rc != 0 and 'DELIVERY_SCOPE_INVALID' in err, (out,err)
    assert _b16_rows(db, tid) == before


def test_b16_scope_changed_route_does_not_dispatch_known_failing_verification(tmp_path, monkeypatch):
    roots, db, tdir, tid, call = _b16_runtime(tmp_path, monkeypatch)
    _b16_cp(call, roots)
    rc,out,err = call('scope-change', '--scope-id','owner-scope','--summary','New authorized scope includes frontend only', '--repo-root',str(roots[0]))
    assert rc == 0, (out,err)
    route = orchestration.resolve_route(tid, db_path=str(db), allowed_effects=['repo_mutation'])
    assert route['recommended_action'] == 'none', route
    assert 'FULL_SCOPE_CHECKPOINT_REQUIRED' in route['reason_codes'], route
