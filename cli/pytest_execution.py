# -*- coding: utf-8 -*-
"""Opt-in, selected pytest execution using its public CLI, not a Shell runner.

The caller must already have approval for the selected code and its effects.
A local evidence reference documents that scope; it is not an authorization
oracle or a sandbox. Execution receipts are evidence, never formal PASS.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Any

from . import db as dbmod
from . import record_first, recording, event_policies, transaction_commit
from .change_set import capture_change_set
from .evidence import validate_evidence_path
from .version import active_version


SCHEMA = 'tp-spec.pytest-execution/v1'


def _hash(path: Path) -> str:
    return recording._digest(path)


def _json_hash(value: dict[str, Any]) -> str:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _new_json(path: Path, value: dict[str, Any]) -> None:
    # An interrupted write is intentionally not replaced or treated as finished.
    # An incomplete reserved request must be diagnosed, never automatically rerun.
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('EXECUTION_RECEIPT_INVALID: missing, linked or oversized receipt; do not rerun')
    from .execution_reports import _unique_object
    try:
        result = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        if not isinstance(result, dict):
            raise ValueError('not an object')
        return result
    except (OSError, ValueError) as exc:
        raise ValueError('EXECUTION_RECEIPT_INVALID: restore original evidence; do not rerun') from exc


def _run_directory(tdir: Path, key: str, *, create: bool = True) -> Path:
    current = tdir
    for name in ('evidence', 'pytest-executions'):
        current = current / name
        if create:
            current.mkdir(exist_ok=True)
        elif not current.exists() and not current.is_symlink():
            continue
        info = current.lstat()
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('EXECUTION_PATH_INVALID: linked or invalid output parent')
    return current / hashlib.sha256(key.encode('ascii')).hexdigest()[:32]


def _selections(root: Path, tests: list[str]) -> list[str]:
    if not tests or len(tests) > 128 or len(set(tests)) != len(tests):
        raise ValueError('PYTEST_SELECTION_INVALID: select distinct explicit test files/node IDs (1..128)')
    result = []
    for value in tests:
        if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
            raise ValueError('PYTEST_SELECTION_INVALID')
        raw, *nodes = value.split('::')
        path = (root / raw).resolve()
        if (not path.is_relative_to(root) or not path.is_file() or path.suffix != '.py'
                or any(not part for part in nodes)):
            raise ValueError('PYTEST_SELECTION_INVALID: only existing .py files within the bound repository')
        # Absolute file arguments cannot be mistaken for pytest flags.
        result.append(str(path) + (('::' + '::'.join(nodes)) if nodes else ''))
    if len(set(result)) != len(result):
        raise ValueError('PYTEST_SELECTION_INVALID: aliases select the same test twice')
    return result


def _check_live(conn, tdir: Path, tid: str):
    task = record_first._load(conn, tid)
    transaction_commit._assert_task_workspace_identity(conn, tdir, tid)
    if (task['current_state'] not in {'NEW', 'ACTIVE'} or event_policies.is_task_retired(conn, tid)):
        raise ValueError('EXECUTION_TASK_NOT_LIVE: resolve waiting or terminal state before new execution')
    return task


def _accept(tdir: Path, tid: str, db_path: str, run_dir: Path, payload: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    start = _read(run_dir / 'started.json')
    if start.get('request') != payload:
        raise ValueError('REQUEST_ID_CONFLICT: this run ID belongs to a different command or scope')
    if not (run_dir / 'completed.json').exists():
        raise ValueError('EXECUTION_INCOMPLETE: request already reserved; process/output state unknown; do not rerun')
    result = _read(run_dir / 'completed.json')
    if (start.get('schema') != SCHEMA or start.get('contract') != active_version()
            or result.get('schema') != SCHEMA or result.get('request') != payload
            or result.get('started_sha256') != _json_hash(start)
            or _hash(run_dir / 'started.json') != _json_hash(start)):
        raise ValueError('EXECUTION_RECEIPT_INVALID: completion identity changed; do not rerun')
    execution = result.get('execution')
    if (not isinstance(execution, dict) or execution.get('status') not in {'FINISHED', 'TIMED_OUT', 'INTERRUPTED', 'NOT_STARTED'}
            or type(execution.get('command_exit_code')) is not int
            or execution['command_exit_code'] not in {0, 1, 2, 3, 4, 5, 124, 127, 130}
            or execution.get('command') != start.get('command')):
        raise ValueError('EXECUTION_RECEIPT_INVALID: invalid observed result')
    code = execution['command_exit_code']
    status, rc = execution['status'], execution.get('exit_code')
    if ((status == 'FINISHED' and (type(rc) is not int or code != (rc if rc in {0, 1, 2, 3, 4, 5} else 1)))
            or (status != 'FINISHED' and code != {'TIMED_OUT': 124, 'INTERRUPTED': 130, 'NOT_STARTED': 127}[status])
            or execution.get('observed_here') is not True
            or execution.get('authorization') != start.get('authorization')
            or execution.get('change_set_before') != (start.get('change_set') or {}).get('content_digest')
            or execution.get('prepared_at') != start.get('prepared_at')
            or type(execution.get('duration_ms')) not in (int, float)
            or not math.isfinite(execution['duration_ms']) or execution['duration_ms'] < 0):
        raise ValueError('EXECUTION_RECEIPT_INVALID: inconsistent observed result')
    files = result.get('files')
    if not isinstance(files, list) or not 2 <= len(files) <= 3:
        raise ValueError('EXECUTION_RECEIPT_INVALID: invalid output inventory')
    names = []
    for item in files:
        if not isinstance(item, dict) or item.get('name') not in {'output.log', 'junit.xml', 'authorization.txt'}:
            raise ValueError('EXECUTION_RECEIPT_INVALID: unexpected output')
        path = run_dir / item['name']
        if path.is_symlink() or not path.is_file() or _hash(path) != item.get('sha256'):
            raise ValueError('EXECUTION_EVIDENCE_CHANGED: restore recorded output; do not rerun tests')
        names.append(item['name'])
    if (len(set(names)) != len(names) or not {'output.log', 'authorization.txt'} <= set(names)
            or type(result.get('junit_accepted')) is not bool
            or (result['junit_accepted'] and 'junit.xml' not in names)
            or _hash(run_dir / 'authorization.txt') != (start.get('authorization') or {}).get('sha256')):
        raise ValueError('EXECUTION_RECEIPT_INVALID: incomplete output or authorization inventory')
    sources = [str(run_dir / 'started.json'), str(run_dir / 'completed.json')]
    sources += [str(run_dir / item['name']) for item in files if (run_dir / item['name']).stat().st_size > 0]
    reports = []
    junit = run_dir / 'junit.xml'
    if result.get('junit_accepted'):
        reports = [str(junit)]
        sources.remove(str(junit))
    output = {'task_id': tid, 'execution': execution, 'replayed': replay,
              'formal_verification_created': False, 'facts_committed': False,
              'execution_receipt': str((run_dir / 'completed.json').relative_to(tdir)),
              'result_scope': 'observed selected pytest process only; not whole-task, visual or human acceptance',
              'command_exit_code': execution['command_exit_code']}
    kwargs = dict(actor='tp-test-engineer', phase='verification', summary=payload['summary'],
                  collect=sources, result_reports=reports)
    key = 'pytest:' + payload['request_id']
    accepted = None
    try:
        accepted = record_first.checkpoint(task_id=tid, task_dir=str(tdir), db=db_path,
                                          request_id=key, **kwargs)
    except Exception as exc:
        # A lost response can occur AFTER commit. Resolve the same logical
        # request by reading its original receipt, never by running tests again.
        output.update(registration_error=str(exc), view_status='UNAVAILABLE')
        try:
            conn = dbmod.connect(db_path)
            try:
                accepted = recording.checkpoint_request(tid, tdir, key, **kwargs).replay(conn)
            finally:
                conn.close()
        except Exception as recovery_error:
            output.update(facts_committed=None, registration_status='UNKNOWN',
                          recovery_error=str(recovery_error))
    if accepted is not None:
        # The local control receipt is not authoritative over an earlier bound
        # copy. In particular, it must not promote a previous exit=1 to exit=0.
        for name, value in [('started.json', start), ('completed.json', result)]:
            matches = [item for item in accepted.get('collected_artifacts', [])
                       if item.get('source_name') == name]
            if len(matches) != 1 or matches[0].get('sha256') != _json_hash(value):
                raise ValueError('EXECUTION_RECEIPT_INVALID: differs from original committed evidence; do not rerun')
        output.update(accepted)
        output['replayed'] = bool(replay or accepted.get('replayed'))
    elif output['command_exit_code'] == 0:
        output['command_exit_code'] = 1

    return output


def run_pytest(*, task_id: str, task_dir: str, tests: list[str], authorization_evidence: str,
               request_id: str, summary: str, repo_root: str | None = None,
               timeout: float = 600.0, db: str | None = None, security_context: dict | None = None) -> dict[str, Any]:
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,96}', request_id or ''):
        raise ValueError('REQUEST_ID_INVALID: execution requires 1..96 safe ASCII characters')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('EXECUTION_TIMEOUT_INVALID: expected finite positive seconds')
    if not summary.strip() or len(summary) > 4000:
        raise ValueError('EXECUTION_SUMMARY_INVALID: expected a short non-empty summary')
    tdir = record_first._task_dir(task_dir)
    db_path = str(Path(dbmod.resolve_db_path(db, task_id=task_id)).resolve())
    payload = {'task_id': task_id, 'task_dir': str(tdir), 'db': db_path, 'tests': list(tests),
               'authorization_evidence': authorization_evidence, 'request_id': request_id,
               'repo_root': str(Path(repo_root).resolve()) if repo_root else None,
               'summary': summary, 'timeout': timeout,
               **({'security_context': security_context} if security_context is not None else {})}
    conn = dbmod.connect(db_path)
    try:
        record_first._load(conn, task_id)
        transaction_commit._assert_task_workspace_identity(conn, tdir, task_id)
        run_dir = _run_directory(tdir, request_id, create=False)
        if run_dir.exists():
            info = run_dir.lstat()
            if (run_dir.is_symlink() or not run_dir.is_dir()
                    or getattr(info, 'st_file_attributes', 0) & 0x400):
                raise ValueError('EXECUTION_PATH_INVALID: invalid reserved request')
            return _accept(tdir, task_id, db_path, run_dir, payload, replay=True)
        # Even a deleted control receipt must not turn a committed request into
        # another execution. The original evidence must be restored instead.
        for row in conn.execute("SELECT detail_json FROM task_event WHERE task_id=? AND event_type='FACT'", (task_id,)):
            detail = json.loads(row['detail_json'] or '{}')
            if isinstance(detail, dict) and (detail.get('logical_request') or {}).get('request_id') == 'pytest:' + request_id:
                raise ValueError('EXECUTION_RECEIPT_MISSING: committed run requires original receipt; do not rerun')
        task = _check_live(conn, tdir, task_id)
        auth = validate_evidence_path(tdir, authorization_evidence, require_evidence_dir=True)
        if not auth.ok:
            raise ValueError('EXECUTION_AUTHORIZATION_EVIDENCE_REQUIRED: ' + str(auth.error))
        development = record_first._latest_development_change_set(conn, task_id)
        if not development or not development.get('repo_roots'):
            raise ValueError('DEVELOPMENT_CHANGE_SET_REQUIRED')
        roots = [Path(value).resolve() for value in development['repo_roots']]
        root = Path(repo_root).resolve() if repo_root else (roots[0] if len(roots) == 1 else None)
        if root is None or root not in roots:
            raise ValueError('EXECUTION_REPO_REQUIRED: select one already bound development repository')
        selected = _selections(root, list(tests))
        from . import security_authority as authority
        security = authority.normalize_context(security_context or {"effect_scope": "regression"})
        if security["effect_scope"] != "regression":
            raise ValueError("SECURITY_POC_NOT_FORMAL: run isolated PoC under its separately authorized investigation, not formal regression")
        security["paths"] = sorted(set(security["paths"]) | {Path(s.split("::", 1)[0]).relative_to(root).as_posix() for s in selected})
        authority.check_effect(conn, task_id, security, task_dir=tdir)
        authority.check_formal_evidence(authority.read(conn, task_id, tdir), tdir, [auth.item])
        before = capture_change_set([str(p) for p in roots])
        from .change_set import same_bound_product_content
        from .delivery_contract import require_scope_checkpoint
        require_scope_checkpoint(conn, task_id, development_event_id=development['event_id'])
        if not same_bound_product_content(development['detail'], before):
            raise ValueError('DEVELOPMENT_CHANGE_SET_STALE')
        # Atomic mkdir is the no-rerun fence; never expire or automatically erase
        # a reserved request, including one interrupted before process creation.
        _run_directory(tdir, request_id)
        try:
            run_dir.mkdir()
        except FileExistsError:
            raise ValueError('EXECUTION_IN_PROGRESS: same logical request is already reserved; do not rerun')
        command = [sys.executable, '-m', 'pytest', '-q', '--strict-markers', '-o', 'addopts=',
                   '--junitxml=' + str(run_dir / 'junit.xml'), *selected]
        started = {'schema': SCHEMA, 'request': payload, 'command': command,
                   'contract': active_version(), 'project_id': task['project_id'],
                   'prepared_at': dbmod.now_iso(), 'change_set': record_first._compact_change_set(before),
                   'authorization': auth.item, 'controller_pid': os.getpid(),
                   'python': sys.version.split()[0], 'scope': 'explicit selected pytest; caller retains effect authorization'}
        _new_json(run_dir / 'started.json', started)
        # Preserve the actual authorization source, not just its descriptor.
        # A reference remains a caller-supplied assertion, never a grant.
        source = tdir / auth.item['path']
        with source.open('rb') as original, (run_dir / 'authorization.txt').open('xb') as saved:
            for block in iter(lambda: original.read(1024 * 1024), b''):
                saved.write(block)
        if _hash(run_dir / 'authorization.txt') != auth.item['sha256']:
            raise ValueError('EXECUTION_AUTHORIZATION_CHANGED: reserved run was not launched')
        # Refresh mutable prerequisites immediately before spawning; no database
        # write lock is held while product tests execute.
        _check_live(conn, tdir, task_id)
        latest = record_first._latest_development_change_set(conn, task_id)
        if (not latest or latest['event_id'] != development['event_id']
                or not same_bound_product_content(development['detail'], capture_change_set([str(p) for p in roots]))):
            raise ValueError('EXECUTION_PRECONDITION_CHANGED: reserved run was not launched')
        require_scope_checkpoint(conn, task_id, development_event_id=development['event_id'])
        authority.check_effect(conn, task_id, security, task_dir=tdir)
        authority.check_formal_evidence(authority.read(conn, task_id, tdir), tdir, [auth.item])
        recording.validate_bound_items(tdir, [auth.item])
    finally:
        conn.close()

    env = os.environ.copy()
    # This typed entry accepts no hidden extra test selections or options.
    # Projects needing arbitrary options/plugins use their existing approved
    # upstream command and import its report instead of widening this entry.
    env.pop('PYTEST_ADDOPTS', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        pytest_version = importlib.metadata.version('pytest')
    except (importlib.metadata.PackageNotFoundError, OSError):
        pytest_version = None
    process_started_at = dbmod.now_iso()
    start_ns = time.perf_counter_ns()
    status, rc, child_pid = 'NOT_STARTED', None, None
    command_code = 127
    with (run_dir / 'output.log').open('xb') as stream:
        process = None
        try:
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, shell=False)
            child_pid = process.pid
            rc = process.wait(timeout=timeout)
            status = 'FINISHED'
            command_code = rc if rc in {0, 1, 2, 3, 4, 5} else 1
        except subprocess.TimeoutExpired:
            process.kill(); rc = process.wait()
            status, command_code = 'TIMED_OUT', 124
        except KeyboardInterrupt:
            if process is not None:
                process.kill(); rc = process.wait()
            status, command_code = 'INTERRUPTED', 130
        except OSError as exc:
            stream.write(('pytest process could not start: ' + str(exc)).encode('utf-8'))
    elapsed = (time.perf_counter_ns() - start_ns) / 1_000_000
    process_finished_at = dbmod.now_iso()
    after_digest = None
    subject_unchanged = False
    try:
        after = capture_change_set([str(p) for p in roots])
        after_digest = after['content_digest']
        subject_unchanged = same_bound_product_content(development['detail'], after)
    except (ValueError, OSError):
        pass  # We observed the process, not a reliable post-execution subject.
    execution = {'status': status, 'exit_code': rc, 'command_exit_code': command_code,
                 'prepared_at': started['prepared_at'], 'started_at': process_started_at,
                 'finished_at': process_finished_at,
                 'installed_pytest_version': pytest_version,
                 'tool_version_source': 'interpreter distribution metadata; not proof of child import resolution',
                 'duration_ms': elapsed, 'duration_scope': 'process spawn/wait only; excludes accounting',
                 'command': command, 'cwd': str(root), 'change_set_before': before['content_digest'],
                 'change_set_after': after_digest, 'subject_unchanged': subject_unchanged,
                 'executor': {'kind': 'local-pytest-process', 'pid': child_pid, 'model': None},
                 'authorization': auth.item, 'observed_here': True,
                 'descendant_process_state': 'not monitored; only the owned direct child is waited/terminated'}
    junit_ok = False
    report_issue = None
    junit = run_dir / 'junit.xml'
    if junit.is_file() and junit.stat().st_size:
        try:
            from .execution_reports import read_report
            checked = validate_evidence_path(tdir, str(junit.relative_to(tdir)), require_evidence_dir=True)
            if not checked.ok:
                raise ValueError('invalid pytest output')
            read_report(tdir, checked.item, task_id=task_id)
            junit_ok = True
        except ValueError as exc:
            report_issue = str(exc)
    files = [{'name': name, 'sha256': _hash(run_dir / name)}
             for name in ('output.log', 'junit.xml', 'authorization.txt') if (run_dir / name).is_file()]
    completed = {'schema': SCHEMA, 'request': payload, 'started_sha256': _hash(run_dir / 'started.json'),
                 'execution': execution, 'files': files, 'junit_accepted': junit_ok, 'report_issue': report_issue}
    _new_json(run_dir / 'completed.json', completed)
    return _accept(tdir, task_id, db_path, run_dir, payload, replay=False)
