# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

from cli import commit_cmd  # noqa: E402
from cli import db as dbmod  # noqa: E402
from cli import main as climain  # noqa: E402
from cli import transaction_journal  # noqa: E402
from cli.version import active_version  # noqa: E402


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def make_runtime_db(db_path: Path, project_id: str, root_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(str(db_path))
    try:
        dbmod.init_schema(conn)
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                "INSERT OR REPLACE INTO project "
                "(project_id, project_name, root_path, base_version, schema_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, project_id, str(root_path.resolve()), active_version(), dbmod.EXPECTED_SCHEMA_VERSION, now, now),
            )
    finally:
        conn.close()


class V523RuntimeHardeningCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v523-runtime-hardening-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.user_root = self.root / "user-state"
        self.registry = self.user_root / "registry.local.json"
        self.env = patch.dict(
            os.environ,
            {
                "TP_SPEC_USER_ROOT": str(self.user_root),
                "TP_SPEC_REGISTRY": str(self.registry),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _init(self, workspace: Path, project_id: str = "demo"):
        workspace.mkdir(parents=True, exist_ok=True)
        rc, out, err = run(["project", "init", "--id", project_id, "--root", str(workspace)])
        self.assertEqual(rc, 0, (out, err))
        return workspace / ".tp-spec" / "db" / f"{project_id}.db"

    def _create_task(self, workspace: Path, task_id: str = "TASK-V523-WRITER"):
        old = Path.cwd()
        try:
            os.chdir(workspace)
            rc, out, err = run([
                "task", "create", "--id", task_id, "--project", "demo",
                "--risk", "L0", "--flow", "L0", "--scaffold",
            ])
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0, (out, err))
        return workspace / ".tp-spec" / "tasks" / task_id

    def test_project_init_rejects_duplicate_live_workspace_identity(self):
        workspace_a = self.root / "Project-A"
        workspace_b = self.root / "Project-B"
        self._init(workspace_a)
        workspace_b.mkdir()

        rc, out, err = run(["project", "init", "--id", "demo", "--root", str(workspace_b)])

        self.assertNotEqual(rc, 0, (out, err))
        self.assertIn("PROJECT_IDENTITY_CONFLICT", err)
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        row = next(p for p in registry["projects"] if p["project_id"] == "demo")
        self.assertEqual(Path(row["root_path"]), workspace_a.resolve())
        self.assertFalse((workspace_b / ".tp-spec" / "db" / "demo.db").exists())

    def test_task_create_rejects_registry_pointing_to_another_workspace(self):
        workspace_a = self.root / "Project-A"
        workspace_b = self.root / "Project-B"
        db_a = self._init(workspace_a)
        self.assertTrue(db_a.is_file())
        workspace_b.mkdir()
        db_b = workspace_b / ".tp-spec" / "db" / "demo.db"
        make_runtime_db(db_b, "demo", workspace_b)
        dbmod.register_project(
            project_id="demo",
            db_path=str(db_b),
            root_path=str(workspace_b),
            base_version=active_version(),
            schema_version=dbmod.EXPECTED_SCHEMA_VERSION,
        )

        old = Path.cwd()
        try:
            os.chdir(workspace_a)
            rc, out, err = run([
                "task", "create", "--id", "TASK-CROSS", "--project", "demo",
                "--risk", "L0", "--flow", "L0", "--scaffold",
            ])
        finally:
            os.chdir(old)

        self.assertNotEqual(rc, 0, (out, err))
        self.assertIn("PROJECT_WORKSPACE_MISMATCH", err)
        conn = dbmod.connect_readonly(str(db_b))
        try:
            row = conn.execute("SELECT task_id FROM task WHERE task_id='TASK-CROSS'").fetchone()
        finally:
            conn.close()
        self.assertIsNone(row)
        self.assertFalse((workspace_a / ".tp-spec" / "tasks" / "TASK-CROSS").exists())

    def test_task_create_recovers_interrupted_marked_scaffold_before_retry(self):
        workspace = self.root / "Project-A"
        db_path = self._init(workspace)
        task_id = "TASK-RECOVER"
        task_dir = workspace / ".tp-spec" / "tasks" / task_id
        marker = task_dir / ".tp-spec" / "create-transaction.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        (task_dir / "status.yaml").write_text("orphaned create\n", encoding="utf-8")
        marker.write_text(
            json.dumps(
                {
                    "schema": "tp-spec.task-create/v1",
                    "task_id": task_id,
                    "project_id": "demo",
                    "db_path": str(db_path.resolve()),
                    "phase": "FILES_REPLACED",
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        old = Path.cwd()
        try:
            os.chdir(workspace)
            rc, out, err = run([
                "task", "create", "--id", task_id, "--project", "demo",
                "--risk", "L0", "--flow", "L0", "--scaffold",
            ])
        finally:
            os.chdir(old)

        self.assertEqual(rc, 0, (out, err))
        self.assertFalse(marker.exists())
        conn = dbmod.connect_readonly(str(db_path))
        try:
            row = conn.execute("SELECT task_id FROM task WHERE task_id=?", (task_id,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertIn("task_id:", (task_dir / "status.yaml").read_text(encoding="utf-8"))

    def test_record_first_write_rejects_cross_workspace_task_dir_after_registry_pollution(self):
        workspace_a = self.root / "Project-A"
        db_a = self._init(workspace_a)
        task_dir_a = self._create_task(workspace_a, "TASK-CROSS-WRITE")

        workspace_b = self.root / "Project-B"
        shutil.copytree(workspace_a, workspace_b)
        db_b = workspace_b / ".tp-spec" / "db" / "demo.db"
        conn = dbmod.connect(str(db_b))
        try:
            with dbmod.transactional(conn):
                conn.execute("UPDATE project SET root_path=? WHERE project_id='demo'", (str(workspace_b.resolve()),))
        finally:
            conn.close()
        dbmod.register_project(
            project_id="demo", db_path=str(db_b), root_path=str(workspace_b),
            base_version=active_version(), schema_version=dbmod.EXPECTED_SCHEMA_VERSION,
        )

        before_status = (task_dir_a / "status.yaml").read_text(encoding="utf-8")
        old = Path.cwd()
        try:
            os.chdir(workspace_a)
            rc, out, err = run([
                "task", "checkpoint", "--task", "TASK-CROSS-WRITE",
                "--task-dir", str(task_dir_a),
                "--actor", "tp-development-engineering",
                "--phase", "development", "--summary", "must not cross-write",
            ])
        finally:
            os.chdir(old)

        self.assertNotEqual(rc, 0, (out, err))
        self.assertIn("PROJECT_WORKSPACE_MISMATCH", err)
        conn = dbmod.connect_readonly(str(db_b))
        try:
            row = conn.execute("SELECT current_state FROM task WHERE task_id='TASK-CROSS-WRITE'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row["current_state"], "NEW")
        self.assertEqual((task_dir_a / "status.yaml").read_text(encoding="utf-8"), before_status)

    def test_unmarked_existing_task_directory_remains_fail_closed(self):
        workspace = self.root / "Project-A"
        self._init(workspace)
        task_id = "TASK-UNMARKED"
        task_dir = workspace / ".tp-spec" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        user_file = task_dir / "user-owned.txt"
        user_file.write_text("keep me\n", encoding="utf-8")

        old = Path.cwd()
        try:
            os.chdir(workspace)
            rc, out, err = run([
                "task", "create", "--id", task_id, "--project", "demo",
                "--risk", "L0", "--flow", "L0", "--scaffold",
            ])
        finally:
            os.chdir(old)

        self.assertNotEqual(rc, 0, (out, err))
        self.assertTrue(user_file.is_file())
        self.assertEqual(user_file.read_text(encoding="utf-8"), "keep me\n")

    def test_competing_sqlite_writer_is_rejected_before_projection_backup(self):
        workspace = self.root / "Project-A"
        db_path = self._init(workspace)
        task_dir = self._create_task(workspace, "TASK-WRITER-BUSY")
        holder = dbmod.connect(str(db_path))
        contender = dbmod.connect(str(db_path))
        contender.execute("PRAGMA busy_timeout=1")
        backup_called = []
        try:
            holder.execute("BEGIN IMMEDIATE")
            with patch.object(commit_cmd, "_backup", side_effect=lambda *a, **k: backup_called.append(True)):
                with self.assertRaisesRegex(ValueError, "TASK_WRITER_BUSY"):
                    commit_cmd._commit_with_recovery(
                        task_dir, contender, ["status.yaml"], lambda c, transaction_id="": {},
                        task_id="TASK-WRITER-BUSY", operation="busy-test",
                    )
        finally:
            try:
                holder.execute("ROLLBACK")
            except Exception:
                pass
            holder.close()
            contender.close()

        self.assertEqual(backup_called, [])

    def test_projection_backup_runs_only_after_sqlite_write_transaction_is_held(self):
        workspace = self.root / "Project-A"
        db_path = self._init(workspace)
        task_dir = self._create_task(workspace)
        conn = dbmod.connect(str(db_path))
        seen = []
        original_backup = commit_cmd._backup

        def checking_backup(*args, **kwargs):
            seen.append(conn.in_transaction)
            return original_backup(*args, **kwargs)

        def db_and_render(dbconn, transaction_id=""):
            task = dbconn.execute("SELECT * FROM task WHERE task_id=?", ("TASK-V523-WRITER",)).fetchone()
            status = (task_dir / "status.yaml").read_text(encoding="utf-8")
            return {"status.yaml": status}

        try:
            with patch.object(commit_cmd, "_backup", side_effect=checking_backup):
                commit_cmd._commit_with_recovery(
                    task_dir,
                    conn,
                    ["status.yaml"],
                    db_and_render,
                    task_id="TASK-V523-WRITER",
                    operation="writer-serialization-test",
                    db_state_before="NEW",
                    target_state="NEW",
                    owner_before="tp-architecture-design",
                    owner_after="tp-architecture-design",
                    flush_id="",
                )
        finally:
            conn.close()

        self.assertEqual(seen, [True])

    def test_durability_contract_does_not_claim_guaranteed_power_loss_recovery(self):
        journal_doc = transaction_journal.__doc__ or ""
        commit_doc = commit_cmd._commit_with_recovery.__doc__ or ""
        combined = journal_doc + "\n" + commit_doc
        self.assertNotIn("kill/断电", combined)
        self.assertIn("不保证突然断电", combined)


if __name__ == "__main__":
    unittest.main()
