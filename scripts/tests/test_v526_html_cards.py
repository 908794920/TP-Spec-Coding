# -*- coding: utf-8 -*-
"""V5.3.3 read-only HTML information card regression tests."""
from __future__ import annotations

import contextlib
import io
import json
import re
from argparse import Namespace
from pathlib import Path

import yaml

from cli import db as dbmod
from cli import main as climain
from scripts.tests.cli_testutil import invoke_main
from cli.version import active_version

BASE = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _run(argv: list[str]):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = invoke_main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def _install_fixture(tmp_path: Path, monkeypatch, *, with_config: bool = True):
    user_root = tmp_path / "user" / ".tp-spec"
    workspace = tmp_path / "workspace"
    wiki_root = tmp_path / "wiki-vault"
    knowledge_root = tmp_path / "knowledge-vault"
    workspace.mkdir(parents=True)
    wiki_root.mkdir(parents=True)
    knowledge_root.mkdir(parents=True)
    monkeypatch.setenv("TP_SPEC_USER_ROOT", str(user_root))
    monkeypatch.delenv("TP_SPEC_REGISTRY", raising=False)
    monkeypatch.delenv("TP_SPEC_INSTALLATION_CONFIG", raising=False)
    monkeypatch.delenv("TP_SPEC_WORKSPACE_INVENTORY", raising=False)
    if with_config:
        _write(
            user_root / "installation.yaml",
            yaml.safe_dump(
                {
                    "schema": "tp-spec.installation/v1",
                    "base": {"root": str(BASE)},
                    "systems": {
                        "wiki": {"root": str(wiki_root)},
                        "knowledge": {"root": str(knowledge_root)},
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )
        _write(
            user_root / "workspaces.yaml",
            yaml.safe_dump(
                {
                    "schema": "tp-spec.workspace-inventory/v1",
                    "workspaces": [{"id": "demo-workspace", "root": str(workspace)}],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )
    return user_root, workspace, wiki_root, knowledge_root


def _runtime_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    include_binding: bool = True,
    include_active: bool = True,
):
    user_root, workspace, wiki_root, knowledge_root = _install_fixture(tmp_path, monkeypatch)
    project_id = "demo-project"
    db_path = workspace / ".tp-spec" / "db" / "demo.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(str(db_path))
    dbmod.init_schema(conn)
    now = dbmod.now_iso()
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (project_id, "Demo Project", str(workspace), active_version(), 1, now, now),
        )
        if include_active:
            conn.execute(
                "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("TASK-ACTIVE", project_id, "Active task", "L1", "L1", "ACTIVE", "development", "tp-development-engineer", active_version(), now, now),
            )
            conn.execute(
                "INSERT INTO task_event(task_id,event_type,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                ("TASK-ACTIVE", "FACT", "requirement", "requirement", "tp-product-manager", "Requirement confirmed", json.dumps({"schema":"tp-spec.event-semantics/v1","operation":"CHECKPOINT","phase":"requirement","result_status":"COMPLETED","producer":"record-first"}), active_version(), now),
            )
            conn.execute(
                "INSERT INTO task_event(task_id,event_type,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                ("TASK-ACTIVE", "FACT", "architecture", "architecture", "tp-software-architect", "Architecture complete", json.dumps({"schema":"tp-spec.event-semantics/v1","operation":"CHECKPOINT","phase":"architecture","result_status":"COMPLETED","producer":"record-first"}), active_version(), now),
            )
        conn.execute(
            "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("TASK-BLOCKED", project_id, "Blocked task", "L1", "L1", "BLOCKED", "verification", "tp-test-engineer", active_version(), now, now),
        )
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-BLOCKED", "BLOCKER", "tp-test-engineer", "External environment unavailable", json.dumps({"operation": "BLOCK", "phase": "verification"}), active_version(), now),
        )
        conn.execute(
            "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("TASK-DONE", project_id, "Completed task", "L1", "L1", "COMPLETED", "delivery", "tp-integration-engineer", active_version(), now, now, now),
        )
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,from_stage,to_stage,actor_role,summary,detail_json,evidence_path,workflow_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("TASK-DONE", "VERIFICATION_COMPLETED", "development", "verification", "tp-test-engineer", "Verification needs fix", json.dumps({"decision": "NEEDS_FIX", "evidence": ["evidence/test.txt"]}), "evidence/test.txt", active_version(), now),
        )
    conn.close()

    registry = {
        "projects": [
            {
                "project_id": project_id,
                "project_name": "Demo Project",
                "root_path": str(workspace),
                "db_path": str(db_path),
                "base_version": active_version(),
                "schema_version": 1,
            }
        ]
    }
    _write(user_root / "registry.local.json", json.dumps(registry, ensure_ascii=False, indent=2) + "\n")

    if include_binding:
        _write(
            workspace / ".tp-spec" / "config" / "project-binding.yaml",
            yaml.safe_dump(
                {
                    "schema": "tp-spec.project-binding/v1",
                    "base_version": active_version(),
                    "project": {"id": project_id, "wiki_id": "demo-wiki", "knowledge_id": project_id},
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )

    _write(
        wiki_root / "00-system" / "repo-registry.yaml",
        yaml.safe_dump(
            {
                "version": 1,
                "workspaces": [
                    {
                        "id": "demo-wiki",
                        "workspace_root": str(workspace),
                        "repos": [{"id": "demo-repo", "repo_root": str(workspace), "enabled": True}],
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    (wiki_root / "projects" / "demo-wiki" / "demo-repo").mkdir(parents=True, exist_ok=True)
    _write(
        knowledge_root / "00-system" / "project-registry.yaml",
        yaml.safe_dump(
            {
                "registry_version": "1.0.0",
                "projects": [
                    {"id": project_id, "status": "active", "workspace_roots": [str(workspace)]}
                ],
                "shared_scopes": [{"id": "shared-engineering", "status": "active"}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    (knowledge_root / "10-projects" / project_id).mkdir(parents=True, exist_ok=True)
    (knowledge_root / "20-shared").mkdir(parents=True, exist_ok=True)
    return {
        "user_root": user_root,
        "workspace": workspace,
        "wiki_root": wiki_root,
        "knowledge_root": knowledge_root,
        "project_id": project_id,
        "db_path": db_path,
    }


def test_global_snapshot_reads_fixture_without_secrets(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    _write(
        fx["user_root"] / "autonomy" / "profiles" / "demo-autonomy.yaml",
        yaml.safe_dump(
            {
                "schema": "tp-spec.autonomy-profile/v1",
                "profile_id": "demo-autonomy",
                "enabled": True,
                "canonical": {"workspace_root": str(BASE), "project_id": "demo-project"},
                "autonomous": {"workspace_root": str(tmp_path / "autonomy-workspace"), "runtime_project_id": "demo-autonomy-runtime"},
                "policy": {
                    "difficulty_ceiling": "L1",
                    "discovery": {"max_new_tasks_per_cycle": 2, "quota_semantics": "ceiling_not_target"},
                },
                "workflow": {"confirmation_policy": "material"},
                "automation": {"prompt": "demo"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    _write(
        fx["user_root"] / "autonomy" / "profiles" / "demo-autonomy-two.yaml",
        yaml.safe_dump(
            {
                "schema": "tp-spec.autonomy-profile/v1",
                "profile_id": "demo-autonomy-two",
                "enabled": False,
                "canonical": {"workspace_root": str(BASE), "project_id": "demo-project"},
                "autonomous": {"workspace_root": str(tmp_path / "autonomy-workspace-two"), "runtime_project_id": "demo-autonomy-runtime-two"},
                "policy": {
                    "difficulty_ceiling": "L2",
                    "discovery": {"max_new_tasks_per_cycle": 4, "quota_semantics": "ceiling_not_target"},
                },
                "workflow": {"confirmation_policy": "each_stage"},
                "automation": {"prompt": "demo two"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    from cli.cards.snapshot import build_global_snapshot

    snap = build_global_snapshot()

    assert snap["card_type"] == "global_config"
    assert snap["version"] == active_version()
    assert snap["base"]["root"] == str(BASE.resolve())
    assert snap["workspace"]["count"] == 1
    assert snap["workspace"]["workspaces"] == [
        {
            "id": "demo-workspace",
            "root": str(fx["workspace"]),
            "enabled": None,
            "enabled_declared": False,
        }
    ]
    assert snap["autonomy"]["configured"] is True
    assert snap["autonomy"]["profile_count"] == 2
    assert [profile["profile_id"] for profile in snap["autonomy"]["profiles"]] == ["demo-autonomy", "demo-autonomy-two"]
    assert snap["autonomy"]["profiles"][0] == {
        "profile_id": "demo-autonomy",
        "enabled": True,
        "enabled_declared": True,
        "canonical_root": str(BASE),
        "autonomous_root": str(tmp_path / "autonomy-workspace"),
        "confirmation_policy": "material",
        "difficulty_ceiling": "L1",
        "max_new_tasks_per_cycle": 2,
    }
    assert snap["registry"]["project_count"] == 1
    assert snap["registered_projects"][0]["project_id"] == fx["project_id"]
    assert "password" not in json.dumps(snap, ensure_ascii=False).lower()


def test_project_snapshot_uses_binding_or_registry_exact_root_and_runtime_counts(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    from cli.cards.snapshot import build_project_snapshot

    snap = build_project_snapshot(fx["workspace"])

    assert snap["card_type"] == "current_project"
    assert snap["project"]["project_id"] == fx["project_id"]
    assert snap["project"]["identity_source"] == "project-binding"
    assert snap["task_statistics"] == {
        "total": 3,
        "new": 0,
        "active": 1,
        "blocked": 1,
        "completed": 1,
        "cancelled": 0,
        "verification_attention": 1,
    }
    assert [row["task_id"] for row in snap["in_progress_tasks"]] == ["TASK-BLOCKED", "TASK-ACTIVE"]
    assert snap["knowledge"]["project_scope"]["project_id"] == fx["project_id"]


def test_project_snapshot_excludes_retired_active_tasks(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    now = dbmod.now_iso()
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "TASK-RETIRED",
                fx["project_id"],
                "Retired historical task",
                "L1",
                "L1",
                "ACTIVE",
                "development",
                "tp-development-engineer",
                active_version(),
                now,
                now,
            ),
        )
        detail = {
            "transaction_id": "RETIRE-TEST",
            "producer": "task_retire",
            "schema_version": active_version(),
            "task_id": "TASK-RETIRED",
            "actor_role": "human_owner",
            "created_at": now,
            "reason": "历史任务已收口",
            "superseded_by": "",
            "last_state": "ACTIVE",
            "base_version": active_version(),
        }
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                "TASK-RETIRED",
                "TASK_RETIRED",
                "human_owner",
                "retired historical task",
                json.dumps(detail, ensure_ascii=False),
                active_version(),
                now,
            ),
        )
    conn.close()

    from cli.cards.snapshot import build_project_snapshot

    snap = build_project_snapshot(fx["workspace"])

    assert snap["task_statistics"]["active"] == 1
    assert "TASK-RETIRED" not in {row["task_id"] for row in snap["in_progress_tasks"]}
    archived = {row["task_id"]: row for row in snap["archived_tasks"]}
    assert {"TASK-DONE", "TASK-RETIRED"} <= set(archived)
    assert archived["TASK-RETIRED"]["state"] == "ACTIVE"
    assert archived["TASK-RETIRED"]["retired"] is True


def test_task_snapshot_uses_runtime_events_and_workflow_route(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])

    assert snap["card_type"] == "active_task"
    assert snap["task"]["task_id"] == "TASK-ACTIVE"
    assert snap["task"]["state"] == "ACTIVE"
    assert snap["workflow"]["next_step"]["stage"] == "development"
    assert snap["workflow"]["next_step"]["role"] == "tp-development-engineer"
    assert {step["stage"] for step in snap["workflow"]["completed_steps"]} >= {"requirement", "architecture"}
    assert snap["latest_checkpoint"]["summary"] == "Architecture complete"
    assert len(snap["timeline"]) >= 2


def test_task_snapshot_splits_semicolon_delimited_evidence_paths(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "UPDATE task_event SET detail_json=? WHERE task_id=? AND summary=?",
            (json.dumps({"operation": "CHECKPOINT", "phase": "architecture", "evidence": ["docs/a.md;docs/b.md", "docs/c.md"]}), "TASK-ACTIVE", "Architecture complete"),
        )
    conn.close()

    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])

    assert [item["raw_path"] for item in snap["evidence"]] == ["docs/a.md", "docs/b.md", "docs/c.md"]
    assert all(item["anchor"] == "unknown" for item in snap["evidence"])
    assert all(item["verification"] == "legacy_unverified" for item in snap["evidence"])
    assert len(snap["evidence"]) == 3


def test_missing_global_config_is_explicit_and_does_not_create_user_root(tmp_path, monkeypatch):
    user_root, _workspace, _wiki, _knowledge = _install_fixture(tmp_path, monkeypatch, with_config=False)
    from cli.cards.snapshot import build_global_snapshot
    from cli.cards.render import default_output_path, render_card

    assert not user_root.exists()
    snap = build_global_snapshot()
    assert snap["health"] in {"degraded", "unavailable"}
    assert snap["base"]["configured"] is False
    output = default_output_path("global_config")
    assert user_root not in output.parents
    render_card(snap, output)
    assert output.is_file()
    assert not user_root.exists()


def test_project_without_binding_or_registry_exact_match_is_not_guessed(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_binding=False)
    other = tmp_path / "same-looking-name"
    other.mkdir()
    from cli.cards.snapshot import build_project_snapshot

    snap = build_project_snapshot(other)

    assert snap["project"]["project_id"] == ""
    assert snap["project"]["identity_source"] == "unresolved"
    assert snap["health"] in {"degraded", "unavailable"}
    assert any("项目身份" in p["message"] for p in snap["problems"])
    assert fx["project_id"] not in snap["project"]["project_id"]


def test_project_with_no_in_progress_tasks_has_empty_state(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute("DELETE FROM task_event WHERE task_id='TASK-BLOCKED'")
        conn.execute("DELETE FROM task WHERE task_id='TASK-BLOCKED'")
    conn.close()
    from cli.cards.snapshot import build_project_snapshot

    snap = build_project_snapshot(fx["workspace"])

    assert snap["in_progress_tasks"] == []
    assert snap["task_statistics"]["completed"] == 1


def test_missing_task_id_never_selects_recent_task(tmp_path, monkeypatch):
    _runtime_fixture(tmp_path, monkeypatch)
    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("")

    assert snap["task"]["task_id"] == ""
    assert snap["health"] == "unavailable"
    assert any("task_id" in p["message"] for p in snap["problems"])


def test_renderer_contains_core_fields_interactions_and_snapshot_notice(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task.html"
    snapshot = {
        "card_type": "active_task",
        "title": "当前任务进度",
        "generated_at": "2026-08-25T16:00:00+08:00",
        "health": "healthy",
        "task": {"task_id": "TASK-X", "title": "<script>alert(1)</script>", "state": "ACTIVE", "phase": "development", "owner": "tp-development-engineer", "risk_level": "L1", "flow_level": "L1"},
        "workflow": {"completed_steps": [], "current_step": {}, "next_step": {"stage": "verification", "role": "tp-test-engineer"}, "steps": []},
        "latest_checkpoint": {},
        "blockers": [],
        "verification": {"status": "NOT_RECORDED", "summary": ""},
        "evidence": [],
        "timeline": [],
        "summary": "",
        "problems": [],
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    assert "一次性快照" in text
    assert "data-action=\"copy\"" in text or "copyText" in text
    assert "node('button', 'event-toggle')" in text
    assert "dataset.filter" in text
    assert "textContent" in text
    assert ".innerHTML" not in text
    assert "<script>alert(1)</script>" not in text


def test_renderer_notice_spans_content_grid(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "project.html"
    render_card(
        {
            "card_type": "current_project",
            "title": "当前项目概况",
            "generated_at": "2026-09-11T13:54:27+08:00",
            "health": "healthy",
            "project": {},
            "wiki": {},
            "knowledge": {},
            "registry": {},
            "task_statistics": {},
            "in_progress_tasks": [],
            "archived_tasks": [],
            "summary": "项目共有 30 个任务",
            "problems": [],
        },
        output,
    )
    text = output.read_text(encoding="utf-8")

    notice_rule = re.search(r"\.notice\s*\{([^}]*)\}", text)
    assert notice_rule, "card template must define the notice style"
    assert re.search(r"grid-column\s*:\s*1\s*/\s*-1", notice_rule.group(1)), (
        "project summary notice must occupy the full content grid"
    )


def test_project_summary_notice_is_scoped_to_task_statistics(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "project.html"
    render_card(
        {
            "card_type": "current_project",
            "title": "当前项目概况",
            "generated_at": "2026-09-11T13:54:27+08:00",
            "health": "healthy",
            "project": {},
            "wiki": {},
            "knowledge": {},
            "registry": {},
            "task_statistics": {},
            "in_progress_tasks": [],
            "archived_tasks": [],
            "summary": "项目共有 30 个任务",
            "problems": [],
        },
        output,
    )
    text = output.read_text(encoding="utf-8")

    assert "const statsRow = metrics(stats, 'project-stats', contentScroll);" in text
    assert "statsRow.insertBefore(node('div', 'notice', data.summary" in text
    assert "append(contentScroll, node('div', 'notice', data.summary" not in text


def test_renderer_formats_iso_timestamps_for_human_display(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-times.html"
    snapshot = {
        "card_type": "active_task",
        "title": "当前任务进度",
        "generated_at": "2026-08-25T20:24:07+08:00",
        "health": "healthy",
        "task": {"task_id": "TASK-TIME", "state": "ACTIVE", "phase": "development", "owner": "tp-development-engineer", "updated_at": "2026-08-25T20:20:07+08:00"},
        "workflow": {"next_step": {}, "steps": []},
        "latest_checkpoint": {"created_at": "2026-08-25T20:21:07+08:00"},
        "blockers": [{"reason": "等待外部依赖", "created_at": "2026-08-25T20:22:07+08:00"}],
        "verification": {"status": "PASS", "created_at": "2026-08-25T20:23:07+08:00"},
        "evidence": [],
        "timeline": [{"event_type": "FACT", "created_at": "2026-08-25T20:24:00+08:00", "summary": "已记录"}],
        "summary": "",
        "problems": [],
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    assert "function formatDateTime(value)" in text
    assert "formatDateTime(data.generated_at)" in text
    assert "formatDateTime(rowData.completed_at || rowData.updated_at)" in text
    assert "formatDateTime(task.updated_at)" in text
    assert "formatDateTime(checkpoint.created_at)" in text
    assert "formatDateTime(blocker.created_at)" in text
    assert "formatDateTime(eventData.created_at)" in text


def test_renderer_presents_evidence_as_traceable_file_rows(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-evidence.html"
    render_card({"card_type": "active_task", "title": "当前任务进度", "generated_at": "now", "health": "healthy", "task": {}, "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {}, "evidence": [], "timeline": [], "summary": "", "problems": []}, output)
    text = output.read_text(encoding="utf-8")

    assert "function evidenceFileName(path)" in text
    assert "function evidenceDirectory(path)" not in text
    assert "function evidenceGroupLabel(value)" in text
    assert "依据（${(data.evidence || []).length}）" in text
    assert "evidence.copy_path" in text
    assert "evidence.scope_label" in text
    assert ".evidence-table" in text
    assert ".evidence-detail-table" in text


def test_renderer_presents_timeline_as_localized_grouped_events(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-timeline.html"
    render_card({"card_type": "active_task", "title": "当前任务进度", "generated_at": "now", "health": "healthy", "task": {}, "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {}, "evidence": [], "timeline": [], "summary": "", "problems": []}, output)
    text = output.read_text(encoding="utf-8")

    assert "REVIEW_COMPLETED: '复审完成'" in text
    assert "WORK_SESSION_STARTED: '工作会话开始'" in text
    assert "WORK_SESSION_ENDED: '工作会话结束'" in text
    assert "WORKFLOW_CONFIRMATION: '工作流确认'" in text
    assert "STATE: '状态变更'" in text
    assert "function displayEventSummary(eventData)" in text
    assert "function eventDecisionToken(eventData)" in text
    assert "function displayEventReason(eventData)" in text
    assert "function displayEventHeading(eventData)" in text
    assert "displayEventHeading(eventData)" in text
    assert "displayEventReason(eventData)" in text
    assert "普通事务" in text
    assert "需要修复" in text
    assert "存在阻塞" in text
    assert "const label = presentation.event_label || displayEvent((eventData || {}).event_type)" in text
    assert "return decision ? `${label}（${decision}）` : label;" not in text
    assert "PASS: '通过'" in text
    assert "REVISE: '需修改'" in text
    assert "NEEDS_FIX: '需要修复'" in text
    assert "const signal = `${summary} ${decision}`" not in text
    assert "signal.includes('FAIL')" not in text
    assert "return presentation.status_class || 'info';" in text
    assert "function eventStatusClass(eventData)" in text
    assert "timeline-day" in text
    assert "event-marker" in text
    assert "event-body" in text
    assert "event-preview" in text
    assert "event-toggle" in text
    assert "eventBody.classList.toggle('open', expanded)" in text


def test_task_snapshot_preserves_event_decision_for_timeline_projection(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "REVIEW_COMPLETED", "tp-software-architect", "REVISE", json.dumps({"decision": "REVISE"}), active_version(), dbmod.now_iso()),
        )
    conn.close()

    from cli.cards.snapshot import build_task_snapshot

    snapshot = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])
    event = next(item for item in snapshot["timeline"] if item["event_type"] == "REVIEW_COMPLETED")
    assert event["decision"] == "REVISE"
    assert event["presentation"]["event_label"] == "复审完成"
    assert event["presentation"]["reason_label"] == "需修改"
    assert event["presentation"]["status_class"] == "bad"


def test_renderer_keeps_timeline_interactions_from_triggering_default_scroll(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-timeline-interaction.html"
    render_card({"card_type": "active_task", "title": "当前任务进度", "generated_at": "now", "health": "healthy", "task": {}, "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {}, "evidence": [], "timeline": [], "summary": "", "problems": []}, output)
    text = output.read_text(encoding="utf-8")

    assert "function preserveCardScrollPosition" not in text
    assert "document.scrollingElement" not in text
    assert ".scrollTop =" not in text
    assert "const eventToggle = node('button', 'event-toggle')" in text
    assert "eventToggle.setAttribute('aria-expanded'" in text
    assert "eventDetails = node('details', 'event-body')" not in text
    assert "const details = node('details', 'card section-card')" not in text


def test_active_task_overview_absorbs_problem_section(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-overview-problems.html"
    render_card({"card_type": "active_task", "title": "当前任务进度", "generated_at": "now", "health": "degraded", "task": {}, "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {}, "evidence": [], "timeline": [], "summary": "", "problems": [{"severity": "warning", "message": "示例异常"}]}, output)
    text = output.read_text(encoding="utf-8")

    assert "const taskOverview = node('section', 'overview section-card')" in text
    assert "taskOverview.dataset.cardSection = 'task-overview'" in text
    assert "append(taskOverview, problems(data.problems))" in text
    assert "['task-problems', '异常'" not in text


def test_renderer_contains_compact_navigation_and_named_sections_for_all_card_types(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "cards.html"
    snapshot = {
        "card_type": "global_config",
        "title": "TP-Spec 全局配置",
        "generated_at": "now",
        "health": "healthy",
        "version": active_version(),
        "base": {},
        "wiki": {},
        "knowledge": {},
        "workspace": {},
        "resolver": {},
        "registry": {},
        "registered_projects": [],
        "problems": [],
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    assert ".card-nav" in text
    assert "position: sticky" in text
    assert "function cardNav" in text
    assert "function activateCardSection" in text
    assert "node('button', `nav-link" in text
    assert "function namedCard" in text
    assert "function summaryStrip" in text
    assert "--tp-muted" in text
    assert "var(--muted)" not in text
    assert "data-card-section" in text
    assert "section.hidden" in text
    assert "aria-label" in text
    assert "卡片导航" in text
    for section_id in (
        "global-overview",
        "global-content",
        "global-workspace",
        "global-registry",
            "project-overview",
        "project-content",
        "project-stats",
        "project-active",
        "project-completed",
        "task-overview",
        "task-facts",
        "task-workflow",
        "task-evidence",
        "task-timeline",
    ):
        assert section_id in text


def test_global_overview_contains_base_problems_and_workspace_list(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "global.html"
    snapshot = {
        "card_type": "global_config",
        "title": "TP-Spec 全局配置",
        "generated_at": "now",
        "health": "degraded",
        "version": active_version(),
        "base": {"base_version": active_version(), "root": "C:/tp-spec", "configured": True, "valid": True},
        "wiki": {"status": "available"},
        "knowledge": {"status": "available"},
        "workspace": {
            "configured": True,
            "count": 1,
            "workspaces": [{"id": "demo-workspace", "root": "C:/demo", "enabled": True}],
        },
        "resolver": {"status": "healthy"},
        "registry": {"status": "available", "project_count": 0},
        "autonomy": {
            "configured": True,
            "profile_count": 1,
            "profiles": [{
                "profile_id": "demo-autonomy",
                "enabled": True,
                "canonical_root": "C:/canonical",
                "autonomous_root": "C:/autonomous",
                "confirmation_policy": "material",
                "difficulty_ceiling": "L1",
                "max_new_tasks_per_cycle": 2,
            }],
        },
        "registered_projects": [],
        "problems": [{"severity": "warning", "message": "示例异常"}],
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    assert "function workspaceTable" in text
    assert "workspace.workspaces" in text
    assert "['global-base', '基础 / 契约']" not in text
    assert "['global-problems', '异常'" not in text
    assert "function problems" in text
    assert "function autonomyCard" in text
    assert "autonomy.profiles" in text
    assert "function compactTable" in text
    assert "function workspaceTable" in text
    assert "workspaceTable('工作区列表'" in text
    assert ".overview > .card + .card" in text
    assert ".global-config-card .overview > .summary-grid + .card { margin-top: 10px; }" in text
    assert "compactTable('配置档案'" in text
    assert "['global-autonomy', '自治维护']" in text
    assert "append(contentScroll, autonomyCard(data.autonomy || {}, 'global-autonomy'));" in text
    assert "append(overview, autonomyCard" not in text
    assert "demo-autonomy" in text


def test_current_project_card_uses_global_style_overview(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "current-project.html"
    snapshot = {
        "card_type": "current_project",
        "title": "当前项目概览",
        "generated_at": "now",
        "health": "degraded",
        "project": {
            "project_id": "idc",
            "name": "IDC",
            "root_path": r"D:\work\work-git\idcProject",
            "base_version": active_version(),
            "contract_version": active_version(),
            "identity_source": "project-binding",
            "runtime_status": "available",
            "runtime_db": r"D:\work\work-git\idcProject\.tp-spec\db\idc.db",
            "binding": {"exists": True, "path": r"D:\work\work-git\idcProject\.tp-spec\config\project-binding.yaml"},
        },
        "wiki": {"status": "available", "path": "E:/wiki", "registry_exists": True, "identity": {"workspace_id": "idcproject"}},
        "knowledge": {"status": "available", "path": "E:/knowledge", "registry_exists": True, "project_scope": {"project_id": "idc"}, "shared_scope": {"count": 1}, "projection": {"status": "available"}},
        "registry": {"status": "available"},
        "task_statistics": {"total": 15, "active": 3, "blocked": 0, "completed": 10, "verification_attention": 1},
        "in_progress_tasks": [],
        "completed_tasks": [],
        "summary": "项目共有 15 个任务",
        "problems": [{"severity": "warning", "message": "版本不一致"}],
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    assert "function projectOverviewSection" in text
    assert "projectOverviewSection(project, binding, stats, data.problems)" in text
    assert "['project-overview', '概览']" in text
    assert "const identityCard = card('项目身份')" in text
    assert "['项目', project.name || project.project_id || '未解析']" not in text
    assert ".project-overview > .card + .card" in text
    assert "['运行时', displayStatus(project.runtime_status)]" not in text
    assert "['project-summary', '项目摘要'" not in text
    assert "if (data.summary) append(app, append(namedCard('project-summary'" not in text
    assert "['project-identity', '项目身份']" not in text
    assert "['project-problems', '异常'" not in text
    assert r"D:\\work\\work-git\\idcProject" in text
    assert "项目概览" in text


def test_project_overview_separates_summary_tiles_from_identity(tmp_path):
    """The identity block stays visibly distinct after responsive metric wrapping."""
    from cli.cards.render import render_card

    output = tmp_path / "current-project-spacing.html"
    render_card(
        {
            "card_type": "current_project",
            "title": "当前项目概况",
            "generated_at": "2026-08-26T00:28:59+08:00",
            "health": "healthy",
            "project": {},
            "task_statistics": {},
            "problems": [],
        },
        output,
    )

    text = output.read_text(encoding="utf-8")
    assert ".project-overview > .summary-grid + .card { margin-top: 8px; }" in text


def test_renderer_localizes_visible_labels_and_statuses(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "localized.html"
    snapshot = {
        "card_type": "active_task",
        "title": "当前任务进度",
        "generated_at": "now",
        "health": "healthy",
        "task": {"task_id": "TASK-X", "state": "ACTIVE", "phase": "development", "owner": "tp-development-engineer", "risk_level": "L1", "flow_level": "L1"},
        "workflow": {"completed_steps": [], "current_step": {}, "next_step": {"stage": "verification", "role": "tp-test-engineer"}, "steps": []},
        "latest_checkpoint": {},
        "blockers": [],
        "verification": {"status": "NOT_RECORDED", "summary": ""},
        "evidence": [],
        "timeline": [],
        "summary": "",
        "problems": [],
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    for label in (
        "基础 / 契约",
        "Wiki / 知识库",
        "工作区 / 解析器",
        "工程注册",
        "任务编号",
        "风险 / 流程",
        "运行时数据库",
        "依据",
        "进行中",
        "开发阶段",
        "测试工程师",
    ):
        assert label in text
    for label in ("Base / Contract", "Wiki / Knowledge", "Workspace / Resolver", "Evidence", "Task ID", "Owner"):
        assert label not in text


def test_renderer_is_offline_and_has_restrictive_csp(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "global.html"
    render_card({"card_type": "global_config", "title": "TP-Spec 全局配置", "generated_at": "now", "health": "healthy", "version": active_version(), "base": {}, "wiki": {}, "knowledge": {}, "workspace": {}, "registry": {}, "registered_projects": [], "problems": []}, output)
    text = output.read_text(encoding="utf-8")

    assert "http://" not in text
    assert "https://" not in text
    assert "connect-src 'none'" in text
    assert "cdn" not in text.lower()


def test_renderer_does_not_serialize_sensitive_config_values(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "global.html"
    snapshot = {
        "card_type": "global_config",
        "title": "TP-Spec 全局配置",
        "generated_at": "now",
        "health": "healthy",
        "version": active_version(),
        "base": {"root": "/safe/path", "configured": True},
        "wiki": {},
        "knowledge": {},
        "workspace": {},
        "registry": {},
        "registered_projects": [],
        "problems": [],
        "password": "SHOULD-NOT-LEAK",
        "api_key": "SHOULD-NOT-LEAK-EITHER",
    }
    render_card(snapshot, output)
    text = output.read_text(encoding="utf-8")

    assert "SHOULD-NOT-LEAK" not in text
    assert "api_key" not in text
    assert "password" not in text.lower()


def test_card_cli_is_explicit_and_task_id_is_optional_for_empty_state():
    args = climain.build_parser().parse_args(["card", "task"])
    assert args.group == "card"
    assert args.card_type == "task"
    assert args.task is None


def test_automatic_card_trigger_is_removed_from_production_entry():
    import inspect
    assert not (BASE / "cli/cards/trigger.py").exists()
    assert "refresh_after_success" not in inspect.getsource(climain.main)


def test_task_create_leaves_cards_absent_until_explicit_request(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    card_root = tmp_path / "cards-out"
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))
    monkeypatch.chdir(fx["workspace"])
    rc, out, err = _run([
        "task", "create", "--id", "TASK-NEW", "--project", fx["project_id"],
        "--title", "New task", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])
    assert rc == 0, (out, err)
    assert not card_root.exists()
    assert not (fx["workspace"] / ".tp-spec/card/index.html").exists()
    assert "CARD_DISPLAY" not in out + err
    output = tmp_path / "explicit.html"
    rc, out, err = _run(["card", "task", "--task", "TASK-NEW", "--db", str(fx["db_path"]), "--output", str(output)])
    assert rc == 0, (out, err)
    assert "TASK-NEW" in output.read_text(encoding="utf-8")


def test_entry_skill_routes_only_explicit_config_project_and_task_card_requests():
    text = (BASE / "entry" / "tp-spec-coding" / "SKILL.md").read_text(encoding="utf-8")
    from scripts.check_document_navigation import iter_markdown_links, resolve_document_link
    source = BASE / "entry/tp-spec-coding/SKILL.md"
    targets = {label: resolve_document_link(source, target, base=BASE)
               for label, target in iter_markdown_links(source)}
    display_path = targets["tp-card-display"]
    assert display_path == BASE / "agents/tp-card-display/SKILL.md"
    display = display_path.read_text(encoding="utf-8")
    assert "tp-spec card global" in display
    assert "tp-spec card project" in display
    assert "tp-spec card task --task" in display
    assert "普通代码搜索" in text and "仅用户显式请求" in text
    assert "不得自动生成" in text


def test_lifecycle_skill_requires_explicit_card_request_and_markdown_feedback():
    text = (BASE / "agents/tp-software-lifecycle/SKILL.md").read_text(encoding="utf-8")
    for phrase in ("task checkpoint", "work start", "workflow confirm", "Markdown", "不自动生成", "用户明确"):
        assert phrase in text
    assert "刷新白名单保持" not in text


def test_explicit_global_card_command_generates_preview_file(tmp_path, monkeypatch):
    _runtime_fixture(tmp_path, monkeypatch)
    output = tmp_path / "global-card.html"

    rc, out, err = _run(["card", "global", "--output", str(output)])

    assert rc == 0, (out, err)
    assert output.is_file()
    assert str(output) in out
    text = output.read_text(encoding="utf-8")
    assert "TP-Spec 全局配置" in text


def test_explicit_project_card_command_generates_preview_file(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    output = tmp_path / "project-card.html"

    rc, out, err = _run(["card", "project", "--root", str(fx["workspace"]), "--output", str(output)])

    assert rc == 0, (out, err)
    assert output.is_file()
    assert str(output) in out
    text = output.read_text(encoding="utf-8")
    assert "当前项目概况" in text
    assert fx["project_id"] in text


def test_explicit_task_card_command_generates_preview_file(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    output = tmp_path / "task-card.html"

    rc, out, err = _run(["card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"]), "--output", str(output)])

    assert rc == 0, (out, err)
    assert output.is_file()
    assert str(output) in out
    text = output.read_text(encoding="utf-8")
    assert "当前任务进度" in text
    assert "TASK-ACTIVE" in text


def test_unknown_task_in_explicit_runtime_keeps_requested_task_id(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-NOT-THERE", db_path=fx["db_path"])

    assert snap["health"] == "unavailable"
    assert snap["task"]["task_id"] == "TASK-NOT-THERE"
    assert any(p["code"] == "TASK_NOT_FOUND" for p in snap["problems"])


def test_global_registered_project_list_is_compact_table():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")
    assert "function compactTable" in text
    assert "function projectTable" in text
    assert "projectTable('已注册工程'" in text
    assert "function projectList" not in text


def test_global_registry_summary_and_project_list_share_one_navigation_section():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")
    assert "['global-registry', '工程注册']" in text
    assert "['global-projects', '注册工程']" not in text
    assert "kv(registryCard, [" in text
    assert "append(registryCard, projectTable('已注册工程', data.registered_projects || []));" in text


def test_invalid_legacy_card_output_does_not_enter_renderer(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("file blocks card output directory", encoding="utf-8")
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(invalid_root))

    rc, out, err = _run([
        "task", "create", "--id", "TASK-CARD-WARN", "--project", fx["project_id"],
        "--title", "Runtime succeeds even if card fails", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])

    assert rc == 0, (out, err)
    assert "CARD_RENDER_WARNING" not in err
    conn = dbmod.connect_readonly(str(fx["db_path"]))
    try:
        row = conn.execute("SELECT task_id FROM task WHERE task_id='TASK-CARD-WARN'").fetchone()
    finally:
        conn.close()
    assert row is not None


def test_global_home_override_keeps_registry_reads_inside_fixture_root(tmp_path, monkeypatch):
    from cli.cards.snapshot import build_global_snapshot

    monkeypatch.delenv("TP_SPEC_USER_ROOT", raising=False)
    monkeypatch.delenv("TP_SPEC_REGISTRY", raising=False)
    monkeypatch.delenv("TP_SPEC_INSTALLATION_CONFIG", raising=False)
    monkeypatch.delenv("TP_SPEC_WORKSPACE_INVENTORY", raising=False)
    home = tmp_path / "isolated-home"
    root = home / ".tp-spec"
    _write(root / "installation.yaml", yaml.safe_dump({"schema": "tp-spec.installation/v1", "base": {"root": str(BASE)}}, sort_keys=False))
    _write(root / "workspaces.yaml", yaml.safe_dump({"schema": "tp-spec.workspace-inventory/v1", "workspaces": []}, sort_keys=False))
    _write(root / "registry.local.json", json.dumps({"projects": [{"project_id": "fixture-only", "project_name": "Fixture Only", "root_path": str(tmp_path / "fixture-project"), "db_path": ""}]}, indent=2) + "\n")

    snap = build_global_snapshot(home=home)

    assert snap["user_root"] == str(root.resolve())
    assert snap["registry"]["path"] == str((root / "registry.local.json").resolve())
    assert [p["project_id"] for p in snap["registered_projects"]] == ["fixture-only"]


def test_project_card_surfaces_binding_and_content_registry_statuses():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")
    assert "项目绑定" in text
    assert "Wiki 注册" in text
    assert "知识库注册" in text


def test_stable_web_artifact_path_is_fixed_under_workspace(tmp_path):
    from cli.cards.render import artifact_output_path

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert artifact_output_path(workspace) == (workspace / ".tp-spec" / "card" / "index.html").resolve()


def test_explicit_project_card_also_updates_fixed_web_artifact(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "project-offline.html"

    rc, out, err = _run([
        "card", "project", "--root", str(fx["workspace"]), "--output", str(offline),
    ])

    artifact = fx["workspace"] / ".tp-spec" / "card" / "index.html"
    assert rc == 0, (out, err)
    assert offline.is_file()
    assert artifact.is_file()
    assert not (fx["workspace"] / ".tp-spec-preview" / "card" / "index.html").exists()
    assert f"WEB_ARTIFACT: {artifact.resolve()}" in out
    text = artifact.read_text(encoding="utf-8")
    assert "当前项目概况" in text
    assert fx["project_id"] in text


def test_global_and_task_cards_accept_explicit_artifact_root_and_reuse_index(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    artifact_root = tmp_path / "codex-workspace"
    artifact_root.mkdir()
    global_offline = tmp_path / "global-offline.html"
    task_offline = tmp_path / "task-offline.html"

    rc, out, err = _run([
        "card", "global", "--output", str(global_offline), "--artifact-root", str(artifact_root),
    ])
    artifact = artifact_root / ".tp-spec" / "card" / "index.html"
    assert rc == 0, (out, err)
    assert artifact.is_file()
    assert "TP-Spec 全局配置" in artifact.read_text(encoding="utf-8")

    rc, out, err = _run([
        "card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"]),
        "--output", str(task_offline), "--artifact-root", str(artifact_root),
    ])
    assert rc == 0, (out, err)
    assert f"WEB_ARTIFACT: {artifact.resolve()}" in out
    text = artifact.read_text(encoding="utf-8")
    assert "当前任务进度" in text
    assert "TASK-ACTIVE" in text
    assert "TP-Spec 全局配置" not in text
    assert list((artifact_root / ".tp-spec" / "card").glob("*.html")) == [artifact]


def test_artifact_write_failure_keeps_explicit_offline_preview_successful(tmp_path, monkeypatch):
    _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "global-offline.html"
    blocked_root = tmp_path / "blocked-root"
    blocked_root.write_text("not a directory", encoding="utf-8")

    rc, out, err = _run([
        "card", "global", "--output", str(offline), "--artifact-root", str(blocked_root),
    ])

    assert rc == 0, (out, err)
    assert offline.is_file()
    assert str(offline.resolve()) in out
    assert "CARD_ARTIFACT_WARNING" in err


def test_formal_runtime_preserves_existing_fixed_workspace_artifact(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    monkeypatch.chdir(fx["workspace"])
    artifact = fx["workspace"] / ".tp-spec/card/index.html"
    _write(artifact, "previous user-requested snapshot")
    before = (artifact.read_bytes(), artifact.stat().st_mtime_ns)
    rc, out, err = _run([
        "task", "create", "--id", "TASK-ARTIFACT", "--project", fx["project_id"],
        "--title", "No refresh", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])
    assert rc == 0, (out, err)
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == before
    assert "CARD_DISPLAY" not in out + err


def test_renderer_avoids_navigation_and_expansion_scroll_side_effects():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    for forbidden in (
        "<details",
        "scrollIntoView",
        "window.scrollTo",
        "location.hash",
        "document.scrollingElement",
        "preserveCardScrollPosition",
        ".scrollTop =",
    ):
        assert forbidden not in text
    assert "link.type = 'button'" in text
    assert "eventToggle.type = 'button'" in text
    assert "aria-expanded" in text
    assert "aria-controls" in text


def test_entry_skill_prefers_fixed_web_artifact_with_offline_fallback():
    text = (BASE / "entry" / "tp-spec-coding" / "SKILL.md").read_text(encoding="utf-8")

    assert "[tp-card-display](../../agents/tp-card-display/SKILL.md)" in text
    display = (BASE / "agents/tp-card-display/SKILL.md").read_text(encoding="utf-8")
    assert ".tp-spec/card/index.html" in display
    assert "Web Artifact" in display or "网站预览" in display
    assert "离线 HTML" in display
    assert "不得只返回" in display


def test_lifecycle_skill_keeps_display_non_authoritative_and_explicit_only():
    text = (BASE / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")

    assert "不自动生成 snapshot" in text
    assert "不新增 public state" in text


def test_renderer_uses_internal_scroll_to_reduce_host_layout_shift():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "html, body { height: 100%; }" in text
    assert "overflow: hidden;" in text
    assert "height: 100%;" in text
    assert "overflow-y: auto;" in text
    assert "min-height: 0;" in text


def test_repo_ignores_generated_web_artifact_directory():
    lines = (BASE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".tp-spec/card/" in lines
    assert ".tp-spec-preview/" not in lines
    assert ".tp-spec/" not in lines


def test_project_local_artifact_placement_is_documented():
    maintenance = (BASE / "agents" / "tp-base-maintenance" / "SKILL.md").read_text(encoding="utf-8")
    readme = (BASE / "project-entry" / "tp-spec-readme.md").read_text(encoding="utf-8")

    for text in (maintenance, readme):
        assert ".tp-spec/card" in text
        assert "presentation-only" in text
        assert "rebuildable" in text
        assert "non-authoritative" in text
        assert "system Temp" in text


def test_inline_renderer_emits_three_host_safe_card_fragments(tmp_path):
    from cli.cards.render import render_inline_card

    snapshots = [
        {
            "card_type": "global_config",
            "title": "TP-Spec 全局配置",
            "generated_at": "2026-08-25T20:24:07+08:00",
            "health": "healthy",
            "version": active_version(),
            "base": {},
            "wiki": {},
            "knowledge": {},
            "workspace": {},
            "resolver": {},
            "registry": {},
            "registered_projects": [],
            "problems": [],
        },
        {
            "card_type": "current_project",
            "title": "当前项目概况",
            "generated_at": "2026-08-25T20:24:07+08:00",
            "health": "healthy",
            "project": {"project_id": "demo-project", "name": "Demo Project"},
            "wiki": {},
            "knowledge": {},
            "registry": {},
            "task_statistics": {},
            "in_progress_tasks": [],
            "completed_tasks": [],
            "summary": "",
            "problems": [],
        },
        {
            "card_type": "active_task",
            "title": "当前任务进度",
            "generated_at": "2026-08-25T20:24:07+08:00",
            "health": "healthy",
            "task": {"task_id": "TASK-INLINE"},
            "workflow": {},
            "latest_checkpoint": {},
            "blockers": [],
            "verification": {},
            "evidence": [],
            "timeline": [],
            "summary": "",
            "problems": [],
        },
    ]

    roots = set()
    for snapshot in snapshots:
        output = tmp_path / f"{snapshot['card_type']}.html"
        render_inline_card(snapshot, output)
        fragment = output.read_text(encoding="utf-8")

        assert "<!doctype" not in fragment.lower()
        assert "<html" not in fragment.lower()
        assert "<head" not in fragment.lower()
        assert "<body" not in fragment.lower()
        assert "attachShadow({mode: 'open'})" in fragment
        assert "height: 100%" not in fragment
        assert re.search(r"\.grid \{[^}]*overflow-y:\s*auto", fragment) is None
        if snapshot["card_type"] == "active_task":
            assert "task-progress-card" in fragment
            assert "task-progress-scroll" in fragment
            assert ".task-progress-card { overflow: hidden; }" in fragment
            assert ".task-progress-scroll { min-height: 0; overflow-y: auto;" in fragment
            assert ".task-progress-card .card-nav { position: static; }" in fragment
        else:
            assert "position: sticky" not in fragment
            assert "card-content-scroll" in fragment
            assert ".global-config-card, .current-project-card { overflow: hidden; }" in fragment
            assert ".card-content-scroll { min-height: 0; overflow-y: auto;" in fragment
        assert "document.body.appendChild" not in fragment
        assert snapshot["title"] in fragment
        assert len(fragment.encode("utf-8")) < 1_000_000

        marker = 'id="tp-spec-card-'
        root = fragment.split(marker, 1)[1].split('"', 1)[0]
        roots.add(root)
        assert f"document.getElementById('tp-spec-card-{root}')" in fragment

    assert len(roots) == 3


def test_all_card_types_share_typography_tokens(tmp_path):
    from cli.cards.render import render_inline_card

    common = {
        "generated_at": "2026-08-25T20:24:07+08:00",
        "health": "healthy",
    }
    snapshots = {
        "global_config": {
            **common,
            "card_type": "global_config",
            "title": "TP-Spec 全局配置",
            "version": active_version(),
            "base": {}, "wiki": {}, "knowledge": {}, "workspace": {}, "resolver": {},
            "registry": {}, "registered_projects": [], "problems": [],
        },
        "current_project": {
            **common,
            "card_type": "current_project",
            "title": "当前项目概况",
            "project": {"project_id": "demo-project", "name": "Demo Project"},
            "wiki": {}, "knowledge": {}, "registry": {}, "task_statistics": {},
            "in_progress_tasks": [], "completed_tasks": [], "summary": "", "problems": [],
        },
        "active_task": {
            **common,
            "card_type": "active_task",
            "title": "当前任务进度",
            "task": {"task_id": "TASK-TYPOGRAPHY"},
            "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {},
            "evidence": [], "timeline": [], "summary": "", "problems": [],
        },
    }
    required = (
        "--tp-font-sans",
        "--tp-font-mono",
        "--tp-font-size-body",
        "--tp-font-size-micro",
        "--tp-font-size-label",
        "--tp-font-size-section",
        "--tp-font-size-title",
        "--tp-font-size-metric",
        "--tp-font-weight-regular",
        "--tp-font-weight-medium",
        "--tp-font-weight-semibold",
        "--tp-font-weight-bold",
        "--tp-leading-body",
        "--tp-leading-tight",
        "--tp-leading-compact",
    )

    for card_type, snapshot in snapshots.items():
        output = tmp_path / f"{card_type}-typography.html"
        render_inline_card(snapshot, output)
        fragment = output.read_text(encoding="utf-8")
        for token in required:
            assert token in fragment, f"{card_type} missing typography token {token}"
        assert "font-family: var(--tp-font-sans)" in fragment
        assert "font-family: var(--tp-font-mono)" in fragment
        assert "font-size: var(--tp-font-size-body)" in fragment
        assert "line-height: var(--tp-leading-body)" in fragment
        assert re.search(r"table \{[^}]*font-size: var\(--tp-font-size-label\)", fragment)
        assert "th, td { text-align: left; padding: 7px 8px;" in fragment
        assert "line-height: var(--tp-leading-compact)" in fragment
        assert ".compact-table th, .compact-table td { padding: 6px 7px;" in fragment
        assert ".task-list-table { min-width: 1200px; table-layout: fixed; }" in fragment
        assert ".task-list-table th:nth-child(1) { width: 12%; }" in fragment
        assert ".task-list-table th:nth-child(2) { width: 20%; }" in fragment
        assert ".task-list-table th:nth-child(7) { width: 25%; }" in fragment
        assert ".autonomy-table { min-width: 1100px; }" in fragment
        assert ".task-list-table { font-size: var(--tp-font-size-body); line-height: var(--tp-leading-body); }" not in fragment
        assert ".autonomy-table { font-size: var(--tp-font-size-body); line-height: var(--tp-leading-body); }" not in fragment
        for legacy_weight in ("font-weight: 650", "font-weight: 760", "font-weight: 800"):
            assert legacy_weight not in fragment


def test_inline_renderer_truncates_oversized_snapshot_with_visible_notice(tmp_path):
    from cli.cards.render import render_inline_card

    output = tmp_path / "oversized-task.html"
    snapshot = {
        "card_type": "active_task",
        "title": "当前任务进度",
        "generated_at": "2026-08-25T20:24:07+08:00",
        "health": "healthy",
        "task": {"task_id": "TASK-OVERSIZED"},
        "workflow": {},
        "latest_checkpoint": {"summary": "A" * 1_100_000},
        "blockers": [],
        "verification": {},
        "evidence": [],
        "timeline": [],
        "summary": "B" * 1_100_000,
        "problems": [],
    }

    render_inline_card(snapshot, output)
    fragment = output.read_text(encoding="utf-8")

    assert len(fragment.encode("utf-8")) < 1_000_000
    assert "会话卡片内容过多，已截断展示" in fragment
    assert "A" * 100_000 not in fragment
    assert "B" * 100_000 not in fragment


def test_all_explicit_card_commands_can_emit_inline_fragments(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    artifact_root = tmp_path / "artifact-root"
    artifact_root.mkdir()

    commands = [
        (
            ["card", "global"],
            "global",
            "global_config",
            "TP-Spec 全局配置",
        ),
        (
            ["card", "project", "--root", str(fx["workspace"])],
            "project",
            "current_project",
            fx["project_id"],
        ),
        (
            ["card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"])],
            "task",
            "active_task",
            "TASK-ACTIVE",
        ),
    ]

    for argv, name, card_type, expected in commands:
        offline = tmp_path / f"{name}-offline.html"
        inline = tmp_path / f"{name}-inline.html"
        rc, out, err = _run([
            *argv,
            "--output", str(offline),
            "--artifact-root", str(artifact_root),
            "--inline-output", str(inline),
        ])

        assert rc == 0, (out, err)
        assert offline.is_file()
        assert inline.is_file()
        assert f"INLINE_VISUALIZATION: {inline.resolve()}" in out
        payload = _card_display_payload(out)
        assert payload["schema"] == "tp-spec.card-display/v1"
        assert payload["card_type"] == card_type
        assert payload["offline_html"] == str(offline.resolve())
        assert payload["web_artifact"] == str((artifact_root / ".tp-spec" / "card" / "index.html").resolve())
        assert payload["inline"]["status"] == "generated"
        assert payload["inline"]["path"] == str(inline.resolve())
        fragment = inline.read_text(encoding="utf-8")
        assert expected in fragment
        assert "<!doctype" not in fragment.lower()


def test_inline_write_failure_keeps_explicit_offline_preview_successful(tmp_path, monkeypatch):
    _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "global-offline.html"
    artifact_root = tmp_path / "artifact-root"
    artifact_root.mkdir()
    blocked = tmp_path / "blocked-inline-parent"
    blocked.write_text("not a directory", encoding="utf-8")

    rc, out, err = _run([
        "card", "global",
        "--output", str(offline),
        "--artifact-root", str(artifact_root),
        "--inline-output", str(blocked / "global-inline.html"),
    ])

    assert rc == 0, (out, err)
    assert offline.is_file()
    assert "CARD_INLINE_WARNING" in err


def test_normal_runtime_ignores_legacy_inline_environment(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    card_root = tmp_path / "cards-out"
    inline = tmp_path / "conversation/task-inline.html"
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))
    monkeypatch.setenv("TP_SPEC_CARD_INLINE_OUTPUT", str(inline))
    monkeypatch.chdir(fx["workspace"])
    rc, out, err = _run([
        "task", "create", "--id", "TASK-INLINE", "--project", fx["project_id"],
        "--title", "No automatic inline", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])
    assert rc == 0, (out, err)
    assert not inline.exists()
    assert not card_root.exists()
    assert "INLINE_VISUALIZATION" not in out + err
    assert "CARD_DISPLAY" not in out + err


def test_invalid_legacy_inline_path_has_no_runtime_side_effect(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    card_root = tmp_path / "cards-out"
    blocked = tmp_path / "blocked-inline-parent"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))
    monkeypatch.setenv("TP_SPEC_CARD_INLINE_OUTPUT", str(blocked / "task-inline.html"))
    monkeypatch.chdir(fx["workspace"])

    rc, out, err = _run([
        "task", "create", "--id", "TASK-INLINE-WARN", "--project", fx["project_id"],
        "--title", "Inline warning", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])

    assert rc == 0, (out, err)
    assert "CARD_INLINE_WARNING" not in err
    assert not (card_root / "tasks" / "TASK-INLINE-WARN.html").exists()
    assert not (fx["workspace"] / ".tp-spec" / "card" / "index.html").exists()
    conn = dbmod.connect_readonly(str(fx["db_path"]))
    try:
        row = conn.execute("SELECT task_id FROM task WHERE task_id='TASK-INLINE-WARN'").fetchone()
    finally:
        conn.close()
    assert row is not None


def test_explicit_task_card_forwards_base_root_to_snapshot(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    alternate_base = tmp_path / "alternate-base"
    major, minor, patch = (int(part) for part in active_version().split("."))
    alternate_version = f"{major}.{minor}.{patch + 1}"
    _write(alternate_base / "VERSION", f"{alternate_version}\n")
    output = tmp_path / "alternate.html"
    rc, out, err = _run(["card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"]), "--base-root", str(alternate_base), "--output", str(output)])
    assert rc == 0, (out, err)
    assert f"任务 Contract {active_version()} 与当前 Base {alternate_version} 不一致" in output.read_text(encoding="utf-8")


def test_card_skills_use_governed_display_contract_with_host_capability_fallbacks():
    entry = (BASE / "entry" / "tp-spec-coding" / "SKILL.md").read_text(encoding="utf-8")
    lifecycle = (BASE / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")
    display = (BASE / "agents" / "tp-card-display" / "SKILL.md").read_text(encoding="utf-8")

    assert "card → `tp-card-display`" in entry
    assert "tp-software-lifecycle` 的按需能力" not in entry
    assert "visualize" not in entry
    assert "CARD_DISPLAY" in display
    assert "宿主" in display and "Web Artifact" in display and "离线 HTML" in display
    assert "用户明确" in lifecycle
    assert "tp-card-display" in lifecycle
    assert "不得复制卡片模板、渲染器或 Host bridge" in lifecycle
    assert "CARD_DISPLAY" in lifecycle
    assert "不自动生成" in lifecycle
    assert "会话内" in lifecycle


def test_explicit_card_commands_use_one_canonical_renderer_without_runtime_hook():
    commands = (BASE / "cli/cards/commands.py").read_text(encoding="utf-8")
    assert "def render_display_outputs(" in commands
    assert "render_inline_card(snapshot, inline_output)" in commands
    assert not (BASE / "cli/cards/trigger.py").exists()


def test_global_snapshot_and_renderer_include_skill_topology_with_name_and_id(tmp_path, monkeypatch):
    _install_fixture(tmp_path, monkeypatch)
    from cli.cards.snapshot import build_global_snapshot
    from cli.cards.render import render_card, sanitize_snapshot

    snap = build_global_snapshot()

    topology = snap["skill_topology"]
    assert topology["status"] == "available"
    assert topology["root_id"] == "tp-spec-coding"
    assert topology["nodes"]["tp-product-manager"]["name"] == "tp-产品经理"
    assert topology["nodes"]["requirement-clarification"]["name"] == "需求澄清"
    assert "skill_topology" in sanitize_snapshot(snap)

    output = tmp_path / "global-topology.html"
    render_card(snap, output)
    text = output.read_text(encoding="utf-8")
    assert "global-skills" in text
    assert "能力拓扑" in text
    assert "Agent / Role / Skill" not in text
    assert "tp-product-manager" in text
    assert "tp-产品经理" in text
    assert "requirement-clarification" in text
    assert "需求澄清" in text


def test_global_snapshot_uses_chinese_skill_topology_problem_label(tmp_path, monkeypatch):
    _install_fixture(tmp_path, monkeypatch)
    from cli.cards import snapshot as card_snapshot

    def broken_topology(_base_root):
        raise ValueError("catalog mismatch")

    monkeypatch.setattr(card_snapshot.orchestration, "load_role_topology", broken_topology)
    snapshot = card_snapshot.build_global_snapshot()

    problem = next(item for item in snapshot["problems"] if item["code"] == "SKILL_TOPOLOGY_INVALID")
    assert problem["message"] == "能力拓扑图谱不可读：catalog mismatch"


def _card_display_payload(output: str) -> dict:
    line = next(line for line in output.splitlines() if line.startswith("CARD_DISPLAY: "))
    return json.loads(line.split("CARD_DISPLAY: ", 1)[1])


def test_explicit_card_uses_env_inline_output_when_argument_is_absent(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "task-offline.html"
    artifact_root = tmp_path / "artifact-root"
    inline = tmp_path / "conversation" / "task-inline.html"
    monkeypatch.setenv("TP_SPEC_CARD_INLINE_OUTPUT", str(inline))

    rc, out, err = _run([
        "card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"]),
        "--output", str(offline), "--artifact-root", str(artifact_root),
    ])

    assert rc == 0, (out, err)
    assert inline.is_file()
    payload = _card_display_payload(out)
    assert payload["schema"] == "tp-spec.card-display/v1"
    assert payload["card_type"] == "active_task"
    assert payload["offline_html"] == str(offline.resolve())
    assert payload["inline"] == {
        "requested": True,
        "status": "generated",
        "path": str(inline.resolve()),
        "error": None,
    }


def test_explicit_inline_argument_overrides_environment_default(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    env_inline = tmp_path / "conversation" / "env-inline.html"
    arg_inline = tmp_path / "conversation" / "arg-inline.html"
    monkeypatch.setenv("TP_SPEC_CARD_INLINE_OUTPUT", str(env_inline))

    rc, out, err = _run([
        "card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"]),
        "--inline-output", str(arg_inline),
    ])

    assert rc == 0, (out, err)
    assert arg_inline.is_file()
    assert not env_inline.exists()
    payload = _card_display_payload(out)
    assert payload["inline"]["path"] == str(arg_inline.resolve())


def test_card_display_result_reports_generated_artifact_and_fragment(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    artifact_root = tmp_path / "artifact-root"
    inline = tmp_path / "inline.html"
    offline = tmp_path / "global.html"

    rc, out, err = _run([
        "card", "global", "--output", str(offline),
        "--artifact-root", str(artifact_root), "--inline-output", str(inline),
    ])

    assert rc == 0, (out, err)
    payload = _card_display_payload(out)
    assert payload == {
        "schema": "tp-spec.card-display/v1",
        "card_type": "global_config",
        "offline_html": str(offline.resolve()),
        "web_artifact": str((artifact_root / ".tp-spec" / "card" / "index.html").resolve()),
        "artifact": {"status": "generated", "error": None},
        "inline": {"requested": True, "status": "generated", "path": str(inline.resolve()), "error": None},
    }


def test_card_display_degrades_without_changing_runtime_or_offline_success(tmp_path, monkeypatch):
    _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "global.html"
    blocked_root = tmp_path / "blocked-root"
    blocked_root.write_text("not a directory", encoding="utf-8")
    blocked_inline = tmp_path / "blocked-inline"
    blocked_inline.write_text("not a directory", encoding="utf-8")

    rc, out, err = _run([
        "card", "global", "--output", str(offline),
        "--artifact-root", str(blocked_root),
        "--inline-output", str(blocked_inline / "inline.html"),
    ])

    assert rc == 0, (out, err)
    assert offline.is_file()
    payload = _card_display_payload(out)
    assert payload["artifact"]["status"] == "failed"
    assert payload["web_artifact"] is None
    assert payload["artifact"]["error"]
    assert payload["inline"]["status"] == "failed"
    assert payload["inline"]["path"] is None
    assert payload["inline"]["error"]
    assert "CARD_ARTIFACT_WARNING" in err
    assert "CARD_INLINE_WARNING" in err


def test_workflow_presentation_contract_covers_pipeline_stages_actions_and_confirmations():
    from cli import orchestration

    contract = orchestration.load_contract(BASE)
    presentation = contract["presentation"]
    stage_ids = {
        str(step["stage"])
        for pipeline in (contract.get("pipelines") or {}).values()
        for step in pipeline
    }
    stage_ids.add("complete")

    assert stage_ids <= set(presentation["stages"])
    assert presentation["stages"]["architecture_review"]["label"] == "架构复审"
    assert presentation["stages"]["review"]["label"] == "代码复审"
    assert presentation["stages"]["complete"]["label"] == "完成"
    for action in ("dispatch_role", "await_confirmation", "await_effect_approval", "task_complete", "none", "task_resume_after_resolution"):
        assert presentation["actions"][action]["label"].strip()
    assert presentation["actions"]["await_confirmation"]["label"] == "等待确认"
    assert presentation["confirmations"]["EACH_STAGE_POLICY"]["label"].strip()
    assert presentation["confirmations"]["MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION"]["label"].strip()


def test_task_snapshot_projects_governed_workflow_display_fields_without_changing_machine_ids(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    rc, out, err = _run(["workflow", "preference", "--set", "each_stage", "--json"])
    assert rc == 0, (out, err)

    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])
    workflow = snap["workflow"]
    next_step = workflow["next_step"]

    assert next_step["stage"] == "development"
    assert next_step["action"] == "await_confirmation"
    assert next_step["confirmation_reason"] == "EACH_STAGE_POLICY"
    assert next_step["stage_display"]["label"] == "开发"
    assert next_step["role_display"]["label"] == "tp-开发工程师"
    assert next_step["action_display"]["label"] == "等待确认"
    assert next_step["confirmation_display"]["label"] == "等待阶段确认"
    for step in workflow["steps"]:
        assert step["stage_display"]["label"]
        assert step["role_display"]["label"]
        assert step["stage"] in {"requirement", "architecture", "development", "verification"}


def test_task_card_workflow_renderer_uses_projected_labels_and_accessible_technical_details():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "当前步骤" in text
    assert "stage_display" in text
    assert "action_display" in text
    assert "confirmation_display" in text
    assert "workflow-tech-toggle" in text
    assert "aria-expanded" in text
    assert "aria-controls" in text
    assert "必需步骤" in text
    assert "条件步骤" in text
    assert "执行角色：" in text
    assert "条件参与角色" in text
    assert "displayStage(next.stage)" not in text
    assert "`${next.action || ''}" not in text


def test_task_card_prefers_structured_evidence_items_with_task_anchor(tmp_path, monkeypatch):
    import hashlib

    fx = _runtime_fixture(tmp_path, monkeypatch)
    task_dir = fx["workspace"] / ".tp-spec" / "tasks" / "TASK-ACTIVE"
    evidence_file = task_dir / "evidence" / "proof.txt"
    _write(evidence_file, "proof\n")
    digest = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    detail = {
        "evidence_items": [{"type": "local_file", "path": "evidence/proof.txt", "sha256": digest}],
        "evidence": ["evidence/proof.txt"],
    }
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,evidence_path,workflow_version,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "VERIFICATION_COMPLETED", "tp-test-engineer", "proof linked", json.dumps(detail), "evidence/proof.txt", active_version(), dbmod.now_iso()),
        )
    conn.close()

    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])
    item = next(row for row in snap["evidence"] if row["raw_path"] == "evidence/proof.txt")
    assert item["anchor"] == "task"
    assert item["display_name"] == "proof.txt"
    assert item["display_path"] == ".tp-spec/tasks/TASK-ACTIVE/evidence/proof.txt"
    assert item["copy_path"] == item["display_path"]
    assert item["verification"] == "structured"
    assert item["current_exists"] is True
    assert item["sha256"] == digest
    assert item["occurrence_count"] == 1
    assert [source["field"] for source in item["sources"]] == ["detail.evidence_items"]


def test_legacy_bare_evidence_path_is_retained_but_not_claimed_as_project_root(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,evidence_path,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "FACT", "tp-development-engineer", "legacy note", "task.md", active_version(), dbmod.now_iso()),
        )
    conn.close()

    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])
    item = next(row for row in snap["evidence"] if row["raw_path"] == "task.md")
    assert item["anchor"] == "unknown"
    assert item["display_path"] == "task.md"
    assert item["copy_path"] == "task.md"
    assert item["verification"] == "legacy_unverified"
    assert item["scope_label"] == "未验证"


def test_evidence_deduplication_uses_anchor_and_normalized_path(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    now = dbmod.now_iso()
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,evidence_path,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "FACT", "tp-development-engineer", "legacy one", "docs/../docs/a.md", active_version(), now),
        )
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,evidence_path,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "FACT", "tp-development-engineer", "legacy two", "docs/a.md", active_version(), now),
        )
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "FACT", "tp-development-engineer", "structured", json.dumps({"evidence_items": [{"type": "local_file", "path": "docs/a.md", "sha256": "a" * 64}]}), active_version(), now),
        )
    conn.close()

    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])
    matches = [row for row in snap["evidence"] if row["normalized_path"] == "docs/a.md"]
    assert {(row["anchor"], row["occurrence_count"]) for row in matches} == {("unknown", 2), ("task", 1)}


def test_evidence_projection_marks_traversal_and_absolute_paths_unsafe(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    conn = dbmod.connect(str(fx["db_path"]))
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO task_event(task_id,event_type,actor_role,summary,evidence_path,workflow_version,created_at) VALUES(?,?,?,?,?,?,?)",
            ("TASK-ACTIVE", "FACT", "tp-development-engineer", "unsafe paths", "../secret.txt;/tmp/outside.txt;C:\\secret.txt", active_version(), dbmod.now_iso()),
        )
    conn.close()

    from cli.cards.snapshot import build_task_snapshot

    snap = build_task_snapshot("TASK-ACTIVE", db_path=fx["db_path"])
    unsafe = [row for row in snap["evidence"] if row["verification"] == "unsafe"]
    assert {row["raw_path"] for row in unsafe} >= {"../secret.txt", "/tmp/outside.txt", "C:\\secret.txt"}
    assert all(row["anchor"] == "unsafe" for row in unsafe)
    assert all(row["scope_label"] == "不安全路径" for row in unsafe)


def test_evidence_renderer_shows_scope_reason_and_copy_path():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "scope_label" in text
    assert "copy_path" in text
    assert "raw_path" in text
    assert "原始路径" in text
    assert "结构化来源 · 当前文件状态未验证" in text
    assert "evidence-table" in text
    assert "evidence-detail-button" in text
    assert "evidence-detail-table" in text
    assert "evidence-detail-body" in text
    assert "依据 / 规范路径" in text
    assert "table-layout: fixed" in text
    assert ".evidence-table-wrap" in text
    assert "overflow: hidden" in text
    assert "evidence-table-identity" in text
    assert "detailRow.hidden = true" in text
    assert "aria-expanded" in text
    assert "evidence-parent-form" not in text
    assert "作用域" in text
    assert "规范路径" in text
    assert "当前状态" in text
    assert "关联次数" in text
    assert "操作" in text
    assert "来源事件" in text
    assert "来源字段" in text
    assert "发生时间" in text
    assert "来源摘要" in text
    assert "事件 ID" in text
    assert "项目根目录" not in text


def test_task_progress_card_is_bounded_and_scrollable():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "task-progress-card" in text
    assert "max-height: 600px" in text
    assert "overflow: hidden" in text
    assert "task-progress-scroll" in text
    assert "grid-template-rows: auto minmax(0, 1fr)" in text
    assert "scrollbar-gutter: stable" in text
    assert "app.classList.add('task-progress-card')" in text


def test_project_task_tables_use_search_only_and_archive_retired_tasks():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "query.dataset.filter = 'text'" in text
    assert "const state = node('select')" not in text
    assert "全部状态" not in text
    assert "['project-completed', '任务归档']" in text
    assert "taskTable('任务归档', data.archived_tasks || data.completed_tasks || [], 'project-completed')" in text
    assert "const displayState = rowData.retired ? 'RETIRED' : rowData.state" in text
    assert "RETIRED: '已退休'" in text


def test_project_task_statistics_use_semantic_colors():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "['total', '总任务', 'info']" in text
    assert "['active', '进行中', 'info']" in text
    assert "['blocked', '已阻塞', 'warn']" in text
    assert "['completed', '已完成', 'ok']" in text
    assert "['cancelled', '已取消', 'bad']" in text
    assert "['verification_attention', '验证需关注', 'warn']" in text
    assert "node('strong', color || 'muted'" in text


def test_global_and_project_cards_are_bounded_and_scrollable():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert ".global-config-card, .current-project-card { max-height: 600px; overflow: hidden; grid-template-rows: auto minmax(0, 1fr);" in text
    assert ".global-config-card > .card-nav, .current-project-card > .card-nav { position: static; }" in text
    assert ".card-content-scroll { grid-column: 1 / -1; min-height: 0; overflow-y: auto;" in text
    assert "app.classList.add('global-config-card')" in text
    assert "app.classList.add('current-project-card')" in text
    assert "const contentScroll = node('div', 'card-content-scroll')" in text
    assert "metrics(stats, 'project-stats', contentScroll)" in text


def test_inline_task_progress_restores_scroll_after_host_grid_reset(tmp_path):
    from cli.cards.render import render_inline_card

    output = tmp_path / "task-scroll.html"
    render_inline_card(
        {
            "card_type": "active_task",
            "title": "当前任务进度",
            "generated_at": "now",
            "health": "healthy",
            "task": {"task_id": "TASK-SCROLL"},
            "workflow": {},
            "latest_checkpoint": {},
            "blockers": [],
            "verification": {},
            "evidence": [],
            "timeline": [{"event_type": "FACT", "created_at": "now", "summary": "event"}],
            "summary": "",
            "problems": [],
        },
        output,
    )

    fragment = output.read_text(encoding="utf-8")
    assert ".grid { overflow: visible; }" in fragment
    assert ".task-progress-card { overflow: hidden; }" in fragment
    assert fragment.index(".grid { overflow: visible; }") < fragment.index(".task-progress-card { overflow: hidden; }")
    assert ".card-nav { position: static; }" in fragment
    assert ".task-progress-card .card-nav { position: static; }" in fragment
    assert ".task-progress-scroll { min-height: 0; overflow-y: auto;" in fragment
    assert fragment.index(".task-progress-card .card-nav { position: static; }") < fragment.index(".task-progress-scroll { min-height: 0;")


def test_structured_evidence_keeps_task_anchor_when_workspace_root_is_unavailable():
    from cli.cards.evidence_view import build_evidence_view

    rows = build_evidence_view(
        [
            {
                "id": 1,
                "event_type": "FACT",
                "created_at": "2026-08-26T00:00:00Z",
                "summary": "structured evidence",
                "detail_json": json.dumps(
                    {
                        "evidence_items": [
                            {"type": "local_file", "path": "evidence/proof.txt", "sha256": "a" * 64}
                        ]
                    }
                ),
            }
        ],
        task_id="TASK-NO-ROOT",
        project_root=None,
    )

    assert len(rows) == 1
    assert rows[0]["anchor"] == "task"
    assert rows[0]["verification"] == "structured"
    assert rows[0]["display_path"] == ".tp-spec/tasks/TASK-NO-ROOT/evidence/proof.txt"
    assert rows[0]["current_exists"] is None


def test_card_display_skill_contract_separates_generation_capability_and_actual_render():
    display = (BASE / "agents" / "tp-card-display" / "SKILL.md").read_text(encoding="utf-8")
    entry = (BASE / "entry" / "tp-spec-coding" / "SKILL.md").read_text(encoding="utf-8")
    lifecycle = (BASE / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")
    combined = "\n".join((display, entry, lifecycle))

    assert "fragment generated" in display
    assert "host capability confirmed" in display
    assert "actual host render" in display
    assert "capability 未确认" in display
    assert "实际桥接调用成功" in display
    assert "inline.status=generated" in combined
    assert "inline.status=generated` 永远不等于“已展示”" in display


def test_card_display_skill_contract_declares_fail_closed_fallback_reasons():
    display = (BASE / "agents" / "tp-card-display" / "SKILL.md").read_text(encoding="utf-8")

    for reason in (
        "INLINE_CAPABILITY_UNAVAILABLE",
        "INLINE_RENDER_FAILED",
        "INLINE_GENERATION_FAILED",
        "WEB_ARTIFACT_UNAVAILABLE",
        "WEB_ARTIFACT_OPEN_FAILED",
    ):
        assert reason in display
    assert "会话内 HTML fragment → Web Artifact → 离线 HTML" in display
    assert "Runtime DB" in display


def test_card_display_generation_contract_does_not_claim_host_render_state(tmp_path, monkeypatch):
    _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "global.html"
    inline = tmp_path / "inline.html"

    rc, out, err = _run([
        "card", "global", "--output", str(offline), "--inline-output", str(inline),
    ])

    assert rc == 0, (out, err)
    payload = _card_display_payload(out)
    assert payload["inline"]["status"] == "generated"
    assert "rendered" not in payload["inline"]
    assert "host_capability" not in payload["inline"]


def test_b06_project_keeps_cancelled_history_and_reports_workitem_drift(tmp_path,monkeypatch):
    fx = _runtime_fixture(tmp_path,monkeypatch)
    now = dbmod.now_iso()
    with dbmod.connect(str(fx['db_path'])) as conn:
        with dbmod.transactional(conn):
            conn.execute("UPDATE task SET current_state='CANCELLED' WHERE task_id='TASK-BLOCKED'")
            conn.execute("INSERT INTO work_item(item_id,task_id,title,status,created_at,updated_at) VALUES ('WI-PENDING','TASK-DONE','WP-0 milestone','PENDING',?,?)",(now,now))
    from cli.cards.snapshot import build_project_snapshot
    snap = build_project_snapshot(fx['workspace'])
    archive = {row['task_id']:row for row in snap['archived_tasks']}
    assert 'TASK-BLOCKED' in archive
    assert 'TASK-BLOCKED' not in {row['task_id'] for row in snap['in_progress_tasks']}
    assert archive['TASK-DONE']['work_items']['consistency'] == 'NEEDS_RECONCILIATION'
    assert all(row['runtime_status']=='UNKNOWN' for row in snap['in_progress_tasks'])
    assert '不代表整个项目完成' in snap['summary']
    assert any(p['code']=='WORKITEM_DRIFT' and 'TASK-DONE' in p['message'] for p in snap['problems'])


def test_b06_explicit_task_snapshot_exposes_work_records_not_liveness(tmp_path,monkeypatch):
    fx = _runtime_fixture(tmp_path,monkeypatch)
    from scripts.tests.v532_testutil import run_cli
    rc,out,err = run_cli(['work','start','--task','TASK-ACTIVE','--role','tp-development-engineer','--db',str(fx['db_path'])])
    assert rc == 0,(out,err)
    from cli.cards.snapshot import build_task_snapshot
    snap = build_task_snapshot('TASK-ACTIVE',db_path=str(fx['db_path']))
    assert snap['workflow']['work_sessions']['runtime_status']=='UNKNOWN'
    assert snap['workflow']['work_sessions']['open_count']==1
    from cli.cards.render import render_card
    target = tmp_path/'explicit-card.html'
    render_card(snap,target)
    text = target.read_text(encoding='utf-8')
    assert "['执行观察'," in text and '运行状态未知' in text
    assert "['业务里程碑'," in text


def test_b06_non_git_preview_freeze_remains_declared_scope_not_software_complete(tmp_path,monkeypatch):
    import hashlib
    fx = _runtime_fixture(tmp_path,monkeypatch)
    from cli import current_context, orchestration
    tdir = fx['workspace']/'.tp-spec/tasks/TASK-ACTIVE'
    preview = fx['workspace']/'preview.html'
    preview.write_text('<main>isolated prototype</main>',encoding='utf-8')
    digest=hashlib.sha256(preview.read_bytes()).hexdigest()
    text=f'PREVIEW：非 Git 原型已批准 SHA-256 冻结 {digest}；仅作为共享前置，不代表软件交付完成。'
    _write(tdir/'task.md',current_context.START+'\n'+text+'\n'+current_context.END+'\n')
    before=preview.read_bytes()
    progress=orchestration.resolve_progress('TASK-ACTIVE',db_path=str(fx['db_path']))
    assert progress['current_effective']['content']==text
    assert progress['current_effective']['authorization_granted'] is False
    assert not (fx['workspace']/'.git').exists()
    assert preview.read_bytes()==before
    with dbmod.connect_readonly(str(fx['db_path'])) as conn:
        assert conn.execute("SELECT current_state FROM task WHERE task_id='TASK-ACTIVE'").fetchone()[0]=='ACTIVE'
