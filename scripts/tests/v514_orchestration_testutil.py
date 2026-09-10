from __future__ import annotations
import json
from pathlib import Path
from cli import db as dbmod
from cli.version import active_version
from cli.event_contract import EVENT_SCHEMA, add_event_semantics

FIXTURE_CHANGE_SET_ID = "sha256:" + ("0" * 64)


def make_db(path: Path, *, task_id='TASK-V514', risk='L1', flow='L1', state='NEW', phase='intake') -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn=dbmod.connect(str(path)); dbmod.init_schema(conn)
    now=dbmod.now_iso(); v=active_version()
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',('demo','demo',str(path.parent.parent),v,1,now,now))
        conn.execute('INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(task_id,'demo','test',risk,flow,state,phase,'tp-product-manager',v,now,now))
    conn.close(); return str(path)


def add_checkpoint(db: str, task: str, actor: str, phase: str, summary='done'):
    payload = {'schema_version': active_version()}
    if actor == 'tp-development-engineer' and phase == 'development':
        payload['change_set_id'] = FIXTURE_CHANGE_SET_ID
    conn=dbmod.connect(db); now=dbmod.now_iso(); detail=json.dumps(add_event_semantics(
        payload,
        event_type='FACT', operation='CHECKPOINT', result_status='COMPLETED',
        producer='record-first', phase=phase,
    ))
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,to_stage,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',(task,'FACT',phase,actor,summary,detail,now))
        conn.execute("UPDATE task SET current_state='ACTIVE',current_stage=?,owner_role=?,updated_at=? WHERE task_id=?",(phase,actor,now,task))
    conn.close()


def add_decision(db: str, task: str, summary: str):
    conn=dbmod.connect(db); now=dbmod.now_iso()
    detail = add_event_semantics(
        {'signal': summary, 'schema_version': active_version()},
        event_type='DECISION', operation='RECORD', result_status='RECORDED',
        producer='test-fixture',
    )
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',(task,'DECISION','human_owner',summary,json.dumps(detail),now))
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
    conn=dbmod.connect(db); now=dbmod.now_iso(); detail=json.dumps(add_event_semantics(
        {'review_kind':'ARCHITECTURE','schema_version':active_version()},
        event_type='REVIEW_COMPLETED', operation='REVIEW',
        result_status='BLOCKED' if decision == 'BLOCKED' else 'COMPLETED',
        decision=decision, producer='test-fixture',
    ))
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',(task,'REVIEW_COMPLETED','tp-software-architect',decision,detail,now))
    conn.close()


def add_verify(db: str, task: str, decision='PASS'):
    conn=dbmod.connect(db); now=dbmod.now_iso(); detail=json.dumps(add_event_semantics(
        {
            'review_kind':'VERIFICATION',
            'schema_version':active_version(),
            'change_set_id':FIXTURE_CHANGE_SET_ID,
        },
        event_type='VERIFICATION_COMPLETED', operation='VERIFY',
        result_status='BLOCKED' if decision == 'BLOCKED' else 'COMPLETED',
        decision=decision, producer='test-fixture',
    ))
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,to_stage,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',(task,'VERIFICATION_COMPLETED','verification','tp-test-engineer',decision,detail,now))
        conn.execute("UPDATE task SET current_state='ACTIVE',current_stage='verification',owner_role='tp-test-engineer',updated_at=? WHERE task_id=?",(now,task))
    conn.close()


def add_code_review(db: str, task: str, decision='PASS'):
    conn=dbmod.connect(db)
    verification = conn.execute(
        "SELECT id FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED' "
        "AND actor_role='tp-test-engineer' ORDER BY id DESC LIMIT 1",
        (task,),
    ).fetchone()
    verification_event_id = int(verification['id']) if verification is not None else 0
    now=dbmod.now_iso(); detail=json.dumps(add_event_semantics(
        {
            'review_kind':'CODE',
            'schema_version':active_version(),
            'change_set_id':FIXTURE_CHANGE_SET_ID,
            'verification_event_id':verification_event_id,
        },
        event_type='REVIEW_COMPLETED', operation='REVIEW',
        result_status='BLOCKED' if decision == 'BLOCKED' else 'COMPLETED',
        decision=decision, producer='test-fixture',
    ))
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,to_stage,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',(task,'REVIEW_COMPLETED','review','tp-code-reviewer',decision,detail,now))
        conn.execute("UPDATE task SET current_state='ACTIVE',current_stage='review',owner_role='tp-code-reviewer',updated_at=? WHERE task_id=?",(now,task))
    conn.close()


def make_bound_runtime(root: Path, *, level="L2", with_review=True):
    """Build positive delivery fixtures through real writers, not legacy bare IDs.

    Evidence is explicitly synthetic. This establishes machine contracts only,
    not real business testing or an independently running reviewer.
    """
    from scripts.tests.test_v529_change_set_binding import make_repo
    from scripts.tests.v532_testutil import run_cli, task_args

    project = make_repo(root, "project")
    registry = root / "registry.json"
    registry.write_text('{"projects": []}\n', encoding="utf-8")
    rc, out, err = run_cli(["project", "bootstrap", "--id", "demo", "--root", str(project),
                            "--registry", str(registry)])
    assert rc == 0, (out, err)
    db = project / ".tp-spec/db/demo.db"
    task_dir = project / ".tp-spec/tasks/TASK-V514"
    rc, out, err = run_cli(["task", "create", "--id", "TASK-V514", "--project", "demo",
                            "--risk", level, "--flow", level, "--db", str(db),
                            "--scaffold", "--task-dir", str(task_dir)])
    assert rc == 0, (out, err)
    (task_dir / "acceptance.md").write_text(
        '# Isolated routing fixture\n\n```yaml\nno_acceptance_required:\n'
        '  declared: true\n  reason: No business acceptance claims in this fixture.\n```\n',
        encoding="utf-8",
    )
    rc, out, err = run_cli(task_args(db, task_dir, "TASK-V514", "checkpoint",
        "--actor", "tp-development-engineer", "--phase", "development", "--summary", "fixture scope",
        "--repo-root", str(project)))
    assert rc == 0, (out, err)
    evidence = task_dir / "evidence/verification.txt"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text("Synthetic verification evidence for routing contract.\n", encoding="utf-8")
    rc, out, err = run_cli(task_args(db, task_dir, "TASK-V514", "verify",
        "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "fixture verification",
        "--evidence", "evidence/verification.txt"))
    assert rc == 0, (out, err)
    if with_review:
        add_bound_code_review(str(db), task_dir)
    return str(db), task_dir


def add_bound_code_review(db: str, task_dir: Path):
    from scripts.tests.v532_testutil import run_cli
    (task_dir / "evidence/code-review.txt").write_text(
        "Synthetic reviewer report for routing contract.\n", encoding="utf-8")
    rc, out, err = run_cli(["review", "record", "--task", "TASK-V514", "--task-dir", str(task_dir),
        "--db", db, "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS",
        "--summary", "fixture review", "--evidence", "evidence/code-review.txt"])
    assert rc == 0, (out, err)
