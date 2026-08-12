# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

from cli.content_systems import load_content_systems  # noqa: E402
from cli.project_portability import normalize_project_portability, project_portability_plan  # noqa: E402
from cli.project_surface import MANAGED_END, MANAGED_START, project_surface_plan, sync_project_surface  # noqa: E402
from scripts.check_portability import scan as portability_scan  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class PortabilityCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "sample-app"
        self.workspace.mkdir()
        self.wiki = self.root / "wiki-system"
        self.knowledge = self.root / "knowledge-system"
        self.wiki.mkdir(); self.knowledge.mkdir()
        self.install = self.root / "installation.yaml"
        write(self.install, yaml.safe_dump({
            "schema": "ai-work.installation/v1",
            "base": {"root": str(BASE)},
            "systems": {"wiki": {"root": str(self.wiki)}, "knowledge": {"root": str(self.knowledge)}},
        }, sort_keys=False))
        write(self.workspace / ".ai-work/config/project-binding.yaml", """schema: ai-work.project-binding/v1
project:
  id: sample-app
  wiki_id: sample-app
  knowledge_id: sample-app
base_version: 5.1.3
""")

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_surface_is_created_without_machine_paths(self):
        plan = project_surface_plan(self.workspace)
        self.assertEqual(plan["status"], "SYNC_AVAILABLE")
        result = sync_project_surface(self.workspace, apply=True)
        self.assertEqual(result["status"], "CURRENT")
        for rel in ("README.md", "AGENTS.md", ".ai-work/README.md"):
            text = (self.workspace / rel).read_text(encoding="utf-8")
            self.assertNotIn(str(self.root), text)
            self.assertNotIn(str(BASE), text)
        self.assertIn(MANAGED_START, (self.workspace / "README.md").read_text(encoding="utf-8"))
        self.assertIn(MANAGED_END, (self.workspace / "AGENTS.md").read_text(encoding="utf-8"))

    def test_root_readme_custom_content_is_preserved(self):
        write(self.workspace / "README.md", "# Product\n\ncustom intro\n\ncustom tail\n")
        sync_project_surface(self.workspace, apply=True)
        text = (self.workspace / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Product", text)
        self.assertIn("custom intro", text)
        self.assertIn("custom tail", text)
        self.assertEqual(text.count(MANAGED_START), 1)

    def test_legacy_managed_block_and_runtime_readme_are_replaced_without_touching_project_text(self):
        write(
            self.workspace / "README.md",
            f"# Product\n\nproject-owned\n\n{MANAGED_START}\nlegacy machine path: D:/private/old-base\n{MANAGED_END}\n\nkeep-tail\n",
        )
        write(self.workspace / ".ai-work/README.md", "legacy runtime instructions D:/private/old-base\n")
        result = sync_project_surface(self.workspace, apply=True)
        self.assertEqual(result["status"], "CURRENT")
        root_text = (self.workspace / "README.md").read_text(encoding="utf-8")
        runtime_text = (self.workspace / ".ai-work/README.md").read_text(encoding="utf-8")
        self.assertIn("project-owned", root_text)
        self.assertIn("keep-tail", root_text)
        self.assertNotIn("D:/private/old-base", root_text)
        self.assertNotIn("D:/private/old-base", runtime_text)
        self.assertEqual(root_text.count(MANAGED_START), 1)

    def test_malformed_managed_markers_fail_closed(self):
        write(self.workspace / "AGENTS.md", f"{MANAGED_START}\nbroken\n")
        result = sync_project_surface(self.workspace, apply=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("broken", (self.workspace / "AGENTS.md").read_text(encoding="utf-8"))

    def test_redundant_machine_roots_are_removed_and_empty_override_deleted(self):
        write(self.workspace / ".ai-work/config/content-systems.yaml", yaml.safe_dump({
            "schema": "ai-work.content-systems/v1",
            "paths": {"ai_work_root": ""},
            "systems": {
                "wiki": {"enabled": True, "root": str(self.wiki), "registry": ""},
                "knowledge": {"enabled": True, "root": str(self.knowledge)},
            },
        }, sort_keys=False))
        result = normalize_project_portability(self.workspace, installation_config=self.install, apply=True)
        self.assertEqual(result["status"], "CURRENT")
        self.assertFalse((self.workspace / ".ai-work/config/content-systems.yaml").exists())

    def test_project_semantic_override_survives_machine_root_cleanup(self):
        write(self.workspace / ".ai-work/config/content-systems.yaml", yaml.safe_dump({
            "schema": "ai-work.content-systems/v1",
            "systems": {
                "wiki": {"root": str(self.wiki), "coverage": {"no_doc_globs": ["**/vendor/**"]}},
                "knowledge": {"root": str(self.knowledge)},
            },
        }, sort_keys=False))
        normalize_project_portability(self.workspace, installation_config=self.install, apply=True)
        data = yaml.safe_load((self.workspace / ".ai-work/config/content-systems.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["systems"]["wiki"]["coverage"]["no_doc_globs"], ["**/vendor/**"])
        self.assertNotIn("root", data["systems"]["wiki"])
        self.assertNotIn("knowledge", data.get("systems", {}))

    def test_different_absolute_project_root_is_blocked(self):
        other = self.root / "other-wiki"
        write(self.workspace / ".ai-work/config/content-systems.yaml", yaml.safe_dump({
            "schema": "ai-work.content-systems/v1",
            "systems": {"wiki": {"root": str(other)}},
        }, sort_keys=False))
        plan = project_portability_plan(self.workspace, installation_config=self.install)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertTrue(plan["blockers"])

    def test_legacy_projection_filename_remains_readable_via_configured_candidate(self):
        # Public defaults must stay machine/user neutral. Legacy projection names are
        # therefore opt-in compatibility data supplied by a project override.
        legacy = ".ai-kb/legacy-projection.db"
        write(self.workspace / ".ai-work/config/content-systems.yaml", yaml.safe_dump({
            "schema": "ai-work.content-systems/v1",
            "systems": {
                "knowledge": {
                    "projection": {
                        "legacy_databases": [legacy],
                    },
                },
            },
        }, sort_keys=False))
        legacy_path = self.knowledge / legacy
        write(legacy_path, "legacy-placeholder")
        cfg = load_content_systems(self.workspace, installation_config_path=self.install)
        self.assertEqual(cfg.paths.knowledge_projection_db, legacy_path.resolve(strict=False))

    def test_base_source_has_no_machine_fingerprints_outside_compat_config(self):
        self.assertEqual(portability_scan(), [])


if __name__ == "__main__":
    unittest.main()
