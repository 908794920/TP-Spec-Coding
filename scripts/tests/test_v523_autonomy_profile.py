from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from cli import main as climain
from cli import autonomy_profile


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = int(exc.code or 0)
    return rc, out.getvalue(), err.getvalue()


def git_init(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "README.md").write_text("repo\n", encoding="utf-8")


def test_profile_create_show_prompt_and_multiple_profiles_on_same_canonical_workspace():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        user = root / "user"
        canonical = root / "IDC"
        git_init(canonical / "idc")
        git_init(canonical / "idc-module-task")
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            for profile, repo in (("idc-quality", "idc"), ("idc-task", "idc-module-task")):
                rc, out, err = run([
                    "autonomy", "profile", "create", "--id", profile,
                    "--canonical-root", str(canonical), "--canonical-project", "idc-workspace",
                    "--autonomy-root", str(root / "auto" / profile),
                    "--mutable-repo", repo, "--goal", "code quality",
                    "--difficulty-ceiling", "L1", "--max-new-tasks", "3", "--json",
                ])
                assert rc == 0, (out, err)
                data = json.loads(out)
                assert data["profile_id"] == profile
                assert data["runtime_project_id"] == f"autonomy-{profile}"
            profiles = autonomy_profile.list_profiles()
            assert [p["profile_id"] for p in profiles] == ["idc-quality", "idc-task"]
            rc, out, err = run(["autonomy", "profile", "show", "--id", "idc-quality", "--json"])
            assert rc == 0, (out, err)
            data = json.loads(out)
            assert data["policy"]["discovery"]["quota_semantics"] == "ceiling_not_target"
            assert data["policy"]["discovery"]["max_new_tasks_per_cycle"] == 3
            assert data["workflow"]["confirmation_policy"] == "material"
            rc, out, err = run(["autonomy", "profile", "prompt", "--id", "idc-quality"])
            assert rc == 0, (out, err)
            assert "idc-quality" in out and "不得自行复制" in out
            profile_path = user / "autonomy" / "profiles" / "idc-quality.yaml"
            saved = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            assert saved["automation"]["prompt"] == out.strip("\n")


def test_profile_create_rejects_autonomy_root_inside_canonical_and_unknown_repo():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        user = root / "user"
        canonical = root / "IDC"
        git_init(canonical / "idc")
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            rc, out, err = run([
                "autonomy", "profile", "create", "--id", "bad",
                "--canonical-root", str(canonical), "--canonical-project", "idc-workspace",
                "--autonomy-root", str(canonical / ".autonomy"),
                "--mutable-repo", "idc", "--goal", "quality",
                "--difficulty-ceiling", "L1", "--max-new-tasks", "2",
            ])
            assert rc != 0
            assert "AUTONOMY_PATH_CONFLICT" in err
            rc, out, err = run([
                "autonomy", "profile", "create", "--id", "bad2",
                "--canonical-root", str(canonical), "--canonical-project", "idc-workspace",
                "--autonomy-root", str(root / "auto" / "bad2"),
                "--mutable-repo", "missing", "--goal", "quality",
                "--difficulty-ceiling", "L1", "--max-new-tasks", "2",
            ])
            assert rc != 0
            assert "MUTABLE_REPO_NOT_FOUND" in err


def test_profile_enable_disable_and_doctor_schema_version():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        user = root / "user"
        canonical = root / "p"
        git_init(canonical / "repo")
        with patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(user)}, clear=False):
            rc, out, err = run([
                "autonomy", "profile", "create", "--id", "demo",
                "--canonical-root", str(canonical), "--canonical-project", "demo",
                "--autonomy-root", str(root / "auto" / "demo"),
                "--mutable-repo", "repo", "--goal", "quality",
                "--difficulty-ceiling", "L0", "--max-new-tasks", "1",
            ])
            assert rc == 0, (out, err)
            rc, out, err = run(["autonomy", "profile", "disable", "--id", "demo", "--json"])
            assert rc == 0 and json.loads(out)["enabled"] is False
            rc, out, err = run(["autonomy", "doctor", "--profile", "demo", "--json"])
            assert rc == 0, (out, err)
            assert json.loads(out)["status"] == "PASS"
            p = user / "autonomy" / "profiles" / "demo.yaml"
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            raw["schema"] = "tp-spec.autonomy-profile/v99"
            p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            rc, out, err = run(["autonomy", "doctor", "--profile", "demo", "--json"])
            assert rc != 0
            data = json.loads(out)
            assert "PROFILE_SCHEMA_UPGRADE_REQUIRED" in data["errors"][0]


def test_profile_edit_updates_only_user_policy_and_prompt_refresh_is_persisted():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); user=root/"user"; canonical=root/"p"; git_init(canonical/"repo")
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(user)},clear=False):
            rc,out,err=run(["autonomy","profile","create","--id","demo","--canonical-root",str(canonical),"--canonical-project","demo","--autonomy-root",str(root/"auto"),"--mutable-repo","repo","--goal","quality","--difficulty-ceiling","L0","--max-new-tasks","1"]); assert rc==0,(out,err)
            rc,out,err=run(["autonomy","profile","edit","--id","demo","--goal","ux","--goal","quality","--difficulty-ceiling","L1","--max-new-tasks","4","--confirmation-policy","each_stage","--json"]); assert rc==0,(out,err)
            data=json.loads(out); assert data["policy"]["goals"]==["ux","quality"] and data["policy"]["difficulty_ceiling"]=="L1" and data["policy"]["discovery"]["max_new_tasks_per_cycle"]==4 and data["workflow"]["confirmation_policy"]=="each_stage"
            rc,out,err=run(["autonomy","profile","refresh-prompt","--id","demo","--json"]); assert rc==0,(out,err)
            refreshed=json.loads(out); assert refreshed["automation"]["prompt_template_version"]==autonomy_profile.PROMPT_TEMPLATE_VERSION and "demo" in refreshed["automation"]["prompt"]
