from pathlib import Path
import yaml
from cli import orchestration
from cli.version import active_version

BASE=Path(__file__).resolve().parents[2]

def test_contract_and_catalog_are_valid():
    assert active_version()=='5.2.2'
    assert orchestration.validate_contract(BASE)==[]

def test_contract_preserves_record_first_boundaries():
    c=orchestration.load_contract(BASE)
    assert c['entry_role']=='tp-workflow-orchestrator'
    assert c['runtime']['new_public_states'] is False
    assert c['runtime']['new_database_objects'] is False
    assert c['runtime']['ordinary_confirmation_persisted'] is True
    assert c['confirmation']['default_policy']=='material'
    assert c['confirmation']['user_preference_path']=='~/.tp-spec/preferences.yaml'
    assert c['execution']['lazy_load_role_skill'] is True
    assert c['execution']['concurrent_workflow_stages'] is False

def test_only_orchestrator_is_new_control_role_and_has_no_state():
    cat=orchestration.load_role_catalog(BASE)
    item=next(r for r in cat['roles'] if r['workflow_role']=='tp-workflow-orchestrator')
    assert item['type']=='control-role'
    assert item['owns_states']==[]
    assert 'tp-workflow-orchestrator' not in cat['state_owner_map'].values()

def test_ultra_implementation_stays_in_existing_roles():
    arch=(BASE/'skills/tp-architecture-design/SKILL.md').read_text(encoding='utf-8')
    verify=(BASE/'skills/tp-verification-engineering/SKILL.md').read_text(encoding='utf-8')
    orch=(BASE/'agents/tp-workflow-orchestrator/SKILL.md').read_text(encoding='utf-8')
    assert 'Deep Planning Capability' in arch and 'UltraPlan' in arch
    assert 'Deep Review Capability' in verify and 'UltraReview' in verify
    assert '只决定**何时进入深度模式**' in orch
    c=orchestration.load_contract(BASE)
    for pipeline in c['pipelines'].values():
        for step in pipeline:
            if step['mode']=='AUTO_PLANNING': assert step['role']=='tp-architecture-design'
            if step['mode']=='AUTO_REVIEW': assert step['role']=='tp-verification-engineering'

def test_planning_parallel_fallback_is_isolated_and_nonblocking():
    p=yaml.safe_load((BASE/'governance/planning-strategy.yaml').read_text(encoding='utf-8'))
    ex=p['modes']['COMPARATIVE']['execution']
    assert 'parallel isolated' in ex['preferred']
    assert 'isolated sequential' in ex['fallback']
    assert ex['fallback_must_not_block'] is True
