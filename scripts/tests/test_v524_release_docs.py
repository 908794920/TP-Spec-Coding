from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (BASE / rel).read_text(encoding="utf-8")


def test_readme_exposes_current_entry_and_document_map():
    text = read("README.md")
    assert "tp-spec-coding" in text
    assert "tp-software-lifecycle" in text
    assert "tp-workflow-orchestrator" not in text
    assert "docs/README.md" in text
    assert "## 交给 AI 自动安装" in text


def test_getting_started_links_back_to_ai_install_entry_and_current_model():
    text = read("docs/GETTING_STARTED.md")
    assert "README.md" in text
    assert "交给 AI 自动安装" in text
    assert "tp-spec-coding" in text
    assert "tp-software-lifecycle" in text
    assert "tp-workflow-orchestrator" not in text
    assert "不要重新执行 project init" in text


def test_agents_and_skills_is_current_model_not_migration_history():
    text = read("docs/AGENTS_AND_SKILLS.md")
    assert "entry/tp-spec-coding/SKILL.md" in text
    assert "governance/role-catalog.yaml" in text
    assert "docs/agents/" in text
    assert "历史 previous-contract Action Role" not in text


def test_changelog_keeps_release_history_not_process_plan():
    text = read("CHANGELOG.md")
    assert "## [5.3.0]" in text
    assert "tp-spec-coding" in text
    assert "tp-software-lifecycle" in text
    assert "文档入口" in text
