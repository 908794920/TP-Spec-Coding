from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli import orchestration
from cli import db as dbmod
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args
from scripts.tests.v514_orchestration_testutil import (
    add_checkpoint,
    add_code_review,
    add_decision,
    add_verify,
    make_db,
)

BASE = Path(__file__).resolve().parents[2]


def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, level: str) -> str:
    monkeypatch.setenv("TP_SPEC_USER_ROOT", str(tmp_path / "user-root"))
    return make_db(tmp_path / f"{level}.db", risk=level, flow=level)


@pytest.mark.parametrize(
    ("level", "signals", "expected"),
    [
        (
            "L0",
            ("workflow:behavioral-change", "workflow:deep-review"),
            {
                "development": (True, ""),
                "verification": (False, "behavioral_change"),
                "review": (False, "deep_review"),
            },
        ),
        (
            "L1",
            ("workflow:include-stage:planning", "workflow:include-stage:architecture", "workflow:deep-review"),
            {
                "requirement": (False, "unresolved_scope"),
                "architecture": (False, "architecture_risk"),
                "planning": (False, "contextual"),
                "development": (True, ""),
                "verification": (True, ""),
                "review": (False, "deep_review"),
            },
        ),
        (
            "L2",
            ("workflow:include-stage:product", "workflow:include-stage:architecture", "workflow:include-stage:planning", "workflow:include-stage:architecture_review"),
            {
                "requirement": (False, "unresolved_scope"),
                "product": (False, "contextual"),
                "architecture": (False, "architecture_risk"),
                "architecture_review": (False, "architecture_risk"),
                "planning": (False, "contextual"),
                "development": (True, ""),
                "verification": (True, ""),
                "review": (True, ""),
                "delivery": (True, ""),
            },
        ),
        (
            "L3",
            ("workflow:include-stage:product", "workflow:include-stage:architecture", "workflow:include-stage:architecture_review", "workflow:include-stage:planning"),
            {
                "requirement": (False, "unresolved_scope"),
                "product": (False, "contextual"),
                "architecture": (False, "architecture_risk"),
                "architecture_review": (False, "architecture_risk"),
                "planning": (False, "contextual"),
                "development": (True, ""),
                "verification": (True, ""),
                "review": (True, ""),
                "delivery": (True, ""),
            },
        ),
    ],
)
def test_progress_steps_preserve_required_trigger_and_definition_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    signals: tuple[str, ...],
    expected: dict[str, tuple[bool, str]],
):
    db = _db(tmp_path, monkeypatch, level=level)
    for signal in signals:
        add_decision(db, "TASK-V514", signal)

    progress = orchestration.resolve_progress("TASK-V514", db_path=db)
    by_stage = {step["stage"]: step for step in progress["steps"]}

    assert set(by_stage) == set(expected)
    for stage, (required, trigger) in expected.items():
        assert by_stage[stage]["required"] is required
        assert by_stage[stage]["trigger"] == trigger
        assert by_stage[stage]["definition_source"] == "workflow.pipeline"


def test_progress_projects_security_and_database_as_conditional_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    add_decision(db, "TASK-V514", "workflow:security-risk")
    add_decision(db, "TASK-V514", "workflow:database-risk")

    progress = orchestration.resolve_progress("TASK-V514", db_path=db)
    roles = {item["role_id"]: item for item in progress["conditional_roles"]}

    assert set(roles) == {"tp-security-engineer", "tp-database-engineer"}
    assert roles["tp-security-engineer"]["role_display"]["label"] == "tp-安全工程师"
    assert roles["tp-security-engineer"]["trigger"] == "security_risk"
    assert roles["tp-security-engineer"]["reason_code"] == "SECURITY_RISK"
    assert roles["tp-database-engineer"]["role_display"]["label"] == "tp-数据库工程师"
    assert roles["tp-database-engineer"]["trigger"] == "database_risk"
    assert roles["tp-database-engineer"]["reason_code"] == "DATABASE_RISK"
    assert all(item["definition_source"] == "workflow.conditional_roles" for item in roles.values())


def test_progress_deduplicates_conditional_role_already_used_by_pipeline_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    task = "TASK-V514"
    add_checkpoint(db, task, "tp-product-manager", "requirement")
    add_checkpoint(db, task, "tp-software-architect", "architecture")
    add_checkpoint(db, task, "tp-development-engineer", "development")
    add_verify(db, task, "PASS")
    add_decision(db, task, "workflow:deep-review")

    route = orchestration.resolve_route(task, db_path=db)
    assert route["next_stage"] == "review"
    assert {item["role_id"] for item in route["recommended_roles"]} == {"tp-code-reviewer"}

    progress = orchestration.resolve_progress(task, db_path=db)
    assert "tp-code-reviewer" in {step["role"] for step in progress["steps"]}
    assert "tp-code-reviewer" not in {item["role_id"] for item in progress["conditional_roles"]}


def test_progress_complete_terminal_has_no_execution_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    monkeypatch.setattr(
        orchestration,
        "resolve_route",
        lambda *args, **kwargs: {
            "effective_level": "L1",
            "next_stage": "complete",
            "role_id": None,
            "recommended_action": "task_complete",
            "confirmation_required": False,
            "confirmation_reason": "",
            "reason_codes": ["PIPELINE_COMPLETE"],
            "decision": "TASK_COMPLETE",
            "recommended_roles": [],
        },
    )

    progress = orchestration.resolve_progress("TASK-V514", db_path=db)

    assert progress["next_step"]["stage"] == "complete"
    assert progress["next_step"]["role"] == ""
    assert progress["next_step"]["role_display"]["label"] == ""


def test_progress_projection_does_not_change_review_rework_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = _db(tmp_path, monkeypatch, level="L1")
    task = "TASK-V514"
    add_checkpoint(db, task, "tp-product-manager", "requirement")
    add_checkpoint(db, task, "tp-software-architect", "architecture")
    add_checkpoint(db, task, "tp-development-engineer", "development")
    add_verify(db, task, "PASS")
    add_decision(db, task, "workflow:deep-review")
    add_code_review(db, task, "NEEDS_FIX")

    keys = (
        "next_stage",
        "role_id",
        "recommended_action",
        "reason_codes",
        "confirmation_required",
    )
    before = orchestration.resolve_route(task, db_path=db)
    orchestration.resolve_progress(task, db_path=db)
    after = orchestration.resolve_route(task, db_path=db)

    assert {key: after.get(key) for key in keys} == {key: before.get(key) for key in keys}
    assert after["next_stage"] == "development"
    assert after["role_id"] == "tp-development-engineer"


def test_task_card_visually_separates_steps_execution_roles_and_conditional_roles():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "工作步骤" in text
    assert "执行角色：" in text
    assert "条件参与角色" in text
    assert "必需步骤" in text
    assert "条件步骤" in text
    assert "角色代表专业职责/SKILL，不代表独立人员" in text
    assert "definition_source" in text
    assert "reason_code" in text
    assert '"workflow.conditional_roles"' not in text  # definition source value comes from projection data

# B06: these summaries are Runtime records, not a process monitor or project PASS.


def test_b06_completed_task_with_pending_workitem_reports_drift_without_repair(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    assert run_cli(['workitem','create','--task',tid,'--id','WI-1','--title','Pending milestone','--db',str(db)])[0] == 0
    assert run_cli(task_args(db,tdir,tid,'checkpoint','--actor','tp-development-engineer','--phase','development','--summary','WP-0 complete'))[0] == 0
    assert run_cli(task_args(db,tdir,tid,'complete','--actor','tp-development-engineer','--summary','WP-0 only'))[0] == 0
    before = (tdir/'generated/final-result.md').read_bytes()
    with dbmod.connect_readonly(str(db)) as conn:
        events = conn.execute('SELECT COUNT(*) FROM task_event').fetchone()[0]
    progress = orchestration.resolve_progress(tid,db_path=str(db))
    assert progress['work_items']['consistency'] == 'NEEDS_RECONCILIATION'
    assert progress['work_items']['counts'] == {'PENDING':1,'ACTIVE':0,'COMPLETED':0}
    assert progress['work_items']['completion_scope'] == 'task_work_items_only'
    assert progress['current_step'] == {} and progress['next_step'] == {}
    rc,out,err = run_cli(['report','task-summary','--task',tid,'--db',str(db)])
    assert rc == 0 and 'NEEDS_RECONCILIATION' in out, (out,err)
    rc,out,err = run_cli(['workitem','list','--task',tid,'--db',str(db)])
    assert rc == 0 and 'NEEDS_RECONCILIATION' in out, (out,err)
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT status FROM work_item').fetchone()[0] == 'PENDING'
        assert conn.execute('SELECT COUNT(*) FROM task_event').fetchone()[0] == events
    assert (tdir/'generated/final-result.md').read_bytes() == before


def test_b06_open_work_record_is_not_process_liveness(tmp_path, monkeypatch):
    _,db,tdir,tid = make_runtime(tmp_path,monkeypatch)
    assert run_cli(['work','start','--task',tid,'--role','tp-development-engineer','--agent','worker-a','--db',str(db)])[0] == 0
    progress = orchestration.resolve_progress(tid,db_path=str(db))
    record = progress['work_sessions']
    assert record['runtime_status'] == 'UNKNOWN'
    assert record['open_count'] == 1
    assert record['open_sessions'][0]['actor_agent'] == 'worker-a'
    assert record['open_sessions'][0]['model_used'] == ''
    assert record['last_recorded_at']
    assert '运行状态未知' in record['summary']
    rc,out,err = run_cli(['report','stage-time','--task',tid,'--db',str(db)])
    assert rc == 0 and '运行状态未知' in out, (out,err)
    assert run_cli(task_args(db,tdir,tid,'cancel','--actor','human_owner','--reason','stop'))[0] == 0
    stopped = orchestration.resolve_progress(tid,db_path=str(db))
    assert stopped['current_step'] == {} and stopped['next_step'] == {}
    assert stopped['work_sessions']['open_count'] == 1
    assert stopped['work_sessions']['runtime_status'] == 'UNKNOWN'


def test_b06_workitems_completed_do_not_grant_task_or_dependency_completion(tmp_path, monkeypatch):
    _,db,_,tid = make_runtime(tmp_path,monkeypatch)
    def item(*args):
        rc,out,err = run_cli(['workitem',*args,'--task',tid,'--db',str(db)])
        assert rc == 0,(out,err)
    item('create','--id','WI-1','--depends','WI-UPSTREAM')
    item('complete','--id','WI-1')
    progress = orchestration.resolve_progress(tid,db_path=str(db))
    assert progress['work_items']['items'][0]['unresolved_dependencies'] == ['WI-UPSTREAM']
    assert progress['work_items']['consistency'] == 'NEEDS_RECONCILIATION'
    assert progress['work_items']['counts']['COMPLETED'] == 1
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT current_state FROM task').fetchone()[0] not in ['COMPLETED','CANCELLED']


def test_b06_retirement_keeps_original_state_and_open_work_history(tmp_path,monkeypatch):
    _,db,tdir,tid = make_runtime(tmp_path,monkeypatch)
    assert run_cli(task_args(db,tdir,tid,'checkpoint','--actor','tp-development-engineer','--phase','development','--summary','record'))[0] == 0
    assert run_cli(['work','start','--task',tid,'--role','tp-development-engineer','--db',str(db)])[0] == 0
    rc,out,err = run_cli(['task','retire','--task',tid,'--actor','human_owner','--reason','synthetic historical instance','--db',str(db)])
    assert rc == 0,(out,err)
    route = orchestration.resolve_route(tid,db_path=str(db))
    assert route['recommended_action']=='none' and route['role_id'] is None
    assert route['reason_codes']==['TASK_RETIRED']
    progress = orchestration.resolve_progress(tid,db_path=str(db))
    assert progress['retired'] and progress['current_step']=={} and progress['next_step']=={}
    assert progress['work_sessions']['open_count']==1
    assert progress['work_items']['current'] is False
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT current_state FROM task').fetchone()[0]=='ACTIVE'
    rc,out,err = run_cli(['work','start','--task',tid,'--role','tp-code-reviewer','--db',str(db)])
    assert rc != 0 and 'TASK_NOT_CURRENT' in err,(out,err)


@pytest.mark.parametrize('metadata', ['null','{"bad":1}','["MISSING"]','{broken'])
def test_b06_invalid_workitem_metadata_is_reported_without_repair(tmp_path,monkeypatch,metadata):
    _,db,_,tid = make_runtime(tmp_path,monkeypatch)
    assert run_cli(['workitem','create','--task',tid,'--id','WI-1','--db',str(db)])[0]==0
    with dbmod.connect(str(db)) as conn:
        with dbmod.transactional(conn):
            conn.execute('UPDATE work_item SET depends_on_json=?',(metadata,))
    progress = orchestration.resolve_progress(tid,db_path=str(db))
    assert progress['work_items']['consistency']=='NEEDS_RECONCILIATION'
    assert progress['work_items']['issues']
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT depends_on_json FROM work_item').fetchone()[0]==metadata


def test_b06_all_items_done_but_no_sessions_is_not_task_completion(tmp_path,monkeypatch):
    _,db,_,tid = make_runtime(tmp_path,monkeypatch)
    for args in [('create',),('complete',)]:
        assert run_cli(['workitem',*args,'--task',tid,'--id','WI-1','--db',str(db)])[0]==0
    progress = orchestration.resolve_progress(tid,db_path=str(db))
    assert progress['work_items']['consistency']=='RECORDED'
    assert progress['work_items']['counts']['COMPLETED']==1
    assert progress['work_sessions']['runtime_status']=='UNKNOWN'
    assert progress['work_sessions']['last_recorded_at']==''
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT current_state FROM task').fetchone()[0]=='NEW'


def test_b06_milestone_list_shows_dependencies_without_changing_items(tmp_path, monkeypatch):
    _, db, _, tid = make_runtime(tmp_path, monkeypatch)
    for item_id, dependencies in [('WI-1', []), ('WI-2', ['--depends', 'WI-1'])]:
        assert run_cli(['workitem', 'create', '--task', tid, '--id', item_id,
                        *dependencies, '--db', str(db)])[0] == 0
    rc, out, err = run_cli(['workitem', 'list', '--task', tid, '--status', 'PENDING', '--db', str(db)])
    assert rc == 0, (out, err)
    assert 'WI-2' in out and 'depends=WI-1 waiting_on=WI-1' in out
    assert run_cli(['workitem', 'complete', '--task', tid, '--id', 'WI-1', '--db', str(db)])[0] == 0
    rc, out, err = run_cli(['workitem', 'list', '--task', tid, '--status', 'PENDING', '--db', str(db)])
    assert rc == 0, (out, err)
    assert 'depends=WI-1 waiting_on=-' in out and '已完成 1' in out
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute("SELECT status FROM work_item WHERE item_id='WI-2'").fetchone()[0] == 'PENDING'
