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

from cli import db as dbmod
from scripts.tests.runtime_testutil import run


def _git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return cp.stdout.strip()


class VisualCase:
    def __init__(self, level: str = "L0"):
        self.root = Path(tempfile.mkdtemp(prefix="v529-visual-"))
        self.project = self.root / "project"
        self.user_root = self.root / "user"
        self.temp_root = self.root / "temp"
        self.env = patch.dict(
            os.environ,
            {"TP_SPEC_USER_ROOT": str(self.user_root), "TP_SPEC_TEMP_ROOT": str(self.temp_root)},
            clear=False,
        )
        self.env.start()
        self.registry = self.root / "registry.json"
        self.registry.write_text('{"projects": []}\n', encoding="utf-8")
        rc, out, err = run([
            "project", "bootstrap", "--id", "demo", "--root", str(self.project), "--registry", str(self.registry),
        ])
        assert rc == 0, (out, err)
        self.db = self.project / ".tp-spec" / "db" / "demo.db"
        _git(self.project, "init", "-q")
        _git(self.project, "config", "user.name", "test")
        _git(self.project, "config", "user.email", "test@example.com")
        (self.project / "src").mkdir()
        (self.project / "src" / "app.txt").write_text("v1\n", encoding="utf-8")
        _git(self.project, "add", "src/app.txt")
        _git(self.project, "commit", "-qm", "baseline")
        self.level = level

    def close(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def call(self, *args):
        return run(list(args) + ["--db", str(self.db)])

    def create_task(self, task_id: str, *, visual: bool = True) -> Path:
        td = self.project / ".tp-spec" / "tasks" / task_id
        rc, out, err = self.call(
            "task", "create", "--id", task_id, "--project", "demo",
            "--risk", self.level, "--flow", self.level, "--scaffold", "--task-dir", str(td),
        )
        assert rc == 0, (out, err)
        if visual:
            self.write_visual_acceptance(td)
        return td

    @staticmethod
    def write_visual_acceptance(task_dir: Path) -> None:
        (task_dir / "acceptance.md").write_text(
            "# 验收条件与证据矩阵\n\n"
            "| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| AC-UI-01 | 375px 页面结构和交互符合原型 | task.md | L1 | 真实浏览器 | evidence/visual/manifest.json | verification | PASS |\n\n"
            "```yaml\n"
            "page_verification:\n"
            "  mode: verification\n"
            "  human_witness: pending\n"
            "  witness_evidence: \"\"\n"
            "  visual:\n"
            "    required: true\n"
            "    viewports: [\"375x812\"]\n"
            "    routes: [\"/application/create\"]\n"
            "    reference_assets: [\"evidence/visual/reference/UI-01.png\"]\n"
            "    required_states: [normal]\n"
            "    evidence_manifest: \"evidence/visual/manifest.json\"\n"
            "deferred_acceptance: []\n"
            "owner_waivers: []\n"
            "database_operations: []\n"
            "```\n",
            encoding="utf-8", newline="\n",
        )

    def checkpoint(self, task_id: str, td: Path, actor: str, phase: str, *, repo: bool = False) -> dict:
        args = [
            "task", "checkpoint", "--task", task_id, "--task-dir", str(td),
            "--actor", actor, "--phase", phase, "--summary", f"{phase} done",
        ]
        if repo:
            args += ["--repo-root", str(self.project)]
        rc, out, err = self.call(*args)
        assert rc == 0, (out, err)
        return json.loads(out)

    def prepare_development(self, task_id: str, td: Path) -> dict:
        if self.level in {"L2", "L3"}:
            self.checkpoint(task_id, td, "tp-product-manager", "requirement")
            self.checkpoint(task_id, td, "tp-software-architect", "architecture")
            self.checkpoint(task_id, td, "tp-tech-lead", "planning")
            rc, out, err = self.call("workflow", "confirm", "--task", task_id, "--task-dir", str(td), "--json")
            assert rc == 0, (out, err)
        return self.checkpoint(task_id, td, "tp-development-engineer", "development", repo=True)

    def write_manifest(
        self,
        td: Path,
        change_set_id: str,
        *,
        bad_change_set: bool = False,
        escape_actual: bool = False,
        omit_route: bool = False,
        temporary_bypass: bool = False,
    ) -> Path:
        visual = td / "evidence" / "visual"
        (visual / "reference").mkdir(parents=True, exist_ok=True)
        (visual / "actual").mkdir(parents=True, exist_ok=True)
        (visual / "diff").mkdir(parents=True, exist_ok=True)
        (visual / "reference" / "UI-01.png").write_bytes(b"reference")
        (visual / "actual" / "UI-01.png").write_bytes(b"actual")
        (visual / "diff" / "UI-01.png").write_bytes(b"diff")
        (visual / "UI-01.md").write_text("visual review passed\n", encoding="utf-8", newline="\n")
        cleanup = visual / "auth-cleanup.md"
        if temporary_bypass:
            cleanup.write_text("temporary auth patch removed\n", encoding="utf-8", newline="\n")
        case = {
            "id": "UI-01",
            "acceptance_refs": ["AC-UI-01"],
            "viewport": {"width": 375, "height": 812},
            "state": "normal",
            "reference": "evidence/visual/reference/UI-01.png",
            "actual": "../outside.png" if escape_actual else "evidence/visual/actual/UI-01.png",
            "diff": "evidence/visual/diff/UI-01.png",
            "report": "evidence/visual/UI-01.md",
            "horizontal_overflow": False,
            "console_errors": 0,
            "failed_requests": [],
        }
        if not omit_route:
            case["route"] = "/application/create"
        data = {
            "schema": "tp-spec.visual-verification/v1",
            "change_set_id": "sha256:wrong" if bad_change_set else change_set_id,
            "executed_at": "2026-08-29T15:00:00+08:00",
            "browser": "chromium",
            "auth": {
                "strategy": "temporary_patch" if temporary_bypass else "storage_state",
                "temporary_bypass_used": temporary_bypass,
                "cleanup_evidence": "evidence/visual/auth-cleanup.md" if temporary_bypass else "",
            },
            "cases": [case],
        }
        manifest = visual / "manifest.json"
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return manifest

    def verify(self, task_id: str, td: Path, *evidence: str):
        args = [
            "task", "verify", "--task", task_id, "--task-dir", str(td),
            "--actor", "tp-test-engineer", "--decision", "PASS", "--summary", "verified",
        ]
        for item in evidence:
            args += ["--evidence", item]
        return self.call(*args)

    def review(self, task_id: str, td: Path):
        (td / "evidence/code-review.txt").write_text("Synthetic reviewer evidence for the current subject.\n", encoding="utf-8")
        return self.call(
            "review", "record", "--task", task_id, "--task-dir", str(td),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS", "--summary", "reviewed",
            "--evidence", "evidence/code-review.txt",
        )


def test_visual_required_rejects_static_contract_only():
    case = VisualCase()
    try:
        task_id = "TASK-V529-VISUAL-STATIC"
        td = case.create_task(task_id)
        case.prepare_development(task_id, td)
        static = td / "evidence" / "static-contract.txt"
        static.write_text("DOM/CSS contract passed\n", encoding="utf-8")
        rc, out, err = case.verify(task_id, td, "evidence/static-contract.txt")
        assert rc != 0
        assert "VISUAL_VERIFICATION" in out + err
    finally:
        case.close()


def test_visual_manifest_must_bind_current_change_set():
    case = VisualCase()
    try:
        task_id = "TASK-V529-VISUAL-CHANGESET"
        td = case.create_task(task_id)
        development = case.prepare_development(task_id, td)
        case.write_manifest(td, development["change_set_id"], bad_change_set=True)
        rc, out, err = case.verify(task_id, td, "evidence/visual/manifest.json")
        assert rc != 0
        assert "change_set_id" in out + err
    finally:
        case.close()


def test_visual_case_requires_acceptance_ref_route_viewport_actual_and_report():
    case = VisualCase()
    try:
        task_id = "TASK-V529-VISUAL-FIELDS"
        td = case.create_task(task_id)
        development = case.prepare_development(task_id, td)
        case.write_manifest(td, development["change_set_id"], omit_route=True)
        rc, out, err = case.verify(task_id, td, "evidence/visual/manifest.json")
        assert rc != 0
        assert "route" in out + err
    finally:
        case.close()


def test_visual_paths_cannot_escape_task_evidence():
    case = VisualCase()
    try:
        task_id = "TASK-V529-VISUAL-PATH"
        td = case.create_task(task_id)
        development = case.prepare_development(task_id, td)
        case.write_manifest(td, development["change_set_id"], escape_actual=True)
        rc, out, err = case.verify(task_id, td, "evidence/visual/manifest.json")
        assert rc != 0
        assert "actual" in out + err and "evidence" in out + err
    finally:
        case.close()


def test_visual_evidence_artifact_path_is_canonical_and_safe():
    case = VisualCase()
    try:
        td = case.create_task("TASK-V529-VISUAL-PATH-CLI", visual=False)
        rc, out, err = case.call(
            "task", "artifact-path", "--task-dir", str(td), "--kind", "visual-evidence", "--ensure",
        )
        assert rc == 0, (out, err)
        assert Path(out.strip()).resolve() == (td / "evidence" / "visual").resolve()
        assert (td / "evidence" / "visual").is_dir()
        rc, out, err = case.call(
            "task", "artifact-path", "--task-dir", str(td), "--kind", "visual-evidence", "--name", "../escape.png",
        )
        assert rc != 0
    finally:
        case.close()


def test_valid_visual_manifest_is_added_to_verification_evidence():
    case = VisualCase()
    try:
        task_id = "TASK-V529-VISUAL-VALID"
        td = case.create_task(task_id)
        development = case.prepare_development(task_id, td)
        case.write_manifest(td, development["change_set_id"])
        rc, out, err = case.verify(task_id, td, "evidence/visual/manifest.json")
        assert rc == 0, (out, err)
        conn = dbmod.connect(str(case.db))
        try:
            row = conn.execute(
                "SELECT detail_json FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED' ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        detail = json.loads(row["detail_json"])
        paths = {item["path"] for item in detail["evidence_items"]}
        assert "evidence/visual/manifest.json" in paths
        assert "evidence/visual/actual/UI-01.png" in paths
        assert "evidence/visual/UI-01.md" in paths
    finally:
        case.close()


def _prepare_l2_delivery(case: VisualCase, task_id: str, *, visual: bool = False, temporary_bypass: bool = False):
    td = case.create_task(task_id, visual=visual)
    development = case.prepare_development(task_id, td)
    if visual:
        case.write_manifest(td, development["change_set_id"], temporary_bypass=temporary_bypass)
        rc, out, err = case.verify(task_id, td, "evidence/visual/manifest.json")
    else:
        evidence = td / "evidence" / "verification.txt"
        evidence.write_text("verified\n", encoding="utf-8")
        rc, out, err = case.verify(task_id, td, "evidence/verification.txt")
    assert rc == 0, (out, err)
    rc, out, err = case.review(task_id, td)
    assert rc == 0, (out, err)
    return td


def test_delivery_rejects_active_or_cleanup_pending_temp_artifacts():
    for status in ("ACTIVE", "CLEANUP_PENDING"):
        case = VisualCase(level="L2")
        try:
            task_id = f"TASK-V529-TEMP-{status}"
            td = _prepare_l2_delivery(case, task_id)
            rc, out, err = case.call(
                "task", "artifact-path", "--task-dir", str(td), "--kind", "execution-temp",
                "--task", task_id, "--project", "demo", "--role", "tp-test-engineer",
                "--run-id", f"RUN-{status}", "--ensure",
            )
            assert rc == 0, (out, err)
            if status == "CLEANUP_PENDING":
                manifest = next((case.user_root / "temp-artifacts" / "manifests" / "demo" / task_id).glob("*.json"))
                data = json.loads(manifest.read_text(encoding="utf-8"))
                data["status"] = "CLEANUP_PENDING"
                data["cleanup_error"] = "simulated cleanup failure"
                manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            rc, out, err = case.call(
                "task", "delivery-converge", "--task", task_id, "--task-dir", str(td),
                "--delivery-status", "READY",
                "--reason", "Verified and reviewed change is ready for integration without blockers.",
            )
            assert rc != 0
            expected = "TEMP_ARTIFACT_ACTIVE" if status == "ACTIVE" else "TEMP_ARTIFACT_CLEANUP_PENDING"
            assert expected in out + err
        finally:
            case.close()


def test_delivery_rejects_uncleaned_temporary_auth_bypass():
    case = VisualCase(level="L2")
    try:
        task_id = "TASK-V529-AUTH-CLEANUP"
        td = _prepare_l2_delivery(case, task_id, visual=True, temporary_bypass=True)
        (td / "evidence" / "visual" / "auth-cleanup.md").unlink()
        rc, out, err = case.call(
            "task", "delivery-converge", "--task", task_id, "--task-dir", str(td),
            "--delivery-status", "READY",
            "--reason", "Verified and reviewed change is ready for integration without blockers.",
        )
        assert rc != 0
        assert "DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS" in out + err
    finally:
        case.close()


def test_visual_required_must_be_boolean_in_verification_contract():
    case = VisualCase()
    try:
        task_id = "TASK-V529-VISUAL-BOOLEAN"
        td = case.create_task(task_id)
        case.prepare_development(task_id, td)
        acceptance = td / "acceptance.md"
        text = acceptance.read_text(encoding="utf-8").replace("    required: true", '    required: "true"')
        acceptance.write_text(text, encoding="utf-8", newline="\n")
        static = td / "evidence" / "static-contract.txt"
        static.write_text("DOM/CSS contract passed\n", encoding="utf-8")
        rc, out, err = case.verify(task_id, td, "evidence/static-contract.txt")
        assert rc != 0
        assert "page_verification.visual.required" in out + err
    finally:
        case.close()


def test_visual_qa_guidance_and_template_are_explicit():
    root = Path(__file__).resolve().parents[2]
    testing_skill = (root / "skills/capabilities/testing-strategy/SKILL.md").read_text(encoding="utf-8")
    test_role = (root / "skills/roles/tp-test-engineer/SKILL.md").read_text(encoding="utf-8")
    review_role = (root / "skills/roles/tp-code-reviewer/SKILL.md").read_text(encoding="utf-8")
    integration_role = (root / "skills/roles/tp-integration-engineer/SKILL.md").read_text(encoding="utf-8")
    acceptance = (root / "templates/5.3.3/acceptance.md").read_text(encoding="utf-8")
    guide = (root / "templates/5.3.3/requirement-test-guide.md").read_text(encoding="utf-8")
    visual_reference = root / "skills/capabilities/testing-strategy/references/visual-qa.md"

    assert "Diff-aware" in testing_skill
    assert "visual-qa.md" in testing_skill
    assert "visual-qa.md" in test_role
    assert "静态结构契约" in review_role and "视觉" in review_role
    assert "TEMP_ARTIFACT_ACTIVE" in integration_role
    assert "visual:" in acceptance and "evidence_manifest" in acceptance
    assert "Change Set / Diff 影响页面" in guide
    assert visual_reference.is_file()


# B03 uses the production main, not the cached/parser-skipping test entry.


@pytest.fixture
def b03_case(monkeypatch):
    from scripts.tests.v532_testutil import run_cli
    monkeypatch.setitem(globals(), "run", run_cli)
    case = VisualCase(level="L2")
    tid = "TASK-B03-EVIDENCE"
    td = case.create_task(tid, visual=False)
    (td / "acceptance.md").write_text(
        '```yaml\nno_acceptance_required:\n  declared: true\n'
        '  reason: Isolated evidence identity regression, not business acceptance.\n'
        'deferred_acceptance: []\nowner_waivers: []\ndatabase_operations: []\n```\n',
        encoding="utf-8",
    )
    case.prepare_development(tid, td)
    (td / "evidence/technical.txt").write_text("synthetic technical result\n", encoding="utf-8")
    (td / "evidence/code-review.txt").write_text(
        "Synthetic independent-review fixture; human/visual acceptance is not claimed.\n", encoding="utf-8"
    )
    rc, out, err = case.verify(tid, td, "evidence/technical.txt")
    assert rc == 0, (out, err)
    try:
        yield case, tid, td
    finally:
        case.close()


def _b03_review(case, tid, td, *, decision="PASS", kind="CODE", evidence=True, count=0):
    return case.call(
        "review", "record", "--task", tid, "--task-dir", str(td),
        "--actor", "tp-code-reviewer", "--kind", kind, "--decision", decision,
        "--findings-count", str(count), "--summary", "Synthetic review result",
        *(["--evidence", "evidence/code-review.txt"] if evidence else []),
    )


def _b03_delivery(case, tid, td):
    return case.call("task", "delivery-converge", "--task", tid, "--task-dir", str(td),
                     "--delivery-status", "READY", "--reason", "Synthetic delivery with independently bound evidence.")


def _b03_event_rows(case, tid):
    with dbmod.connect_readonly(str(case.db)) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (tid,))]


def test_b03_code_pass_requires_review_evidence_not_a_generated_receipt(b03_case):
    case, tid, td = b03_case
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td, evidence=False)
    assert rc != 0, "a Runtime receipt alone must not constitute a CODE PASS"
    assert "CODE_REVIEW_EVIDENCE_REQUIRED" in out + err
    assert _b03_event_rows(case, tid) == before


def test_b03_code_pass_rejects_negative_findings(b03_case):
    count = -1
    case, tid, td = b03_case
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td, count=count)
    assert rc != 0, "A negative findings count is invalid"
    assert "findings" in (out + err).lower()
    assert _b03_event_rows(case, tid) == before


def test_b03_positive_findings_count_does_not_invent_a_blocking_severity(b03_case):
    case, tid, td = b03_case
    (td / "evidence/code-review.txt").write_text(
        "Synthetic reviewer PASS with one non-blocking maintenance recommendation.\n", encoding="utf-8"
    )
    rc, out, err = _b03_review(case, tid, td, count=1)
    assert rc == 0, (out, err)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc == 0, (out, err)


@pytest.mark.parametrize("decision", ["FAIL", "NEEDS_FIX"])
def test_b03_newer_failed_verification_does_not_revive_older_pass(b03_case, decision):
    case, tid, td = b03_case
    rc, out, err = case.call("task", "verify", "--task", tid, "--task-dir", str(td),
                             "--actor", "tp-test-engineer", "--decision", decision,
                             "--summary", "New technical evidence disproves the earlier pass")
    assert rc == 0, (out, err)
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0, "Review must not search past a newer negative result for an older PASS"
    assert "VERIFICATION_STALE" in out + err
    assert _b03_event_rows(case, tid) == before


def test_b03_invalid_latest_verification_evidence_does_not_fall_back(b03_case):
    case, tid, td = b03_case
    new = td / "evidence/new-technical.txt"
    new.write_text("new synthetic result\n", encoding="utf-8")
    rc, out, err = case.verify(tid, td, "evidence/new-technical.txt")
    assert rc == 0, (out, err)
    new.unlink()
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0, "damaged latest evidence must not silently select an older event"
    assert "VERIFICATION_STALE" in out + err
    assert _b03_event_rows(case, tid) == before


@pytest.mark.parametrize("target", ["evidence", "receipt"])
def test_b03_delivery_revalidates_review_evidence_and_receipt(b03_case, target):
    case, tid, td = b03_case
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    review = _b03_event_rows(case, tid)[-1]
    detail = json.loads(review["detail_json"])
    path = td / ("evidence/code-review.txt" if target == "evidence" else detail["artifact"])
    path.write_text("corrupted after the formal review\n", encoding="utf-8")
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc != 0, "Delivery must validate the evidence and artifact it relies on"
    assert "REVIEW" in (out + err).upper()
    assert _b03_event_rows(case, tid) == before


@pytest.mark.parametrize("kind,decision", [("CODE", "NEEDS_FIX"), ("IMPLEMENTATION", "FAIL"), ("ULTRA_REVIEW", "BLOCKED")])
def test_b03_delivery_cannot_ignore_newer_review_across_aliases(b03_case, kind, decision):
    case, tid, td = b03_case
    for new_kind, verdict in [("CODE", "PASS"), (kind, decision)]:
        rc, out, err = _b03_review(case, tid, td, kind=new_kind, decision=verdict)
        assert rc == 0, (out, err)
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc != 0, "a newer finding/BLOCKED must not be bypassed using an older alias PASS"
    assert "REVIEW" in (out + err).upper()
    assert _b03_event_rows(case, tid) == before


def test_b03_review_rechecks_bound_evidence_at_transaction_boundary(b03_case, monkeypatch):
    from cli import review_cmd
    case, tid, td = b03_case
    real_commit = review_cmd._commit_with_recovery
    def mutate_then_commit(*args, **kwargs):
        (td / "evidence/code-review.txt").write_text("changed after preflight\n", encoding="utf-8")
        return real_commit(*args, **kwargs)
    monkeypatch.setattr(review_cmd, "_commit_with_recovery", mutate_then_commit)
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0, "Review must not commit evidence hashes computed before a concurrent modification"
    assert _b03_event_rows(case, tid) == before


def test_b03_complete_cannot_reuse_ready_after_review_evidence_is_corrupted(b03_case):
    case, tid, td = b03_case
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc == 0, (out, err)
    (td / "evidence/code-review.txt").write_text("modified after READY\n", encoding="utf-8")
    before = _b03_event_rows(case, tid)
    rc, out, err = case.call("task", "complete", "--task", tid, "--task-dir", str(td),
                            "--actor", "tp-integration-engineer", "--summary", "Must not pass corrupted evidence")
    assert rc != 0, "READY is not an exemption from current evidence integrity"
    assert _b03_event_rows(case, tid) == before


@pytest.mark.parametrize("target", ["technical", "product", "subject"])
def test_b03_review_rechecks_technical_binding_before_write(b03_case, monkeypatch, target):
    from cli import review_cmd
    case, tid, td = b03_case
    real_commit = review_cmd._commit_with_recovery
    def mutate_then_commit(*args, **kwargs):
        path = {"technical": td / "evidence/technical.txt",
                "product": case.project / "src/app.txt", "subject": td / "acceptance.md"}[target]
        assert path.is_file()
        path.write_text(path.read_text(encoding="utf-8") + "\nconcurrent change\n", encoding="utf-8")
        return real_commit(*args, **kwargs)
    monkeypatch.setattr(review_cmd, "_commit_with_recovery", mutate_then_commit)
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0, "Review must be bound to the technical evidence/subject actually committed"
    assert _b03_event_rows(case, tid) == before


@pytest.mark.parametrize("target", ["technical.txt", "code-review.txt", "delivery.txt"])
def test_b03_delivery_rechecks_bound_results_before_write(b03_case, monkeypatch, target):
    from cli import record_first
    case, tid, td = b03_case
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    (td / "evidence/delivery.txt").write_text("Synthetic delivery observation\n", encoding="utf-8")
    real_write = record_first._write_with_projection
    def mutate_then_write(*args, **kwargs):
        (td / "evidence" / target).write_text("changed after delivery preflight\n", encoding="utf-8")
        return real_write(*args, **kwargs)
    monkeypatch.setattr(record_first, "_write_with_projection", mutate_then_write)
    before = _b03_event_rows(case, tid)
    rc, out, err = case.call("task", "delivery-converge", "--task", tid, "--task-dir", str(td),
                            "--delivery-status", "READY", "--reason", "Boundary validation",
                            "--evidence", "evidence/delivery.txt")
    assert rc != 0, "READY must not bind evidence that changed before the transaction"
    assert _b03_event_rows(case, tid) == before


@pytest.mark.parametrize("human_verdict", ["PENDING", "BLOCKED"])
def test_b03_human_pending_can_keep_technical_and_review_facts_but_not_complete(b03_case, human_verdict):
    from cli.digest import compute_verification_subject_digest
    case, tid, td = b03_case
    acceptance = td / "acceptance.md"
    acceptance.write_text(
        "| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| AC-HUMAN-01 | 用户确认交互行为 | task.md | L1 | 人工操作 | | human | {human_verdict} |\n"
        '```yaml\npage_verification:\n  mode: human\n  human_witness: pending\n'
        '  witness_evidence: ""\ndeferred_acceptance: []\nowner_waivers: []\ndatabase_operations: []\n```\n',
        encoding="utf-8",
    )
    rc, out, err = case.verify(tid, td, "evidence/technical.txt")
    assert rc == 0, (out, err)
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    subject = compute_verification_subject_digest(td)
    # Adding an external screenshot/result alone neither changes a technical subject
    # nor manufactures a witness, a verification or a new review event.
    before = _b03_event_rows(case, tid)
    (td / "evidence/external-result.txt").write_text("External declaration; execution and witness unknown.\n", encoding="utf-8")
    assert compute_verification_subject_digest(td) == subject
    assert _b03_event_rows(case, tid) == before
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc != 0 and "INTEGRITY_ACCEPTANCE" in out + err
    assert _b03_event_rows(case, tid) == before
    rc, out, err = case.call("task", "complete", "--task", tid, "--task-dir", str(td),
                            "--actor", "tp-integration-engineer", "--summary", "Human still pending")
    assert rc != 0
    assert "human_witness: pending" in acceptance.read_text(encoding="utf-8")


@pytest.mark.parametrize("actor", ["tp-development-engineer", "tp-software-architect"])
def test_b03_non_reviewer_cannot_sign_code_pass(b03_case, actor):
    case, tid, td = b03_case
    before = _b03_event_rows(case, tid)
    rc, out, err = case.call("review", "record", "--task", tid, "--task-dir", str(td),
        "--actor", actor, "--kind", "CODE", "--decision", "PASS", "--evidence", "evidence/code-review.txt")
    assert rc != 0
    assert _b03_event_rows(case, tid) == before


def test_b03_visual_required_missing_evidence_still_blocks_full_verify_and_review(b03_case):
    case, tid, td = b03_case
    case.write_visual_acceptance(td)
    acceptance = td / "acceptance.md"
    acceptance.write_text(acceptance.read_text(encoding="utf-8").replace("| verification | PASS |", "| verification | PENDING |"), encoding="utf-8")
    before = _b03_event_rows(case, tid)
    rc, out, err = case.verify(tid, td, "evidence/technical.txt")
    assert rc != 0 and "VISUAL_VERIFICATION_INVALID" in out + err
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0 and "VERIFICATION_STALE" in out + err
    assert _b03_event_rows(case, tid) == before


@pytest.mark.parametrize("mode,verdict", [("waive", "OWNER_WAIVED"), ("defer", "DEFERRED_ACCEPTED")])
def test_b03_legal_owner_disposition_preserves_unrun_fact_at_ready_and_complete(b03_case, mode, verdict):
    from scripts.tests.test_v529_acceptance_database import _write_acceptance
    case, tid, td = b03_case
    _write_acceptance(td, "PENDING")
    path = td / "acceptance.md"
    path.write_text(path.read_text(encoding="utf-8").replace("| verification |", "| human |")
                    .replace("mode: NOT_REQUIRED", "mode: human"), encoding="utf-8")
    rc, out, err = case.call(
        "task", "acceptance-override", "--task", tid, "--task-dir", str(td),
        "--actor", "human_owner", "--mode", mode, "--ac", "AC-01",
        "--reason", "Synthetic owner decision", "--residual-risk", "User operation remains unrun",
        *(["--reverify-owner", "human_owner", "--trigger", "Authorized test window"] if mode == "defer" else []),
    )
    assert rc == 0, (out, err)
    assert verdict in path.read_text(encoding="utf-8")
    rc, out, err = case.verify(tid, td, "evidence/technical.txt")
    assert rc == 0, (out, err)
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc == 0, (out, err)
    rc, out, err = case.call("task", "complete", "--task", tid, "--task-dir", str(td),
                            "--actor", "tp-integration-engineer", "--summary", "Owner disposition is not PASS")
    assert rc == 0, (out, err)
    assert "| PASS |" not in path.read_text(encoding="utf-8")
    assert "human_witness: pending" in path.read_text(encoding="utf-8")


@pytest.fixture
def b03b_case(monkeypatch):
    """Real CLI with isolated visual/technical evidence, not a browser run."""
    from scripts.tests.v532_testutil import run_cli
    monkeypatch.setitem(globals(), "run", run_cli)
    case = VisualCase(level="L2")
    try:
        tid = "TASK-B03B-SCOPED"
        td = case.create_task(tid)
        acceptance = td / "acceptance.md"
        acceptance.write_text(acceptance.read_text(encoding="utf-8").replace("| PASS |", "| PENDING |"), encoding="utf-8")
        development = case.prepare_development(tid, td)
        (td / "evidence/technical.txt").write_text("Synthetic unit check: replacement preserves one selection.\n", encoding="utf-8")
        (td / "evidence/code-review.txt").write_text("Synthetic CODE review evidence; no actual reviewer/model invoked.\n", encoding="utf-8")
        yield case, tid, td, development
    finally:
        case.close()


def _b03b_verify(case, tid, td, *, scope="technical", decision="PASS", check=True, evidence=True):
    args = ["task", "verify", "--task", tid, "--task-dir", str(td), "--scope", scope,
            "--decision", decision, "--summary", "Selected technical check only; visual acceptance pending"]
    if check:
        args += ["--check", "replacement preserves one selection"]
    if evidence:
        args += ["--evidence", "evidence/technical.txt"]
    return case.call(*args)


def _b03b_full(case, tid, td, development):
    case.write_manifest(td, development["change_set_id"])
    acceptance = td / "acceptance.md"
    acceptance.write_text(acceptance.read_text(encoding="utf-8").replace("| PENDING |", "| PASS |"), encoding="utf-8")
    rc, out, err = case.verify(tid, td, "evidence/technical.txt")
    assert rc == 0, (out, err)
    return json.loads(out)


def test_b03b_explicit_technical_pass_records_scope_without_visual_pass(b03b_case):
    case, tid, td, development = b03b_case
    before = (td / "acceptance.md").read_bytes()
    rc, out, err = _b03b_verify(case, tid, td)
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result["verification_scope"] == "technical"
    assert result["checks"] == ["replacement preserves one selection"]
    detail = json.loads(_b03_event_rows(case, tid)[-1]["detail_json"])
    assert detail["change_set_id"] == development["change_set_id"]
    assert detail["verification_scope"] == "technical" and "visual_verification" not in detail
    assert (td / "acceptance.md").read_bytes() == before
    assert not (td / "evidence/visual/manifest.json").exists()
    assert "PASS_TECHNICAL" in (td / "status.yaml").read_text(encoding="utf-8")
    assert "PASS_TECHNICAL" in (td / "generated/continuation.md").read_text(encoding="utf-8")


def test_b03b_default_verify_still_requires_visual_evidence(b03b_case):
    case, tid, td, _ = b03b_case
    rc, out, err = case.verify(tid, td, "evidence/technical.txt")
    assert rc != 0 and "VISUAL_VERIFICATION" in out + err


@pytest.mark.parametrize("missing", ["check", "evidence"])
def test_b03b_scoped_pass_rejects_missing_scope_or_real_evidence(b03b_case, missing):
    case, tid, td, _ = b03b_case
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03b_verify(case, tid, td, check=missing != "check", evidence=missing != "evidence")
    assert rc != 0
    assert ("check" if missing == "check" else "evidence") in (out + err).lower()
    assert _b03_event_rows(case, tid) == before


def test_b03b_review_before_visual_then_wait_without_repeated_delivery(b03b_case):
    case, tid, td, _ = b03b_case
    rc, out, err = _b03b_verify(case, tid, td)
    assert rc == 0, (out, err)
    rc, out, err = case.call("workflow", "next", "--task", tid, "--json")
    assert rc == 0, (out, err)
    assert json.loads(out)["next_stage"] == "review"
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    assert 'review: "PASS"' in (td / "status.yaml").read_text(encoding="utf-8")
    before = _b03_event_rows(case, tid)
    for _ in range(2):
        rc, out, err = case.call("workflow", "next", "--task", tid, "--json")
        assert rc == 0, (out, err)
        route = json.loads(out)
        assert route["recommended_action"] == "none", route
        assert "FULL_VERIFICATION_REQUIRED" in route["reason_codes"]
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc != 0 and "VERIFICATION" in out + err
    assert _b03_event_rows(case, tid) == before


def test_b03b_full_verification_reuses_unchanged_technical_review(b03b_case):
    case, tid, td, development = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    rc, out, err = _b03_review(case, tid, td)
    assert rc == 0, (out, err)
    reviewed = [r for r in _b03_event_rows(case, tid) if r["event_type"] == "REVIEW_COMPLETED"]
    _b03b_full(case, tid, td, development)
    rc, out, err = case.call("workflow", "next", "--task", tid, "--json")
    assert rc == 0, (out, err)
    assert json.loads(out)["next_stage"] == "delivery", out
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc == 0, (out, err)
    assert reviewed == [r for r in _b03_event_rows(case, tid) if r["event_type"] == "REVIEW_COMPLETED"]


@pytest.mark.parametrize("target", ["product", "criteria", "evidence"])
def test_b03b_technical_review_rejects_changed_subject_or_evidence(b03b_case, target):
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    path = {"product": case.project / "src/app.txt", "criteria": td / "acceptance.md",
            "evidence": td / "evidence/technical.txt"}[target]
    path.write_text(path.read_text(encoding="utf-8") + "\nsubstantive change\n", encoding="utf-8")
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0 and "VERIFICATION_STALE" in out + err
    assert _b03_event_rows(case, tid) == before


def test_b03b_new_failure_requires_review_again_even_after_full_pass(b03b_case):
    case, tid, td, development = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    assert _b03_review(case, tid, td)[0] == 0
    assert _b03b_verify(case, tid, td, decision="FAIL")[0] == 0
    _b03b_full(case, tid, td, development)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc != 0 and "review" in (out + err).lower()


def test_b03b_full_pass_does_not_hide_destroyed_original_technical_evidence(b03b_case):
    case, tid, td, development = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    assert _b03_review(case, tid, td)[0] == 0
    (td / "evidence/technical.txt").write_text("new run overwrote original evidence\n", encoding="utf-8")
    _b03b_full(case, tid, td, development)
    rc, out, err = _b03_delivery(case, tid, td)
    assert rc != 0 and "review" in (out + err).lower()


def test_b03b_blocked_review_stays_blocked_with_unchanged_technical_prerequisite(b03b_case):
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    rc, out, err = _b03_review(case, tid, td, decision="BLOCKED")
    assert rc == 0, (out, err)
    for _ in range(2):
        rc, out, err = case.call("workflow", "next", "--task", tid, "--json")
        assert rc == 0, (out, err)
        route = json.loads(out)
        assert route["recommended_action"] == "none", route
        assert route["reason_codes"] == ["REVIEW_BLOCKED"], route


@pytest.mark.parametrize("target", ["product", "criteria"])
def test_b03b_verify_rechecks_subject_at_commit_boundary(b03b_case, monkeypatch, target):
    from cli import record_first
    case, tid, td, _ = b03b_case
    original = record_first._write_with_projection
    def change_before_transaction(*args, **kwargs):
        path = case.project / "src/app.txt" if target == "product" else td / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged during verify\n", encoding="utf-8")
        return original(*args, **kwargs)
    monkeypatch.setattr(record_first, "_write_with_projection", change_before_transaction)
    before = _b03_event_rows(case, tid)
    rc, out, err = _b03b_verify(case, tid, td)
    assert rc != 0, "PASS must bind the actual subject at its commit boundary"
    assert _b03_event_rows(case, tid) == before


def test_b03b_scope_and_checks_participate_in_logical_request_identity(b03b_case):
    case, tid, td, _ = b03b_case
    args = ["task", "verify", "--task", tid, "--task-dir", str(td), "--scope", "technical",
            "--decision", "PASS", "--summary", "same logical request", "--evidence", "evidence/technical.txt",
            "--request-id", "b03b-same-request", "--check", "actual targeted check"]
    rc, out, err = case.call(*args)
    assert rc == 0, (out, err)
    before = _b03_event_rows(case, tid)
    rc, out, err = case.call(*args)
    assert rc == 0 and json.loads(out)["replayed"] is True, (out, err)
    changed = list(args)
    changed[-1] = "different check"
    assert case.call(*changed)[0] != 0
    changed = list(args)
    changed[changed.index("technical")] = "full"
    assert case.call(*changed)[0] != 0
    assert _b03_event_rows(case, tid) == before


def test_b03b_l0_cannot_complete_on_only_technical_result(monkeypatch, tmp_path):
    from scripts.tests.v532_testutil import make_runtime, run_cli, task_args
    project, db, td, tid = make_runtime(tmp_path, monkeypatch, task_id="TASK-B03B-L0")
    rc, out, err = run_cli(task_args(db, td, tid, "checkpoint", "--actor", "tp-development-engineer",
                                    "--phase", "development", "--summary", "done", "--repo-root", str(project)))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(db, td, tid, "verify", "--decision", "PASS", "--scope", "technical",
                                    "--check", "targeted unit", "--summary", "technical only", "--evidence", "evidence/check.txt"))
    assert rc == 0, (out, err)
    rc, out, err = run_cli(task_args(db, td, tid, "complete", "--actor", "tp-development-engineer", "--summary", "not full"))
    assert rc != 0 and "INTEGRITY_PIPELINE_PENDING" in out + err


@pytest.mark.parametrize("field,value", [("verification_scope", "unknown"), ("verification_scope", None), ("checks", []), ("checks", [""])])
def test_b03b_unknown_or_incomplete_scope_never_grants_current_pass(b03b_case, field, value):
    from cli import event_policies
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    detail = json.loads(_b03_event_rows(case, tid)[-1]["detail_json"])
    detail[field] = value
    assert not event_policies.verification_subject_matches(detail, td)


def test_b03b_legacy_absent_scope_retains_full_subject_semantics(b03b_case):
    from cli import event_policies
    from cli.digest import compute_verification_subject_digest
    _, _, td, _ = b03b_case
    detail = {"decision": "PASS", "subject_digest": compute_verification_subject_digest(td)}
    assert event_policies.verification_scope(detail) == "full"
    assert event_policies.verification_subject_matches(detail, td)


def test_b03b_projection_marks_changed_criteria_stale(b03b_case):
    from cli import projection_cmd
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    assert _b03_review(case, tid, td)[0] == 0
    acceptance = td / "acceptance.md"
    acceptance.write_text(acceptance.read_text(encoding="utf-8").replace("375px", "430px"), encoding="utf-8")
    with dbmod.connect_readonly(str(case.db)) as conn:
        quality = projection_cmd._extract_quality_facts(conn, tid)
    assert quality["verification"] == "PASS_TECHNICAL_STALE"
    assert quality["review"] == "PASS_STALE"


def test_b03b_later_technical_result_invalidates_ready_projection(b03b_case):
    from cli import projection_cmd
    case, tid, td, development = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    assert _b03_review(case, tid, td)[0] == 0
    _b03b_full(case, tid, td, development)
    assert _b03_delivery(case, tid, td)[0] == 0
    assert _b03b_verify(case, tid, td)[0] == 0
    with dbmod.connect_readonly(str(case.db)) as conn:
        quality = projection_cmd._extract_quality_facts(conn, tid)
    assert quality["delivery"] == "READY_STALE"
    assert quality["verification"] == "PASS_TECHNICAL"


@pytest.mark.parametrize("target", ["criteria", "product"])
def test_b03b_complete_rechecks_full_subject_at_commit_boundary(b03b_case, monkeypatch, target):
    from cli import record_first
    case, tid, td, development = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    assert _b03_review(case, tid, td)[0] == 0
    _b03b_full(case, tid, td, development)
    assert _b03_delivery(case, tid, td)[0] == 0
    before = _b03_event_rows(case, tid)
    original = record_first._write_with_projection
    def changed_before_complete(*args, **kwargs):
        path = td / "acceptance.md" if target == "criteria" else case.project / "src/app.txt"
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged after preflight\n", encoding="utf-8")
        return original(*args, **kwargs)
    monkeypatch.setattr(record_first, "_write_with_projection", changed_before_complete)
    rc, out, err = case.call("task", "complete", "--task", tid, "--task-dir", str(td),
                            "--actor", "tp-integration-engineer", "--summary", "must not close stale subject")
    assert rc != 0, "Complete must not use validation of a different final subject"
    assert _b03_event_rows(case, tid) == before


def test_b03b_wait_exposes_existing_condition_field(b03b_case):
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    assert _b03_review(case, tid, td)[0] == 0
    rc, out, err = case.call("workflow", "next", "--task", tid, "--json")
    assert rc == 0, (out, err)
    wait = json.loads(out)["context"]["waiting"]
    assert wait.get("condition"), "Existing wait consumers need the recovery condition, not a new parallel field"


def test_b03b_projection_failure_rolls_back_staged_review_receipt(b03b_case, monkeypatch):
    from cli import projection_cmd
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    before = _b03_event_rows(case, tid)
    receipts = set(td.glob(".execution/*/review/result-*.json"))
    def fail_projection(*args, **kwargs):
        raise OSError("synthetic required projection failure")
    monkeypatch.setattr(projection_cmd, "render_projection", fail_projection)
    rc, out, err = _b03_review(case, tid, td)
    assert rc != 0
    assert _b03_event_rows(case, tid) == before
    assert set(td.glob(".execution/*/review/result-*.json")) == receipts


def test_b03b_explicit_card_preserves_technical_scope(b03b_case):
    from cli.cards.snapshot import build_task_snapshot
    case, tid, td, _ = b03b_case
    assert _b03b_verify(case, tid, td)[0] == 0
    before = _b03_event_rows(case, tid)
    snapshot = build_task_snapshot(tid, db_path=case.db, registry_path=str(case.registry))
    assert snapshot["verification"]["status"] == "PASS_TECHNICAL"
    assert snapshot["verification"]["checks"] == ["replacement preserves one selection"]
    assert _b03_event_rows(case, tid) == before
