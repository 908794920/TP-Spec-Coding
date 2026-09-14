# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.tests.runtime_testutil import run
from cli import db as dbmod
from cli import event_policies, orchestration


class KnowledgeTaskCase:
    def setup_method(self):
        self.root = Path(tempfile.mkdtemp(prefix="v529-knowledge-convergence-"))
        self.project = self.root / "project"
        self.registry = self.root / "registry.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        self.user_root = self.root / "user-tp-spec"
        self.env = patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(self.user_root)}, clear=False)
        self.env.start()

        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project),
            "--registry", str(self.registry),
        ])
        assert rc == 0, (out, err)
        self.db = self.project / ".tp-spec" / "db" / "demo.db"

        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.project, check=True)
        (self.project / "README.md").write_text("demo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=self.project, check=True)

        self.wiki_root = self.root / "wiki"
        self.knowledge_root = self.root / "knowledge"
        self.wiki_root.mkdir(parents=True, exist_ok=True)
        (self.knowledge_root / "00-system").mkdir(parents=True, exist_ok=True)
        (self.knowledge_root / "10-projects" / "demo" / "30-features").mkdir(parents=True, exist_ok=True)
        base_root = Path(__file__).resolve().parents[2]
        self.user_root.mkdir(parents=True, exist_ok=True)
        (self.user_root / "installation.yaml").write_text(
            "schema: tp-spec.installation/v1\n"
            f"base:\n  root: {json.dumps(str(base_root))}\n"
            f"systems:\n  wiki:\n    root: {json.dumps(str(self.wiki_root))}\n"
            f"  knowledge:\n    root: {json.dumps(str(self.knowledge_root))}\n",
            encoding="utf-8",
        )
        (self.knowledge_root / "00-system" / "project-registry.yaml").write_text(
            "registry_version: \"1\"\nprojects:\n"
            f"  - id: demo\n    display_name: Demo\n    status: active\n    workspace_roots:\n      - {json.dumps(str(self.project))}\n"
            "shared_scopes: []\n",
            encoding="utf-8",
        )
        rc, out, err = run(["knowledge", "index", "build", "--workspace-root", str(self.project)])
        assert rc == 0, (out, err)

    def teardown_method(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def call(self, *args):
        return run(list(args) + ["--db", str(self.db)])

    def events(self, task_id: str, event_type: str | None = None):
        conn = dbmod.connect(str(self.db))
        try:
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM task_event WHERE task_id=? AND event_type=? ORDER BY id",
                    (task_id, event_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def create_task(self, task_id: str) -> Path:
        task_dir = self.project / ".tp-spec" / "tasks" / task_id
        rc, out, err = run([
            "task", "create", "--id", task_id, "--project", "demo", "--risk", "L2", "--flow", "L2",
            "--db", str(self.db), "--scaffold", "--task-dir", str(task_dir),
        ])
        assert rc == 0, (out, err)
        (task_dir / "acceptance.md").write_text(
            "# 验收条件与证据矩阵\n\n"
            "```yaml\n"
            "no_acceptance_required:\n"
            "  declared: true\n"
            "  reason: Knowledge 收敛流程测试不包含业务验收项\n"
            "deferred_acceptance: []\n"
            "owner_waivers: []\n"
            "database_operations: []\n"
            "```\n",
            encoding="utf-8",
        )
        return task_dir

    def checkpoint(self, task_id: str, task_dir: Path, actor: str, phase: str):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", actor, "--phase", phase, "--summary", f"{phase} done",
        )
        assert rc == 0, (out, err)

    def prepare_delivery(self, task_id: str, *, knowledge_signal: dict | None = None,
                         extra_evidence: dict[str, str] | None = None) -> Path:
        task_dir = self.create_task(task_id)
        self.checkpoint(task_id, task_dir, "tp-product-manager", "requirement")
        self.checkpoint(task_id, task_dir, "tp-software-architect", "architecture")
        self.checkpoint(task_id, task_dir, "tp-tech-lead", "planning")
        rc, out, err = self.call("workflow", "confirm", "--task", task_id, "--task-dir", str(task_dir), "--json")
        assert rc == 0, (out, err)
        self.checkpoint(task_id, task_dir, "tp-development-engineer", "development")

        ev = task_dir / "evidence" / "verification.txt"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text("verified knowledge candidate\n", encoding="utf-8")
        for name, content in (extra_evidence or {}).items():
            (task_dir / "evidence" / name).write_text(content, encoding="utf-8")
        verify_args = [
            "task", "verify", "--task", task_id, "--task-dir", str(task_dir),
            "--decision", "PASS", "--summary", "verification PASS",
            "--evidence", "evidence/verification.txt",
        ]
        if knowledge_signal is not None:
            verify_args += ["--knowledge-signal-json", json.dumps(knowledge_signal, ensure_ascii=False)]
        rc, out, err = self.call(*verify_args)
        assert rc == 0, (out, err)

        (task_dir / "evidence/code-review.txt").write_text("Synthetic reviewer evidence for the current subject.\n", encoding="utf-8")
        rc, out, err = self.call(
            "review", "record", "--task", task_id, "--task-dir", str(task_dir),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS",
            "--summary", "code review PASS", "--evidence", "evidence/code-review.txt",
        )
        assert rc == 0, (out, err)
        return task_dir

    def deliver_ready(self, task_id: str, task_dir: Path):
        rc, out, err = self.call(
            "task", "delivery-converge", "--task", task_id, "--task-dir", str(task_dir),
            "--delivery-status", "READY",
            "--reason", "Verified change is ready for integration and no delivery blocker remains.",
        )
        assert rc == 0, (out, err)
        return json.loads(out)

    def latest_request(self, task_id: str):
        rows = self.events(task_id, "KNOWLEDGE_CONVERGENCE_REQUEST")
        assert rows
        row = rows[-1]
        return row, json.loads(row["detail_json"])


def test_integration_can_write_request_but_not_result():
    assert event_policies.event_allowed_for_producer("KNOWLEDGE_CONVERGENCE_REQUEST", "delivery_converge")
    assert not event_policies.event_allowed_for_producer("KNOWLEDGE_CONVERGENCE_REQUEST", "event_add")
    assert event_policies.event_allowed_for_producer("KNOWLEDGE_CONVERGENCE_RESULT", "knowledge_task_converge")
    assert not event_policies.event_allowed_for_producer("KNOWLEDGE_CONVERGENCE_RESULT", "delivery_converge")


def test_required_request_without_result_routes_knowledge_and_blocks_completion():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-REQ"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "NEW_BUSINESS_RULE", "summary": "新增长期业务规则",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, request = case.latest_request(task_id)
        assert request_row["actor_role"] == "tp-integration-engineer"
        assert request["producer"] == "delivery_converge"
        assert request["change_set_id"]
        assert request["trigger_reason_codes"] == ["NEW_BUSINESS_RULE"]

        route = orchestration.resolve_route(task_id, db_path=str(case.db))
        assert route["recommended_action"] == "dispatch_effect"
        assert route["role_id"] == "tp-knowledge"
        assert route["next_stage"] == "complete"

        rc, out, err = case.call(
            "task", "complete", "--task", task_id, "--task-dir", str(task_dir),
            "--summary", "must wait for knowledge convergence",
        )
        assert rc != 0
        assert "INTEGRITY_PIPELINE_PENDING" in err

        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "NO_DURABLE_INSIGHT",
            "--reason-code", "TASK_SPECIFIC_LOW_REUSE_VALUE",
            "--query", "one-off business rule", "--source", "evidence/verification.txt",
        ])
        assert rc == 0, (out, err)
        completed = orchestration.resolve_route(task_id, db_path=str(case.db))
        assert completed["recommended_action"] == "task_complete"
        assert completed["next_stage"] == "complete"
    finally:
        case.teardown_method()


def test_no_knowledge_signal_is_not_required():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-NOT-REQUIRED"
        task_dir = case.prepare_delivery(task_id)
        case.deliver_ready(task_id, task_dir)
        assert case.events(task_id, "KNOWLEDGE_CONVERGENCE_REQUEST") == []
        route = orchestration.resolve_route(task_id, db_path=str(case.db))
        assert route["recommended_action"] == "task_complete"
        assert route["next_stage"] == "complete"
    finally:
        case.teardown_method()


def test_no_durable_insight_requires_queries_sources_and_reason_code():
    from cli.main import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "knowledge", "task-converge",
            "--task", "TASK-1", "--task-dir", "/tmp/task", "--db", "/tmp/db",
            "--workspace-root", "/tmp/workspace", "--request-event-id", "1",
            "--disposition", "NO_DURABLE_INSIGHT",
        ])


def test_duplicate_requires_targeted_search_hit():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-DUP"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "NEW_BUSINESS_RULE", "summary": "门禁授权长期规则",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, _ = case.latest_request(task_id)

        note = case.knowledge_root / "10-projects" / "demo" / "30-features" / "DEMO-FEAT-001-Gate.md"
        note.write_text(
            "---\n"
            "id: DEMO-FEAT-001\n"
            "title: Gate Rule\n"
            "project: demo\n"
            "kind: feature\n"
            "status: active\n"
            "canonical: true\n"
            "source_refs: [TASK-V529-KNOW-DUP]\n"
            "confidence: 0.9\n"
            "last_verified: '2026-08-29'\n"
            "relations: []\n"
            "---\n# Gate Rule\n门禁授权长期规则 durable gate rule\n",
            encoding="utf-8",
        )
        rc, out, err = run(["knowledge", "index", "build", "--workspace-root", str(case.project)])
        assert rc == 0, (out, err)

        common = [
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "DUPLICATE", "--reason-code", "EXISTING_KNOWLEDGE_COVERS_INSIGHT",
            "--query", "durable gate rule", "--source", "evidence/verification.txt",
        ]
        rc, out, err = run(common + ["--knowledge-ref", "DEMO-FEAT-999"])
        assert rc != 0
        assert "knowledge-ref" in out.lower() or "knowledge-ref" in err.lower() or "DUPLICATE" in out

        rc, out, err = run(common + ["--knowledge-ref", "DEMO-FEAT-001"])
        assert rc == 0, (out, err)
        result = json.loads(out)
        assert result["knowledge_disposition"] == "DUPLICATE"
        assert result["query_receipts"][0]["scope"] == "project+shared"
        assert "DEMO-FEAT-001" in result["query_receipts"][0]["matched_canonical_refs"]
    finally:
        case.teardown_method()


def test_created_validates_exact_canonical_and_indexes_only_that_ref():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-CREATED"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "NEW_BUSINESS_RULE", "summary": "brand new durable rule",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, _ = case.latest_request(task_id)

        note = case.knowledge_root / "10-projects" / "demo" / "30-features" / "DEMO-FEAT-009-NewRule.md"
        note.write_text(
            "---\n"
            "id: DEMO-FEAT-009\n"
            "title: New Durable Rule\n"
            "project: demo\n"
            "kind: feature\n"
            "status: active\n"
            "canonical: true\n"
            "source_refs: []\n"
            "confidence: 0.9\n"
            "last_verified: '2026-08-29'\n"
            "relations: []\n"
            "evidence_refs:\n"
            f"  - type: task\n    ref: {task_id}\n    locator: evidence/verification.txt\n"
            "---\n# New Durable Rule\nbrand new durable rule for access control\n",
            encoding="utf-8",
        )

        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "CREATED", "--reason-code", "NEW_DURABLE_INSIGHT",
            "--query", "brand new durable rule", "--source", "evidence/verification.txt",
            "--knowledge-ref", "DEMO-FEAT-009",
        ])
        assert rc == 0, (out, err)
        result = json.loads(out)
        assert result["knowledge_ref"] == "DEMO-FEAT-009"
        assert result["canonical_receipt"]["lint"]["status"] == "PASS"
        assert result["canonical_receipt"]["index"]["status"] == "PASS"

        rc, out, err = run([
            "knowledge", "search", "--workspace-root", str(case.project),
            "--scope", "project", "--query", "brand new durable rule",
        ])
        assert rc == 0, (out, err)
        hits = json.loads(out)["results"]
        assert any(hit.get("id") == "DEMO-FEAT-009" for hit in hits)
    finally:
        case.teardown_method()


def test_updated_exact_canonical_can_replace_stale_indexed_path():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-UPDATED"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "NEW_BUSINESS_RULE", "summary": "existing durable rule update",
            "evidence": ["evidence/verification.txt"],
        })
        canonical_dir = case.knowledge_root / "10-projects" / "demo" / "30-features"
        old = canonical_dir / "DEMO-FEAT-011-OldName.md"
        old.write_text(
            "---\nid: DEMO-FEAT-011\ntitle: Old Rule\nproject: demo\nkind: feature\nstatus: active\ncanonical: true\n"
            "source_refs: [TASK-LEGACY]\nconfidence: 0.8\nlast_verified: '2026-08-28'\nrelations: []\n"
            "---\n# Old Rule\nexisting durable rule update\n",
            encoding="utf-8",
        )
        rc, out, err = run(["knowledge", "index", "build", "--workspace-root", str(case.project)])
        assert rc == 0, (out, err)

        case.deliver_ready(task_id, task_dir)
        request_row, _ = case.latest_request(task_id)
        new = canonical_dir / "DEMO-FEAT-011-Renamed.md"
        old.rename(new)
        new.write_text(
            "---\nid: DEMO-FEAT-011\ntitle: Renamed Rule\nproject: demo\nkind: feature\nstatus: active\ncanonical: true\n"
            "source_refs: []\nconfidence: 0.9\nlast_verified: '2026-08-29'\nrelations: []\n"
            f"evidence_refs:\n  - type: task\n    ref: {task_id}\n    locator: evidence/verification.txt\n"
            "---\n# Renamed Rule\nexisting durable rule update with clarified semantics\n",
            encoding="utf-8",
        )
        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "UPDATED", "--reason-code", "DURABLE_INSIGHT_UPDATED",
            "--query", "existing durable rule update", "--source", "evidence/verification.txt",
            "--knowledge-ref", "DEMO-FEAT-011",
        ])
        assert rc == 0, (out, err)
        rc, out, err = run([
            "knowledge", "search", "--workspace-root", str(case.project),
            "--scope", "project", "--query", "clarified semantics",
        ])
        assert rc == 0, (out, err)
        hits = json.loads(out)["results"]
        match = next(hit for hit in hits if hit.get("id") == "DEMO-FEAT-011")
        assert match["path"].endswith("DEMO-FEAT-011-Renamed.md")
    finally:
        case.teardown_method()


def test_created_rejects_canonical_without_current_task_evidence_binding():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-CREATED-BAD"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "NEW_BUSINESS_RULE", "summary": "unbound durable rule",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, _ = case.latest_request(task_id)
        note = case.knowledge_root / "10-projects" / "demo" / "30-features" / "DEMO-FEAT-010-Unbound.md"
        note.write_text(
            "---\n"
            "id: DEMO-FEAT-010\n"
            "title: Unbound Rule\nproject: demo\nkind: feature\nstatus: active\ncanonical: true\n"
            "source_refs: []\nconfidence: 0.9\nlast_verified: '2026-08-29'\nrelations: []\n"
            "evidence_refs:\n  - type: task\n    ref: TASK-OTHER\n    locator: evidence/verification.txt\n"
            "---\n# Unbound\nunbound durable rule\n",
            encoding="utf-8",
        )
        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "CREATED", "--reason-code", "NEW_DURABLE_INSIGHT",
            "--query", "unbound durable rule", "--source", "evidence/verification.txt",
            "--knowledge-ref", "DEMO-FEAT-010",
        ])
        assert rc != 0
        assert "bind task evidence" in (out + err).lower() or "canonical" in (out + err).lower()
    finally:
        case.teardown_method()


def test_result_must_bind_same_request_and_change_set():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-STALE"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "ROOT_CAUSE_LEARNING", "summary": "可复用故障根因",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, _ = case.latest_request(task_id)

        (case.project / "README.md").write_text("changed after request\n", encoding="utf-8")
        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "NO_DURABLE_INSIGHT", "--reason-code", "TASK_SPECIFIC_LOW_REUSE_VALUE",
            "--query", "root cause learning", "--source", "evidence/verification.txt",
        ])
        assert rc != 0
        assert "change_set" in out.lower() or "change_set" in err.lower() or "stale" in out.lower()
    finally:
        case.teardown_method()


def test_result_sources_must_be_bound_to_request():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-SOURCE-BOUND"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "ROOT_CAUSE_LEARNING", "summary": "可复用故障根因",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, request = case.latest_request(task_id)
        assert "evidence/verification.txt" in request["source_refs"]

        unrelated = task_dir / "evidence" / "unrelated.txt"
        unrelated.write_text("not part of the trusted request\n", encoding="utf-8")
        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "NO_DURABLE_INSIGHT", "--reason-code", "TASK_SPECIFIC_LOW_REUSE_VALUE",
            "--query", "root cause learning", "--source", "evidence/unrelated.txt",
        ])
        assert rc != 0
        combined = (out + err).lower()
        assert "source" in combined and "request" in combined
    finally:
        case.teardown_method()



@pytest.mark.parametrize("source, action, role", [
    ("evidence/verification.txt", "dispatch_role", "tp-test-engineer"),
    ("evidence/learning.txt", "dispatch_effect", "tp-knowledge"),
])
def test_result_becomes_stale_when_bound_source_changes(source, action, role):
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        task_id = "TASK-V529-KNOW-SOURCE-STALE"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "ROOT_CAUSE_LEARNING", "summary": "可复用故障根因",
            "evidence": [source],
        }, extra_evidence={"learning.txt": "independent learning source\n"})
        case.deliver_ready(task_id, task_dir)
        request_row, request = case.latest_request(task_id)
        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "NO_DURABLE_INSIGHT", "--reason-code", "TASK_SPECIFIC_LOW_REUSE_VALUE",
            "--query", "root cause learning", "--source", source,
        ])
        assert rc == 0, (out, err)
        assert orchestration.resolve_route(task_id, db_path=str(case.db))["recommended_action"] == "task_complete"

        (task_dir / source).write_text("changed after Knowledge convergence\n", encoding="utf-8")
        # Knowledge freshness still applies to both sources. When the very same
        # file also proves Verification PASS, that prerequisite must recover first.
        assert orchestration._knowledge_result_for_request(
            case.events(task_id), {"event": request_row, "detail": request}, task_dir,
        ) is None
        route = orchestration.resolve_route(task_id, db_path=str(case.db))
        assert route["recommended_action"] == action
        assert route["role_id"] == role
        if role == "tp-test-engineer":
            assert "CURRENT_VERIFICATION_REQUIRED" in route["reason_codes"]
    finally:
        case.teardown_method()


def test_task_scoped_convergence_uses_targeted_search_not_full_vault_scan():
    import inspect
    from cli.knowledge import commands as knowledge_commands
    from cli.knowledge import projection as knowledge_projection
    source = (
        inspect.getsource(knowledge_commands.cmd_task_converge)
        + inspect.getsource(knowledge_commands._search_receipt)
        + inspect.getsource(knowledge_commands._resolve_exact_canonical_note)
        + inspect.getsource(knowledge_commands._validate_knowledge_ref)
        + inspect.getsource(knowledge_projection.update_canonical_note_projection)
    )
    assert "search(" in source
    for forbidden in ("collect_notes", "build_projection", "update_projection(", "migration_plan", "evaluate(", "register_batch"):
        assert forbidden not in source


def test_knowledge_projection_distinguishes_not_required_not_run_and_result():
    case = KnowledgeTaskCase(); case.setup_method()
    try:
        no_signal_id = "TASK-V529-KNOW-PROJ-NR"
        no_signal_dir = case.prepare_delivery(no_signal_id)
        case.deliver_ready(no_signal_id, no_signal_dir)
        text = (no_signal_dir / "status.yaml").read_text(encoding="utf-8")
        assert 'knowledge: "NOT_REQUIRED"' in text

        task_id = "TASK-V529-KNOW-PROJ-REQ"
        task_dir = case.prepare_delivery(task_id, knowledge_signal={
            "type": "ROOT_CAUSE_LEARNING", "summary": "一次性故障调查结论",
            "evidence": ["evidence/verification.txt"],
        })
        case.deliver_ready(task_id, task_dir)
        request_row, _ = case.latest_request(task_id)
        text = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert 'knowledge: "NOT_RUN"' in text

        rc, out, err = run([
            "knowledge", "task-converge",
            "--task", task_id, "--task-dir", str(task_dir), "--db", str(case.db),
            "--workspace-root", str(case.project), "--request-event-id", str(request_row["id"]),
            "--disposition", "NO_DURABLE_INSIGHT", "--reason-code", "TASK_SPECIFIC_LOW_REUSE_VALUE",
            "--query", "one-off incident detail", "--source", "evidence/verification.txt",
        ])
        assert rc == 0, (out, err)
        text = (task_dir / "status.yaml").read_text(encoding="utf-8")
        assert 'knowledge: "NO_DURABLE_INSIGHT"' in text
        route = orchestration.resolve_route(task_id, db_path=str(case.db))
        assert route["recommended_action"] == "task_complete"
    finally:
        case.teardown_method()


def test_task_knowledge_guidance_uses_typed_request_result_contract():
    root = Path(__file__).resolve().parents[2]
    knowledge = (root / "agents" / "tp-knowledge" / "SKILL.md").read_text(encoding="utf-8")
    lifecycle = (root / "agents" / "tp-software-lifecycle" / "SKILL.md").read_text(encoding="utf-8")
    integration = (root / "skills" / "roles" / "tp-integration-engineer" / "SKILL.md").read_text(encoding="utf-8")
    rule = (root / "governance" / "knowledge-rule.yaml").read_text(encoding="utf-8")
    api = (root / "governance" / "runtime-api.yaml").read_text(encoding="utf-8")

    assert "CREATED / UPDATED / DUPLICATE / NO_DURABLE_INSIGHT" in knowledge
    assert "NOT_RUN" in knowledge
    assert "KNOWLEDGE_CONVERGENCE_REQUEST" in integration
    assert "Integration 不写最终 Knowledge Result" in integration
    assert "dispatch_effect" in lifecycle and "tp-knowledge" in lifecycle
    assert "completion_gate: conditional" in rule
    assert "--request-event-id" in api
    assert "--knowledge-disposition" not in api

    import inspect
    delivery_pack = inspect.getsource(orchestration._delivery_fact_pack)
    assert "NO_CHANGE" not in delivery_pack
    assert "DEFERRED" not in delivery_pack
    assert "Integration 不写最终 Knowledge Result" in integration
