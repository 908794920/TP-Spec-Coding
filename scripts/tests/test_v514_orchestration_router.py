import tempfile
from pathlib import Path
from cli import orchestration
from scripts.tests.v514_orchestration_testutil import make_db,add_checkpoint,add_decision,add_review,add_verify,add_workflow_confirmation


def test_effective_level_never_downgrades():
    assert orchestration.resolve_effective_level('L3','L1')=='L3'
    assert orchestration.resolve_effective_level('L1','L2')=='L2'

def test_l1_standard_route():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L1',flow='L1')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='requirement'
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture' and r['execution_mode']=='DIRECT'
        assert r['transition_notice_required'] is True and r['transition_from_role']=='tp-requirement-analysis'
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='development'
        assert r['transition_notice_required'] is True and r['transition_from_role']=='tp-architecture-design'

def test_l3_ultraplan_only_on_multiple_route_signal():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture' and r['execution_mode']=='DIRECT'
        add_decision(db,'TASK-V514','workflow:multiple-feasible-routes')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['execution_mode']=='COMPARATIVE'

def test_l3_architecture_review_then_material_confirmation():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture_review'
        add_review(db,'TASK-V514','PASS')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='development' and r['confirmation_required'] is True
        assert r['recommended_action']=='await_confirmation' and r['skill_path'] is None
        assert r['transition_from_role']=='tp-architecture-review'
        add_workflow_confirmation(db,'TASK-V514')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['confirmation_required'] is False and r['skill_path'].endswith('tp-development-engineering/SKILL.md')

def test_verification_rework_and_deep_review():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        for actor,phase in [('tp-requirement-analysis','requirement'),('tp-architecture-design','architecture')]: add_checkpoint(db,'TASK-V514',actor,phase)
        add_review(db,'TASK-V514','PASS'); add_workflow_confirmation(db,'TASK-V514')
        add_checkpoint(db,'TASK-V514','tp-development-engineering','development')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='verification' and r['execution_mode']=='DEEP_REVIEW'
        assert r['transition_from_role']=='tp-development-engineering'
        add_verify(db,'TASK-V514','NEEDS_FIX')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='development' and 'VERIFICATION_NEEDS_FIX' in r['reason_codes']
        assert r['transition_from_role']=='tp-verification-engineering'
