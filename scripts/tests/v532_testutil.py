"""Unmodified production entry helpers; no parser/card/timing monkeypatches."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

from cli import main as climain
from scripts.tests.test_v529_change_set_binding import make_repo


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(list(argv))
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue(), err.getvalue()


def make_runtime(tmp_path: Path, monkeypatch, *, task_id="TASK-V532"):
    project = make_repo(tmp_path)
    monkeypatch.chdir(project)
    registry = tmp_path / "registry.json"
    registry.write_text('{"projects": []}\n', encoding="utf-8")
    rc, out, err = run_cli([
        "project", "bootstrap", "--id", "v532-test", "--root", str(project),
        "--registry", str(registry),
    ])
    assert rc == 0, (out, err)
    db = project / ".tp-spec/db/v532-test.db"
    task_dir = project / ".tp-spec/tasks" / task_id
    rc, out, err = run_cli([
        "task", "create", "--id", task_id, "--project", "v532-test", "--risk", "L0",
        "--flow", "L0", "--db", str(db), "--scaffold", "--task-dir", str(task_dir),
    ])
    assert rc == 0, (out, err)
    (task_dir / "acceptance.md").write_text(
        '# Isolated Runtime fixture\n\n```yaml\nno_acceptance_required:\n'
        '  declared: true\n  reason: This fixture has no business acceptance claims.\n'
        'deferred_acceptance: []\nowner_waivers: []\ndatabase_operations: []\n```\n',
        encoding="utf-8",
    )
    (task_dir / "evidence").mkdir(exist_ok=True)
    (task_dir / "evidence/check.txt").write_text("synthetic test output\n", encoding="utf-8")
    return project, db, task_dir, task_id


def task_args(db, task_dir, task_id, operation, *args):
    return ["task", operation, "--task", task_id, "--task-dir", str(task_dir), *args, "--db", str(db)]
