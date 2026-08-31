from __future__ import annotations

from pathlib import Path

import pytest

from cli import orchestration
from scripts.tests.v514_orchestration_testutil import (
    add_checkpoint,
    add_code_review,
    add_decision,
    add_verify,
    make_db,
)

BASE = Path(__file__).resolve().parents[2]


def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, level: str) -> str:
    monkeypatch.setenv("TP_SPEC_USER_ROOT", str(tmp_path / "user-root"))
    return make_db(tmp_path / f"{level}.db", risk=level, flow=level)


@pytest.mark.parametrize(
    ("level", "signals", "expected"),
    [
        (
            "L0",
            ("workflow:behavioral-change", "workflow:deep-review"),
            {
                "development": (True, ""),
                "verification": (False, "behavioral_change"),
                "review": (False, "deep_review"),
            },
        ),
        (
            "L1",
            ("workflow:include-stage:planning", "workflow:deep-review"),
            {
                "requirement": (True, ""),
                "architecture": (True, ""),
                "planning": (False, "contextual"),
                "development": (True, ""),
                "verification": (True, ""),
                "review": (False, "deep_review"),
            },
        ),
        (
            "L2",
            ("workflow:include-stage:product", "workflow:include-stage:architecture_review"),
            {
                "requirement": (True, ""),
                "product": (False, "contextual"),
                "architecture": (True, ""),
                "architecture_review": (False, "architecture_risk"),
                "planning": (True, ""),
                "development": (True, ""),
                "verification": (True, ""),
                "review": (True, ""),
                "delivery": (True, ""),
            },
        ),
        (
            "L3",
            ("workflow:include-stage:product",),
            {
                "requirement": (True, ""),
                "product": (False, "contextual"),
                "architecture": (True, ""),
                "architecture_review": (False, "architecture_risk"),
                "planning": (True, ""),
                "development": (True, ""),
                "verification": (True, ""),
                "review": (True, ""),
                "delivery": (True, ""),
            },
        ),
    ],
)
def test_progress_steps_preserve_required_trigger_and_definition_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    signals: tuple[str, ...],
    expected: dict[str, tuple[bool, str]],
):
    db = _db(tmp_path, monkeypatch, level=level)
    for signal in signals:
        add_decision(db, "TASK-V514", signal)

    progress = orchestration.resolve_progress("TASK-V514", db_path=db)
    by_stage = {step["stage"]: step for step in progress["steps"]}

    assert set(by_stage) == set(expected)
    for stage, (required, trigger) in expected.items():
        assert by_stage[stage]["required"] is required
        assert by_stage[stage]["trigger"] == trigger
        assert by_stage[stage]["definition_source"] == "workflow.pipeline"


def test_progress_projects_security_and_database_as_conditional_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    add_decision(db, "TASK-V514", "workflow:security-risk")
    add_decision(db, "TASK-V514", "workflow:database-risk")

    progress = orchestration.resolve_progress("TASK-V514", db_path=db)
    roles = {item["role_id"]: item for item in progress["conditional_roles"]}

    assert set(roles) == {"tp-security-engineer", "tp-database-engineer"}
    assert roles["tp-security-engineer"]["role_display"]["label"] == "tp-安全工程师"
    assert roles["tp-security-engineer"]["trigger"] == "security_risk"
    assert roles["tp-security-engineer"]["reason_code"] == "SECURITY_RISK"
    assert roles["tp-database-engineer"]["role_display"]["label"] == "tp-数据库工程师"
    assert roles["tp-database-engineer"]["trigger"] == "database_risk"
    assert roles["tp-database-engineer"]["reason_code"] == "DATABASE_RISK"
    assert all(item["definition_source"] == "workflow.conditional_roles" for item in roles.values())


def test_progress_deduplicates_conditional_role_already_used_by_pipeline_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    task = "TASK-V514"
    add_checkpoint(db, task, "tp-product-manager", "requirement")
    add_checkpoint(db, task, "tp-software-architect", "architecture")
    add_checkpoint(db, task, "tp-development-engineer", "development")
    add_verify(db, task, "PASS")
    add_decision(db, task, "workflow:deep-review")

    route = orchestration.resolve_route(task, db_path=db)
    assert route["next_stage"] == "review"
    assert {item["role_id"] for item in route["recommended_roles"]} == {"tp-code-reviewer"}

    progress = orchestration.resolve_progress(task, db_path=db)
    assert "tp-code-reviewer" in {step["role"] for step in progress["steps"]}
    assert "tp-code-reviewer" not in {item["role_id"] for item in progress["conditional_roles"]}


def test_progress_complete_terminal_has_no_execution_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    monkeypatch.setattr(
        orchestration,
        "resolve_route",
        lambda *args, **kwargs: {
            "effective_level": "L1",
            "next_stage": "complete",
            "role_id": None,
            "recommended_action": "task_complete",
            "confirmation_required": False,
            "confirmation_reason": "",
            "reason_codes": ["PIPELINE_COMPLETE"],
            "decision": "TASK_COMPLETE",
            "recommended_roles": [],
        },
    )

    progress = orchestration.resolve_progress("TASK-V514", db_path=db)

    assert progress["next_step"]["stage"] == "complete"
    assert progress["next_step"]["role"] == ""
    assert progress["next_step"]["role_display"]["label"] == ""


def test_progress_projection_does_not_change_review_rework_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    task = "TASK-V514"
    add_checkpoint(db, task, "tp-product-manager", "requirement")
    add_checkpoint(db, task, "tp-software-architect", "architecture")
    add_checkpoint(db, task, "tp-development-engineer", "development")
    add_verify(db, task, "PASS")
    add_decision(db, task, "workflow:deep-review")
    add_code_review(db, task, "NEEDS_FIX")

    keys = (
        "next_stage",
        "role_id",
        "recommended_action",
        "reason_codes",
        "confirmation_required",
    )
    before = orchestration.resolve_route(task, db_path=db)
    orchestration.resolve_progress(task, db_path=db)
    after = orchestration.resolve_route(task, db_path=db)

    assert {key: after.get(key) for key in keys} == {key: before.get(key) for key in keys}
    assert after["next_stage"] == "development"
    assert after["role_id"] == "tp-development-engineer"


def test_task_card_visually_separates_steps_execution_roles_and_conditional_roles():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "工作步骤" in text
    assert "执行角色：" in text
    assert "条件参与角色" in text
    assert "必需步骤" in text
    assert "条件步骤" in text
    assert "角色代表专业职责/SKILL，不代表独立人员" in text
    assert "definition_source" in text
    assert "reason_code" in text
    assert '"workflow.conditional_roles"' not in text  # definition source value comes from projection data
