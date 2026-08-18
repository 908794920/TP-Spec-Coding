from pathlib import Path
import yaml

BASE = Path(__file__).resolve().parents[2]


def load(rel):
    return yaml.safe_load((BASE / rel).read_text(encoding='utf-8'))


def test_orchestration_uses_software_lifecycle_and_formal_roles_only():
    c = load('governance/orchestration.yaml')
    assert c['entry_role'] == 'tp-software-lifecycle'
    from cli.migrations.v5_2_3.role_map import ROLE_MAP
    old = set(ROLE_MAP)
    roles = {step['role'] for pipe in c['pipelines'].values() for step in pipe}
    assert not (roles & old)
    assert {'tp-product-manager','tp-software-architect','tp-development-engineer','tp-test-engineer'} <= roles


def test_workflow_keeps_five_states_and_adds_planning_review_without_dropping_discovery():
    wf = load('governance/workflow.yaml')
    assert set(wf['states']) == {'NEW','ACTIVE','BLOCKED','COMPLETED','CANCELLED'}
    phases = set(wf['rules']['phases']['values'])
    assert {'intake','requirement','product','discovery','architecture','planning','development','verification','review','delivery','other'} <= phases
    assert 'phase is a query/audit fact' in wf['rules']['phases']['semantics']


def test_orchestration_preserves_mode_effects_and_conditional_roles():
    c = load('governance/orchestration.yaml')
    steps = [s for p in c['pipelines'].values() for s in p]
    assert any(s['mode'] == 'AUTO_PLANNING' and s['role'] == 'tp-software-architect' for s in steps)
    assert any(s['mode'] == 'AUTO_REVIEW' and s['role'] == 'tp-code-reviewer' for s in steps)
    assert any('repo_mutation' in s.get('effects', []) and s['role'] == 'tp-development-engineer' for s in steps)
    conditional = {r['role']: r for r in c['conditional_roles']}
    assert conditional['tp-database-engineer']['trigger'] == 'database_risk'
    assert conditional['tp-security-engineer']['trigger'] == 'security_risk'


def test_ai_role_describes_formal_team_not_action_roles():
    ai = load('governance/ai-role.yaml')
    assert ai['collaboration']['default_entry'] == 'tp-spec-coding'
    ids = set(ai['agents'])
    assert 'tp-software-lifecycle' in ids
    assert 'tp-product-manager' in ids
    assert 'tp-software-architect' in ids
    assert 'tp-tech-lead' in ids
    assert 'tp-code-reviewer' in ids
    assert 'tp-workflow-orchestrator' not in ids


def test_risk_rule_has_role_trigger_policy():
    rr = load('governance/risk-rule.yaml')
    triggers = rr['role_triggers']
    assert 'tp-security-engineer' in triggers
    assert 'tp-database-engineer' in triggers
    assert 'tp-code-reviewer' in triggers
