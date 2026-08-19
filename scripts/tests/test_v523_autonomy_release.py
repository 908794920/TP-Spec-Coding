from pathlib import Path
import yaml

from cli.version import active_version

BASE=Path(__file__).resolve().parents[2]


def test_v523_is_single_active_contract_and_autonomy_surface_is_shipped():
    assert active_version()=="5.2.4"
    assert (BASE/"templates/5.2.4/status.yaml").is_file()
    previous = "5.2." + "2"
    assert not (BASE/"templates"/previous).exists()
    for path in [
        BASE/"agents/tp-project-autonomy/SKILL.md",
        BASE/"skills/autonomy/tp-autonomy-setup/SKILL.md",
        BASE/"skills/autonomy/tp-autonomy-cycle/SKILL.md",
        BASE/"skills/autonomy/tp-autonomy-review/SKILL.md",
        BASE/"skills/autonomy/tp-autonomy-integrate/SKILL.md",
        BASE/"automation/autonomy/SCHEDULER_BOOTSTRAP.md",
        BASE/"automation/autonomy/autonomous-cycle.md",
    ]:
        assert path.is_file(), path
    catalog=yaml.safe_load((BASE/"governance/role-catalog.yaml").read_text(encoding="utf-8"))
    by_id={x["workflow_role"]:x for x in catalog["roles"]}
    assert by_id["tp-project-autonomy"]["skill_path"]=="agents/tp-project-autonomy/SKILL.md"


def test_autonomy_helpers_are_skills_not_parallel_workflow_roles():
    catalog=yaml.safe_load((BASE/"governance/role-catalog.yaml").read_text(encoding="utf-8"))
    role_ids={x["workflow_role"] for x in catalog["roles"]}
    assert "tp-project-autonomy" in role_ids
    assert not ({"tp-autonomy-setup","tp-autonomy-cycle","tp-autonomy-review","tp-autonomy-integrate"} & role_ids)
