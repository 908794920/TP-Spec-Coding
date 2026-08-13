# -*- coding: utf-8 -*-
"""V5.1.3 personal-mode regression coverage.

The personal edition uses automatic quality gates for normal completion.  It has
no personnel approval state, PFX tooling, approval database extension or
cryptographic receipt request/approve commands.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]

from cli import db as dbmod
from cli import main as climain
from cli.evidence import validate_evidence_path
from cli.event_policies import load_trusted_governance_event
from cli.yaml_checks import check_acceptance_yaml
from test_v511_commit_reliability import run


class TestPersonalModeSurface(unittest.TestCase):
    def test_personnel_approval_implementation_is_absent(self):
        absent = (
            ROOT / "cli" / "approval.py",
            ROOT / "tools" / "human-approve.ps1",
            ROOT / "tools" / "human-approval-setup.ps1",
            ROOT / "db" / "migrations" / "0002_receipt_request.sql",
            ROOT / "db" / "migrations" / "0003_approval_challenge.sql",
        )
        for path in absent:
            self.assertFalse(path.exists(), str(path))

    def test_workflow_is_record_first_and_has_no_personnel_gate(self):
        data = yaml.safe_load((ROOT / "governance" / "workflow.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(data["states"]), {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"})
        self.assertNotIn("HUMAN_APPROVAL", data["states"])
        for level in ("L0", "L1", "L2", "L3"):
            states = [entry["state"] for entry in data["levels"][level]["flow"]]
            self.assertEqual(states, ["NEW", "ACTIVE", "COMPLETED"])
            self.assertFalse(data["levels"][level]["human_required"])

    def test_human_interaction_is_a_blocker_fact_not_a_microstate(self):
        data = yaml.safe_load((ROOT / "governance" / "workflow.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("CHANGE_CONFIRMING", data["states"])
        self.assertIn("BLOCKED", data["states"])

    def test_receipt_request_and_approve_are_not_commands(self):
        rc, _, err = run(["receipt", "request"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized arguments", err)
        rc, _, err = run(["receipt", "approve"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized arguments", err)

    def test_commit_has_no_human_confirmation_flag(self):
        rc, _, err = run(["commit", "--task", "T", "--task-dir", ".", "--actor", "tp-delivery-convergence", "--human-confirmation", "approved"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized arguments", err)

    def test_disabled_task_transition_has_no_legacy_human_flags(self):
        rc, _, err = run([
            "task", "transition", "--task", "T", "--to", "COMPLETED",
            "--summary", "done", "--human-actor", "human_owner",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized arguments", err)

    def test_schema_has_no_receipt_request_table(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        dbmod.init_schema(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("receipt_request", tables)
        conn.close()

    def test_powershell_flush_mirror_allows_verification_rework(self):
        text = (ROOT / "scripts" / "Invoke-TpSpecHandoffFlush.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("VERIFYING = @('DEVELOPING','BROWSER_VERIFYING','REVIEWING','CLOSING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')", text)

    def test_active_powershell_uses_personal_deferred_schema(self):
        text = (ROOT / "scripts" / "Test-TpSpecTask.ps1").read_text(encoding="utf-8")
        self.assertIn("recorded_at", text)
        self.assertNotIn("approved_by", text)
        self.assertNotIn("approved_at", text)
        self.assertNotIn("DEFERRED_APPROVER_INVALID", text)

    def test_role_catalog_completion_chain_has_no_human_gate(self):
        data = yaml.safe_load((ROOT / "agents" / "role-catalog.yaml").read_text(encoding="utf-8"))
        for chain in data["completion_chain"].values():
            self.assertNotIn("human_owner", chain)
            self.assertNotIn("HUMAN_APPROVAL", chain)


class TestNoAcceptanceDeclaration(unittest.TestCase):
    def test_no_acceptance_declaration_needs_reason_not_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "acceptance.md"
            p.write_text(
                "# acceptance\n\n```yaml\nno_acceptance_required:\n  declared: true\n  reason: 纯文档任务，无可执行验收条件\n```\n",
                encoding="utf-8",
            )
            result = check_acceptance_yaml(p.read_text(encoding="utf-8"))
        self.assertTrue(result.no_acceptance_required)
        self.assertTrue(result.ok, result.issues)

    def test_no_acceptance_declaration_without_reason_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "acceptance.md"
            p.write_text("```yaml\nno_acceptance_required:\n  declared: true\n  reason: ''\n```\n", encoding="utf-8")
            result = check_acceptance_yaml(p.read_text(encoding="utf-8"))
        self.assertFalse(result.ok)


class TestGovernanceEvidenceBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.tmp.name)
        (self.task_dir / "evidence").mkdir()
        (self.task_dir / "evidence" / "proof.txt").write_text("proof\n", encoding="utf-8")
        (self.task_dir / "events.jsonl").write_text("{}\n", encoding="utf-8")
        (self.task_dir / "architecture-review.md").write_text("review\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_independent_evidence_file_is_accepted(self):
        result = validate_evidence_path(self.task_dir, "evidence/proof.txt", require_evidence_dir=True)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(64, len(result.sha256))

    def test_projection_and_self_artifact_are_rejected(self):
        for rel in ("events.jsonl", "architecture-review.md"):
            with self.subTest(rel=rel):
                result = validate_evidence_path(self.task_dir, rel, require_evidence_dir=True)
                self.assertFalse(result.ok)

    def test_empty_evidence_is_rejected(self):
        (self.task_dir / "evidence" / "empty.txt").write_bytes(b"")
        result = validate_evidence_path(self.task_dir, "evidence/empty.txt", require_evidence_dir=True)
        self.assertFalse(result.ok)
        self.assertIn("empty", result.error)


class TestTrustedEventSelection(unittest.TestCase):
    def test_newer_invalid_event_does_not_hide_older_valid_event(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE task_event (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, event_type TEXT, actor_role TEXT, summary TEXT, detail_json TEXT)")
        valid = {
            "transaction_id": "TX-VALID", "producer": "review_record", "schema_version": "5.1.3",
            "task_id": "TASK-1", "actor_role": "tp-architecture-review", "created_at": "2026-08-05T00:00:00+08:00",
            "decision": "PASS", "artifact": "architecture-review.md", "artifact_digest": "a" * 64,
            "subject_digest": "b" * 64, "evidence": ["evidence/proof.txt"],
        }
        invalid = dict(valid, transaction_id="TX-BAD", producer="event_add")
        for detail in (valid, invalid):
            conn.execute("INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json) VALUES(?,?,?,?,?)", ("TASK-1", "REVIEW_COMPLETED", "tp-architecture-review", "PASS", json.dumps(detail)))
        trusted = load_trusted_governance_event(conn, "TASK-1", event_type="REVIEW_COMPLETED", actor="tp-architecture-review", decision="PASS", review_kind=None)
        self.assertIsNotNone(trusted)
        self.assertEqual("TX-VALID", trusted.detail["transaction_id"])
        conn.close()


class TestDirectoryManifestHygiene(unittest.TestCase):
    def test_regenerable_caches_are_ignored(self):
        script_path = ROOT / "scripts" / "update_manifest.py"
        spec = importlib.util.spec_from_file_location("update_manifest_personal_test", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            (root / ".pytest_cache").mkdir()
            (root / ".pytest_cache" / "nodeids").write_text("cache", encoding="utf-8")
            (root / "pkg" / "__pycache__").mkdir(parents=True)
            (root / "pkg" / "__pycache__" / "x.pyc").write_bytes(b"cache")
            with mock.patch.object(module, "BASE", root):
                found = module._dir_file_set()
        self.assertEqual({"tracked.txt"}, found)


if __name__ == "__main__":
    unittest.main()
