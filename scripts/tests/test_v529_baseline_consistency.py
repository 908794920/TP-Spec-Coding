from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from cli import orchestration
from scripts.tests.v514_orchestration_testutil import (
    add_checkpoint,
    add_code_review,
    add_decision,
    add_verify,
    make_db,
)

BASE = Path(__file__).resolve().parents[2]


def _copy_base(target: Path) -> Path:
    root = target / "base"
    shutil.copytree(
        BASE,
        root,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    return root


def test_workflow_doctor_detects_lifecycle_phase_coverage_gap():
    with tempfile.TemporaryDirectory() as td:
        root = _copy_base(Path(td))
        lifecycle = root / "governance" / "lifecycle.md"
        text = lifecycle.read_text(encoding="utf-8")
        text = text.replace(" / planning", "").replace(" / review", "")
        lifecycle.write_text(text, encoding="utf-8")

        errors = orchestration.validate_contract(root)

        assert any("lifecycle.md" in error and "planning" in error for error in errors)
        assert any("lifecycle.md" in error and "review" in error for error in errors)


def test_workflow_doctor_detects_conditional_role_phase_outside_catalog():
    with tempfile.TemporaryDirectory() as td:
        root = _copy_base(Path(td))
        catalog_path = root / "governance" / "role-catalog.yaml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        for role in catalog["roles"]:
            if role.get("workflow_role") == "tp-database-engineer":
                role["phases"] = [phase for phase in role["phases"] if phase != "planning"]
                break
        catalog_path.write_text(
            yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        errors = orchestration.validate_contract(root)

        assert any(
            "tp-database-engineer" in error and "planning" in error and "role catalog" in error.lower()
            for error in errors
        )


# BLOCKED is a prerequisite wait, covered through real CLI fixtures in test_v532_waiting.
@pytest.mark.parametrize("decision", ["NEEDS_FIX", "REVISE", "FAIL"])
def test_code_review_defect_decisions_route_to_development(decision: str):
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "x.db", risk="L1", flow="L1")
        task = "TASK-V514"
        add_checkpoint(db, task, "tp-product-manager", "requirement")
        add_checkpoint(db, task, "tp-software-architect", "architecture")
        add_checkpoint(db, task, "tp-development-engineer", "development")
        add_verify(db, task, "PASS")
        add_decision(db, task, "workflow:deep-review")
        add_code_review(db, task, decision)

        route = orchestration.resolve_route(task, db_path=db, allowed_effects=["repo_mutation"])

        assert route["next_stage"] == "development"
        assert route["role_id"] == "tp-development-engineer"
        assert route["recommended_action"] == "dispatch_role"


def test_code_review_rework_requires_fresh_verification_before_review():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / "x.db", risk="L1", flow="L1")
        task = "TASK-V514"
        add_checkpoint(db, task, "tp-product-manager", "requirement")
        add_checkpoint(db, task, "tp-software-architect", "architecture")
        add_checkpoint(db, task, "tp-development-engineer", "development")
        add_verify(db, task, "PASS")
        add_decision(db, task, "workflow:deep-review")
        add_code_review(db, task, "NEEDS_FIX")
        add_checkpoint(db, task, "tp-development-engineer", "development", summary="fixed")

        route = orchestration.resolve_route(task, db_path=db, allowed_effects=["repo_mutation"])

        assert route["next_stage"] == "verification"
        assert route["role_id"] == "tp-test-engineer"

        add_verify(db, task, "PASS")
        route = orchestration.resolve_route(task, db_path=db, allowed_effects=["repo_mutation"])
        assert route["next_stage"] == "review"
        assert route["role_id"] == "tp-code-reviewer"
