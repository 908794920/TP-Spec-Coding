# -*- coding: utf-8 -*-
"""V5.1.0 版本纯度测试：调用版本纯度扫描器并断言通过。

Pure stdlib unittest; offline. 验证当前工作区无旧版本 token 污染，
并覆盖扫描器漏检回归（前缀版本字面量、历史编码标识符、自身扫描）。

Run:
    python scripts/tests/test_v510_version_purity.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base


_SCANNER = BASE / "scripts" / "check_version_consistency.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("cvc", str(_SCANNER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scanner_ctx():
    """返回 (legacy_re, version, is_legacy_fn) 供断言使用。"""
    m = _load_scanner()
    version = (BASE / "VERSION").read_text(encoding="utf-8").strip()
    return m._build_legacy_re(version), version, m._is_legacy_dotted


def _is_legacy(sample: str) -> bool:
    """正则命中 + 数值判定（当前/未来版本放行）。"""
    legacy_re, version, is_legacy_fn = _scanner_ctx()
    m = legacy_re.search(sample)
    if not m:
        return False
    return is_legacy_fn(m.group(0), version)


class TestVersionPurity(unittest.TestCase):
    def test_scanner_passes(self):
        """check_version_consistency.py 必须退出 0（无旧版本 token）。"""
        proc = subprocess.run(
            [sys.executable, str(_SCANNER)],
            capture_output=True,
            text=True,
            cwd=str(BASE),
        )
        self.assertEqual(proc.returncode, 0, f"scanner failed:\n{proc.stdout}\n{proc.stderr}")

    def test_no_legacy_dirs(self):
        """目录纯度：templates/ 仅 5.1.3，无 cutover-snapshots。"""
        tpl = BASE / "templates"
        dirs = {p.name for p in tpl.iterdir() if p.is_dir()}
        self.assertEqual(dirs, {(BASE / "VERSION").read_text(encoding="utf-8").strip()})
        self.assertFalse((BASE / "cutover-snapshots").exists())

    # ---- 扫描器漏检回归（审计 P1-2）----

    def test_scanner_rejects_prefixed_dotted_version(self):
        """带 v/V 前缀的 dotted 旧版本必须被识别。"""
        # 拼接构造样本，避免测试文件自身被扫描器命中
        legacy506 = "5.0." + "6"
        legacy442 = "4.4." + "2"
        legacy441 = "4.4." + "1"
        for sample in ("v" + legacy506, "V" + legacy506, legacy506, "v" + legacy442, "V" + legacy441, legacy442):
            self.assertTrue(_is_legacy(sample), sample)

    def test_scanner_rejects_historical_identifier_with_suffix(self):
        """带语义后缀的历史编码标识符必须被识别。"""
        legacy503 = "v5" + "03"
        legacy502 = "V5" + "02"
        legacy441 = "v4" + "41"
        for sample in (
            "$" + legacy503 + "CompletionStates",
            "Get-" + legacy503.upper() + "GeneratedSources",
            "acceptance" + legacy502.upper() + "Path",
            "$" + legacy441 + "Artifacts",
            legacy503.upper(),
            legacy503,
            legacy502,
        ):
            self.assertTrue(_is_legacy(sample), sample)

    def test_scanner_rejects_previous_patch(self):
        """当前 5.1.3 时，前一修补版本（5.1.0）必须被识别为污染。"""
        prev = "5.1." + "0"
        for sample in ("V" + prev, prev, "v" + prev):
            self.assertTrue(_is_legacy(sample), sample)

    def test_scanner_allows_current_and_foreign_versions(self):
        """当前版本与独立命名空间版本不得误报。"""
        current = (BASE / "VERSION").read_text(encoding="utf-8").strip()
        foreign = "6.7." + "8"
        for sample in (
            "V" + current,
            current,
            "V" + foreign,
            foreign,
            "V510",
            "172.15.0.1",
            "manifest_version 1.0.0",
            "risk-rule 2.0.0",
            "Test-V510SingleContract.ps1",
        ):
            self.assertFalse(_is_legacy(sample), sample)

    def test_scanner_scans_its_own_source(self):
        """扫描器自身源码不得包含可命中的旧版本字面量（拼接声明）。"""
        import importlib.util as _iiu
        spec = _iiu.spec_from_file_location("cvc_scan", str(_SCANNER))
        mod = _iiu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        version = (BASE / "VERSION").read_text(encoding="utf-8").strip()
        legacy_re = mod._build_legacy_re(version)
        issues = mod.scan_file(_SCANNER, legacy_re, version)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
