from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from cli import db as dbmod
from cli import orchestration
from cli.task_cmd import _upgrade_contract_artifact_text
from cli.version import active_version
from cli.migrations import SOURCE_CONTRACTS
from scripts.tests.runtime_testutil import build_task, run


def _legacy_version() -> str:
    return ".".join(["5", "2", "9"])


def _target_version() -> str:
    """Migration target is the currently active contract, not a frozen release literal."""
    return active_version()


def _git_baseline(task_dir: str) -> Path:
    root = Path(task_dir).parents[2]
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        (root / "README.md").write_text("baseline\n", encoding="utf-8", newline="\n")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
    return root


def _replace_contract_versions(task_dir: Path, source: str, target: str) -> None:
    for path in task_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        if target in text:
            path.write_text(text.replace(target, source), encoding="utf-8", newline="\n")


def _downgrade_task(task_dir: str, db_path: str, task_id: str) -> None:
    legacy = _legacy_version()
    current = active_version()
    tdir = Path(task_dir)
    _replace_contract_versions(tdir, legacy, current)
    conn = dbmod.connect(db_path)
    try:
        conn.execute("UPDATE task SET base_version=? WHERE task_id=?", (legacy, task_id))
        conn.execute("UPDATE project SET base_version=? WHERE project_id=(SELECT project_id FROM task WHERE task_id=?)", (legacy, task_id))
        conn.commit()
    finally:
        conn.close()


def _upgrade_project(db_path: str, project_id: str = "p-test") -> None:
    rc, out, err = run(["project", "upgrade-contract", "--id", project_id, "--db", db_path])
    assert rc == 0, (out, err)


def _insert_event(conn, task_id: str, event_type: str, actor: str, detail: dict, *, summary: str) -> int:
    cur = conn.execute(
        "INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
        (task_id, event_type, actor, summary, json.dumps(detail, ensure_ascii=False), _legacy_version(), dbmod.now_iso()),
    )
    return int(cur.lastrowid)


def test_old_database_verification_migrates_to_exactly_one_operation():
    source = _legacy_version()
    target = _target_version()
    text = """# 验收\n\n| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |\n|---|---|---|---|---|---|---|---|\n| AC-01 | 数据已更新 | task.md | L2 | SQL | evidence/sql/result.md | verification | PASS |\n\n## 数据库验证声明\n\n```yaml\ndatabase_verification:\n  action: DML\n  environment: development\n  authorized_by: human_owner\n  execution_evidence: evidence/sql/result.md\n  expected_result: 更新 1 行\n  rollback_or_cleanup: evidence/sql/rollback.md\n  dml_execution: passed\n  dml_residual_risk: 无\n```\n"""
    migrated = _upgrade_contract_artifact_text("acceptance.md", text, source, target)
    assert "database_verification:" not in migrated
    assert "## 数据库操作声明" in migrated
    assert "## 数据库验证声明" not in migrated
    assert migrated.count("- id: DB-LEGACY-01") == 1
    assert "type: DML" in migrated
    assert "acceptance_refs:\n  - AC-01" in migrated
    assert "status: EXECUTED" in migrated
    assert "execution_evidence: evidence/sql/result.md" in migrated
    assert "rollback_or_cleanup: evidence/sql/rollback.md" in migrated


def test_terminal_v528_history_is_not_rewritten(tmp_path: Path):
    assert _target_version() != _legacy_version()
    task_id = "TASK-V529-TERMINAL"
    task_dir, db_path = build_task(tmp_path, task_id=task_id)
    _downgrade_task(task_dir, db_path, task_id)
    _upgrade_project(db_path)
    conn = dbmod.connect(db_path)
    try:
        conn.execute("UPDATE task SET current_state='COMPLETED', current_stage='delivery' WHERE task_id=?", (task_id,))
        conn.commit()
        before_events = conn.execute("SELECT COUNT(*) AS n FROM task_event WHERE task_id=?", (task_id,)).fetchone()["n"]
    finally:
        conn.close()
    before = {p.name: p.read_bytes() for p in Path(task_dir).iterdir() if p.is_file()}

    rc, out, err = run(["task", "migrate", "--task", task_id, "--task-dir", task_dir, "--db", db_path])
    assert rc != 0
    assert "terminal tasks are immutable archives" in (out + err)
    after = {p.name: p.read_bytes() for p in Path(task_dir).iterdir() if p.is_file()}
    assert after == before
    conn = dbmod.connect(db_path)
    try:
        row = conn.execute("SELECT base_version,current_state FROM task WHERE task_id=?", (task_id,)).fetchone()
        after_events = conn.execute("SELECT COUNT(*) AS n FROM task_event WHERE task_id=?", (task_id,)).fetchone()["n"]
    finally:
        conn.close()
    assert row["base_version"] == _legacy_version()
    assert row["current_state"] == "COMPLETED"
    assert after_events == before_events


def test_inflight_v528_pass_without_change_set_becomes_stale_after_migration(tmp_path: Path):
    assert _target_version() != _legacy_version()
    task_id = "TASK-V529-STALE"
    task_dir, db_path = build_task(tmp_path, task_id=task_id, risk="L1", flow="L1")
    _git_baseline(task_dir)
    _downgrade_task(task_dir, db_path, task_id)
    _upgrade_project(db_path)
    conn = dbmod.connect(db_path)
    try:
        for actor, phase in (
            ("tp-product-manager", "requirement"),
            ("tp-software-architect", "architecture"),
            ("tp-development-engineer", "development"),
        ):
            _insert_event(
                conn, task_id, "FACT", actor,
                {"operation": "CHECKPOINT", "result_status": "COMPLETED", "phase": phase, "producer": "legacy"},
                summary=f"legacy {phase} complete",
            )
        _insert_event(
            conn, task_id, "VERIFICATION_COMPLETED", "tp-test-engineer",
            {"operation": "VERIFY", "result_status": "COMPLETED", "decision": "PASS", "producer": "legacy"},
            summary="legacy verification pass",
        )
        _insert_event(
            conn, task_id, "REVIEW_COMPLETED", "tp-code-reviewer",
            {"operation": "REVIEW", "result_status": "COMPLETED", "decision": "PASS", "review_kind": "CODE", "producer": "legacy"},
            summary="legacy review pass",
        )
        conn.execute("UPDATE task SET current_state='ACTIVE', current_stage='review' WHERE task_id=?", (task_id,))
        conn.commit()
    finally:
        conn.close()

    rc, out, err = run(["task", "migrate", "--task", task_id, "--task-dir", task_dir, "--db", db_path])
    assert rc == 0, (out, err)
    route = orchestration.resolve_route(task_id, db_path=db_path, base_root=Path(__file__).resolve().parents[2], allowed_effects=["repo_mutation"])
    assert route["next_stage"] == "development"
    assert route["role_id"] == "tp-development-engineer"
    assert "CHANGE_SET_REQUIRED" in route["reason_codes"]


def test_old_no_change_does_not_satisfy_new_required_knowledge(tmp_path: Path):
    assert _target_version() != _legacy_version()
    task_id = "TASK-V529-KNOWLEDGE"
    task_dir, db_path = build_task(tmp_path, task_id=task_id, risk="L0", flow="L0")
    _git_baseline(task_dir)
    # Use current contract for the typed Request, but preserve a legacy NO_CHANGE FACT beside it.
    conn = dbmod.connect(db_path)
    try:
        request_id = _insert_event(
            conn, task_id, "KNOWLEDGE_CONVERGENCE_REQUEST", "tp-integration-engineer",
            {
                "operation": "KNOWLEDGE_CONVERGENCE_REQUEST",
                "result_status": "COMPLETED",
                "request_event_id": 0,
                "change_set_id": "sha256:legacy-test",
                "trigger_reason_codes": ["HUMAN_OWNER_REQUIRED"],
                "source_refs": ["implementation.md"],
                "producer": "delivery_converge",
            },
            summary="knowledge request",
        )
        conn.execute(
            "UPDATE task_event SET workflow_version=? WHERE id=?",
            (active_version(), request_id),
        )
        _insert_event(
            conn, task_id, "FACT", "tp-integration-engineer",
            {"knowledge_disposition": "NO_CHANGE", "producer": "legacy_delivery"},
            summary="legacy knowledge no change",
        )
        conn.commit()
    finally:
        conn.close()

    # 旧 FACT 不是 typed Result；即使存在，也不能满足新的 Request。
    _, events = orchestration._load_task_facts(task_id, db_path)
    request_event = next(e for e in events if e["event_type"] == "KNOWLEDGE_CONVERGENCE_REQUEST")
    request = {"event": request_event, "detail": json.loads(request_event["detail_json"])}
    assert orchestration._knowledge_result_for_request(events, request, Path(task_dir)) is None


def test_release_contract_is_v529_and_single_active_template():
    assert _target_version() != _legacy_version()
    base = Path(__file__).resolve().parents[2]
    active_dirs = sorted(p.name for p in (base / "templates").iterdir() if p.is_dir())
    assert active_dirs == [_target_version()]
    assert (base / "templates" / _target_version() / "status.yaml").is_file()
    assert not (base / "templates" / _legacy_version()).exists()


# B09: synthetic legacy contracts exercise the real production CLI; no site DB.
B09_SOURCE = ".".join(["5", "3", "0"])

def _b09_legacy_case(tmp_path, monkeypatch, source=B09_SOURCE):
    from scripts.tests.v532_testutil import make_runtime
    project, db, tdir, tid = make_runtime(tmp_path, monkeypatch)
    _replace_contract_versions(tdir, source, active_version())
    conn = dbmod.connect(str(db))
    try:
        conn.execute("UPDATE task SET base_version=? WHERE task_id=?", (source, tid))
        conn.execute("UPDATE project SET base_version=?", (source,))
    finally:
        conn.close()
    return project, db, tdir, tid


def _b09_rows(db):
    conn = dbmod.connect_readonly(str(db))
    try:
        return {name: [tuple(r) for r in conn.execute(f"SELECT * FROM {name} ORDER BY 1")]
                for name in ("project", "task", "task_event", "config")}
    finally:
        conn.close()


@pytest.mark.parametrize("operation", ["plan", "project_dry_run"])
def test_b09_migration_previews_do_not_switch_sqlite_journal_mode(tmp_path, monkeypatch, operation):
    import sqlite3
    from scripts.tests.v532_testutil import run_cli
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    conn = sqlite3.connect(db, isolation_level=None)
    assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    conn.close()
    before = (db.read_bytes(), db.stat().st_mtime_ns, _b09_rows(db))
    argv = (["task", "migration-plan", "--project", "v532-test"] if operation == "plan" else
            ["project", "upgrade-contract", "--id", "v532-test", "--dry-run"])
    rc, out, err = run_cli([*argv, "--db", str(db)])
    assert rc == 0, (out, err)
    assert (db.read_bytes(), db.stat().st_mtime_ns, _b09_rows(db)) == before


@pytest.mark.parametrize("source", ["99.0.0", "5.3.99", "0.0.0"])
def test_b09_unknown_contract_is_not_blindly_relabelled(tmp_path, monkeypatch, source):
    from scripts.tests.v532_testutil import run_cli, task_args
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch, source)
    before = _b09_rows(db)
    rc, out, err = run_cli(["project", "upgrade-contract", "--id", "v532-test", "--db", str(db)])
    assert rc != 0 and "UNSUPPORTED_MIGRATION_SOURCE" in out + err
    assert _b09_rows(db) == before
    conn = dbmod.connect(str(db))
    conn.execute("UPDATE project SET base_version=?", (active_version(),)); conn.close()
    before = _b09_rows(db)
    rc, out, err = run_cli(task_args(db, tdir, tid, "migrate"))
    assert rc != 0 and "UNSUPPORTED_MIGRATION_SOURCE" in out + err
    assert _b09_rows(db) == before
    rc, out, err = run_cli(["task", "migration-plan", "--project", "v532-test", "--db", str(db)])
    assert rc == 0, (out, err)
    row = json.loads(out)["tasks"][0]
    assert "MIGRATE_TO_ACTIVE" not in row["decision_options"]
    assert row["compatibility"]["migration_supported"] is False


@pytest.mark.parametrize("change", ["artifact", "event", "terminal"])
def test_b09_task_migration_rechecks_inputs_inside_writer_boundary(tmp_path, monkeypatch, change):
    from cli import transaction_commit
    from scripts.tests.v532_testutil import run_cli, task_args
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    rc, out, err = run_cli(["project", "upgrade-contract", "--id", "v532-test", "--db", str(db)])
    assert rc == 0, (out, err)
    original = transaction_commit._commit_with_recovery
    observed = {}
    def changed_before_lock(*args, **kwargs):
        if change == "artifact":
            p = tdir / "acceptance.md"
            p.write_bytes(p.read_bytes() + b"\nUser change while migration was preparing.\n")
        else:
            conn = dbmod.connect(str(db))
            if change == "terminal":
                conn.execute("UPDATE task SET current_state='COMPLETED' WHERE task_id=?", (tid,))
            else:
                _insert_event(conn, tid, "OBSERVATION", "human_owner", {}, summary="concurrent fact")
            conn.close()
        observed["rows"] = _b09_rows(db)
        observed["files"] = {p.name: p.read_bytes() for p in tdir.iterdir() if p.is_file()}
        return original(*args, **kwargs)
    monkeypatch.setattr(transaction_commit, "_commit_with_recovery", changed_before_lock)
    rc, out, err = run_cli(task_args(db, tdir, tid, "migrate"))
    assert rc != 0 and "MIGRATION_INPUT_CHANGED" in out + err, (rc, out, err)
    assert _b09_rows(db) == observed["rows"]
    assert {p.name: p.read_bytes() for p in tdir.iterdir() if p.is_file()} == observed["files"]
    assert not list(tdir.glob(".v511-bak-*"))


def test_b09_registry_output_failure_does_not_hide_committed_project_upgrade(tmp_path, monkeypatch):
    from scripts.tests.v532_testutil import run_cli
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    registry = tmp_path / 'registered.json'
    dbmod.register_project(project_id='v532-test', project_name='fixture', db_path=str(db),
                           root_path=str(project), base_version=B09_SOURCE, schema_version=1,
                           registry_path=str(registry))
    original = dbmod._write_registry_payload
    def fail(*args, **kwargs):
        raise OSError('registry volume unavailable')
    monkeypatch.setattr(dbmod, '_write_registry_payload', fail)
    args = ['project', 'upgrade-contract', '--id', 'v532-test', '--registry', str(registry), '--db', str(db)]
    rc, out, err = run_cli(args)
    assert rc == 0 and 'PENDING' in out + err and 'committed' in out + err, (rc, out, err)
    committed = _b09_rows(db)
    assert committed['project'][0][3] == active_version()
    monkeypatch.setattr(dbmod, '_write_registry_payload', original)
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    assert _b09_rows(db) == committed
    assert json.loads(registry.read_text())["projects"][0]["base_version"] == active_version()


@pytest.mark.parametrize('source', sorted(SOURCE_CONTRACTS))
def test_b09_known_source_plans_migrate_once_and_preserve_evidence(tmp_path, monkeypatch, source):
    from scripts.tests.v532_testutil import run_cli, task_args
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch, source)
    evidence = (tdir / 'evidence/check.txt').read_bytes()
    old_events = _b09_rows(db)['task_event']
    rc, out, err = run_cli(['task', 'migration-plan', '--project', 'v532-test', '--db', str(db)])
    assert rc == 0, (out, err)
    report = json.loads(out)
    assert report['read_only'] is True and report['active_version'] == active_version()
    assert report['tasks'][0]['compatibility']['runtime_compatible'] is False
    assert report['tasks'][0]['compatibility']['migration_supported'] is True
    assert report['tasks'][0]['planned_artifact_changes']
    assert _b09_rows(db)['task_event'] == old_events
    assert run_cli(['project', 'upgrade-contract', '--id', 'v532-test', '--db', str(db)])[0] == 0
    args = task_args(db, tdir, tid, 'migrate')
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    rows = _b09_rows(db)
    files = {str(p.relative_to(tdir)): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in tdir.rglob('*') if p.is_file()}
    rc, out, err = run_cli(args)
    assert rc == 0 and 'already current' in out, (rc, out, err)
    assert _b09_rows(db) == rows
    assert {str(p.relative_to(tdir)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in tdir.rglob('*') if p.is_file()} == files
    assert (tdir / 'evidence/check.txt').read_bytes() == evidence
    assert rows['task_event'][:len(old_events)] == old_events


def test_b09_explicit_artifact_migration_preserves_bom_newlines_and_history_prose(tmp_path, monkeypatch):
    from scripts.tests.v532_testutil import run_cli, task_args
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    artifact = tdir / 'tech-design.md'
    raw = (f'\ufeff---\r\nartifact: tech-design\r\nartifact_contract:\r\n  version: "{B09_SOURCE}"\r\n---\r\n'
           f'\r\nUser-owned discussion of {B09_SOURCE}; trailing spaces  \r\n\r\n').encode("utf-8")
    artifact.write_bytes(raw)
    assert run_cli(['project', 'upgrade-contract', '--id', 'v532-test', '--db', str(db)])[0] == 0
    rc, out, err = run_cli(task_args(db, tdir, tid, 'migrate'))
    assert rc == 0, (out, err)
    assert artifact.read_bytes() == raw.replace(f'version: "{B09_SOURCE}"'.encode(), f'version: "{active_version()}"'.encode())


def test_b09_migration_failure_rolls_back_and_can_be_retried(tmp_path, monkeypatch):
    from cli import transaction_commit
    from scripts.tests.v532_testutil import run_cli, task_args
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    assert run_cli(['project', 'upgrade-contract', '--id', 'v532-test', '--db', str(db)])[0] == 0
    before = _b09_rows(db)
    files = {str(p.relative_to(tdir)): p.read_bytes() for p in tdir.rglob('*') if p.is_file()}
    original = transaction_commit._stage_and_replace
    def fail_after_replace(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('simulated migration write interruption')
    monkeypatch.setattr(transaction_commit, '_stage_and_replace', fail_after_replace)
    args = task_args(db, tdir, tid, 'migrate')
    rc, out, err = run_cli(args)
    assert rc != 0 and 'rolled back' in out + err
    assert _b09_rows(db) == before
    assert {str(p.relative_to(tdir)): p.read_bytes() for p in tdir.rglob('*') if p.is_file()} == files
    monkeypatch.setattr(transaction_commit, '_stage_and_replace', original)
    assert run_cli(args)[0] == 0


@pytest.mark.parametrize('operation', ['project','task'])
def test_b09_schema_mismatch_cannot_be_relabelled_as_current(tmp_path, monkeypatch, operation):
    from scripts.tests.v532_testutil import run_cli, task_args
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    conn = dbmod.connect(str(db))
    if operation == 'task':
        conn.execute('UPDATE project SET base_version=?', (active_version(),))
    conn.execute('UPDATE schema_meta SET schema_version=2'); conn.close()
    before = _b09_rows(db)
    args = (['project','upgrade-contract','--id','v532-test','--db',str(db)] if operation=='project'
            else task_args(db,tdir,tid,'migrate'))
    rc, out, err = run_cli(args)
    assert rc != 0 and 'SCHEMA_MISMATCH' in out + err, (rc,out,err)
    assert _b09_rows(db) == before
