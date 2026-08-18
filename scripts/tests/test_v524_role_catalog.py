from pathlib import Path
import sys
import yaml

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

CANONICAL_ROLES = {
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
    "tp-spec-coding",
    "tp-software-lifecycle",
    "tp-project-autonomy",
    "tp-base-maintenance",
    "tp-knowledge",
    "tp-wiki",
}
from cli.migrations.v5_2_3.role_map import ROLE_MAP
OLD = set(ROLE_MAP) | {"tp-workflow-orchestrator"}


def _catalog():
    return yaml.safe_load((BASE / "agents/role-catalog.yaml").read_text(encoding="utf-8"))


def test_catalog_has_only_new_active_role_model():
    c = _catalog()
    ids = {r["workflow_role"] for r in c["roles"]}
    assert CANONICAL_ROLES <= ids
    assert DOMAIN_AGENTS <= ids
    assert not (OLD & ids)
    assert c["state_owner_map"] == {"NEW": "tp-software-lifecycle", "CANCELLED": "human_owner"}


def test_formal_roles_declare_domain_phase_and_capabilities():
    c = _catalog()
    by_id = {r["workflow_role"]: r for r in c["roles"]}
    for role_id in CANONICAL_ROLES:
        row = by_id[role_id]
        assert row["type"] == "workflow-role"
        assert row["domain"] == "software"
        assert row["phases"]
        assert row["capabilities"]
        assert (BASE / row["skill_path"]).is_file()


def test_mode_hosts_are_declared_on_formal_roles():
    c = _catalog()
    by_id = {r["workflow_role"]: r for r in c["roles"]}
    assert "auto_planning_host" in by_id["tp-software-architect"]["orchestration_capabilities"]
    assert "auto_review_host" in by_id["tp-code-reviewer"]["orchestration_capabilities"]


def test_subskill_paths_are_real():
    c = _catalog()
    for role in c["roles"]:
        for sub in role.get("subskills") or []:
            assert sub["id"]
            assert (BASE / sub["path"]).is_file(), (role["workflow_role"], sub)
