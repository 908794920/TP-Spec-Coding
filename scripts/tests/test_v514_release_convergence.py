from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from cli import record_first, task_cmd

BASE = Path(__file__).resolve().parents[2]

FLOW_SKILLS = {
    "tp-requirement-analysis",
    "tp-product-design",
    "tp-architecture-design",
    "tp-architecture-review",
    "tp-development-engineering",
    "tp-verification-engineering",
    "tp-delivery-convergence",
}
EXPOSED_AGENTS = {
    "tp-workflow-orchestrator",
    "tp-base-maintenance",
    "tp-knowledge",
    "tp-wiki",
}
LEGACY_CONTRACT = "5.1." + "3"


def test_development_flow_exposes_only_orchestrator_as_agent_entry():
    actual = {path.parent.name for path in (BASE / "agents").glob("tp-*/SKILL.md")}
    assert actual == EXPOSED_AGENTS

    catalog = yaml.safe_load((BASE / "agents/role-catalog.yaml").read_text(encoding="utf-8"))
    by_id = {item["workflow_role"]: item for item in catalog["roles"]}
    assert FLOW_SKILLS <= set(by_id)
    for role_id in FLOW_SKILLS:
        assert by_id[role_id]["skill_path"] == f"skills/{role_id}/SKILL.md"
        assert (BASE / by_id[role_id]["skill_path"]).is_file()


def test_professional_role_ids_remain_runtime_provenance_after_skill_move():
    assert "tp-workflow-orchestrator" not in record_first.ACTORS
    assert FLOW_SKILLS <= set(record_first.ACTORS)


def test_explicit_contract_artifact_is_always_migratable_even_when_not_in_shape_allowlist():
    with tempfile.TemporaryDirectory() as td:
        task_dir = Path(td)
        (task_dir / "tech-design.md").write_text(
            f"---\nartifact: tech-design\nartifact_contract:\n  version: \"{LEGACY_CONTRACT}\"\n---\n\n# Design\n",
            encoding="utf-8",
        )
        result = task_cmd._task_migratable_artifacts(task_dir)
        assert "tech-design.md" in result


def test_post_migration_contract_check_detects_any_leftover_explicit_version():
    with tempfile.TemporaryDirectory() as td:
        task_dir = Path(td)
        (task_dir / "tech-design.md").write_text(
            f"---\nartifact: tech-design\nartifact_contract:\n  version: \"{LEGACY_CONTRACT}\"\n---\n",
            encoding="utf-8",
        )
        assert task_cmd._post_migration_contract_issues(task_dir, "5.2.0") == [f"tech-design.md:{LEGACY_CONTRACT}"]
