import tempfile
from pathlib import Path
import pytest
from cli import orchestration
from scripts.tests.v514_orchestration_testutil import make_db,add_checkpoint,add_verify,add_review


def test_path_escape_is_rejected():
    with pytest.raises(orchestration.OrchestrationError):
        orchestration._safe_child(Path('/tmp/base'), '../escape/SKILL.md')

def test_invalid_levels_fail_closed():
    with pytest.raises(orchestration.OrchestrationError):
        orchestration.resolve_effective_level('LOW','HIGH')

def test_architecture_review_revise_routes_back_not_forward():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        add_review(db,'TASK-V514','REVISE')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture' and 'ARCHITECTURE_REVIEW_REVISE' in r['reason_codes']

def test_fail_reassesses_architecture_for_high_risk():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_verify(db,'TASK-V514','FAIL')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture'

def test_orchestrator_is_not_runtime_actor():
    from cli import record_first
    assert 'tp-workflow-orchestrator' not in record_first.ACTORS

def test_needs_fix_rework_checkpoint_advances_to_reverification():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L1',flow='L1')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        add_checkpoint(db,'TASK-V514','tp-development-engineering','development')
        add_verify(db,'TASK-V514','NEEDS_FIX')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='development'
        add_checkpoint(db,'TASK-V514','tp-development-engineering','development','rework done')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='verification'


def test_architecture_revise_new_checkpoint_invalidates_stale_downstream_work():
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        add_review(db,'TASK-V514','PASS')
        add_checkpoint(db,'TASK-V514','tp-development-engineering','development')
        add_review(db,'TASK-V514','REVISE')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture'
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture','revision done')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='architecture_review'
        add_review(db,'TASK-V514','PASS')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='development', 'old development checkpoint must be stale after architecture revision'
        assert r['confirmation_required'] is True


def test_old_material_confirmation_is_stale_after_architecture_revision():
    from scripts.tests.v514_orchestration_testutil import add_decision
    with tempfile.TemporaryDirectory() as td:
        db=make_db(Path(td)/'a.db',risk='L3',flow='L3')
        add_checkpoint(db,'TASK-V514','tp-requirement-analysis','requirement')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture')
        add_review(db,'TASK-V514','PASS')
        add_decision(db,'TASK-V514','workflow:material-confirmed:architecture->development')
        add_checkpoint(db,'TASK-V514','tp-development-engineering','development')
        add_review(db,'TASK-V514','REVISE')
        add_checkpoint(db,'TASK-V514','tp-architecture-design','architecture','revision done')
        add_review(db,'TASK-V514','PASS')
        r=orchestration.resolve_route('TASK-V514',db_path=db)
        assert r['next_stage']=='development'
        assert r['confirmation_required'] is True
