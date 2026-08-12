# -*- coding: utf-8 -*-
"""V5.1.3 maintenance regressions discovered from real-task operation.

Covers pristine Runtime bootstrap, actionable task-create errors, and pre-task intake adoption.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

from cli import db as dbmod  # noqa: E402
from cli import main as climain  # noqa: E402
from cli.version import active_version  # noqa: E402


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class TestV512Maintenance(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v512-maint-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.registry = self.root / "registry.local.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        self.project_root = self.root / "project"
        self.db = self.project_root / ".ai-work" / "db" / "demo.db"

    def bootstrap(self):
        return run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project_root),
            "--registry", str(self.registry),
        ])

    def test_task_create_missing_db_returns_project_not_initialized_without_side_effect(self):
        rc, out, err = run([
            "task", "create", "--id", "TASK-MISSING-DB", "--project", "demo",
            "--risk", "L1", "--flow", "L1", "--db", str(self.db),
        ])
        self.assertEqual(rc, 4, (out, err))
        self.assertIn("PROJECT_NOT_INITIALIZED", err)
        self.assertIn("project bootstrap", err)
        self.assertNotIn("unable to open database file", err)
        self.assertFalse(self.db.exists())

    def test_task_create_empty_sqlite_returns_project_not_initialized(self):
        self.db.parent.mkdir(parents=True)
        self.db.write_bytes(b"")
        rc, out, err = run([
            "task", "create", "--id", "TASK-EMPTY-DB", "--project", "demo",
            "--risk", "L1", "--flow", "L1", "--db", str(self.db),
        ])
        self.assertEqual(rc, 4, (out, err))
        self.assertIn("PROJECT_NOT_INITIALIZED", err)
        self.assertIn("Runtime schema is unavailable", err)
        self.assertTrue(self.db.is_file())

    def test_project_bootstrap_refuses_existing_empty_sqlite(self):
        self.db.parent.mkdir(parents=True)
        self.db.write_bytes(b"")
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 4, (out, err))
        self.assertIn("PROJECT_BOOTSTRAP_UNSAFE", err)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_project_bootstrap_check_only_is_read_only_on_pristine_project(self):
        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project_root),
            "--registry", str(self.registry), "--check-only",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("PROJECT_BOOTSTRAP_AVAILABLE", out)
        self.assertFalse(self.db.exists())
        self.assertEqual(json.loads(self.registry.read_text(encoding="utf-8")), {"projects": []})

    def test_project_bootstrap_pristine_initializes_and_is_idempotent(self):
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("PROJECT_BOOTSTRAPPED", out)
        self.assertTrue(self.db.is_file())
        conn = dbmod.connect(str(self.db))
        try:
            row = conn.execute("SELECT project_id, base_version FROM project WHERE project_id='demo'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["base_version"], active_version())

        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        rc2, out2, err2 = self.bootstrap()
        self.assertEqual(rc2, 0, (out2, err2))
        self.assertIn("PROJECT_READY", out2)
        self.assertNotIn("PROJECT_BOOTSTRAPPED", out2)
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertEqual(after, before)

    def test_project_bootstrap_refuses_task_history_without_db(self):
        orphan = self.project_root / ".ai-work" / "tasks" / "TASK-OLD"
        orphan.mkdir(parents=True)
        (orphan / "events.jsonl").write_text('{"event":"old"}\n', encoding="utf-8")
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 4, (out, err))
        self.assertIn("PROJECT_BOOTSTRAP_UNSAFE", err)
        self.assertFalse(self.db.exists())

    def test_project_bootstrap_reuses_registered_custom_db(self):
        custom = self.root / "custom" / "runtime.db"
        custom.parent.mkdir(parents=True)
        conn = dbmod.connect(str(custom))
        try:
            dbmod.init_schema(conn)
            now = dbmod.now_iso()
            with dbmod.transactional(conn):
                conn.execute(
                    "INSERT INTO project (project_id, project_name, root_path, base_version, schema_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    ("demo", "demo", str(self.project_root), active_version(), dbmod.EXPECTED_SCHEMA_VERSION, now, now),
                )
        finally:
            conn.close()
        self.registry.write_text(json.dumps({"projects": [{
            "project_id": "demo", "project_name": "demo", "db_path": str(custom),
            "root_path": str(self.project_root), "base_version": active_version(),
            "schema_version": dbmod.EXPECTED_SCHEMA_VERSION,
        }]}), encoding="utf-8")
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("PROJECT_READY", out)
        self.assertIn(str(custom), out)
        self.assertFalse(self.db.exists())

    def test_project_bootstrap_refuses_stale_registry(self):
        self.registry.write_text(json.dumps({"projects": [{
            "project_id": "demo",
            "project_name": "demo",
            "db_path": str(self.db),
            "root_path": str(self.project_root),
            "base_version": active_version(),
            "schema_version": dbmod.EXPECTED_SCHEMA_VERSION,
        }]}), encoding="utf-8")
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 4, (out, err))
        self.assertIn("already registered but its database is missing", err)
        self.assertFalse(self.db.exists())

    def test_task_create_from_intake_adopts_contract_identity_and_provenance(self):
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 0, (out, err))
        intake = self.root / "intake"
        intake.mkdir()
        src = intake / "requirement-knowledge.md"
        source_text = (BASE / "templates" / active_version() / "requirement-knowledge.md").read_text(encoding="utf-8")
        source_text += "\n| intake | 保留这条 intake 业务事实 | 影响正式需求理解 |\n"
        src.write_text(source_text, encoding="utf-8", newline="\n")
        source_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        task_dir = self.project_root / ".ai-work" / "tasks" / "TASK-INTAKE-1"

        rc2, out2, err2 = run([
            "task", "create", "--id", "TASK-INTAKE-1", "--project", "demo",
            "--title", "intake adoption", "--risk", "L1", "--flow", "L1",
            "--db", str(self.db), "--from-intake", str(intake), "--task-dir", str(task_dir),
        ])
        self.assertEqual(rc2, 0, (out2, err2))
        self.assertIn("intake_adopted=requirement-knowledge.md", out2)
        self.assertIn("intake_source_preserved=true", out2)
        adopted = (task_dir / "requirement-knowledge.md").read_text(encoding="utf-8")
        self.assertIn('task_id: "TASK-INTAKE-1"', adopted)
        self.assertIn(f"version: {active_version()}", adopted)
        self.assertIn("保留这条 intake 业务事实", adopted)
        self.assertIn(f'source_sha256: "sha256:{source_hash}"', adopted)
        self.assertIn("policy: copy_preserve_source", adopted)
        self.assertTrue(src.is_file())

    def test_role_contracts_encode_pristine_and_pretask_boundaries(self):
        base_maintenance = (BASE / "agents" / "tp-base-maintenance" / "SKILL.md").read_text(encoding="utf-8")
        requirement = (BASE / "skills" / "tp-requirement-analysis" / "SKILL.md").read_text(encoding="utf-8")
        architecture = (BASE / "skills" / "tp-architecture-design" / "SKILL.md").read_text(encoding="utf-8")
        runtime_api = (BASE / "governance" / "runtime-api.yaml").read_text(encoding="utf-8")
        self.assertIn("TP-Spec-Coding Installation + Project Binding", base_maintenance)
        self.assertIn("Workspace Inventory", base_maintenance)
        self.assertIn("PROJECT_BOOTSTRAP_UNSAFE", base_maintenance)
        self.assertIn("需求分析允许发生在正式 Task 创建之前", requirement)
        self.assertIn("不得为了写 FACT/DECISION/HANDOFF 事件提前建 Task", requirement)
        self.assertIn("--from-intake <DIR>", architecture)
        self.assertIn("project_bootstrap:", runtime_api)
        self.assertIn("PROJECT_NOT_INITIALIZED:", runtime_api)

    def test_task_create_from_intake_rejects_unknown_only_directory_atomically(self):
        rc, out, err = self.bootstrap()
        self.assertEqual(rc, 0, (out, err))
        intake = self.root / "bad-intake"
        intake.mkdir()
        (intake / "notes.md").write_text("notes\n", encoding="utf-8")
        task_dir = self.project_root / ".ai-work" / "tasks" / "TASK-INTAKE-BAD"
        rc2, out2, err2 = run([
            "task", "create", "--id", "TASK-INTAKE-BAD", "--project", "demo",
            "--risk", "L1", "--flow", "L1", "--db", str(self.db),
            "--from-intake", str(intake), "--task-dir", str(task_dir),
        ])
        self.assertEqual(rc2, 6, (out2, err2))
        self.assertIn("contains no supported requirement artifacts", err2)
        self.assertFalse(task_dir.exists())
        conn = dbmod.connect(str(self.db))
        try:
            row = conn.execute("SELECT task_id FROM task WHERE task_id='TASK-INTAKE-BAD'").fetchone()
        finally:
            conn.close()
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
