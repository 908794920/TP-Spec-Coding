# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

import importlib


def _module():
    return importlib.import_module("cli.namespace_migration")


def test_legacy_only_is_migration_available_and_apply_moves_state():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        workspace = root / "project"; workspace.mkdir()
        home = root / "home"; home.mkdir()
        (workspace / ".ai-work").mkdir()
        (home / ".ai-work").mkdir()
        (home / ".ai-work" / "installation.yaml").write_text(
            'schema: ai-work.installation/v1\nbase:\n  root: "X"\nsystems:\n  wiki:\n    root: "W"\n  knowledge:\n    root: "K"\n',
            encoding="utf-8",
        )
        plan = _module().namespace_plan(workspace, home=home)
        assert plan["status"] == "MIGRATION_AVAILABLE"
        result = _module().migrate_namespace(workspace, home=home, apply=True)
        assert result["status"] == "PASS"
        assert (workspace / ".tp-spec").is_dir()
        assert (home / ".tp-spec").is_dir()
        assert not (workspace / ".ai-work").exists()
        assert not (home / ".ai-work").exists()
        assert "tp-spec.installation/v1" in (home / ".tp-spec" / "installation.yaml").read_text(encoding="utf-8")


def test_both_project_roots_fail_closed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); workspace = root / "p"; workspace.mkdir(); home = root / "h"; home.mkdir()
        (workspace / ".ai-work").mkdir(); (workspace / ".tp-spec").mkdir()
        plan = _module().namespace_plan(workspace, home=home)
        assert plan["status"] == "BLOCKED"
        assert any("project" in x.lower() for x in plan["blockers"])


def test_migration_preserves_physical_paths_that_only_contain_legacy_brand_text():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); workspace = root / "project"; workspace.mkdir(); home = root / "home"; home.mkdir()
        (workspace / ".ai-work").mkdir()
        (home / ".ai-work").mkdir()
        physical_base = "C:/work/ai-work-base"
        (home / ".ai-work" / "installation.yaml").write_text(
            f'schema: ai-work.installation/v1\nbase:\n  root: "{physical_base}"\n', encoding="utf-8"
        )
        result = _module().migrate_namespace(workspace, home=home, apply=True)
        assert result["status"] == "PASS"
        migrated = (home / ".tp-spec" / "installation.yaml").read_text(encoding="utf-8")
        assert "schema: tp-spec.installation/v1" in migrated
        assert physical_base in migrated
        assert "C:/work/tp-spec-base" not in migrated


def test_migration_does_not_rebrand_unrelated_task_business_text():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); workspace = root / "project"; workspace.mkdir(); home = root / "home"; home.mkdir()
        task_dir = workspace / ".ai-work" / "tasks" / "TASK-X"; task_dir.mkdir(parents=True)
        (task_dir / "task.md").write_text(
            "schema: ai-work.task/v1\n目标：兼容外部仓库 ai-work-tools；运行状态位于 .ai-work/tasks。\n",
            encoding="utf-8",
        )
        result = _module().migrate_namespace(workspace, home=home, apply=True)
        assert result["status"] == "PASS"
        migrated = (workspace / ".tp-spec" / "tasks" / "TASK-X" / "task.md").read_text(encoding="utf-8")
        assert "schema: tp-spec.task/v1" in migrated
        assert "外部仓库 ai-work-tools" in migrated
        assert ".tp-spec/tasks" in migrated
