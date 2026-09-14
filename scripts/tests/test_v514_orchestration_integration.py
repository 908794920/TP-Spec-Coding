import json,tempfile
from pathlib import Path
from cli import db as dbmod
from cli import orchestration
from scripts.tests.runtime_testutil import run
from scripts.tests.v514_orchestration_testutil import make_db,add_checkpoint,add_decision,add_review,add_code_review,add_verify,add_workflow_confirmation,make_bound_runtime,add_bound_code_review

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

def test_l3_pass_requires_structured_delivery_result_not_plain_checkpoint(tmp_path):
    from cli import record_first
    db, task_dir = make_bound_runtime(tmp_path, level="L3", with_review=False)
    route = orchestration.resolve_route("TASK-V514", db_path=db)
    assert route["next_stage"] == "review" and route["role_id"] == "tp-code-reviewer"
    add_bound_code_review(db, task_dir)
    route = orchestration.resolve_route("TASK-V514", db_path=db)
    assert route["next_stage"] == "delivery" and route["role_id"] == "tp-integration-engineer"
    record_first.checkpoint(task_id="TASK-V514", task_dir=str(task_dir), actor="tp-integration-engineer",
                            phase="delivery", summary="plain checkpoint, not delivery acceptance", db=db)
    route = orchestration.resolve_route("TASK-V514", db_path=db)
    assert route["next_stage"] == "delivery" and route["recommended_action"] == "dispatch_role"

# B04: use the normal production CLI, not the parser-caching test helper.
import shutil
import pytest
import yaml
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args

_BASE = Path(__file__).resolve().parents[2]


def _b04_route(db, task='TASK-V514', *extra):
    rc, out, err = run_cli(['workflow', 'next', '--task', task, '--db', str(db), '--json', *extra])
    assert rc == 0, (out, err)
    return json.loads(out)


def _b04_base(tmp_path, edit):
    root = tmp_path / 'base-policy'
    root.mkdir()
    shutil.copy2(_BASE / 'VERSION', root / 'VERSION')
    shutil.copytree(_BASE / 'governance', root / 'governance')
    path = root / 'governance/orchestration.yaml'
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    edit(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return root


def _b04_config(db, key, value, *, scope='project', project='demo'):
    return run_cli(['config', 'set', '--key', key, '--value', value,
                    '--scope', scope, '--scope-id', project, '--db', str(db)])


@pytest.mark.parametrize('level', ['L1', 'L2', 'L3'])
def test_b04_resolved_requirement_does_not_manufacture_design_and_planning(tmp_path, level):
    db = make_db(tmp_path / 'runtime.db', risk=level, flow=level)
    add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
    route = _b04_route(db)
    assert route['next_stage'] == 'development', route
    assert route['confirmation_required'] is False
    assert route['effective_level'] == level


@pytest.mark.parametrize('level', ['L2', 'L3'])
def test_b04_local_rework_without_historic_stage_records_advances_to_verification(tmp_path, level):
    db = make_db(tmp_path / 'runtime.db', risk=level, flow=level)
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
    route = _b04_route(db)
    assert route['next_stage'] == 'verification', route
    add_verify(db, 'TASK-V514', 'NEEDS_FIX')
    assert _b04_route(db)['next_stage'] == 'development'
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development', 'one feedback batch fixed')
    assert _b04_route(db)['next_stage'] == 'verification'
    assert route['effective_level'] == level


def test_b04_optional_note_does_not_invalidate_completed_product_work(tmp_path):
    db = make_db(tmp_path / 'runtime.db', risk='L2', flow='L2')
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
    add_verify(db, 'TASK-V514')
    add_checkpoint(db, 'TASK-V514', 'tp-tech-lead', 'planning', 'reference note, not a new Finding')
    route = _b04_route(db)
    assert route['next_stage'] == 'review', route


def test_b04_permission_risk_recommends_specialist_even_when_level_already_l3(tmp_path):
    db = make_db(tmp_path / 'db/runtime.db', risk='L3', flow='L3')
    tdir = tmp_path / '.tp-spec/tasks/TASK-V514'
    tdir.mkdir(parents=True)
    (tdir / 'task.md').write_text('本轮修改权限规则，只有一行变更。\n', encoding='utf-8')
    add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
    route = _b04_route(db)
    assert route['next_stage'] == 'architecture', route
    assert route['effective_level'] == 'L3'
    assert 'tp-security-engineer' in {r['role_id'] for r in route['recommended_roles']}


def test_b04_project_optional_stage_override_is_effective_and_queryable(tmp_path):
    db = make_db(tmp_path / 'runtime.db', risk='L2', flow='L2')
    add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
    key = 'orchestration.pipelines.L2.planning.required'
    assert _b04_config(db, key, 'true')[0] == 0
    route = _b04_route(db)
    assert route['next_stage'] == 'planning', route
    rc, out, err = run_cli(['config', 'get', '--key', 'orchestration', '--effective',
                           '--scope-id', 'demo', '--db', db])
    assert rc == 0, (out, err)
    effective = json.loads(out)
    assert effective['sources']['pipelines.L2.planning.required'] == 'config:project/demo'
    assert next(s for s in effective['data']['pipelines']['L2'] if s['stage'] == 'planning')['required'] is True
    assert route['policy_sources']['pipelines.L2.planning.required'] == 'config:project/demo'
    assert _b04_config(db, key, 'false')[0] == 0
    assert _b04_route(db)['next_stage'] == 'development'
    # Exact project scope: another project's override cannot leak into demo.
    with dbmod.connect(db) as conn:
        conn.execute("INSERT INTO config(key,scope,scope_id,value_json,updated_at) VALUES(?,?,?,?,?)",
                     (key, 'project', 'other-project', 'true', dbmod.now_iso()))
    assert _b04_route(db)['next_stage'] == 'development'


@pytest.mark.parametrize(('key', 'value', 'scope'), [
    ('orchestration.pipelines.L2.review.required', 'false', 'project'),
    ('orchestration.pipelines.L2.development.effects', '[]', 'project'),
    ('orchestration.pipelines.L2.review.role', 'tp-development-engineer', 'project'),
    ('orchestration.runtime.new_public_states', 'true', 'project'),
    ('orchestration.pipelines.L2.planning.required', '"false"', 'project'),
    ('orchestration.pipelines.L2.planning.required', 'false', 'task'),
    ('orchestration.auto_refresh_card', 'true', 'project'),
    ('orchestration.unknown_key', 'true', 'project'),
])
def test_b04_invalid_or_unsafe_override_is_rejected_without_writing(tmp_path, key, value, scope):
    db = make_db(tmp_path / 'runtime.db', risk='L2', flow='L2')
    with dbmod.connect_readonly(db) as conn:
        before = conn.execute('SELECT COUNT(*) FROM config').fetchone()[0]
    rc, out, err = _b04_config(db, key, value, scope=scope)
    assert rc != 0 and 'ORCHESTRATION_POLICY_INVALID' in err, (out, err)
    with dbmod.connect_readonly(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM config').fetchone()[0] == before


def test_b04_legacy_invalid_override_fails_readonly_route_not_silently_ignored(tmp_path):
    db = make_db(tmp_path / 'runtime.db')
    with dbmod.connect(db) as conn:
        conn.execute("INSERT INTO config(key,scope,scope_id,value_json,updated_at) VALUES(?,?,?,?,?)",
                     ('orchestration.pipelines.L1.architecture.required', 'project', 'demo', '"false"', dbmod.now_iso()))
    before = Path(db).read_bytes()
    rc, out, err = run_cli(['workflow', 'next', '--task', 'TASK-V514', '--db', db, '--json'])
    assert rc != 0 and 'ORCHESTRATION_POLICY_INVALID' in err, (out, err)
    assert Path(db).read_bytes() == before


def test_b04_base_policy_validated_on_production_route(tmp_path):
    db = make_db(tmp_path / 'runtime.db')
    def corrupt(data):
        data['pipelines']['L1'][0]['required'] = 'false'
    root = _b04_base(tmp_path, corrupt)
    rc, out, err = run_cli(['workflow', 'next', '--task', 'TASK-V514', '--db', db,
                           '--base-root', str(root), '--json'])
    assert rc != 0 and 'ORCHESTRATION_POLICY_INVALID' in err, (out, err)


def test_b04_configured_signal_prefix_is_consumed_by_route(tmp_path):
    db = make_db(tmp_path / 'runtime.db', risk='L2', flow='L2')
    add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
    def edit(data):
        data['signals']['include_stage_prefix'] = 'project:request:'
    root = _b04_base(tmp_path, edit)
    add_decision(db, 'TASK-V514', 'project:request:planning')
    route = _b04_route(db, 'TASK-V514', '--base-root', str(root))
    assert route['next_stage'] == 'planning', route


def test_b04_delivery_budget_is_read_from_effective_policy_not_literal_five(tmp_path):
    db, _ = make_bound_runtime(tmp_path)
    key = 'orchestration.execution.delivery_fast_path.max_incremental_ai_overhead_percent'
    assert _b04_config(db, key, '3')[0] == 0
    route = _b04_route(db)
    assert route['next_stage'] == 'delivery', route
    assert route['context']['max_incremental_ai_overhead_percent'] == 3


def test_b04_skip_signal_cannot_remove_required_independent_review(tmp_path):
    db = make_db(tmp_path / 'runtime.db', risk='L2', flow='L2')
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
    add_verify(db, 'TASK-V514')
    add_decision(db, 'TASK-V514', 'workflow:skip-stage:review')
    rc, out, err = run_cli(['workflow', 'next', '--task', 'TASK-V514', '--db', db, '--json'])
    assert rc != 0 and 'PROTECTED_STAGE' in err, (out, err)


def test_b04_real_diff_returns_bounded_validation_advice_not_full_test_authority(tmp_path, monkeypatch):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    (project / 'shared.css').write_text('.panel { padding: 4px; }\n', encoding='utf-8')
    (tdir / 'acceptance.md').write_text(
        '| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |\n'
        '| AC-01 | 相关页面间距 | task.md | L0 | browser interaction | | human | PENDING |\n', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
                                    '--phase', 'development', '--summary', 'one related feedback batch'))
    assert rc == 0, (out, err)
    with dbmod.connect_readonly(str(db)) as conn:
        count = conn.execute('SELECT COUNT(*) FROM task_event').fetchone()[0]
    route = _b04_route(db, tid)
    assert route['next_stage'] == 'verification', route
    guidance = route['context']['validation']
    assert guidance['scope'] == 'affected'
    assert guidance['coverage_complete'] is False
    assert guidance['authorization_granted'] is False
    assert any(row['path'] == 'shared.css' for row in guidance['changed_files'])
    assert guidance['acceptance_candidates'][0]['id'] == 'AC-01'
    assert guidance['acceptance_candidates'][0]['witness'] == 'human'
    assert guidance['usage_mapping'] == 'requires_actual_callers'
    assert 'testing-strategy' in route['recommended_skills']
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM task_event').fetchone()[0] == count
    assert not list(project.glob('.tp-spec/card/*.html'))


@pytest.mark.parametrize(('path', 'value'), [
    (('runtime', 'new_public_states'), True),
    (('execution', 'auto_refresh_card'), True),
    (('execution', 'delivery_fast_path'), []),
    (('execution', 'prefer_parallel_isolated_subagents'), False),
    (('pipelines', 'L1', 0, 'stage'), ['requirement']),
])
def test_b04_malformed_nested_policy_reports_source_not_ignored_or_traceback(tmp_path, path, value):
    db = make_db(tmp_path / 'runtime.db')
    def edit(data):
        node = data
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
    root = _b04_base(tmp_path, edit)
    rc, out, err = run_cli(['workflow', 'next', '--task', 'TASK-V514', '--db', db,
                           '--base-root', str(root), '--json'])
    assert rc == 4 and 'ORCHESTRATION_POLICY_INVALID' in err, (out, err)
    assert str(path[0]) in err and 'Traceback' not in err


@pytest.mark.parametrize('decision', ['NEEDS_FIX', 'FAIL'])
def test_b04_verification_rework_cannot_dispatch_mutation_with_empty_envelope(tmp_path, decision):
    db = make_db(tmp_path / 'runtime.db', risk='L1', flow='L1')
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
    add_verify(db, 'TASK-V514', decision)
    route = orchestration.resolve_route('TASK-V514', db_path=db, allowed_effects=[])
    assert route['recommended_action'] == 'await_effect_approval', route
    assert route['role_id'] is None and route['required_effects'] == ['repo_mutation']
    resumed = orchestration.resolve_route('TASK-V514', db_path=db, allowed_effects=['repo_mutation'])
    assert resumed['recommended_action'] == 'dispatch_role' and resumed['next_stage'] == 'development'


def test_b04_real_upstream_failure_does_not_reuse_pre_failure_development(tmp_path):
    db = make_db(tmp_path / 'runtime.db', risk='L3', flow='L3')
    add_checkpoint(db, 'TASK-V514', 'tp-product-manager', 'requirement')
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
    add_verify(db, 'TASK-V514', 'FAIL')
    assert _b04_route(db)['next_stage'] == 'architecture'
    add_checkpoint(db, 'TASK-V514', 'tp-software-architect', 'architecture', 'failure assessed: revise implementation')
    route = _b04_route(db)
    assert route['next_stage'] in {'planning', 'development'}, route
    assert route['next_stage'] != 'requirement'


def test_b04_existing_bad_policy_can_be_repaired_by_validated_config_write(tmp_path):
    db = make_db(tmp_path / 'runtime.db', risk='L2', flow='L2')
    key = 'orchestration.pipelines.L2.planning.required'
    with dbmod.connect(db) as conn:
        conn.execute('INSERT INTO config(key,scope,scope_id,value_json,updated_at) VALUES(?,?,?,?,?)',
                     (key, 'project', 'demo', '"false"', dbmod.now_iso()))
    assert _b04_config(db, key, 'false')[0] == 0
    add_checkpoint(db, 'TASK-V514', 'tp-development-engineer', 'development')
    route = _b04_route(db)
    progress = orchestration.resolve_progress('TASK-V514', db_path=db)
    assert route['next_stage'] == 'verification'
    assert [s['stage'] for s in progress['steps']] == route['included_stages']


def test_b04_no_new_work_does_not_manufacture_another_development_batch(tmp_path):
    # The no-new-work state has current evidence, not an unbound legacy PASS.
    db, _ = make_bound_runtime(tmp_path, level="L0", with_review=False)
    before = Path(db).read_bytes()
    first, second = _b04_route(db), _b04_route(db)
    assert first['recommended_action'] == second['recommended_action'] == 'task_complete'
    assert first['next_stage'] == second['next_stage'] == 'complete'
    assert Path(db).read_bytes() == before


@pytest.mark.parametrize("level", ["L0", "L1", "L2", "L3"])
def test_b17_unscoped_legacy_subject_waits_without_crash_or_completion(tmp_path, level):
    # Legacy fixture intentionally has an ID but no captured repository scope.
    # Missing machine evidence must not become a crash or a whole-task PASS.
    db = make_db(tmp_path / "legacy.db", risk=level, flow=level)
    add_checkpoint(db, "TASK-V514", "tp-development-engineer", "development")
    if level != "L0":
        add_verify(db, "TASK-V514")
    if level in {"L2", "L3"}:
        add_code_review(db, "TASK-V514")
    before = Path(db).read_bytes()
    route = _b04_route(db)
    assert route["recommended_action"] == "none", route
    assert route["next_stage"] == "verification", route
    assert route["reason_codes"] == ["FULL_SCOPE_CHECKPOINT_REQUIRED"], route
    assert route["context"]["waiting"]["condition"]
    assert route["role_id"] is None  # Missing bookkeeping is not product rework.
    orchestration.resolve_progress("TASK-V514", db_path=db)
    assert Path(db).read_bytes() == before
