# -*- coding: utf-8 -*-
"""V5.2.3 phase-aware artifact validator.

The validator intentionally separates *working* checks from *closing* checks.
A role entering VERIFYING must not be required to have already produced the
verification result.  This module therefore exposes three validation modes:

- ``working``: validate structure that must already exist in the current state;
  completion outcomes (PASS, human witness, codex-review) are not required.
- ``handoff``: validate readiness for a concrete target state using the same
  transition_service rules used by ``tp-spec commit`` (requires DB + task id).
- ``closing``: strict fail-closed completion validation (legacy default).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .version import active_version
from .yaml_checks import VERDICT_ENUM

_DEFAULT_SECTIONS = ["acceptance", "codex-review", "test-guide", "scope", "decisions"]
_CLOSING_STATES = {"REVIEWING", "CLOSING", "COMPLETED"}


def _working_validation(ts, tdir: Path, section: str, state: str, issues) -> None:
    """Validate only facts that should exist *before* work in ``state`` finishes."""
    state = (state or "").upper()
    if section == "acceptance":
        # Structural validation only: PENDING/BLOCKED and human witness=pending are
        # valid while verification is in progress.
        ts._check_acceptance(tdir, issues, enforce_no_pending=False, enforce_yaml=True)
    elif section == "codex-review":
        # The verification role owns this output.  In working mode it is never an
        # entry gate, even when a scaffolded DRAFT template already exists.
        pass
    elif section == "test-guide":
        if state in {"VERIFYING", "BROWSER_VERIFYING", "REVIEWING"}:
            ts._check_test_guide(tdir, issues, require_development=True, to_state="VERIFYING")
        elif state in _CLOSING_STATES:
            ts._check_test_guide(tdir, issues, require_verification=True, to_state="CLOSING")
        elif state in {"DEVELOPING", "ASSISTING"}:
            ts._check_test_guide(tdir, issues, require_skeleton=True, to_state="DEVELOPING")
        elif (tdir / "requirement-test-guide.md").is_file():
            ts._check_test_guide(tdir, issues)
    elif section == "scope":
        ts._check_scope_change(tdir, issues)
    elif section == "decisions":
        # Working-state validation checks malformed/unresolved declared decisions,
        # but does not require a decision file merely to enter a later role.
        ts._check_decisions(tdir, issues, require_decisions=False)
    else:
        raise ValueError(f"unknown validator section: {section}")


def validate_artifacts(
    task_dir,
    sections: List[str],
    db_path=None,
    task_id=None,
    *,
    mode: str = "closing",
    state: str = "",
    to_state: str = "",
    actor: str = "",
) -> Dict[str, Any]:
    """Run phase-aware artifact validation (read-only, zero side effects)."""
    from . import transition_service as ts
    from . import db as dbmod

    issues: List[ts.ValidationIssue] = []
    tdir = Path(task_dir)
    active = sections if sections else list(_DEFAULT_SECTIONS)
    mode = (mode or "closing").lower()

    if mode == "handoff":
        if not db_path or not task_id or not to_state or not actor:
            raise ValueError("handoff mode requires --db, --task, --to-state and --actor")
        conn = dbmod.connect(db_path)
        try:
            task = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"task not found: {task_id}")
            result = ts.validate_transition(
                task_id=task_id,
                task_dir=tdir,
                from_state=task["current_state"] or "",
                to_state=to_state,
                actor=actor,
                conn=conn,
            )
            issues.extend(result.issues)
        finally:
            conn.close()
    else:
        for section in active:
            if mode == "working":
                _working_validation(ts, tdir, section, state, issues)
            elif mode == "closing":
                if section == "acceptance":
                    ts._check_acceptance(tdir, issues, enforce_no_pending=True, enforce_yaml=True)
                elif section == "codex-review":
                    ts._check_codex_review_body(tdir, issues)
                elif section == "test-guide":
                    ts._check_test_guide(tdir, issues, require_verification=True, to_state="CLOSING")
                elif section == "scope":
                    ts._check_scope_change(tdir, issues)
                elif section == "decisions":
                    ts._check_decisions(tdir, issues, require_decisions=True)
                else:
                    raise ValueError(f"unknown validator section: {section}")
            else:
                raise ValueError(f"unknown validator mode: {mode}")
        if mode == "closing":
            # One cheap, high-confidence integrity pass for all delivery artifacts.
            # This catches mojibake/literal PowerShell newline leakage before CLOSING
            # without turning prose quality into a governance gate.
            ts._check_text_integrity(tdir, issues, include_quality=(state.upper() == "COMPLETED"))

    return {
        "ok": not issues,
        "validator": "cli.validator",
        "schema_version": active_version(),
        "mode": mode,
        "state": state or None,
        "to_state": to_state or None,
        "sections": active,
        "verdict_enum": list(VERDICT_ENUM),
        "issues": [i.to_dict() for i in issues],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cli.validator", description="V5.2.3 phase-aware artifact validator")
    parser.add_argument("--task-dir", required=True, help="task directory")
    parser.add_argument("--db", default=None, help="sqlite db path (required for --mode handoff)")
    parser.add_argument("--task", default=None, help="task id (required for --mode handoff)")
    parser.add_argument("--sections", default=",".join(_DEFAULT_SECTIONS), help="comma-separated sections to validate")
    parser.add_argument("--mode", choices=["working", "handoff", "closing"], default="closing")
    parser.add_argument("--state", default="", help="current state for working-mode phase semantics")
    parser.add_argument("--to-state", default="", help="target state for handoff-mode transition validation")
    parser.add_argument("--actor", default="", help="actor for handoff-mode transition validation")
    args = parser.parse_args(argv)
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    try:
        result = validate_artifacts(
            args.task_dir,
            sections,
            db_path=args.db,
            task_id=args.task,
            mode=args.mode,
            state=args.state,
            to_state=args.to_state,
            actor=args.actor,
        )
    except Exception as e:  # noqa: BLE001
        result = {
            "ok": False,
            "validator": "cli.validator",
            "schema_version": active_version(),
            "mode": args.mode,
            "state": args.state or None,
            "to_state": args.to_state or None,
            "sections": sections,
            "verdict_enum": list(VERDICT_ENUM),
            "issues": [{
                "code": "VALIDATOR_ERROR",
                "message": f"{type(e).__name__}: {e}",
                "artifact": None,
                "field": None,
                "severity": "ERROR",
            }],
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
