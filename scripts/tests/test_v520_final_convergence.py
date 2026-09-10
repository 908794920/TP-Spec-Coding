# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from cli import environment, orchestration, record_first
from scripts.tests.v514_orchestration_testutil import make_bound_runtime


def _complete_l2_until_verification(root: Path):
    return make_bound_runtime(root, level="L2")


def test_project_runtime_default_is_tp_spec():
    with tempfile.TemporaryDirectory() as td:
        p = environment.default_binding_path(Path(td))
        assert p.parts[-3:] == (".tp-spec", "config", "project-binding.yaml")


def test_l2_routes_to_required_delivery_after_verification(tmp_path):
    db, _ = _complete_l2_until_verification(tmp_path)
    route = orchestration.resolve_route("TASK-V514", db_path=db)
    assert route["next_stage"] == "delivery"
    assert route["role_id"] == "tp-integration-engineer"
    assert route["context"]["mode"] == "FAST_PATH"
    assert route["context"]["max_incremental_ai_overhead_percent"] == 5
    assert route["context"]["subagents"] == "forbidden-by-default"


def test_l3_routes_to_required_delivery_after_verification(tmp_path):
    db, _ = make_bound_runtime(tmp_path, level="L3")
    route = orchestration.resolve_route("TASK-V514", db_path=db)
    assert route["next_stage"] == "delivery"
    assert route["role_id"] == "tp-integration-engineer"


def test_task_complete_rejects_pending_delivery(tmp_path):
    db, task_dir = _complete_l2_until_verification(tmp_path)
    try:
        record_first.complete(task_id="TASK-V514", task_dir=str(task_dir),
                              actor="tp-test-engineer", summary="done", db=db)
    except ValueError as exc:
        assert "INTEGRITY_PIPELINE_PENDING" in str(exc)
    else:
        raise AssertionError("complete must reject while required delivery is pending")


def test_delivery_checkpoint_does_not_substitute_for_structured_delivery_result(tmp_path):
    db, task_dir = _complete_l2_until_verification(tmp_path)
    record_first.checkpoint(task_id="TASK-V514", task_dir=str(task_dir), actor="tp-integration-engineer",
                            phase="delivery", summary="plain checkpoint, not delivery acceptance", db=db)
    route = orchestration.resolve_route("TASK-V514", db_path=db)
    assert route["recommended_action"] == "dispatch_role"
    assert route["next_stage"] == "delivery"


def test_development_workflow_never_dispatches_tp_knowledge():
    contract = yaml.safe_load((Path(__file__).parents[2] / "governance" / "orchestration.yaml").read_text(encoding="utf-8"))
    roles = {step["role"] for pipeline in contract["pipelines"].values() for step in pipeline}
    assert "tp-knowledge" not in roles
