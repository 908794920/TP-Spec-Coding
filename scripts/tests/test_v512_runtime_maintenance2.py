# -*- coding: utf-8 -*-
"""V5.1.3 second maintenance regressions from TASK-20260808-001 timing/process audit.

No contract/version bump. Covers:
- same-owner architecture handoff metadata preservation;
- validator base-root/Junction resolution contract;
- refs-validate self-discoverable schema/example;
- commit payload schema/help and refresh default summary;
- auditable work-session start/end pairing and role contract wiring.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()

from cli import db as dbmod  # noqa: E402
from scripts.tests.test_v511_commit_reliability import build_task, run  # noqa: E402


class TestV512RuntimeMaintenance2(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="v512-maint2-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _task(self, task_id: str):
        return build_task(self.work, task_id=task_id)

    def test_version_remains_512(self):
        self.assertEqual((BASE / "VERSION").read_text(encoding="utf-8").strip(), ACTIVE_VERSION)

    def test_architecture_same_owner_transition_does_not_pollute_stage_handoff(self):
        """V5.1.3 removes stage_handoff from the active task template entirely."""
        text = (BASE / "templates" / ACTIVE_VERSION / "task.md").read_text(encoding="utf-8")
        self.assertNotIn("stage_handoff", text)
        self.assertNotIn("intended_next", text)
    def test_architecture_cross_owner_exit_still_marks_handoff_ready(self):
        task_id = "TASK-MAINT2-HANDOFF-EXIT"
        task_dir, db_path = self._task(task_id)
        rc, out, err = run([
            "commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--to", "DEVELOPING",
            "--summary", "handoff to development",
        ])
        self.assertEqual(rc, 0, (out, err))
        text = (Path(task_dir) / "task.md").read_text(encoding="utf-8")
        self.assertIn('status: "ready"', text)
        self.assertIn('intended_next: "DEVELOPING"', text)

    def test_refresh_without_summary_uses_runtime_deterministic_summary(self):
        task_id = "TASK-MAINT2-REFRESH"
        task_dir, db_path = self._task(task_id)
        rc, out, err = run([
            "commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--refresh",
        ])
        self.assertEqual(rc, 0, (out, err))
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute(
                "SELECT summary,detail_json FROM task_event WHERE task_id=? AND event_type='ARTIFACT_REFRESH' ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["summary"], "refresh generated projections")
        self.assertEqual(json.loads(row["detail_json"])["summary"], "refresh generated projections")

    def test_commit_help_exposes_payload_field_types(self):
        rc, out, err = run(["commit", "--help"])
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("scalar strings: summary, decision, authorization", out)
        self.assertIn("string arrays:  changes, risks, evidence, action, constraint", out)
        self.assertIn("--refresh may omit --summary", out)

    def test_refs_validate_schema_and_example_are_self_discoverable_and_runnable(self):
        rc, out, err = run(["refs-validate", "--schema"])
        self.assertEqual(rc, 0, (out, err))
        contract = json.loads(out)
        self.assertEqual(contract["input"]["kind"], ["file", "command", "symbol", "evidence", "external"])
        self.assertIn("PENDING_LOCAL", contract["input"]["evidence_hash_reason"])
        self.assertIn("relative to that scope directory", contract["path_semantics"]["scope_dirs"])

        rc2, out2, err2 = run(["refs-validate", "--example"])
        self.assertEqual(rc2, 0, (out2, err2))
        example = json.loads(out2)
        refs_path = Path(self.work) / "refs.json"
        refs_path.write_text(json.dumps(example["refs_file_content"], ensure_ascii=False), encoding="utf-8")
        rc3, out3, err3 = run(["refs-validate", "--refs-file", str(refs_path)])
        self.assertEqual(rc3, 0, (out3, err3))
        self.assertEqual(json.loads(out3)["summary"]["passed"], 1)

    def test_work_session_pairs_start_end_and_rejects_ambiguous_events(self):
        task_id = "TASK-MAINT2-WORK"
        _, db_path = self._task(task_id)
        start = ["work", "start", "--task", task_id, "--role", "tp-architecture-design", "--db", db_path]
        end = ["work", "end", "--task", task_id, "--role", "tp-architecture-design", "--reason", "completed", "--db", db_path]

        rc1, out1, err1 = run(start)
        self.assertEqual(rc1, 0, (out1, err1))
        rc_dup, _, err_dup = run(start)
        self.assertEqual(rc_dup, 5)
        self.assertIn("open work session already exists", err_dup)
        rc2, out2, err2 = run(end)
        self.assertEqual(rc2, 0, (out2, err2))
        rc_orphan, _, err_orphan = run(end)
        self.assertEqual(rc_orphan, 5)
        self.assertIn("no open work session", err_orphan)

        conn = dbmod.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id,event_type,detail_json FROM task_event WHERE task_id=? AND event_type IN ('WORK_SESSION_STARTED','WORK_SESSION_ENDED') ORDER BY id",
                (task_id,),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 2)
        start_detail = json.loads(rows[0]["detail_json"])
        end_detail = json.loads(rows[1]["detail_json"])
        self.assertTrue(start_detail["session_id"].startswith("WORK-"))
        self.assertEqual(end_detail["session_id"], start_detail["session_id"])
        self.assertEqual(end_detail["start_event_id"], rows[0]["id"])

    def test_work_start_role_and_agent_can_fall_back_to_task_owner(self):
        task_id = "TASK-MAINT2-WORK-DEFAULT"
        _, db_path = self._task(task_id)
        rc, out, err = run(["work", "start", "--task", task_id, "--db", db_path])
        self.assertEqual(rc, 0, (out, err))
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute(
                "SELECT actor_role FROM task_event WHERE task_id=? AND event_type='WORK_SESSION_STARTED' ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["actor_role"], "tp-architecture-design")

    def test_validator_resolves_base_root_without_cli_junction_contract(self):
        text = (BASE / "scripts" / "Test-TpSpecTask.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Resolve-TpSpecBaseRoot", text)
        self.assertIn("TP_SPEC_BASE_ROOT", text)
        self.assertIn("$scriptItem.Target", text)
        self.assertIn("$script:BaseRoot", text)
        self.assertNotIn("$mirrorBase = Split-Path -Parent $PSScriptRoot   # tp-spec-base", text)

    def test_runtime_contract_and_roles_wire_timing_without_pretask_fabrication(self):
        runtime = yaml.safe_load((BASE / "governance" / "runtime-api.yaml").read_text(encoding="utf-8"))
        self.assertEqual(runtime["version"], ACTIVE_VERSION)
        self.assertIn("session_id", runtime["rules"]["execution_timing"]["pairing_rule"])
        self.assertIn("No TaskId", runtime["rules"]["execution_timing"]["pretask_rule"])
        self.assertEqual(runtime["optional_capabilities"]["work_sessions"].split(";")[0], "available for timing evidence")
        # Role prompts must not force manual start/end bookkeeping in the normal path.
        catalog = yaml.safe_load((BASE / "agents" / "role-catalog.yaml").read_text(encoding="utf-8"))
        by_role = {entry["workflow_role"]: entry for entry in catalog["roles"]}
        for role in (
            "tp-architecture-design", "tp-architecture-review", "tp-development-engineering",
            "tp-product-design", "tp-verification-engineering", "tp-delivery-convergence",
        ):
            text = (BASE / by_role[role]["skill_path"]).read_text(encoding="utf-8")
            self.assertNotIn("tp-spec work start", text, role)
            self.assertNotIn("tp-spec work end", text, role)
