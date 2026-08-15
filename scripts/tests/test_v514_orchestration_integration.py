import contextlib,io,json,tempfile
from pathlib import Path
from cli import db as dbmod
from cli import main as climain, orchestration
from scripts.tests.v514_orchestration_testutil import make_db,add_checkpoint,add_decision,add_review,add_verify,add_workflow_confirmation


def run(argv):
    o,e=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(o),contextlib.redirect_stderr(e):
        rc=climain.main(argv)
    return rc,o.getvalue(),e.getvalue()

def test_workflow_next_cli_is_readonly_and_json_stable():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db')
        conn=dbmod.connect_readonly(db); before=conn.execute('select count(*) c from task_event').fetchone()['c']; conn.close()
        rc,out,err=run(['workflow','next','--task','TASK-V514','--db',db,'--json'])
        assert rc==0,(out,err); data=json.loads(out)
        assert data['schema']=='tp-spec.workflow-route/v1' and data['recommended_action']=='dispatch_role'
        conn=dbmod.connect_readonly(db); after=conn.execute('select count(*) c from task_event').fetchone()['c']; conn.close()
        assert before==after

def test_blocked_and_terminal_do_not_dispatch():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',state='BLOCKED',phase='development')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['role_id'] is None and r['recommended_action']=='task_resume_after_resolution'
        conn=dbmod.connect(db); conn.execute("update task set current_state='COMPLETED' where task_id='TASK-V514'"); conn.close()
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['recommended_action']=='none'

def test_l3_pass_requires_structured_delivery_result_not_plain_checkpoint():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        add_review(db,'TASK-V514','PASS')
        add_workflow_confirmation(db,'TASK-V514')
        add_checkpoint(db,'TASK-V514','tp-development-engineering','development')
        add_verify(db,'TASK-V514','PASS')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='delivery' and r['role_id']=='tp-delivery-convergence'
        add_checkpoint(db,'TASK-V514','tp-delivery-convergence','delivery')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='delivery' and r['recommended_action']=='dispatch_role'
