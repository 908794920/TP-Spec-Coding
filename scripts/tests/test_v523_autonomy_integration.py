from __future__ import annotations

import contextlib, io, os, subprocess, tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cli import autonomy_batch, autonomy_cycle, autonomy_profile, autonomy_records, autonomy_workspace, record_first
from cli import main as climain


def run(argv):
    o,e=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(o),contextlib.redirect_stderr(e):
        try: rc=climain.main(argv)
        except SystemExit as ex: rc=int(ex.code or 0)
    return rc,o.getvalue(),e.getvalue()


def git_repo(path: Path):
    path.mkdir(parents=True)
    subprocess.run(["git","init","-q","-b","main",str(path)],check=True)
    subprocess.run(["git","-C",str(path),"config","user.email","x@y.z"],check=True)
    subprocess.run(["git","-C",str(path),"config","user.name","x"],check=True)
    (path/"README.md").write_text("base\n",encoding="utf-8")
    subprocess.run(["git","-C",str(path),"add","."],check=True)
    subprocess.run(["git","-C",str(path),"commit","-qm","init"],check=True)


def setup(root: Path, repos=("repo1","repo2")):
    canonical=root/"canonical"
    for r in repos: git_repo(canonical/r)
    p=autonomy_profile.build_profile(profile_id="demo",canonical_root=str(canonical),canonical_project_id="demo",autonomy_root=str(root/"auto"),mutable_repos=list(repos),support_repos=[],goals=["quality"],difficulty_ceiling="L0",max_new_tasks=3)
    autonomy_profile.save_profile(p); ws=autonomy_workspace.initialize_workspace("demo")
    return p,ws


def create_ready_batch(root: Path, profile, ws):
    auto=Path(profile["autonomous"]["workspace_root"]); old=Path.cwd(); os.chdir(auto)
    try: rc,o,e=run(["task","create","--id","TASK-AUTO-1","--project","autonomy-demo","--risk","L0","--flow","L0","--title","integration","--scaffold"])
    finally: os.chdir(old)
    assert rc==0,(o,e)
    td=auto/".tp-spec"/"tasks"/"TASK-AUTO-1"; autonomy_records.record_discovered("demo","TASK-AUTO-1",str(td),discovery_key="repo/integration")
    c0=autonomy_cycle.begin_cycle("demo"); autonomy_records.record_decision("demo","TASK-AUTO-1",decision="APPROVED",reason="ok"); autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"])
    c1=autonomy_cycle.begin_cycle("demo"); b=autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1"]); autonomy_batch.start_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
    for rid in (profile["canonical"]["repositories"]["mutable"]):
        repo=auto/rid["path"]; (repo/f"{rid['id']}.txt").write_text(f"{rid['id']} change\n",encoding="utf-8")
    record_first.checkpoint(task_id="TASK-AUTO-1",task_dir=str(td),actor="tp-development-engineering",phase="development",summary="done",db=ws["db_path"])
    record_first.complete(task_id="TASK-AUTO-1",task_dir=str(td),actor="tp-development-engineering",summary="complete",db=ws["db_path"])
    autonomy_batch.commit_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"]); b=autonomy_batch.finalize_batch("demo",b["batch_id"],c1["cycle_id"],c1["generation"])
    autonomy_cycle.end_cycle("demo",c1["cycle_id"],c1["generation"])
    return b


def verify(integration):
    from cli import autonomy_integration
    ev=Path(integration["integration_root"])/"evidence"/"verification.txt"; ev.parent.mkdir(parents=True,exist_ok=True); ev.write_text("integration candidate verified\n",encoding="utf-8")
    return autonomy_integration.record_verification("demo",integration["integration_id"],decision="PASS",evidence=[str(ev)])


def test_prepare_requires_verification_then_apply_updates_all_canonical_repos():
    from cli import autonomy_integration
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); b=create_ready_batch(root,p,ws)
            integ=autonomy_integration.prepare("demo",[b["batch_id"]])
            assert integ["status"]=="NEEDS_VERIFICATION"
            with pytest.raises(Exception,match="INTEGRATION_VERIFICATION_REQUIRED"):
                autonomy_integration.apply("demo",integ["integration_id"])
            v=verify(integ); assert v["verification"]["decision"]=="PASS"
            result=autonomy_integration.apply("demo",integ["integration_id"])
            assert result["status"]=="INTEGRATION_COMMITTED"
            assert (root/"canonical"/"repo1"/"repo1.txt").exists()
            assert (root/"canonical"/"repo2"/"repo2.txt").exists()


def test_multi_repo_apply_crash_after_first_repo_is_journaled_and_retry_finishes_forward():
    from cli import autonomy_integration
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); b=create_ready_batch(root,p,ws); integ=autonomy_integration.prepare("demo",[b["batch_id"]]); verify(integ)
            with patch.dict(os.environ,{"TP_SPEC_AUTONOMY_FAULT":"after_repo:repo1"},clear=False):
                with pytest.raises(Exception,match="AUTONOMY_FAULT_INJECTED"):
                    autonomy_integration.apply("demo",integ["integration_id"])
            journal=autonomy_integration.load_integration("demo",integ["integration_id"])
            assert journal["repositories"]["repo1"]["apply_status"]=="APPLIED"
            assert journal["repositories"]["repo2"]["apply_status"]=="PENDING"
            result=autonomy_integration.apply("demo",integ["integration_id"])
            assert result["status"]=="INTEGRATION_COMMITTED"
            assert (root/"canonical"/"repo1"/"repo1.txt").exists() and (root/"canonical"/"repo2"/"repo2.txt").exists()


def test_apply_refuses_if_canonical_changed_after_prepare_and_cli_apply_has_explicit_target():
    from cli import autonomy_integration
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root,repos=("repo1",)); b=create_ready_batch(root,p,ws); integ=autonomy_integration.prepare("demo",[b["batch_id"]]); verify(integ)
            c=root/"canonical"/"repo1"; (c/"human.txt").write_text("human\n",encoding="utf-8"); subprocess.run(["git","-C",str(c),"add","."],check=True); subprocess.run(["git","-C",str(c),"commit","-qm","human"],check=True)
            with pytest.raises(Exception,match="PREPARE_STALE"):
                autonomy_integration.apply("demo",integ["integration_id"])
            rc,out,err=run(["autonomy","integrate","show","--profile","demo","--integration",integ["integration_id"],"--json"])
            assert rc==0,(out,err)


@pytest.mark.parametrize("fault_point", ["before_ref:repo1", "after_ref:repo1", "after_repo:repo2"])
def test_apply_fault_points_are_retryable_without_unknown_canonical_state(fault_point):
    from cli import autonomy_integration
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); b=create_ready_batch(root,p,ws); integ=autonomy_integration.prepare("demo",[b["batch_id"]]); verify(integ)
            with patch.dict(os.environ,{"TP_SPEC_AUTONOMY_FAULT":fault_point},clear=False):
                with pytest.raises(Exception,match="AUTONOMY_FAULT_INJECTED"):
                    autonomy_integration.apply("demo",integ["integration_id"])
            journal=autonomy_integration.load_integration("demo",integ["integration_id"])
            for rid,row in journal["repositories"].items():
                current=subprocess.check_output(["git","-C",row["canonical_path"],"rev-parse","HEAD"],text=True).strip()
                assert current in {row["pre_ref"],row["target_ref"]}
            result=autonomy_integration.apply("demo",integ["integration_id"])
            assert result["status"]=="INTEGRATION_COMMITTED"
            for rid,row in result["repositories"].items():
                current=subprocess.check_output(["git","-C",row["canonical_path"],"rev-parse","HEAD"],text=True).strip()
                assert current==row["target_ref"]
