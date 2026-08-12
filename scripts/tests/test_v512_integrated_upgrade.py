# -*- coding: utf-8 -*-
"""V5.1.3 integrated upgrade regressions.

Covers generic failure modes only. No production/historical task IDs are embedded.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

from cli import db as dbmod  # noqa: E402
from cli import main as climain  # noqa: E402
from cli.digest import compute_verification_subject_digest  # noqa: E402
from cli.version import active_version  # noqa: E402
from test_v511_commit_reliability import build_task, run  # noqa: E402

TASK_ID = "TASK-V512-INTEGRATED"


def _advance_to_verifying(task_dir: str, db_path: str, task_id: str = TASK_ID) -> None:
    rc, out, err = run([
        "task", "checkpoint", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
        "--actor", "tp-development-engineering", "--phase", "development",
        "--summary", "implementation completed",
    ])
    assert rc == 0, (out, err)


def _set_human_pending(task_dir: str, *, ac: str = "AC-01") -> None:
    p = Path(task_dir) / "acceptance.md"
    s = p.read_text(encoding="utf-8")
    s = s.replace(
        "| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |",
        f"| {ac} | 页面功能由后续测试人员确认 | task.md / requirement-test-guide.md | L1 | 页面点击 |  | human | PENDING |",
    )
    s = s.replace("mode: NOT_REQUIRED", "mode: human")
    p.write_text(s, encoding="utf-8", newline="\n")


def _record_technical_pass(task_dir: str, db_path: str, task_id: str = TASK_ID) -> None:
    rc, out, err = run([
        "task", "verify", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
        "--actor", "tp-verification-engineering", "--decision", "PASS",
        "--summary", "technical verification passed", "--evidence", "evidence/test-result.txt",
    ])
    assert rc == 0, (out, err)


class TestVerificationAndOwnerAuthority(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v513-integrated-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_verification_decisions_are_facts_not_route_fields(self):
        for decision in ("NEEDS_FIX", "FAIL"):
            task_id = f"{TASK_ID}-{decision}"
            case_work = self.work / decision.lower()
            case_work.mkdir(parents=True, exist_ok=True)
            task_dir, db_path = build_task(str(case_work), task_id=task_id)
            _advance_to_verifying(task_dir, db_path, task_id)
            rc, out, err = run([
                "task", "verify", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
                "--actor", "tp-verification-engineering", "--decision", decision,
                "--summary", f"{decision} result",
            ])
            self.assertEqual(rc, 0, (out, err))
            conn = dbmod.connect(db_path)
            try:
                task = conn.execute("SELECT current_state,current_stage FROM task WHERE task_id=?", (task_id,)).fetchone()
                ev = conn.execute(
                    "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED' ORDER BY id DESC LIMIT 1",
                    (task_id,),
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(task["current_state"], "ACTIVE")
            self.assertEqual(task["current_stage"], "verification")
            self.assertEqual(json.loads(ev["detail_json"])["decision"], decision)

    def test_technical_pass_allows_human_pending_then_owner_defer_completion(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        _set_human_pending(task_dir)
        _advance_to_verifying(task_dir, db_path)
        before_subject = compute_verification_subject_digest(task_dir)
        _record_technical_pass(task_dir, db_path)

        rc, out, err = run([
            "task", "acceptance-override", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "human_owner", "--mode", "defer", "--scope", "human-pending",
            "--reason", "development is complete; tester will execute later",
            "--residual-risk", "manual page flow is not yet witnessed",
            "--reverify-owner", "tester", "--trigger", "test build delivered",
        ])
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(before_subject, compute_verification_subject_digest(task_dir))
        acc = (Path(task_dir) / "acceptance.md").read_text(encoding="utf-8")
        self.assertIn("DEFERRED_ACCEPTED", acc)
        self.assertIn("reverify_owner: tester", acc)
        self.assertIn("human_witness: pending", acc)

        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--summary", "work complete; manual test deferred",
        ])
        self.assertEqual(rc, 0, (out, err))
        result = json.loads(out)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["verification"], "PASS")

    def test_owner_waive_is_audited_and_not_pass(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        _set_human_pending(task_dir)
        _advance_to_verifying(task_dir, db_path)
        _record_technical_pass(task_dir, db_path)
        rc, out, err = run([
            "task", "acceptance-override", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "human_owner", "--mode", "waive", "--scope", "human-pending",
            "--reason", "owner explicitly skips this manual check",
            "--residual-risk", "manual visual behavior remains unverified",
        ])
        self.assertEqual(rc, 0, (out, err))
        acc = (Path(task_dir) / "acceptance.md").read_text(encoding="utf-8")
        row = next(line for line in acc.splitlines() if line.strip().startswith("| AC-01 "))
        self.assertIn("OWNER_WAIVED", row)
        self.assertNotIn("| PASS |", row)
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--summary", "complete with owner waiver",
        ])
        self.assertEqual(rc, 0, (out, err))

    def test_manual_owner_waiver_without_trusted_event_is_rejected(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        _set_human_pending(task_dir)
        _advance_to_verifying(task_dir, db_path)
        _record_technical_pass(task_dir, db_path)
        p = Path(task_dir) / "acceptance.md"
        s = p.read_text(encoding="utf-8")
        s = s.replace("| human | PENDING |", "| human | OWNER_WAIVED |")
        s = s.replace(
            "owner_waivers: []",
            "owner_waivers:\n- ac: AC-01\n  recorded_at: '2026-08-08T00:00:00+08:00'\n  reason: manual edit\n  residual_risk: unverified\n  actor: human_owner",
        )
        p.write_text(s, encoding="utf-8", newline="\n")
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--summary", "attempt forged waiver completion",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("INTEGRITY_ACCEPTANCE", err + out)

    def test_human_pass_still_requires_confirmed_witness(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        _set_human_pending(task_dir)
        _advance_to_verifying(task_dir, db_path)
        _record_technical_pass(task_dir, db_path)
        p = Path(task_dir) / "acceptance.md"
        s = p.read_text(encoding="utf-8")
        s = s.replace("| 页面点击 |  | human | PENDING |", "| 页面点击 | evidence/test-result.txt | human | PASS |")
        p.write_text(s, encoding="utf-8", newline="\n")
        rc, out, err = run([
            "task", "complete", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "tp-verification-engineering", "--summary", "attempt unconfirmed human PASS",
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("human PASS requires confirmed human witness", err + out)

    def test_human_outcome_does_not_change_technical_subject_but_criteria_does(self):
        task_dir, _ = build_task(str(self.work), task_id=TASK_ID)
        _set_human_pending(task_dir)
        before = compute_verification_subject_digest(task_dir)
        p = Path(task_dir) / "acceptance.md"
        s = p.read_text(encoding="utf-8")
        s = s.replace("| human | PENDING |", "| human | OWNER_WAIVED |")
        s = s.replace("human_witness: pending", "human_witness: confirmed")
        s = s.replace("owner_waivers: []", "owner_waivers:\n- ac: AC-01\n  recorded_at: now\n  reason: owner\n  residual_risk: risk\n  actor: human_owner")
        p.write_text(s, encoding="utf-8", newline="\n")
        self.assertEqual(before, compute_verification_subject_digest(task_dir))
        s = p.read_text(encoding="utf-8").replace("页面功能由后续测试人员确认", "页面功能和导出都必须正确")
        p.write_text(s, encoding="utf-8", newline="\n")
        self.assertNotEqual(before, compute_verification_subject_digest(task_dir))


class TestContractUpgradeAndPlanning(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v512-upgrade-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_project_upgrade_contract_changes_project_only(self):
        root = self.work / "project"
        db_path = root / ".ai-work" / "db" / "p.db"
        db_path.parent.mkdir(parents=True)
        legacy = ".".join(["5", "1", "1"])
        conn = dbmod.connect(str(db_path))
        dbmod.init_schema(conn)
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                "INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("p512", "p512", str(root), legacy, 1, now, now),
            )
            conn.execute(
                "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,base_version,current_state,owner_role,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("TASK-UPGRADE-ONLY", "p512", "x", "L1", "L1", legacy, "NEW", "tp-architecture-design", now, now),
            )
        conn.close()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = climain.main(["project", "upgrade-contract", "--id", "p512", "--db", str(db_path)])
        self.assertEqual(rc, 0, (out.getvalue(), err.getvalue()))
        conn = dbmod.connect(str(db_path))
        try:
            project_base = conn.execute("SELECT base_version FROM project WHERE project_id='p512'").fetchone()["base_version"]
            task_base = conn.execute("SELECT base_version FROM task WHERE task_id='TASK-UPGRADE-ONLY'").fetchone()["base_version"]
            audit = conn.execute("SELECT value_json FROM config WHERE key='contract_upgrade_last' AND scope_id='p512'").fetchone()
        finally:
            conn.close()
        self.assertEqual(project_base, active_version())
        self.assertEqual(task_base, legacy)
        self.assertIsNotNone(audit)

    def test_task_migrate_from_previous_contract_upgrades_artifact_shape(self):
        task_dir, db_path = build_task(str(self.work), task_id=TASK_ID)
        tdir = Path(task_dir)
        legacy = ".".join(["5", "1", "1"])
        for fp in tdir.iterdir():
            if fp.is_file() and fp.suffix.lower() in {".md", ".yaml", ".yml"}:
                text = fp.read_text(encoding="utf-8-sig").replace(active_version(), legacy)
                if fp.name == "codex-review.md":
                    text = text.replace("next_state:", "intended_next:")
                if fp.name == "acceptance.md":
                    text = re.sub(r"\n## Owner 跳过记录\n\n```yaml\nowner_waivers:.*?```\n", "\n", text, flags=re.DOTALL)
                fp.write_text(text, encoding="utf-8", newline="\n")
        conn = dbmod.connect(db_path)
        try:
            conn.execute("UPDATE task SET base_version=? WHERE task_id=?", (legacy, TASK_ID))
            conn.commit()
        finally:
            conn.close()
        rc, out, err = run(["task", "migrate", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path])
        self.assertEqual(rc, 0, (out, err))
        review = (tdir / "codex-review.md").read_text(encoding="utf-8")
        acceptance = (tdir / "acceptance.md").read_text(encoding="utf-8")
        review_fm = review.split("---", 2)[1]
        self.assertIn(f"version: {active_version()}", review_fm)
        self.assertNotIn("intended_next:", review_fm)
        self.assertNotIn("stage_handoff:", review_fm)
        self.assertIn("owner_waivers: []", acceptance)
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

    def test_ultraplan_lite_is_optional_cost_gated_and_non_blocking(self):
        data = yaml.safe_load((BASE / "governance" / "planning-strategy.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["default_mode"], "DIRECT")
        comp = data["modes"]["COMPARATIVE"]
        self.assertEqual(len(comp["fan_out"]["perspectives"]), 3)
        self.assertIn("isolated sequential", comp["execution"]["fallback"])
        self.assertTrue(comp["execution"]["fallback_must_not_block"])
        self.assertTrue(data["constraints"]["no_new_state"])
        self.assertTrue(data["constraints"]["no_new_mandatory_artifact"])
        self.assertTrue(data["constraints"]["fallback_must_not_block"])

    def test_runtime_api_distinguishes_direct_sqlite_edits_from_official_writes(self):
        data = yaml.safe_load((BASE / "governance" / "runtime-api.yaml").read_text(encoding="utf-8"))
        ws = data["rules"]["write_semantics"]
        self.assertEqual(ws["direct_sqlite_edit"], "forbidden")
        self.assertIn("Runtime", ws["canonical_writer"])
        self.assertIn("task checkpoint / task verify / task block / task resume / task complete", ws["audited_write_commands"])
        self.assertIn("project_bootstrap", data["project_api"])
        self.assertIn("project_upgrade_contract", data["project_api"])
        self.assertIn("PROJECT_NOT_INITIALIZED", data["errors"])

    def test_powershell_validator_uses_record_first_integrity_path(self):
        p = BASE / "scripts" / "Test-AiWorkTask.ps1"
        raw = p.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 public validator must be UTF-8 BOM")
        text = raw.decode("utf-8-sig")
        self.assertIn("Record-first fast path", text)
        self.assertIn("task validate", text)
        for state in ("NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"):
            self.assertIn(state, text)
        # Projection refresh is Runtime-owned; the active Record-first path must not require it.
        marker = "Record-first fast path"
        fast = text[text.index(marker):]
        legacy_at = fast.lower().find("# legacy")
        fast = fast[:legacy_at] if legacy_at >= 0 else fast
        self.assertNotIn("ARTIFACT_REFRESH", fast)

    def test_powershell_acceptance_parser_accepts_pyyaml_two_space_children(self):
        # acceptance-override uses yaml.safe_dump(), which emits list child fields
        # with two-space indentation. The PowerShell validator must consume that
        # canonical Runtime output instead of assuming four spaces.
        sample = yaml.safe_dump({
            "deferred_acceptance": [{
                "ac": "AC-01",
                "recorded_at": "2026-08-08T15:00:00+08:00",
                "reason": "tester executes later",
                "residual_risk": "manual path remains unverified",
                "reverify_owner": "human_owner",
                "trigger": "tester returns evidence",
            }]
        }, allow_unicode=True, sort_keys=False)
        self.assertRegex(sample, r"(?m)^  recorded_at:")

        item_pattern = re.compile(
            r'(?m)^[ \t]*-[ \t]+ac:[ \t]*"?(?P<ac>AC-[^"\r\n]+?)"?[ \t]*$'
            r'(?P<fields>(?:\r?\n[ \t]{2,}[a-z_]+:[^\r\n]*)*)'
        )
        field_pattern = re.compile(
            r'(?m)^[ \t]{2,}(?P<key>[a-z_]+):[ \t]*"?(?P<value>[^"\r\n]*?)"?[ \t]*$'
        )
        body = sample.split("deferred_acceptance:\n", 1)[1]
        item = item_pattern.search(body)
        self.assertIsNotNone(item)
        fields = {m.group("key"): m.group("value").strip() for m in field_pattern.finditer(item.group("fields"))}
        for required in ("recorded_at", "residual_risk", "reverify_owner", "trigger"):
            self.assertTrue(fields.get(required), required)

        ps = (BASE / "scripts" / "Test-AiWorkTask.ps1").read_text(encoding="utf-8-sig")
        acceptance_section = ps[ps.index("$deferredRecords = @{}") : ps.index("# 人工页面验收声明") ]
        self.assertNotIn(r"\s{4,}", acceptance_section)
        self.assertGreaterEqual(acceptance_section.count(r"[ \t]{2,}"), 4)

    def test_all_non_ascii_powershell_scripts_are_ps51_safe(self):
        for p in sorted((BASE / "scripts").rglob("*.ps1")):
            raw = p.read_bytes()
            body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
            text = body.decode("utf-8")
            if any(ord(ch) > 127 for ch in text):
                self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), str(p))

    def test_role_facing_runtime_contract_is_current_record_first(self):
        api = BASE / "governance" / "runtime-api.yaml"
        self.assertTrue(api.is_file())
        data = yaml.safe_load(api.read_text(encoding="utf-8"))
        self.assertEqual(str(data.get("version")), active_version())
        self.assertEqual(data.get("mode"), "record-first")
        daily = data.get("daily_api") or {}
        self.assertEqual(
            set(daily),
            {"task_checkpoint", "task_verify", "task_block", "task_resume", "task_complete"},
        )
        forbidden = data.get("do_not_use_in_normal_role_flow") or []
        self.assertIn("commit --refresh", forbidden)
        self.assertIn("hand-authored stage_handoff / intended_next / next_prompt", forbidden)
        legacy = (data.get("optional_capabilities") or {}).get("legacy_commit", "")
        self.assertIn("compatibility/recovery", legacy)
        self.assertIn(f"not the V{active_version()} daily role API", legacy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
