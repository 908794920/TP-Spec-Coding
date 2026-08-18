# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from cli import environment, orchestration, record_first
from scripts.tests.v514_orchestration_testutil import (
    make_db, add_checkpoint, add_decision, add_review, add_verify, add_code_review, add_workflow_confirmation,
)


def _complete_l2_until_verification(db: str, task: str) -> None:
    add_checkpoint(db, task, "tp-product-manager", "requirement", "req")
    add_checkpoint(db, task, "tp-software-architect", "architecture", "arch")
    add_checkpoint(db, task, "tp-tech-lead", "planning", "plan")
    add_workflow_confirmation(db, task)
    add_checkpoint(db, task, "tp-development-engineer", "development", "dev")
    add_verify(db, task, "PASS")
    add_code_review(db, task, "PASS")


def test_project_runtime_default_is_tp_spec():
    with tempfile.TemporaryDirectory() as td:
        p = environment.default_binding_path(Path(td))
        assert p.parts[-3:] == (".tp-spec", "config", "project-binding.yaml")


def test_l2_routes_to_required_delivery_after_verification():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "p" / ".tp-spec" / "db" / "a.db", risk="L2", flow="L2")
        _complete_l2_until_verification(db, "TASK-V514")
        route = orchestration.resolve_route("TASK-V514", db_path=db)
        assert route["next_stage"] == "delivery"
        assert route["role_id"] == "tp-integration-engineer"
        assert route["context"]["mode"] == "FAST_PATH"
        assert route["context"]["max_incremental_ai_overhead_percent"] == 5
        assert route["context"]["subagents"] == "forbidden-by-default"


def test_l3_routes_to_required_delivery_after_verification():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "p" / ".tp-spec" / "db" / "a.db", risk="L3", flow="L3")
        add_checkpoint(db, "TASK-V514", "tp-product-manager", "requirement", "req")
        add_checkpoint(db, "TASK-V514", "tp-software-architect", "architecture", "arch")
        add_review(db, "TASK-V514", "PASS")
        add_checkpoint(db, "TASK-V514", "tp-tech-lead", "planning", "plan")
        add_workflow_confirmation(db, "TASK-V514")
        add_checkpoint(db, "TASK-V514", "tp-development-engineer", "development", "dev")
        add_verify(db, "TASK-V514", "PASS")
        add_code_review(db, "TASK-V514", "PASS")
        route = orchestration.resolve_route("TASK-V514", db_path=db)
        assert route["next_stage"] == "delivery"
        assert route["role_id"] == "tp-integration-engineer"


def test_task_complete_rejects_pending_delivery():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "p"
        db = make_db(root / ".tp-spec" / "db" / "a.db", risk="L2", flow="L2")
        _complete_l2_until_verification(db, "TASK-V514")
        task_dir = root / ".tp-spec" / "tasks" / "TASK-V514"
        task_dir.mkdir(parents=True)
        try:
            record_first.complete(
                task_id="TASK-V514", task_dir=str(task_dir),
                actor="tp-test-engineer", summary="done", db=db,
            )
        except ValueError as exc:
            assert "INTEGRITY_PIPELINE_PENDING" in str(exc)
        else:
            raise AssertionError("complete must reject while required delivery is pending")


def test_delivery_checkpoint_does_not_substitute_for_structured_delivery_result():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "p"
        db = make_db(root / ".tp-spec" / "db" / "a.db", risk="L2", flow="L2")
        _complete_l2_until_verification(db, "TASK-V514")
        add_checkpoint(db, "TASK-V514", "tp-integration-engineer", "delivery", "delivery done")
        route = orchestration.resolve_route("TASK-V514", db_path=db)
        assert route["recommended_action"] == "dispatch_role"
        assert route["next_stage"] == "delivery"


def test_development_workflow_never_dispatches_tp_knowledge():
    contract = yaml.safe_load((Path(__file__).parents[2] / "governance" / "orchestration.yaml").read_text(encoding="utf-8"))
    roles = {step["role"] for pipeline in contract["pipelines"].values() for step in pipeline}
    assert "tp-knowledge" not in roles
