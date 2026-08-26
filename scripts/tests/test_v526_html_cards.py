# -*- coding: utf-8 -*-
"""V5.2.7 read-only HTML information card regression tests."""
from __future__ import annotations

import contextlib
import io
import json
from argparse import Namespace
from pathlib import Path

import yaml

from cli import db as dbmod
from cli import main as climain
from cli.version import active_version

BASE = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _run(argv: list[str]):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
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
                ("TASK-ACTIVE", "FACT", "requirement", "requirement", "tp-product-manager", "Requirement confirmed", json.dumps({"operation": "CHECKPOINT", "phase": "requirement"}), active_version(), now),
            )
            conn.execute(
                "INSERT INTO task_event(task_id,event_type,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                ("TASK-ACTIVE", "FACT", "architecture", "architecture", "tp-software-architect", "Architecture complete", json.dumps({"operation": "CHECKPOINT", "phase": "architecture"}), active_version(), now),
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
        {"id": "demo-workspace", "root": str(fx["workspace"]), "enabled": True}
    ]
    assert snap["autonomy"]["configured"] is True
    assert snap["autonomy"]["profile_count"] == 2
    assert [profile["profile_id"] for profile in snap["autonomy"]["profiles"]] == ["demo-autonomy", "demo-autonomy-two"]
    assert snap["autonomy"]["profiles"][0] == {
        "profile_id": "demo-autonomy",
        "enabled": True,
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

    assert [item["path"] for item in snap["evidence"]] == ["docs/a.md", "docs/b.md", "docs/c.md"]
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


def test_renderer_presents_evidence_as_grouped_file_rows(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-evidence.html"
    render_card({"card_type": "active_task", "title": "当前任务进度", "generated_at": "now", "health": "healthy", "task": {}, "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {}, "evidence": [], "timeline": [], "summary": "", "problems": []}, output)
    text = output.read_text(encoding="utf-8")

    assert "function evidenceFileName(path)" in text
    assert "function evidenceDirectory(path)" in text
    assert "function evidenceGroupLabel(value)" in text
    assert "依据（${(data.evidence || []).length}）" in text
    assert "复制 ${evidenceFileName(evidence.path)} 路径" in text
    assert ".evidence-row" in text


def test_renderer_presents_timeline_as_localized_grouped_events(tmp_path):
    from cli.cards.render import render_card

    output = tmp_path / "task-timeline.html"
    render_card({"card_type": "active_task", "title": "当前任务进度", "generated_at": "now", "health": "healthy", "task": {}, "workflow": {}, "latest_checkpoint": {}, "blockers": [], "verification": {}, "evidence": [], "timeline": [], "summary": "", "problems": []}, output)
    text = output.read_text(encoding="utf-8")

    assert "REVIEW_COMPLETED: '复审完成'" in text
    assert "WORK_SESSION_STARTED: '工作会话开始'" in text
    assert "WORKFLOW_CONFIRMATION: '工作流确认'" in text
    assert "STATE: '状态变更'" in text
    assert "function eventStatusClass(eventData)" in text
    assert "timeline-day" in text
    assert "event-marker" in text
    assert "event-body" in text
    assert "event-preview" in text
    assert "event-toggle" in text
    assert "eventBody.classList.toggle('open', expanded)" in text


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
    assert "compactTable('配置档案'" in text
    assert "['global-autonomy', '自治维护']" in text
    assert "append(app, autonomyCard(data.autonomy || {}, 'global-autonomy'));" in text
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


def test_trigger_whitelist_excludes_read_only_and_ordinary_operations():
    from cli.cards.trigger import should_refresh_task_card

    assert should_refresh_task_card(Namespace(group="task", subcommand="get", task="TASK-X")) is False
    assert should_refresh_task_card(Namespace(group="workflow", subcommand="next", task="TASK-X")) is False
    assert should_refresh_task_card(Namespace(group="document", document_cmd="convert")) is False
    assert should_refresh_task_card(Namespace(group="task", subcommand="checkpoint", task="TASK-X")) is True
    assert should_refresh_task_card(Namespace(group="work", subcommand="start", task="TASK-X")) is True
    assert should_refresh_task_card(Namespace(group="workflow", subcommand="confirm", task="TASK-X")) is True


def test_successful_formal_task_step_refreshes_single_latest_html(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    card_root = tmp_path / "cards-out"
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))

    rc, out, err = _run([
        "task", "create", "--id", "TASK-NEW", "--project", fx["project_id"],
        "--title", "New task", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])

    assert rc == 0, (out, err)
    output = card_root / "tasks" / "TASK-NEW.html"
    assert output.is_file(), err
    first = output.read_text(encoding="utf-8")
    assert "TASK-NEW" in first
    assert list((card_root / "tasks").glob("TASK-NEW*.html")) == [output]


def test_entry_skill_routes_only_explicit_config_project_and_task_card_requests():
    text = (BASE / "entry" / "tp-spec-coding" / "SKILL.md").read_text(encoding="utf-8")
    assert "tp-spec card global" in text
    assert "tp-spec card project" in text
    assert "tp-spec card task --task" in text
    assert "普通代码搜索" in text
    assert "不得自动生成" in text


def test_lifecycle_skill_defers_task_card_refresh_to_successful_runtime_commands():
    text = (BASE / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")
    assert "task checkpoint" in text
    assert "work start" in text
    assert "workflow confirm" in text
    assert "HTML 卡片失败不得改变原命令成功结果" in text
    assert "不得根据最近执行的任意命令猜测" in text


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


def test_card_render_warning_does_not_change_successful_runtime_command(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("file blocks card output directory", encoding="utf-8")
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(invalid_root))

    rc, out, err = _run([
        "task", "create", "--id", "TASK-CARD-WARN", "--project", fx["project_id"],
        "--title", "Runtime succeeds even if card fails", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])

    assert rc == 0, (out, err)
    assert "CARD_RENDER_WARNING" in err
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

    assert artifact_output_path(workspace) == (workspace / ".tp-spec-preview" / "card" / "index.html").resolve()


def test_explicit_project_card_also_updates_fixed_web_artifact(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch)
    offline = tmp_path / "project-offline.html"

    rc, out, err = _run([
        "card", "project", "--root", str(fx["workspace"]), "--output", str(offline),
    ])

    artifact = fx["workspace"] / ".tp-spec-preview" / "card" / "index.html"
    assert rc == 0, (out, err)
    assert offline.is_file()
    assert artifact.is_file()
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
    artifact = artifact_root / ".tp-spec-preview" / "card" / "index.html"
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
    assert list((artifact_root / ".tp-spec-preview" / "card").glob("*.html")) == [artifact]


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


def test_formal_runtime_refresh_updates_fixed_workspace_artifact(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    card_root = tmp_path / "cards-out"
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))
    monkeypatch.chdir(fx["workspace"])

    rc, out, err = _run([
        "task", "create", "--id", "TASK-ARTIFACT", "--project", fx["project_id"],
        "--title", "Artifact task", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])

    artifact = fx["workspace"] / ".tp-spec-preview" / "card" / "index.html"
    assert rc == 0, (out, err)
    assert artifact.is_file(), err
    text = artifact.read_text(encoding="utf-8")
    assert "TASK-ARTIFACT" in text
    assert list(artifact.parent.glob("*.html")) == [artifact]


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

    assert ".tp-spec-preview/card/index.html" in text
    assert "Web Artifact" in text or "网站预览" in text
    assert "离线 HTML" in text
    assert "不得只返回" in text


def test_lifecycle_skill_refreshes_fixed_artifact_without_new_runtime_semantics():
    text = (BASE / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")

    assert ".tp-spec-preview/card/index.html" in text
    assert "覆盖" in text
    assert "不新增 public state" in text


def test_renderer_uses_internal_scroll_to_reduce_host_layout_shift():
    text = (BASE / "cli" / "cards" / "assets" / "card.html").read_text(encoding="utf-8")

    assert "html, body { height: 100%; }" in text
    assert "overflow: hidden;" in text
    assert "height: 100%;" in text
    assert "overflow-y: auto;" in text
    assert "min-height: 0;" in text


def test_repo_ignores_generated_web_artifact_directory():
    text = (BASE / ".gitignore").read_text(encoding="utf-8")
    assert ".tp-spec-preview/" in text.splitlines()


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
        assert "overflow-y: auto" not in fragment
        assert "position: sticky" not in fragment
        assert "document.body.appendChild" not in fragment
        assert snapshot["title"] in fragment
        assert len(fragment.encode("utf-8")) < 1_000_000

        marker = 'id="tp-spec-card-'
        root = fragment.split(marker, 1)[1].split('"', 1)[0]
        roots.add(root)
        assert f"document.getElementById('tp-spec-card-{root}')" in fragment

    assert len(roots) == 3


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
            "TP-Spec 全局配置",
        ),
        (
            ["card", "project", "--root", str(fx["workspace"])],
            "project",
            fx["project_id"],
        ),
        (
            ["card", "task", "--task", "TASK-ACTIVE", "--db", str(fx["db_path"])],
            "task",
            "TASK-ACTIVE",
        ),
    ]

    for argv, name, expected in commands:
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


def test_formal_runtime_step_can_emit_inline_task_fragment(tmp_path, monkeypatch):
    fx = _runtime_fixture(tmp_path, monkeypatch, include_active=False)
    card_root = tmp_path / "cards-out"
    inline = tmp_path / "conversation" / "task-inline.html"
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))
    monkeypatch.setenv("TP_SPEC_CARD_INLINE_OUTPUT", str(inline))
    monkeypatch.chdir(fx["workspace"])

    rc, out, err = _run([
        "task", "create", "--id", "TASK-INLINE", "--project", fx["project_id"],
        "--title", "Inline task", "--risk", "L0", "--flow", "L0", "--db", str(fx["db_path"]),
    ])

    assert rc == 0, (out, err)
    assert inline.is_file(), err
    assert f"INLINE_VISUALIZATION: {inline.resolve()}" in out
    fragment = inline.read_text(encoding="utf-8")
    assert "TASK-INLINE" in fragment
    assert "<!doctype" not in fragment.lower()


def test_formal_runtime_inline_failure_keeps_runtime_and_other_previews_successful(tmp_path, monkeypatch):
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
    assert "CARD_INLINE_WARNING" in err
    assert (card_root / "tasks" / "TASK-INLINE-WARN.html").is_file()
    assert (fx["workspace"] / ".tp-spec-preview" / "card" / "index.html").is_file()
    conn = dbmod.connect_readonly(str(fx["db_path"]))
    try:
        row = conn.execute("SELECT task_id FROM task WHERE task_id='TASK-INLINE-WARN'").fetchone()
    finally:
        conn.close()
    assert row is not None


def test_formal_refresh_forwards_explicit_base_root_to_task_snapshot(tmp_path, monkeypatch):
    from cli.cards.trigger import refresh_after_success

    fx = _runtime_fixture(tmp_path, monkeypatch)
    alternate_base = tmp_path / "alternate-base"
    major, minor, patch = (int(part) for part in active_version().split("."))
    alternate_version = f"{major}.{minor}.{patch + 1}"
    _write(alternate_base / "VERSION", f"{alternate_version}\n")
    card_root = tmp_path / "cards-out"
    monkeypatch.setenv("TP_SPEC_CARD_OUTPUT_ROOT", str(card_root))
    monkeypatch.chdir(fx["workspace"])

    refresh_after_success(Namespace(
        group="workflow",
        subcommand="confirm",
        task="TASK-ACTIVE",
        db=str(fx["db_path"]),
        base_root=str(alternate_base),
    ))

    rendered = (card_root / "tasks" / "TASK-ACTIVE.html").read_text(encoding="utf-8")
    assert f"任务 Contract {active_version()} 与当前 Base {alternate_version} 不一致" in rendered


def test_card_skills_require_same_turn_inline_reference_with_fallbacks():
    entry = (BASE / "entry" / "tp-spec-coding" / "SKILL.md").read_text(encoding="utf-8")
    lifecycle = (BASE / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")

    assert "--inline-output" in entry
    assert "visualize" in entry
    assert "同一次回复" in entry
    assert "TP_SPEC_CARD_INLINE_OUTPUT" in lifecycle
    assert "INLINE_VISUALIZATION" in lifecycle
    assert "会话内" in lifecycle
