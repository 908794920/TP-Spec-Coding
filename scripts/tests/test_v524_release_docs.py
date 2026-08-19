from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (BASE / rel).read_text(encoding="utf-8")


def test_readme_exposes_only_current_product_and_software_domain_entry():
    text = read("README.md")
    assert "tp-spec-coding" in text
    assert "tp-software-lifecycle" in text
    assert "tp-workflow-orchestrator" not in text
    assert "previous active contract → 5.2.4 migration/history" in text


def test_getting_started_uses_role_first_entry_and_formal_roles():
    text = read("docs/GETTING_STARTED.md")
    assert "tp-spec-coding" in text
    assert "entry/tp-spec-coding/SKILL.md" in text
    assert "tp-software-lifecycle" in text
    assert "tp-workflow-orchestrator" not in text
    for role in (
        "tp-product-manager",
        "tp-software-architect",
        "tp-tech-lead",
        "tp-security-engineer",
        "tp-development-engineer",
        "tp-database-engineer",
        "tp-test-engineer",
        "tp-code-reviewer",
        "tp-integration-engineer",
    ):
        assert role in text


def test_agents_and_skills_describes_old_actions_as_v523_history():
    text = read("docs/AGENTS_AND_SKILLS.md")
    assert "历史 previous-contract Action Role" in text
    assert "历史 v5.2.4 Action Role" not in text


def test_changelog_has_v524_role_first_release_entry():
    text = read("CHANGELOG.md")
    assert "## [5.2.4]" in text
    assert "Role-first" in text
    assert "tp-spec-coding" in text
    assert "tp-software-lifecycle" in text
