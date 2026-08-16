from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path

from cli import main as climain
from cli import orchestration
from scripts.tests.v514_orchestration_testutil import make_db

BASE = Path(__file__).resolve().parents[2]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = climain.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_every_pipeline_stage_declares_known_effects_and_current_mutation_surface_is_explicit():
    contract = orchestration.load_contract(BASE)
    seen = set()
    for level, pipeline in contract["pipelines"].items():
        for step in pipeline:
            effects = step.get("effects")
            assert isinstance(effects, list), (level, step)
            assert set(effects) <= {"repo_mutation"}, (level, step)
            seen.add((step["stage"], tuple(effects)))
    assert ("development", ("repo_mutation",)) in seen
    for stage in {"requirement", "product", "architecture", "architecture_review", "verification", "delivery"}:
        assert not any(s == stage and "repo_mutation" in effects for s, effects in seen)


def test_workflow_route_json_exposes_stable_workflow_decision_contract_without_breaking_route_schema():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "a.db", risk="L0", flow="L0")
        rc, out, err = run(["workflow", "next", "--task", "TASK-V514", "--db", db, "--json"])
        assert rc == 0, (out, err)
        data = json.loads(out)
        assert data["schema"] == "tp-spec.workflow-route/v1"
        assert data["decision_schema"] == "tp-spec.workflow-decision/v1"
        assert data["decision"] == "DISPATCH_ROLE"
        assert data["required_effects"] == ["repo_mutation"]
        assert data["requires_human"] is False
        assert data["reason"] == "dispatch_role"


def test_execution_envelope_blocks_repo_mutation_by_effect_not_role_name():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "a.db", risk="L0", flow="L0")
        route = orchestration.resolve_route("TASK-V514", db_path=db, allowed_effects=[])
        assert route["decision"] == "BOUNDARY_REACHED"
        assert route["required_effects"] == ["repo_mutation"]
        assert route["requires_human"] is True
        assert route["role_id"] is None
        assert route["recommended_action"] == "await_effect_approval"
        assert route["reason"] == "effect_not_allowed"


def test_workflow_next_cli_can_supply_explicit_allowed_effects_for_external_controllers():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "a.db", risk="L0", flow="L0")
        rc, out, err = run([
            "workflow", "next", "--task", "TASK-V514", "--db", db,
            "--allowed-effect", "repo_mutation", "--json",
        ])
        assert rc == 0, (out, err)
        data = json.loads(out)
        assert data["decision"] == "DISPATCH_ROLE"
        assert data["allowed_effects"] == ["repo_mutation"]
