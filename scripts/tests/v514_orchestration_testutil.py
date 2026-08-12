from __future__ import annotations
import json
from pathlib import Path
from cli import db as dbmod
from cli.version import active_version


def make_db(path: Path, *, task_id='TASK-V514', risk='L1', flow='L1', state='NEW', phase='intake') -> str:
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
