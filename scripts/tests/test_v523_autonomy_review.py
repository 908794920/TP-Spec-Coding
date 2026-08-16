from __future__ import annotations

import contextlib, io, os, subprocess, tempfile
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
    path.mkdir(parents=True)
    subprocess.run(["git","init","-q","-b","main",str(path)],check=True)
    subprocess.run(["git","-C",str(path),"config","user.email","x@y.z"],check=True)
    subprocess.run(["git","-C",str(path),"config","user.name","x"],check=True)
    (path/"README.md").write_text("base\n",encoding="utf-8")
    subprocess.run(["git","-C",str(path),"add","."],check=True)
    subprocess.run(["git","-C",str(path),"commit","-qm","init"],check=True)


def setup(root: Path):
    canonical=root/"canonical"; git_repo(canonical/"repo")
    p=autonomy_profile.build_profile(profile_id="demo",canonical_root=str(canonical),canonical_project_id="demo",autonomy_root=str(root/"auto"),mutable_repos=["repo"],support_repos=[],goals=["quality"],difficulty_ceiling="L0",max_new_tasks=3)
    autonomy_profile.save_profile(p); ws=autonomy_workspace.initialize_workspace("demo")
    return p,ws


def create_task(profile, task_id):
    auto=Path(profile["autonomous"]["workspace_root"]); old=Path.cwd(); os.chdir(auto)
    try: rc,o,e=run(["task","create","--id",task_id,"--project","autonomy-demo","--risk","L0","--flow","L0","--title",task_id,"--scaffold"])
    finally: os.chdir(old)
    assert rc==0,(o,e)
    td=auto/".tp-spec"/"tasks"/task_id
    autonomy_records.record_discovered("demo",task_id,str(td),discovery_key=f"repo/{task_id}")
    return td


def complete(ws, task_id, td):
    record_first.checkpoint(task_id=task_id,task_dir=str(td),actor="tp-development-engineering",phase="development",summary="done",db=ws["db_path"])
    record_first.complete(task_id=task_id,task_dir=str(td),actor="tp-development-engineering",summary="complete",db=ws["db_path"])


def test_review_inbox_batch_and_task_are_read_only_and_drill_down_to_real_git_diff():
    from cli import autonomy_review
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root); td=create_task(p,"TASK-AUTO-1")
            c0=autonomy_cycle.begin_cycle("demo"); autonomy_records.record_decision("demo","TASK-AUTO-1",decision="APPROVED",reason="ok"); autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"])
            c1=autonomy_cycle.begin_cycle("demo"); b=autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1"])
            autonomy_batch.start_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            repo=Path(p["autonomous"]["workspace_root"])/"repo"; (repo/"feature.txt").write_text("hello\n",encoding="utf-8")
            complete(ws,"TASK-AUTO-1",td); autonomy_batch.commit_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"]); autonomy_batch.finalize_batch("demo",b["batch_id"],c1["cycle_id"],c1["generation"])
            before=subprocess.check_output(["git","-C",str(repo),"status","--porcelain"],text=True)

            inbox=autonomy_review.inbox()
            assert inbox["profiles"][0]["profile_id"]=="demo"
            assert inbox["profiles"][0]["awaiting_integration"]==1
            br=autonomy_review.review_batch("demo",b["batch_id"])
            assert br["files_changed"]>=1 and br["tasks"][0]["task_id"]=="TASK-AUTO-1"
            tr=autonomy_review.review_task("demo","TASK-AUTO-1",include_diff=True)
            assert "feature.txt" in tr["repositories"]["repo"]["diff"]
            after=subprocess.check_output(["git","-C",str(repo),"status","--porcelain"],text=True)
            assert after==before


def test_review_cli_surface_is_user_session_and_requires_no_cycle_token():
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            setup(root)
            rc,out,err=run(["autonomy","review","profile","--profile","demo","--json"])
            assert rc==0,(out,err)
            assert '"profile_id": "demo"' in out


def test_review_profile_and_inbox_include_partial_ready_batch_as_awaiting_integration():
    from cli import autonomy_review
    with tempfile.TemporaryDirectory() as td0:
        root=Path(td0)
        with patch.dict(os.environ,{"TP_SPEC_USER_ROOT":str(root/"user")},clear=False):
            p,ws=setup(root)
            td1=create_task(p,"TASK-AUTO-1")
            td2=create_task(p,"TASK-AUTO-2")
            c0=autonomy_cycle.begin_cycle("demo")
            autonomy_records.record_decision("demo","TASK-AUTO-1",decision="APPROVED",reason="ok")
            autonomy_records.record_decision("demo","TASK-AUTO-2",decision="APPROVED",reason="ok")
            autonomy_cycle.end_cycle("demo",c0["cycle_id"],c0["generation"])

            c1=autonomy_cycle.begin_cycle("demo")
            b=autonomy_batch.create_batch("demo",c1["cycle_id"],c1["generation"],["TASK-AUTO-1","TASK-AUTO-2"])
            repo=Path(p["autonomous"]["workspace_root"])/"repo"
            autonomy_batch.start_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            (repo/"feature.txt").write_text("hello\n",encoding="utf-8")
            complete(ws,"TASK-AUTO-1",td1)
            autonomy_batch.commit_task("demo",b["batch_id"],"TASK-AUTO-1",c1["cycle_id"],c1["generation"])
            autonomy_batch.start_task("demo",b["batch_id"],"TASK-AUTO-2",c1["cycle_id"],c1["generation"])
            (repo/"deferred.txt").write_text("later\n",encoding="utf-8")
            autonomy_batch.abort_task("demo",b["batch_id"],"TASK-AUTO-2",c1["cycle_id"],c1["generation"])
            final=autonomy_batch.finalize_batch("demo",b["batch_id"],c1["cycle_id"],c1["generation"])
            assert final["status"]=="PARTIAL_READY"

            profile_view=autonomy_review.review_profile("demo")
            assert profile_view["awaiting_integration"]==1
            assert profile_view["ready_batches"]==[b["batch_id"]]
            inbox=autonomy_review.inbox()
            assert inbox["profiles"][0]["awaiting_integration"]==1
