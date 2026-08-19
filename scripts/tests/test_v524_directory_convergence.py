from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]

ROLE_IDS = {
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
DOMAIN_AGENTS = {
    "tp-software-lifecycle",
    "tp-project-autonomy",
    "tp-base-maintenance",
    "tp-knowledge",
    "tp-wiki",
}
CAPABILITY_SKILLS = {
    "assumption-management",
    "delivery-planning",
    "implementation-control",
    "knowledge-capture",
    "requirement-clarification",
    "systematic-debugging",
    "task-decomposition",
    "technical-review",
    "testing-strategy",
    "tp-memory-capture",
}
AUTONOMY_SKILLS = {
    "tp-autonomy-setup",
    "tp-autonomy-cycle",
    "tp-autonomy-review",
    "tp-autonomy-integrate",
}


def test_product_entry_is_physically_separate_from_domain_agents():
    assert (BASE / "entry/tp-spec-coding/SKILL.md").is_file()
    assert not (BASE / "agents/tp-spec-coding").exists()
    for agent_id in DOMAIN_AGENTS:
        assert (BASE / f"agents/{agent_id}/SKILL.md").is_file(), agent_id


def test_skills_are_partitioned_by_role_capability_and_autonomy():
    for role_id in ROLE_IDS:
        assert (BASE / f"skills/roles/{role_id}/SKILL.md").is_file(), role_id
        assert not (BASE / f"skills/{role_id}").exists(), role_id
    for skill_id in CAPABILITY_SKILLS:
        assert (BASE / f"skills/capabilities/{skill_id}/SKILL.md").is_file(), skill_id
        assert not (BASE / f"skills/{skill_id}").exists(), skill_id
    for skill_id in AUTONOMY_SKILLS:
        assert (BASE / f"skills/autonomy/{skill_id}/SKILL.md").is_file(), skill_id
        assert not (BASE / f"skills/{skill_id}").exists(), skill_id


def test_role_catalog_is_governance_contract_and_points_to_new_topology():
    catalog_path = BASE / "governance/role-catalog.yaml"
    assert catalog_path.is_file()
    assert not (BASE / "agents/role-catalog.yaml").exists()
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    by_id = {row["workflow_role"]: row for row in catalog["roles"]}
    assert by_id["tp-spec-coding"]["skill_path"] == "entry/tp-spec-coding/SKILL.md"
    for agent_id in DOMAIN_AGENTS:
        assert by_id[agent_id]["skill_path"] == f"agents/{agent_id}/SKILL.md"
    for role_id in ROLE_IDS:
        assert by_id[role_id]["skill_path"] == f"skills/roles/{role_id}/SKILL.md"
    for role in catalog["roles"]:
        for sub in role.get("subskills") or []:
            assert sub["path"].startswith("skills/capabilities/"), (role["workflow_role"], sub)


def test_current_product_docs_use_converged_paths():
    current_docs = [
        BASE / "README.md",
        BASE / "docs/GETTING_STARTED.md",
        BASE / "docs/AGENTS_AND_SKILLS.md",
    ]
    for path in current_docs:
        text = path.read_text(encoding="utf-8")
        assert "agents/role-catalog.yaml" not in text, path
        assert "agents/tp-spec-coding/SKILL.md" not in text, path
    assert "entry/tp-spec-coding/SKILL.md" in (BASE / "docs/AGENTS_AND_SKILLS.md").read_text(encoding="utf-8")
    assert "governance/role-catalog.yaml" in (BASE / "docs/AGENTS_AND_SKILLS.md").read_text(encoding="utf-8")

def test_readme_explains_physical_layering_without_listing_entry_as_agent():
    text = (BASE / "README.md").read_text(encoding="utf-8")
    assert "entry/          唯一默认产品入口" in text
    assert "agents/         Domain Agent" in text
    assert "skills/roles/   软件工程正式 Role Skill" in text
    assert "skills/capabilities/" in text
    assert "skills/autonomy/" in text
    agent_block = text.split("当前公开 Domain Agent：", 1)[1].split("软件领域的 active formal Role", 1)[0]
    assert "tp-spec-coding" not in agent_block
    assert "tp-software-lifecycle" in agent_block

def test_active_product_and_autonomy_surfaces_do_not_reintroduce_retired_workflow_agent():
    active = [
        BASE / "project-entry/tp-spec-readme.md",
        BASE / "project-entry/root-managed-block.md",
        BASE / "agents/tp-project-autonomy/SKILL.md",
        BASE / "skills/autonomy/tp-autonomy-cycle/SKILL.md",
        BASE / "skills/autonomy/tp-autonomy-integrate/SKILL.md",
        BASE / "cli/autonomy_profile.py",
    ]
    for path in active:
        assert "tp-workflow-orchestrator" not in path.read_text(encoding="utf-8"), path
