# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli import db as dbmod
from scripts.tests.runtime_testutil import run
from scripts.tests.test_v529_visual_verification import VisualCase


def _write_no_acceptance_required(task_dir: Path) -> None:
    (task_dir / "acceptance.md").write_text(
        "# 验收条件与证据矩阵\n\n"
        "```yaml\n"
        "no_acceptance_required:\n"
        "  declared: true\n"
        "  reason: 该测试只验证 Runtime 投影和终态完整性，不包含业务验收项\n"
        "page_verification:\n"
        "  mode: NOT_REQUIRED\n"
        "  human_witness: pending\n"
        "  witness_evidence: \"\"\n"
        "deferred_acceptance: []\n"
        "owner_waivers: []\n"
        "database_operations: []\n"
        "```\n",
        encoding="utf-8",
        newline="\n",
    )


def _verify_plain(case: VisualCase, task_id: str, task_dir: Path) -> dict:
    evidence = task_dir / "evidence" / "verification.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("verified\n", encoding="utf-8", newline="\n")
    rc, out, err = case.verify(task_id, task_dir, "evidence/verification.txt")
    assert rc == 0, (out, err)
    return json.loads(out)


def _prepare_l2_reviewed(case: VisualCase, task_id: str) -> Path:
    task_dir = case.create_task(task_id, visual=False)
    case.prepare_development(task_id, task_dir)
    _verify_plain(case, task_id, task_dir)
    rc, out, err = case.review(task_id, task_dir)
    assert rc == 0, (out, err)
    return task_dir


def _complete_l0(case: VisualCase, task_id: str) -> Path:
    task_dir = case.create_task(task_id, visual=False)
    _write_no_acceptance_required(task_dir)
    evidence = task_dir / "evidence" / "terminal-evidence.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("terminal evidence\n", encoding="utf-8", newline="\n")
    case.prepare_development(task_id, task_dir)
    rc, out, err = case.call(
        "task", "complete", "--task", task_id, "--task-dir", str(task_dir),
        "--actor", "tp-development-engineer", "--summary", "task done",
    )
    assert rc == 0, (out, err)
    return task_dir


def test_scope_change_requires_human_owner_and_projects_to_status():
    case = VisualCase(level="L0")
    try:
        task_id = "TASK-V529-SCOPE"
        task_dir = case.create_task(task_id, visual=False)

        rc, out, err = case.call(
            "task", "scope-change", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-product-manager", "--scope-id", "SC-01", "--summary", "扩大到详情页",
        )
        assert rc != 0
        assert "human_owner" in out + err

        rc, out, err = case.call(
            "task", "scope-change", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "human_owner", "--scope-id", "SC-01", "--summary", "扩大到详情页",
        )
        assert rc == 0, (out, err)
        status = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert "SC-01" in status
        assert "扩大到详情页" in status

        conn = dbmod.connect(str(case.db))
        try:
            row = conn.execute(
                "SELECT actor_role, detail_json FROM task_event WHERE task_id=? AND event_type='SCOPE_CHANGE' ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        detail = json.loads(row["detail_json"])
        assert row["actor_role"] == "human_owner"
        assert detail["scope_id"] == "SC-01"
        assert detail["summary"] == "扩大到详情页"
        assert detail["producer"] == "task_scope_change"
        assert detail["transaction_id"]
        assert detail["created_at"]
    finally:
        case.close()


def test_status_projects_active_delivery_blocker():
    case = VisualCase(level="L2")
    try:
        task_id = "TASK-V529-DELIVERY-BLOCKER"
        task_dir = _prepare_l2_reviewed(case, task_id)
        rc, out, err = case.call(
            "task", "delivery-converge", "--task", task_id, "--task-dir", str(task_dir),
            "--delivery-status", "BLOCKED",
            "--reason", "缺少真实登录态浏览器会话",
            "--blocker-kind", "HUMAN_DECISION",
            "--responsibility", "human_owner",
            "--recovery-condition", "真实登录态和权限数据可用后重新执行浏览器验收",
        )
        assert rc == 0, (out, err)
        status = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert 'current_state: "ACTIVE"' in status
        assert "缺少真实登录态浏览器会话" in status
        assert "HUMAN_DECISION" in status
    finally:
        case.close()


def test_latest_negative_review_is_projected_until_new_valid_pass():
    case = VisualCase(level="L2")
    try:
        task_id = "TASK-V529-FINDING"
        task_dir = case.create_task(task_id, visual=False)
        case.prepare_development(task_id, task_dir)
        _verify_plain(case, task_id, task_dir)

        rc, out, err = case.call(
            "review", "record", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "NEEDS_FIX",
            "--summary", "事务边界错误，需要开发修复",
        )
        assert rc == 0, (out, err)
        status = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert "事务边界错误，需要开发修复" in status

        case.checkpoint(task_id, task_dir, "tp-development-engineer", "development", repo=True)
        _verify_plain(case, task_id, task_dir)
        rc, out, err = case.review(task_id, task_dir)
        assert rc == 0, (out, err)
        status = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert "事务边界错误，需要开发修复" not in status
    finally:
        case.close()


def test_quality_facts_mark_change_set_dependent_results_stale_after_repo_mutation():
    case = VisualCase(level="L2")
    try:
        task_id = "TASK-V529-QUALITY-STALE"
        task_dir = _prepare_l2_reviewed(case, task_id)
        (case.project / "src" / "app.txt").write_text("v2\n", encoding="utf-8", newline="\n")
        rc, out, err = case.call(
            "projection", "rebuild", "--task", task_id, "--task-dir", str(task_dir),
        )
        assert rc == 0, (out, err)
        status = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert 'development: "STALE"' in status
        assert 'verification: "PASS_STALE"' in status
        assert 'review: "PASS_STALE"' in status
    finally:
        case.close()


def test_completion_rolls_back_when_terminal_manifest_cannot_be_built():
    case = VisualCase(level="L0")
    try:
        task_id = "TASK-V529-TERMINAL-ATOMIC"
        task_dir = case.create_task(task_id, visual=False)
        _write_no_acceptance_required(task_dir)
        case.prepare_development(task_id, task_dir)
        status_before = (task_dir / "status.yaml").read_bytes()
        events_before = (task_dir / "events.jsonl").read_bytes()

        with patch(
            "cli.transaction_commit.build_terminal_manifest_text",
            side_effect=RuntimeError("manifest boom"),
        ):
            rc, out, err = case.call(
                "task", "complete", "--task", task_id, "--task-dir", str(task_dir),
                "--actor", "tp-development-engineer", "--summary", "task done",
            )

        assert rc != 0
        assert "manifest boom" in out + err
        assert (task_dir / "status.yaml").read_bytes() == status_before
        assert (task_dir / "events.jsonl").read_bytes() == events_before
        assert not (task_dir / "generated" / "final-result.md").exists()
        assert not (task_dir / "generated" / "terminal-manifest.json").exists()
        conn = dbmod.connect(str(case.db))
        try:
            state = conn.execute(
                "SELECT current_state FROM task WHERE task_id=?", (task_id,)
            ).fetchone()["current_state"]
        finally:
            conn.close()
        assert state == "ACTIVE"
    finally:
        case.close()


def test_terminal_manifest_is_created_with_final_result_and_task_evidence():
    case = VisualCase(level="L0")
    try:
        task_id = "TASK-V529-TERMINAL-MANIFEST"
        task_dir = _complete_l0(case, task_id)
        manifest_path = task_dir / "generated" / "terminal-manifest.json"
        assert manifest_path.is_file()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["schema"] == "tp-spec.terminal-manifest/v1"
        assert data["task_id"] == task_id
        files = {item["path"]: item for item in data["files"]}
        assert "generated/final-result.md" in files
        assert "evidence/terminal-evidence.txt" in files
        assert "generated/terminal-manifest.json" not in files
        assert all(item["sha256"].startswith("sha256:") for item in files.values())
    finally:
        case.close()


def test_terminal_check_reports_added_modified_and_deleted_artifacts():
    case = VisualCase(level="L0")
    try:
        task_id = "TASK-V529-TERMINAL-DRIFT"
        task_dir = _complete_l0(case, task_id)
        (task_dir / "docs").mkdir(exist_ok=True)
        (task_dir / "docs" / "late-plan.md").write_text("late\n", encoding="utf-8", newline="\n")
        (task_dir / "task.md").write_text("modified after completion\n", encoding="utf-8", newline="\n")
        (task_dir / "evidence" / "terminal-evidence.txt").unlink()

        rc, out, err = case.call(
            "task", "terminal-check", "--task", task_id, "--task-dir", str(task_dir),
        )
        assert rc == 0, (out, err)
        result = json.loads(out)
        assert result["status"] == "DRIFTED"
        assert "docs/late-plan.md" in result["added"]
        assert "task.md" in result["modified"]
        assert "evidence/terminal-evidence.txt" in result["deleted"]
    finally:
        case.close()


def test_terminal_check_is_read_only_and_never_reopens_task():
    case = VisualCase(level="L0")
    try:
        task_id = "TASK-V529-TERMINAL-READONLY"
        task_dir = _complete_l0(case, task_id)
        (task_dir / "docs").mkdir(exist_ok=True)
        (task_dir / "docs" / "late-plan.md").write_text("late\n", encoding="utf-8", newline="\n")
        status_before = (task_dir / "status.yaml").read_bytes()
        events_before = (task_dir / "events.jsonl").read_bytes()
        manifest_before = (task_dir / "generated" / "terminal-manifest.json").read_bytes()
        conn = dbmod.connect(str(case.db))
        try:
            before = conn.execute(
                "SELECT current_state, updated_at FROM task WHERE task_id=?", (task_id,)
            ).fetchone()
            event_count_before = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (task_id,)
            ).fetchone()["c"]
        finally:
            conn.close()

        rc, out, err = case.call(
            "task", "terminal-check", "--task", task_id, "--task-dir", str(task_dir),
        )
        assert rc == 0, (out, err)
        assert json.loads(out)["status"] == "DRIFTED"
        assert (task_dir / "status.yaml").read_bytes() == status_before
        assert (task_dir / "events.jsonl").read_bytes() == events_before
        assert (task_dir / "generated" / "terminal-manifest.json").read_bytes() == manifest_before
        conn = dbmod.connect(str(case.db))
        try:
            after = conn.execute(
                "SELECT current_state, updated_at FROM task WHERE task_id=?", (task_id,)
            ).fetchone()
            event_count_after = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (task_id,)
            ).fetchone()["c"]
        finally:
            conn.close()
        assert dict(after) == dict(before)
        assert after["current_state"] == "COMPLETED"
        assert event_count_after == event_count_before
    finally:
        case.close()


def test_final_result_exposes_quality_facts_and_terminal_snapshot_status():
    case = VisualCase(level="L2")
    try:
        task_id = "TASK-V529-FINAL-QUALITY"
        task_dir = case.create_task(task_id, visual=False)
        _write_no_acceptance_required(task_dir)
        case.prepare_development(task_id, task_dir)
        _verify_plain(case, task_id, task_dir)
        rc, out, err = case.review(task_id, task_dir)
        assert rc == 0, (out, err)
        rc, out, err = case.call(
            "task", "delivery-converge", "--task", task_id, "--task-dir", str(task_dir),
            "--delivery-status", "READY",
            "--reason", "验证和复审均通过，当前变更可交付。",
        )
        assert rc == 0, (out, err)
        rc, out, err = case.call(
            "task", "complete", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-integration-engineer", "--summary", "delivery complete",
        )
        assert rc == 0, (out, err)
        final = (task_dir / "generated" / "final-result.md").read_text(encoding="utf-8")
        assert "Verification：PASS" in final
        assert "Code Review：PASS" in final
        assert "Delivery：READY" in final
        assert "Knowledge：NOT_REQUIRED" in final
        assert "终态完整性：CAPTURED" in final
    finally:
        case.close()
