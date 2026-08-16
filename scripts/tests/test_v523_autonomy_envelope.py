from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from cli import autonomy_cycle, autonomy_git, autonomy_profile, autonomy_records, autonomy_workspace
from cli import db as dbmod
from cli import main as climain
from scripts.tests.v514_orchestration_testutil import add_checkpoint


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = int(exc.code or 0)
    return rc, out.getvalue(), err.getvalue()


def git_repo(path: Path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "x@y.z"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "x"], check=True)
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def setup_env(root: Path, *, level="L0", confirmation="material", support=False):
    canonical = root / "canonical"; git_repo(canonical / "repo")
    if support:
        git_repo(canonical / "support")
    profile = autonomy_profile.build_profile(
        profile_id="demo", canonical_root=str(canonical), canonical_project_id="demo",
        autonomy_root=str(root / "auto"), mutable_repos=["repo"], support_repos=["support"] if support else [], goals=["quality"],
        difficulty_ceiling=level, max_new_tasks=2, confirmation_policy=confirmation,
    )
    autonomy_profile.save_profile(profile)
    ws = autonomy_workspace.initialize_workspace("demo")
    auto_root = Path(ws["workspace_root"])
    old = Path.cwd(); os.chdir(auto_root)
    try:
        rc, out, err = run([
            "task", "create", "--id", "TASK-AUTO-1", "--project", "autonomy-demo",
            "--risk", level, "--flow", level, "--scaffold",
        ])
    finally:
        os.chdir(old)
    assert rc == 0, (out, err)
    task_dir = auto_root / ".tp-spec" / "tasks" / "TASK-AUTO-1"
    autonomy_records.record_discovered("demo", "TASK-AUTO-1", str(task_dir), discovery_key="demo/repo/improvement")
    return profile, Path(ws["db_path"]), task_dir


def task_state(db: Path):
    conn = dbmod.connect_readonly(str(db))
    try:
        return conn.execute("select current_state from task where task_id='TASK-AUTO-1'").fetchone()["current_state"]
    finally:
        conn.close()


def test_repo_mutation_boundary_blocks_until_human_approval_then_next_cycle_dispatches():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            profile, db, task_dir = setup_env(root, level="L0")
            c1 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run([
                "autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--cycle-id", c1["cycle_id"], "--generation", str(c1["generation"]), "--json",
            ])
            assert rc == 0, (out, err)
            route = json.loads(out)
            assert route["decision"] == "BOUNDARY_REACHED"
            assert route["reason"] == "effect_not_allowed"
            assert route["required_effects"] == ["repo_mutation"]
            assert route["autonomy_waiting_reason"] == "awaiting_autonomy_decision"
            assert task_state(db) == "BLOCKED"

            # User-session command: no cycle token is required and it does not resume immediately.
            rc, out, err = run([
                "autonomy", "decide", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--decision", "APPROVED", "--reason", "do it", "--json",
            ])
            assert rc == 0, (out, err)
            assert json.loads(out)["effective_after_generation"] == c1["generation"] + 1
            assert task_state(db) == "BLOCKED"
            # same cycle remains blocked even after approval
            rc, out, err = run([
                "autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--cycle-id", c1["cycle_id"], "--generation", str(c1["generation"]), "--json",
            ])
            assert rc == 0 and json.loads(out)["recommended_action"] == "task_resume_after_resolution"
            autonomy_cycle.end_cycle("demo", c1["cycle_id"], c1["generation"])
            c2 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run([
                "autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--cycle-id", c2["cycle_id"], "--generation", str(c2["generation"]), "--json",
            ])
            assert rc == 0, (out, err)
            route = json.loads(out)
            assert route["decision"] == "DISPATCH_ROLE"
            assert route["role_id"] == "tp-development-engineering"
            assert task_state(db) == "ACTIVE"


def test_material_confirmation_blocked_in_unattended_cycle_can_be_confirmed_but_resumes_next_cycle_only():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            profile, db, task_dir = setup_env(root, level="L2", confirmation="material")
            add_checkpoint(str(db), "TASK-AUTO-1", "tp-requirement-analysis", "requirement")
            add_checkpoint(str(db), "TASK-AUTO-1", "tp-architecture-design", "architecture")
            # First cycle hits effect boundary; approve for next cycle.
            c1 = autonomy_cycle.begin_cycle("demo")
            run(["autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1", "--cycle-id", c1["cycle_id"], "--generation", str(c1["generation"]), "--json"])
            run(["autonomy", "decide", "--profile", "demo", "--task", "TASK-AUTO-1", "--decision", "APPROVED", "--reason", "ok", "--json"])
            autonomy_cycle.end_cycle("demo", c1["cycle_id"], c1["generation"])

            c2 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run(["autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1", "--cycle-id", c2["cycle_id"], "--generation", str(c2["generation"]), "--json"])
            assert rc == 0, (out, err)
            route = json.loads(out)
            assert route["decision"] == "AWAIT_CONFIRMATION"
            assert route["confirmation_reason"] == "MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION"
            assert route["autonomy_waiting_reason"] == "awaiting_human_confirmation"
            assert task_state(db) == "BLOCKED"

            # Existing workflow confirmation remains the truth source, but does not resume in this interaction.
            rc, out, err = run([
                "workflow", "confirm", "--task", "TASK-AUTO-1", "--task-dir", str(task_dir),
                "--db", str(db), "--confirmation-policy", "material", "--json",
            ])
            assert rc == 0, (out, err)
            confirmed = json.loads(out)
            assert confirmed["recommended_action"] == "next_cycle_resume"
            assert task_state(db) == "BLOCKED"
            autonomy_cycle.end_cycle("demo", c2["cycle_id"], c2["generation"])

            c3 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run(["autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1", "--cycle-id", c3["cycle_id"], "--generation", str(c3["generation"]), "--json"])
            assert rc == 0, (out, err)
            route = json.loads(out)
            assert route["decision"] == "DISPATCH_ROLE"
            assert route["role_id"] == "tp-development-engineering"


def test_effects_empty_stage_guard_detects_git_visible_mutation():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"; git_repo(repo)
        before = autonomy_git.repo_state_fingerprint(repo)
        (repo / "README.md").write_text("mutated\n", encoding="utf-8")
        try:
            autonomy_git.assert_no_repo_mutation(repo, before)
        except autonomy_git.AutonomyGitError as exc:
            assert "UNDECLARED_REPO_MUTATION" in str(exc)
        else:
            raise AssertionError("git-visible mutation must fail an effects:[] guard")


def test_autonomy_route_arms_effects_empty_guard_and_next_route_fails_on_repo_mutation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            profile, db, task_dir = setup_env(root, level="L1")
            token = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run([
                "autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--cycle-id", token["cycle_id"], "--generation", str(token["generation"]), "--json",
            ])
            assert rc == 0, (out, err)
            first = json.loads(out)
            assert first["decision"] == "DISPATCH_ROLE"
            assert first["next_stage"] == "requirement"
            assert first["required_effects"] == []

            auto_repo = Path((profile.get("autonomous") or {})["workspace_root"]) / "repo"
            (auto_repo / "README.md").write_text("unexpected mutation\n", encoding="utf-8")

            rc, out, err = run([
                "autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--cycle-id", token["cycle_id"], "--generation", str(token["generation"]), "--json",
            ])
            assert rc != 0
            assert "UNDECLARED_REPO_MUTATION" in err


def test_support_repo_remains_read_only_even_when_stage_allows_mutable_repo_mutation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            profile, db, task_dir = setup_env(root, level="L0", support=True)
            c1 = autonomy_cycle.begin_cycle("demo")
            run(["autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1", "--cycle-id", c1["cycle_id"], "--generation", str(c1["generation"]), "--json"])
            run(["autonomy", "decide", "--profile", "demo", "--task", "TASK-AUTO-1", "--decision", "APPROVED", "--reason", "ok", "--json"])
            autonomy_cycle.end_cycle("demo", c1["cycle_id"], c1["generation"])
            c2 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run(["autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1", "--cycle-id", c2["cycle_id"], "--generation", str(c2["generation"]), "--json"])
            assert rc == 0, (out, err)
            route = json.loads(out)
            assert route["decision"] == "DISPATCH_ROLE"
            assert route["required_effects"] == ["repo_mutation"]

            support_repo = Path(profile["autonomous"]["workspace_root"]) / "support"
            (support_repo / "README.md").write_text("illegal support mutation\n", encoding="utf-8")
            rc, out, err = run(["autonomy", "route", "--profile", "demo", "--task", "TASK-AUTO-1", "--cycle-id", c2["cycle_id"], "--generation", str(c2["generation"]), "--json"])
            assert rc != 0
            assert "SUPPORT_REPO_MUTATION" in err


def test_user_session_decide_requires_a_real_awaiting_autonomy_boundary():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            profile, db, task_dir = setup_env(root, level="L1")
            rc, out, err = run([
                "autonomy", "decide", "--profile", "demo", "--task", "TASK-AUTO-1",
                "--decision", "APPROVED", "--reason", "too early", "--json",
            ])
            assert rc != 0
            assert "AUTONOMY_DECISION_NOT_PENDING" in err
