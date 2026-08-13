# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

from cli import db as dbmod  # noqa: E402
from cli.active_task_portability import scan_active_task_portability  # noqa: E402
from cli.base_maintenance import inventory_rows, reconcile_inventory_project  # noqa: E402
from cli.environment import load_workspace_inventory, write_workspace_inventory  # noqa: E402
from cli.installation_lifecycle import configure_installation, installation_doctor, installation_migration  # noqa: E402
from cli.path_identity import same_path  # noqa: E402
from cli.runtime_portability import apply_runtime_rebind, runtime_rebind_plan  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


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
                (project_id, project_id, str(root_path), "5.1.3", dbmod.EXPECTED_SCHEMA_VERSION, now, now),
            )
    finally:
        conn.close()


class RuntimePortabilityCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v513-runtime-portability-")
        self.root = Path(self.tmp.name)
        self.user = self.root / "user-state"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.project_id = "demo"
        write(self.workspace / ".tp-spec/config/project-binding.yaml", """schema: tp-spec.project-binding/v1
project:
  id: demo
base_version: 5.1.3
""")
        self.env = patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(self.user)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_register_project_seeds_machine_registry_from_legacy_before_first_write(self):
        legacy = self.root / "legacy-registry.json"
        write(legacy, json.dumps({"projects": [{"project_id": "other", "db_path": "X:/other.db", "root_path": "X:/other", "base_version": "5.1.3", "schema_version": 1}]}, indent=2))
        with patch.object(dbmod, "_LEGACY_REGISTRY_PATH", legacy):
            dbmod.register_project(
                project_id="demo", project_name="demo", db_path=str(self.workspace / ".tp-spec/db/demo.db"),
                root_path=str(self.workspace), base_version="5.1.3", schema_version=1,
            )
        data = json.loads(dbmod.registry_default_path().read_text(encoding="utf-8"))
        self.assertEqual({p["project_id"] for p in data["projects"]}, {"other", "demo"})

    def test_legacy_registry_mutation_copy_on_write_moves_state_out_of_base(self):
        legacy = self.root / "legacy-registry.json"
        write(legacy, json.dumps({"projects": [{"project_id": "demo", "db_path": "X:/demo.db", "root_path": "X:/demo", "base_version": "5.1." + "2", "schema_version": 1}]}, indent=2))
        with patch.object(dbmod, "_LEGACY_REGISTRY_PATH", legacy):
            self.assertTrue(dbmod.update_registered_project_contract("demo", "5.1.3"))
        target = dbmod.registry_default_path()
        self.assertTrue(target.is_file())
        self.assertFalse(legacy.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["projects"][0]["base_version"], "5.1.3")

    def test_runtime_root_rebind_updates_db_and_machine_registry(self):
        old = self.root / "old-missing-workspace"
        db_path = self.workspace / ".tp-spec/db/demo.db"
        make_runtime_db(db_path, self.project_id, old)
        plan = runtime_rebind_plan(self.workspace, self.project_id)
        self.assertEqual(plan["status"], "REBIND_AVAILABLE", plan)
        result = apply_runtime_rebind(self.workspace, self.project_id)
        self.assertEqual(result["status"], "CURRENT", result)
        self.assertEqual(result["action"], "REBIND_RUNTIME_ROOT")
        conn = dbmod.connect_readonly(str(db_path))
        try:
            row = conn.execute("SELECT root_path FROM project WHERE project_id='demo'").fetchone()
        finally:
            conn.close()
        self.assertEqual(Path(row["root_path"]), self.workspace.resolve(strict=False))
        registry = dbmod.registry_default_path()
        self.assertTrue(registry.is_file())
        self.assertTrue(same_path(registry.parent, self.user))
        self.assertFalse((BASE / "db/registry.local.json").exists())

    def test_relative_legacy_runtime_root_is_rebindable_not_resolved_against_current_cwd(self):
        db_path = self.workspace / ".tp-spec/db/demo.db"
        make_runtime_db(db_path, self.project_id, Path("."))
        plan = runtime_rebind_plan(self.workspace, self.project_id)
        self.assertEqual(plan["status"], "REBIND_AVAILABLE", plan)

    def test_runtime_rebind_blocks_when_previous_workspace_still_exists(self):
        old = self.root / "old-live-workspace"
        old.mkdir()
        make_runtime_db(self.workspace / ".tp-spec/db/demo.db", self.project_id, old)
        plan = runtime_rebind_plan(self.workspace, self.project_id)
        self.assertEqual(plan["status"], "BLOCKED", plan)
        self.assertTrue(any("previous Runtime root still exists" in b for b in plan["blockers"]))

    def test_sqlite_wal_shm_are_reported_as_transient_not_portable_truth(self):
        db_path = self.workspace / ".tp-spec/db/demo.db"
        make_runtime_db(db_path, self.project_id, self.workspace)
        Path(str(db_path) + "-wal").touch()
        Path(str(db_path) + "-shm").touch()
        plan = runtime_rebind_plan(self.workspace, self.project_id)
        kinds = {Path(x["path"]).name: x for x in plan["transient_files"]}
        self.assertFalse(kinds["demo.db-wal"]["portable_truth"])
        self.assertFalse(kinds["demo.db-shm"]["portable_truth"])

    def test_inventory_reconciles_stale_same_project_root(self):
        stale = self.root / "stale-missing"
        inventory = self.user / "workspaces.yaml"
        write_workspace_inventory([{"id": "demo", "root": str(stale), "enabled": True}], path=inventory)
        dbmod.register_project(
            project_id="demo", project_name="demo", db_path=str(self.workspace / ".tp-spec/db/demo.db"),
            root_path=str(self.workspace), base_version="5.1.3", schema_version=1,
        )
        rows = inventory_rows(inventory_path=str(inventory))
        demo = [r for r in rows if r.get("id") == "demo"]
        self.assertEqual(len(demo), 1, rows)
        self.assertEqual(Path(demo[0]["root"]), self.workspace.resolve(strict=False))
        self.assertIn(str(stale.resolve(strict=False)), demo[0].get("reconciled_stale_roots") or [])

    def test_active_task_scanner_ignores_history_and_negated_mentions(self):
        active = self.workspace / ".tp-spec/tasks/TASK-1"
        write(active / "status.yaml", "task_id: TASK-1\ncurrent_state: ACTIVE\n")
        write(active / "tech-design.md", "知识沉淀后落 `.tp-spec/knowledge/`。\n不得依赖旧 `.tp-spec/wiki/` Junction。\n")
        done = self.workspace / ".tp-spec/tasks/TASK-2"
        write(done / "status.yaml", "task_id: TASK-2\ncurrent_state: COMPLETED\n")
        write(done / "tech-design.md", "执行 `.tp-spec/scripts/run.ps1`。\n")
        write(self.workspace / ".tp-spec/tasksHistory/TASK-H/tech-design.md", "执行 `.tp-spec/knowledge/`。\n")
        result = scan_active_task_portability(self.workspace)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(result["findings"]), 1, result)
        self.assertEqual(result["findings"][0]["task_id"], "TASK-1")
        self.assertIn("knowledge", result["findings"][0]["snippet"])


class InstallationLifecycleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v513-installation-life-")
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.wiki = self.root / "wiki"; self.wiki.mkdir()
        self.knowledge = self.root / "knowledge"; self.knowledge.mkdir()
        self.install = self.user / "installation.yaml"
        self.env = patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(self.user)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_configure_create_then_partial_update_preserves_content_roots(self):
        first = configure_installation(base_root=BASE, wiki_root=self.wiki, knowledge_root=self.knowledge, installation_config=self.install)
        self.assertEqual(first["status"], "PASS", first)
        self.assertEqual(first["action"], "CREATED")
        second = configure_installation(base_root=BASE, installation_config=self.install)
        self.assertEqual(second["status"], "PASS", second)
        data = yaml.safe_load(self.install.read_text(encoding="utf-8"))
        self.assertEqual(Path(data["systems"]["wiki"]["root"]), self.wiki.resolve(strict=False))
        self.assertEqual(Path(data["systems"]["knowledge"]["root"]), self.knowledge.resolve(strict=False))
        health = installation_doctor(self.install, executing_base_root=BASE)
        self.assertEqual(health["status"], "PASS", health)

    def test_invalid_existing_installation_requires_full_explicit_repair(self):
        write(self.install, "schema: broken/v0\n")
        blocked = configure_installation(base_root=BASE, installation_config=self.install)
        self.assertEqual(blocked["status"], "BLOCKED")
        repaired = configure_installation(base_root=BASE, wiki_root=self.wiki, knowledge_root=self.knowledge, installation_config=self.install)
        self.assertEqual(repaired["status"], "PASS", repaired)

    def test_installation_migration_prefers_live_rebound_machine_entry_over_stale_legacy_root(self):
        configure_installation(base_root=BASE, wiki_root=self.wiki, knowledge_root=self.knowledge, installation_config=self.install)
        current_ws = self.root / "current-ws"; current_ws.mkdir()
        current_db = current_ws / ".tp-spec/db/demo.db"; current_db.parent.mkdir(parents=True)
        current_db.touch()
        legacy = self.root / "legacy-registry.json"
        target = self.user / "registry.local.json"
        write(legacy, json.dumps({"projects": [{"project_id": "demo", "db_path": str(self.root / "missing-old/demo.db"), "root_path": str(self.root / "missing-old"), "base_version": "5.1.3", "schema_version": 1}]}, indent=2))
        write(target, json.dumps({"projects": [{"project_id": "demo", "db_path": str(current_db), "root_path": str(current_ws), "base_version": "5.1.3", "schema_version": 1}]}, indent=2))
        result = installation_migration(self.install, apply=True, legacy_registry_path=str(legacy), target_registry_path=str(target))
        self.assertEqual(result["status"], "PASS", result)
        self.assertFalse(legacy.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["projects"][0]["root_path"], str(current_ws))

    def test_installation_migration_moves_legacy_registry_after_safe_copy(self):
        configure_installation(base_root=BASE, wiki_root=self.wiki, knowledge_root=self.knowledge, installation_config=self.install)
        legacy = self.root / "base-local-registry.json"
        target = self.user / "registry.local.json"
        write(legacy, json.dumps({"projects": [{"project_id": "demo", "db_path": "X:/demo.db", "root_path": "X:/demo", "base_version": "5.1.3", "schema_version": 1}]}, indent=2))
        plan = installation_migration(self.install, apply=False, legacy_registry_path=str(legacy), target_registry_path=str(target))
        self.assertEqual(plan["status"], "MIGRATION_AVAILABLE", plan)
        applied = installation_migration(self.install, apply=True, legacy_registry_path=str(legacy), target_registry_path=str(target))
        self.assertEqual(applied["status"], "PASS", applied)
        self.assertTrue(target.is_file())
        self.assertFalse(legacy.exists())


class SchedulerBootstrapCase(unittest.TestCase):
    def test_wiki_scheduler_uses_installation_like_knowledge_scheduler(self):
        wiki = (BASE / "automation/wiki/SCHEDULER_BOOTSTRAP.md").read_text(encoding="utf-8")
        knowledge = (BASE / "automation/knowledge/SCHEDULER_BOOTSTRAP.md").read_text(encoding="utf-8")
        for token in ("~/.tp-spec/installation.yaml", "TP_SPEC_INSTALLATION_CONFIG", "automation/wiki/daily-maintenance.md", "tp-spec.ps1"):
            self.assertIn(token, wiki)
        self.assertIn("~/.tp-spec/installation.yaml", knowledge)
        self.assertNotIn("<BaseRoot> = <", wiki)


if __name__ == "__main__":
    unittest.main(verbosity=2)
