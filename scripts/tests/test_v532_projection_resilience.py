from __future__ import annotations

import json
import os
from pathlib import Path

from cli import db as dbmod, transaction_commit
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args


def checkpoint(db, tdir, tid):
    return run_cli(task_args(db, tdir, tid, "checkpoint", "--actor", "tp-development-engineer", "--phase", "development", "--summary", "durable business fact"))


def event_count(db, tid):
    with dbmod.connect_readonly(str(db)) as conn:
        return conn.execute("SELECT COUNT(*) FROM task_event WHERE task_id=?", (tid,)).fetchone()[0]


def test_generated_render_failure_commits_facts_and_reports_rebuild_condition(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    before = event_count(db, tid)
    def fail(*args, **kwargs):
        raise OSError("injected derived-render failure")
    monkeypatch.setattr(transaction_commit, "_rebuild_current_view_text", fail)
    rc, out, err = checkpoint(db, tdir, tid)
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result["facts_committed"] is True
    assert result["view_status"] == "PENDING"
    assert "DERIVED_VIEW_PENDING" in err
    assert event_count(db, tid) > before
    assert "durable business fact" in (tdir / "events.jsonl").read_text(encoding="utf-8")


def test_unwritable_derived_target_does_not_rollback_and_can_be_rebuilt(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    view = tdir / "generated/continuation.md"
    view.unlink(missing_ok=True)
    view.mkdir(parents=True)
    rc, out, err = checkpoint(db, tdir, tid)
    assert rc == 0, (out, err)
    assert json.loads(out)["view_status"] == "PENDING"
    before = event_count(db, tid)
    view.rmdir()
    rc, out, err = run_cli(["projection", "rebuild", "--view-only", "--task", tid, "--task-dir", str(tdir), "--db", str(db)])
    assert rc == 0, (out, err)
    assert json.loads(out)["view_status"] == "CURRENT"
    assert "durable business fact" in view.read_text(encoding="utf-8")
    assert event_count(db, tid) == before


def test_mandatory_projection_failure_still_rolls_back_facts(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    before = event_count(db, tid)
    original = transaction_commit._stage_and_replace
    def fail_mandatory(task_dir, texts, rel_paths):
        if "status.yaml" in rel_paths:
            raise OSError("injected required projection failure")
        return original(task_dir, texts, rel_paths)
    monkeypatch.setattr(transaction_commit, "_stage_and_replace", fail_mandatory)
    rc, out, err = checkpoint(db, tdir, tid)
    assert rc != 0
    assert "rolled back" in err
    assert event_count(db, tid) == before


def test_checkpoint_replaces_each_mandatory_projection_only_once(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    original = os.replace
    replacements = []
    def observe(source, target, *args, **kwargs):
        replacements.append(Path(target))
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(os, "replace", observe)
    rc, out, err = checkpoint(db, tdir, tid)
    assert rc == 0, (out, err)
    assert replacements.count(tdir / "status.yaml") == 1
    assert replacements.count(tdir / "events.jsonl") == 1


def test_view_only_rebuild_cannot_accept_same_count_tampered_events(tmp_path, monkeypatch):
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = checkpoint(db, tdir, tid)
    assert rc == 0, (out, err)
    path = tdir / 'events.jsonl'
    lines = path.read_text(encoding='utf-8').splitlines()
    last = json.loads(lines[-1])
    last['note'] = 'fabricated summary not in the DB'
    lines[-1] = json.dumps(last)
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    before = path.read_bytes()
    rc, out, err = run_cli(['projection', 'rebuild', '--view-only', '--task', tid, '--task-dir', str(tdir), '--db', str(db)])
    assert rc != 0 and json.loads(out)['view_status'] == 'PENDING'
    assert 'reconcile' in err
    assert path.read_bytes() == before


def test_view_only_rebuild_does_not_ignore_unreadable_journal(tmp_path, monkeypatch):
    from cli import transaction_journal
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    rc, out, err = checkpoint(db, tdir, tid)
    assert rc == 0, (out, err)
    directory = transaction_journal.transactions_dir(tdir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'corrupt.json').write_text('{malformed', encoding='utf-8')
    rc, out, err = run_cli(['projection', 'rebuild', '--view-only', '--task', tid, '--task-dir', str(tdir), '--db', str(db)])
    assert rc != 0 and json.loads(out)['view_status'] == 'PENDING'
    assert 'journal' in err


def test_b08_closed_warning_channel_still_returns_committed_derived_pending(tmp_path, monkeypatch):
    import contextlib
    import io
    from cli import main as climain
    _, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    before = event_count(db, tid)
    view = tdir / 'generated/continuation.md'
    view.unlink(missing_ok=True)
    view.mkdir()
    class ClosedWarningChannel(io.StringIO):
        def write(self, text):
            raise BrokenPipeError('closed diagnostic stderr')
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(ClosedWarningChannel()):
        rc = climain.main(task_args(db, tdir, tid, 'checkpoint', '--actor', 'tp-development-engineer',
                                   '--phase', 'development', '--summary', 'committed with unavailable view warning'))
    result = json.loads(out.getvalue())
    assert rc == 0 and result['facts_committed'] is True
    assert result['view_status'] == 'PENDING'
    assert result['view_recovery'] == 'projection rebuild --view-only'
    assert event_count(db, tid) > before
