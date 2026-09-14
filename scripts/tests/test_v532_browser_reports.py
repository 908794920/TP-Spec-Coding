"""Public upstream JSON mapping and opt-in local attachment custody, not browser QA."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from cli.execution_reports import read_report
from scripts.tests.test_v532_recording import cp, rows
from scripts.tests.v532_testutil import make_runtime, run_cli


def playwright_report(*, status='expected', expected='passed', attempts=None, attachments=None):
    if attempts is None:
        attempts = ['passed']
    tests = [{
        'timeout': 30000, 'annotations': [], 'expectedStatus': expected,
        'projectName': 'secret-project-name', 'projectId': 'project-1', 'status': status,
        'results': [{
            'workerIndex': 0, 'parallelIndex': 0, 'status': state, 'duration': 5,
            'errors': [{'message': 'SECRET-error'}] if state in {'failed', 'timedOut'} else [],
            'stdout': [{'text': 'SECRET-stdout'}], 'stderr': [], 'retry': n,
            'startTime': '2026-09-08T07:00:00.000Z',
            'attachments': attachments or [],
        } for n, state in enumerate(attempts)],
    }]
    return {'config': {'version': '1.63.0', 'metadata': {'token': 'SECRET-metadata'}, 'projects': []},
            'suites': [{'title': 'SECRET-suite', 'file': 'e2e/flow.spec.ts', 'line': 0, 'column': 0,
                        'specs': [{'id': 'spec-1', 'title': 'SECRET-title', 'file': 'e2e/flow.spec.ts',
                                   'line': 1, 'column': 1, 'ok': status != 'unexpected', 'tags': [], 'tests': tests}]}],
            'errors': [], 'stats': {'startTime': '2026-09-08T07:00:00.000Z', 'duration': 20,
                                   **{k: int(k == status) for k in ('expected', 'unexpected', 'flaky', 'skipped')}}}


def write_report(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def parse_at(tmp_path, data):
    path = write_report(tmp_path / 'evidence/result.json', data)
    return read_report(tmp_path, {'type': 'local_file', 'path': 'evidence/result.json',
                                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, task_id='TASK-SAMPLE')


def test_native_playwright_json_is_observation_not_visual_or_deployment_proof(tmp_path):
    observed = parse_at(tmp_path, playwright_report())
    assert observed['format'] == 'playwright-json'
    assert observed['authority'] == 'observation_only'
    assert observed['execution_observed_by_cli'] is False
    assert observed['exit_code'] is None and observed['command'] is None
    result = observed['reported_result']
    assert result['tests'] == 1 and result['outcome'] == 'passed'
    assert result['duration_ms'] == 20
    assert observed['visual_review'] == 'not_inferred'
    assert observed['deployment_binding'] == 'unverified'
    assert 'SECRET' not in json.dumps(observed) and 'secret-project' not in json.dumps(observed)


@pytest.mark.parametrize('status,expected,attempts,outcome', [
    ('skipped', 'skipped', ['skipped'], 'incomplete'),
    ('skipped', 'passed', [], 'incomplete'),
    ('expected', 'failed', ['failed'], 'incomplete'),
    ('flaky', 'passed', ['failed', 'passed'], 'incomplete'),
    ('unexpected', 'passed', ['failed'], 'failed'),
    ('unexpected', 'passed', ['timedOut'], 'failed'),
    ('skipped', 'passed', ['interrupted'], 'incomplete'),
])
def test_native_nonpassing_or_partial_outcomes_never_flatten_to_pass(tmp_path, status, expected, attempts, outcome):
    observed = parse_at(tmp_path, playwright_report(status=status, expected=expected, attempts=attempts))
    assert observed['reported_result']['outcome'] == outcome
    assert observed['reported_result']['cases'][0]['attempt_count'] == len(attempts)


def test_native_global_error_and_empty_run_remain_visible(tmp_path):
    data = playwright_report()
    data['suites'] = []
    data['stats']['expected'] = 0
    assert parse_at(tmp_path, data)['reported_result']['outcome'] == 'not_run'
    data['errors'] = [{'message': 'SECRET worker crashed'}]
    observed = parse_at(tmp_path, data)
    assert observed['reported_result']['outcome'] == 'failed'
    assert observed['reported_result']['global_error_count'] == 1
    assert 'SECRET' not in json.dumps(observed)


@pytest.mark.parametrize('change', ['count', 'boolean', 'nan', 'status', 'attempt', 'expected', 'date', 'error-shape', 'version'])
def test_native_malformed_report_is_rejected(tmp_path, change):
    data = playwright_report()
    test = data['suites'][0]['specs'][0]['tests'][0]
    if change == 'count': data['stats']['expected'] = 2
    elif change == 'boolean': data['stats']['expected'] = True
    elif change == 'nan': data['stats']['duration'] = float('nan')
    elif change == 'status': test['status'] = 'PASS'
    elif change == 'attempt': test['results'][0]['status'] = 'PASS'
    elif change == 'expected': test['results'][0]['status'] = 'failed'
    elif change == 'date': data['stats']['startTime'] = 'yesterday'
    elif change == 'error-shape': data['errors'] = 'no errors'
    elif change == 'version': data['config']['version'] = 'latest'
    with pytest.raises(ValueError, match='RESULT_REPORT_INVALID'):
        parse_at(tmp_path, data)


def test_native_nested_suites_repeats_and_preview_preserve_full_counts(tmp_path):
    data = playwright_report()
    spec = data['suites'][0]['specs'][0]
    original = copy.deepcopy(spec)
    data['suites'][0]['specs'] = []
    data['suites'][0]['suites'] = [{'title': 'nested', 'file': 'flow.spec.ts', 'line': 2, 'column': 1,
                                  'specs': [copy.deepcopy(original) for _ in range(30)]}]
    data['stats']['expected'] = 30
    observed = parse_at(tmp_path, data)
    assert observed['reported_result']['tests'] == 30
    assert observed['reported_result']['cases_truncated'] is True
    assert len(observed['reported_result']['cases']) <= 16


def test_default_import_does_not_open_declared_attachments(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    missing = tmp_path / 'must-not-read.png'
    source = write_report(tmp_path/'report.json', playwright_report(attachments=[
        {'name': 'SECRET', 'contentType': 'image/png', 'path': str(missing)}]))
    rc, out, err = run_cli(cp(db, tdir, tid, 'native-default', 'observed only', '--result-report', str(source)))
    assert rc == 0, (out, err)
    observed = json.loads(out)['result_observations'][0]
    assert observed['reported_result']['file_attachment_count'] == 1
    assert 'attachment_evidence' not in observed
    assert not missing.exists()
    assert not any(r['event_type'] in {'VERIFICATION_COMPLETED', 'REVIEW_COMPLETED'} for r in rows(db, tid))


def test_scoped_native_attachments_are_bound_once_and_replayed_without_source(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    assets = tmp_path/'outputs'; assets.mkdir()
    image = assets/'normal.png'; image.write_bytes(b'fixture image bytes, not visual proof')
    html = assets/'midscene.html'; html.write_bytes(b'<html>fixture only</html>')
    source = write_report(tmp_path/'report.json', playwright_report(attachments=[
        {'name':'SECRET-image', 'contentType':'image/png', 'path':str(image)},
        {'name':'SECRET-midscene', 'contentType':'text/html', 'path':'midscene.html'},
        {'name':'SECRET-inline', 'contentType':'text/plain', 'body':'U0VDUkVU'},
    ]))
    args = cp(db, tdir, tid, 'browser-batch', 'selected browser result', '--result-report', str(source),
              '--report-artifact-root', str(assets))
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    result = json.loads(out)
    observed = result['result_observations'][0]
    assert len(observed['attachment_evidence']) == 2
    assert observed['reported_result']['inline_attachment_count'] == 1
    for item in observed['attachment_evidence']:
        p = tdir/item['path']; assert hashlib.sha256(p.read_bytes()).hexdigest() == item['sha256']
    assert 'SECRET' not in out
    before = rows(db, tid)
    image.unlink(); html.unlink(); source.unlink(); assets.rmdir()
    rc, out, err = run_cli(args)
    assert rc == 0 and json.loads(out)['replayed'], (out, err)
    assert rows(db, tid) == before
    (tdir/observed['attachment_evidence'][0]['path']).write_bytes(b'changed')
    rc, out, err = run_cli(args)
    assert rc != 0 and 'REQUEST_EVIDENCE_CHANGED' in err
    assert rows(db, tid) == before


def test_concurrent_attachment_collection_binds_one_attempt_and_replays_without_sources(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    assets = tmp_path / 'outputs'
    assets.mkdir()
    image = assets / 'normal.png'
    image.write_bytes(b'concurrent fixture image bytes')
    report = write_report(tmp_path / 'report.json', playwright_report(attachments=[
        {'name': 'image', 'contentType': 'image/png', 'path': str(image)},
    ]))
    args = cp(db, tdir, tid, 'concurrent-browser-batch', 'same logical browser result',
              '--result-report', str(report), '--report-artifact-root', str(assets))
    base = Path(__file__).resolve().parents[2]
    processes = [subprocess.Popen([sys.executable, '-m', 'cli.main', *args], cwd=base,
                                  env=os.environ.copy(), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding='utf-8')
                 for _ in range(4)]
    responses = []
    try:
        for process in processes:
            out, err = process.communicate(timeout=45)
            assert process.returncode == 0, (out, err)
            responses.append(json.loads(out))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert sum(not item['replayed'] for item in responses) == 1
    assert len({item['flush_id'] for item in responses}) == 1
    winning = next(item for item in responses if not item['replayed'])
    attachment = winning['result_observations'][0]['attachment_evidence'][0]
    bound = tdir / attachment['path']
    assert bound.is_file()
    assert bound.parent.name.startswith('a-')
    assert hashlib.sha256(bound.read_bytes()).hexdigest() == attachment['sha256']

    image.unlink()
    report.unlink()
    rc, out, err = run_cli(args)
    assert rc == 0 and json.loads(out)['replayed'], (out, err)


@pytest.mark.parametrize('bad', ['escape','absolute','url','symlink','missing','secret-file','root-symlink'])
def test_scoped_attachment_rejects_unsafe_sources_without_partial_facts(tmp_path, monkeypatch, bad):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    root = tmp_path/'outputs'; root.mkdir()
    outside = tmp_path/'outside.png'; outside.write_bytes(b'outside')
    path = '../outside.png'; content_type = 'image/png'
    if bad == 'absolute': path = str(outside)
    elif bad == 'url': path = 'https://invalid.example/test.png'
    elif bad == 'missing': path = 'missing.png'
    elif bad == 'secret-file':
        (root/'storageState.json').write_text('{"cookies":["SECRET"]}')
        path='storageState.json';content_type='application/json'
    elif bad in {'symlink','root-symlink'}:
        try:
            if bad == 'symlink': (root/'linked.png').symlink_to(outside); path='linked.png'
            else:
                (root/'normal.png').write_bytes(b'image'); alias=tmp_path/'root-link'; alias.symlink_to(root, target_is_directory=True); root=alias; path='normal.png'
        except OSError:
            pytest.skip('symlink unavailable')
    source=write_report(tmp_path/'report.json',playwright_report(attachments=[{'name':'bad','contentType':content_type,'path':path}]))
    before=rows(db,tid)
    rc,out,err=run_cli(cp(db,tdir,tid,'bad-attachment','outputs','--result-report',str(source),'--report-artifact-root',str(root)))
    assert rc != 0 and 'BROWSER_ARTIFACT' in err, (out,err)
    assert rows(db,tid)==before and outside.read_bytes()==b'outside'


def test_browser_root_requires_a_native_report_and_is_part_of_request_identity(tmp_path, monkeypatch):
    _,db,tdir,tid=make_runtime(tmp_path,monkeypatch)
    root=tmp_path/'outputs';root.mkdir()
    rc,out,err=run_cli(cp(db,tdir,tid,'missing-report','outputs','--report-artifact-root',str(root)))
    assert rc!=0 and 'RESULT_REPORT_REQUIRED' in err
    source=write_report(tmp_path/'report.json',playwright_report())
    args=cp(db,tdir,tid,'root-identity','outputs','--result-report',str(source),'--report-artifact-root',str(root))
    rc,out,err=run_cli(args); assert rc==0,(out,err)
    other=tmp_path/'other';other.mkdir()
    changed=list(args); changed[changed.index('--report-artifact-root')+1]=str(other)
    rc,out,err=run_cli(changed)
    assert rc!=0 and 'REQUEST_ID_CONFLICT' in err


def test_two_equal_reports_remain_two_independent_observations(tmp_path, monkeypatch):
    _,db,tdir,tid=make_runtime(tmp_path,monkeypatch)
    root=tmp_path/'outputs';root.mkdir();(root/'a.png').write_bytes(b'image')
    data=playwright_report(attachments=[{'name':'picture','contentType':'image/png','path':'a.png'}])
    first=write_report(tmp_path/'first.json',data);second=write_report(tmp_path/'second.json',data)
    args=cp(db,tdir,tid,'equal-reports','two source reports','--result-report',str(first),'--result-report',str(second),'--report-artifact-root',str(root))
    rc,out,err=run_cli(args);assert rc==0,(out,err)
    obs=json.loads(out)['result_observations'];assert len(obs)==2
    assert len(obs[0]['attachment_evidence'])==len(obs[1]['attachment_evidence'])==1
    rc,out,err=run_cli(args);assert rc==0 and json.loads(out)['replayed'],(out,err)


def test_native_passed_attempt_with_errors_is_rejected(tmp_path):
    data=playwright_report()
    data['suites'][0]['specs'][0]['tests'][0]['results'][0]['errors']=[{'message':'failure'}]
    with pytest.raises(ValueError,match='RESULT_REPORT_INVALID'):
        parse_at(tmp_path,data)


def test_scoped_attachment_changed_to_link_before_copy_never_reads_outside(tmp_path, monkeypatch):
    from cli import recording
    _,db,tdir,tid=make_runtime(tmp_path,monkeypatch)
    root=tmp_path/'outputs';root.mkdir();image=root/'a.png';image.write_bytes(b'allowed image')
    outside=tmp_path/'outside.png';outside.write_bytes(b'OUTSIDE-SECRET-BYTES')
    report=write_report(tmp_path/'report.json',playwright_report(attachments=[{'name':'image','contentType':'image/png','path':'a.png'}]))
    collect=recording.collect_artifacts
    def swap(task_dir, request_id, sources, **kwargs):
        if request_id.startswith('browser:'):
            image.unlink()
            try: image.symlink_to(outside)
            except OSError: pytest.skip('symlink unavailable')
        return collect(task_dir,request_id,sources,**kwargs)
    monkeypatch.setattr(recording,'collect_artifacts',swap)
    before=rows(db,tid)
    rc,out,err=run_cli(cp(db,tdir,tid,'late-link','outputs','--result-report',str(report),'--report-artifact-root',str(root)))
    assert rc!=0 and 'BROWSER_ARTIFACT' in err,(out,err)
    assert rows(db,tid)==before
    assert all(p.read_bytes()!=b'OUTSIDE-SECRET-BYTES' for p in (tdir/'evidence').rglob('*') if p.is_file())


@pytest.mark.parametrize('failure',['required_projection','optional_projection'])
def test_browser_batch_transaction_and_derived_failure_semantics(tmp_path,monkeypatch,failure):
    from cli import record_first, transaction_commit
    _,db,tdir,tid=make_runtime(tmp_path,monkeypatch)
    root=tmp_path/'outputs';root.mkdir();(root/'a.png').write_bytes(b'image')
    report=write_report(tmp_path/'report.json',playwright_report(attachments=[{'name':'image','contentType':'image/png','path':'a.png'}]))
    args=cp(db,tdir,tid,'projection','outputs','--result-report',str(report),'--report-artifact-root',str(root))
    before=rows(db,tid)
    def fail(*args,**kwargs): raise OSError('injected derived failure')
    if failure=='required_projection': monkeypatch.setattr(record_first.projection_cmd,'render_projection',fail)
    else: monkeypatch.setattr(transaction_commit,'_rebuild_current_view_text',fail)
    rc,out,err=run_cli(args)
    if failure=='required_projection':
        assert rc!=0 and rows(db,tid)==before,(out,err)
    else:
        result=json.loads(out)
        assert rc==0 and result['facts_committed'] and result['view_status']=='PENDING',(out,err)
        committed=rows(db,tid)
        assert len(committed)>len(before)
        rc,out,err=run_cli(args)
        assert rc==0 and json.loads(out)['replayed'] and rows(db,tid)==committed


@pytest.mark.parametrize("first_ok", [True, False])
def test_native_multi_project_spec_ok_is_not_a_merged_verdict(tmp_path, first_ok):
    # Native JSONReporter._mergeTestsFromSuite preserves the first spec.ok
    # when appending other projects' test results; it does not recompute it.
    data = playwright_report()
    spec = data['suites'][0]['specs'][0]
    failed = playwright_report(status='unexpected', attempts=['failed'])['suites'][0]['specs'][0]['tests'][0]
    spec['tests'].append(failed)
    if not first_ok:
        spec['tests'].reverse()
    spec['ok'] = first_ok
    data['stats']['unexpected'] = 1
    result = parse_at(tmp_path, data)['reported_result']
    assert result['tests'] == 2 and result['outcome'] == 'failed'
    assert result['expected'] == result['unexpected'] == 1


def test_source_growth_on_stability_reread_still_obeys_collection_limit(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from cli import recording
    source = tmp_path / 'source.png'; source.write_bytes(b'original')
    task_dir = tmp_path / 'task'; task_dir.mkdir()
    original_open = recording._collection_stream

    @contextmanager
    def changing_stream(path, source_root):
        with original_open(path, source_root) as stream:
            class ChangeOnRewind:
                def __getattr__(self, key): return getattr(stream, key)
                def seek(self, offset):
                    source.write_bytes(b'x' * 17)
                    return stream.seek(offset)
            yield ChangeOnRewind()

    monkeypatch.setattr(recording, '_limits', lambda: (128, 16))
    monkeypatch.setattr(recording, '_collection_stream', changing_stream)
    with pytest.raises(ValueError, match='ARTIFACT_COLLECTION_LIMIT'):
        recording.collect_artifacts(task_dir, 'growth', [str(source)])
    assert not list((task_dir / 'evidence').rglob('*.png'))


def test_collection_accepts_a_ctime_only_path_stat_skew(tmp_path, monkeypatch):
    from cli import recording

    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    original_stat = Path.stat

    class CtimeSkew:
        def __init__(self, value):
            self._value = value

        def __getattr__(self, key):
            return getattr(self._value, key)

        @property
        def st_ctime_ns(self):
            return self._value.st_ctime_ns + 1

    def path_stat(self, *args, **kwargs):
        value = original_stat(self, *args, **kwargs)
        return CtimeSkew(value) if self == source else value

    monkeypatch.setattr(Path, 'stat', path_stat)
    collected = recording.collect_artifacts(task_dir, 'ctime-skew', [str(source)])
    assert [item['source_name'] for item in collected] == ['source.png']


def test_same_logical_request_uses_independent_collection_attempt_directories(tmp_path):
    from cli import recording

    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    first = recording.collect_artifacts(task_dir, 'same-request', [str(source)])
    second = recording.collect_artifacts(task_dir, 'same-request', [str(source)])
    assert first[0]['source_name'] == second[0]['source_name'] == 'source.png'
    assert first[0]['path'] != second[0]['path']
    for item in first + second:
        copied = task_dir / item['path']
        assert copied.read_bytes() == b'stable artifact'
        assert copied.is_relative_to(task_dir / 'evidence' / 'collected')


def test_attempt_name_collision_never_reuses_an_existing_directory(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cli import recording

    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    monkeypatch.setattr(recording.uuid, 'uuid4', lambda: SimpleNamespace(hex='c' * 32))
    first = recording.collect_artifacts(task_dir, 'collision-request', [str(source)])
    with pytest.raises(ValueError, match='ARTIFACT_COLLECTION_ATTEMPT_CONFLICT'):
        recording.collect_artifacts(task_dir, 'collision-request', [str(source)])
    assert (task_dir / first[0]['path']).read_bytes() == b'stable artifact'


@pytest.mark.skipif(os.name != 'nt', reason='Windows rooted-handle failure path')
@pytest.mark.parametrize('failure_point', ['handle', 'fd'])
def test_windows_output_wrapper_failure_removes_unpublished_object(tmp_path, monkeypatch, failure_point):
    from cli import windows_collection

    base = tmp_path / 'task'
    base.mkdir()
    request_key = hashlib.sha256(b'wrapper-failure').hexdigest()[:24]
    attempt_name = 'a-' + ('d' * 12)
    with windows_collection.attempt(base, request_key, attempt_name) as (attempt_dir, attempt_handle):
        if failure_point == 'handle':
            import msvcrt

            def fail_open_osfhandle(*args, **kwargs):
                raise OSError('simulated handle wrapping failure')

            monkeypatch.setattr(msvcrt, 'open_osfhandle', fail_open_osfhandle)
        else:
            def fail_fdopen(*args, **kwargs):
                raise OSError('simulated fd wrapping failure')

            monkeypatch.setattr(windows_collection.os, 'fdopen', fail_fdopen)
        with pytest.raises(OSError, match='simulated .* wrapping failure'):
            with windows_collection.output(attempt_handle, '000.bin'):
                pass
        assert not (attempt_dir / '000.bin').exists()


def test_posix_attempt_collision_uses_collection_conflict_code(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cli import recording

    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    real_os = recording.os
    supports_dir_fd = getattr(real_os, 'supports_dir_fd', ())
    if (real_os.open not in supports_dir_fd or real_os.stat not in supports_dir_fd
            or real_os.rename not in supports_dir_fd or real_os.unlink not in supports_dir_fd
            or not hasattr(real_os, 'O_DIRECTORY') or not hasattr(real_os, 'O_NOFOLLOW')):
        pytest.skip('POSIX directory-handle output is unavailable on this host')

    class PosixOsProxy:
        name = 'posix'

        def __getattr__(self, key):
            return getattr(real_os, key)

    monkeypatch.setattr(recording, 'os', PosixOsProxy())
    monkeypatch.setattr(recording.uuid, 'uuid4', lambda: SimpleNamespace(hex='e' * 32))
    recording.collect_artifacts(task_dir, 'posix-collision-request', [str(source)])
    with pytest.raises(ValueError, match='ARTIFACT_COLLECTION_ATTEMPT_CONFLICT'):
        recording.collect_artifacts(task_dir, 'posix-collision-request', [str(source)])


def test_windows_collection_import_is_safe_without_windows_stdlib(monkeypatch):
    import builtins
    import importlib

    module_name = 'cli.windows_collection'
    previous = sys.modules.pop(module_name, None)
    real_import = builtins.__import__

    def no_msvcrt(name, *args, **kwargs):
        if name == 'msvcrt':
            raise ModuleNotFoundError("No module named 'msvcrt'")
        return real_import(name, *args, **kwargs)

    try:
        monkeypatch.setattr(os, 'name', 'posix')
        monkeypatch.setattr(builtins, '__import__', no_msvcrt)
        module = importlib.import_module(module_name)
        assert module.available() is False
    finally:
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous


def test_collector_rejects_a_parent_replaced_by_link_before_first_write(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from cli import recording

    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    original_stream = recording._collection_stream
    request_id = 'parent-replaced'
    request_key = hashlib.sha256(request_id.encode('ascii')).hexdigest()[:24]
    attempt = task_dir / 'evidence' / 'collected' / request_key / ('a-' + 'a' * 12)
    monkeypatch.setattr(recording.uuid, 'uuid4', lambda: SimpleNamespace(hex='a' * 32))

    @contextmanager
    def replace_parent_then_stream(*args, **kwargs):
        import shutil
        shutil.rmtree(attempt)
        try:
            attempt.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip('symlink unavailable')
        with original_stream(*args, **kwargs) as stream:
            yield stream

    monkeypatch.setattr(recording, '_collection_stream', replace_parent_then_stream)
    with pytest.raises(ValueError):
        recording.collect_artifacts(task_dir, request_id, [str(source)])
    assert list(outside.iterdir()) == []


def test_collector_pins_attempt_directory_before_output_write(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cli import recording

    supports_dir_fd = getattr(recording.os, 'supports_dir_fd', ())
    if (os.name == 'nt' or recording.os.open not in supports_dir_fd
            or recording.os.stat not in supports_dir_fd
            or recording.os.rename not in supports_dir_fd
            or recording.os.unlink not in supports_dir_fd
            or not hasattr(recording.os, 'O_DIRECTORY')
            or not hasattr(recording.os, 'O_NOFOLLOW')):
        pytest.skip('POSIX directory-handle output is unavailable on this host')
    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    original_open = recording._open_posix_collection_temp
    request_id = 'pin-before-write'
    request_key = hashlib.sha256(request_id.encode('ascii')).hexdigest()[:24]
    attempt = task_dir / 'evidence' / 'collected' / request_key / ('a-' + 'c' * 12)
    monkeypatch.setattr(recording.uuid, 'uuid4', lambda: SimpleNamespace(hex='c' * 32))

    def replace_then_open(handle):
        moved = attempt.with_name(attempt.name + '-original')
        attempt.rename(moved)
        attempt.symlink_to(outside, target_is_directory=True)
        return original_open(handle)

    monkeypatch.setattr(recording, '_open_posix_collection_temp', replace_then_open)
    with pytest.raises(ValueError, match='ARTIFACT_COLLECTION_PATH_ESCAPE'):
        recording.collect_artifacts(task_dir, request_id, [str(source)])
    assert list(outside.iterdir()) == []


def test_collector_rejects_a_parent_replaced_by_junction_before_first_write(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import os
    import shutil
    import subprocess
    from cli import recording

    if os.name != 'nt':
        pytest.skip('Windows junction boundary')
    source = tmp_path / 'source.png'
    source.write_bytes(b'stable artifact')
    task_dir = tmp_path / 'task'
    task_dir.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    original_stream = recording._collection_stream
    request_id = 'parent-replaced-junction'
    request_key = hashlib.sha256(request_id.encode('ascii')).hexdigest()[:24]
    attempt = task_dir / 'evidence' / 'collected' / request_key / ('a-' + 'b' * 12)
    monkeypatch.setattr(recording.uuid, 'uuid4', lambda: SimpleNamespace(hex='b' * 32))

    @contextmanager
    def replace_parent_then_stream(*args, **kwargs):
        shutil.rmtree(attempt)
        linked = subprocess.run(['cmd', '/c', 'mklink', '/J', str(attempt), str(outside)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
        if linked.returncode != 0:
            pytest.skip('junction unavailable: ' + linked.stderr)
        with original_stream(*args, **kwargs) as stream:
            yield stream

    monkeypatch.setattr(recording, '_collection_stream', replace_parent_then_stream)
    with pytest.raises(ValueError, match='ARTIFACT_COLLECTION_PATH_ESCAPE'):
        recording.collect_artifacts(task_dir, request_id, [str(source)])
    assert list(outside.iterdir()) == []
