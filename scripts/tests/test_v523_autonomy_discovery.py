from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from cli import autonomy_cycle, autonomy_profile, autonomy_workspace
from cli import db as dbmod
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
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def setup(root: Path, max_new=2, pending=5):
    canonical = root / "canonical"; git_repo(canonical / "repo")
    p = autonomy_profile.build_profile(
        profile_id="demo", canonical_root=str(canonical), canonical_project_id="demo",
        autonomy_root=str(root / "auto"), mutable_repos=["repo"], support_repos=[], goals=["quality"],
        difficulty_ceiling="L1", max_new_tasks=max_new,
    )
    p["safety"]["max_pending_user_decisions"] = pending
    autonomy_profile.save_profile(p)
    ws = autonomy_workspace.initialize_workspace("demo")
    return p, ws, canonical


def discover(token, key, title="Improve thing"):
    return run([
        "autonomy", "discover", "--profile", "demo",
        "--cycle-id", token["cycle_id"], "--generation", str(token["generation"]),
        "--discovery-key", key, "--title", title, "--summary", "valuable improvement",
        "--risk", "L0", "--flow", "L0", "--json",
    ])


def test_discovery_ceiling_is_upper_bound_and_duplicate_is_suppressed_without_new_task():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            p, ws, canonical = setup(root, max_new=2)
            token = autonomy_cycle.begin_cycle("demo")
            rc, out, err = discover(token, "repo/k1", "First")
            assert rc == 0, (out, err); first = json.loads(out)
            assert first["status"] == "CREATED" and first["task_id"].startswith("TASK-")
            rc, out, err = discover(token, "repo/k1", "Same idea different wording")
            assert rc == 0; dup = json.loads(out)
            assert dup["status"] == "SUPPRESSED" and dup["matched_task"] == first["task_id"]
            rc, out, err = discover(token, "repo/k2", "Second")
            assert rc == 0 and json.loads(out)["status"] == "CREATED"
            rc, out, err = discover(token, "repo/k3", "Third")
            assert rc != 0 and "DISCOVERY_CEILING_REACHED" in err


def test_discovery_uses_autonomous_staging_head_not_newer_canonical_head():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            p, ws, canonical = setup(root, max_new=2)
            auto_repo = Path(ws["workspace_root"]) / "repo"
            staging_head = subprocess.check_output(["git", "-C", str(auto_repo), "rev-parse", "HEAD"], text=True).strip()
            c = canonical / "repo"
            (c / "CANON.txt").write_text("new canonical\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(c), "add", "."], check=True)
            subprocess.run(["git", "-C", str(c), "commit", "-qm", "canonical drift"], check=True)
            canonical_head = subprocess.check_output(["git", "-C", str(c), "rev-parse", "HEAD"], text=True).strip()
            token = autonomy_cycle.begin_cycle("demo")
            rc, out, err = discover(token, "repo/staging-source")
            assert rc == 0, (out, err)
            data = json.loads(out)
            assert data["staging_heads"]["repo"] == staging_head
            assert data["staging_heads"]["repo"] != canonical_head


def test_pending_user_decision_backlog_pauses_new_discovery_and_digest_surfaces_inbox():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            p, ws, canonical = setup(root, max_new=3, pending=1)
            token = autonomy_cycle.begin_cycle("demo")
            rc, out, err = discover(token, "repo/k1")
            task = json.loads(out)["task_id"]
            rc, out, err = run([
                "autonomy", "route", "--profile", "demo", "--task", task,
                "--cycle-id", token["cycle_id"], "--generation", str(token["generation"]), "--json",
            ])
            assert rc == 0 and json.loads(out)["autonomy_waiting_reason"] == "awaiting_autonomy_decision"
            rc, out, err = discover(token, "repo/k2")
            assert rc != 0 and "DISCOVERY_PAUSED_PENDING_BACKLOG" in err
            rc, out, err = run([
                "autonomy", "digest", "--profile", "demo", "--cycle-id", token["cycle_id"],
                "--generation", str(token["generation"]), "--json",
            ])
            assert rc == 0, (out, err)
            digest = json.loads(out)
            assert task in [x["task_id"] for x in digest["awaiting_user_decision"]]
            assert "source" not in json.dumps(digest).lower()
            status_file = Path(ws["workspace_root"]) / ".tp-spec" / "autonomy" / "status.json"
            assert status_file.is_file()


def test_digest_completed_this_cycle_excludes_tasks_completed_before_current_cycle():
    from cli import autonomy_records, record_first
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            p, ws, canonical = setup(root, max_new=2)
            c1 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = discover(c1, "repo/old-complete", "Old complete")
            assert rc == 0, (out, err)
            task = json.loads(out)["task_id"]
            auto_root = Path(ws["workspace_root"])
            task_dir = auto_root / ".tp-spec" / "tasks" / task
            record_first.checkpoint(
                task_id=task, task_dir=str(task_dir), actor="tp-development-engineering",
                phase="development", summary="done", db=ws["db_path"],
            )
            record_first.complete(
                task_id=task, task_dir=str(task_dir), actor="tp-development-engineering",
                summary="complete", db=ws["db_path"],
            )
            autonomy_cycle.end_cycle("demo", c1["cycle_id"], c1["generation"])

            c2 = autonomy_cycle.begin_cycle("demo")
            rc, out, err = run([
                "autonomy", "digest", "--profile", "demo", "--cycle-id", c2["cycle_id"],
                "--generation", str(c2["generation"]), "--json",
            ])
            assert rc == 0, (out, err)
            digest = json.loads(out)
            assert task not in [x["task_id"] for x in digest["completed_this_cycle"]]


def test_discovery_refuses_dirty_autonomous_repo_so_analysis_cannot_smuggle_code_changes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            p, ws, canonical = setup(root, max_new=2)
            auto_repo = Path(ws["workspace_root"]) / "repo"
            (auto_repo / "README.md").write_text("analysis changed code\n", encoding="utf-8")
            token = autonomy_cycle.begin_cycle("demo")
            rc, out, err = discover(token, "repo/dirty-discovery")
            assert rc != 0
            assert "DISCOVERY_REPO_DIRTY" in err
            conn = dbmod.connect_readonly(ws["db_path"])
            try:
                count = conn.execute("SELECT COUNT(*) AS n FROM task").fetchone()["n"]
            finally:
                conn.close()
            assert count == 0
