# -*- coding: utf-8 -*-
"""V5.1.3 real-task repair regression tests.

These tests lock in fixes found during real L2/L3 task pressure testing:
- VERIFYING entry uses working semantics (verification outputs are not prerequisites);
- in-flight task contract migration is official, atomic/recoverable and idempotent;
- commit --dry-run is read-only and aggregates blockers;
- review artifact digests ignore only BOM/newline transport differences;
- task create --scaffold creates DB task and task artifacts in one command.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()

from cli import db as dbmod  # noqa: E402
from cli import validator  # noqa: E402
from cli.digest import (  # noqa: E402
    compute_text_artifact_digest,
    compute_architecture_subject_digest,
    compute_verification_subject_digest,
)
from cli.version import active_version  # noqa: E402
from test_v511_commit_reliability import PROJECT_ID as FIXTURE_PROJECT_ID, build_task, run  # noqa: E402


TASK_ID = "TASK-REAL-REPAIR"
PROJECT_ID = "p-real-repair"


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestRealTaskRepair(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v511-real-repair-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_verifying_working_mode_does_not_require_verification_outputs(self):
        task_dir, _ = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)

        # Give the AC a real condition but deliberately keep verdict/human witness pending
        # and codex-review unfilled. These are outputs of VERIFYING, not entry inputs.
        acceptance = tdir / "acceptance.md"
        text = acceptance.read_text(encoding="utf-8")
        text = text.replace("| AC-01 |  |", "| AC-01 | 功能结果符合需求 |")
        acceptance.write_text(text, encoding="utf-8", newline="\n")
        result = validator.validate_artifacts(
            tdir,
            ["acceptance", "codex-review"],
            mode="working",
            state="VERIFYING",
        )
        self.assertTrue(result["ok"], result)

        strict = validator.validate_artifacts(
            tdir,
            ["acceptance", "codex-review"],
            mode="closing",
            state="CLOSING",
        )
        self.assertFalse(strict["ok"])
        codes = {i["code"] for i in strict["issues"]}
        self.assertTrue(codes, strict)

    def test_review_digest_normalizes_bom_and_newline_only(self):
        lf = "---\ndecision: PASS\n---\n正文\n"
        crlf = lf.replace("\n", "\r\n")
        bom_crlf = "\ufeff" + crlf
        self.assertEqual(compute_text_artifact_digest(lf), compute_text_artifact_digest(crlf))
        self.assertEqual(compute_text_artifact_digest(lf), compute_text_artifact_digest(bom_crlf))
        # Semantic content remains protected.
        self.assertNotEqual(compute_text_artifact_digest(lf), compute_text_artifact_digest(lf.replace("正文", "正文已修改")))

    def test_commit_dry_run_is_zero_write_and_returns_all_detectable_blockers(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)
        # Force at least two independent blockers: required main artifact missing and
        # development details not prepared for the receiving role.
        (tdir / "task.md").unlink()
        before_status = file_hash(tdir / "status.yaml")
        before_events = file_hash(tdir / "events.jsonl")
        conn = dbmod.connect(db_path)
        try:
            before_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
            before_state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (TASK_ID,)).fetchone()["current_state"]
        finally:
            conn.close()

        rc, out, err = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--to", "DEVELOPING", "--phase-exit", "--dry-run",
        ])
        self.assertEqual(rc, 7, (out, err))
        report = json.loads(out)
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(len(report["issues"]), 2, report)

        conn = dbmod.connect(db_path)
        try:
            after_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
            after_state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (TASK_ID,)).fetchone()["current_state"]
        finally:
            conn.close()
        self.assertEqual((after_state, after_count), (before_state, before_count))
        self.assertEqual(file_hash(tdir / "status.yaml"), before_status)
        self.assertEqual(file_hash(tdir / "events.jsonl"), before_events)

    def test_task_migrate_repairs_db_file_contract_mismatch_and_is_idempotent(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)

        # Reproduce the real upgrade failure: file projections/artifacts and DB can
        # disagree. Here we make the active task look like an older-contract in-flight task;
        # project itself remains on the active base so task-scoped migration is valid.
        legacy = ".".join(["5", "1", "0"])
        for fp in tdir.iterdir():
            if fp.is_file() and fp.suffix.lower() in {".md", ".yaml", ".yml"}:
                text = fp.read_text(encoding="utf-8-sig")
                text = text.replace(f'version: "{active_version()}"', f'version: "{legacy}"')
                text = text.replace(f"version: {active_version()}", f"version: {legacy}")
                if fp.name == "status.yaml":
                    text = text.replace(f'base_version: "{active_version()}"', f'base_version: "{legacy}"')
                    text = text.replace(f"base_version: {active_version()}", f"base_version: {legacy}")
                fp.write_text(text, encoding="utf-8", newline="\n")
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET base_version=? WHERE task_id=?", (legacy, TASK_ID))
            conn.commit()
            before_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()

        rc, out, err = run(["task", "migrate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc, 0, (out, err))
        self.assertIn(f"{legacy} -> {active_version()}", out)

        conn = dbmod.connect(db_path)
        try:
            task = conn.execute("SELECT base_version FROM task WHERE task_id=?", (TASK_ID,)).fetchone()
            after_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
            ev = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='RECONCILIATION' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(task["base_version"], active_version())
        self.assertEqual(after_count, before_count + 1)
        self.assertIsNotNone(ev)
        detail = json.loads(ev["detail_json"])
        self.assertEqual(detail["kind"], "CONTRACT_MIGRATION")
        self.assertEqual(detail["producer"], "task_migrate")
        status = (tdir / "status.yaml").read_text(encoding="utf-8")
        self.assertIn(f'base_version: "{ACTIVE_VERSION}"', status)
        self.assertRegex(status, rf'artifact_contract:\s*\n\s+version:\s*["\']?{re.escape(active_version())}')

        # Second run is a true no-op: no duplicate migration audit event.
        rc2, out2, err2 = run(["task", "migrate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc2, 0, (out2, err2))
        self.assertIn("already current", out2)
        conn = dbmod.connect(db_path)
        try:
            final_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(final_count, after_count)

    def test_task_create_scaffold_creates_runtime_ready_directory(self):
        project_root = self.work / "proj-scaffold"
        db_path = project_root / ".ai-work" / "db" / "ai-work.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = dbmod.connect(str(db_path))
        dbmod.init_schema(conn)
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                "INSERT INTO project (project_id, project_name, root_path, base_version, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (PROJECT_ID, PROJECT_ID, str(project_root), active_version(), now, now),
            )
        conn.close()

        task_dir = project_root / ".ai-work" / "tasks" / TASK_ID
        rc, out, err = run([
            "task", "create", "--id", TASK_ID, "--project", PROJECT_ID,
            "--title", "真实任务脚手架", "--risk", "L2", "--flow", "L2",
            "--db", str(db_path), "--scaffold", "--task-dir", str(task_dir),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertTrue(task_dir.is_dir())
        self.assertFalse((task_dir / "README.md").exists())
        self.assertTrue((task_dir / "generated").is_dir())
        self.assertTrue((task_dir / "generated" / "continuation.md").is_file())
        self.assertTrue((task_dir / "evidence").is_dir())
        self.assertTrue((task_dir / "evidence" / "sql").is_dir())
        self.assertTrue((task_dir / "status.yaml").is_file())
        self.assertTrue((task_dir / "events.jsonl").is_file())
        status = (task_dir / "status.yaml").read_text(encoding="utf-8")
        self.assertIn(TASK_ID, status)
        self.assertIn("真实任务脚手架", status)
        conn = dbmod.connect(str(db_path))
        try:
            row = conn.execute("SELECT current_state, base_version FROM task WHERE task_id=?", (TASK_ID,)).fetchone()
            count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(row["current_state"], "NEW")
        self.assertEqual(row["base_version"], active_version())
        self.assertEqual(count, 1)

        # A freshly scaffolded task is already four-way consistent; upgrade scans must
        # not classify its intentionally new state as projection drift.
        prc, pout, perr = run([
            "task", "migration-plan", "--project", PROJECT_ID,
            "--tasks-root", str(task_dir.parent), "--db", str(db_path), "--gate",
        ])
        self.assertEqual(prc, 0, (pout, perr))
        plan = json.loads(pout)
        self.assertEqual(plan["release_gate"], "PASS")
        self.assertEqual(plan["tasks"][0]["classification"], "CURRENT")

    def test_runtime_records_phase_without_rewriting_optional_test_guide(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)
        guide = tdir / "requirement-test-guide.md"
        before = guide.read_bytes()
        rc, out, err = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--phase", "architecture", "--summary", "design complete",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(before, guide.read_bytes(), "Runtime must not rewrite optional business prose for phase bookkeeping")
        rc2, out2, err2 = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development", "--summary", "implementation active",
        ])
        self.assertEqual(rc2, 0, (out2, err2))
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute("SELECT current_state,current_stage,owner_role FROM task WHERE task_id=?", (TASK_ID,)).fetchone()
        finally:
            conn.close()
        self.assertEqual((row["current_state"], row["current_stage"], row["owner_role"]),
                         ("ACTIVE", "development", "tp-development-engineering"))

    def test_l2_does_not_require_fabricated_decision(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET risk_level='L2', flow_level='L2' WHERE task_id=?", (TASK_ID,))
            conn.commit()
        finally:
            conn.close()
        # Make requirement retrieval complete; leave requirement-decisions.md as its empty
        # scaffold. Architecture review is intentionally absent, so dry-run must still fail
        # for the real missing gate, not for an invented decision quota.
        kp = tdir / "requirement-knowledge.md"
        kt = kp.read_text(encoding="utf-8")
        kt = kt.replace("complete: false", "complete: true").replace("search_rounds: 0", "search_rounds: 1").replace("evidence_items: 0", "evidence_items: 1")
        kp.write_text(kt, encoding="utf-8", newline="\n")
        rc, out, err = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--phase-exit", "--dry-run",
        ])
        self.assertEqual(rc, 7, (out, err))
        report = json.loads(out)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("ARCHITECTURE_REVIEW_REQUIRED", codes)
        self.assertFalse(any(code.startswith("DECISIONS_") for code in codes), report)

    def test_unrelated_future_artifact_does_not_block_current_handoff(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        # A future closing artifact can be a broken draft without blocking architecture -> dev.
        (Path(task_dir) / "quality-and-knowledge.md").write_text("---\nbroken: [\n---\n", encoding="utf-8")
        rc, out, err = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "to dev",
        ])
        self.assertEqual(rc, 0, (out, err))

    def test_migration_plan_reports_four_way_mismatch_read_only(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        legacy = ".".join(["5", "1", "0"])
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET base_version=? WHERE task_id=?", (legacy, TASK_ID))
            conn.commit()
            before_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        status_before = file_hash(Path(task_dir) / "status.yaml")
        tasks_root = str(Path(task_dir).parent)
        rc, out, err = run([
            "task", "migration-plan", "--project", FIXTURE_PROJECT_ID, "--tasks-root", tasks_root,
            "--db", db_path, "--gate",
        ])
        self.assertEqual(rc, 8, (out, err))
        report = json.loads(out)
        self.assertEqual(report["release_gate"], "BLOCKED")
        item = next(i for i in report["tasks"] if i["task_id"] == TASK_ID)
        self.assertEqual(item["classification"], "CONTRACT_MISMATCH")
        self.assertIn("MIGRATE_TO_ACTIVE", item["decision_options"])
        self.assertEqual(item["four_way"]["sqlite_task_base_version"], legacy)
        conn = dbmod.connect(db_path)
        try:
            after_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(after_count, before_count)
        self.assertEqual(file_hash(Path(task_dir) / "status.yaml"), status_before)


    def _advance_to_verifying(self, task_dir: str, db_path: str, task_id: str = TASK_ID):
        rc, out, err = run([
            "commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "to dev",
        ])
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = run([
            "commit", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--to", "VERIFYING", "--summary", "to verify",
        ])
        self.assertEqual(rc, 0, (out, err))

    def test_review_only_dry_run_is_supported_and_zero_write(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        self._advance_to_verifying(task_dir, db_path)
        tdir = Path(task_dir)
        before = {
            "status": file_hash(tdir / "status.yaml"),
            "events": file_hash(tdir / "events.jsonl"),
            "review": file_hash(tdir / "codex-review.md"),
        }
        conn = dbmod.connect(db_path)
        try:
            before_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        rc, out, err = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--review-only", "--decision", "PASS",
            "--evidence", "evidence/test-result.txt", "--dry-run",
        ])
        self.assertEqual(rc, 7, (out, err))
        report = json.loads(out)
        self.assertEqual(report["command"], "commit --review-only --dry-run")
        self.assertNotIn("DRY_RUN_UNSUPPORTED_MODE", {i["code"] for i in report["issues"]})
        self.assertGreaterEqual(len(report["issues"]), 2, report)
        conn = dbmod.connect(db_path)
        try:
            after_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(after_count, before_count)
        self.assertEqual(file_hash(tdir / "status.yaml"), before["status"])
        self.assertEqual(file_hash(tdir / "events.jsonl"), before["events"])
        self.assertEqual(file_hash(tdir / "codex-review.md"), before["review"])

    def test_verification_needs_fix_is_fact_and_rework_stays_active(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development", "--summary", "implementation ready",
        ])
        rc, out, err = run([
            "task", "verify", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--decision", "NEEDS_FIX",
            "--summary", "scoped implementation defects need local rework",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(json.loads(out)["decision"], "NEEDS_FIX")
        rc2, out2, err2 = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development", "--summary", "local rework",
        ])
        self.assertEqual(rc2, 0, (out2, err2))
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute("SELECT current_state,current_stage FROM task WHERE task_id=?", (TASK_ID,)).fetchone()
        finally:
            conn.close()
        self.assertEqual((row["current_state"], row["current_stage"]), ("ACTIVE", "development"))

    def test_verification_fail_is_recorded_and_development_can_resume_without_state_rollback(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development", "--summary", "implementation ready",
        ])
        rc, out, err = run([
            "task", "verify", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--decision", "FAIL",
            "--summary", "substantial implementation defects",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(json.loads(out)["decision"], "FAIL")
        rc2, out2, err2 = run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development", "--summary", "return to implementation",
        ])
        self.assertEqual(rc2, 0, (out2, err2))

    def test_verification_cannot_return_to_developing_without_failed_review(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        self._advance_to_verifying(task_dir, db_path)
        rc, out, err = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--to", "DEVELOPING",
            "--summary", "invalid naked return",
        ])
        self.assertNotEqual(rc, 0, (out, err))
        self.assertIn("VERIFICATION_REWORK_REVIEW_REQUIRED", err)

    def test_migration_plan_detects_same_count_event_tamper_and_migrate_repairs_current(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        rc0, out0, err0 = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "canonicalize projections",
        ])
        self.assertEqual(rc0, 0, (out0, err0))
        ep = Path(task_dir) / "events.jsonl"
        lines = ep.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["note"] = "tampered-but-same-line-count"
        lines[0] = json.dumps(first, ensure_ascii=False)
        ep.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

        rc, out, err = run([
            "task", "migration-plan", "--project", FIXTURE_PROJECT_ID,
            "--tasks-root", str(Path(task_dir).parent), "--db", db_path, "--gate",
        ])
        self.assertEqual(rc, 8, (out, err))
        plan = json.loads(out)
        item = next(i for i in plan["tasks"] if i["task_id"] == TASK_ID)
        self.assertEqual(item["four_way"]["event_ledger"], "drift")
        self.assertTrue(any("canonical DB projection" in x for x in item["issues"]), item)

        conn = dbmod.connect(db_path)
        try:
            before_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
        finally:
            conn.close()
        rc2, out2, err2 = run([
            "task", "migrate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
        ])
        self.assertEqual(rc2, 0, (out2, err2))
        self.assertIn("CURRENT_CONTRACT_REPAIR", out2)
        conn = dbmod.connect(db_path)
        try:
            after_count = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id=?", (TASK_ID,)).fetchone()["c"]
            detail = json.loads(conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='RECONCILIATION' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()["detail_json"])
        finally:
            conn.close()
        self.assertEqual(after_count, before_count + 2)
        self.assertEqual(detail["kind"], "CURRENT_CONTRACT_REPAIR")
        rc3, out3, err3 = run([
            "task", "migration-plan", "--project", FIXTURE_PROJECT_ID,
            "--tasks-root", str(Path(task_dir).parent), "--db", db_path, "--gate",
        ])
        self.assertEqual(rc3, 0, (out3, err3))
        self.assertEqual(json.loads(out3)["tasks"][0]["classification"], "CURRENT")

    def test_migration_records_non_retroactive_grandfather_policy(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        rc0, out0, err0 = run([
            "commit", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-architecture-design", "--to", "DEVELOPING", "--summary", "historically entered development",
        ])
        self.assertEqual(rc0, 0, (out0, err0))
        legacy = ".".join(["5", "1", "0"])
        tdir = Path(task_dir)
        for fp in tdir.iterdir():
            if fp.is_file() and fp.suffix.lower() in {".md", ".yaml", ".yml"}:
                text = fp.read_text(encoding="utf-8-sig")
                text = text.replace(f'version: "{active_version()}"', f'version: "{legacy}"')
                text = text.replace(f"version: {active_version()}", f"version: {legacy}")
                if fp.name == "status.yaml":
                    text = text.replace(f'base_version: "{active_version()}"', f'base_version: "{legacy}"')
                fp.write_text(text, encoding="utf-8", newline="\n")
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET base_version=? WHERE task_id=?", (legacy, TASK_ID))
            conn.commit()
        finally:
            conn.close()
        rc, out, err = run(["task", "migrate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc, 0, (out, err))
        conn = dbmod.connect(db_path)
        try:
            detail = json.loads(conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='RECONCILIATION' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()["detail_json"])
        finally:
            conn.close()
        self.assertEqual(detail["migration_policy"], "non_retroactive")
        self.assertTrue(detail["future_transitions_use_target_contract"])
        self.assertIn("pre_DEVELOPING_gates", detail["grandfathered_gates"])

    def test_task_retire_removes_historical_instance_from_active_gate_without_faking_completion(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        conn = dbmod.connect(db_path)
        try:
            before_state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (TASK_ID,)).fetchone()["current_state"]
        finally:
            conn.close()
        rc, out, err = run([
            "task", "retire", "--task", TASK_ID, "--reason", "historical instance no longer active", "--db", db_path,
        ])
        self.assertEqual(rc, 0, (out, err))
        conn = dbmod.connect(db_path)
        try:
            after_state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (TASK_ID,)).fetchone()["current_state"]
            ev = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='TASK_RETIRED' ORDER BY id DESC LIMIT 1",
                (TASK_ID,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(after_state, before_state)
        self.assertIsNotNone(ev)
        rc2, out2, err2 = run([
            "task", "migration-plan", "--project", FIXTURE_PROJECT_ID,
            "--tasks-root", str(Path(task_dir).parent), "--db", db_path, "--gate",
        ])
        self.assertEqual(rc2, 0, (out2, err2))
        plan = json.loads(out2)
        self.assertIn(TASK_ID, plan["retired_historical_tasks"])
        self.assertEqual(plan["active_non_terminal_tasks"], 0)
        self.assertEqual(plan["release_gate"], "PASS")
        rcv, outv, errv = run(["task", "validate", "--task", TASK_ID, "--db", db_path])
        self.assertEqual(rcv, 0, (outv, errv))
        self.assertIn("retired historical archive", outv)
        rcl, outl, errl = run(["task", "list", "--active", "--db", db_path])
        self.assertEqual(rcl, 0, (outl, errl))
        self.assertIn("(no tasks)", outl)

    def test_closing_validator_rejects_high_confidence_mojibake(self):
        task_dir, _ = build_task(str(self.work), task_id=TASK_ID)
        p = Path(task_dir) / "acceptance.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n乱码样本: Ã¤Â¸Â­Ã¦ÂÂ\n", encoding="utf-8", newline="\n")
        result = validator.validate_artifacts(
            task_dir, ["acceptance"], mode="closing", state="CLOSING",
        )
        codes = {i["code"] for i in result["issues"]}
        self.assertIn("TEXT_INTEGRITY_INVALID", codes, result)


    def _prepare_verification_pass_subject(self, task_dir: str):
        tdir = Path(task_dir)
        acc = tdir / "acceptance.md"
        text = acc.read_text(encoding="utf-8")
        text = text.replace(
            "| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |",
            "| AC-01 | 完成目标功能并验证 | task.md / requirement-test-guide.md | L1 | 验证 | evidence/test-result.txt | verification | PASS |",
        )
        acc.write_text(text, encoding="utf-8", newline="\n")
        review = tdir / "codex-review.md"
        review.write_text(
            "---\nreview:\n  actor: tp-verification-engineering\n  decision: PENDING\n"
            "  evidence: \"\"\n  timestamp: \"\"\n  intended_next: \"\"\n---\n\n"
            "## 结论\n已独立复核需求、实现、验收矩阵与测试指南，实际执行主流程、异常路径和边界检查；当前实现与任务范围一致，未发现阻断交付的问题。该结论只覆盖本次任务声明的范围与当前证据，后续业务正文或测试证据发生实质变化时必须重新验收。\n\n"
            "## 证据\n`evidence/test-result.txt` 为本次真实测试输出，包含可复算的验证结果；验收矩阵 AC-01 已显式绑定该证据。审查没有把 status/events/handoff 或本 review 文件本身作为自证证据。\n\n"
            "## 残余风险\n当前无已知阻塞残余风险；未覆盖的外部环境事实仍以任务中明确声明的验证边界为准，不把未执行事项伪造成 PASS。\n",
            encoding="utf-8", newline="\n",
        )

    def test_subject_digest_ignores_transport_but_protects_test_guide_business_content(self):
        task_dir, _ = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)
        arch0 = compute_architecture_subject_digest(tdir)
        ver0 = compute_verification_subject_digest(tdir)
        guide = tdir / "requirement-test-guide.md"
        text = guide.read_text(encoding="utf-8")
        # Transport-only BOM/CRLF rewrite is normalized.
        guide.write_bytes(("\ufeff" + text.replace("\n", "\r\n")).encode("utf-8"))
        self.assertEqual(arch0, compute_architecture_subject_digest(tdir))
        self.assertEqual(ver0, compute_verification_subject_digest(tdir))
        # Tester-facing business content remains protected.
        with open(guide, "r", encoding="utf-8-sig", newline=None) as handle:
            changed = handle.read().replace("## 关键场景", "## 关键场景\n\n- 新增一个必须验证的业务边界")
        guide.write_text(changed, encoding="utf-8", newline="\n")
        self.assertNotEqual(arch0, compute_architecture_subject_digest(tdir))
        self.assertNotEqual(ver0, compute_verification_subject_digest(tdir))

    def test_one_verification_pass_survives_runtime_completion_without_bookkeeping_rewrite(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)
        guide = tdir / "requirement-test-guide.md"
        guide_before = guide.read_bytes()
        run([
            "task", "checkpoint", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-development-engineering", "--phase", "development", "--summary", "implementation done",
        ])
        rc1, out1, err1 = run([
            "task", "verify", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--decision", "PASS",
            "--summary", "verification pass", "--evidence", "evidence/test-result.txt",
        ])
        self.assertEqual(rc1, 0, (out1, err1))
        rc2, out2, err2 = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--summary", "done",
        ])
        self.assertEqual(rc2, 0, (out2, err2))
        self.assertEqual(json.loads(out2)["verification"], "PASS")
        self.assertEqual(guide_before, guide.read_bytes())
        conn = dbmod.connect(db_path)
        try:
            pass_count = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED'",
                (TASK_ID,),
            ).fetchone()["c"]
            state = conn.execute("SELECT current_state FROM task WHERE task_id=?", (TASK_ID,)).fetchone()["current_state"]
        finally:
            conn.close()
        self.assertEqual(pass_count, 1)
        self.assertEqual(state, "COMPLETED")

    def test_closing_validator_rejects_literal_powershell_newline_leak(self):
        task_dir, _ = build_task(str(self.work), task_id=TASK_ID)
        p = Path(task_dir) / "acceptance.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n污染`r`n文本`r`n仍在正文\n", encoding="utf-8", newline="\n")
        result = validator.validate_artifacts(task_dir, ["acceptance"], mode="closing", state="CLOSING")
        self.assertIn("TEXT_INTEGRITY_INVALID", {i["code"] for i in result["issues"]}, result)

    def test_artifact_path_resolves_verification_sql_and_rejects_traversal(self):
        task_dir = self.work / "task-path"
        task_dir.mkdir()
        rc, out, err = run([
            "task", "artifact-path", "--task-dir", str(task_dir), "--kind", "verification-sql",
            "--name", "check.sql", "--ensure",
        ])
        self.assertEqual(rc, 0, (out, err))
        expected = task_dir / "evidence" / "sql" / "check.sql"
        self.assertEqual(Path(out.strip()), expected.resolve())
        self.assertTrue(expected.parent.is_dir())
        rc2, out2, err2 = run([
            "task", "artifact-path", "--task-dir", str(task_dir), "--kind", "verification-sql",
            "--name", "../escape.sql",
        ])
        self.assertEqual(rc2, 2, (out2, err2))
        self.assertIn("plain file name", err2)


if __name__ == "__main__":
    unittest.main()
