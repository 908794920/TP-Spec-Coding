from pathlib import Path

from cli import anchor_check, projection_cmd, receipt_cmd, rework_cmd, reuse_warnings, task_cmd, work_session_cmd


def test_task_creation_owner_is_software_lifecycle():
    assert task_cmd.INITIAL_TASK_OWNER == "tp-software-lifecycle"


def test_session_rework_and_projection_fallback_to_software_lifecycle():
    assert work_session_cmd.DEFAULT_ROLE == "tp-software-lifecycle"
    assert rework_cmd.DEFAULT_ROLE == "tp-software-lifecycle"
    assert projection_cmd.DEFAULT_OWNER_ROLE == "tp-software-lifecycle"


def test_receipt_actor_allowlist_uses_formal_roles_only():
    expected = {
        "tp-product-manager", "tp-software-architect", "tp-tech-lead",
        "tp-security-engineer", "tp-development-engineer", "tp-database-engineer",
        "tp-test-engineer", "tp-code-reviewer", "tp-integration-engineer", "human_owner",
    }
    assert expected.issubset(set(receipt_cmd._ALLOWED_ACTORS))
    from cli.migrations.v5_2_3.role_map import ROLE_MAP
    assert not set(ROLE_MAP).intersection(receipt_cmd._ALLOWED_ACTORS)


def test_review_warning_and_anchor_handoff_use_formal_reviewer_language():
    assert "tp-code-reviewer" in reuse_warnings.W5_EN
    assert "tp-test-engineer" not in reuse_warnings.W5_EN
    assert "tp-code-reviewer" in anchor_check.__doc__
