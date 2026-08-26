# -*- coding: utf-8 -*-
"""V5.2.7 temporary artifact and work-session hardening regressions."""
from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli import main as climain
from cli import temp_artifacts


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class TempArtifactUnitCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v526-temp-artifacts-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.user_root = self.root / "user" / ".tp-spec"
        self.temp_root = self.root / "系统 Temp 空格 [符号] #1"
        self.env = mock.patch.dict(
            os.environ,
            {
                "TP_SPEC_USER_ROOT": str(self.user_root),
                "TP_SPEC_TEMP_ROOT": str(self.temp_root),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def create(self, *, run_id="WORK-ABC123", task_id="TASK-TEMP-1"):
        return temp_artifacts.create_run_root(
            project_id="demo",
            task_id=task_id,
            creator_role="tp-test-engineer",
            creator_agent="agent-a",
            run_id=run_id,
        )

    def test_create_run_root_uses_system_temp_and_persists_ownership_manifest(self):
        rec = self.create()
        root = Path(rec["root_path"])
        self.assertTrue(root.is_dir())
        self.assertEqual(root, self.temp_root / "tp-spec" / "demo" / "TASK-TEMP-1" / "WORK-ABC123")
        self.assertNotIn(".tmp", root.parts)
        manifest = Path(rec["manifest_path"])
        self.assertTrue(manifest.is_file())
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "ACTIVE")
        self.assertEqual(saved["project_id"], "demo")
        self.assertEqual(saved["task_id"], "TASK-TEMP-1")
        self.assertEqual(saved["run_id"], "WORK-ABC123")
        self.assertEqual(saved["creator_role"], "tp-test-engineer")
        self.assertEqual(saved["creator_agent"], "agent-a")

    def test_cleanup_is_idempotent_and_never_touches_source_outside_owned_root(self):
        source = self.root / "用户原始 输入.xlsx"
        source.write_text("original", encoding="utf-8")
        rec = self.create()
        owned = Path(rec["root_path"])
        (owned / "fixture.xlsx").write_text("copy", encoding="utf-8")

        first = temp_artifacts.cleanup_run(project_id="demo", task_id="TASK-TEMP-1", run_id="WORK-ABC123")
        second = temp_artifacts.cleanup_run(project_id="demo", task_id="TASK-TEMP-1", run_id="WORK-ABC123")

        self.assertEqual(first["status"], "CLEANED")
        self.assertEqual(second["status"], "CLEANED")
        self.assertFalse(owned.exists())
        self.assertEqual(source.read_text(encoding="utf-8"), "original")

    def test_cleanup_unlinks_nested_symlink_without_following_external_target(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unsupported")
        outside = self.root / "用户重要数据"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        rec = self.create()
        owned = Path(rec["root_path"])
        link = owned / "external-link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")

        result = temp_artifacts.cleanup_run(project_id="demo", task_id="TASK-TEMP-1", run_id="WORK-ABC123")

        self.assertEqual(result["status"], "CLEANED")
        self.assertTrue(sentinel.is_file())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_tampered_manifest_path_outside_controlled_temp_fails_closed(self):
        rec = self.create()
        manifest = Path(rec["manifest_path"])
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        outside = self.root / "do-not-delete"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        payload["root_path"] = str(outside)
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = temp_artifacts.cleanup_run(project_id="demo", task_id="TASK-TEMP-1", run_id="WORK-ABC123")

        self.assertEqual(result["status"], "CLEANUP_PENDING")
        self.assertIn("owned root mismatch", result["error"])
        self.assertTrue(sentinel.is_file())

    def test_existing_run_id_cannot_be_reused_by_a_different_owner(self):
        self.create(run_id="WORK-SHARED")
        with self.assertRaises(ValueError):
            temp_artifacts.create_run_root(
                project_id="demo", task_id="TASK-TEMP-1",
                creator_role="tp-code-reviewer", creator_agent="agent-b",
                run_id="WORK-SHARED",
            )

    def test_parent_symlink_escape_is_rejected_before_owned_root_creation(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unsupported")
        base = self.temp_root / "tp-spec"
        base.mkdir(parents=True)
        outside = self.root / "outside-project"
        outside.mkdir()
        try:
            os.symlink(outside, base / "demo", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")

        with self.assertRaises(ValueError):
            self.create(run_id="RUN-ESCAPE")
        self.assertFalse((outside / "TASK-TEMP-1" / "RUN-ESCAPE").exists())

    def test_two_distinct_runs_are_isolated(self):
        first = self.create(run_id="RUN-ONE")
        second = self.create(run_id="RUN-TWO")
        self.assertNotEqual(first["root_path"], second["root_path"])
        Path(first["root_path"], "one.txt").write_text("one", encoding="utf-8")
        Path(second["root_path"], "two.txt").write_text("two", encoding="utf-8")
        temp_artifacts.cleanup_run(project_id="demo", task_id="TASK-TEMP-1", run_id="RUN-ONE")
        self.assertFalse(Path(first["root_path"]).exists())
        self.assertTrue(Path(second["root_path"]).is_dir())


    def test_invalid_identity_rejects_path_traversal_before_creating_any_temp_path(self):
        with self.assertRaises(ValueError):
            temp_artifacts.create_run_root(
                project_id="demo", task_id="TASK-TEMP-1", creator_role="tp-test-engineer",
                run_id="../escape",
            )
        self.assertFalse((self.temp_root / "tp-spec" / "escape").exists())

    def test_cleanup_of_missing_owned_root_is_idempotently_marked_cleaned(self):
        rec = self.create(run_id="RUN-MISSING")
        shutil.rmtree(Path(rec["root_path"]))

        result = temp_artifacts.cleanup_run(
            project_id="demo", task_id="TASK-TEMP-1", run_id="RUN-MISSING",
        )

        self.assertEqual(result["status"], "CLEANED")
        saved = json.loads(Path(rec["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "CLEANED")

    def test_reparse_attribute_is_detected_without_following_target(self):
        fake = mock.Mock(st_file_attributes=0x400)
        self.assertTrue(temp_artifacts._is_reparse_stat(fake))



    def test_corrupt_manifest_is_reported_pending_for_its_task_and_never_auto_deleted(self):
        rec = self.create(run_id="RUN-CORRUPT")
        manifest = Path(rec["manifest_path"])
        root = Path(rec["root_path"])
        manifest.write_text("{broken-json", encoding="utf-8")

        summary = temp_artifacts.cleanup_task(project_id="demo", task_id="TASK-TEMP-1")
        report = temp_artifacts.orphan_report(project_id="demo", task_id="TASK-TEMP-1")

        self.assertEqual(summary["pending"], 1)
        self.assertTrue(root.is_dir())
        self.assertEqual(len(report["owned_candidates"]), 1)
        self.assertEqual(report["owned_candidates"][0]["classification"], "CLEANUP_PENDING")
        self.assertEqual(report["auto_deleted"], 0)

    def test_concurrent_runs_for_same_task_do_not_race_on_shared_parent_creation(self):
        run_ids = [f"RUN-CONCURRENT-{i:02d}" for i in range(16)]

        def create_one(run_id):
            return temp_artifacts.create_run_root(
                project_id="demo", task_id="TASK-CONCURRENT", creator_role="tp-test-engineer",
                creator_agent=run_id, run_id=run_id,
            )

        with ThreadPoolExecutor(max_workers=16) as pool:
            records = list(pool.map(create_one, run_ids))

        self.assertEqual({Path(row["root_path"]).name for row in records}, set(run_ids))
        self.assertTrue(all(Path(row["root_path"]).is_dir() for row in records))

    def test_registered_root_replaced_by_symlink_is_rejected_on_reuse(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unsupported")
        rec = self.create(run_id="RUN-ROOT-LINK")
        root = Path(rec["root_path"])
        shutil.rmtree(root)
        outside = self.root / "outside-root"
        outside.mkdir()
        try:
            os.symlink(outside, root, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")

        with self.assertRaises(ValueError):
            self.create(run_id="RUN-ROOT-LINK")
        self.assertTrue(outside.is_dir())



class TempArtifactCliCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v526-temp-cli-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.user_root = self.root / "user" / ".tp-spec"
        self.temp_root = self.root / "system-temp"
        self.env = mock.patch.dict(
            os.environ,
            {
                "TP_SPEC_USER_ROOT": str(self.user_root),
                "TP_SPEC_TEMP_ROOT": str(self.temp_root),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.registry = self.root / "registry.local.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        self.project = self.root / "project"
        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project),
            "--registry", str(self.registry),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.db = self.project / ".tp-spec" / "db" / "demo.db"
        self.task_id = "TASK-TEMP-CLI"
        self.task_dir = self.project / ".tp-spec" / "tasks" / self.task_id
        rc, out, err = run([
            "task", "create", "--id", self.task_id, "--project", "demo",
            "--risk", "L0", "--flow", "L0", "--db", str(self.db),
            "--scaffold", "--task-dir", str(self.task_dir),
        ])
        self.assertEqual(rc, 0, (out, err))

    def test_execution_temp_uses_owned_system_temp_instead_of_workspace(self):
        rc, out, err = run([
            "work", "start", "--task", self.task_id, "--role", "tp-test-engineer",
            "--db", str(self.db),
        ])
        self.assertEqual(rc, 0, (out, err))
        import re
        match = re.search(r"session_id=([A-Za-z0-9._-]+)", out)
        self.assertIsNotNone(match)
        session_id = match.group(1)

        legacy_execution = self.project / ".tp-spec" / ".execution"
        before_legacy = sorted(str(p.relative_to(legacy_execution)) for p in legacy_execution.rglob("*"))
        rc, out, err = run([
            "task", "artifact-path", "--task-dir", str(self.task_dir),
            "--kind", "execution-temp", "--task", self.task_id,
            "--project", "demo", "--role", "tp-test-engineer",
            "--run-id", session_id, "--db", str(self.db), "--ensure",
        ])

        self.assertEqual(rc, 0, (out, err))
        path = Path(out.strip())
        self.assertTrue(path.is_dir())
        self.assertTrue(str(path).startswith(str(self.temp_root / "tp-spec")))
        self.assertFalse((self.project / ".tmp").exists())
        after_legacy = sorted(str(p.relative_to(legacy_execution)) for p in legacy_execution.rglob("*"))
        self.assertEqual(after_legacy, before_legacy)

    def test_execution_temp_without_formal_project_identity_fails_closed(self):
        orphan_workspace = self.root / "unbound"
        task_dir = orphan_workspace / ".tp-spec" / "tasks" / "TASK-UNBOUND"
        task_dir.mkdir(parents=True)

        rc, out, err = run([
            "task", "artifact-path", "--task-dir", str(task_dir),
            "--kind", "execution-temp", "--task", "TASK-UNBOUND",
            "--role", "tp-test-engineer", "--ensure",
        ])

        self.assertNotEqual(rc, 0)
        self.assertIn("project identity", err.lower())
        self.assertFalse((self.temp_root / "tp-spec").exists())

    def test_temp_orphan_check_reports_workspace_tmp_without_deleting_it(self):
        legacy = self.project / ".tmp" / "sensitive-photo-fixture-20260825"
        legacy.mkdir(parents=True)
        sentinel = legacy / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        rc, out, err = run([
            "temp", "orphan-check", "--workspace-root", str(self.project), "--json",
        ])

        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        self.assertEqual(payload["auto_deleted"], 0)
        self.assertTrue(any(item["path"] == str(legacy) for item in payload["unmanaged_candidates"]))
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_temp_create_summary_and_explicit_cleanup_are_machine_local(self):
        rc, out, err = run([
            "temp", "create", "--project", "demo", "--task", self.task_id,
            "--role", "tp-test-engineer", "--run-id", "RUN-MANUAL-1",
            "--db", str(self.db), "--json",
        ])
        self.assertEqual(rc, 0, (out, err))
        created = json.loads(out)
        root = Path(created["root_path"])
        self.assertTrue(root.is_dir())

        rc, out, err = run(["temp", "summary", "--task", self.task_id, "--json"])
        self.assertEqual(rc, 0, (out, err))
        summary = json.loads(out)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["active"], 1)

        rc, out, err = run([
            "temp", "cleanup", "--project", "demo", "--task", self.task_id,
            "--run-id", "RUN-MANUAL-1", "--json",
        ])
        self.assertEqual(rc, 0, (out, err))
        cleaned = json.loads(out)
        self.assertEqual(cleaned["status"], "CLEANED")
        self.assertFalse(root.exists())

    def test_work_end_cleans_only_the_matching_session_temp_run(self):
        rc, out, err = run([
            "work", "start", "--task", self.task_id, "--role", "tp-test-engineer",
            "--db", str(self.db),
        ])
        self.assertEqual(rc, 0, (out, err))
        import re
        session_id = re.search(r"session_id=([A-Za-z0-9._-]+)", out).group(1)
        session_rec = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id=session_id,
        )
        manual_rec = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id="RUN-OTHER",
        )

        rc, out, err = run([
            "work", "end", "--task", self.task_id, "--role", "tp-test-engineer",
            "--reason", "completed", "--db", str(self.db),
        ])

        self.assertEqual(rc, 0, (out, err))
        self.assertFalse(Path(session_rec["root_path"]).exists())
        self.assertTrue(Path(manual_rec["root_path"]).exists())
        saved = json.loads(Path(session_rec["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "CLEANED")

    def test_work_end_cleanup_failure_is_pending_but_runtime_end_still_succeeds(self):
        rc, out, err = run([
            "work", "start", "--task", self.task_id, "--role", "tp-test-engineer",
            "--db", str(self.db),
        ])
        self.assertEqual(rc, 0, (out, err))
        import re
        session_id = re.search(r"session_id=([A-Za-z0-9._-]+)", out).group(1)
        rec = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id=session_id,
        )

        with mock.patch("cli.temp_artifacts._remove_tree_no_follow", side_effect=OSError("locked")):
            rc, out, err = run([
                "work", "end", "--task", self.task_id, "--role", "tp-test-engineer",
                "--reason", "interrupted", "--db", str(self.db),
            ])

        self.assertEqual(rc, 0, (out, err))
        self.assertIn("TEMP_CLEANUP_PENDING", err)
        saved = json.loads(Path(rec["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "CLEANUP_PENDING")
        from cli import db as dbmod
        conn = dbmod.connect_readonly(str(self.db))
        try:
            ended = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event WHERE task_id=? AND event_type='WORK_SESSION_ENDED'",
                (self.task_id,),
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(ended, 1)

    def test_task_complete_cleans_all_owned_runs_and_reports_summary(self):
        first = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-development-engineer", run_id="RUN-A",
        )
        second = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id="RUN-B",
        )
        rc, out, err = run([
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--phase", "development",
            "--summary", "implementation complete", "--db", str(self.db),
        ])
        self.assertEqual(rc, 0, (out, err))

        rc, out, err = run([
            "task", "complete", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineer", "--summary", "done", "--db", str(self.db),
        ])

        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        self.assertEqual(payload["temp_artifacts"]["cleaned"], 2)
        self.assertEqual(payload["temp_artifacts"]["pending"], 0)
        self.assertFalse(Path(first["root_path"]).exists())
        self.assertFalse(Path(second["root_path"]).exists())

    def test_task_cancel_cleanup_failure_does_not_rollback_cancelled_state(self):
        rec = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id="RUN-LOCKED",
        )
        with mock.patch("cli.temp_artifacts._remove_tree_no_follow", side_effect=OSError("locked")):
            rc, out, err = run([
                "task", "cancel", "--task", self.task_id, "--task-dir", str(self.task_dir),
                "--reason", "cancel test", "--db", str(self.db),
            ])

        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        self.assertEqual(payload["state"], "CANCELLED")
        self.assertEqual(payload["temp_artifacts"]["pending"], 1)
        saved = json.loads(Path(rec["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "CLEANUP_PENDING")


    def test_temp_create_requires_runtime_db_for_task_ownership_validation(self):
        rc, out, err = run([
            "temp", "create", "--project", "demo", "--task", self.task_id,
            "--role", "tp-test-engineer", "--run-id", "RUN-NO-DB", "--json",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("--db", err)
        self.assertFalse((self.temp_root / "tp-spec" / "demo" / self.task_id / "RUN-NO-DB").exists())

    def test_execution_temp_rejects_unknown_task_from_explicit_runtime(self):
        unknown_dir = self.project / ".tp-spec" / "tasks" / "TASK-NOT-EXIST"
        unknown_dir.mkdir(parents=True)
        rc, out, err = run([
            "task", "artifact-path", "--task-dir", str(unknown_dir),
            "--kind", "execution-temp", "--task", "TASK-NOT-EXIST",
            "--project", "demo", "--role", "tp-test-engineer",
            "--run-id", "RUN-NOT-EXIST", "--db", str(self.db), "--ensure",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("task not found", err.lower())
        self.assertFalse((self.temp_root / "tp-spec" / "demo" / "TASK-NOT-EXIST").exists())

    def test_temp_create_rejects_unknown_task_when_runtime_db_is_supplied(self):
        rc, out, err = run([
            "temp", "create", "--project", "demo", "--task", "TASK-NOT-EXIST",
            "--role", "tp-test-engineer", "--run-id", "RUN-UNKNOWN",
            "--db", str(self.db), "--json",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("task not found", err.lower())
        self.assertFalse((self.temp_root / "tp-spec" / "demo" / "TASK-NOT-EXIST").exists())

    def test_orphan_check_with_runtime_marks_ended_session_without_cleanup_as_orphan(self):
        from cli import db as dbmod
        rec = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id="WORK-ORPHAN",
        )
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                    (self.task_id, "WORK_SESSION_STARTED", "tp-test-engineer", json.dumps({"session_id": "WORK-ORPHAN"}), "start", "2026-08-25T10:00:00+08:00"),
                )
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                    (self.task_id, "WORK_SESSION_ENDED", "tp-test-engineer", json.dumps({"session_id": "WORK-ORPHAN", "reason": "completed"}), "end", "2026-08-25T10:10:00+08:00"),
                )
        finally:
            conn.close()

        rc, out, err = run([
            "temp", "orphan-check", "--project", "demo", "--task", self.task_id,
            "--db", str(self.db), "--json",
        ])

        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        candidate = next(item for item in payload["owned_candidates"] if item["run_id"] == "WORK-ORPHAN")
        self.assertEqual(candidate["classification"], "ORPHAN_SESSION_ENDED")
        self.assertTrue(Path(rec["root_path"]).is_dir())
        self.assertEqual(payload["auto_deleted"], 0)



    def test_project_level_orphan_check_correlates_session_id_with_task_id(self):
        from cli import db as dbmod
        other_task = "TASK-TEMP-OTHER"
        other_dir = self.project / ".tp-spec" / "tasks" / other_task
        rc, out, err = run([
            "task", "create", "--id", other_task, "--project", "demo",
            "--risk", "L0", "--flow", "L0", "--db", str(self.db),
            "--scaffold", "--task-dir", str(other_dir),
        ])
        self.assertEqual(rc, 0, (out, err))
        temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id="WORK-COLLIDE",
        )
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                    (self.task_id, "WORK_SESSION_STARTED", "tp-test-engineer", json.dumps({"session_id": "WORK-COLLIDE"}), "start current", "2026-08-25T12:00:00+08:00"),
                )
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                    (other_task, "WORK_SESSION_STARTED", "tp-test-engineer", json.dumps({"session_id": "WORK-COLLIDE"}), "start other", "2026-08-25T12:01:00+08:00"),
                )
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                    (other_task, "WORK_SESSION_ENDED", "tp-test-engineer", json.dumps({"session_id": "WORK-COLLIDE", "reason": "completed"}), "end other", "2026-08-25T12:02:00+08:00"),
                )
        finally:
            conn.close()

        rc, out, err = run([
            "temp", "orphan-check", "--project", "demo", "--db", str(self.db), "--json",
        ])
        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        current = next(item for item in payload["owned_candidates"] if item.get("task_id") == self.task_id and item.get("run_id") == "WORK-COLLIDE")
        self.assertEqual(current["classification"], "ACTIVE_SESSION_OPEN")

    def test_ended_session_orphan_can_be_explicitly_cleaned_without_touching_unmanaged_tmp(self):
        from cli import db as dbmod
        rec = temp_artifacts.create_run_root(
            project_id="demo", task_id=self.task_id, creator_role="tp-test-engineer", run_id="WORK-RECOVER",
        )
        unmanaged = self.project / ".tmp" / "legacy-user-owned"
        unmanaged.mkdir(parents=True)
        (unmanaged / "keep.txt").write_text("keep", encoding="utf-8")
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                for event_type, when in (("WORK_SESSION_STARTED", "2026-08-25T11:00:00+08:00"), ("WORK_SESSION_ENDED", "2026-08-25T11:05:00+08:00")):
                    conn.execute(
                        "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                        (self.task_id, event_type, "tp-test-engineer", json.dumps({"session_id": "WORK-RECOVER", "reason": "interrupted"}), event_type, when),
                    )
        finally:
            conn.close()

        rc, out, err = run([
            "temp", "orphan-check", "--project", "demo", "--task", self.task_id,
            "--workspace-root", str(self.project), "--db", str(self.db), "--json",
        ])
        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        owned = next(item for item in payload["owned_candidates"] if item["run_id"] == "WORK-RECOVER")
        self.assertEqual(owned["classification"], "ORPHAN_SESSION_ENDED")
        self.assertTrue(unmanaged.is_dir())

        rc, out, err = run([
            "temp", "cleanup", "--project", "demo", "--task", self.task_id,
            "--run-id", "WORK-RECOVER", "--json",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertFalse(Path(rec["root_path"]).exists())
        self.assertEqual((unmanaged / "keep.txt").read_text(encoding="utf-8"), "keep")




class WorkSessionTimingCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v526-work-time-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.user_root = self.root / "user" / ".tp-spec"
        self.env = mock.patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(self.user_root)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.registry = self.root / "registry.local.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        self.project = self.root / "project"
        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project),
            "--registry", str(self.registry),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.db = self.project / ".tp-spec" / "db" / "demo.db"
        self.task_id = "TASK-WORK-TIME"
        self.task_dir = self.project / ".tp-spec" / "tasks" / self.task_id
        rc, out, err = run([
            "task", "create", "--id", self.task_id, "--project", "demo",
            "--risk", "L0", "--flow", "L0", "--db", str(self.db),
            "--scaffold", "--task-dir", str(self.task_dir),
        ])
        self.assertEqual(rc, 0, (out, err))
        from cli import db as dbmod
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute(
                    "UPDATE task_event SET created_at=? WHERE task_id=? AND event_type='STATE'",
                    ("2026-08-25T09:00:00+08:00", self.task_id),
                )
        finally:
            conn.close()

    def add_session_event(self, event_type, role, created_at, session_id, *, reason=""):
        from cli import db as dbmod
        detail = {"session_id": session_id}
        if reason:
            detail["reason"] = reason
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,actor_role,detail_json,summary,created_at) VALUES (?,?,?,?,?,?)",
                    (self.task_id, event_type, role, json.dumps(detail), event_type, created_at),
                )
        finally:
            conn.close()

    def test_stage_time_pairs_interleaved_sessions_by_session_id_and_reports_role_totals(self):
        self.add_session_event("WORK_SESSION_STARTED", "tp-test-engineer", "2026-08-25T10:00:00+08:00", "WORK-TEST")
        self.add_session_event("WORK_SESSION_STARTED", "tp-code-reviewer", "2026-08-25T10:05:00+08:00", "WORK-REVIEW")
        self.add_session_event("WORK_SESSION_ENDED", "tp-test-engineer", "2026-08-25T10:20:00+08:00", "WORK-TEST", reason="completed")
        self.add_session_event("WORK_SESSION_ENDED", "tp-code-reviewer", "2026-08-25T10:35:00+08:00", "WORK-REVIEW", reason="completed")

        rc, out, err = run(["report", "stage-time", "--task", self.task_id, "--db", str(self.db)])

        self.assertEqual(rc, 0, (out, err))
        self.assertIn("Role Work Time", out)
        self.assertRegex(out, r"tp-test-engineer\s+1\s+20\.0m")
        self.assertRegex(out, r"tp-code-reviewer\s+1\s+30\.0m")
        self.assertIn("unmatched starts: 0", out)
        self.assertIn("unmatched ends: 0", out)

    def test_stage_time_aggregates_multiple_sessions_for_same_role(self):
        self.add_session_event("WORK_SESSION_STARTED", "tp-test-engineer", "2026-08-25T10:00:00+08:00", "WORK-1")
        self.add_session_event("WORK_SESSION_ENDED", "tp-test-engineer", "2026-08-25T10:10:00+08:00", "WORK-1", reason="completed")
        self.add_session_event("WORK_SESSION_STARTED", "tp-test-engineer", "2026-08-25T11:00:00+08:00", "WORK-2")
        self.add_session_event("WORK_SESSION_ENDED", "tp-test-engineer", "2026-08-25T11:15:00+08:00", "WORK-2", reason="waiting_human")

        rc, out, err = run(["report", "stage-time", "--task", self.task_id, "--db", str(self.db)])

        self.assertEqual(rc, 0, (out, err))
        self.assertRegex(out, r"tp-test-engineer\s+2\s+25\.0m")
        self.assertIn("waiting end reasons do not measure waiting duration", out)

    def test_stage_time_reports_unmatched_sessions_without_inventing_duration(self):
        self.add_session_event("WORK_SESSION_STARTED", "tp-test-engineer", "2026-08-25T10:00:00+08:00", "WORK-OPEN")
        self.add_session_event("WORK_SESSION_ENDED", "tp-code-reviewer", "2026-08-25T10:30:00+08:00", "WORK-UNKNOWN", reason="interrupted")

        rc, out, err = run(["report", "stage-time", "--task", self.task_id, "--db", str(self.db)])

        self.assertEqual(rc, 0, (out, err))
        self.assertIn("unmatched starts: 1", out)
        self.assertIn("unmatched ends: 1", out)
        self.assertIn("no paired role work sessions", out)


class TempArtifactContractCase(unittest.TestCase):
    def test_test_engineer_requires_owned_system_temp_and_immutable_source_inputs(self):
        base = Path(__file__).parents[2]
        skill = (base / "skills" / "roles" / "tp-test-engineer" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("task artifact-path --kind execution-temp", skill)
        self.assertIn("--db <RUNTIME-DB>", skill)
        self.assertIn("系统临时目录", skill)
        self.assertIn("禁止在项目工作区创建 `.tmp`", skill)
        self.assertIn("用户原始文件", skill)
        self.assertIn("不得修改、覆盖、移动或删除", skill)
        self.assertIn("CLEANUP_PENDING", skill)

    def test_lifecycle_documents_interrupted_recovery_and_report_only_orphan_check(self):
        base = Path(__file__).parents[2]
        skill = (base / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("work end --reason interrupted", skill)
        self.assertIn("temp orphan-check --db <DB>", skill)
        self.assertIn("只报告", skill)
        self.assertIn("不得自动删除", skill)

    def test_runtime_api_keeps_cleanup_pending_outside_task_state_machine(self):
        base = Path(__file__).parents[2]
        runtime_api = (base / "governance" / "runtime-api.yaml").read_text(encoding="utf-8")
        self.assertIn("temporary_artifacts:", runtime_api)
        self.assertIn("CLEANUP_PENDING", runtime_api)
        self.assertIn("not_a_task_state", runtime_api)
        self.assertIn("system_temp", runtime_api)


if __name__ == "__main__":
    unittest.main(verbosity=2)
