from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]


def test_migration_role_map_preserves_current_and_human_identity():
    from cli.migrations.v5_2_3.role_map import map_active_owner

    assert map_active_owner("human_owner") == "human_owner"
    assert map_active_owner("tp-software-lifecycle") == "tp-software-lifecycle"


def test_active_contract_is_only_524():
    assert (BASE / "VERSION").read_text(encoding="utf-8").strip() == "5.2.4"
    compat = yaml.safe_load((BASE / "governance/compat-matrix.yaml").read_text(encoding="utf-8"))
    assert set(compat["contracts"]) == {"5.2.4"}
    assert compat["contracts"]["5.2.4"]["base_version"] == "5.2.4"


def test_governed_role_first_contract_versions_are_524():
    for rel, field in [
        ("governance/workflow.yaml", "version"),
        ("governance/ai-role.yaml", "version"),
        ("governance/orchestration.yaml", "version"),
        ("governance/role-catalog.yaml", "catalog_version"),
    ]:
        data = yaml.safe_load((BASE / rel).read_text(encoding="utf-8"))
        assert str(data[field]) == "5.2.4", rel


def test_only_active_template_contract_is_524():
    templates = BASE / "templates"
    version_dirs = sorted(p.name for p in templates.iterdir() if p.is_dir() and p.name[0].isdigit())
    assert version_dirs == ["5.2.4"]
    assert (templates / "5.2.4/requirement.md").is_file()
    assert not (templates / "5.2.4/requirement-knowledge.md").exists()
