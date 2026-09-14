from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from cli import config_loader, db as dbmod
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args


def test_normal_lifecycle_never_calls_or_rewrites_card_chain(tmp_path, monkeypatch):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    card = project / ".tp-spec/card/index.html"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("previous explicit user card", encoding="utf-8")
    before = (card.read_bytes(), card.stat().st_mtime_ns)
    calls = []

    def observe(frame, event, arg):
        name = frame.f_code.co_name
        file = frame.f_code.co_filename.replace("\\", "/")
        if event == "call" and "/cli/cards/" in file and (
            name.startswith("build_") or name.startswith("render_") or name == "refresh_after_success"
        ):
            calls.append((file, name))

    commands = [
        ["work", "start", "--task", tid, "--role", "tp-development-engineer", "--db", str(db)],
        ["work", "end", "--task", tid, "--role", "tp-development-engineer", "--reason", "completed", "--db", str(db)],
        task_args(db, tdir, tid, "checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", "implemented"),
        task_args(db, tdir, tid, "verify", "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "checked", "--evidence", "evidence/check.txt"),
        task_args(db, tdir, tid, "block", "--actor", "tp-test-engineer", "--reason", "owner review"),
        task_args(db, tdir, tid, "resume", "--actor", "tp-test-engineer", "--summary", "owner review resolved"),
        task_args(db, tdir, tid, "complete", "--actor", "tp-test-engineer", "--summary", "fixture complete"),
    ]
    old_profile = sys.getprofile()
    try:
        sys.setprofile(observe)
        for command in commands:
            rc, out, err = run_cli(command)
            assert rc == 0, (command, out, err)
            if command[0] == "task":
                json.loads(out)
            assert "CARD_DISPLAY" not in out + err
            assert "INLINE_VISUALIZATION" not in out + err
    finally:
        sys.setprofile(old_profile)
    assert calls == []
    assert (card.read_bytes(), card.stat().st_mtime_ns) == before


def test_production_cli_records_queryable_phases_and_event_correlation(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(db, tdir, tid, "checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", "measured"))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(["report", "timings", "--task", tid, "--json"])
    assert rc == 0, (out, err)
    records = json.loads(out)["records"]
    row = next(r for r in records if r["command"] == "task checkpoint")
    assert row["exit_code"] == 0
    assert row["total_ms"] > 0
    for segment in ("parse", "changeset", "lock_wait", "db_write", "db_commit", "projection"):
        assert row["segments"][segment]["calls"] > 0, (segment, row)
        assert row["segments"][segment]["elapsed_ms"] >= 0
    assert row["segments"]["card"]["status"] == "not_entered"
    with dbmod.connect_readonly(str(db)) as conn:
        detail = json.loads(conn.execute("SELECT detail_json FROM task_event WHERE task_id=? AND event_type='FACT' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()[0])
    assert detail["cli_invocation_id"] == row["invocation_id"]


def test_parse_failure_is_measured_without_recording_sensitive_argv(tmp_path, monkeypatch):
    rc, _, _ = run_cli(["task", "checkpoint", "--unknown-secret", "do-not-persist-me"])
    assert rc != 0
    rc, out, err = run_cli(["report", "timings", "--json"])
    assert rc == 0, (out, err)
    records = json.loads(out)["records"]
    assert any(r["exit_code"] == 2 and r["segments"]["parse"]["status"] == "failed" for r in records)
    assert "do-not-persist-me" not in out


def test_config_cache_cannot_trust_unchanged_mtime_or_mutable_return_values(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("decision: A\n", encoding="utf-8")
    old_stat = path.stat()
    first = config_loader.load_config(path)
    first["decision"] = "caller mutation"
    assert config_loader.load_config(path)["decision"] == "A"
    path.write_text("decision: B\n", encoding="utf-8")
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert config_loader.load_config(path)["decision"] == "B"


def test_invocation_cache_reuses_parse_but_detects_same_mtime_and_mutation(tmp_path):
    from cli import command_context
    path = tmp_path / "config.yaml"
    path.write_text("decision: A\n", encoding="utf-8")
    stat = path.stat()
    with command_context.command() as context:
        first = config_loader.load_config(path)
        first["decision"] = "mutated"
        assert config_loader.load_config(path)["decision"] == "A"
        assert context.counters["config_parses"] == 1
        assert context.counters["config_cache_hits"] == 1
        path.write_text("decision: B\n", encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert config_loader.load_config(path)["decision"] == "B"
        assert context.counters["config_parses"] == 2
    assert command_context.current() is None


def test_fresh_process_uses_production_parser_and_persists_timing(tmp_path):
    import subprocess
    root = Path(__file__).resolve().parents[2]
    process = subprocess.run([sys.executable, "-m", "cli.main", "--help"], cwd=root, capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    rc, out, err = run_cli(["report", "timings", "--json"])
    assert rc == 0, (out, err)
    row = next(r for r in json.loads(out)["records"] if r["command"] == "unparsed")
    assert row["exit_code"] == 0
    assert row["segments"]["parse"]["calls"] == 1
    assert row["segments"]["parse"]["status"] == "completed"
    assert row["segments"]["card"]["status"] == "not_entered"


def test_diagnostic_directory_failure_does_not_rollback_checkpoint(tmp_path, monkeypatch):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    user = Path(os.environ["TP_SPEC_USER_ROOT"])
    # Real filesystem failure; do not replace the timing or command functions.
    blocked = tmp_path / "blocked-user-root"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("TP_SPEC_USER_ROOT", str(blocked))
    rc, out, err = run_cli(task_args(db, tdir, tid, "checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", "committed despite diagnostics failure"))
    assert rc == 0, (out, err)
    assert "DIAGNOSTIC_WRITE_WARNING" in err
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_event WHERE task_id=? AND summary=?", (tid, "committed despite diagnostics failure")).fetchone()[0] >= 1


def test_work_sessions_measure_actual_transaction_body_without_claiming_begin_wait(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(['work', 'start', '--task', tid, '--role', 'tp-development-engineer', '--db', str(db)])
    assert rc == 0, (out, err)
    rc, out, err = run_cli(['report', 'timings', '--task', tid, '--json'])
    row = next(row for row in json.loads(out)['records'] if row['command'] == 'work start')
    assert row['segments']['db_write']['calls'] > 0
    assert row['segments']['db_commit']['calls'] > 0
    assert row['segments']['lock_wait']['status'] == 'not_entered'
    assert row['counters']['deferred_transactions'] > 0


def test_event_contract_caller_mutation_cannot_disable_next_call_decisions():
    from cli import event_contract
    first = event_contract.load_event_semantics_contract()
    saved = list(first['controlled']['decision'])
    first['controlled']['decision'][:] = []
    assert event_contract.load_event_semantics_contract()['controlled']['decision'] == saved


def test_workflow_config_has_no_process_stale_or_caller_owned_cache(tmp_path):
    import shutil
    from cli import workflow_loader, command_context
    base = Path(__file__).resolve().parents[2]
    (tmp_path / 'governance').mkdir()
    path = tmp_path / 'governance/workflow.yaml'
    shutil.copy2(base / 'governance/workflow.yaml', path)
    with command_context.command():
        first = workflow_loader.load_workflow(tmp_path)
        expected = dict(first.states)
        first.states.clear()
        assert workflow_loader.load_workflow(tmp_path).states == expected
    stat = path.stat()
    text = path.read_text(encoding='utf-8')
    assert '5.3.3' in text
    path.write_text(text.replace('5.3.3','5.3.3'), encoding='utf-8')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert workflow_loader.load_workflow(tmp_path).version == '5.3.3'


def test_malformed_timing_receipt_is_reported_not_rendered_as_success(tmp_path):
    from cli import command_context
    root = command_context._root()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'malformed.json').write_text(json.dumps({'schema': 'tp-spec.cli-timing/v1'}), encoding='utf-8')
    rc, out, err = run_cli(['report', 'timings'])
    assert rc == 0, (out, err)
    assert 'DIAGNOSTIC_CORRUPT: 1' in err


# B05: canonical current prose is a read-only, source-bound context slice, not
# a grant of authority or a second decision ledger.
_CURRENT_START = '<!-- tp-spec:current:start -->'
_CURRENT_END = '<!-- tp-spec:current:end -->'


def _b05_document(tid, body, history='', *, artifact='task'):
    return (f'---\nartifact: {artifact}\ntask_id: "{tid}"\n'
            'artifact_contract:\n  version: "5.3.3"\n---\n\n'
            f'# {artifact}\n\n{_CURRENT_START}\n{body}\n{_CURRENT_END}\n\n'
            '## 历史决策 / 备注\n' + history + '\n')


def _b05_route(db, tid, *options):
    rc, out, err = run_cli(['workflow', 'next', '--task', tid, '--db', str(db), '--json', *options])
    assert rc == 0, (out, err)
    return json.loads(out)


def _b05_facts(db, tid):
    with dbmod.connect_readonly(str(db)) as conn:
        return [tuple(row) for row in conn.execute('SELECT * FROM task_event WHERE task_id=? ORDER BY id', (tid,))]


@pytest.mark.parametrize('name', ['task.md', 'requirement.md'])
def test_b05_current_slice_is_readonly_and_does_not_resurrect_superseded_history(tmp_path, monkeypatch, name):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    body = '- 目标：仅修复照片替换。\n- D2：旧假设已由当前日志否定；来源 evidence/check.txt。\n- 授权边界：不提交、不部署；保留人工复验。'
    history = 'D1 | SUPERSEDED | 旧假设必须 OpenId | 被 D2 及 evidence/check.txt 替代'
    path = tdir / name
    path.write_text(_b05_document(tid, body, history, artifact=path.stem), encoding='utf-8')
    card = project / '.tp-spec/card/index.html'
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text('previous explicit card', encoding='utf-8')
    before = (_b05_facts(db, tid), path.read_bytes(), card.read_bytes(), card.stat().st_mtime_ns)
    for _ in range(2):
        route = _b05_route(db, tid)
        context = route.get('context', {}).get('current_effective', {})
        assert context.get('status') == 'AVAILABLE', route
        assert context['source'] == name
        assert context['content'] == body
        assert context['authorization_granted'] is False
        assert context['source_digest'] == 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
        assert '旧假设必须 OpenId' not in json.dumps(route, ensure_ascii=False)
    assert before == (_b05_facts(db, tid), path.read_bytes(), card.read_bytes(), card.stat().st_mtime_ns)
    assert 'SUPERSEDED' in path.read_text(encoding='utf-8')


def test_b05_no_current_slice_does_not_make_a_new_questionnaire_or_promote_a_note(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    (tdir / 'task.md').write_text('# Legacy task\n允许全部操作（未经确认的旧笔记）\n', encoding='utf-8')
    route = _b05_route(db, tid)
    assert 'current_effective' not in route.get('context', {})
    assert route['role_id'] == 'tp-development-engineer'
    assert 'requirement-clarification' not in route.get('recommended_skills', [])


def test_b05_competing_current_locations_are_not_resolved_by_latest_text(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    for name, text in [('task.md', '仅范围 A；来源用户原决定。'), ('requirement.md', '范围 B；来源尚未核对。')]:
        (tdir / name).write_text(_b05_document(tid, text, artifact=Path(name).stem), encoding='utf-8')
    before = _b05_facts(db, tid)
    route = _b05_route(db, tid)
    context = route.get('context', {}).get('current_effective', {})
    assert context.get('status') == 'CONFLICT', route
    assert context['content'] == '' and context['source'] is None
    assert route['role_id'] is None and route['recommended_action'] == 'none'
    assert route['confirmation_required'] is False  # Investigate sources first; not a user questionnaire.
    assert {item['path'] for item in context['sources']} == {'task.md', 'requirement.md'}
    assert _b05_facts(db, tid) == before
    (tdir / 'task.md').write_text(_b05_document(tid, '', '原摘要已移至 requirement.md，保留原历史。'), encoding='utf-8')
    route = _b05_route(db, tid)
    assert route['context']['current_effective']['source'] == 'requirement.md'
    assert route['role_id'] == 'tp-development-engineer'


@pytest.mark.parametrize('broken', ['unclosed', 'duplicate', 'reversed', 'identity', 'oversized', 'encoding'])
def test_b05_invalid_current_region_does_not_fall_back_to_old_or_partial_scope(tmp_path, monkeypatch, broken):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    good = _b05_document(tid, '新范围；来源用户决定。')
    raw = {
        'unclosed': good.replace(_CURRENT_END, ''),
        'duplicate': good + '\n' + _CURRENT_START + '\n第二范围\n' + _CURRENT_END,
        'reversed': good.replace(_CURRENT_START, 'TEMP').replace(_CURRENT_END, _CURRENT_START).replace('TEMP', _CURRENT_END),
        'identity': good.replace(tid, 'TASK-OTHER'),
        'oversized': _b05_document(tid, '不得省略限制。' * 2500),
        'encoding': good,
    }[broken].encode('utf-8')
    if broken == 'encoding':
        raw += b'\xff'
    (tdir / 'task.md').write_bytes(raw)
    # No old requirement fallback when the competing Task document cannot be read.
    (tdir / 'requirement.md').write_text(_b05_document(tid, '旧范围；没有依据说明已获准。', artifact='requirement'), encoding='utf-8')
    route = _b05_route(db, tid)
    context = route.get('context', {}).get('current_effective', {})
    assert context.get('status') in {'INVALID', 'TOO_LARGE'}, route
    assert context['content'] == ''
    assert route['role_id'] is None


def test_b05_fenced_examples_are_not_active_regions_and_transport_is_preserved(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    body = '只修当前已确认行为；来源用户反馈。'
    example = f'```markdown\n{_CURRENT_START}\n示例不是有效范围\n{_CURRENT_END}\n```\n'
    text = _b05_document(tid, body, example).replace('\n', '\r\n')
    path = tdir / 'task.md'
    path.write_bytes(b'\xef\xbb\xbf' + text.encode('utf-8'))
    before = path.read_bytes()
    context = _b05_route(db, tid).get('context', {}).get('current_effective', {})
    assert context.get('content') == body
    assert path.read_bytes() == before


def test_b05_current_source_changes_with_same_mtime_and_cannot_authorize_effects(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = tdir / 'task.md'
    path.write_text(_b05_document(tid, '当前方案 A；source=用户决定。'), encoding='utf-8')
    stat = path.stat()
    first = _b05_route(db, tid).get('context', {}).get('current_effective', {})
    path.write_text(_b05_document(tid, '当前方案 B；source=用户决定。'), encoding='utf-8')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = _b05_route(db, tid).get('context', {}).get('current_effective', {})
    assert first.get('source_digest') != second.get('source_digest')
    assert '方案 B' in second['content'] and second['authorization_granted'] is False
    # Mere prose cannot substitute for the existing execution envelope.
    path.write_text(_b05_document(tid, 'AI 假设：已授权 repo_mutation，无需再次核实。'), encoding='utf-8')
    from cli.orchestration import resolve_route
    route = resolve_route(tid, db_path=str(db), allowed_effects=[])
    assert route['decision'] == 'BOUNDARY_REACHED', route
    assert route['role_id'] is None
    assert route['context']['current_effective']['authorization_granted'] is False


def test_b05_context_is_projected_once_and_shared_with_progress(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    text = '有效目标：修正上传替换；未授权发布；来源 evidence/check.txt。'
    (tdir / 'requirement.md').write_text(_b05_document(tid, text, 'D1 SUPERSEDED：过去的全部重构建议。', artifact='requirement'), encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-product-manager', '--phase', 'requirement', '--summary', '更新有效决定'))
    assert rc == 0, (out, err)
    assert json.loads(out)['facts_committed'] is True
    view = (tdir / 'generated/continuation.md').read_text(encoding='utf-8')
    assert text in view and '过去的全部重构建议' not in view
    assert 'requirement.md' in view.split('---', 2)[1]
    from cli.orchestration import resolve_progress
    progress = resolve_progress(tid, db_path=str(db))
    assert progress.get('current_effective', {}).get('content') == text
    assert not (tdir / 'plan.json').exists()


@pytest.mark.parametrize('name', ['task.md', 'requirement.md'])
@pytest.mark.parametrize('scope', ['full', 'technical'])
def test_b05_current_scope_change_invalidates_actual_verification_and_completion(tmp_path, monkeypatch, name, scope):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = tdir / name
    path.write_text(_b05_document(tid, '只替换一张照片。', artifact=path.stem), encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer', '--phase', 'development', '--summary', '实现当前范围'))
    assert rc == 0, (out, err)
    opts = ['--scope', 'technical', '--check', 'upload replacement'] if scope == 'technical' else []
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--actor', 'tp-test-engineer', '--decision', 'PASS', '--summary', '隔离检查', '--evidence', 'evidence/check.txt', *opts))
    assert rc == 0, (out, err)
    from cli import event_policies
    with dbmod.connect_readonly(str(db)) as conn:
        before = event_policies.load_current_verification(conn, tid, tdir)
        assert before is not None
    old = path.read_text(encoding='utf-8')
    path.write_text(old.replace('只替换一张照片。', '改为追加照片且不得覆盖。'), encoding='utf-8')
    with dbmod.connect_readonly(str(db)) as conn:
        assert event_policies.load_current_verification(conn, tid, tdir) is None
        # Historical PASS remains auditable with its original subject.
        unchanged = conn.execute('SELECT detail_json FROM task_event WHERE id=?', (before.row['id'],)).fetchone()[0]
        assert json.loads(unchanged)['subject_digest'] == before.detail['subject_digest']
    rc, out, err = run_cli(task_args(db, tdir, tid, 'complete', '--actor', 'tp-test-engineer', '--summary', '不应结单'))
    assert rc != 0, out


def test_b05_canonical_requirement_affects_architecture_and_projection_digest(tmp_path):
    from cli.digest import compute_architecture_subject_digest
    from cli.transaction_commit import _continuation_sources, _source_digest
    (tmp_path / 'task.md').write_text('existing task', encoding='utf-8')
    path = tmp_path / 'requirement.md'
    path.write_text('current requirement A', encoding='utf-8')
    architecture = compute_architecture_subject_digest(tmp_path)
    current = _source_digest(_continuation_sources(tmp_path, 'ACTIVE'), tmp_path)
    path.write_text('current requirement B', encoding='utf-8')
    assert architecture != compute_architecture_subject_digest(tmp_path)
    assert current != _source_digest(_continuation_sources(tmp_path, 'ACTIVE'), tmp_path)


def test_b05_current_region_source_is_not_followed_through_symlink(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    outside = tmp_path / 'outside.md'
    outside.write_text(_b05_document(tid, '不应泄露的外部声明'), encoding='utf-8')
    link = tdir / 'requirement.md'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation not permitted')
    route = _b05_route(db, tid)
    context = route.get('context', {}).get('current_effective', {})
    assert context.get('status') == 'INVALID'
    assert context['content'] == '' and '不应泄露的外部声明' not in json.dumps(context, ensure_ascii=False)


def test_b05_empty_scaffold_and_from_intake_keep_one_current_document(tmp_path, monkeypatch):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    assert 'current_effective' not in _b05_route(db, tid).get('context', {})
    source = tmp_path / 'intake'
    source.mkdir()
    original = _b05_document('', '获准范围：只修当前上传；依据原用户决定。', 'D1 SUPERSEDED 仅作历史。', artifact='requirement')
    (source / 'requirement.md').write_text(original, encoding='utf-8')
    adopted_id = 'TASK-B05-INTAKE'
    adopted = project / '.tp-spec/tasks' / adopted_id
    rc, out, err = run_cli(['task', 'create', '--id', adopted_id, '--project', 'v532-test', '--risk', 'L0', '--flow', 'L0',
                           '--db', str(db), '--from-intake', str(source), '--task-dir', str(adopted)])
    assert rc == 0, (out, err)
    context = _b05_route(db, adopted_id).get('context', {}).get('current_effective', {})
    assert context.get('source') == 'requirement.md'
    assert context['status'] == 'AVAILABLE'
    assert (source / 'requirement.md').read_text(encoding='utf-8') == original
    assert 'D1 SUPERSEDED' in (adopted / 'requirement.md').read_text(encoding='utf-8')
    assert not (adopted / 'requirement-decisions.md').exists()


def test_b05_current_view_stamps_consumed_source_not_a_concurrent_replacement(tmp_path, monkeypatch):
    from cli import current_context, transaction_commit
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = tdir / 'task.md'
    path.write_text(_b05_document(tid, '方案 A 来源已确认。'), encoding='utf-8')
    real_read = current_context.read_current

    def replace_after_read(*args, **kwargs):
        result = real_read(*args, **kwargs)
        path.write_text(_b05_document(tid, '方案 B 新变更待核对。'), encoding='utf-8')
        return result

    monkeypatch.setattr(current_context, 'read_current', replace_after_read)
    with dbmod.connect_readonly(str(db)) as conn:
        task = conn.execute('SELECT * FROM task WHERE task_id=?', (tid,)).fetchone()
        text = transaction_commit._rebuild_current_view_text(tdir, task, 'current test', 'B05-TEST')
    assert '方案 A' in text and '方案 B' not in text
    import yaml
    front = yaml.safe_load(text.split('---', 2)[1])
    live = transaction_commit._source_digest(transaction_commit._continuation_sources(tdir, 'NEW'), tdir)
    assert front['source_digest'] != 'sha256:' + live


def test_b05_context_conflict_does_not_rollback_a_committed_fact_or_override_wait(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    for name in ('task.md', 'requirement.md'):
        (tdir / name).write_text(_b05_document(tid, '待核对来源。', artifact=Path(name).stem), encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-product-manager', '--phase', 'requirement', '--summary', '已发现两个冲突记录'))
    assert rc == 0 and json.loads(out)['facts_committed'] is True, (out, err)
    view = (tdir / 'generated/continuation.md').read_text(encoding='utf-8')
    assert 'CONFLICT' in view and '继续完成业务工作即可' not in view
    rc, out, err = run_cli(task_args(db, tdir, tid, 'block', '--actor', 'tp-test-engineer', '--reason', '等待用户授权', '--kind', 'permission', '--condition', '收到真实操作授权'))
    assert rc == 0, (out, err)
    route = _b05_route(db, tid)
    assert route['current_state'] == 'BLOCKED'
    assert route['recommended_action'] == 'task_resume_after_resolution'
    assert route['context']['waiting']['kind'] == 'permission'
    assert route['context']['current_effective']['status'] == 'CONFLICT'


@pytest.mark.parametrize('scope', ['full', 'technical'])
def test_b05_canonical_transport_only_changes_do_not_stale_current_verification(tmp_path, monkeypatch, scope):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = tdir / 'requirement.md'
    doc = _b05_document(tid, '只修已确认问题。', artifact='requirement')
    path.write_text(doc, encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer', '--phase', 'development', '--summary', '实现'))
    assert rc == 0, (out, err)
    options = ['--scope', 'technical', '--check', 'current test'] if scope == 'technical' else []
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--actor', 'tp-test-engineer', '--decision', 'PASS', '--summary', '检查', '--evidence', 'evidence/check.txt', *options))
    assert rc == 0, (out, err)
    path.write_bytes(b'\xef\xbb\xbf' + doc.replace('\n', '\r\n').encode('utf-8'))
    from cli import event_policies
    with dbmod.connect_readonly(str(db)) as conn:
        assert event_policies.load_current_verification(conn, tid, tdir) is not None


@pytest.mark.parametrize('change', ['add', 'remove'])
def test_b05_view_source_set_race_keeps_fact_and_requires_rebuild(tmp_path, monkeypatch, change):
    from cli import transaction_commit
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    (tdir / 'task.md').write_text(_b05_document(tid, '当前范围以任务为准。'), encoding='utf-8')
    requirement = tdir / 'requirement.md'
    if change == 'remove':
        requirement.write_text('历史需求说明，当前范围留在 task.md。', encoding='utf-8')
    real_sources = transaction_commit._continuation_sources

    def mutate_source_set(*args, **kwargs):
        if change == 'remove':
            requirement.unlink(missing_ok=True)
        else:
            requirement.write_text(_b05_document(tid, '另一处待核对的范围。', artifact='requirement'), encoding='utf-8')
        return real_sources(*args, **kwargs)

    monkeypatch.setattr(transaction_commit, '_continuation_sources', mutate_source_set)
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-product-manager',
                                    '--phase', 'requirement', '--summary', '事实不因派生竞争回滚'))
    assert rc == 0 and json.loads(out)['facts_committed'] is True, (out, err)
    assert json.loads(out)['view_status'] == 'PENDING', (out, err)
    assert 'CURRENT_CONTEXT_SOURCES_CHANGED' in err
    with dbmod.connect_readonly(str(db)) as conn:
        before = conn.execute('SELECT COUNT(*) FROM task_event WHERE task_id=?', (tid,)).fetchone()[0]
    monkeypatch.setattr(transaction_commit, '_continuation_sources', real_sources)
    rc, out, err = run_cli(['projection', 'rebuild', '--view-only', '--task', tid,
                           '--task-dir', str(tdir), '--db', str(db)])
    assert rc == 0 and json.loads(out)['view_status'] == 'CURRENT', (out, err)
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM task_event WHERE task_id=?', (tid,)).fetchone()[0] == before


# B08: diagnostics and optional presentation must not become business dependencies.
@pytest.mark.parametrize('module', ['cli.cards.render', 'cli.cards.snapshot'])
def test_b08_optional_card_import_failure_cannot_block_normal_checkpoint(tmp_path, monkeypatch, module):
    import subprocess
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    root = Path(__file__).resolve().parents[2]
    card = project / '.tp-spec/card/index.html'
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text('last explicitly requested card', encoding='utf-8')
    before = (card.read_bytes(), card.stat().st_mtime_ns)
    # Fail the real import in a fresh interpreter; never replace a renderer with no-op.
    boot = (
        'import sys, importlib.abc\n'
        f'blocked = {module!r}\n'
        'class BrokenCard(importlib.abc.MetaPathFinder):\n'
        ' def find_spec(self, fullname, path=None, target=None):\n'
        '  if fullname == blocked: raise ImportError("injected optional card failure")\n'
        'sys.meta_path.insert(0, BrokenCard())\n'
        'from cli.main import main\n'
        'sys.exit(main(sys.argv[1:]))\n'
    )
    args = task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
                     '--phase', 'development', '--summary', 'card import must be optional')
    proc = subprocess.run([sys.executable, '-c', boot, *args], cwd=root,
                          capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout)['facts_committed'] is True
    assert (card.read_bytes(), card.stat().st_mtime_ns) == before
    rc, out, err = run_cli(['report', 'timings', '--task', tid, '--json'])
    assert rc == 0, (out, err)
    row = next(r for r in json.loads(out)['records'] if r['command'] == 'task checkpoint')
    assert row['segments']['card']['status'] == 'not_entered'
    # The same broken component is actually needed on explicit request and must fail visibly.
    proc = subprocess.run([sys.executable, '-c', boot, 'card', 'task', '--task', tid,
                           '--db', str(db), '--output', str(tmp_path / 'card.html')],
                          cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert proc.returncode != 0 and 'injected optional card failure' in proc.stderr
    assert not (tmp_path / 'card.html').exists()
    assert (card.read_bytes(), card.stat().st_mtime_ns) == before
    rc, out, err = run_cli(['report', 'timings', '--task', tid, '--json'])
    row = next(r for r in json.loads(out)['records'] if r['command'] == 'card task')
    assert row['exit_code'] != 0 and row['segments']['card']['status'] == 'failed'


@pytest.mark.parametrize('failure', ['receipt', 'warning'])
def test_b08_diagnostic_finalization_cannot_turn_committed_fact_into_exception(tmp_path, monkeypatch, failure):
    import contextlib
    import io
    from cli import command_context, main as climain
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    before = len(_b05_facts(db, tid))
    def broken(*args, **kwargs):
        raise OSError('private diagnostic details must not escape')
    monkeypatch.setattr(command_context.CommandContext if failure == 'receipt' else command_context,
                        'receipt' if failure == 'receipt' else '_persist', broken)
    class BrokenStderr(io.StringIO):
        def write(self, text):
            raise BrokenPipeError('diagnostic channel closed')
    out, err = io.StringIO(), BrokenStderr() if failure == 'warning' else io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = climain.main(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
                                   '--phase', 'development', '--summary', 'fact survives diagnostic failure'))
    assert rc == 0
    assert json.loads(out.getvalue())['facts_committed'] is True
    assert len(_b05_facts(db, tid)) > before
    assert command_context.current() is None
    assert 'private diagnostic details' not in out.getvalue() + err.getvalue()


def test_b08_invalid_task_identifier_is_not_persisted_as_sensitive_diagnostic_input(tmp_path):
    secret = 'Authorization: Bearer do-not-copy-this-token'
    rc, _, _ = run_cli(['task', 'create', '--id', secret, '--project', 'missing', '--risk', 'L0', '--flow', 'L0'])
    assert rc != 0
    rc, out, err = run_cli(['report', 'timings', '--json'])
    assert rc == 0, (out, err)
    row = next(r for r in json.loads(out)['records'] if r['command'] == 'task create')
    assert row['task_id'] is None
    assert secret not in out


def test_b08_caught_interrupt_is_not_recorded_as_ordinary_failure_or_completed_command(tmp_path, monkeypatch):
    from cli import main as climain, command_context
    def interrupt(_):
        raise KeyboardInterrupt()
    with monkeypatch.context() as patch:
        patch.setattr(climain.autonomy_context, 'guard_content_cli', interrupt)
        with pytest.raises(KeyboardInterrupt):
            climain.main(['report', 'timings', '--json'])
    assert command_context.current() is None
    rc, out, err = run_cli(['report', 'timings', '--json'])
    assert rc == 0, (out, err)
    row = next(r for r in json.loads(out)['records'] if r['command'] == 'report timings')
    assert row['exit_code'] == 130
    assert row.get('completion') == 'interrupted'
    assert row['segments']['card']['status'] == 'not_entered'


@pytest.mark.parametrize('outcome', ['success', 'required_failure', 'derived_failure'])
def test_b08_immediate_lock_hold_is_measured_through_commit_or_rollback(tmp_path, monkeypatch, outcome):
    import time
    from cli import transaction_commit
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    before = len(_b05_facts(db, tid))
    backup = transaction_commit._backup
    def slow_backup(*args, **kwargs):
        # This real work is outside db_write but inside the acquired writer lock.
        time.sleep(0.02)
        return backup(*args, **kwargs)
    monkeypatch.setattr(transaction_commit, '_backup', slow_backup)
    replace = transaction_commit._stage_and_replace
    def fail_if_selected(task_dir, texts, rel_paths):
        if ((outcome == 'required_failure' and 'status.yaml' in rel_paths)
                or (outcome == 'derived_failure' and 'generated/continuation.md' in rel_paths)):
            raise OSError('injected selected projection failure')
        return replace(task_dir, texts, rel_paths)
    monkeypatch.setattr(transaction_commit, '_stage_and_replace', fail_if_selected)
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
                                   '--phase', 'development', '--summary', 'measure held lock'))
    if outcome == 'required_failure':
        assert rc != 0 and len(_b05_facts(db, tid)) == before
    else:
        assert rc == 0 and json.loads(out)['facts_committed'] is True, (out, err)
        assert json.loads(out)['view_status'] == ('PENDING' if outcome == 'derived_failure' else 'CURRENT')
    rc, out, err = run_cli(['report', 'timings', '--task', tid, '--json'])
    assert rc == 0, (out, err)
    row = next(r for r in json.loads(out)['records'] if r['command'] == 'task checkpoint')
    held = row['segments'].get('lock_held')
    assert held is not None, row
    assert held['calls'] == (1 if outcome == 'required_failure' else 2)
    assert 20 <= held['elapsed_ms'] <= row['total_ms']
    assert held['status'] == ('completed' if outcome == 'success' else 'failed')
    assert row['segments']['card']['status'] == 'not_entered'
    assert 'lock_held' in row['measurement_notes']


def test_b08_fresh_explicit_card_uses_current_facts_without_mutating_them(tmp_path, monkeypatch):
    import subprocess
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
                                   '--phase', 'development', '--summary', 'B08 latest explicit snapshot'))
    assert rc == 0, (out, err)
    before = (_b05_facts(db, tid), (tdir / 'status.yaml').read_bytes(), (tdir / 'events.jsonl').read_bytes())
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / 'explicit-card.html'
    proc = subprocess.run([sys.executable, str(root / 'cli/main.py'), 'card', 'task', '--task', tid,
                           '--db', str(db), '--output', str(output), '--artifact-root', str(project)],
                          cwd=project, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(next(line[len('CARD_DISPLAY: '):] for line in proc.stdout.splitlines() if line.startswith('CARD_DISPLAY: ')))
    assert result['artifact']['status'] == 'generated'
    assert result['inline']['status'] == 'not_requested'
    assert 'B08 latest explicit snapshot' in output.read_text(encoding='utf-8')
    assert before == (_b05_facts(db, tid), (tdir / 'status.yaml').read_bytes(), (tdir / 'events.jsonl').read_bytes())
    rc, out, err = run_cli(['report', 'timings', '--task', tid, '--json'])
    assert rc == 0, (out, err)
    row = next(r for r in json.loads(out)['records'] if r['command'] == 'card task')
    assert row['exit_code'] == 0 and row['segments']['card']['calls'] == 1
    assert row['segments']['card']['elapsed_ms'] > 0


@pytest.mark.parametrize('bad', [
    {'calls': -1}, {'elapsed_ms': float('nan')}, {'elapsed_ms': True},
    {'status': ['completed']}, {'elapsed_ms': 10 ** 400},
    {'calls': 1, 'elapsed_ms': 3.0, 'status': 'not_entered'},
])
def test_b08_corrupt_segment_cannot_be_returned_as_measured_duration(tmp_path, bad):
    from cli import command_context
    row = command_context.CommandContext().receipt()
    row['segments']['card'].update(bad)
    root = command_context._root()
    root.mkdir(parents=True)
    (root / 'corrupt.json').write_text(json.dumps(row), encoding='utf-8')
    rc, out, err = run_cli(['report', 'timings', '--json'])
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result['records'] == []
    assert result['corrupt_records_skipped'] == 1


def test_b08_legacy_diagnostic_without_new_optional_fields_remains_queryable(tmp_path):
    from cli import command_context
    row = command_context.CommandContext().receipt()
    row.pop('completion', None)
    row['segments'].pop('lock_held', None)
    root = command_context._root()
    root.mkdir(parents=True)
    (root / 'legacy.json').write_text(json.dumps(row), encoding='utf-8')
    rc, out, err = run_cli(['report', 'timings', '--json'])
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result['records'] == [row]
    assert result['corrupt_records_skipped'] == 0
