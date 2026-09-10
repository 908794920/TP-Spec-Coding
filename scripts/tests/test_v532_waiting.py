from __future__ import annotations

import json
import os

from cli import db as dbmod
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args


def test_waiting_human_has_consistent_owner_and_does_not_dispatch_development(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(db, tdir, tid, "block", "--actor", "tp-test-engineer", "--reason", "visual acceptance not run", "--kind", "human_acceptance", "--condition", "owner validates current version"))
    assert rc == 0, (out, err)
    assert 'next_responsibility: "human_owner"' in (tdir / "status.yaml").read_text(encoding="utf-8")
    rc, out, err = run_cli(["workflow", "next", "--task", tid, "--db", str(db), "--json"])
    assert rc == 0, (out, err)
    route = json.loads(out)
    assert route["skill_path"] is None
    assert route["next_responsibility"] == "human_owner"
    assert route["context"]["waiting"]["kind"] == "human_acceptance"
    assert route["requires_human"] is True
    assert "NEEDS_FIX" not in out
    rc, _, err = run_cli(task_args(db, tdir, tid, "resume", "--actor", "tp-test-engineer", "--summary", "pretend resolved", "--resolution-evidence", "evidence/check.txt"))
    assert rc != 0 and "OWNER_RESOLUTION_REQUIRED" in err
    rc, out, err = run_cli(task_args(db, tdir, tid, "resume", "--actor", "human_owner", "--summary", "owner resolution received", "--resolution-evidence", "evidence/check.txt"))
    assert rc == 0, (out, err)


def test_unchanged_environment_proof_does_not_resume_or_add_events(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    proof = tdir / "evidence/check.txt"
    rc, out, err = run_cli(task_args(db, tdir, tid, "block", "--actor", "tp-test-engineer", "--reason", "runtime unavailable", "--kind", "environment", "--condition", "runtime becomes available", "--prerequisite-evidence", "evidence/check.txt"))
    assert rc == 0, (out, err)
    with dbmod.connect_readonly(str(db)) as conn:
        before = conn.execute("SELECT COUNT(*) FROM task_event").fetchone()[0]
    args = task_args(db, tdir, tid, "resume", "--actor", "tp-test-engineer", "--summary", "retry", "--resolution-evidence", "evidence/check.txt")
    rc, _, err = run_cli(args)
    assert rc != 0 and "PREREQUISITE_UNCHANGED" in err
    with dbmod.connect_readonly(str(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_event").fetchone()[0] == before
    stat = proof.stat()
    proof.write_bytes(b"X" * stat.st_size)
    os.utime(proof, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)


def create_dependency(project, db, tid):
    tdir = project / ".tp-spec/tasks" / tid
    rc, out, err = run_cli(["task", "create", "--id", tid, "--project", "v532-test", "--risk", "L0", "--flow", "L0", "--scaffold", "--task-dir", str(tdir), "--db", str(db)])
    assert rc == 0, (out, err)
    tdir.joinpath("acceptance.md").write_text('```yaml\nno_acceptance_required:\n  declared: true\n  declared_by: human_owner\n  reason: isolated synthetic dependency\n```\n', encoding="utf-8")
    return tdir


def test_dependency_wait_checks_actual_tasks_and_rejects_cycles(tmp_path, monkeypatch):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    dep = "TASK-DEPENDENCY"
    depdir = create_dependency(project, db, dep)
    rc, out, err = run_cli(task_args(db, tdir, tid, "block", "--actor", "tp-test-engineer", "--reason", "upstream not complete", "--kind", "dependency", "--requires-task", dep))
    assert rc == 0, (out, err)
    rc, _, err = run_cli(task_args(db, depdir, dep, "block", "--actor", "tp-test-engineer", "--reason", "cycle", "--kind", "dependency", "--requires-task", tid))
    assert rc != 0 and "DEPENDENCY_CYCLE" in err
    args = task_args(db, tdir, tid, "resume", "--actor", "tp-test-engineer", "--summary", "upstream resolved")
    rc, _, err = run_cli(args)
    assert rc != 0 and "DEPENDENCY_NOT_COMPLETE" in err
    rc, out, err = run_cli(task_args(db, depdir, dep, "checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", "synthetic upstream work"))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(db, depdir, dep, "complete", "--actor", "tp-development-engineer", "--summary", "synthetic upstream complete"))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)


def test_corrupt_typed_wait_cannot_downgrade_to_legacy_or_lose_dependency_gate():
    import pytest
    from cli import event_contract, waiting
    valid = {
        'kind': 'dependency', 'responsibility': 'tp-test-engineer',
        'condition': 'upstream completed', 'requires_tasks': ['TASK-UPSTREAM'],
        'prerequisite_evidence': [],
    }
    corrupt = [None, {}, {**valid, 'requires_tasks': []},
               {**valid, 'requires_tasks': 'TASK-UPSTREAM'},
               {**valid, 'responsibility': 'invented-owner'},
               {**valid, 'prerequisite_evidence': [None]},
               {**valid, 'kind': 'human_acceptance', 'responsibility': 'tp-test-engineer'}]
    for wait in corrupt:
        event = {'id': 1, 'event_type': 'STATE', 'to_state': 'BLOCKED',
                 'detail_json': json.dumps({'schema': event_contract.EVENT_SCHEMA,
                    'producer': 'record-first', 'transaction_id': 'test-only-txn', 'waiting': wait})}
        with pytest.raises(ValueError, match='WAIT_FACT_INVALID'):
            waiting.active_wait([event], 'BLOCKED')
    # Genuinely absent legacy fields remain compatible, never inferred from text.
    event['detail_json'] = '{}'
    assert waiting.active_wait([event], 'BLOCKED') == {}


def _read_route(db, tid):
    rc, out, err = run_cli(["workflow", "next", "--task", tid, "--db", str(db), "--json"])
    assert rc == 0, (out, err)
    return json.loads(out)


def _task_fact_identity(db, tid):
    with dbmod.connect_readonly(str(db)) as conn:
        state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (tid,)).fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM task_event WHERE task_id=?", (tid,)).fetchone()[0]
    return state, count


def test_blocked_continuation_stops_at_resume_boundary(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(
        db, tdir, tid, "block", "--actor", "tp-test-engineer",
        "--reason", "等待用户复验当前页面", "--kind", "human_acceptance",
        "--condition", "用户提供当前版本的复验结果",
    ))
    assert rc == 0, (out, err)
    view = tdir / "generated/continuation.md"
    text = view.read_text(encoding="utf-8")
    before = _task_fact_identity(db, tid), view.read_bytes()
    for _ in range(2):
        route = _read_route(db, tid)
        assert route["current_state"] == "BLOCKED"
        assert route["skill_path"] is None
        assert route["role_id"] is None
        assert route["next_responsibility"] == "human_owner"
        assert route["context"]["waiting"]["condition"] == "用户提供当前版本的复验结果"
        assert route["recommended_action"] == "task_resume_after_resolution"
    assert (_task_fact_identity(db, tid), view.read_bytes()) == before
    assert "等待用户复验当前页面" in text
    assert "下一责任：human_owner" in text
    # The generated handoff must not contradict the Runtime's stop boundary.
    assert "继续完成业务工作即可" not in text
    assert "保持等待" in text and "task resume" in text


def test_legacy_blocked_continuation_stops_without_inventing_a_resolution(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(
        db, tdir, tid, "block", "--actor", "tp-test-engineer",
        "--reason", "外部前置尚未满足",
    ))
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route["current_state"] == "BLOCKED" and route["skill_path"] is None
    assert not route.get("context", {}).get("waiting")
    text = (tdir / "generated/continuation.md").read_text(encoding="utf-8")
    assert "外部前置尚未满足" in text
    assert "继续完成业务工作即可" not in text
    assert "保持等待" in text and "task resume" in text


def test_cancelled_continuation_is_terminal_not_a_wake_prompt(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(
        db, tdir, tid, "cancel", "--actor", "human_owner", "--reason", "取消隔离测试任务",
    ))
    assert rc == 0, (out, err)
    before = _task_fact_identity(db, tid)
    route = _read_route(db, tid)
    assert route["current_state"] == "CANCELLED"
    assert route["recommended_action"] == "none" and route["skill_path"] is None
    rc, _, err = run_cli(task_args(
        db, tdir, tid, "resume", "--actor", "tp-test-engineer", "--summary", "不能恢复取消任务",
    ))
    assert rc != 0 and "requires current state BLOCKED" in err
    assert _task_fact_identity(db, tid) == before
    text = (tdir / "generated/continuation.md").read_text(encoding="utf-8")
    assert "继续完成业务工作即可" not in text
    assert "已终止" in text and "仅供查询" in text


def test_resumed_active_continuation_does_not_keep_waiting_guidance(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(task_args(
        db, tdir, tid, "block", "--actor", "tp-test-engineer",
        "--reason", "等待隔离环境", "--kind", "environment", "--condition", "环境可用",
    ))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, tdir, tid, "resume", "--actor", "tp-test-engineer",
        "--summary", "隔离环境已有新证据", "--resolution-evidence", "evidence/check.txt",
    ))
    assert rc == 0, (out, err)
    assert _task_fact_identity(db, tid)[0] == "ACTIVE"
    route = _read_route(db, tid)
    assert route["current_state"] == "ACTIVE" and "TASK_BLOCKED" not in route["reason_codes"]
    text = (tdir / "generated/continuation.md").read_text(encoding="utf-8")
    assert "继续完成业务工作即可" in text
    assert "保持等待" not in text and "当前工作已终止" not in text


# B02 exercises the production entry, not synthetic governance rows or a stub router.
def _prepare_review(tmp_path, monkeypatch, *, delivery=False):
    import shutil

    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    if delivery:
        old_dir = tdir
        tid = 'TASK-B02-DELIVERY'
        tdir = project / '.tp-spec/tasks' / tid
        rc, out, err = run_cli([
            'task', 'create', '--id', tid, '--project', 'v532-test',
            '--risk', 'L2', '--flow', 'L2', '--scaffold', '--task-dir', str(tdir),
            '--db', str(db),
        ])
        assert rc == 0, (out, err)
        shutil.copyfile(old_dir / 'acceptance.md', tdir / 'acceptance.md')
        (tdir / 'evidence').mkdir(exist_ok=True)
        shutil.copyfile(old_dir / 'evidence/check.txt', tdir / 'evidence/check.txt')
        for actor, phase in [('tp-product-manager', 'requirement'),
                             ('tp-software-architect', 'architecture'),
                             ('tp-tech-lead', 'planning')]:
            rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint',
                '--actor', actor, '--phase', phase, '--summary', phase + ' complete'))
            assert rc == 0, (out, err)
        rc, out, err = run_cli(['workflow', 'confirm', '--task', tid,
                               '--task-dir', str(tdir), '--db', str(db), '--json'])
        assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint',
        '--actor', 'tp-development-engineer', '--phase', 'development',
        '--summary', 'isolated reviewed subject', '--repo-root', str(project)))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify',
        '--actor', 'tp-test-engineer', '--decision', 'PASS',
        '--summary', 'isolated technical check', '--evidence', 'evidence/check.txt'))
    assert rc == 0, (out, err)
    return project, db, tdir, tid


def _record_review(db, tdir, tid, decision, *, kind='CODE', findings=0):
    actor = 'tp-software-architect' if kind == 'ARCHITECTURE' else 'tp-code-reviewer'
    if kind == 'ARCHITECTURE':
        from pathlib import Path
        from cli.version import active_version
        template = Path(__file__).resolve().parents[2] / 'templates' / active_version() / 'architecture-review.md'
        (tdir / 'architecture-review.md').write_bytes(template.read_bytes())
    (tdir / 'evidence/code-review.txt').write_text('Synthetic professional result evidence.\n', encoding='utf-8')
    rc, out, err = run_cli(['review', 'record', '--task', tid, '--task-dir', str(tdir),
        '--evidence', 'evidence/code-review.txt',
        '--db', str(db), '--actor', actor, '--kind', kind, '--decision', decision,
        '--findings-count', str(findings), '--summary',
        '等待审查前置；尚无产品缺陷结论' if decision == 'BLOCKED' else '实际审查结论：' + decision])
    assert rc == 0, (out, err)


def test_b02_typed_wait_condition_reaches_status_and_continuation(tmp_path, monkeypatch):
    import yaml

    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    condition = '用户复验当前版本，提供按钮遮挡的实际结果'
    rc, out, err = run_cli(task_args(db, tdir, tid, 'block',
        '--actor', 'tp-test-engineer', '--reason', '视觉检查尚未运行',
        '--kind', 'human_acceptance', '--condition', condition))
    assert rc == 0, (out, err)
    status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
    route = _read_route(db, tid)
    text = (tdir / 'generated/continuation.md').read_text(encoding='utf-8')
    assert condition in '\n'.join(status['blockers'])
    assert condition in text and 'human_acceptance' in text
    assert route['context']['waiting']['condition'] == condition
    assert status['findings'] == []
    assert status['quality_facts']['verification'] == 'NOT_RECORDED'


def test_b02_code_blocked_waits_without_findings_or_unrelated_retry(tmp_path, monkeypatch):
    import yaml

    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    for _ in range(2):
        before = _task_fact_identity(db, tid)
        route = _read_route(db, tid)
        assert route['role_id'] is None and route['skill_path'] is None
        assert route['recommended_action'] == 'none'
        assert route['next_responsibility'] == 'tp-code-reviewer'
        assert 'REVIEW_BLOCKED' in route['reason_codes']
        assert _task_fact_identity(db, tid) == before
    status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
    assert status['findings'] == [] and status['blockers']
    assert status['next_responsibility'] == route['next_responsibility']
    text = (tdir / 'generated/continuation.md').read_text(encoding='utf-8')
    assert '保持等待' in text and '继续完成业务工作即可' not in text
    # A newer checkpoint with identical product content is not a resolved prerequisite.
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint',
        '--actor', 'tp-development-engineer', '--phase', 'development',
        '--summary', 'only repeated bookkeeping, not a repair'))
    assert rc == 0, (out, err)
    (tdir / 'evidence/unrelated-note.md').write_text('unrelated note', encoding='utf-8')
    route = _read_route(db, tid)
    assert route['skill_path'] is None and 'REVIEW_BLOCKED' in route['reason_codes']


def test_b02_architecture_blocked_waits_instead_of_forcing_redesign(tmp_path, monkeypatch):
    import yaml

    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED', kind='ARCHITECTURE')
    route = _read_route(db, tid)
    assert route['role_id'] is None and route['skill_path'] is None
    assert route['next_responsibility'] == 'tp-software-architect'
    status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
    assert status['next_responsibility'] == route['next_responsibility']
    assert status['findings'] == [] and status['blockers']


def test_b02_delivery_blocked_waits_for_owner_and_keeps_real_recovery_condition(tmp_path, monkeypatch):
    import yaml

    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch, delivery=True)
    _record_review(db, tdir, tid, 'PASS')
    condition = '获得指定集成操作授权并保留证据'
    rc, out, err = run_cli(task_args(db, tdir, tid, 'delivery-converge',
        '--delivery-status', 'BLOCKED', '--reason', '集成受限操作尚未得到授权，不可继续执行',
        '--blocker-kind', 'HUMAN_DECISION', '--responsibility', 'human_owner',
        '--recovery-condition', condition))
    assert rc == 0, (out, err)
    before = _task_fact_identity(db, tid)
    for _ in range(2):
        route = _read_route(db, tid)
        assert route['role_id'] is None and route['skill_path'] is None
        assert route['requires_human'] is True
        assert route['next_responsibility'] == 'human_owner'
        assert route['context']['waiting']['condition'] == condition
        assert 'DELIVERY_BLOCKED' in route['reason_codes']
    assert _task_fact_identity(db, tid) == before
    status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
    assert status['findings'] == []
    assert condition in '\n'.join(status['blockers'])
    assert condition in (tdir / 'generated/continuation.md').read_text(encoding='utf-8')


def test_b02_typed_resolution_reopens_review_without_granting_pass(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    proof = tdir / 'evidence/environment.txt'
    proof.write_text('environment unavailable', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'block',
        '--actor', 'tp-code-reviewer', '--phase', 'review', '--kind', 'environment',
        '--reason', 'review environment unavailable', '--condition', 'environment available',
        '--prerequisite-evidence', 'evidence/environment.txt'))
    assert rc == 0, (out, err)
    resume = task_args(db, tdir, tid, 'resume', '--actor', 'tp-code-reviewer',
        '--summary', 'current environment checked', '--resolution-evidence', 'evidence/environment.txt')
    before = _task_fact_identity(db, tid)
    for _ in range(2):
        rc, _, err = run_cli(resume)
        assert rc != 0 and 'PREREQUISITE_UNCHANGED' in err
    assert _task_fact_identity(db, tid) == before
    proof.write_text('environment now available', encoding='utf-8')
    rc, out, err = run_cli(resume)
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route['next_stage'] == 'review' and route['role_id'] == 'tp-code-reviewer'
    assert 'REVIEW_BLOCKED' not in route['reason_codes']
    with dbmod.connect_readonly(str(db)) as conn:
        rows = conn.execute("SELECT detail_json FROM task_event WHERE task_id=? AND event_type='REVIEW_COMPLETED'", (tid,)).fetchall()
    assert [json.loads(row[0])['decision'] for row in rows] == ['BLOCKED']
    assert '保持等待' not in (tdir / 'generated/continuation.md').read_text(encoding='utf-8')


def test_b02_changed_product_subject_reassesses_but_does_not_reuse_old_pass(tmp_path, monkeypatch):
    project, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    (project / 'app.txt').write_text('v2 substantive product change\n', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
        '--phase', 'development', '--summary', 'new actual product subject'))
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route['next_stage'] == 'verification' and route['role_id'] == 'tp-test-engineer'
    before = _task_fact_identity(db, tid)
    for _ in range(2):
        rc, out, err = run_cli(['review', 'record', '--task', tid, '--task-dir', str(tdir),
            '--db', str(db), '--actor', 'tp-code-reviewer', '--kind', 'CODE',
            '--decision', 'PASS', '--summary', 'old verification is insufficient'])
        assert rc != 0 and 'VERIFICATION_STALE' in err
    assert _task_fact_identity(db, tid) == before


def test_b02_new_actual_finding_still_dispatches_repair(tmp_path, monkeypatch):
    import yaml

    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    _record_review(db, tdir, tid, 'NEEDS_FIX', findings=1)
    route = _read_route(db, tid)
    assert route['role_id'] == 'tp-development-engineer'
    assert route['recommended_action'] == 'dispatch_role'
    assert 'CODE_REVIEW_REWORK' in route['reason_codes']
    status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
    assert status['findings'] and not status['blockers']
    assert status['next_responsibility'] == route['role_id']


def test_b02_delivery_owner_resolution_is_not_replaced_by_environment_resolution(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch, delivery=True)
    _record_review(db, tdir, tid, 'PASS')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'delivery-converge',
        '--delivery-status', 'BLOCKED', '--reason', 'a specific owner decision is still required',
        '--blocker-kind', 'HUMAN_DECISION', '--responsibility', 'human_owner',
        '--recovery-condition', 'owner authorizes the specified integration operation'))
    assert rc == 0, (out, err)
    for kind, actor in [('environment', 'tp-integration-engineer'), ('permission', 'human_owner')]:
        rc, out, err = run_cli(task_args(db, tdir, tid, 'block',
            '--actor', 'tp-integration-engineer', '--phase', 'delivery', '--kind', kind,
            '--reason', 'the specified delivery prerequisite', '--condition', 'new prerequisite proof available'))
        assert rc == 0, (out, err)
        rc, out, err = run_cli(task_args(db, tdir, tid, 'resume', '--actor', actor,
            '--summary', 'new explicit resolution', '--resolution-evidence', 'evidence/check.txt'))
        assert rc == 0, (out, err)
        route = _read_route(db, tid)
        if kind == 'environment':
            assert route['skill_path'] is None and route['next_responsibility'] == 'human_owner'
        else:
            assert route['next_stage'] == 'delivery' and route['role_id'] == 'tp-integration-engineer'
            assert 'DELIVERY_BLOCKED' not in route['reason_codes']
    rc, _, err = run_cli(task_args(db, tdir, tid, 'complete', '--actor', 'tp-integration-engineer',
                                  '--summary', 'a resolution is not delivery READY'))
    assert rc != 0  # No READY result has been recorded.


def test_b02_stale_technical_subject_does_not_redispatch_doomed_delivery(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch, delivery=True)
    _record_review(db, tdir, tid, 'PASS')
    with (tdir / 'acceptance.md').open('a', encoding='utf-8') as handle:
        handle.write('\nNew acceptance criterion: also check the second input.\n')
    before = _task_fact_identity(db, tid)
    for _ in range(2):
        route = _read_route(db, tid)
        assert route['next_stage'] == 'verification' and route['role_id'] == 'tp-test-engineer'
        assert 'CURRENT_VERIFICATION_REQUIRED' in route['reason_codes']
    assert _task_fact_identity(db, tid) == before
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--actor', 'tp-test-engineer',
        '--decision', 'PASS', '--summary', 'current criteria checked', '--evidence', 'evidence/check.txt'))
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route['next_stage'] == 'review' and route['role_id'] == 'tp-code-reviewer'


def test_b02_progress_keeps_waiting_responsibility_without_inventing_execution(tmp_path, monkeypatch):
    from cli import orchestration

    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch, delivery=True)
    _record_review(db, tdir, tid, 'PASS')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'delivery-converge',
        '--delivery-status', 'BLOCKED', '--reason', 'owner controlled prerequisite is not ready',
        '--blocker-kind', 'HUMAN_DECISION', '--responsibility', 'human_owner',
        '--recovery-condition', 'explicit owner resolution'))
    assert rc == 0, (out, err)
    progress = orchestration.resolve_progress(tid, db_path=str(db))
    assert progress['current_step']['status'] == '已阻塞'
    assert progress['next_step']['role'] == 'human_owner'
    assert progress['next_step']['waiting']['condition'] == 'explicit owner resolution'
    assert progress['route']['recommended_action'] == 'none'


def test_b02_new_verification_evidence_reopens_review_but_duplicate_pass_does_not(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--actor', 'tp-test-engineer',
        '--decision', 'PASS', '--summary', 'duplicate of the same check', '--evidence', 'evidence/check.txt'))
    assert rc == 0, (out, err)
    assert _read_route(db, tid)['skill_path'] is None
    (tdir / 'evidence/new-check.txt').write_text('additional observed prerequisite result', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--actor', 'tp-test-engineer',
        '--decision', 'PASS', '--summary', 'new relevant check', '--evidence', 'evidence/new-check.txt'))
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route['next_stage'] == 'review' and route['role_id'] == 'tp-code-reviewer'


def test_b02_new_real_verification_failure_is_not_hidden_by_old_review_wait(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    (tdir / 'evidence/failure.txt').write_text('reproduced wrong result in the affected input', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--actor', 'tp-test-engineer',
        '--decision', 'NEEDS_FIX', '--summary', 'a reproducible defect was found', '--evidence', 'evidence/failure.txt'))
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route['next_stage'] == 'development' and 'VERIFICATION_NEEDS_FIX' in route['reason_codes']


def test_b02_architecture_subject_change_can_be_reassessed_without_unrelated_notes(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED', kind='ARCHITECTURE')
    (tdir / 'evidence/unrelated.txt').write_text('an unrelated diagnostic note', encoding='utf-8')
    assert _read_route(db, tid)['skill_path'] is None
    with (tdir / 'requirement-decisions.md').open('a', encoding='utf-8') as handle:
        handle.write('\nThe conflicting architecture requirement is now resolved in this synthetic scenario.\n')
    route = _read_route(db, tid)
    assert 'REVIEW_BLOCKED' not in route['reason_codes']
    # Reevaluation is not a new review PASS and must still use existing routing.
    assert route['recommended_action'] != 'task_complete'


def test_b02_non_owner_change_cannot_clear_owner_responsibility_even_with_other_kind(tmp_path, monkeypatch):
    project, db, tdir, tid = _prepare_review(tmp_path, monkeypatch, delivery=True)
    _record_review(db, tdir, tid, 'PASS')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'delivery-converge',
        '--delivery-status', 'BLOCKED', '--reason', 'an explicit owner decision remains necessary',
        '--blocker-kind', 'OTHER', '--responsibility', 'human_owner', '--recovery-condition', 'owner decision received'))
    assert rc == 0, (out, err)
    (project / 'app.txt').write_text('v2 actual change cannot grant permission', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
        '--phase', 'development', '--summary', 'new actual product content'))
    assert rc == 0, (out, err)
    route = _read_route(db, tid)
    assert route['skill_path'] is None and route['next_responsibility'] == 'human_owner'


def test_b02_legacy_or_other_phase_resume_cannot_clear_professional_wait(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    for phase, options in [('review', []), ('development', ['--kind', 'environment', '--condition', 'different phase is ready'])]:
        rc, out, err = run_cli(task_args(db, tdir, tid, 'block', '--actor', 'tp-test-engineer',
            '--phase', phase, '--reason', 'different or untyped wait', *options))
        assert rc == 0, (out, err)
        proof = ['--resolution-evidence', 'evidence/check.txt'] if options else []
        rc, out, err = run_cli(task_args(db, tdir, tid, 'resume', '--actor', 'tp-test-engineer',
            '--summary', 'this resolution does not prove the review prerequisite', *proof))
        assert rc == 0, (out, err)
        route = _read_route(db, tid)
        assert route['skill_path'] is None and 'REVIEW_BLOCKED' in route['reason_codes']


def test_b02_resolution_proof_replacement_does_not_keep_wait_unlocked(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    proof = tdir / 'evidence/resolution.txt'
    proof.write_text('actual environment recovery result', encoding='utf-8')
    rc, out, err = run_cli(task_args(db, tdir, tid, 'block', '--actor', 'tp-code-reviewer',
        '--phase', 'review', '--kind', 'environment', '--reason', 'review prerequisite unavailable',
        '--condition', 'prerequisite now available'))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(db, tdir, tid, 'resume', '--actor', 'tp-code-reviewer',
        '--summary', 'prerequisite was verified', '--resolution-evidence', 'evidence/resolution.txt'))
    assert rc == 0, (out, err)
    assert _read_route(db, tid)['role_id'] == 'tp-code-reviewer'
    stat = proof.stat()
    proof.write_bytes(b'X' * stat.st_size)
    os.utime(proof, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    route = _read_route(db, tid)
    assert route['skill_path'] is None and 'REVIEW_BLOCKED' in route['reason_codes']


def test_b02_replaced_verification_evidence_routes_to_test_not_doomed_review(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    proof = tdir / 'evidence/check.txt'
    stat = proof.stat()
    proof.write_bytes(b'X' * stat.st_size)
    os.utime(proof, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    before = _task_fact_identity(db, tid)
    route = _read_route(db, tid)
    assert route['next_stage'] == 'verification' and 'CURRENT_VERIFICATION_REQUIRED' in route['reason_codes']
    assert _task_fact_identity(db, tid) == before


def test_b02_review_aliases_keep_finding_and_waiting_views_consistent(tmp_path, monkeypatch):
    import yaml

    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    for kind in ['IMPLEMENTATION', 'ULTRA_REVIEW']:
        _record_review(db, tdir, tid, 'NEEDS_FIX', kind=kind, findings=1)
        route = _read_route(db, tid)
        status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
        assert route['role_id'] == 'tp-development-engineer'
        assert status['next_responsibility'] == route['role_id'] and status['findings']
        _record_review(db, tdir, tid, 'BLOCKED', kind=kind)
        route = _read_route(db, tid)
        status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
        assert route['skill_path'] is None and not status['findings']
        assert status['blockers'] and status['next_responsibility'] == 'tp-code-reviewer'
        _record_review(db, tdir, tid, 'PASS', kind=kind)
        status = yaml.safe_load((tdir / 'status.yaml').read_text(encoding='utf-8'))
        assert not status['blockers'] and not status['findings']
        assert status['quality_facts']['review'] == 'PASS'


def test_b02_changed_review_criteria_reopens_verification_not_old_pass(tmp_path, monkeypatch):
    _, db, tdir, tid = _prepare_review(tmp_path, monkeypatch)
    _record_review(db, tdir, tid, 'BLOCKED')
    with (tdir / 'acceptance.md').open('a', encoding='utf-8') as handle:
        handle.write('\nResolved criterion: use the confirmed input boundary.\n')
    route = _read_route(db, tid)
    assert route['next_stage'] == 'verification'
    assert route['role_id'] == 'tp-test-engineer'
    assert 'CURRENT_VERIFICATION_REQUIRED' in route['reason_codes']
