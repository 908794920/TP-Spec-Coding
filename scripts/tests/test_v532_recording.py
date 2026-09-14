from __future__ import annotations

import hashlib
import json

import pytest

from cli import db as dbmod
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args


def rows(db, tid):
    with dbmod.connect_readonly(str(db)) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (tid,))]


def cp(db, tdir, tid, key, summary="batch of work", *extra):
    return task_args(db, tdir, tid, "checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", summary, "--request-id", key, *extra)


def test_same_logical_request_replays_without_new_events_but_new_request_is_recorded(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    args = cp(db, tdir, tid, "logical-work-1")
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    original = json.loads(out)
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    repeated = json.loads(out)
    assert repeated["replayed"] is True
    assert repeated["flush_id"] == original["flush_id"]
    assert repeated["change_set_id"] == original["change_set_id"]
    assert rows(db, tid) == before
    rc, out, err = run_cli(cp(db, tdir, tid, "logical-work-2"))
    assert rc == 0, (out, err)
    assert json.loads(out)["replayed"] is False
    assert len(rows(db, tid)) > len(before)


def test_request_id_payload_conflict_is_not_silently_deduplicated(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(cp(db, tdir, tid, "same-id"))
    assert rc == 0, (out, err)
    before = rows(db, tid)
    rc, _, err = run_cli(cp(db, tdir, tid, "same-id", "different business meaning"))
    assert rc != 0 and "REQUEST_ID_CONFLICT" in err
    assert rows(db, tid) == before


def test_checkpoint_collects_outputs_in_one_fact_without_claiming_pass(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    first = tmp_path / "test-result.txt"
    second = tmp_path / "another/test-result.txt"
    second.parent.mkdir()
    first.write_text("actual isolated fixture output A", encoding="utf-8")
    second.write_text("actual isolated fixture output B", encoding="utf-8")
    rc, out, err = run_cli(cp(db, tdir, tid, "artifact-batch", "outputs collected", "--collect", str(first), "--collect", str(second)))
    assert rc == 0, (out, err)
    response = json.loads(out)
    assert len(response["collected_artifacts"]) == 2
    for artifact in response["collected_artifacts"]:
        target = tdir / artifact["path"]
        assert target.is_file()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == artifact["sha256"]
        assert artifact["path"].startswith("evidence/collected/")
    facts = [row for row in rows(db, tid) if row["event_type"] == "FACT"]
    detail = json.loads(facts[-1]["detail_json"])
    assert len(detail["evidence_items"]) == 2
    assert detail["logical_request"]["request_id"] == "artifact-batch"
    assert not any(row["event_type"] == "VERIFICATION_COMPLETED" for row in rows(db, tid))
    first.unlink()
    second.unlink()
    rc, out, err = run_cli(cp(db, tdir, tid, "artifact-batch", "outputs collected", "--collect", str(first), "--collect", str(second)))
    assert rc == 0 and json.loads(out)["replayed"] is True, (out, err)
    target = tdir / response["collected_artifacts"][0]["path"]
    target.write_bytes(b"tampered")
    rc, _, err = run_cli(cp(db, tdir, tid, "artifact-batch", "outputs collected", "--collect", str(first), "--collect", str(second)))
    assert rc != 0 and "REQUEST_EVIDENCE_CHANGED" in err


def test_verify_replay_does_not_forge_a_new_test_run(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(cp(db, tdir, tid, "development"))
    assert rc == 0, (out, err)
    args = task_args(db, tdir, tid, "verify", "--decision", "PASS", "--summary", "fixture tested", "--evidence", "evidence/check.txt", "--request-id", "test-run-one")
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    result = json.loads(out)
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    assert json.loads(out)["flush_id"] == result["flush_id"]
    assert json.loads(out)["replayed"] is True
    assert rows(db, tid) == before


def test_concurrent_process_retries_have_one_receipt_and_no_journal_leftovers(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import subprocess
    import sys
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    base = Path(__file__).resolve().parents[2]
    args = [sys.executable, '-m', 'cli.main', *cp(db, tdir, tid, 'concurrent-request')]
    before = rows(db, tid)
    processes = [subprocess.Popen(args, cwd=base, env=os.environ.copy(), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
    responses = []
    try:
        for process in processes:
            out, err = process.communicate(timeout=30)
            assert process.returncode == 0, (out, err)
            responses.append(json.loads(out))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert sorted(item['replayed'] for item in responses) == [False, True]
    assert responses[0]['flush_id'] == responses[1]['flush_id']
    after = rows(db, tid)
    assert len([r for r in after[len(before):] if r['event_type'] == 'FACT']) == 1
    assert not list(tdir.glob('.v511-bak-*'))
    from cli import transaction_journal
    assert transaction_journal.list_journals(tdir) == []


def test_artifact_collection_limits_are_loaded_from_active_base_in_real_cli(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import sys
    import yaml
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    base = Path(__file__).resolve().parents[2]
    copy = tmp_path / 'configured-base'
    copy.mkdir()
    for name in ('cli', 'governance'):
        shutil.copytree(base / name, copy / name, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(base / 'VERSION', copy / 'VERSION')
    policy = copy / 'governance/orchestration.yaml'
    config = yaml.safe_load(policy.read_text(encoding='utf-8'))
    config['execution']['artifact_collection']['max_file_bytes'] = 2
    policy.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    source = tmp_path / 'output.txt'
    source.write_text('larger than limit', encoding='utf-8')
    before = rows(db, tid)
    process = subprocess.run([sys.executable, '-m', 'cli.main',
        *cp(db, tdir, tid, 'configured-limit', 'outputs', '--collect', str(source))],
        cwd=copy, env=os.environ.copy(), capture_output=True, text=True, timeout=30)
    assert process.returncode != 0 and 'ARTIFACT_COLLECTION_LIMIT' in process.stderr, process.stderr
    assert rows(db, tid) == before


def test_collector_refuses_symlink_escape_without_copying_outside_task(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tdir / 'evidence/collected'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        import pytest
        pytest.skip('Creating a directory symlink is not available in this environment')
    source = tmp_path / 'output.txt'
    source.write_text('completed output', encoding='utf-8')
    before = rows(db, tid)
    rc, out, err = run_cli(cp(db, tdir, tid, 'path-escape', 'outputs', '--collect', str(source)))
    assert rc != 0 and 'ARTIFACT_COLLECTION_PATH_ESCAPE' in err, (out, err)
    assert list(outside.iterdir()) == []
    assert rows(db, tid) == before


def test_corrupted_stored_receipt_cannot_return_success(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    args = cp(db, tdir, tid, 'corrupt-receipt')
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    # Deliberate corruption is confined to this synthetic test DB.
    with dbmod.connect(str(db)) as conn:
        row = conn.execute("SELECT id,detail_json FROM task_event WHERE task_id=? AND event_type='FACT' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
        detail = json.loads(row['detail_json'])
        detail['logical_request']['response'] = {'task_id': 'ANOTHER-TASK'}
        conn.execute('UPDATE task_event SET detail_json=? WHERE id=?', (json.dumps(detail), row['id']))
        conn.commit()
    before = rows(db, tid)
    rc, _, err = run_cli(args)
    assert rc != 0 and 'REQUEST_RECORD_INVALID' in err
    assert rows(db, tid) == before


def test_request_identity_includes_valid_context_usage_but_drops_invalid_telemetry(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    valid = [{'source_type': 'wiki', 'asset_id': 'wiki:demo/architecture.md', 'stage': 'retrieved'}]
    args = cp(db, tdir, tid, 'context-request')
    rc, out, err = run_cli(args + ['--context-usage-json', json.dumps(valid)])
    assert rc == 0, (out, err)
    before = rows(db, tid)
    valid[0]['stage'] = 'adopted'
    rc, out, err = run_cli(args + ['--context-usage-json', json.dumps(valid)])
    assert rc != 0 and 'REQUEST_ID_CONFLICT' in err
    assert rows(db, tid) == before
    # Telemetry remains optional; malformed telemetry cannot prevent business recording.
    rc, out, err = run_cli(cp(db, tdir, tid, 'invalid-telemetry') + ['--context-usage-json', '{malformed'])
    assert rc == 0, (out, err)


# B07: reports are collected facts, never an implicit grant of verification or review.
def _junit(path, *, failures=0, skipped=0):
    outcome = '<failure message="fixture failure"/>' if failures else ('<skipped/>' if skipped else '')
    path.write_text(
        '<testsuites><testsuite name="pytest" tests="1" failures="%d" errors="0" skipped="%d" time="0.125">'
        '<testcase classname="test_scope" name="test_selected" time="0.1">%s</testcase>'
        '</testsuite></testsuites>' % (failures, skipped, outcome), encoding='utf-8')
    return path


def _base_report(path):
    path.write_text(json.dumps({
        'version': '1.0.0', 'mode': 'Static', 'passed': 1, 'failed': 0, 'duration': 0.5,
        'artifact_contract': '5.3.3', 'git_sha': 'a' * 40,
        'items': [{'name': 'static.fixture', 'status': 'PASS', 'exit_code': 0,
                   'duration_ms': 125, 'detail': 'raw trace not copied into summary'}],
        'workdir': 'private-local-path', 'workdir_kept': False, 'artifact_hashes': {},
    }), encoding='utf-8')
    return path


def _review_report(path, tid):
    path.write_text(json.dumps({
        'schema': 'tp-spec.code-review-result/v1', 'task_id': tid, 'review_kind': 'CODE',
        'actor_role': 'tp-code-reviewer', 'decision': 'PASS', 'round': 1,
        'findings_count': 0, 'summary': 'external reviewer statement',
        'subject_digest': 'b' * 64, 'change_set_id': 'sha256:' + 'c' * 64,
        'verification_event_id': 17, 'verification_scope': 'technical',
        'evidence': ['evidence/external-review.txt'], 'recorded_at': '2026-09-08T00:00:00Z',
    }), encoding='utf-8')
    return path


def _report_args(db, tdir, tid, key, *paths):
    args = cp(db, tdir, tid, key, 'one completed batch; acceptance remains separate')
    for path in paths:
        args += ['--result-report', str(path)]
    return args


def test_result_reports_create_one_atomic_batch_without_granting_any_pass(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    files = [_junit(tmp_path / 'pytest.xml'), _base_report(tmp_path / 'base.json'),
             _review_report(tmp_path / 'review.json', tid)]
    before = rows(db, tid)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'batch-results', *files))
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result['facts_committed'] is True
    observations = result['result_observations']
    assert [r['format'] for r in observations] == ['junit', 'tp-spec-base-report', 'tp-spec-code-review']
    assert all(r['authority'] == 'observation_only' for r in observations)
    assert all(r['execution_observed_by_cli'] is False for r in observations)
    assert observations[0]['exit_code'] is None and observations[0]['command'] is None
    assert observations[0]['reported_result']['tests'] == 1
    assert observations[1]['reported_result']['checks'][0]['exit_code'] == 0
    assert observations[2]['reported_actor_role'] == 'tp-code-reviewer'
    assert 'private-local-path' not in out
    assert 'raw trace not copied' not in out
    new = rows(db, tid)[len(before):]
    facts = [r for r in new if r['event_type'] == 'FACT']
    observed = [r for r in new if r['event_type'] == 'OBSERVATION']
    assert len(facts) == 1 and len(observed) == 3
    assert not any(r['event_type'] in {'VERIFICATION_COMPLETED', 'REVIEW_COMPLETED'} for r in new)
    assert all(r['actor_role'] == 'tp-development-engineer' for r in observed)
    details = [json.loads(r['detail_json']) for r in observed + facts]
    assert len({d['transaction_id'] for d in details}) == 1
    assert len({d['flush_id'] for d in details}) == 1
    assert len({d['cli_invocation_id'] for d in details}) == 1
    assert all('decision' not in d for d in details)
    assert [r['event_id'] for r in observations] == [r['id'] for r in observed]
    assert [json.loads(r['detail_json'])['execution_report'] for r in observed] == [
        {k: v for k, v in r.items() if k != 'event_id'} for r in observations]


def test_real_pytest_report_is_received_without_rerunning_tests(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    case_dir = tmp_path / 'upstream'
    case_dir.mkdir()
    (case_dir / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
    (case_dir / 'test_example.py').write_text(
        'from pathlib import Path\n'
        'def test_pass():\n    Path("executed.txt").write_text("once")\n'
        'def test_fail():\n    assert False, "known upstream failure"\n', encoding='utf-8')
    report = case_dir / 'results.xml'
    proc = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'test_example.py',
                           '--junitxml', str(report)], cwd=case_dir, env=os.environ.copy(),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    stamp = (case_dir / 'executed.txt').stat().st_mtime_ns
    args = _report_args(db, tdir, tid, 'real-report', report)
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    obs = json.loads(out)['result_observations'][0]
    assert obs['reported_result']['tests'] == 2 and obs['reported_result']['failures'] == 1
    assert obs['reported_result']['outcome'] == 'failed'
    assert obs['reported_result']['duration_seconds'] >= 0
    assert obs['exit_code'] is None  # JUnit did not report the actual process exit code.
    original = rows(db, tid)
    report.unlink()  # A response-loss retry relies on accepted copies, not rerunning producers.
    rc, out, err = run_cli(args)
    assert rc == 0 and json.loads(out)['replayed'] is True, (out, err)
    assert rows(db, tid) == original
    assert (case_dir / 'executed.txt').stat().st_mtime_ns == stamp


def test_real_pytest_junit_subtests_and_teardown_failure_are_recorded(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    case = tmp_path / 'pytest9_junit_case.py'
    report = tmp_path / 'pytest9-junit.xml'
    case.write_text(
        'import unittest\n\n'
        'def test_plain_pass():\n    assert True\n\n'
        'class Boundaries(unittest.TestCase):\n'
        '    def test_subtests(self):\n'
        "        with self.subTest(case='pass'):\n            self.assertTrue(True)\n"
        "        with self.subTest(case='fail'):\n            self.assertTrue(False, 'intentional subtest failure')\n\n"
        'def test_teardown_error(request):\n'
        "    request.addfinalizer(lambda: (_ for _ in ()).throw(RuntimeError('intentional teardown error')))\n"
        '    assert True\n',
        encoding='utf-8',
    )
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--junitxml=' + str(report), str(case)],
        cwd=tmp_path, env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
        text=True, capture_output=True, encoding='utf-8', check=False,
    )
    assert completed.returncode == 1, (completed.stdout, completed.stderr)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'pytest9-junit', report))
    assert rc == 0, (out, err)
    received = json.loads(out)['result_observations'][0]['reported_result']
    assert received['tests'] == 5
    assert received['failures'] == 1 and received['errors'] == 1 and received['skipped'] == 0
    assert received['suite_count'] == 1 and received['outcome'] == 'failed'


@pytest.mark.parametrize('name,body,returncode,expected', [
    ('subtests-all-pass',
     'import unittest\n\nclass Cases(unittest.TestCase):\n'
     '    def test_many(self):\n'
     '        for number in range(3):\n'
     '            with self.subTest(number=number):\n'
     '                self.assertEqual(number, number)\n',
     0, {'tests': 4, 'failures': 0, 'errors': 0, 'skipped': 0, 'outcome': 'passed'}),
    ('subtests-all-fail',
     'import unittest\n\nclass Cases(unittest.TestCase):\n'
     '    def test_many(self):\n'
     '        for number in range(3):\n'
     '            with self.subTest(number=number):\n'
     '                self.assertEqual(number, -1)\n',
     1, {'tests': 4, 'failures': 3, 'errors': 0, 'skipped': 0, 'outcome': 'failed'}),
    ('subtests-mixed',
     'import unittest\n\nclass Cases(unittest.TestCase):\n'
     '    def test_many(self):\n'
     '        for number in range(3):\n'
     '            with self.subTest(number=number):\n'
     '                self.assertEqual(number, 1)\n',
     1, {'tests': 4, 'failures': 2, 'errors': 0, 'skipped': 0, 'outcome': 'failed'}),
    ('ordinary-pass-teardown-error',
     'class TestBoundary:\n'
     '    def test_passes(self):\n'
     '        assert True\n\n'
     '    def teardown_method(self):\n'
     "        raise RuntimeError('intentional teardown error')\n",
     1, {'tests': 1, 'failures': 0, 'errors': 1, 'skipped': 0, 'outcome': 'failed'}),
])
def test_real_pytest_junit_counter_variants_are_received_without_inventing_cases(
        tmp_path, monkeypatch, name, body, returncode, expected):
    import os
    import subprocess
    import sys
    import xml.etree.ElementTree as ET

    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    case = tmp_path / 'test_pytest9_counter.py'
    report = tmp_path / f'{name}.xml'
    case.write_text(body, encoding='utf-8')
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--junitxml=' + str(report), str(case)],
        cwd=tmp_path, env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
        text=True, capture_output=True, encoding='utf-8', check=False,
    )
    assert completed.returncode == returncode, (completed.stdout, completed.stderr)
    root = ET.parse(report).getroot()
    suite = next(iter(root))
    assert root.tag == 'testsuites' and root.get('name') == 'pytest tests'
    assert suite.tag == 'testsuite' and suite.get('name') == 'pytest'
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'pytest9-' + name, report))
    assert rc == 0, (out, err)
    received = json.loads(out)['result_observations'][0]['reported_result']
    assert {key: received[key] for key in expected} == expected


def test_invalid_second_result_does_not_partially_commit_the_batch(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    first = _junit(tmp_path / 'first.xml')
    bad = tmp_path / 'not-a-result.json'
    bad.write_text('{"decision":"PASS","exit_code":0}', encoding='utf-8')
    before = rows(db, tid)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'bad-second', first, bad))
    assert rc != 0 and 'RESULT_REPORT_INVALID' in err, (out, err)
    assert rows(db, tid) == before
    assert first.is_file() and bad.is_file()


def test_report_copy_changed_after_parsing_cannot_commit(tmp_path, monkeypatch):
    from cli import execution_reports
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    source = _junit(tmp_path / 'source.xml')
    read = execution_reports.read_report
    def tamper(task_dir, item, *, task_id):
        result = read(task_dir, item, task_id=task_id)
        (task_dir / item['path']).write_text('replaced after parsing', encoding='utf-8')
        return result
    monkeypatch.setattr(execution_reports, 'read_report', tamper)
    before = rows(db, tid)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'tampered-copy', source))
    assert rc != 0 and 'EVIDENCE_CHANGED_BEFORE_COMMIT' in err, (out, err)
    assert rows(db, tid) == before


def test_batch_observation_insert_failure_rolls_back_all_facts(tmp_path, monkeypatch):
    from cli import record_first
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    source = _junit(tmp_path / 'source.xml')
    before = rows(db, tid)
    render = record_first.projection_cmd.render_projection
    def fail_after_writes(conn, task):
        count = conn.execute("SELECT COUNT(*) FROM task_event WHERE task_id=? AND event_type='OBSERVATION'", (tid,)).fetchone()[0]
        assert count == 1  # Inject after the real observation + summary writer, before commit.
        raise OSError('injected required projection failure')
    monkeypatch.setattr(record_first.projection_cmd, 'render_projection', fail_after_writes)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'rollback-report', source))
    assert rc != 0, (out, err)
    assert rows(db, tid) == before
    monkeypatch.setattr(record_first.projection_cmd, 'render_projection', render)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'rollback-report', source))
    assert rc == 0, (out, err)
    assert len(json.loads(out)['result_observations']) == 1


def test_result_batch_receipt_rejects_deleted_observation(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    args = _report_args(db, tdir, tid, 'missing-observation', _junit(tmp_path / 'report.xml'))
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    observation = json.loads(out)['result_observations'][0]
    # Deliberate corruption is confined to this synthetic DB.
    with dbmod.connect(str(db)) as conn:
        conn.execute('DELETE FROM task_event WHERE id=?', (observation['event_id'],))
        conn.commit()
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc != 0 and 'REQUEST_RECORD_INVALID' in err, (out, err)
    assert rows(db, tid) == before


def test_result_batch_id_is_payload_specific_and_new_id_retains_new_facts(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    first = _junit(tmp_path / 'first.xml')
    second = _junit(tmp_path / 'second.xml')
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'logical-batch', first))
    assert rc == 0, (out, err)
    before = rows(db, tid)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'logical-batch', second))
    assert rc != 0 and 'REQUEST_ID_CONFLICT' in err, (out, err)
    assert rows(db, tid) == before
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'new-run', first))
    assert rc == 0, (out, err)
    assert len([r for r in rows(db, tid) if r['event_type'] == 'OBSERVATION']) == 2


@pytest.mark.parametrize('kind', ['empty', 'skipped', 'failed'])
def test_junit_partial_or_empty_reports_are_never_labeled_passed(tmp_path, monkeypatch, kind):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = _junit(tmp_path / 'result.xml', failures=int(kind == 'failed'), skipped=int(kind == 'skipped'))
    if kind == 'empty':
        path.write_text('<testsuite tests="0" failures="0" errors="0" skipped="0" time="0"/>', encoding='utf-8')
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'outcomes', path))
    assert rc == 0, (out, err)
    assert json.loads(out)['result_observations'][0]['reported_result']['outcome'] == {
        'empty': 'not_run', 'skipped': 'incomplete', 'failed': 'failed'}[kind]


@pytest.mark.parametrize('corruption', [
    'dtd', 'utf16-dtd', 'count', 'root-count', 'status-notrun', 'disabled', 'nonfinite',
    'nested', 'json-duplicate', 'bool-count', 'base-contradiction', 'review-task', 'review-role',
])
def test_result_report_bad_or_ambiguous_input_is_rejected_atomically(tmp_path, monkeypatch, corruption):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = _junit(tmp_path / 'input.xml')
    text = path.read_text(encoding='utf-8')
    if corruption in {'dtd', 'utf16-dtd'}:
        text = '<!DOCTYPE testsuite [<!ENTITY x "expanded">]>' + text
    elif corruption == 'count':
        text = text.replace('tests="1"', 'tests="2"')
    elif corruption == 'root-count':
        text = text.replace('<testsuites>', '<testsuites tests="9">')
    elif corruption == 'status-notrun':
        text = text.replace('<testcase ', '<testcase status="notrun" ')
    elif corruption == 'disabled':
        text = text.replace('<testsuite ', '<testsuite disabled="1" ')
    elif corruption == 'nonfinite':
        text = text.replace('time="0.125"', 'time="NaN"')
    elif corruption == 'nested':
        text = '<testsuite tests="0" failures="0" errors="0" skipped="0" time="0">' + text + '</testsuite>'
    elif corruption in {'json-duplicate', 'bool-count', 'base-contradiction'}:
        _base_report(path)
        data = json.loads(path.read_text(encoding='utf-8'))
        if corruption == 'bool-count':
            data['passed'] = True
        elif corruption == 'base-contradiction':
            data['items'][0]['exit_code'] = 2
        text = json.dumps(data)
        if corruption == 'json-duplicate':
            text = text.replace('"passed": 1', '"passed": 0, "passed": 1')
    else:
        _review_report(path, tid)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['task_id' if corruption == 'review-task' else 'actor_role'] = 'unrelated'
        text = json.dumps(data)
    path.write_bytes(text.encode('utf-16' if corruption == 'utf16-dtd' else 'utf-8'))
    before = rows(db, tid)
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'invalid-result', path))
    assert rc != 0 and 'RESULT_REPORT_INVALID' in err, (out, err)
    assert rows(db, tid) == before


def test_result_report_summary_is_bounded_without_hiding_failure_counts(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = _base_report(tmp_path / 'many-checks.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    data['passed'] = 99
    data['failed'] = 1
    data['items'] = [dict(data['items'][0], name=f'check.{index}') for index in range(100)]
    data['items'][-1].update(status='FAIL', exit_code=1)
    path.write_text(json.dumps(data), encoding='utf-8')
    rc, out, err = run_cli(_report_args(db, tdir, tid, 'compact', path))
    assert rc == 0, (out, err)
    result = json.loads(out)['result_observations'][0]['reported_result']
    assert result['failed'] == 1 and result['check_count'] == 100
    assert len(result['checks']) <= 16 and result['checks_truncated'] is True
    assert any(c['name'] == 'check.99' and c['status'] == 'FAIL' for c in result['checks'])


@pytest.mark.parametrize('field', ['actor_role', 'transaction_id', 'reported_result', 'delete-receipt-list'])
def test_corrupted_batch_observation_or_receipt_is_not_replayed(tmp_path, monkeypatch, field):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    args = _report_args(db, tdir, tid, 'corrupt-batch', _junit(tmp_path / 'source.xml'))
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    item = json.loads(out)['result_observations'][0]
    with dbmod.connect(str(db)) as conn:
        row = conn.execute('SELECT * FROM task_event WHERE id=?', (item['event_id'],)).fetchone()
        detail = json.loads(row['detail_json'])
        if field == 'actor_role':
            conn.execute("UPDATE task_event SET actor_role='human_owner' WHERE id=?", (row['id'],))
        elif field == 'delete-receipt-list':
            fact = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='FACT' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
            payload = json.loads(fact['detail_json'])
            del payload['logical_request']['response']['result_observations']
            conn.execute('UPDATE task_event SET detail_json=? WHERE id=?', (json.dumps(payload), fact['id']))
            conn.execute('DELETE FROM task_event WHERE id=?', (row['id'],))
        else:
            if field == 'transaction_id':
                detail['transaction_id'] = 'wrong-transaction'
            else:
                detail['execution_report']['reported_result']['tests'] = 999
            conn.execute('UPDATE task_event SET detail_json=? WHERE id=?', (json.dumps(detail), row['id']))
        conn.commit()
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc != 0 and 'REQUEST_RECORD_INVALID' in err, (out, err)
    assert rows(db, tid) == before


def test_verify_replay_cannot_promote_technical_to_full_in_corrupted_response(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(cp(db, tdir, tid, 'development'))
    assert rc == 0, (out, err)
    args = task_args(db, tdir, tid, 'verify', '--decision', 'PASS', '--summary', 'only selected check',
        '--scope', 'technical', '--check', 'selected', '--evidence', 'evidence/check.txt', '--request-id', 'bounded-verify')
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    with dbmod.connect(str(db)) as conn:
        row = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
        detail = json.loads(row['detail_json'])
        detail['logical_request']['response']['verification_scope'] = 'full'
        conn.execute('UPDATE task_event SET detail_json=? WHERE id=?', (json.dumps(detail), row['id']))
        conn.commit()
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc != 0 and 'REQUEST_RECORD_INVALID' in err, (out, err)
    assert rows(db, tid) == before


def test_result_report_concurrent_retries_write_one_batch(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import subprocess
    import sys
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    source = _junit(tmp_path / 'once.xml')
    argv = [sys.executable, '-m', 'cli.main', *_report_args(db, tdir, tid, 'concurrent-batch', source)]
    procs = [subprocess.Popen(argv, cwd=Path(__file__).resolve().parents[2], env=os.environ.copy(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8') for _ in range(2)]
    results = []
    try:
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            assert proc.returncode == 0, (out, err)
            results.append(json.loads(out))
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    assert sorted(r['replayed'] for r in results) == [False, True]
    assert results[0]['result_observations'] == results[1]['result_observations']
    assert len([r for r in rows(db, tid) if r['event_type'] == 'OBSERVATION']) == 1


def test_report_acceptance_never_satisfies_formal_review_or_completion(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    # L0 with no acceptance claims may legitimately close without verification;
    # exercise a real pending acceptance, not a stronger invented global gate.
    (tdir / 'acceptance.md').write_text(
        '| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |\n'
        '|---|---|---|---|---|---|---|---|\n'
        '| AC-01 | actual owner acceptance | task.md | L0 | human | | human | PENDING |\n',
        encoding='utf-8')
    args = _report_args(db, tdir, tid, 'external-passes',
        _junit(tmp_path / 'passed.xml'), _review_report(tmp_path / 'review.json', tid))
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    before = rows(db, tid)
    rc, out, err = run_cli(['review', 'record', '--task', tid, '--task-dir', str(tdir),
        '--actor', 'tp-code-reviewer', '--kind', 'CODE', '--decision', 'PASS',
        '--evidence', 'evidence/check.txt', '--db', str(db)])
    assert rc != 0 and 'VERIFICATION_STALE' in err, (out, err)
    assert rows(db, tid) == before
    rc, out, err = run_cli(task_args(db, tdir, tid, 'complete', '--summary', 'must not close'))
    assert rc != 0, (out, err)
    assert rows(db, tid) == before


def test_report_acceptance_and_replay_leave_card_untouched(tmp_path, monkeypatch):
    import sys
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    card = project / '.tp-spec/card/index.html'
    card.parent.mkdir(parents=True)
    card.write_text('previous explicit card', encoding='utf-8')
    before = (card.read_bytes(), card.stat().st_mtime_ns)
    args = _report_args(db, tdir, tid, 'without-cards', _junit(tmp_path / 'run.xml'))
    calls = []
    def observe(frame, event, _arg):
        if (event == 'call' and '/cli/cards/' in frame.f_code.co_filename.replace('\\', '/')
                and frame.f_code.co_name != 'add_card_subparsers'):
            # Parser registration is not snapshot/render/display execution.
            calls.append(frame.f_code.co_name)
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        for _ in range(2):
            rc, out, err = run_cli(args)
            assert rc == 0, (out, err)
            assert json.loads(out)['facts_committed'] is True
            assert 'CARD_DISPLAY' not in out + err
    finally:
        sys.setprofile(previous)
    assert calls == []
    assert (card.read_bytes(), card.stat().st_mtime_ns) == before


def test_report_pending_view_recovery_does_not_reingest_or_rerun(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    view = tdir / 'generated/continuation.md'
    view.unlink(missing_ok=True)
    view.mkdir(parents=True)
    args = _report_args(db, tdir, tid, 'view-pending', _junit(tmp_path / 'run.xml'))
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result['facts_committed'] is True and result['view_status'] == 'PENDING'
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc == 0 and json.loads(out)['replayed'] is True, (out, err)
    assert rows(db, tid) == before
    view.rmdir()
    rc, out, err = run_cli(['projection', 'rebuild', '--view-only', '--task', tid,
                          '--task-dir', str(tdir), '--db', str(db)])
    assert rc == 0 and json.loads(out)['view_status'] == 'CURRENT', (out, err)
    assert rows(db, tid) == before


@pytest.mark.parametrize('bad', ['oversized', 'too-many-cases', 'duplicate-path'])
def test_report_resource_bounds_fail_before_any_fact_write(tmp_path, monkeypatch, bad):
    from cli.execution_reports import MAX_REPORT_BYTES, MAX_REPORT_ITEMS
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    path = _junit(tmp_path / 'bounded.xml')
    if bad == 'oversized':
        path.write_bytes(b' ' * (MAX_REPORT_BYTES + 1))
    elif bad == 'too-many-cases':
        path.write_text('<testsuite tests="%d" failures="0" errors="0" skipped="0" time="0">'
                        '%s</testsuite>' % (MAX_REPORT_ITEMS + 1,
                                           '<testcase/>' * (MAX_REPORT_ITEMS + 1)), encoding='utf-8')
    args = _report_args(db, tdir, tid, 'bounded', *([path, path] if bad == 'duplicate-path' else [path]))
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc != 0 and 'RESULT_REPORT_INVALID' in err, (out, err)
    assert rows(db, tid) == before


def test_report_same_subject_new_actor_is_a_new_fact_not_an_independent_review(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    report = _junit(tmp_path / 'same.xml')
    args = _report_args(db, tdir, tid, 'first-actor', report)
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    before = rows(db, tid)
    changed = list(args)
    changed[changed.index('--actor') + 1] = 'tp-test-engineer'
    rc, out, err = run_cli(changed)
    assert rc != 0 and 'REQUEST_ID_CONFLICT' in err, (out, err)
    assert rows(db, tid) == before
    changed[changed.index('--request-id') + 1] = 'second-actor'
    rc, out, err = run_cli(changed)
    assert rc == 0, (out, err)
    observed = [r for r in rows(db, tid) if r['event_type'] == 'OBSERVATION']
    assert [r['actor_role'] for r in observed] == ['tp-development-engineer', 'tp-test-engineer']
    assert all(json.loads(r['detail_json'])['execution_report']['authority'] == 'observation_only' for r in observed)

# B07b: the typed pytest entry observes a child process; existing formal results
# are referenced, never re-signed as the batch submitter's professional judgment.
def _pytest_fixture(tmp_path, monkeypatch, body=None):
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    test = project / 'test_selected.py'
    test.write_text(body or 'def test_selected():\n    assert True\n', encoding='utf-8')
    (tdir / 'evidence/authorization.txt').write_text(
        'Synthetic owner approval: run this selected local fixture, no external effects.', encoding='utf-8')
    rc, out, err = run_cli(cp(db, tdir, tid, 'dev-before-test'))
    assert rc == 0, (out, err)
    return project, db, tdir, tid


def _pytest_args(db, tdir, tid, key='observed-test', *extra):
    return task_args(db, tdir, tid, 'run-pytest', '--test', 'test_selected.py',
                     '--authorization-evidence', 'evidence/authorization.txt',
                     '--request-id', key, '--summary', 'selected fixture execution', *extra)


def test_b07b_pytest_observes_command_result_and_evidence_without_formal_pass(tmp_path, monkeypatch):
    project, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch)
    rc, out, err = run_cli(_pytest_args(db, tdir, tid))
    assert rc == 0, (out, err)
    result = json.loads(out)
    execution = result['execution']
    assert execution['status'] == 'FINISHED' and execution['exit_code'] == 0
    assert execution['duration_ms'] >= 0 and execution['started_at'] <= execution['finished_at']
    assert execution['command'][1:4] == ['-m', 'pytest', '-q']
    assert execution['subject_unchanged'] is True
    assert result['facts_committed'] is True and result['formal_verification_created'] is False
    assert execution['executor']['kind'] == 'local-pytest-process'
    assert type(execution['executor']['pid']) is int
    assert execution['executor']['model'] is None
    assert len(result['collected_artifacts']) >= 3
    assert any(item['format'] == 'junit' for item in result['result_observations'])
    assert not any(row['event_type'] in {'VERIFICATION_COMPLETED', 'REVIEW_COMPLETED'} for row in rows(db, tid))


def test_b07b_pytest_failure_preserves_test_exit_and_records_observation(tmp_path, monkeypatch):
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch, 'def test_selected():\n    assert False\n')
    rc, out, err = run_cli(_pytest_args(db, tdir, tid))
    assert rc == 1, (out, err)
    result = json.loads(out)
    assert result['execution']['exit_code'] == 1 and result['facts_committed']
    assert result['result_observations'][0]['reported_result']['failures'] == 1


def test_b07b_pytest_same_request_does_not_execute_again(tmp_path, monkeypatch):
    body = ('from pathlib import Path\n'
            'def test_selected():\n'
            '    p=Path(".tp-spec/run-count")\n'
            '    p.write_text(str(int(p.read_text())+1) if p.exists() else "1")\n')
    project, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch, body)
    args = _pytest_args(db, tdir, tid)
    rc, out, err = run_cli(args); assert rc == 0, (out, err)
    original = json.loads(out); before = rows(db, tid)
    rc, out, err = run_cli(args); assert rc == 0, (out, err)
    replay = json.loads(out)
    assert replay['replayed'] and replay['execution'] == original['execution']
    assert (project / '.tp-spec/run-count').read_text() == '1'
    assert rows(db, tid) == before
    rc, out, err = run_cli(_pytest_args(db, tdir, tid, 'new-test'))
    assert rc == 0, (out, err)
    assert (project / '.tp-spec/run-count').read_text() == '2'


@pytest.mark.parametrize('problem', ['authorization', 'outside', 'stale', 'blocked', 'terminal'])
def test_b07b_pytest_preflight_blocks_before_test_effect(tmp_path, monkeypatch, problem):
    project, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch,
        'from pathlib import Path\ndef test_selected():\n    Path(".tp-spec/ran").touch()\n')
    args = _pytest_args(db, tdir, tid)
    if problem == 'authorization':
        (tdir/'evidence/authorization.txt').unlink()
    elif problem == 'outside':
        args[args.index('--test') + 1] = '../outside.py'
    elif problem == 'stale':
        (project / 'README.md').write_text('changed after development')
    elif problem == 'blocked':
        rc, out, err = run_cli(task_args(db, tdir, tid, 'block', '--actor', 'human_owner', '--reason', 'waiting'))
        assert rc == 0, (out, err)
    else:
        rc, out, err = run_cli(task_args(db, tdir, tid, 'cancel', '--actor', 'human_owner', '--reason', 'stop'))
        assert rc == 0, (out, err)
    before = rows(db, tid)
    rc, _, err = run_cli(args)
    assert rc != 0 and 'ERROR' in err, err
    assert not (project / '.tp-spec/ran').exists()
    assert rows(db, tid) == before


def _formal_source_ids(db, tdir, tid):
    rc, out, err = run_cli(cp(db, tdir, tid, 'batch-development'))
    assert rc == 0, (out, err)
    dev = rows(db, tid)[-1]['id']
    rc, out, err = run_cli(task_args(db, tdir, tid, 'verify', '--decision', 'PASS',
        '--summary', 'real fixture check', '--scope', 'technical', '--check', 'fixture',
        '--evidence', 'evidence/check.txt'))
    assert rc == 0, (out, err)
    verify = rows(db, tid)[-1]['id']
    (tdir/'evidence/reviewer.txt').write_text('Synthetic isolated CODE review evidence; no human acceptance.', encoding='utf-8')
    rc, out, err = run_cli(['review','record','--task',tid,'--task-dir',str(tdir),'--db',str(db),
        '--actor','tp-code-reviewer','--kind','CODE','--decision','PASS','--evidence','evidence/reviewer.txt'])
    assert rc == 0, (out, err)
    review = rows(db, tid)[-1]['id']
    return [dev, verify, review]


def test_b07b_batch_references_preserve_actors_scope_and_original_events(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    ids = _formal_source_ids(db, tdir, tid)
    before = rows(db, tid)
    args = task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-software-lifecycle', '--phase', 'other',
        '--summary', 'one result handoff', '--request-id', 'formal-batch',
        *[part for event in ids for part in ('--recorded-result', str(event))])
    rc, out, err = run_cli(args); assert rc == 0, (out, err)
    result = json.loads(out)
    assert [ref['actor'] for ref in result['recorded_results']] == ['tp-development-engineer','tp-test-engineer','tp-code-reviewer']
    assert result['recorded_results'][1]['verification_scope'] == 'technical'
    assert all(ref['authority'] == 'original_event_only' for ref in result['recorded_results'])
    after = rows(db, tid)
    assert after[:len(before)] == before and len(after) == len(before)+1
    rc, out, err = run_cli(args)
    assert rc == 0 and json.loads(out)['replayed'], (out, err)
    assert rows(db, tid) == after


def test_b07b_batch_rejects_untrusted_fact_or_tampered_review_evidence_atomically(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    ids = _formal_source_ids(db, tdir, tid)
    (tdir/'evidence/reviewer.txt').write_text('changed without new review', encoding='utf-8')
    before = rows(db, tid)
    args = task_args(db, tdir, tid, 'checkpoint','--actor','tp-software-lifecycle','--phase','other',
        '--summary','batch','--recorded-result', str(ids[-1]))
    rc, out, err = run_cli(args)
    assert rc != 0 and 'RECORDED_RESULT' in err, (out, err)
    assert rows(db, tid) == before


def test_b07b_execution_receipt_tampering_cannot_replace_a_recorded_failure(tmp_path, monkeypatch):
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch, 'def test_selected():\n    assert False\n')
    args = _pytest_args(db, tdir, tid)
    rc, out, err = run_cli(args); assert rc == 1, (out, err)
    response = json.loads(out)
    path = tdir / response['execution_receipt']
    value = json.loads(path.read_text())
    value['execution']['exit_code'] = value['execution']['command_exit_code'] = 0
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True)+'\n', encoding='utf-8')
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc != 0 and 'EXECUTION_RECEIPT' in err, (out, err)
    assert rows(db, tid) == before


def test_b07b_execution_registration_failure_after_commit_reports_committed(tmp_path, monkeypatch):
    from cli import record_first
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch)
    original = record_first.checkpoint
    def lost_response(**kwargs):
        result = original(**kwargs)
        if kwargs.get('phase') == 'verification':
            raise OSError('simulated response lost after transaction commit')
        return result
    monkeypatch.setattr(record_first, 'checkpoint', lost_response)
    rc, out, err = run_cli(_pytest_args(db, tdir, tid))
    result = json.loads(out)
    assert result['facts_committed'] is True, (out, err)
    assert result['execution']['exit_code'] == 0
    assert len([row for row in rows(db, tid) if row['event_type'] == 'FACT']) == 2


def test_b07b_execution_keeps_original_authorization_evidence_copy(tmp_path, monkeypatch):
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch)
    raw = (tdir/'evidence/authorization.txt').read_bytes()
    rc, out, err = run_cli(_pytest_args(db, tdir, tid)); assert rc == 0, (out, err)
    result = json.loads(out)
    assert any((tdir/item['path']).read_bytes() == raw for item in result['collected_artifacts'])


def test_b07b_finished_execution_survives_pending_registration_without_rerun(tmp_path, monkeypatch):
    from cli import record_first
    project, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch,
        'from pathlib import Path\ndef test_selected():\n    p=Path(".tp-spec/count")\n    p.write_text(str(int(p.read_text())+1) if p.exists() else "1")\n')
    original = record_first.checkpoint
    with monkeypatch.context() as patch:
        def fail(**kwargs):
            raise OSError('simulated database failure before commit')
        patch.setattr(record_first, 'checkpoint', fail)
        rc, out, err = run_cli(_pytest_args(db, tdir, tid))
        response = json.loads(out)
        assert rc != 0 and response['facts_committed'] is False
        assert response['execution']['exit_code'] == 0
    rc, out, err = run_cli(_pytest_args(db, tdir, tid)); assert rc == 0, (out, err)
    assert json.loads(out)['facts_committed'] is True
    assert (project/'.tp-spec/count').read_text() == '1'


def test_b07b_timeout_is_not_pass_and_same_request_does_not_run_again(tmp_path, monkeypatch):
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch, 'import time\ndef test_selected():\n    time.sleep(5)\n')
    args = _pytest_args(db, tdir, tid, 'timeout', '--timeout', '0.2')
    rc, out, err = run_cli(args)
    response = json.loads(out)
    assert rc == 124 and response['execution']['status'] == 'TIMED_OUT'
    assert response['facts_committed'] and not response['formal_verification_created']
    before = rows(db, tid)
    rc, out, err = run_cli(args)
    assert rc == 124 and json.loads(out)['execution'] == response['execution']
    assert rows(db, tid) == before


def test_b07b_reserved_incomplete_execution_is_never_restarted(tmp_path, monkeypatch):
    from cli import pytest_execution
    project, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch,
        'from pathlib import Path\ndef test_selected():\n    Path(".tp-spec/ran").touch()\n')
    original = pytest_execution._new_json
    with monkeypatch.context() as patch:
        def stop_after_reservation(path, value):
            original(path, value)
            if path.name == 'started.json':
                raise OSError('simulated controller interruption')
        patch.setattr(pytest_execution, '_new_json', stop_after_reservation)
        rc, out, err = run_cli(_pytest_args(db, tdir, tid))
        assert rc != 0
    rc, out, err = run_cli(_pytest_args(db, tdir, tid))
    assert rc != 0 and 'EXECUTION_INCOMPLETE' in err, (out, err)
    assert not (project/'.tp-spec/ran').exists()


def test_b07b_conflicting_retry_does_not_launch_another_test(tmp_path, monkeypatch):
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch)
    args = _pytest_args(db, tdir, tid)
    rc, out, err = run_cli(args); assert rc == 0, (out, err)
    before = rows(db, tid)
    args[args.index('--summary')+1] = 'different request meaning'
    rc, out, err = run_cli(args)
    assert rc != 0 and 'REQUEST_ID_CONFLICT' in err
    assert rows(db, tid) == before


def test_b07b_product_change_during_execution_remains_observation_only(tmp_path, monkeypatch):
    _, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch,
        'from pathlib import Path\ndef test_selected():\n    Path("app.txt").write_text("modified")\n')
    rc, out, err = run_cli(_pytest_args(db, tdir, tid)); assert rc == 0, (out, err)
    assert json.loads(out)['execution']['subject_unchanged'] is False
    rc, out, err = run_cli(task_args(db,tdir,tid,'verify','--decision','PASS','--summary','attempt old subject','--evidence','evidence/check.txt'))
    assert rc != 0 and 'DEVELOPMENT_CHANGE_SET_STALE' in err


def test_b07b_recorded_result_public_fact_is_not_a_formal_result(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = run_cli(['event','add','--task',tid,'--type','FACT','--actor','tp-code-reviewer',
        '--note','PASS in prose is not independent review','--db',str(db)])
    assert rc == 0, (out, err)
    before = rows(db, tid)
    rc, out, err = run_cli(task_args(db,tdir,tid,'checkpoint','--actor','tp-software-lifecycle','--phase','other',
        '--summary','reference','--recorded-result',str(before[-1]['id'])))
    assert rc != 0 and 'RECORDED_RESULT_INVALID' in err
    assert rows(db,tid) == before


def test_b07b_recorded_result_retry_detects_deleted_reference_list(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    ids = _formal_source_ids(db,tdir,tid)
    args = task_args(db,tdir,tid,'checkpoint','--actor','tp-software-lifecycle','--phase','other',
        '--summary','refs','--recorded-result',str(ids[1]),'--request-id','refs-one')
    rc,out,err = run_cli(args); assert rc == 0,(out,err)
    with dbmod.connect(str(db)) as conn:
        row = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
        detail = json.loads(row['detail_json'])
        detail['recorded_results'] = []
        detail['logical_request']['response']['recorded_results'] = []
        conn.execute('UPDATE task_event SET detail_json=? WHERE id=?',(json.dumps(detail),row['id'])); conn.commit()
    rc,out,err = run_cli(args)
    assert rc != 0 and 'REQUEST_RECORD_INVALID' in err,(out,err)


def test_b07b_retry_response_cannot_substitute_different_collected_artifacts(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    source = tmp_path/'collected.txt'; source.write_text('original evidence', encoding='utf-8')
    args = cp(db, tdir, tid, 'copied-output', 'collected', '--collect', str(source))
    rc,out,err = run_cli(args); assert rc == 0,(out,err)
    with dbmod.connect(str(db)) as conn:
        row = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
        detail = json.loads(row['detail_json'])
        detail['logical_request']['response']['collected_artifacts'][0]['sha256'] = '0'*64
        conn.execute('UPDATE task_event SET detail_json=? WHERE id=?',(json.dumps(detail),row['id'])); conn.commit()
    rc,out,err = run_cli(args)
    assert rc != 0 and 'REQUEST_RECORD_INVALID' in err,(out,err)


def test_b07b_concurrent_real_cli_executes_selected_test_at_most_once(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from pathlib import Path
    project, db, tdir, tid = _pytest_fixture(tmp_path, monkeypatch,
        'from pathlib import Path\nimport time\ndef test_selected():\n'
        '    with Path(".tp-spec/executed").open("a") as f: f.write("once\\n")\n'
        '    time.sleep(0.1)\n')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    args = [sys.executable,'-m','cli.main',*_pytest_args(db,tdir,tid,'concurrent')]
    processes = [subprocess.Popen(args,cwd=project,env=env,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,text=True,encoding='utf-8') for _ in range(2)]
    try:
        outputs = [p.communicate(timeout=40) for p in processes]
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill(); p.wait()
    assert any(p.returncode == 0 for p in processes),outputs
    assert (project/'.tp-spec/executed').read_text() == 'once\n'
    for p,(out,err) in zip(processes,outputs):
        if p.returncode:
            assert any(code in err for code in ('EXECUTION_IN_PROGRESS','EXECUTION_INCOMPLETE','EXECUTION_RECEIPT_INVALID')), (out,err)
    observed = [row for row in rows(db,tid) if row['event_type']=='OBSERVATION']
    assert len(observed) == 1
    rc,out,err = run_cli(_pytest_args(db,tdir,tid,'concurrent'))
    assert rc == 0 and json.loads(out)['replayed'],(out,err)
    assert (project/'.tp-spec/executed').read_text() == 'once\n'


def test_b07b_runner_does_not_enter_card_chain_or_rewrite_old_html(tmp_path, monkeypatch):
    from cli.cards import snapshot, render
    project,db,tdir,tid = _pytest_fixture(tmp_path,monkeypatch)
    card=tdir/'evidence/old-card.html'; card.write_text('<html>old user card</html>',encoding='utf-8')
    before=(card.read_bytes(),card.stat().st_mtime_ns)
    def forbidden(*args,**kwargs):
        raise AssertionError('ordinary execution entered card generation')
    # A call raises, rather than replacing a real refresh with a successful no-op.
    for module in (snapshot,render):
        for name in dir(module):
            if (name.startswith(('build_','render_')) and callable(getattr(module,name))):
                monkeypatch.setattr(module,name,forbidden)
    rc,out,err = run_cli(_pytest_args(db,tdir,tid,'no-card')); assert rc == 0,(out,err)
    assert (card.read_bytes(),card.stat().st_mtime_ns)==before
    assert 'Card' not in out


@pytest.mark.parametrize('issue',['timeout','directory','duplicate','receipt-missing','log-change'])
def test_b07b_invalid_execution_or_retry_never_launches_extra_work(tmp_path,monkeypatch,issue):
    project,db,tdir,tid = _pytest_fixture(tmp_path,monkeypatch,
        'from pathlib import Path\ndef test_selected():\n'
        '    with Path(".tp-spec/executed").open("a") as f: f.write("once\\n")\n')
    args=_pytest_args(db,tdir,tid)
    if issue=='timeout':
        args += ['--timeout','nan']
    elif issue=='directory':
        args[args.index('--test')+1]='.'
    elif issue=='duplicate':
        args += ['--test','test_selected.py']
    else:
        rc,out,err=run_cli(args); assert rc==0,(out,err)
        completed=tdir/json.loads(out)['execution_receipt']
        if issue=='receipt-missing':
            completed.unlink()
        else:
            (completed.parent/'output.log').write_text('replaced output',encoding='utf-8')
    before=rows(db,tid)
    rc,out,err=run_cli(args)
    assert rc!=0,(out,err)
    assert rows(db,tid)==before
    assert (project/'.tp-spec/executed').exists()==(issue in {'receipt-missing','log-change'})
    if issue in {'receipt-missing','log-change'}:
        assert (project/'.tp-spec/executed').read_text()=='once\n'


def test_b07b_recorded_result_changed_at_write_boundary_rolls_back_batch(tmp_path,monkeypatch):
    from cli import recording
    _,db,tdir,tid=make_runtime(tmp_path,monkeypatch)
    ids=_formal_source_ids(db,tdir,tid)
    original=recording.recorded_results
    def changed_after_precheck(conn, task_id, task_dir, event_ids):
        value=original(conn,task_id,task_dir,event_ids)
        (tdir/'evidence/reviewer.txt').write_text('changed after precheck',encoding='utf-8')
        return value
    monkeypatch.setattr(recording,'recorded_results',changed_after_precheck)
    before=rows(db,tid)
    rc,out,err=run_cli(task_args(db,tdir,tid,'checkpoint','--actor','tp-software-lifecycle','--phase','other',
        '--summary','no partial reference','--recorded-result',str(ids[-1])))
    assert rc!=0 and 'RECORDED_RESULT' in err,(out,err)
    assert rows(db,tid)==before


@pytest.mark.parametrize('ids',[['0'],['9999999'],['1','1']])
def test_b07b_invalid_recorded_results_do_not_create_partial_batch(tmp_path,monkeypatch,ids):
    _,db,tdir,tid=make_runtime(tmp_path,monkeypatch)
    before=rows(db,tid)
    rc,out,err=run_cli(task_args(db,tdir,tid,'checkpoint','--actor','tp-software-lifecycle','--phase','other',
        '--summary','invalid references',*[part for item in ids for part in ('--recorded-result',item)]))
    assert rc!=0 and 'RECORDED_RESULT' in err,(out,err)
    assert rows(db,tid)==before


def test_b07b_execution_metadata_distinguishes_reservation_from_process_start(tmp_path,monkeypatch):
    import importlib.metadata
    _,db,tdir,tid=_pytest_fixture(tmp_path,monkeypatch)
    rc,out,err=run_cli(_pytest_args(db,tdir,tid)); assert rc==0,(out,err)
    result=json.loads(out); completed=tdir/result['execution_receipt']
    started=json.loads((completed.parent/'started.json').read_text(encoding='utf-8'))
    execution=result['execution']
    assert started['prepared_at']<=execution['started_at']<=execution['finished_at']
    assert execution['prepared_at']==started['prepared_at']
    assert execution['installed_pytest_version']==importlib.metadata.version('pytest')
    assert 'not proof of child import resolution' in execution['tool_version_source']


def test_b07b_spawn_failure_does_not_invent_test_exit_or_retry_execution(tmp_path,monkeypatch):
    from cli import pytest_execution
    _,db,tdir,tid=_pytest_fixture(tmp_path,monkeypatch)
    original=pytest_execution.subprocess.Popen
    def unavailable(command,*args,**kwargs):
        if isinstance(command,list) and command[1:3]==['-m','pytest']:
            raise OSError('isolated process launch failure')
        return original(command,*args,**kwargs)
    monkeypatch.setattr(pytest_execution.subprocess,'Popen',unavailable)
    args=_pytest_args(db,tdir,tid)
    rc,out,err=run_cli(args); assert rc==127,(out,err)
    result=json.loads(out)
    assert result['execution']['exit_code'] is None
    assert result['execution']['executor']['pid'] is None
    assert result['execution']['status']=='NOT_STARTED' and result['facts_committed']
    before=rows(db,tid)
    rc,out,err=run_cli(args)
    assert rc==127 and json.loads(out)['replayed'],(out,err)
    assert rows(db,tid)==before


def test_b07b_derived_view_failure_does_not_rerun_completed_pytest(tmp_path,monkeypatch):
    from cli import transaction_commit
    project,db,tdir,tid=_pytest_fixture(tmp_path,monkeypatch,
        'from pathlib import Path\ndef test_selected():\n'
        '    with Path(".tp-spec/executed").open("a") as f: f.write("once\\n")\n')
    def broken(*args,**kwargs):
        raise OSError('isolated derived view failure')
    monkeypatch.setattr(transaction_commit,'_rebuild_current_view_text',broken)
    args=_pytest_args(db,tdir,tid)
    rc,out,err=run_cli(args); assert rc==0,(out,err)
    result=json.loads(out)
    assert result['facts_committed'] and result['view_status']=='PENDING'
    before=rows(db,tid)
    rc,out,err=run_cli(args); assert rc==0,(out,err)
    assert json.loads(out)['view_status']=='NOT_REFRESHED'
    assert rows(db,tid)==before and (project/'.tp-spec/executed').read_text()=='once\n'


def test_b07b_test_path_aliases_do_not_schedule_duplicate_execution(tmp_path,monkeypatch):
    project,db,tdir,tid=_pytest_fixture(tmp_path,monkeypatch,
        'from pathlib import Path\ndef test_selected():\n    Path(".tp-spec/executed").touch()\n')
    args=_pytest_args(db,tdir,tid,'alias','--test','./test_selected.py')
    before=rows(db,tid)
    rc,out,err=run_cli(args)
    assert rc!=0 and 'PYTEST_SELECTION_INVALID' in err,(out,err)
    assert not (project/'.tp-spec/executed').exists() and rows(db,tid)==before
