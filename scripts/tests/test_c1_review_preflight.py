# -*- coding: utf-8 -*-
"""V5.1.0 C1 review-preflight 回归套件（B-17 C1-P1~P9 强断言）。

设计权威：docs/V5.1.0-C1-review-preflight-design.md §3-§7；
对齐 B-17 设计 §3.1（C1-P1~P9，L69-77）与通用约定 §2
（每用例正例+反例；强断言退出码 + STDERR 错误码逐字节 + 状态终值 + 副作用文件/hash；
完全隔离临时目录 + 受控 fixture git 仓库；测试后清理；失败即 FAIL）。

纯 stdlib unittest、离线；fixture 仓库在临时目录内创建（git init + 本地 commit，
命令级 -c user 配置，不触碰任何全局/仓库 git config 文件）。

Run:
    python scripts/tests/test_c1_review_preflight.py
"""

from __future__ import annotations

import hashlib
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

from cli import anchor_check  # noqa: E402
from cli.review_preflight import (  # noqa: E402
    cmd_review_preflight, RISK_RULES_VERSION, RISK_RULES_SHA256,
    RULES_HASH_MISMATCH, SENSITIVE_REFERENCE_ONLY,
    PREFLIGHT_INPUT_INVALID, PREFLIGHT_CONTRACT_MISMATCH,
)
from cli.anchor_check import (  # noqa: E402
    ANCHOR_TEXT_NOT_FOUND, ANCHOR_LINE_RANGE_INVALID,
    ANCHOR_HASH_MISMATCH, ANCHOR_OFFSET_UNDETERMINED,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )


def _git_ok(repo: Path, *args: str) -> str:
    proc = _git(repo, *args)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def make_fixture_repo(tmp: Path, extra_head_files: dict[str, str] | None = None, name: str = "repo") -> tuple[Path, str, str]:
    """受控 fixture git 仓库：base commit + head commit（稳定 SHA 可复现）。"""
    repo = tmp / name
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    (repo / "src.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git_ok(repo, "add", ".")
    _git_ok(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    base = _git_ok(repo, "rev-parse", "HEAD")
    (repo / "src.py").write_text("def main():\n    return 43  # changed\n", encoding="utf-8")
    (repo / "app.py").write_text("import src\n", encoding="utf-8")
    for name, content in (extra_head_files or {}).items():
        (repo / name).write_text(content, encoding="utf-8")
    _git_ok(repo, "add", ".")
    _git_ok(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "head")
    head = _git_ok(repo, "rev-parse", "HEAD")
    return repo, base, head


SRC_HEAD = "def main():\n    return 43  # changed\n"
SRC_HEAD_SHA = "sha256:" + hashlib.sha256(SRC_HEAD.encode("utf-8")).hexdigest()


def make_task_dir(tmp: Path) -> Path:
    task_dir = tmp / "task"
    task_dir.mkdir()
    (task_dir / "status.yaml").write_text(
        f'task_id: "TASK-C1-TEST"\nartifact_contract:\n  version: "{ACTIVE_VERSION}"\n',
        encoding="utf-8",
    )
    return task_dir


def write_findings(tmp: Path, findings: list[dict]) -> str:
    path = tmp / "findings.json"
    path.write_text(json.dumps(findings, ensure_ascii=False), encoding="utf-8")
    return str(path)


def run_preflight(task_dir: Path, repo: Path, base: str, head: str, **overrides) -> tuple[int, str, str]:
    import io
    import contextlib
    import argparse
    base_args = dict(
        task="TASK-C1-TEST", task_dir=str(task_dir), repo=str(repo),
        base_sha=base, head_sha=head, findings_file=None, rules_file=None,
        phase_exit=False, simulate=False, db=None,
    )
    base_args.update(overrides)
    args = argparse.Namespace(**base_args)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cmd_review_preflight(args)
        except ValueError as exc:
            err.write(f"ValueError: {exc}\n")
            rc = 1
    return rc, out.getvalue(), err.getvalue()


GOOD_FINDING = {
    "id": "F1",
    "file": "src.py",
    "text": "return 43  # changed",
    "line": 2,
    "evidence_hash": SRC_HEAD_SHA,
    "hunk_context": [" def main():", "+    return 43  # changed"],
}


class TestC1Preflight(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c1_preflight_")
        self.tmp = Path(self._tmp)
        self.repo, self.base, self.head = make_fixture_repo(self.tmp)
        self.task_dir = make_task_dir(self.tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- C1-P1：verified 全通过 ----
    def test_c1_p1_verified_exit0(self):
        findings = write_findings(self.tmp, [GOOD_FINDING])
        rc, out, err = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings)
        self.assertEqual(rc, 0, err)
        self.assertIn("preflight: ok", out)
        # 候选包原子写入 .execution/<TASK-ID>/tp-development-engineering/review/
        review_dir = self.task_dir / ".execution" / "TASK-C1-TEST" / "tp-development-engineering" / "review"
        packs = list(review_dir.glob("*.json"))
        self.assertEqual(len(packs), 1)
        manifest = json.loads(packs[0].read_text(encoding="utf-8"))
        # 无 finding 新增：anchor_check 数量 == 输入 findings 数量
        self.assertEqual(len(manifest["anchor_check"]), 1)
        self.assertEqual(manifest["anchor_check"][0]["anchor_status"], "verified")
        # 文件清单稳定排序：src.py 与 app.py 均在
        paths = [f["path"] for f in manifest["files"]]
        self.assertIn("app.py", paths)
        self.assertIn("src.py", paths)

    # ---- C1-P2：hash 不匹配 → unverified 保留 finding，退出码非 0 ----
    def test_c1_p2_hash_mismatch_unverified(self):
        bad = dict(GOOD_FINDING, evidence_hash="sha256:" + "0" * 64)
        findings = write_findings(self.tmp, [bad])
        rc, out, err = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings)
        self.assertNotEqual(rc, 0)
        self.assertIn(ANCHOR_HASH_MISMATCH, err)
        self.assertIn("1 finding(s) unverified", err)
        review_dir = self.task_dir / ".execution" / "TASK-C1-TEST" / "tp-development-engineering" / "review"
        packs = list(review_dir.glob("*.json"))
        self.assertEqual(len(packs), 1)
        manifest = json.loads(packs[0].read_text(encoding="utf-8"))
        anchors = manifest["anchor_check"]
        self.assertEqual(len(anchors), 1)  # finding 保留（不删除）
        self.assertEqual(anchors[0]["finding_id"], "F1")
        self.assertEqual(anchors[0]["anchor_status"], "unverified")

    # ---- C1-P3：行号越界 → unverified + 错误码 + 不崩溃 ----
    def test_c1_p3_line_range_invalid(self):
        for bad_line in (0, -1, 9999):
            bad = dict(GOOD_FINDING, line=bad_line)
            findings = write_findings(self.tmp, [bad])
            rc, out, err = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings)
            self.assertNotEqual(rc, 0)  # 不崩溃但预检未通过
            self.assertIn(ANCHOR_LINE_RANGE_INVALID, err)

    # ---- C1-P4：引用文本不存在 → unverified + finding 保留 ----
    def test_c1_p4_text_not_found(self):
        bad = dict(GOOD_FINDING, text="NO_SUCH_TEXT_IN_SOURCE_XYZ")
        findings = write_findings(self.tmp, [bad])
        rc, out, err = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings)
        self.assertNotEqual(rc, 0)
        self.assertIn(ANCHOR_TEXT_NOT_FOUND, err)
        review_dir = self.task_dir / ".execution" / "TASK-C1-TEST" / "tp-development-engineering" / "review"
        manifest = json.loads(list(review_dir.glob("*.json"))[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["anchor_check"][0]["anchor_status"], "unverified")

    # ---- C1-P5：稳定重放（两次运行逐字节一致）----
    def test_c1_p5_stable_replay(self):
        findings = write_findings(self.tmp, [GOOD_FINDING])
        rc1, out1, _ = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings)
        self.assertEqual(rc1, 0)
        packs1 = list((self.task_dir / ".execution" / "TASK-C1-TEST" / "tp-development-engineering" / "review").glob("*.json"))
        content1 = packs1[0].read_bytes()
        # 清空候选区后重跑（同一输入）
        shutil.rmtree(self.task_dir / ".execution")
        rc2, out2, _ = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings)
        self.assertEqual(rc2, 0)
        packs2 = list((self.task_dir / ".execution" / "TASK-C1-TEST" / "tp-development-engineering" / "review").glob("*.json"))
        self.assertEqual(content1, packs2[0].read_bytes())  # 逐字节一致
        self.assertEqual(out1, out2)
        # 偏移修正值确定性输出（供 tp-verification-engineering 消费）
        manifest = json.loads(packs2[0].read_text(encoding="utf-8"))
        self.assertIsNotNone(manifest["anchor_check"][0]["offset_correction"])

    # ---- C1-P6：规则文件篡改而版本号不变 → RULES_HASH_MISMATCH ----
    def test_c1_p6_rules_tamper_mismatch(self):
        rules_path = self.tmp / "rules.json"
        rules_path.write_text(
            json.dumps({"version": RISK_RULES_VERSION, "rules": {"permission_change": "TAMPERED"}}),
            encoding="utf-8",
        )
        findings = write_findings(self.tmp, [GOOD_FINDING])
        rc, out, err = run_preflight(
            self.task_dir, self.repo, self.base, self.head,
            findings_file=findings, rules_file=str(rules_path),
        )
        self.assertNotEqual(rc, 0)
        self.assertIn(RULES_HASH_MISMATCH, err)
        # 双锚点绑定：当前规则源 hash 与内容一致；内容变则失配
        self.assertTrue(RISK_RULES_SHA256.startswith("sha256:"))

    # ---- C1-P7：diff 含敏感路径 → 封存阻断 + SENSITIVE_REFERENCE_ONLY + 无原文 ----
    def test_c1_p7_sensitive_seal_blocked(self):
        repo, base, head = make_fixture_repo(self.tmp, extra_head_files={".env": "TOKEN=supersecret\n"}, name="repo_sensitive")
        findings = write_findings(self.tmp, [GOOD_FINDING])
        rc, out, err = run_preflight(self.task_dir, repo, base, head, findings_file=findings, phase_exit=True)
        self.assertNotEqual(rc, 0)
        self.assertIn(SENSITIVE_REFERENCE_ONLY, err)
        seal_base = self.task_dir / "evidence" / "review-packages"
        rejected = list(seal_base.glob("REJECTED-*.json"))
        self.assertEqual(len(rejected), 1)
        record = json.loads(rejected[0].read_text(encoding="utf-8"))
        self.assertEqual(record["status"], SENSITIVE_REFERENCE_ONLY)
        path_hits = [h for h in record["hits"] if h["kind"] == "path"]
        self.assertTrue(any(h["source"] == ".env" for h in path_hits))
        # 不复制原文：REJECTED 记录与封存区均不含敏感原文
        self.assertNotIn("supersecret", rejected[0].read_text(encoding="utf-8"))
        self.assertFalse(any(p.name == "manifest.json" for p in seal_base.rglob("manifest.json")))
        # 命中文件 hash 已记录（源位置 + hash）
        self.assertTrue(all(h["sha256"] for h in path_hits))

    # ---- C1-P8：同 hash 重复封存幂等 + 无半成品 ----
    def test_c1_p8_idempotent_seal(self):
        findings = write_findings(self.tmp, [GOOD_FINDING])
        rc1, out1, err1 = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings, phase_exit=True)
        self.assertEqual(rc1, 0, err1)
        seal_base = self.task_dir / "evidence" / "review-packages"
        manifests1 = list(seal_base.rglob("manifest.json"))
        self.assertEqual(len(manifests1), 1)
        # 重复封存同 hash：幂等返回 exit 0，不重复写入
        rc2, out2, err2 = run_preflight(self.task_dir, self.repo, self.base, self.head, findings_file=findings, phase_exit=True)
        self.assertEqual(rc2, 0, err2)
        manifests2 = list(seal_base.rglob("manifest.json"))
        self.assertEqual(len(manifests2), 1)
        # 无半成品：无 .tmp 残留
        self.assertEqual(list(seal_base.rglob("*.tmp")), [])
        # 自引用字段齐全（实现内 readback 已保证文件字节与写前一致，否则 ValueError）
        manifest = json.loads(manifests2[0].read_text(encoding="utf-8"))
        self.assertIn("content_hash", manifest)
        self.assertIn("package_hash", manifest)
        self.assertTrue(manifest["package_hash"].startswith("sha256:"))

    # ---- C1-P9：--simulate 零写入 ----
    def test_c1_p9_simulate_zero_write(self):
        findings = write_findings(self.tmp, [GOOD_FINDING])
        rc, out, err = run_preflight(
            self.task_dir, self.repo, self.base, self.head,
            findings_file=findings, simulate=True, phase_exit=True,
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("PREFLIGHT SIMULATE (zero-write)", out)
        self.assertIn("would-write", out)
        self.assertIn("would-seal", out)
        # 零写入：.execution 与 evidence 均不存在
        self.assertFalse((self.task_dir / ".execution").exists())
        self.assertFalse((self.task_dir / "evidence").exists())

    # ---- 附加：输入校验（contract 不匹配 / SHA 无效）----
    def test_input_validation(self):
        # contract 不匹配 → PREFLIGHT_CONTRACT_MISMATCH
        task_dir = self.tmp / "task_bad"
        task_dir.mkdir()
        (task_dir / "status.yaml").write_text(
            'task_id: "TASK-C1-TEST"\nartifact_contract:\n  version: "9.9.9"\n',
            encoding="utf-8",
        )
        rc, out, err = run_preflight(task_dir, self.repo, self.base, self.head)
        self.assertNotEqual(rc, 0)
        self.assertIn(PREFLIGHT_CONTRACT_MISMATCH, err)
        # 无效 SHA → PREFLIGHT_INPUT_INVALID
        rc2, out2, err2 = run_preflight(self.task_dir, self.repo, "DEADBEEF", self.head)
        self.assertNotEqual(rc2, 0)
        self.assertIn(PREFLIGHT_INPUT_INVALID, err2)


class TestAnchorCheckUnit(unittest.TestCase):
    """anchor_check 四项校验单元断言（含反例/边界）。"""

    def test_text_exists(self):
        content = "line1\nline2\n"
        self.assertTrue(anchor_check.check_text_exists(content, "line2"))
        self.assertFalse(anchor_check.check_text_exists(content, "line3"))
        self.assertFalse(anchor_check.check_text_exists(content, ""))

    def test_line_range(self):
        content = "a\nb\nc\n"
        self.assertTrue(anchor_check.check_line_range(content, 1))
        self.assertTrue(anchor_check.check_line_range(content, 3))
        self.assertFalse(anchor_check.check_line_range(content, 0))
        self.assertFalse(anchor_check.check_line_range(content, -1))
        self.assertFalse(anchor_check.check_line_range(content, 4))
        self.assertFalse(anchor_check.check_line_range(content, None))

    def test_hash_match(self):
        content = "abc"
        h = hashlib.sha256(b"abc").hexdigest()
        self.assertTrue(anchor_check.check_hash_matches(content, h))
        self.assertTrue(anchor_check.check_hash_matches(content, f"sha256:{h}"))
        self.assertFalse(anchor_check.check_hash_matches(content, "sha256:" + "0" * 64))
        self.assertFalse(anchor_check.check_hash_matches(content, None))
        self.assertFalse(anchor_check.check_hash_matches(content, "not-a-hash"))

    def test_offset_correction(self):
        content = "def main():\n    return 43  # changed\n"
        ctx = [" def main():", "+    return 43  # changed"]
        ok, line = anchor_check.compute_offset_correction(content, ctx)
        self.assertTrue(ok)
        self.assertEqual(line, 1)
        # 找不到 → False, None
        ok2, line2 = anchor_check.compute_offset_correction(content, ["+++ ghost line"])
        self.assertFalse(ok2)
        self.assertIsNone(line2)
        # None/空 → False
        self.assertFalse(anchor_check.compute_offset_correction(content, None)[0])

    def test_run_anchor_check_all_fail(self):
        result = anchor_check.run_anchor_check(
            {"id": "X", "file": "f.py", "text": "ghost", "line": 99, "evidence_hash": "bad", "hunk_context": None},
            "short",
        )
        self.assertEqual(result["anchor_status"], "unverified")
        self.assertEqual(
            set(result["errors"]),
            {ANCHOR_TEXT_NOT_FOUND, ANCHOR_LINE_RANGE_INVALID, ANCHOR_HASH_MISMATCH, ANCHOR_OFFSET_UNDETERMINED},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
