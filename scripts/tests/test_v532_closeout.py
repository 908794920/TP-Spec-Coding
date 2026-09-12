from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli import db as dbmod
from scripts.tests.v532_testutil import make_runtime, run_cli, task_args


def _write_acceptance(task_dir, rows, *, visual: bool = False) -> None:
    table = [
        "# 验收条件与证据矩阵",
        "",
        "| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    table.extend(
        f"| {ac} | {condition} | task.md | L1 | 人工操作 | {evidence} | {witness} | {verdict} |"
        for ac, condition, evidence, witness, verdict in rows
    )
    yaml_lines = [
        "```yaml",
        "page_verification:",
        "  mode: human" if visual else "  mode: NOT_REQUIRED",
        "  human_witness: pending",
        '  witness_evidence: ""',
    ]
    if visual:
        yaml_lines.extend([
            "  visual:",
            "    required: true",
            "    acceptance_refs: [AC-UI-01]",
            '    viewports: ["375x812"]',
            '    routes: ["/application/create"]',
            '    reference_assets: []',
            "    required_states: [normal]",
            '    evidence_manifest: "evidence/visual/manifest.json"',
        ])
    yaml_lines.extend([
        "deferred_acceptance: []",
        "owner_waivers: []",
        "database_operations: []",
        "```",
        "",
    ])
    (task_dir / "acceptance.md").write_text(
        "\n".join(table + [""] + yaml_lines), encoding="utf-8", newline="\n"
    )


def _development(project, db, task_dir, task_id):
    return run_cli(task_args(
        db, task_dir, task_id, "checkpoint",
        "--actor", "tp-development-engineer",
        "--phase", "development",
        "--summary", "implemented current product subject",
        "--repo-root", str(project),
    ))


def _accept(db, task_dir, task_id, *extra):
    return run_cli(task_args(
        db, task_dir, task_id, "acceptance-override",
        "--actor", "human_owner",
        "--mode", "accept",
        "--source", "用户确认当前任务成果已按声明范围验收完成",
        *extra,
    ))


def _event_rows(db, task_id, event_type=None):
    with dbmod.connect_readonly(str(db)) as conn:
        if event_type:
            return conn.execute(
                "SELECT * FROM task_event WHERE task_id=? AND event_type=? ORDER BY id",
                (task_id, event_type),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()


def test_owner_accept_records_human_result_and_replays(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)

    args = ["--scope", "human-pending", "--request-id", "owner-accept-1"]
    rc, out, err = _accept(db, task_dir, task_id, *args)
    assert rc == 0, (out, err)
    acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "| AC-01 | 用户确认当前成果 | task.md | L1 | 人工操作 | evidence/owner-acceptance/owner-accept-1.md | human | PASS |" in acceptance
    assert "human_witness: confirmed" in acceptance
    assert (task_dir / "evidence/owner-acceptance/owner-accept-1.md").is_file()

    events = _event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")
    assert len(events) == 1
    detail = json.loads(events[0]["detail_json"])
    assert detail["mode"] == "accept"
    assert detail["acs"] == ["AC-01"]
    assert detail["decision_source"]["kind"] == "human_owner_statement"
    assert detail["change_set_id"]
    assert detail["subject_digest"]

    rc, out, err = _accept(db, task_dir, task_id, *args)
    assert rc == 0, (out, err)
    assert "replayed" in out.lower()
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 1

    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", "owner-accept-new-id")
    assert rc != 0
    assert "only applies" in out + err
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 1


def test_owner_accept_rechecks_request_id_inside_writer_lock(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    original_acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--scope", "human-pending", "--request-id", "owner-accept-lock")
    assert rc == 0, (out, err)

    # Simulate the request having crossed the initial read while another writer
    # committed it, so the second lookup must happen under BEGIN IMMEDIATE.
    (task_dir / "acceptance.md").write_text(original_acceptance, encoding="utf-8", newline="\n")
    from cli import task_cmd
    original_lookup = task_cmd._owner_acceptance_replay
    calls = 0

    def skip_initial_lookup(conn, current_task_id, request):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original_lookup(conn, current_task_id, request)

    monkeypatch.setattr(task_cmd, "_owner_acceptance_replay", skip_initial_lookup)
    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "human-pending", "--request-id", "owner-accept-lock",
    )
    assert rc == 0, (out, err)
    assert json.loads(out)["replayed"] is True
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 1
    assert (task_dir / "acceptance.md").read_text(encoding="utf-8") == original_acceptance


def test_owner_accept_replays_after_a_concurrent_commit_changes_selection(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    request_id = "owner-accept-selection-race"
    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", request_id)
    assert rc == 0, (out, err)

    from cli import task_cmd
    original_lookup = task_cmd._owner_acceptance_replay
    calls = 0

    def skip_initial_lookup(conn, current_task_id, request):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original_lookup(conn, current_task_id, request)

    monkeypatch.setattr(task_cmd, "_owner_acceptance_replay", skip_initial_lookup)
    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", request_id)
    assert rc == 0, (out, err)
    assert json.loads(out)["replayed"] is True
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 1


def test_new_owner_acceptance_supersedes_old_waiver_without_deleting_history(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "acceptance-override",
        "--actor", "human_owner", "--mode", "waive", "--ac", "AC-01",
        "--reason", "旧记录中的明确豁免", "--residual-risk", "旧环境未验收",
    ))
    assert rc == 0, (out, err)
    rc, out, err = _accept(
        db, task_dir, task_id,
        "--ac", "AC-01", "--request-id", "owner-accept-after-waive",
    )
    assert rc == 0, (out, err)

    acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "| AC-01 | 用户确认当前成果 | task.md | L1 | 人工操作 | evidence/owner-acceptance/owner-accept-after-waive.md | human | PASS |" in acceptance
    assert "owner_waivers:" in acceptance and "旧记录中的明确豁免" in acceptance
    with dbmod.connect_readonly(str(db)) as conn:
        rows = conn.execute(
            "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='OWNER_ACCEPTANCE_DECISION' ORDER BY id",
            (task_id,),
        ).fetchall()
    assert [json.loads(row[0])["mode"] for row in rows] == ["waive", "accept"]


def test_stale_owner_acceptance_can_be_renewed_after_new_development_change_set(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", "owner-accept-old")
    assert rc == 0, (out, err)

    (project / "app.txt").write_text("v2\n", encoding="utf-8")
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", "owner-accept-renewed")
    assert rc == 0, (out, err)
    assert json.loads(out)["request_id"] == "owner-accept-renewed"
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 2


def test_stale_owner_acceptance_can_be_renewed_after_prior_waiver(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "acceptance-override", "--actor", "human_owner",
        "--mode", "waive", "--ac", "AC-01", "--reason", "旧记录中的明确豁免",
        "--residual-risk", "旧环境未验收",
    ))
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", "owner-accept-after-waive-1")
    assert rc == 0, (out, err)

    (project / "app.txt").write_text("v2\n", encoding="utf-8")
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--ac", "AC-01", "--request-id", "owner-accept-after-waive-2")
    assert rc == 0, (out, err)
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 3


def test_same_owner_request_id_with_different_payload_is_rejected(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--scope", "human-pending", "--request-id", "owner-accept-conflict")
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "acceptance-override",
        "--actor", "human_owner", "--mode", "accept", "--ac", "AC-01",
        "--source", "另一份不同的 Owner 声明", "--request-id", "owner-accept-conflict",
    ))
    assert rc != 0
    assert "REQUEST_ID_CONFLICT" in out + err
    assert len(_event_rows(db, task_id, "OWNER_ACCEPTANCE_DECISION")) == 1


def test_owner_accept_on_blocked_human_wait_resumes_only_that_wait(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "block",
        "--actor", "tp-test-engineer",
        "--reason", "等待 Owner 对当前成果进行人工验收",
        "--kind", "human_acceptance",
        "--condition", "Owner 确认 AC-01 的当前成果",
    ))
    assert rc == 0, (out, err)

    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "human-pending", "--request-id", "owner-accept-blocked",
    )
    assert rc == 0, (out, err)
    with dbmod.connect_readonly(str(db)) as conn:
        state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()[0]
    assert state == "ACTIVE"
    states = _event_rows(db, task_id, "STATE")
    assert any(row["from_state"] == "BLOCKED" and row["to_state"] == "ACTIVE" for row in states)


def test_resume_rejects_a_replaced_wait_when_bound_to_owner_acceptance(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "block", "--actor", "tp-test-engineer",
        "--reason", "等待 Owner 对当前成果进行人工验收", "--kind", "human_acceptance",
        "--condition", "Owner 确认 AC-01 的当前成果",
    ))
    assert rc == 0, (out, err)

    from cli import record_first, waiting
    with dbmod.connect_readonly(str(db)) as conn:
        original_wait = waiting.load_wait(conn, task_id)
        task = conn.execute("SELECT current_stage FROM task WHERE task_id=?", (task_id,)).fetchone()
    replacement = {
        "kind": "permission", "responsibility": "human_owner",
        "condition": "取得指定环境权限", "requires_tasks": [],
        "prerequisite_evidence": [],
    }
    detail = record_first._semantic_detail(
        "BLOCKER", "BLOCK", "RACE-BLOCK", "BLOCKED", transaction_id="race-tx",
        phase=str(task["current_stage"]), reason="等待额外权限", reason_code="BLOCKED",
        waiting=replacement,
    )
    with dbmod.connect(str(db)) as conn:
        now = dbmod.now_iso()
        conn.execute(
            "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (task_id, "BLOCKER", "tp-test-engineer", "等待额外权限", detail, record_first.active_version(), now),
        )
        conn.execute(
            "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, "STATE", "BLOCKED", "BLOCKED", task["current_stage"], task["current_stage"],
             "tp-test-engineer", "等待额外权限", detail, record_first.active_version(), now),
        )
        conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, task_id))

    with pytest.raises(ValueError, match="WAIT_PREREQUISITE_CHANGED"):
        record_first.resume(
            task_id=task_id, task_dir=str(task_dir), actor="human_owner",
            summary="Owner acceptance resolved the human acceptance wait",
            phase="development", resolution_evidence=["evidence/check.txt"], db=str(db),
            expected_block_event_id=original_wait["block_event_id"],
            expected_wait_kind=original_wait["kind"],
        )


def test_visual_owner_acceptance_allows_full_verify_without_manifest(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-UI-01", "用户确认页面成果", "", "human", "PENDING")], visual=True)
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)

    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "visual", "--ac", "AC-UI-01", "--request-id", "owner-accept-visual",
    )
    assert rc == 0, (out, err)
    (task_dir / "evidence/technical.txt").write_text("technical verification\n", encoding="utf-8")
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "verify",
        "--actor", "tp-test-engineer", "--decision", "PASS",
        "--summary", "technical evidence plus Owner visual acceptance",
        "--evidence", "evidence/technical.txt",
    ))
    assert rc == 0, (out, err)
    assert not (task_dir / "evidence/visual/manifest.json").exists()
    detail = json.loads(_event_rows(db, task_id, "VERIFICATION_COMPLETED")[-1]["detail_json"])
    assert "visual_verification" not in detail


def test_visual_owner_receipt_is_rechecked_before_verification_commit(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-UI-01", "用户确认页面成果", "", "human", "PENDING")], visual=True)
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    request_id = "owner-accept-visual-bound"
    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "visual", "--ac", "AC-UI-01", "--request-id", request_id,
    )
    assert rc == 0, (out, err)
    (task_dir / "evidence/technical.txt").write_text("technical verification\n", encoding="utf-8")

    from cli import recording
    original_validate = recording.validate_bound_items
    deleted = False

    def delete_owner_receipt_before_writer_validation(base, items, *args, **kwargs):
        nonlocal deleted
        if not deleted:
            (base / "evidence/owner-acceptance" / f"{request_id}.md").unlink()
            deleted = True
        return original_validate(base, items, *args, **kwargs)

    monkeypatch.setattr(recording, "validate_bound_items", delete_owner_receipt_before_writer_validation)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "verify", "--actor", "tp-test-engineer",
        "--decision", "PASS", "--summary", "technical evidence plus Owner visual acceptance",
        "--evidence", "evidence/technical.txt",
    ))
    assert rc != 0
    assert "EVIDENCE_CHANGED_BEFORE_COMMIT" in out + err
    assert not _event_rows(db, task_id, "VERIFICATION_COMPLETED")


def test_visual_owner_scope_does_not_select_unrelated_human_acceptance(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [
        ("AC-UI-01", "用户确认页面成果", "", "human", "PENDING"),
        ("AC-OTHER", "用户确认非页面成果", "", "human", "PENDING"),
    ], visual=True)
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)

    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "visual", "--ac", "AC-UI-01", "--request-id", "owner-accept-visual-only",
    )
    assert rc == 0, (out, err)
    assert json.loads(out)["acs"] == ["AC-UI-01"]
    acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "| AC-OTHER | 用户确认非页面成果 | task.md | L1 | 人工操作 |  | human | PENDING |" in acceptance


def test_visual_owner_scope_requires_nonempty_declared_refs(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-UI-01", "用户确认页面成果", "", "human", "PENDING")], visual=True)
    acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    acceptance = acceptance.replace("acceptance_refs: [AC-UI-01]", "acceptance_refs: []")
    (task_dir / "acceptance.md").write_text(acceptance, encoding="utf-8", newline="\n")
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)

    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "visual", "--ac", "AC-UI-01", "--request-id", "owner-accept-visual-undeclared",
    )
    assert rc != 0
    assert "non-empty" in out + err


def test_partial_acceptance_does_not_clear_unrelated_permission_wait(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [
        ("AC-01", "已确认的成果", "", "human", "PENDING"),
        ("AC-02", "仍待确认的成果", "", "human", "PENDING"),
    ])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "block",
        "--actor", "tp-test-engineer",
        "--reason", "等待额外权限",
        "--kind", "permission",
        "--condition", "取得指定环境权限",
    ))
    assert rc == 0, (out, err)

    rc, out, err = _accept(
        db, task_dir, task_id,
        "--ac", "AC-01", "--request-id", "owner-accept-partial",
    )
    assert rc == 0, (out, err)
    with dbmod.connect_readonly(str(db)) as conn:
        state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()[0]
    assert state == "BLOCKED"
    acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "| AC-01 | 已确认的成果 | task.md | L1 | 人工操作 | evidence/owner-acceptance/owner-accept-partial.md | human | PASS |" in acceptance
    assert "| AC-02 | 仍待确认的成果 | task.md | L1 | 人工操作 |  | human | PENDING |" in acceptance
    assert not any(
        row["from_state"] == "BLOCKED" and row["to_state"] == "ACTIVE"
        for row in _event_rows(db, task_id, "STATE")
    )


def test_completion_check_is_read_only_and_acceptance_can_complete(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--scope", "human-pending", "--request-id", "owner-accept-complete")
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "verify",
        "--actor", "tp-test-engineer", "--decision", "PASS",
        "--summary", "verified", "--evidence", "evidence/check.txt",
    ))
    assert rc == 0, (out, err)

    before_events = len(_event_rows(db, task_id))
    before_status = (task_dir / "status.yaml").read_bytes()
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "complete", "--check", "--db", str(db),
    ))
    assert rc == 0, (out, err)
    check = json.loads(out)
    assert check["ready"] is True
    assert len(_event_rows(db, task_id)) == before_events
    assert (task_dir / "status.yaml").read_bytes() == before_status

    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "complete", "--actor", "tp-development-engineer",
        "--summary", "Owner accepted current result",
    ))
    assert rc == 0, (out, err)
    with dbmod.connect_readonly(str(db)) as conn:
        state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (task_id,)).fetchone()[0]
    assert state == "COMPLETED"


def test_workflow_route_exposes_the_same_effective_owner_acceptance(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-UI-01", "用户确认页面成果", "", "human", "PENDING")], visual=True)
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(
        db, task_dir, task_id,
        "--scope", "visual", "--ac", "AC-UI-01", "--request-id", "owner-accept-route",
    )
    assert rc == 0, (out, err)

    rc, out, err = run_cli(["workflow", "next", "--task", task_id, "--db", str(db), "--json"])
    assert rc == 0, (out, err)
    route = json.loads(out)
    effective = route["context"]["validation"]["effective_owner_acceptance"]
    assert effective["accepted_acs"] == ["AC-UI-01"]
    assert effective["visual_acs"] == ["AC-UI-01"]


def test_tampered_owner_acceptance_binding_blocks_completion_preflight(tmp_path, monkeypatch):
    project, db, task_dir, task_id = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-01", "用户确认当前成果", "", "human", "PENDING")])
    rc, out, err = _development(project, db, task_dir, task_id)
    assert rc == 0, (out, err)
    rc, out, err = _accept(db, task_dir, task_id, "--scope", "human-pending", "--request-id", "owner-accept-tamper")
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(
        db, task_dir, task_id, "verify", "--actor", "tp-test-engineer",
        "--decision", "PASS", "--summary", "verified", "--evidence", "evidence/check.txt",
    ))
    assert rc == 0, (out, err)

    with dbmod.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT id, detail_json FROM task_event WHERE task_id=? AND event_type='OWNER_ACCEPTANCE_DECISION'",
            (task_id,),
        ).fetchone()
        detail = json.loads(row["detail_json"])
        detail["subject_digest"] = "0" * 64
        conn.execute("UPDATE task_event SET detail_json=? WHERE id=?", (json.dumps(detail), row["id"]))
        conn.commit()

    rc, out, err = run_cli(task_args(db, task_dir, task_id, "complete", "--check"))
    assert rc != 0
    assert "OWNER_ACCEPTANCE" in out + err


def test_visual_owner_scope_references_must_be_a_known_acceptance_list(tmp_path, monkeypatch):
    _, _, task_dir, _ = make_runtime(tmp_path, monkeypatch)
    _write_acceptance(task_dir, [("AC-UI-01", "用户确认页面成果", "", "human", "PENDING")], visual=True)
    acceptance = (task_dir / "acceptance.md").read_text(encoding="utf-8")
    acceptance = acceptance.replace("acceptance_refs: [AC-UI-01]", "acceptance_refs: [AC-UNKNOWN]")
    (task_dir / "acceptance.md").write_text(acceptance, encoding="utf-8", newline="\n")
    from cli import yaml_checks
    result = yaml_checks.check_acceptance_yaml(acceptance, enforce_completion=False, allow_human_pending=True)
    assert not result.ok
    assert any("acceptance_refs" in issue for issue in result.issues)


def test_closeout_guidance_describes_owner_acceptance_boundary():
    root = Path(__file__).resolve().parents[2]
    template = (root / "templates/5.3.2/acceptance.md").read_text(encoding="utf-8")
    lifecycle = (root / "docs/agents/tp-software-lifecycle.md").read_text(encoding="utf-8")
    visual_qa = (root / "skills/capabilities/testing-strategy/references/visual-qa.md").read_text(encoding="utf-8")
    test_engineer = (root / "skills/roles/tp-test-engineer/SKILL.md").read_text(encoding="utf-8")

    for text in (template, lifecycle, visual_qa, test_engineer):
        assert "--mode accept" in text
        assert "human_owner" in text
    assert "    acceptance_refs: []" in template
    assert "不会生成或伪造 Visual Manifest" in template
    assert "不解除其他 blocker" in template
    assert "BLOCKED" in lifecycle


def test_owner_acceptance_receipt_path_keeps_request_ids_distinct():
    from cli.task_cmd import _owner_acceptance_source_path

    assert _owner_acceptance_source_path("owner:a") != _owner_acceptance_source_path("owner_a")
