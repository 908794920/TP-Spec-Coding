import json
import tempfile
from pathlib import Path

from cli import db as dbmod
from cli import orchestration
from scripts.tests.v514_orchestration_testutil import make_db, add_checkpoint, add_decision


def add_arch_review(db, task, decision='PASS'):
    conn = dbmod.connect(db); now = dbmod.now_iso()
    detail = json.dumps({
        'decision': decision,
        'review_kind': 'ARCHITECTURE',
        'schema_version': '5.2.5',
        'context_policy': 'isolated',
        'design_execution_context_id': 'ctx-design',
        'review_execution_context_id': 'ctx-review',
        'review_subject_digest': 'sha256:test',
    })
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',
                     (task,'REVIEW_COMPLETED','tp-software-architect',decision,detail,now))
    conn.close()



def add_verify(db, task, decision='PASS'):
    conn = dbmod.connect(db); now = dbmod.now_iso()
    detail = json.dumps({'decision': decision, 'review_kind': 'VERIFICATION', 'schema_version': '5.2.5', 'subject_digest': 'sha256:test'})
    with dbmod.transactional(conn):
        conn.execute('INSERT INTO task_event(task_id,event_type,to_stage,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',
                     (task,'VERIFICATION_COMPLETED','verification','tp-test-engineer',decision,detail,now))
    conn.close()

def test_contract_doctor_accepts_capability_mode_hosts():
    assert orchestration.validate_contract() == []


def test_l1_routes_formal_roles_and_preserves_effect_boundary():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / 'x.db', risk='L1', flow='L1')
        r = orchestration.resolve_route('TASK-V514', db_path=db)
        assert r['role_id'] == 'tp-product-manager'
        add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
        r = orchestration.resolve_route('TASK-V514', db_path=db)
        assert r['role_id'] == 'tp-software-architect' and r['next_stage'] == 'architecture'
        add_checkpoint(db, 'TASK-V514', 'tp-software-architect', 'architecture')
        # L1 planning is contextual and therefore skipped by default.
        r = orchestration.resolve_route('TASK-V514', db_path=db, allowed_effects=[])
        assert r['recommended_action'] == 'await_effect_approval'
        assert r['next_stage'] == 'development'
        assert r['required_effects'] == ['repo_mutation']
        r = orchestration.resolve_route('TASK-V514', db_path=db, allowed_effects=['repo_mutation'])
        assert r['role_id'] == 'tp-development-engineer'


def test_security_and_database_signals_are_recommended_not_new_stages():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / 'x.db', risk='L1', flow='L1')
        add_decision(db, 'TASK-V514', 'workflow:security-risk')
        add_decision(db, 'TASK-V514', 'workflow:database-risk')
        r = orchestration.resolve_route('TASK-V514', db_path=db)
        ids = {row['role_id'] for row in r['recommended_roles']}
        assert {'tp-security-engineer', 'tp-database-engineer'} <= ids
        assert r['next_stage'] == 'requirement'


def test_auto_review_host_is_code_reviewer_on_deep_review():
    with tempfile.TemporaryDirectory() as td:
        db = make_db(Path(td) / 'x.db', risk='L1', flow='L1')
        add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
        add_checkpoint(db, 'TASK-V514', 'tp-software-architect', 'architecture')
        add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
        add_verify(db, 'TASK-V514')
        add_decision(db, 'TASK-V514', 'workflow:deep-review')
        r = orchestration.resolve_route('TASK-V514', db_path=db)
        assert r['next_stage'] == 'review'
        assert r['role_id'] == 'tp-code-reviewer'
        assert r['execution_mode'] == 'DEEP_REVIEW'
