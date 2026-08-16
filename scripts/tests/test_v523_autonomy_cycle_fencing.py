from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cli import autonomy_cycle, autonomy_profile, autonomy_workspace
from cli import main as climain


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


def setup_profile(root: Path):
    canonical = root / "canonical"; git_repo(canonical / "repo")
    profile = autonomy_profile.build_profile(
        profile_id="demo", canonical_root=str(canonical), canonical_project_id="demo",
        autonomy_root=str(root / "auto"), mutable_repos=["repo"], support_repos=[], goals=["quality"],
        difficulty_ceiling="L1", max_new_tasks=2,
    )
    autonomy_profile.save_profile(profile)
    autonomy_workspace.initialize_workspace("demo")
    return profile


def test_cycle_begin_is_generation_fenced_and_second_unexpired_begin_is_zero_write():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            setup_profile(root)
            first = autonomy_cycle.begin_cycle("demo")
            assert first["generation"] == 1 and first["state"] == "RUNNING"
            marker_before = autonomy_cycle.marker_path("demo").read_bytes()
            try:
                autonomy_cycle.begin_cycle("demo")
            except autonomy_cycle.CycleAlreadyRunning as exc:
                assert "CYCLE_ALREADY_RUNNING" in str(exc)
            else:
                raise AssertionError("second unexpired cycle begin must fail")
            assert autonomy_cycle.marker_path("demo").read_bytes() == marker_before
            autonomy_cycle.require_cycle_token("demo", first["cycle_id"], first["generation"])


def test_expired_cycle_can_be_reclaimed_and_old_executor_is_fenced():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            setup_profile(root)
            first = autonomy_cycle.begin_cycle("demo")
            marker = json.loads(autonomy_cycle.marker_path("demo").read_text(encoding="utf-8"))
            marker["deadline"] = "2000-01-01T00:00:00+00:00"
            autonomy_cycle.marker_path("demo").write_text(json.dumps(marker), encoding="utf-8")
            second = autonomy_cycle.begin_cycle("demo")
            assert second["generation"] == first["generation"] + 1
            assert second["cycle_id"] != first["cycle_id"]
            try:
                autonomy_cycle.require_cycle_token("demo", first["cycle_id"], first["generation"])
            except autonomy_cycle.StaleCycleFenced as exc:
                assert "STALE_CYCLE_FENCED" in str(exc)
            else:
                raise AssertionError("old cycle must be fenced after reclaim")
            autonomy_cycle.require_cycle_token("demo", second["cycle_id"], second["generation"])


def test_cycle_end_and_cli_contract_use_explicit_token_while_status_is_read_only():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            setup_profile(root)
            rc, out, err = run(["autonomy", "cycle", "begin", "--profile", "demo", "--json"])
            assert rc == 0, (out, err)
            token = json.loads(out)
            rc, out, err = run(["autonomy", "cycle", "status", "--profile", "demo", "--json"])
            assert rc == 0 and json.loads(out)["state"] == "RUNNING"
            rc, out, err = run([
                "autonomy", "cycle", "end", "--profile", "demo",
                "--cycle-id", token["cycle_id"], "--generation", str(token["generation"]), "--json",
            ])
            assert rc == 0, (out, err)
            assert json.loads(out)["state"] == "COMPLETED"
            rc, out, err = run(["autonomy", "cycle", "begin", "--profile", "demo", "--json"])
            assert rc == 0 and json.loads(out)["generation"] == token["generation"] + 1


def test_hard_deadline_fences_mutation_before_reclaim_grace_expires():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            setup_profile(root); first=autonomy_cycle.begin_cycle("demo")
            marker=json.loads(autonomy_cycle.marker_path("demo").read_text(encoding="utf-8"))
            now=datetime.now(timezone.utc); marker["deadline"]=(now-timedelta(seconds=1)).isoformat(timespec="seconds")
            autonomy_cycle.marker_path("demo").write_text(json.dumps(marker),encoding="utf-8")
            with pytest.raises(autonomy_cycle.StaleCycleFenced):
                autonomy_cycle.require_cycle_token("demo",first["cycle_id"],first["generation"])
            # grace means a replacement cycle cannot claim immediately even though the old token is fenced.
            with pytest.raises(autonomy_cycle.CycleAlreadyRunning):
                autonomy_cycle.begin_cycle("demo")


def test_cycle_safety_budget_tracks_unique_tasks_and_rework_attempts():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            setup_profile(root)
            profile=autonomy_profile.load_profile("demo"); profile["safety"]["max_existing_tasks_per_cycle"]=1; profile["safety"]["max_rework_attempts_per_task"]=1; autonomy_profile.save_profile(profile,overwrite=True)
            c=autonomy_cycle.begin_cycle("demo")
            autonomy_cycle.claim_task("demo",c["cycle_id"],c["generation"],"TASK-A")
            autonomy_cycle.claim_task("demo",c["cycle_id"],c["generation"],"TASK-A")
            with pytest.raises(autonomy_cycle.CycleError,match="CYCLE_TASK_LIMIT_REACHED"):
                autonomy_cycle.claim_task("demo",c["cycle_id"],c["generation"],"TASK-B")
            autonomy_cycle.claim_rework("demo",c["cycle_id"],c["generation"],"TASK-A")
            with pytest.raises(autonomy_cycle.CycleError,match="TASK_REWORK_LIMIT_REACHED"):
                autonomy_cycle.claim_rework("demo",c["cycle_id"],c["generation"],"TASK-A")


def test_two_concurrent_cycle_begin_processes_have_one_generation_winner():
    import sys
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        user_root = root / "user"
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user_root)}, clear=False):
            setup_profile(root)
        env = dict(os.environ)
        env["TP_SPEC_USER_ROOT"] = str(user_root)
        cmd = [sys.executable, "-m", "cli.main", "autonomy", "cycle", "begin", "--profile", "demo", "--json"]
        p1 = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p2 = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        o1, e1 = p1.communicate(timeout=30)
        o2, e2 = p2.communicate(timeout=30)
        results = [(p1.returncode, o1, e1), (p2.returncode, o2, e2)]
        winners = [x for x in results if x[0] == 0]
        losers = [x for x in results if x[0] != 0]
        assert len(winners) == 1, results
        assert len(losers) == 1, results
        assert "CYCLE_ALREADY_RUNNING" in losers[0][2]
        token = json.loads(winners[0][1])
        assert token["generation"] == 1
