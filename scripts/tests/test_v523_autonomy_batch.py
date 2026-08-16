from __future__ import annotations

import contextlib, io, json, os, subprocess, tempfile
from pathlib import Path
from unittest.mock import patch

from cli import autonomy_batch, autonomy_cycle, autonomy_profile, autonomy_records, autonomy_workspace, record_first
from cli import main as climain


def run(argv):
    o,e=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(o),contextlib.redirect_stderr(e):
        try: rc=climain.main(argv)
        except SystemExit as ex: rc=int(ex.code or 0)
    return rc,o.getvalue(),e.getvalue()


def git_repo(path: Path):
    path.mkdir(parents=True); subprocess.run(["git","init","-q","-b","main",str(path)],check=True)
    subprocess.run(["git","-C",str(path),"config","user.email","x@y.z"],check=True)
    subprocess.run(["git","-C",str(path),"config","user.name","x"],check=True)
    (path/"README.md").write_text("base\n",encoding="utf-8"); subprocess.run(["git","-C",str(path),"add","."],check=True); subprocess.run(["git","-C",str(path),"commit","-qm","init"],check=True)


def setup(root: Path):
    c=root/"canonical"; git_repo(c/"repo")
    p=autonomy_profile.build_profile(profile_id="demo",canonical_root=str(c),canonical_project_id="demo",autonomy_root=str(root/"auto"),mutable_repos=["repo"],support_repos=[],goals=["quality"],difficulty_ceiling="L0",max_new_tasks=3)
    autonomy_profile.save_profile(p); ws=autonomy_workspace.initialize_workspace("demo")
    return p,ws


def create_task(root: Path, profile, task_id):
    auto=Path(profile["autonomous"]["workspace_root"]); old=Path.cwd(); os.chdir(auto)
    try:
        rc,o,e=run(["task","create","--id",task_id,"--project","autonomy-demo","--risk","L0","--flow","L0","--title",task_id,"--scaffold"])
    finally: os.chdir(old)
    assert rc==0,(o,e)
    td=auto/".tp-spec"/"tasks"/task_id
    autonomy_records.record_discovered("demo",task_id,str(td),discovery_key=f"repo/{task_id}")
    return td


def approve(profile, task):
    autonomy_records.record_decision("demo",task,decision="APPROVED",reason="ok")


def complete_l0(ws, task, td):
    db=ws["db_path"]
    record_first.checkpoint(task_id=task,task_dir=str(td),actor="tp-development-engineering",phase="development",summary="done",db=db)
    record_first.complete(task_id=task,task_dir=str(td),actor="tp-development-engineering",summary="complete",db=db)


def test_batch_groups_approved_tasks_and_commits_each_task_on_same_cumulative_staging_line():
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); t1=create_task(root,p,"TASK-AUTO-1"); t2=create_task(root,p,"TASK-AUTO-2")
            c0=autonomy_cycle.begin_cycle("demo"); approve(p,"TASK-AUTO-1"); approve(p,"TASK-AUTO-2"); autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"])
            c1=autonomy_cycle.begin_cycle("demo")
            # approval becomes effective in this generation
            batch=autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1","TASK-AUTO-2"])
            repo=Path(p["autonomous"]["workspace_root"])/"repo"
            base=batch["repositories"]["repo"]["base_head"]
            autonomy_batch.start_task("demo",batch["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            (repo/"A.txt").write_text("a\n",encoding="utf-8"); complete_l0(ws,"TASK-AUTO-1",t1)
            r1=autonomy_batch.commit_task("demo",batch["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            h1=r1["repositories"]["repo"]["commit"]
            assert h1 != base
            autonomy_batch.start_task("demo",batch["batch_id"],"TASK-AUTO-2",c1["cycle_id"],c1["generation"])
            (repo/"B.txt").write_text("b\n",encoding="utf-8"); complete_l0(ws,"TASK-AUTO-2",t2)
            r2=autonomy_batch.commit_task("demo",batch["batch_id"],"TASK-AUTO-2",c1["cycle_id"],c1["generation"])
            h2=r2["repositories"]["repo"]["commit"]
            assert subprocess.check_output(["git","-C",str(repo),"rev-parse",f"{h2}^"],text=True).strip()==h1
            final=autonomy_batch.finalize_batch("demo",batch["batch_id"],c1["cycle_id"],c1["generation"])
            assert final["status"]=="READY_FOR_INTEGRATION"
            assert final["repositories"]["repo"]["head"]==h2

            # A later Batch naturally starts from the previous successful staging HEAD.
            t3=create_task(root,p,"TASK-AUTO-3"); approve(p,"TASK-AUTO-3")
            autonomy_cycle.end_cycle("demo",c1["cycle_id"],c1["generation"])
            c2=autonomy_cycle.begin_cycle("demo")
            b2=autonomy_batch.create_batch("demo",c2["cycle_id"],c2["generation"],["TASK-AUTO-3"])
            assert b2["repositories"]["repo"]["base_head"]==h2


def test_abort_task_restores_autonomous_repo_to_recorded_start_without_touching_canonical():
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); task=create_task(root,p,"TASK-AUTO-1"); c0=autonomy_cycle.begin_cycle("demo"); approve(p,"TASK-AUTO-1"); autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"]); c1=autonomy_cycle.begin_cycle("demo")
            b=autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1"]); repo=Path(p["autonomous"]["workspace_root"])/"repo"
            start=autonomy_batch.start_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])["repositories"]["repo"]
            (repo/"bad.txt").write_text("bad\n",encoding="utf-8")
            autonomy_batch.abort_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            assert not (repo/"bad.txt").exists()
            assert subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()==start


def test_partial_batch_preserves_completed_task_commits_and_defers_aborted_task_to_next_cycle():
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); td1=create_task(root,p,"TASK-AUTO-1"); td2=create_task(root,p,"TASK-AUTO-2")
            c0=autonomy_cycle.begin_cycle("demo"); approve(p,"TASK-AUTO-1"); approve(p,"TASK-AUTO-2"); autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"])
            c1=autonomy_cycle.begin_cycle("demo")
            batch=autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1","TASK-AUTO-2"])
            repo=Path(p["autonomous"]["workspace_root"])/"repo"
            autonomy_batch.start_task("demo",batch["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            (repo/"good.txt").write_text("good\n",encoding="utf-8"); complete_l0(ws,"TASK-AUTO-1",td1)
            r1=autonomy_batch.commit_task("demo",batch["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            good_head=r1["repositories"]["repo"]["head"]
            autonomy_batch.start_task("demo",batch["batch_id"],"TASK-AUTO-2",c1["cycle_id"],c1["generation"])
            (repo/"bad.txt").write_text("bad\n",encoding="utf-8")
            autonomy_batch.abort_task("demo",batch["batch_id"],"TASK-AUTO-2",c1["cycle_id"],c1["generation"])
            final=autonomy_batch.finalize_batch("demo",batch["batch_id"],c1["cycle_id"],c1["generation"])
            assert final["status"]=="PARTIAL_READY"
            assert final["ready_tasks"]==["TASK-AUTO-1"]
            assert final["deferred_tasks"]==["TASK-AUTO-2"]
            assert final["repositories"]["repo"]["head"]==good_head
            autonomy_cycle.end_cycle("demo",c1["cycle_id"],c1["generation"])
            c2=autonomy_cycle.begin_cycle("demo")
            b2=autonomy_batch.create_batch("demo",c2["cycle_id"],c2["generation"],["TASK-AUTO-2"])
            assert b2["repositories"]["repo"]["base_head"]==good_head


def test_batch_create_enforces_cycle_existing_task_budget_before_manifest_creation():
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); create_task(root,p,"TASK-AUTO-1"); create_task(root,p,"TASK-AUTO-2")
            profile=autonomy_profile.load_profile("demo"); profile["safety"]["max_existing_tasks_per_cycle"]=1; autonomy_profile.save_profile(profile,overwrite=True)
            c0=autonomy_cycle.begin_cycle("demo"); approve(p,"TASK-AUTO-1"); approve(p,"TASK-AUTO-2"); autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"])
            c1=autonomy_cycle.begin_cycle("demo")
            import pytest
            with pytest.raises(Exception,match="CYCLE_TASK_LIMIT_REACHED"):
                autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1","TASK-AUTO-2"])
            assert autonomy_batch.list_batches("demo")==[]
