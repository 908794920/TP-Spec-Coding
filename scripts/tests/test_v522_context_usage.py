from __future__ import annotations

from cli import context_usage


def test_minimal_receipt_gets_defaults():
    items, warnings = context_usage.normalize_context_usage([
        {"source_type": "wiki", "asset_id": "wiki:demo/backend/architecture.md", "stage": "retrieved"}
    ])
    assert warnings == []
    assert items == [{
        "source_type": "wiki",
        "asset_id": "wiki:demo/backend/architecture.md",
        "stage": "retrieved",
        "outcome": "unknown",
        "confidence": "medium",
        "source_followup": "unknown",
        "evidence": [],
    }]


def test_invalid_payload_is_soft_failed():
    decoded, warnings = context_usage.parse_context_usage_json("{broken")
    assert decoded == []
    assert warnings
    items, more = context_usage.normalize_context_usage(decoded)
    assert items == []
    assert more == []


def test_invalid_item_is_dropped_not_raised():
    items, warnings = context_usage.normalize_context_usage([
        {"source_type": "no-such-type", "asset_id": "x", "stage": "retrieved"},
        {"source_type": "wiki", "asset_id": "", "stage": "retrieved"},
        {"source_type": "wiki", "asset_id": "wiki:demo/a.md", "stage": "adopted"},
    ])
    assert len(items) == 1
    assert items[0]["asset_id"] == "wiki:demo/a.md"
    assert len(warnings) == 2


def test_non_unknown_source_followup_without_evidence_is_downgraded():
    items, warnings = context_usage.normalize_context_usage([
        {
            "source_type": "wiki",
            "asset_id": "wiki:demo/a.md",
            "stage": "adopted",
            "source_followup": "targeted",
        }
    ])
    assert items[0]["source_followup"] == "unknown"
    assert any("downgraded" in x for x in warnings)


def test_non_unknown_source_followup_with_evidence_is_retained():
    items, warnings = context_usage.normalize_context_usage([
        {
            "source_type": "wiki",
            "asset_id": "wiki:demo/a.md",
            "stage": "adopted",
            "source_followup": "targeted",
            "evidence": ["tool:read:src/a.py"],
        }
    ])
    assert warnings == []
    assert items[0]["source_followup"] == "targeted"


def test_memory_project_fragment_is_frozen():
    items, warnings = context_usage.normalize_context_usage([
        {"source_type": "memory_project", "asset_id": "memory_project:demo#constraints", "stage": "adopted"},
        {"source_type": "memory_project", "asset_id": "memory_project:demo#random-heading", "stage": "adopted"},
    ])
    assert [x["asset_id"] for x in items] == ["memory_project:demo#constraints"]
    assert warnings


def test_machine_absolute_paths_are_not_accepted():
    items, warnings = context_usage.normalize_context_usage([
        {"source_type": "wiki", "asset_id": r"wiki:C:\private\wiki.md", "stage": "retrieved"}
    ])
    assert items == []
    assert warnings


def test_prefixed_posix_absolute_paths_are_not_accepted():
    items, warnings = context_usage.normalize_context_usage([
        {"source_type": "wiki", "asset_id": "wiki:/home/private/wiki.md", "stage": "retrieved"},
        {"source_type": "wiki", "asset_id": "wiki:demo/a.md", "stage": "adopted", "evidence": ["tool:read:/home/private/a.py"]},
    ])
    assert len(items) == 1
    assert items[0]["asset_id"] == "wiki:demo/a.md"
    assert items[0]["evidence"] == []
    assert warnings


def test_duplicate_asset_collapses_and_adopted_wins():
    items, warnings = context_usage.normalize_context_usage([
        {"source_type": "knowledge", "asset_id": "knowledge:DEMO-FEAT-001", "stage": "adopted"},
        {"source_type": "knowledge", "asset_id": "knowledge:DEMO-FEAT-001", "stage": "retrieved"},
    ])
    assert len(items) == 1
    assert items[0]["stage"] == "adopted"
    assert warnings


def test_unknown_fields_are_ignored_for_forward_compatibility():
    items, warnings = context_usage.normalize_context_usage([
        {
            "source_type": "memory_skill",
            "asset_id": "memory_skill:demo/start-project",
            "stage": "retrieved",
            "future_field": {"v": 2},
        }
    ])
    assert warnings == []
    assert "future_field" not in items[0]


def test_delivery_search_receipts_become_high_confidence_knowledge_retrievals():
    usage = context_usage.knowledge_usage_from_delivery(
        search_receipts=[{
            "query_hash": "a" * 64,
            "results": [
                {"id": "DEMO-FEAT-001", "layer": "canonical"},
                {"id": "SRC-demo-001", "layer": "source"},
            ],
        }],
        resolved_knowledge_refs=[],
    )
    by_id = {x["asset_id"]: x for x in usage}
    assert by_id["knowledge:DEMO-FEAT-001"]["stage"] == "retrieved"
    assert by_id["knowledge:DEMO-FEAT-001"]["outcome"] == "success"
    assert by_id["knowledge:SRC-demo-001"]["outcome"] == "fallback"
    assert all(x["confidence"] == "high" for x in usage)


def test_resolved_canonical_is_upgraded_to_adopted():
    usage = context_usage.knowledge_usage_from_delivery(
        search_receipts=[{
            "query_hash": "b" * 64,
            "results": [{"id": "DEMO-FEAT-001", "layer": "canonical"}],
        }],
        resolved_knowledge_refs=[
            {"id": "DEMO-FEAT-001", "path": "10-projects/demo/30-features/DEMO-FEAT-001-X.md"},
            {"id": "DEMO-FEAT-NEW", "path": "10-projects/demo/30-features/DEMO-FEAT-NEW-X.md"},
        ],
    )
    by_id = {x["asset_id"]: x for x in usage}
    assert by_id["knowledge:DEMO-FEAT-001"]["stage"] == "adopted"
    assert by_id["knowledge:DEMO-FEAT-NEW"]["stage"] == "adopted"

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import db as dbmod
from cli import main as climain


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class TestContextUsageRuntimeIntegration(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v522-context-usage-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / "project"
        self.registry = self.root / "registry.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        self.user_root = self.root / "user"
        self.env = patch.dict(os.environ, {"TP_SPEC_USER_ROOT": str(self.user_root)}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        rc, out, err = _run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project),
            "--registry", str(self.registry),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.db = self.project / ".tp-spec" / "db" / "demo.db"
        self.wiki_root = self.root / "wiki"; self.wiki_root.mkdir()
        self.knowledge_root = self.root / "knowledge"
        (self.knowledge_root / "00-system").mkdir(parents=True)
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
            'registry_version: "1"\nprojects:\n'
            f'  - id: demo\n    display_name: Demo\n    status: active\n    workspace_roots:\n      - {json.dumps(str(self.project))}\n'
            'shared_scopes: []\n', encoding="utf-8",
        )
        rc, out, err = _run(["knowledge", "index", "build", "--workspace-root", str(self.project)])
        self.assertEqual(rc, 0, (out, err))
        self.task_id = "TASK-V522-CONTEXT"
        self.task_dir = self.project / ".tp-spec" / "tasks" / self.task_id
        rc, out, err = self.call(
            "task", "create", "--id", self.task_id, "--project", "demo",
            "--risk", "L2", "--flow", "L2", "--scaffold", "--task-dir", str(self.task_dir),
        )
        self.assertEqual(rc, 0, (out, err))

    def call(self, *args):
        return _run(list(args) + ["--db", str(self.db)])

    def latest_detail(self, event_type):
        conn = dbmod.connect(str(self.db))
        try:
            row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type=? ORDER BY id DESC LIMIT 1",
                (self.task_id, event_type),
            ).fetchone()
            self.assertIsNotNone(row)
            return json.loads(row["detail_json"] or "{}")
        finally:
            conn.close()

    def test_checkpoint_persists_context_usage(self):
        payload = json.dumps([{
            "source_type": "memory_project",
            "asset_id": "memory_project:demo#constraints",
            "stage": "adopted",
        }])
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineering", "--phase", "development",
            "--summary", "implemented", "--context-usage-json", payload,
        )
        self.assertEqual(rc, 0, (out, err))
        detail = self.latest_detail("FACT")
        self.assertEqual(detail["context_usage"][0]["asset_id"], "memory_project:demo#constraints")

    def test_invalid_checkpoint_context_usage_does_not_block_checkpoint(self):
        rc, out, err = self.call(
            "task", "checkpoint", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-development-engineering", "--phase", "development",
            "--summary", "implemented", "--context-usage-json", "{broken",
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("WARN: context telemetry:", err)
        self.assertNotIn("context_usage", self.latest_detail("FACT"))

    def test_invalid_verification_context_usage_does_not_block_verification(self):
        evidence = self.task_dir / "evidence" / "verify-bad-context.txt"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text("ok\n", encoding="utf-8")
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--decision", "PASS", "--summary", "verified", "--evidence", "evidence/verify-bad-context.txt",
            "--context-usage-json", "{broken",
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("WARN: context telemetry:", err)
        self.assertNotIn("context_usage", self.latest_detail("VERIFICATION_COMPLETED"))

    def test_verification_persists_context_usage(self):
        evidence = self.task_dir / "evidence" / "verify.txt"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text("ok\n", encoding="utf-8")
        payload = json.dumps([{
            "source_type": "memory_skill",
            "asset_id": "memory_skill:demo/start-project",
            "stage": "adopted",
        }])
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--decision", "PASS", "--summary", "verified", "--evidence", "evidence/verify.txt",
            "--context-usage-json", payload,
        )
        self.assertEqual(rc, 0, (out, err))
        detail = self.latest_detail("VERIFICATION_COMPLETED")
        self.assertEqual(detail["context_usage"][0]["source_type"], "memory_skill")

    def test_review_persists_context_usage_and_malformed_is_soft(self):
        template = Path(__file__).resolve().parents[2] / "templates" / "5.2.3" / "architecture-review.md"
        shutil.copy2(template, self.task_dir / "architecture-review.md")
        payload = json.dumps([{
            "source_type": "wiki", "asset_id": "wiki:demo/backend/architecture.md",
            "stage": "adopted", "source_followup": "targeted",
            "evidence": ["tool:read:src/backend/service.py"],
        }])
        rc, out, err = self.call(
            "review", "record", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-architecture-review", "--kind", "ARCHITECTURE", "--decision", "REVISE",
            "--summary", "needs revision", "--context-usage-json", payload,
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(self.latest_detail("REVIEW_COMPLETED")["context_usage"][0]["source_type"], "wiki")

        rc, out, err = self.call(
            "review", "record", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--actor", "tp-architecture-review", "--kind", "ARCHITECTURE", "--decision", "REVISE",
            "--summary", "still revise", "--context-usage-json", "{broken",
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("WARN: context telemetry:", err)
        self.assertNotIn("context_usage", self.latest_detail("REVIEW_COMPLETED"))

    def test_delivery_automatically_records_knowledge_usage_and_bad_context_is_soft(self):
        # Seed a stable canonical so the targeted search has a deterministic hit.
        note = self.knowledge_root / "10-projects" / "demo" / "30-features" / "DEMO-FEAT-001-Context.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\nid: DEMO-FEAT-001\ntitle: Context Feature\nproject: demo\nkind: feature\n"
            "status: active\ncanonical: true\nsource_refs: []\nconfidence: 0.9\n"
            "last_verified: '2026-08-15'\nrelations: []\n---\n# Context Feature\nverified delivery behavior reusable rule\n",
            encoding="utf-8",
        )
        rc, out, err = _run(["knowledge", "index", "build", "--workspace-root", str(self.project)])
        self.assertEqual(rc, 0, (out, err))
        ev = self.task_dir / "evidence" / "verify.txt"
        ev.parent.mkdir(exist_ok=True); ev.write_text("ok\n", encoding="utf-8")
        rc, out, err = self.call(
            "task", "verify", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--decision", "PASS", "--summary", "verified", "--evidence", "evidence/verify.txt",
        )
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call(
            "task", "delivery-converge", "--task", self.task_id, "--task-dir", str(self.task_dir),
            "--knowledge-disposition", "NO_CHANGE", "--knowledge-query", "verified delivery behavior reusable rule",
            "--reason", "Targeted project search found no durable delta beyond the existing canonical fact.",
            "--context-usage-json", "{broken",
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("WARN: context telemetry:", err)
        usage = self.latest_detail("DELIVERY_RESULT").get("context_usage") or []
        self.assertTrue(any(x["asset_id"] == "knowledge:DEMO-FEAT-001" for x in usage), usage)


def test_shared_guidance_declares_best_effort_context_telemetry_without_skill_bloat():
    root = Path(__file__).resolve().parents[2]
    managed = (root / "project-entry" / "root-managed-block.md").read_text(encoding="utf-8")
    assert "--context-usage-json" in managed
    assert "不得为了 telemetry 额外搜索" in managed
    assert "source_followup" in managed and "unknown" in managed
    runtime_api = (root / "governance" / "runtime-api.yaml").read_text(encoding="utf-8")
    assert "context_effectiveness" in runtime_api
    assert "WARN+DROP" in runtime_api
