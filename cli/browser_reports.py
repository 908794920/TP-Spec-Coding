# -*- coding: utf-8 -*-
"""Read native Playwright JSON and preserve explicitly approved local attachments.

No browser, model, network, HTML renderer or formal acceptance producer lives
here. Upstream outcomes are observations; expected failure and flaky are not
silently promoted to a passing visual/business acceptance.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from typing import Any

from . import recording
from .execution_reports import MAX_REPORT_ITEMS, _nonnegative, _unique_object, report_text

_OUTCOMES = {'expected', 'unexpected', 'flaky', 'skipped'}
_STATUSES = {'passed', 'failed', 'timedOut', 'skipped', 'interrupted'}
# Only known report/media types are followed automatically. Other local files
# need explicit --collect, not a path in untrusted report content.
_MEDIA = {
    'image/png': ({'.png'}, 'image'), 'image/jpeg': ({'.jpg', '.jpeg'}, 'image'),
    'image/webp': ({'.webp'}, 'image'), 'video/webm': ({'.webm'}, 'video'),
    'video/mp4': ({'.mp4'}, 'video'), 'application/zip': ({'.zip'}, 'trace'),
    'text/html': ({'.html', '.htm'}, 'report'),
}


def _list(value: Any) -> list:
    if not isinstance(value, list) or len(value) > MAX_REPORT_ITEMS:
        raise ValueError('invalid or excessive Playwright list')
    return value


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError('invalid Playwright object')
    return value


def _date(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError('invalid Playwright timestamp')
    if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('Playwright timestamp must include timezone')
    return value


def _cases(data: dict):
    # Iterative and bounded: nested suites never cause unbounded recursion.
    pending = [(suite, f'suites/{n}') for n, suite in reversed(list(enumerate(_list(data.get('suites')))))]
    count = 0
    while pending:
        suite, pointer = pending.pop()
        suite = _object(suite); count += 1
        if count > MAX_REPORT_ITEMS:
            raise ValueError('Playwright item limit exceeded')
        for n, spec in enumerate(_list(suite.get('specs'))):
            spec = _object(spec)
            tests = _list(spec.get('tests'))
            # Native multi-project merging keeps the first spec.ok unchanged.
            # Per-project tests and aggregate stats, not this hint, drive results.
            if type(spec.get('ok')) is not bool:
                raise ValueError('invalid Playwright spec outcome')
            for j, test in enumerate(tests):
                count += 1
                if count > MAX_REPORT_ITEMS:
                    raise ValueError('Playwright item limit exceeded')
                yield _object(test), f'{pointer}/specs/{n}/tests/{j}'
        children = _list(suite.get('suites', []))
        pending.extend((child, f'{pointer}/suites/{n}') for n, child in reversed(list(enumerate(children))))


def _attachments(data: dict):
    index = 0
    for test, pointer in _cases(data):
        for attempt_index, attempt in enumerate(_list(test.get('results'))):
            for raw in _list(_object(attempt).get('attachments')):
                raw = _object(raw)
                content_type = raw.get('contentType')
                if not isinstance(content_type, str) or len(content_type) > 128 or any(ord(c) < 32 for c in content_type):
                    raise ValueError('invalid Playwright attachment type')
                path, body = raw.get('path'), raw.get('body')
                if path is not None and (not isinstance(path, str) or not path or len(path) > 4096 or any(ord(c) < 32 for c in path)):
                    raise ValueError('invalid Playwright attachment path')
                if body is not None and not isinstance(body, str):
                    raise ValueError('invalid Playwright attachment body')
                if path is None and body is None:
                    raise ValueError('Playwright attachment has no path/body')
                if index >= MAX_REPORT_ITEMS:
                    raise ValueError('Playwright attachment limit exceeded')
                yield {'index': index, 'case_ref': pointer, 'attempt': attempt_index,
                       'path': path, 'content_type': content_type,
                       'reference_sha256': hashlib.sha256(path.encode('utf-8')).hexdigest() if path else None}
                index += 1


def parse_playwright(data: dict) -> dict[str, Any]:
    config, stats = _object(data.get('config')), _object(data.get('stats'))
    version = config.get('version')
    if not isinstance(version, str) or len(version) > 80 or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('missing concrete Playwright report version')
    duration = _nonnegative(stats.get('duration'))
    started = _date(stats.get('startTime'))
    counts = {key: _nonnegative(stats.get(key), integer=True) for key in sorted(_OUTCOMES)}
    actual = dict.fromkeys(counts, 0)
    errors = _list(data.get('errors'))
    for error in errors:
        _object(error)
    cases = []
    nonpassing = 0
    attempt_count = 0
    for test, pointer in _cases(data):
        outcome, expected = test.get('status'), test.get('expectedStatus')
        if outcome not in _OUTCOMES or expected not in _STATUSES:
            raise ValueError('unknown Playwright outcome/status')
        actual[outcome] += 1
        attempts = _list(test.get('results'))
        statuses = []
        for result in attempts:
            result = _object(result); attempt_count += 1
            if attempt_count > MAX_REPORT_ITEMS:
                raise ValueError('Playwright attempt limit exceeded')
            status = result.get('status')
            if status is not None and status not in _STATUSES:
                raise ValueError('unknown Playwright attempt status')
            _nonnegative(result.get('duration'))
            _nonnegative(result.get('retry'), integer=True)
            _date(result.get('startTime'))
            attempt_errors = _list(result.get('errors'))
            for error in attempt_errors:
                _object(error)
            if status == 'passed' and (attempt_errors or result.get('error')):
                raise ValueError('Playwright passed attempt contains errors')
            statuses.append(status)
        if outcome == 'expected' and (not statuses or any(s not in {expected, 'skipped'} for s in statuses) or expected not in statuses):
            raise ValueError('Playwright expected result disagrees with attempts')
        if outcome == 'flaky' and (expected not in statuses or not any(s not in {expected, 'skipped', 'interrupted'} for s in statuses)):
            raise ValueError('Playwright flaky result disagrees with attempts')
        if outcome == 'skipped' and any(s not in {'skipped', 'interrupted', None} for s in statuses):
            raise ValueError('Playwright skipped result disagrees with attempts')
        clean = outcome == 'expected' and expected == 'passed' and statuses and all(s == 'passed' for s in statuses)
        nonpassing += int(not clean)
        cases.append({'case_ref': pointer, 'outcome': outcome, 'expected_status': expected,
                      'attempt_count': len(attempts), 'last_status': statuses[-1] if statuses else None})
    if counts != actual:
        raise ValueError('Playwright summary counts disagree with tests')
    attachments = list(_attachments(data))
    preview = sorted(cases, key=lambda c: c['outcome'] == 'expected')[:16]
    result = ('failed' if counts['unexpected'] or errors else
              'not_run' if not cases else 'incomplete' if nonpassing else 'passed')
    return {'format': 'playwright-json', 'reported_tool_version': version,
            'reported_result': {**counts, 'tests': len(cases), 'outcome': result,
                'duration_ms': duration, 'started_at': started, 'global_error_count': len(errors),
                'nonpassing_or_incomplete': nonpassing, 'cases': preview,
                'cases_truncated': len(cases) > len(preview),
                'file_attachment_count': sum(a['path'] is not None for a in attachments),
                'inline_attachment_count': sum(a['path'] is None for a in attachments)},
            'visual_review': 'not_inferred', 'deployment_binding': 'unverified',
            'failure_classification': 'not_inferred; inspect the relevant upstream evidence',
            'reported_browser': None, 'reported_viewport': None, 'reported_model': None}


def _native_data(task_dir: Path, observation: dict) -> dict:
    _, text = report_text(task_dir, observation['evidence'])
    return json.loads(text, object_pairs_hook=_unique_object)


def _safe_root(root: str) -> Path:
    path = Path(root)
    # Check lexical parents BEFORE resolve, including Windows reparse points.
    for part in [path, *path.parents]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('BROWSER_ARTIFACT_ROOT_INVALID: linked output root')
    if not path.is_dir():
        raise ValueError('BROWSER_ARTIFACT_ROOT_INVALID: expected local output directory')
    return path.resolve()


def collect_attachments(task_dir: Path, request_id: str, root: str, observations: list[dict],
                        *, existing_count: int) -> list[dict]:
    """Opt-in follows only report-declared media under one approved output root."""
    try:
        base = _safe_root(root)
        native = [obs for obs in observations if obs['format'] == 'playwright-json']
        if not native:
            raise ValueError('BROWSER_ARTIFACT_REPORT_REQUIRED: no native Playwright report')
        sources, bindings = [], []
        for obs in native:
            for item in _attachments(_native_data(task_dir, obs)):
                raw = item['path']
                if raw is None:
                    continue  # The original JSON already owns inline bytes. Never decode/render them.
                allowed, kind = _MEDIA.get(item['content_type'], (set(), 'other'))
                # Foreign Windows paths on POSIX must not be reinterpreted as local filenames.
                if (re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', raw) or raw.startswith(('\\\\', '//'))
                        or (os.name != 'nt' and PureWindowsPath(raw).drive)):
                    raise ValueError('BROWSER_ARTIFACT_PATH_INVALID: remote/foreign path')
                candidate = Path(os.path.abspath(base / raw))
                if not candidate.is_relative_to(base) or candidate.suffix.lower() not in allowed:
                    raise ValueError('BROWSER_ARTIFACT_PATH_INVALID: outside root or unsupported media; use explicit --collect after review')
                for part in [candidate, *candidate.parents]:
                    if part == base:
                        break
                    info = part.lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise ValueError('BROWSER_ARTIFACT_PATH_INVALID: linked attachment')
                if not candidate.is_file():
                    raise ValueError('BROWSER_ARTIFACT_PATH_INVALID: attachment is not a regular file')
                sources.append(str(candidate))
                bindings.append({'report_sha256': obs['evidence']['sha256'], 'report_path': obs['evidence']['path'], 'index': item['index'],
                                 'reference_sha256': item['reference_sha256'], 'kind': kind})
        maximum, _ = recording._limits()
        if existing_count + len(sources) > maximum:
            raise ValueError('BROWSER_ARTIFACT_LIMIT: combined batch exceeds configured file count')
        # The existing collector detects source changes, hashes the accepted
        # bytes and preserves evidence custody; no new file/transaction store.
        key = 'browser:' + hashlib.sha256(request_id.encode('ascii')).hexdigest()
        copied = recording.collect_artifacts(task_dir, key, sources, source_root=base)
        for item, binding in zip(copied, bindings):
            item['browser_attachment'] = binding
            item['source_name'] = f"browser-attachment-{binding['index']}" + Path(item['path']).suffix
        return copied
    except (OSError, ValueError) as exc:
        # Do not echo a possibly sensitive attachment path from untrusted JSON.
        if isinstance(exc, ValueError) and str(exc).startswith('BROWSER_ARTIFACT'):
            raise
        raise ValueError('BROWSER_ARTIFACT_INVALID: output missing, unreadable or changed; retain the run and repair collection, do not rerun') from exc


def bind_attachments(task_dir: Path, observation: dict, inventory: list[dict]) -> dict:
    if observation['format'] != 'playwright-json':
        return observation
    refs = [r for r in _attachments(_native_data(task_dir, observation)) if r['path'] is not None]
    matches = [item for item in inventory if isinstance(item.get('browser_attachment'), dict)
               and item['browser_attachment'].get('report_sha256') == observation['evidence']['sha256']
               and item['browser_attachment'].get('report_path') == observation['evidence']['path']]
    if len(matches) != len(refs):
        raise ValueError('BROWSER_ARTIFACT_BINDING_INVALID: attachment inventory incomplete')
    bound = []
    for item, ref in zip(matches, refs):
        marker = item['browser_attachment']
        kind = _MEDIA.get(ref['content_type'], (set(), 'other'))[1]
        if (type(marker.get('index')) is not int or marker['index'] != ref['index']
                or marker.get('reference_sha256') != ref['reference_sha256'] or marker.get('kind') != kind):
            raise ValueError('BROWSER_ARTIFACT_BINDING_INVALID: attachment reference changed')
        bound.append({**{key: item[key] for key in ('type', 'path', 'sha256')},
                      'attachment_index': ref['index'], 'case_ref': ref['case_ref'], 'attempt': ref['attempt'], 'kind': kind})
    return {**observation, 'attachment_evidence': bound}
