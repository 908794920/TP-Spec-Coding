# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

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
        return self.call(
            "review", "record", "--task", task_id, "--task-dir", str(td),
            "--actor", "tp-code-reviewer", "--kind", "CODE", "--decision", "PASS", "--summary", "reviewed",
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
    acceptance = (root / "templates/5.3.0/acceptance.md").read_text(encoding="utf-8")
    guide = (root / "templates/5.3.0/requirement-test-guide.md").read_text(encoding="utf-8")
    visual_reference = root / "skills/capabilities/testing-strategy/references/visual-qa.md"

    assert "Diff-aware" in testing_skill
    assert "visual-qa.md" in testing_skill
    assert "visual-qa.md" in test_role
    assert "静态结构契约" in review_role and "视觉" in review_role
    assert "TEMP_ARTIFACT_ACTIVE" in integration_role
    assert "visual:" in acceptance and "evidence_manifest" in acceptance
    assert "Change Set / Diff 影响页面" in guide
    assert visual_reference.is_file()
