# -*- coding: utf-8 -*-
"""V5.1.0 C5 S1 声明拒绝校验器回归套件（B-17 C5-P1~P6 + fail-closed + D1 优先级）。

设计权威：docs/V5.1.0-C5-S1-declaration-rejection-design.md §3-§4；
对齐 B-17 设计 §3.5（C5-P1~P6，L176-181）与通用约定 §2
（强断言：decision 终值 + errors[] 成员 + STDERR 错误码逐字节 + 退出码；失败即 FAIL）。

纯 stdlib unittest、离线；fixture 与端到端在临时目录内（--s1-validate 经 review-preflight 跑通，
fixture git 仓库临时目录隔离，不污染真实任务目录）。

Run:
    python scripts/tests/test_c5_s1_validator.py
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # tp-spec-base
sys.path.insert(0, str(BASE))
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()

from cli import s1_validator  # noqa: E402
from cli.s1_validator import (  # noqa: E402
    S1_IMPLEMENTATION_REJECTED, S1_PASS_EVIDENCE_REJECTED,
    S3_IMPLEMENTATION_REJECTED, S1_NO_S3_RISK_LABEL,
    S1_RELATED_CANDIDATE_REJECTED, S1_VALIDATOR_ERROR,
    validate_declaration, validate_declarations, any_rejected,
    _S1_VALIDATOR_VERSION,
)


def decl(**kw) -> dict:
    """默认已标注 S3 风险（R4 不命中），仅 R4/D1 用例显式置 False。"""
    base = dict(
        id="D1", source="README.md:84", evidence_level="S1",
        purpose="implementation_basis", context=None, s3_risk_labeled=True,
    )
    base.update(kw)
    return base


class TestS1ValidatorRules(unittest.TestCase):
    """R1-R8 判定分支（C5-P1~P6 + fail-closed + D1 优先级）。"""

    # ---- C5-P1：R1 S1 作为实施依据 → 拒绝 ----
    def test_c5_p1_s1_implementation_rejected(self):
        result = validate_declaration(decl(purpose="implementation_basis"))
        self.assertEqual(result["decision"], "rejected")
        self.assertEqual(result["errors"], [S1_IMPLEMENTATION_REJECTED])
        self.assertEqual(result["message"], "S1 不得作为实施依据")
        self.assertEqual(result["s1_validator_version"], _S1_VALIDATOR_VERSION)

    # ---- C5-P2：R2 S1 作为 PASS 证据 → 拒绝 ----
    def test_c5_p2_s1_pass_evidence_rejected(self):
        result = validate_declaration(decl(purpose="pass_evidence"))
        self.assertEqual(result["decision"], "rejected")
        self.assertEqual(result["errors"], [S1_PASS_EVIDENCE_REJECTED])

    # ---- C5-P3：R3 S3 三用途均拒绝 ----
    def test_c5_p3_s3_rejected_three_purposes(self):
        for purpose in ("implementation_basis", "performance_claim", "acceptance_evidence", "pass_evidence"):
            result = validate_declaration(decl(evidence_level="S3", purpose=purpose))
            self.assertEqual(result["decision"], "rejected", purpose)
            self.assertEqual(result["errors"], [S3_IMPLEMENTATION_REJECTED], purpose)
        # S3 + 非禁止用途（design_reference）→ 不拒绝
        ok = validate_declaration(decl(evidence_level="S3", purpose="design_reference"))
        self.assertEqual(ok["decision"], "accepted")

    # ---- C5-P4：R4 S1 未标注 S3 风险 → requires_label（不阻断）----
    def test_c5_p4_s1_no_s3_risk_label(self):
        result = validate_declaration(decl(purpose="design_reference", s3_risk_labeled=False))
        self.assertEqual(result["decision"], "requires_label")
        self.assertEqual(result["errors"], [S1_NO_S3_RISK_LABEL])
        # 已标注 → 放行
        ok = validate_declaration(decl(purpose="design_reference", s3_risk_labeled=True))
        self.assertEqual(ok["decision"], "accepted")
        self.assertEqual(ok["errors"], [])

    # ---- C5-P5：R5 S2 可回链 → 放行 ----
    def test_c5_p5_s2_linkable_accepted(self):
        for source in ("src/main.py:42", "src/main.py:run:42"):
            result = validate_declaration(decl(evidence_level="S2", purpose="design_reference", source=source))
            self.assertEqual(result["decision"], "accepted", source)
            self.assertEqual(result["errors"], [], source)

    # ---- C5-P6：R6 S1 关联候选（OCR README 归并）→ 拒绝 ----
    def test_c5_p6_s1_related_candidate_rejected(self):
        result = validate_declaration(decl(purpose="related_candidate", source="README.md:84"))
        self.assertEqual(result["decision"], "rejected")
        self.assertEqual(result["errors"], [S1_RELATED_CANDIDATE_REJECTED])
        self.assertEqual(result["message"], "拒绝作为关联规则依据；按 basename 归并自建实现")

    # ---- R7：UNKNOWN 等级 / 非法用途 / S2 不可回链 → fail-closed 拒绝 ----
    def test_r7_unknown_fail_closed(self):
        for kw in (
            {"evidence_level": "UNKNOWN"},
            {"evidence_level": "S4"},
            {"evidence_level": None},
            {"purpose": "not_a_purpose"},
        ):
            result = validate_declaration(decl(**kw))
            self.assertEqual(result["decision"], "rejected", kw)
        # S2 但不可回链 → R7 fail-closed
        bad_s2 = validate_declaration(decl(evidence_level="S2", purpose="design_reference", source="no linkable form"))
        self.assertEqual(bad_s2["decision"], "rejected")

    # ---- R8：输入解析异常 → S1_VALIDATOR_ERROR ----
    def test_r8_parse_error_fail_closed(self):
        # 缺必填 id → KeyError → R8 fail-closed（不静默放行）
        results = validate_declarations([{"purpose": "implementation_basis"}])
        self.assertEqual(results[0]["decision"], "rejected")
        self.assertEqual(results[0]["errors"], [S1_VALIDATOR_ERROR])
        # 非 dict 元素 → R8
        bad = validate_declarations(["not-a-dict"])
        self.assertEqual(bad[0]["decision"], "rejected")
        self.assertEqual(bad[0]["errors"], [S1_VALIDATOR_ERROR])

    # ---- D1：优先级 rejected > requires_label > accepted ----
    def test_d1_priority_rejected_wins(self):
        # R1 与 R4 同时命中 → rejected，errors 双码
        result = validate_declaration(decl(purpose="implementation_basis", s3_risk_labeled=False))
        self.assertEqual(result["decision"], "rejected")
        self.assertEqual(result["errors"], [S1_IMPLEMENTATION_REJECTED, S1_NO_S3_RISK_LABEL])
        # 仅 R4 → requires_label
        only_r4 = validate_declaration(decl(purpose="design_reference", s3_risk_labeled=False))
        self.assertEqual(only_r4["decision"], "requires_label")
        # 无命中 → accepted
        ok = validate_declaration(decl(purpose="design_reference", s3_risk_labeled=True))
        self.assertEqual(ok["decision"], "accepted")

    # ---- errors[] 确定性排序 ----
    def test_errors_sorted_deterministic(self):
        r1 = validate_declaration(decl(purpose="implementation_basis", s3_risk_labeled=False))
        r2 = validate_declaration(decl(purpose="implementation_basis", s3_risk_labeled=False))
        self.assertEqual(r1["errors"], r2["errors"])
        self.assertEqual(r1["errors"], sorted(r1["errors"]))

    # ---- 正交独立：不 import anchor_check/sensitive_scanner/review_preflight ----
    def test_orthogonal_no_scanning_imports(self):
        tree = ast.parse(Path(s1_validator.__file__).read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        for banned in ("anchor_check", "sensitive_scanner", "review_preflight"):
            self.assertNotIn(banned, "|".join(imports), banned)

    # ---- any_rejected 聚合 ----
    def test_any_rejected(self):
        self.assertTrue(any_rejected([{"decision": "rejected"}]))
        self.assertFalse(any_rejected([{"decision": "accepted"}, {"decision": "requires_label"}]))


# =============================================================================
# 端到端：--s1-validate 经 review-preflight 跑通（manifest.s1_validation[] + 退出码）
# =============================================================================
def _git_ok(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def make_fixture_repo(tmp: Path) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    (repo / "src.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    _git_ok(repo, "add", ".")
    _git_ok(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    base = _git_ok(repo, "rev-parse", "HEAD")
    (repo / "src.py").write_text("def main():\n    return 43  # changed\n", encoding="utf-8")
    _git_ok(repo, "add", ".")
    _git_ok(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "head")
    head = _git_ok(repo, "rev-parse", "HEAD")
    return repo, base, head


def run_preflight_with_s1(task_dir: Path, repo: Path, base: str, head: str, s1_path: str) -> tuple[int, str, str]:
    import argparse
    from cli.review_preflight import cmd_review_preflight
    args = argparse.Namespace(
        task="TASK-C5-TEST", task_dir=str(task_dir), repo=str(repo),
        base_sha=base, head_sha=head, findings_file=None, rules_file=None,
        s1_validate=s1_path, phase_exit=False, simulate=False, db=None,
    )
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cmd_review_preflight(args)
        except ValueError as exc:
            err.write(f"ValueError: {exc}\n")
            rc = 1
    return rc, out.getvalue(), err.getvalue()


class TestC5EndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c5_s1_")
        self.tmp = Path(self._tmp)
        self.repo, self.base, self.head = make_fixture_repo(self.tmp)
        self.task_dir = self.tmp / "task"
        self.task_dir.mkdir()
        (self.task_dir / "status.yaml").write_text(
            f'task_id: "TASK-C5-TEST"\nartifact_contract:\n  version: "{ACTIVE_VERSION}"\n',
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_s1(self, declarations: list[dict]) -> str:
        path = self.tmp / "s1.json"
        path.write_text(json.dumps(declarations, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_e2e_rejected_exit_nonzero_and_manifest(self):
        """端到端：S1 拒绝 → 退出码非 0 + manifest.s1_validation[] 含拒绝记录。"""
        s1 = self.write_s1([decl(id="E2E-1", purpose="implementation_basis", s3_risk_labeled=True)])
        rc, out, err = run_preflight_with_s1(self.task_dir, self.repo, self.base, self.head, s1)
        self.assertNotEqual(rc, 0)
        self.assertIn(S1_IMPLEMENTATION_REJECTED, err)
        self.assertIn("S1 不得作为实施依据", err)
        packs = list((self.task_dir / ".execution" / "TASK-C5-TEST" / "tp-development-engineering" / "review").glob("*.json"))
        self.assertEqual(len(packs), 1)
        manifest = json.loads(packs[0].read_text(encoding="utf-8"))
        self.assertIn("s1_validation", manifest)
        self.assertEqual(manifest["s1_validation"][0]["declaration_id"], "E2E-1")
        self.assertEqual(manifest["s1_validation"][0]["decision"], "rejected")
        self.assertEqual(manifest["s1_validation"][0]["errors"], [S1_IMPLEMENTATION_REJECTED])

    def test_e2e_requires_label_not_blocking(self):
        """端到端：R4 requires_label 不阻断（exit 0）+ manifest 记录。"""
        s1 = self.write_s1([decl(id="E2E-2", purpose="design_reference", s3_risk_labeled=False)])
        rc, out, err = run_preflight_with_s1(self.task_dir, self.repo, self.base, self.head, s1)
        self.assertEqual(rc, 0, err)
        packs = list((self.task_dir / ".execution" / "TASK-C5-TEST" / "tp-development-engineering" / "review").glob("*.json"))
        manifest = json.loads(packs[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["s1_validation"][0]["decision"], "requires_label")
        self.assertEqual(manifest["s1_validation"][0]["errors"], [S1_NO_S3_RISK_LABEL])

    def test_e2e_s2_accepted(self):
        """端到端：S2 可回链 → accepted，exit 0。"""
        s1 = self.write_s1([decl(id="E2E-3", evidence_level="S2", purpose="design_reference", source="src/main.py:42")])
        rc, out, err = run_preflight_with_s1(self.task_dir, self.repo, self.base, self.head, s1)
        self.assertEqual(rc, 0, err)
        packs = list((self.task_dir / ".execution" / "TASK-C5-TEST" / "tp-development-engineering" / "review").glob("*.json"))
        manifest = json.loads(packs[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["s1_validation"][0]["decision"], "accepted")
        self.assertEqual(manifest["s1_validation"][0]["errors"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
