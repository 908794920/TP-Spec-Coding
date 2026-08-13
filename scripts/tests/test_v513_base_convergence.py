# -*- coding: utf-8 -*-
"""V5.1.3 Base installation/project binding convergence regression."""
from __future__ import annotations

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

from cli.base_maintenance import (
    inventory_rows,
    migration_plan_for_workspace,
    resolve_workspace,
    workspace_doctor,
    _migrate_one,
)
from cli.content_systems import load_content_systems
from cli.path_identity import same_path
from cli.environment import (
    load_project_binding,
    write_installation_config,
    write_project_binding,
    write_workspace_inventory,
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class BaseConvergenceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v513-base-convergence-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.base = self.root / "base"
        self.wiki = self.root / "wiki"
        self.knowledge = self.root / "knowledge"
        self.user = self.root / "user"
        for p in (self.workspace, self.base, self.wiki, self.knowledge, self.user):
            p.mkdir(parents=True, exist_ok=True)
        # Minimal valid Base + representative linked assets.
        write(self.base / "VERSION", "5.1.3\n")
        for rel in ("cli/main.py", "governance/workflow.yaml", "agents/role-catalog.yaml"):
            write(self.base / rel, "# base\n")
        for rel in ("agents", "cli", "docs", "governance", "scripts", "skills", "templates", "automation"):
            (self.base / rel).mkdir(parents=True, exist_ok=True)

        self.wiki_project = self.wiki / "projects" / "ws"
        self.wiki_repo = self.wiki_project / "repo"
        self.wiki_repo.mkdir(parents=True)
        write(self.wiki / "00-system/repo-registry.yaml", yaml.safe_dump({
            "version": 1,
            "workspaces": [{
                "id": "ws",
                "workspace_root": str(self.workspace),
                "repos": [{"id": "repo", "repo_root": str(self.workspace), "enabled": True}],
            }],
        }, allow_unicode=True, sort_keys=False))

        self.knowledge_project = self.knowledge / "10-projects" / "demo"
        self.shared = self.knowledge / "20-shared"
        self.knowledge_project.mkdir(parents=True)
        self.shared.mkdir(parents=True)
        write(self.knowledge / "00-system/project-registry.yaml", yaml.safe_dump({
            "registry_version": "1.0.0",
            "projects": [{
                "id": "demo", "display_name": "Demo", "status": "active",
                "workspace_roots": [str(self.workspace)],
            }],
            "shared_scopes": [{"id":"shared", "display_name":"Shared", "status":"active"}],
        }, allow_unicode=True, sort_keys=False))

        self.installation = self.user / "installation.yaml"
        write_installation_config(
            base_root=self.base, wiki_root=self.wiki, knowledge_root=self.knowledge,
            path=self.installation,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _link(self, name: str, target: Path) -> Path:
        p = self.workspace / ".tp-spec" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(target, target_is_directory=True)
        return p


class TestBaseConvergence(BaseConvergenceCase):
    def test_resolution_returns_system_roots_and_exact_project_scopes(self):
        r = resolve_workspace(self.workspace, installation_config=self.installation)
        self.assertTrue(r["base"]["valid"], r)
        self.assertEqual(Path(r["base"]["root"]), self.base.resolve(strict=False))
        self.assertEqual(Path(r["wiki"]["system_root"]), self.wiki.resolve(strict=False))
        self.assertEqual(Path(r["wiki"]["workspace_root"]), self.wiki_project.resolve(strict=False))
        self.assertEqual(Path(r["knowledge"]["system_root"]), self.knowledge.resolve(strict=False))
        self.assertEqual(Path(r["knowledge"]["project_root"]), self.knowledge_project.resolve(strict=False))
        self.assertEqual(r["knowledge"]["default_retrieval_scope"], "project")
        self.assertTrue(r["knowledge"]["include_shared"])
        self.assertFalse(r["knowledge"]["global_fallback"])

    def test_migration_removes_only_exact_matching_links_and_preserves_targets(self):
        links = {
            "agents": self._link("agents", self.base / "agents"),
            "wiki": self._link("wiki", self.wiki_project.resolve(strict=False)),
            "knowledge": self._link("knowledge", self.knowledge_project.resolve(strict=False)),
        }
        plan = migration_plan_for_workspace(self.workspace, installation_config=self.installation)
        self.assertEqual(plan["status"], "READY", plan)
        removable = {a["name"] for a in plan["actions"] if a["action"] == "REMOVE_LEGACY_LINK_AFTER_VERIFY"}
        self.assertEqual(removable, {"agents", "wiki", "knowledge"})
        args = SimpleNamespace(
            installation_config=str(self.installation), apply=False,
            remove_legacy_links=True, remove_redundant_content_config=False,
        )
        dry = _migrate_one(self.workspace, args)
        self.assertEqual(dry["status"], "DRY_RUN")
        self.assertTrue(all(os.path.lexists(p) for p in links.values()))
        args.apply = True
        applied = _migrate_one(self.workspace, args)
        self.assertIn(applied["status"], {"PASS", "WARN"}, applied)
        self.assertTrue(load_project_binding(self.workspace).exists)
        self.assertTrue((self.base / "agents").is_dir())
        self.assertTrue(self.wiki_project.is_dir())
        self.assertTrue(self.knowledge_project.is_dir())
        self.assertTrue(all(not os.path.lexists(p) for p in links.values()))
        final = workspace_doctor(self.workspace, installation_config=self.installation)
        self.assertEqual(final["status"], "PASS", final)
        self.assertEqual(final["health"], "HEALTHY", final)

    def test_real_project_local_base_owned_directory_is_never_auto_deleted(self):
        real = self.workspace / ".tp-spec" / "agents"
        write(real / "local.txt", "real project-local data\n")
        plan = migration_plan_for_workspace(self.workspace, installation_config=self.installation)
        reviews = [a for a in plan["actions"] if a.get("action") == "MANUAL_REVIEW_REAL_PATH"]
        self.assertTrue(any(a.get("name") == "agents" for a in reviews), plan)
        args = SimpleNamespace(
            installation_config=str(self.installation), apply=True,
            remove_legacy_links=True, remove_redundant_content_config=False,
        )
        result = _migrate_one(self.workspace, args)
        self.assertIn(result["status"], {"PASS", "WARN"}, result)
        self.assertTrue((real / "local.txt").is_file())

    def test_link_target_mismatch_blocks_migration(self):
        wrong = self.root / "wrong-wiki"; wrong.mkdir()
        self._link("wiki", wrong)
        plan = migration_plan_for_workspace(self.workspace, installation_config=self.installation)
        self.assertEqual(plan["status"], "BLOCKED", plan)
        self.assertTrue(any("wiki legacy link" in b for b in plan["blockers"]))

    def test_inventory_merges_wiki_and_knowledge_registries_and_can_persist(self):
        # Pass an explicit, empty inventory path so the test stays isolated from
        # any real user-level workspaces.yaml on disk.
        empty_inventory = self.user / "empty-workspaces.yaml"
        # inventory_rows intentionally merges the machine-local Runtime registry.
        # This regression is specifically about Wiki + Knowledge registry merging,
        # so isolate it from any real ~/.tp-spec/registry.local.json on the host.
        with patch("cli.base_maintenance.dbmod.list_projects", return_value=[]):
            rows = inventory_rows(
                installation_config=str(self.installation),
                inventory_path=str(empty_inventory),
            )
        found = [r for r in rows if same_path(Path(r["root"]), self.workspace)]
        self.assertEqual(len(found), 1, rows)
        self.assertIn("wiki-registry", found[0]["sources"])
        self.assertIn("knowledge-registry", found[0]["sources"])
        inventory = self.user / "workspaces.yaml"
        write_workspace_inventory(rows, path=inventory)
        data = yaml.safe_load(inventory.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "tp-spec.workspace-inventory/v1")
        self.assertEqual(len(data["workspaces"]), 1)

    def test_project_content_override_has_priority_and_only_equivalent_roots_are_redundant(self):
        # Same roots expressed relative to workspace can safely become redundant.
        wiki_rel = os.path.relpath(self.wiki, self.workspace).replace("\\", "/")
        knowledge_rel = os.path.relpath(self.knowledge, self.workspace).replace("\\", "/")
        write(self.workspace / ".tp-spec/config/content-systems.yaml", f'''schema: tp-spec.content-systems/v1
systems:
  wiki:
    root: "{wiki_rel}"
  knowledge:
    root: "{knowledge_rel}"
''')
        r = resolve_workspace(self.workspace, installation_config=self.installation)
        self.assertTrue(r["project_content_override"]["redundant"], r["project_content_override"])
        # Extra project-specific retrieval override must be preserved.
        write(self.workspace / ".tp-spec/config/content-systems.yaml", f'''schema: tp-spec.content-systems/v1
systems:
  wiki:
    root: "{wiki_rel}"
  knowledge:
    root: "{knowledge_rel}"
    retrieval:
      include_shared: false
''')
        r = resolve_workspace(self.workspace, installation_config=self.installation)
        self.assertFalse(r["project_content_override"]["redundant"], r["project_content_override"])
        cfg = load_content_systems(self.workspace, installation_config_path=self.installation)
        self.assertFalse(cfg.knowledge_retrieval["include_shared"])


class TestLegacyKnowledgeBindingInference(BaseConvergenceCase):
    def test_existing_knowledge_link_can_seed_binding_when_legacy_registry_has_no_workspace_roots(self):
        reg_path = self.knowledge / "00-system/project-registry.yaml"
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
        reg["projects"][0].pop("workspace_roots", None)
        write(reg_path, yaml.safe_dump(reg, allow_unicode=True, sort_keys=False))
        self._link("knowledge", self.knowledge_project.resolve(strict=False))
        r = resolve_workspace(self.workspace, installation_config=self.installation)
        self.assertTrue(r["knowledge"]["resolved"], r)
        self.assertEqual(r["knowledge"]["project_id"], "demo")
        plan = migration_plan_for_workspace(self.workspace, installation_config=self.installation)
        self.assertEqual(plan["status"], "READY", plan)
        self.assertTrue(any(a.get("action") == "WRITE_PROJECT_BINDING" and a.get("knowledge_id") == "demo" for a in plan["actions"]), plan)


class TestKnowledgeProjectScopeJsonSerializable(BaseConvergenceCase):
    def test_resolve_knowledge_project_scope_is_json_serializable(self):
        """Regression: project_root must be str (not Path) so doctor/status JSON emits cleanly."""
        import json

        from cli.knowledge.common import resolve_knowledge_project

        write_project_binding(
            self.workspace, project_id="demo", wiki_id="ws",
            knowledge_id="demo", base_version="5.1.3",
        )
        cfg = load_content_systems(self.workspace, installation_config_path=self.installation)
        scope = resolve_knowledge_project(cfg, require=False)
        self.assertTrue(scope["resolved"], scope)
        self.assertEqual(scope["project_id"], "demo")
        self.assertIsInstance(scope["project_root"], str)
        json.dumps(scope, ensure_ascii=False)  # must not raise TypeError

    def test_unmapped_scope_is_json_serializable(self):
        import json

        from cli.knowledge.common import resolve_knowledge_project

        cfg = load_content_systems(self.root / "no-such-workspace", installation_config_path=self.installation)
        scope = resolve_knowledge_project(cfg, require=False)
        self.assertFalse(scope["resolved"])
        json.dumps(scope, ensure_ascii=False)  # must not raise TypeError


if __name__ == "__main__":
    unittest.main(verbosity=2)
