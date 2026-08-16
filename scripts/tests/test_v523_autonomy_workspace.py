from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from cli import main as climain
from cli import autonomy_profile, autonomy_workspace


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = int(exc.code or 0)
    return rc, out.getvalue(), err.getvalue()


def git_repo(path: Path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    (path / "README.md").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def make_profile(root: Path, user: Path, *, support=False):
    canonical = root / "IDC"
    git_repo(canonical / "idc")
    if support:
        git_repo(canonical / "collect-common")
    profile = autonomy_profile.build_profile(
        profile_id="idc-quality", canonical_root=str(canonical), canonical_project_id="idc-workspace",
        autonomy_root=str(root / "autonomy" / "idc-quality"), mutable_repos=["idc"],
        support_repos=["collect-common"] if support else [], goals=["quality"],
        difficulty_ceiling="L1", max_new_tasks=2,
    )
    autonomy_profile.save_profile(profile)
    return canonical, profile


def test_workspace_init_creates_independent_long_lived_clone_and_runtime():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); user = root / "user"
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            canonical, profile = make_profile(root, user)
            rc, out, err = run(["autonomy", "workspace", "init", "--profile", "idc-quality", "--json"])
            assert rc == 0, (out, err)
            data = json.loads(out)
            auto_root = Path(profile["autonomous"]["workspace_root"])
            auto_repo = auto_root / "idc"
            assert auto_repo.is_dir() and (auto_repo / ".git").exists()
            assert (auto_root / ".tp-spec" / "db" / "autonomy-idc-quality.db").is_file()
            assert (auto_root / ".tp-spec" / "config" / "project-binding.yaml").is_file()
            assert data["repositories"][0]["branch"] == "autonomy/idc-quality/staging"
            canonical_git = subprocess.check_output(["git", "-C", str(canonical / "idc"), "rev-parse", "--absolute-git-dir"], text=True).strip()
            auto_git = subprocess.check_output(["git", "-C", str(auto_repo), "rev-parse", "--absolute-git-dir"], text=True).strip()
            assert Path(canonical_git).resolve() != Path(auto_git).resolve()
            # Idempotent: second init reuses the same long-lived workspace.
            rc2, out2, err2 = run(["autonomy", "workspace", "init", "--profile", "idc-quality", "--json"])
            assert rc2 == 0, (out2, err2)
            assert json.loads(out2)["reused"] is True


def test_workspace_support_repo_is_detected_if_mutated_and_never_treated_mutable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); user = root / "user"
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            canonical, profile = make_profile(root, user, support=True)
            data = autonomy_workspace.initialize_workspace("idc-quality")
            auto_root = Path(profile["autonomous"]["workspace_root"])
            support = auto_root / "collect-common"
            (support / "README.md").write_text("changed\n", encoding="utf-8")
            health = autonomy_workspace.workspace_status("idc-quality", refresh_canonical=False)
            row = next(r for r in health["repositories"] if r["id"] == "collect-common")
            assert row["scope"] == "support"
            assert row["dirty"] is True
            assert "SUPPORT_REPO_MUTATED" in health["warnings"]


def test_drift_reads_canonical_without_rebasing_or_merging_staging():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); user = root / "user"
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            canonical, profile = make_profile(root, user)
            autonomy_workspace.initialize_workspace("idc-quality")
            auto_repo = Path(profile["autonomous"]["workspace_root"]) / "idc"
            # autonomous commit
            (auto_repo / "AUTO.txt").write_text("auto\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(auto_repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(auto_repo), "config", "user.email", "auto@example.com"], check=True)
            subprocess.run(["git", "-C", str(auto_repo), "config", "user.name", "Auto"], check=True)
            subprocess.run(["git", "-C", str(auto_repo), "commit", "-qm", "auto"], check=True)
            staging_before = subprocess.check_output(["git", "-C", str(auto_repo), "rev-parse", "HEAD"], text=True).strip()
            # canonical independent commit
            c = canonical / "idc"
            (c / "CANON.txt").write_text("canon\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(c), "add", "."], check=True)
            subprocess.run(["git", "-C", str(c), "commit", "-qm", "canon"], check=True)
            status = autonomy_workspace.workspace_status("idc-quality", refresh_canonical=True)
            drift = status["repositories"][0]["drift"]
            assert drift["canonical_commits_since_common_base"] == 1
            assert drift["staging_commits_since_common_base"] == 1
            staging_after = subprocess.check_output(["git", "-C", str(auto_repo), "rev-parse", "HEAD"], text=True).strip()
            assert staging_after == staging_before


def test_autonomous_binding_marks_canonical_context_read_only_and_content_mutation_cli_is_fenced():
    import yaml
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(root / "user")}, clear=False):
            _, profile = make_profile(root, root / "user")
            autonomy_workspace.initialize_workspace("idc-quality")
            auto_root = Path(profile["autonomous"]["workspace_root"])
            binding = yaml.safe_load((auto_root/".tp-spec"/"config"/"project-binding.yaml").read_text(encoding="utf-8"))
            assert binding["autonomy"]["context_mode"] == "canonical_read_only"
            rc,out,err=run(["knowledge","maintain","--workspace-root",str(auto_root)])
            assert rc != 0
            assert "AUTONOMY_CANONICAL_CONTEXT_READ_ONLY" in err


def test_autonomy_doctor_after_workspace_init_reports_workspace_cycle_and_integration_capability():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); user = root / "user"
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            _, profile = make_profile(root, user)
            autonomy_workspace.initialize_workspace("idc-quality")
            rc, out, err = run(["autonomy", "doctor", "--profile", "idc-quality", "--json"])
            assert rc == 0, (out, err)
            data = json.loads(out)
            assert data["status"] == "PASS"
            assert data["workspace"]["status"] == "PASS"
            assert data["cycle"]["state"] == "IDLE"
            assert data["integration"]["apply"] in {"ENABLED", "APPLY_NOT_PILOTED"}


def test_autonomy_doctor_fails_closed_when_support_repo_is_mutated():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); user = root / "user"
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            _, profile = make_profile(root, user, support=True)
            autonomy_workspace.initialize_workspace("idc-quality")
            support = Path(profile["autonomous"]["workspace_root"]) / "collect-common"
            (support / "README.md").write_text("illegal\n", encoding="utf-8")
            rc, out, err = run(["autonomy", "doctor", "--profile", "idc-quality", "--json"])
            assert rc != 0
            data = json.loads(out)
            assert data["status"] == "FAIL"
            assert any("SUPPORT_REPO_MUTATED" in x for x in data["errors"])
