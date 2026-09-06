from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]
CHECKER = BASE / "scripts" / "check_document_navigation.py"


def _catalog():
    return yaml.safe_load((BASE / "governance" / "role-catalog.yaml").read_text(encoding="utf-8"))


def _public_agent_ids_from_catalog() -> list[str]:
    ids: list[str] = []
    for row in _catalog().get("roles", []):
        role_id = str(row.get("workflow_role") or "")
        skill_path = str(row.get("skill_path") or "")
        if role_id != "tp-spec-coding" and skill_path.startswith("agents/") and skill_path.endswith("/SKILL.md"):
            ids.append(role_id)
    return ids


def _load_checker():
    spec = importlib.util.spec_from_file_location("tp_spec_document_navigation", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_agents_are_catalog_driven_and_each_has_a_guide():
    checker = _load_checker()
    expected = _public_agent_ids_from_catalog()
    assert expected == [
        "tp-software-lifecycle",
        "tp-card-display",
        "tp-project-autonomy",
        "tp-base-maintenance",
        "tp-knowledge",
        "tp-wiki",
    ]
    assert checker.load_public_agent_ids(BASE / "governance" / "role-catalog.yaml") == expected
    for agent_id in expected:
        assert (BASE / f"docs/agents/{agent_id}.md").is_file(), agent_id


def test_software_role_ids_are_catalog_driven():
    checker = _load_checker()
    expected = [
        str(row["workflow_role"])
        for row in _catalog()["roles"]
        if row.get("type") == "workflow-role" and row.get("domain") == "software"
    ]
    assert checker.load_software_role_ids(BASE / "governance" / "role-catalog.yaml") == expected
    assert len(expected) == 9


def test_public_document_navigation_has_no_broken_links_or_process_paths():
    checker = _load_checker()
    assert checker.validate_document_navigation(BASE) == []


def test_full_and_github_ci_run_document_navigation_check():
    full = (BASE / "scripts/ci/Test-TpSpecBase.ps1").read_text(encoding="utf-8")
    github = (BASE / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "check_document_navigation.py" in full
    assert "check_document_navigation.py" in github
    assert "governance/event-semantics.yaml|event-semantics" in full


def test_empty_retired_directory_is_not_a_release_surface_violation(tmp_path):
    checker = _load_checker()
    retired = tmp_path / "docs" / "superpowers"
    retired.mkdir(parents=True)
    assert checker.retired_process_files(tmp_path) == []
    (retired / "plan.md").write_text("process", encoding="utf-8")
    assert checker.retired_process_files(tmp_path) == ["docs/superpowers/plan.md"]
