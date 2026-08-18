from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path

from cli import db as dbmod
from cli import main as climain
from cli.version import active_version

BASE = Path(__file__).resolve().parents[2]
PROJECT_ID = "p-test"


def run(argv: list[str]):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def build_task(
    work: str | os.PathLike[str],
    *,
    task_id: str = "TASK-20260818-001",
    risk: str = "L1",
    flow: str = "L1",
    db_name: str = "t.db",
    project_id: str = PROJECT_ID,
):
    """Create a current-contract task fixture without legacy commit semantics."""
    proj_root = Path(work) / "proj"
    task_dir = proj_root / ".tp-spec" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    db_path = proj_root / ".tp-spec" / "db" / db_name
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = dbmod.connect(str(db_path))
    dbmod.init_schema(conn)
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO project (project_id, project_name, root_path, base_version, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (project_id, project_id, str(proj_root), active_version(), dbmod.now_iso(), dbmod.now_iso()),
        )
    conn.close()

    template_dir = BASE / "templates" / active_version()
    for src in template_dir.iterdir():
        if src.is_file():
            (task_dir / src.name).write_bytes(src.read_bytes())

    status = task_dir / "status.yaml"
    text = status.read_text(encoding="utf-8")
    text = text.replace('task_id: "TASK-YYYYMMDD-XXX"', f'task_id: "{task_id}"')
    text = text.replace('created: "YYYY-MM-DD"', 'created: "2026-08-18"')
    status.write_text(text, encoding="utf-8", newline="\n")

    evidence = task_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "test-result.txt").write_text("verification test passed\n", encoding="utf-8", newline="\n")
    (evidence / "architecture-review-check.txt").write_text(
        "architecture review checklist passed\n", encoding="utf-8", newline="\n"
    )

    rc, out, err = run([
        "task", "create", "--id", task_id, "--project", project_id,
        "--title", "runtime test", "--risk", risk, "--flow", flow, "--db", str(db_path),
    ])
    assert rc == 0, f"task create failed: rc={rc} out={out} err={err}"
    return str(task_dir), str(db_path)
