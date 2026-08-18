# -*- coding: utf-8 -*-
"""TP-Spec-Coding v5.2.4 public-release contract tests."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]
ACTIVE = (BASE / "VERSION").read_text(encoding="utf-8").strip()


def read(rel: str) -> str:
    return (BASE / rel).read_text(encoding="utf-8")


def test_public_brand_and_release_version():
    assert ACTIVE == "5.2.4"
    assert read("README.md").startswith("# TP-Spec-Coding\n")
    assert "TP-Spec-Coding" in read("governance/workflow.yaml")


def test_open_source_surface_is_complete():
    required = {
        "LICENSE",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "docs/GETTING_STARTED.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
    }
    for rel in required:
        assert (BASE / rel).is_file(), rel
    license_text = read("LICENSE")
    assert "MIT License" in license_text
    assert "Permission is hereby granted, free of charge" in license_text
    assert "TP-Spec-Coding" in license_text


def test_public_machine_configuration_examples_are_empty():
    installation = yaml.safe_load(read("config/installation.example.yaml"))
    assert installation == {
        "schema": "tp-spec.installation/v1",
        "base": {"root": ""},
        "systems": {"wiki": {"root": ""}, "knowledge": {"root": ""}},
    }

    workspaces = yaml.safe_load(read("config/workspaces.example.yaml"))
    assert workspaces == {"schema": "tp-spec.workspace-inventory/v1", "workspaces": []}

    registry = json.loads(read("db/registry.local.json.example"))
    assert registry == {"projects": []}

    for rel in (
        "config/installation.example.yaml",
        "config/workspaces.example.yaml",
        "db/registry.local.json.example",
    ):
        text = read(rel)
        assert not re.search(r"(?i)\b[A-Z]:[/\\]", text), rel
        assert "demo" not in text.lower(), rel
        assert "sample-" not in text.lower(), rel


def test_development_flow_has_one_external_lead_and_three_independent_agents():
    exposed = {
        p.parent.name
        for p in (BASE / "agents").glob("*/SKILL.md")
        if p.is_file()
    }
    assert exposed == {
        "tp-spec-coding",
        "tp-software-lifecycle",
        "tp-project-autonomy",
        "tp-base-maintenance",
        "tp-knowledge",
        "tp-wiki",
    }

    catalog = yaml.safe_load(read("agents/role-catalog.yaml"))
    role_paths = {row["workflow_role"]: row["skill_path"] for row in catalog["roles"]}
    internal = {
        "tp-product-manager",
        "tp-software-architect",
        "tp-tech-lead",
        "tp-security-engineer",
        "tp-development-engineer",
        "tp-database-engineer",
        "tp-test-engineer",
        "tp-code-reviewer",
        "tp-integration-engineer",
    }
    for role in internal:
        assert role_paths[role] == f"skills/{role}/SKILL.md"
    for role in ("tp-spec-coding", "tp-software-lifecycle", "tp-project-autonomy", "tp-base-maintenance", "tp-knowledge", "tp-wiki"):
        assert role_paths[role] == f"agents/{role}/SKILL.md"


def test_readme_explains_value_quickstart_agents_and_portability():
    text = read("README.md")
    for needle in (
        "一人项目组",
        "tp-spec-coding",
        "tp-software-lifecycle",
        "tp-project-autonomy",
        "tp-base-maintenance",
        "tp-knowledge",
        "tp-wiki",
        "快速开始",
        "跨机器",
        "base configure",
        "base installation-doctor",
        "Record-first",
        "MIT",
    ):
        assert needle in text, needle


def test_getting_started_supports_ai_assisted_clean_machine_setup():
    text = read("docs/GETTING_STARTED.md")
    for needle in (
        "全新机器",
        "空配置",
        "AI",
        "base configure",
        "base installation-doctor",
        "base sync-project",
        "TP_SPEC_BASE_ROOT",
        "registry.local.json",
    ):
        assert needle in text, needle
    assert not re.search(r"(?i)\b[A-Z]:[/\\](?:Users|work|src|tools)", text)


def test_only_active_task_template_contract_is_shipped():
    dirs = {p.name for p in (BASE / "templates").iterdir() if p.is_dir()}
    assert dirs == {ACTIVE}
    status = yaml.safe_load(read(f"templates/{ACTIVE}/status.yaml"))
    assert status["base_version"] == ACTIVE
    assert status["artifact_contract"]["version"] == ACTIVE


def test_active_governance_and_catalog_are_v520():
    assert yaml.safe_load(read("governance/workflow.yaml"))["version"] == ACTIVE
    assert yaml.safe_load(read("governance/ai-role.yaml"))["version"] == ACTIVE
    assert yaml.safe_load(read("governance/orchestration.yaml"))["version"] == ACTIVE
    catalog = yaml.safe_load(read("agents/role-catalog.yaml"))
    assert catalog["catalog_version"] == ACTIVE
    assert catalog["base_version"] == ACTIVE
    compat = yaml.safe_load(read("governance/compat-matrix.yaml"))
    assert set(compat["contracts"]) == {ACTIVE}
    assert compat["contracts"][ACTIVE]["status_contract"] == ACTIVE


def test_internal_upgrade_reports_are_not_part_of_public_release():
    tracked_reports = [p for p in (BASE / "reports").glob("*") if p.is_file()] if (BASE / "reports").exists() else []
    assert tracked_reports == []


def test_version_purity_scanner_rejects_previous_minor_after_v520_cutover():
    import importlib.util

    scanner_path = BASE / "scripts" / "check_version_consistency.py"
    spec = importlib.util.spec_from_file_location("v520_purity", scanner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    legacy_re = module._build_legacy_re("5.2.4")
    previous = "5.1." + "4"
    match = legacy_re.search(f"active contract {previous} must not survive in live files")
    assert match is not None
    assert module._is_legacy_dotted(match.group(0), "5.2.4")


def test_public_repo_has_reproducible_dependencies_and_github_ci():
    for rel in ("requirements.txt", "requirements-dev.txt", ".github/workflows/ci.yml"):
        assert (BASE / rel).is_file(), rel
    runtime = read("requirements.txt")
    assert "PyYAML" in runtime
    assert "jsonschema" in runtime
    dev = read("requirements-dev.txt")
    assert "pytest" in dev
    ci = read(".github/workflows/ci.yml")
    assert "pytest" in ci
    assert "update_manifest.py --verify-release" in ci
    assert "check_version_consistency.py" in ci
    assert "update_role_catalog.py --verify" in ci


def test_blank_installation_profile_is_a_valid_unconfigured_template(tmp_path):
    from cli.environment import load_installation_config

    path = tmp_path / "installation.yaml"
    path.write_text(
        "schema: tp-spec.installation/v1\n"
        "base:\n  root: \"\"\n"
        "systems:\n  wiki:\n    root: \"\"\n  knowledge:\n    root: \"\"\n",
        encoding="utf-8",
    )
    cfg = load_installation_config(path)
    assert cfg.exists is True
    assert cfg.base_root is None
    assert cfg.wiki_root is None
    assert cfg.knowledge_root is None


def test_project_init_creates_portable_binding_for_public_onboarding(tmp_path):
    from cli import project_cmd

    workspace = tmp_path / "renamed-folder"
    workspace.mkdir()
    registry = tmp_path / "registry.local.json"
    registry.write_text('{"projects": []}\n', encoding="utf-8")
    args = type("Args", (), {
        "id": "stable-project-id",
        "name": None,
        "root": str(workspace),
        "base_version": ACTIVE,
        "db": None,
        "registry": str(registry),
    })()

    assert project_cmd.cmd_project_init(args) == 0
    binding_path = workspace / ".tp-spec" / "config" / "project-binding.yaml"
    assert binding_path.is_file()
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    assert binding == {
        "schema": "tp-spec.project-binding/v1",
        "project": {"id": "stable-project-id"},
        "base_version": ACTIVE,
    }


def test_project_init_refuses_to_overwrite_conflicting_portable_binding(tmp_path):
    from cli import project_cmd

    workspace = tmp_path / "workspace"
    binding_path = workspace / ".tp-spec" / "config" / "project-binding.yaml"
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text(
        "schema: tp-spec.project-binding/v1\n"
        "project:\n  id: existing-project\n"
        f'base_version: "{ACTIVE}"\n',
        encoding="utf-8",
    )
    registry = tmp_path / "registry.local.json"
    registry.write_text('{"projects": []}\n', encoding="utf-8")
    args = type("Args", (), {
        "id": "different-project",
        "name": None,
        "root": str(workspace),
        "base_version": ACTIVE,
        "db": None,
        "registry": str(registry),
    })()

    assert project_cmd.cmd_project_init(args) != 0
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    assert binding["project"]["id"] == "existing-project"
    assert not (workspace / ".tp-spec" / "db" / "different-project.db").exists()




def test_contributing_documents_git_release_closure():
    text = read("CONTRIBUTING.md")
    for needle in (
        "git add -A",
        "update_manifest.py --verify-release",
        "Test-TpSpecBase.ps1 -Mode Full",
        "Git Tag",
        "GitHub Release",
    ):
        assert needle in text, needle
    assert "full.release.git_manifest" in read("scripts/ci/Test-TpSpecBase.ps1")

def test_release_manifest_gate_distinguishes_working_tree_from_git_release(tmp_path):
    """A visible but untracked file may pass dev verify, but must fail release verify."""
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(BASE / "scripts" / "update_manifest.py", scripts / "update_manifest.py")
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in tuple(env):
            if key.startswith("GIT_"):
                env.pop(key, None)
        return subprocess.run(
            list(args),
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
            env=env,
        )

    assert run("git", "init").returncode == 0
    assert run("git", "config", "core.autocrlf", "false").returncode == 0
    assert run("git", "add", "scripts/update_manifest.py", "tracked.txt").returncode == 0

    generated = run(sys.executable, "scripts/update_manifest.py")
    assert generated.returncode == 0, generated.stderr
    assert run("git", "add", "manifest.sha256").returncode == 0

    clean_release = run(sys.executable, "scripts/update_manifest.py", "--verify-release")
    assert clean_release.returncode == 0, clean_release.stderr

    # Reproduce the v5.2.4 publication failure mode: the file is visible and
    # included by the development manifest, but it was never git-added.
    (repo / "release-surface.txt").write_text("untracked\n", encoding="utf-8")
    regenerated = run(sys.executable, "scripts/update_manifest.py")
    assert regenerated.returncode == 0, regenerated.stderr

    dev_verify = run(sys.executable, "scripts/update_manifest.py", "--verify")
    assert dev_verify.returncode == 0, dev_verify.stderr

    release_verify = run(sys.executable, "scripts/update_manifest.py", "--verify-release")
    assert release_verify.returncode != 0
    combined = release_verify.stdout + release_verify.stderr
    assert "release-surface.txt" in combined
    assert "untracked" in combined.lower()

def test_public_project_entry_uses_tp_spec_coding_brand():
    for rel in ("project-entry/root-managed-block.md", "project-entry/tp-spec-readme.md"):
        text = read(rel)
        assert "TP-Spec-Coding" in text
        assert "TP-Spec " not in text
