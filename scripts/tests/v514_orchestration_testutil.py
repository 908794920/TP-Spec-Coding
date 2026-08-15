from __future__ import annotations
import json
import os
from pathlib import Path
from cli import db as dbmod
from cli.version import active_version


def make_db(path: Path, *, task_id='TASK-V514', risk='L1', flow='L1', state='NEW', phase='intake') -> str:
    # Machine-local workflow preference must never make Base tests depend on the developer's real ~/.tp-spec.
    os.environ['TP_SPEC_USER_ROOT'] = str(path.parent / '.tp-spec-test-user')
    path.parent.mkdir(parents=True, exist_ok=True)
    conn=dbmod.connect(str(path)); dbmod.init_schema(conn)
    now=dbmod.now_iso(); v=active_version()
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',('demo','demo',str(path.parent.parent),v,1,now,now))
        conn.execute('INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(task_id,'demo','test',risk,flow,state,phase,'tp-requirement-analysis',v,now,now))
    conn.close(); return str(path)


def add_checkpoint(db: str, task: str, actor: str, phase: str, summary='done'):
    conn=dbmod.connect(db); now=dbmod.now_iso(); detail=json.dumps({'operation':'CHECKPOINT','phase':phase,'schema_version':active_version()})
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,to_stage,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',(task,'FACT',phase,actor,summary,detail,now))
        conn.execute("UPDATE task SET current_state='ACTIVE',current_stage=?,owner_role=?,updated_at=? WHERE task_id=?",(phase,actor,now,task))
    conn.close()


def add_decision(db: str, task: str, summary: str):
    conn=dbmod.connect(db); now=dbmod.now_iso()
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,actor_role,summary,created_at) VALUES(?,?,?,?,?)',(task,'DECISION','human_owner',summary,now))
    conn.close()


def add_workflow_confirmation(db: str, task: str, confirmation_policy=None):
    from cli import orchestration, workflow_records
    route = orchestration.resolve_route(task, db_path=db, confirmation_policy=confirmation_policy)
    if route.get('recommended_action') != 'await_confirmation' or not isinstance(route.get('confirmation_binding'), dict):
        raise AssertionError(f'no bound workflow confirmation is pending: {route}')
    binding = route['confirmation_binding']
    conn = dbmod.connect(db); now = dbmod.now_iso(); v = active_version()
    detail = workflow_records.build_confirmation_detail(
        task_id=task, binding=binding, transaction_id='test-workflow-confirm',
        flush_id='TEST-WORKFLOW-CONFIRM', created_at=now, schema_version=v,
    )
    with dbmod.transactional(conn):
        conn.execute(
            'INSERT INTO task_event(task_id,event_type,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (task,'WORKFLOW_CONFIRMATION','human_owner',route.get('confirmation_reason'),
             f"confirmed {binding.get('confirmation_kind')} boundary",json.dumps(detail),v,now),
        )
    conn.close()
    return binding


def add_review(db: str, task: str, decision='PASS'):
    conn=dbmod.connect(db); now=dbmod.now_iso(); detail=json.dumps({'decision':decision,'review_kind':'ARCHITECTURE','schema_version':active_version()})
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',(task,'REVIEW_COMPLETED','tp-architecture-review',decision,detail,now))
    conn.close()


def add_verify(db: str, task: str, decision='PASS'):
    conn=dbmod.connect(db); now=dbmod.now_iso(); detail=json.dumps({'decision':decision,'review_kind':'VERIFICATION','schema_version':active_version()})
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,to_stage,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',(task,'VERIFICATION_COMPLETED','verification','tp-verification-engineering',decision,detail,now))
        conn.execute("UPDATE task SET current_state='ACTIVE',current_stage='verification',owner_role='tp-verification-engineering',updated_at=? WHERE task_id=?",(now,task))
    conn.close()
