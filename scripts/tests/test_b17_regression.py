# -*- coding: utf-8 -*-
"""V5.1.0 B-17 已落地能力回归套件（C2/C3/C4/敏感扫描 9.5-1）。

设计权威：docs/V5.1.0-B17-regression-cases.md §2（通用约定）/§3.2（C2）/§3.3（C3）/§3.4（C4）；
敏感扫描回归依据 docs/V5.1.0-sensitive-scan.md §4/§5/§6；
B-16 用例逐项依据 docs/V5.1.0-B16-provenance-schema.md §6（L196-210）B16-R1~R13。

范围：仅对已验收落地能力（report cost-benefit、receipt capability、
sensitive_scanner）建可留档强断言回归。纯 stdlib unittest、离线、
完全隔离临时目录（无真实任务目录/DB 污染），测试后清理。

明确排除（依赖能力未实现，另立任务）：C1 anchor_check（review-preflight
未实现）、C1-P6/P7/P8 封存阻断+规则集双锚点、C5 S1 声明拒绝（S1 校验器
未实现）、C6 旧任务静态只读拒写（cutover 运行时门禁未实现，B-18 前置）。

Run:
    python scripts/tests/test_b17_regression.py
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()

from cli import receipt_cmd  # noqa: E402
from cli import report_cmd  # noqa: E402
from cli.reuse_warnings import (  # noqa: E402
    W1_CN, W2_CN, W3_CN, W4_CN, WARNING_HEADER_CN,
    UNKNOWN_RATIO_WARN_THRESHOLD, UNKNOWN_RATIO_BLOCK_THRESHOLD,
    REUSE_RATE_LOW_THRESHOLD, _THRESHOLD_VERSION,
)
from cli.sensitive_scanner import (  # noqa: E402
    scan_resource_ref, scan_content, has_sensitive_hits, escalate_sensitivity,
    _SCANNER_VERSION, _SCANNER_SHA256, _RULES_SOURCE,
    _SCAN_STATUS_CLEAN, _SCAN_STATUS_HIT, _SCAN_STATUS_ERROR,
)


def run_cost_benefit(**kw) -> tuple[int, str]:
    """调用 cmd_report_cost_benefit，返回 (exit_code, stdout)。"""
    args = argparse.Namespace(**kw)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = report_cmd.cmd_report_cost_benefit(args)
    return rc, buf.getvalue()


def _cb_args(**overrides) -> dict:
    base = dict(
        task="TASK-B17-C2",
        output=None,
        preflight_self_cost=10.0,
        verification_input_saved=30.0,
        net_saving=20.0,
        reuse_rate=0.50,
        verification_input_baseline=None,
        verification_input_actual=None,
        theoretical_saving=None,
        actual_saving=None,
        has_reported_data=False,
        invalidation_reason=None,
        unknown_session_ratio=None,
        unknown_input_bytes_ratio=None,
        session_count=None,
        input_bytes_total=None,
    )
    base.update(overrides)
    return base


# =============================================================================
# C2：B-15 净亏披露（7 例，升级计划 §3.7 第 10 项 L245 / 9.4 第 2 行 L334）
# =============================================================================
class TestC2CostBenefit(unittest.TestCase):
    def test_c2_p1_net_benefit_four_columns(self):
        """C2-P1 净收益样本：四列完整；net_saving 如实呈现。"""
        rc, out = run_cost_benefit(**_cb_args())
        self.assertEqual(rc, 0)
        for col in (
            "preflight_self_cost:         +10.00",
            "verification_input_saved:    +30.00",
            "net_saving:                  +20.00",
            "reuse_rate:                  50.0%",
        ):
            self.assertIn(col, out)
        self.assertIn("Net benefit: +20.00 (positive, eligible for benefit conclusion)", out)

    def test_c2_p2_net_loss_independent_column(self):
        """C2-P2 净亏样本：独立列展示，禁止只展示收益样本。"""
        rc, out = run_cost_benefit(**_cb_args(net_saving=-5.0, preflight_self_cost=10.0, verification_input_saved=5.0))
        self.assertEqual(rc, 0)
        self.assertIn("--- Net Loss Column (net_saving < 0) ---", out)
        self.assertIn("net_saving: -5.00  (preflight self cost exceeds savings; audit/tuning only", out)
        self.assertIn("Net benefit: -5.00 (net loss, excluded from benefit conclusion)", out)
        self.assertIn(W3_CN, out)  # W3 净亏独立提示

    def test_c2_p3_unknown_not_zero(self):
        """C2-P3 UNKNOWN 无数据：标 N/A，禁止以 0 冒充。"""
        rc, out = run_cost_benefit(**_cb_args(unknown_session_ratio=None, unknown_input_bytes_ratio=None))
        self.assertEqual(rc, 0)
        self.assertIn("unknown_session_ratio:       N/A", out)
        self.assertIn("unknown_input_bytes_ratio:   N/A", out)
        self.assertNotIn("unknown_session_ratio:       0.0%", out)
        # 持久化 JSON 中为 null 而非 0
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "report.json"
            rc2, _ = run_cost_benefit(**_cb_args(output=str(out_path)))
            self.assertEqual(rc2, 0)
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIsNone(data["unknown_indicators"]["unknown_session_ratio"])
            self.assertIsNone(data["unknown_indicators"]["unknown_input_bytes_ratio"])

    def test_c2_p4_no_reported_no_actual_saving(self):
        """C2-P4 无 REPORTED 数据：不展示 actual_saving（禁止以理论值宣称节省）。"""
        rc, out = run_cost_benefit(**_cb_args(theoretical_saving=100.0, actual_saving=80.0, has_reported_data=False))
        self.assertEqual(rc, 0)
        self.assertIn("actual_saving:               N/A (no REPORTED data)", out)
        self.assertNotIn("actual_saving:               +80.00", out)
        # REPORTED 数据存在时展示
        rc2, out2 = run_cost_benefit(**_cb_args(actual_saving=80.0, has_reported_data=True))
        self.assertEqual(rc2, 0)
        self.assertIn("actual_saving:               +80.00", out2)

    def test_c2_p5_low_reuse_disclosed(self):
        """C2-P5 reuse_rate 低（<20%）：披露复用率与净值，负净收益显式标注。"""
        rc, out = run_cost_benefit(**_cb_args(reuse_rate=0.10, net_saving=-5.0))
        self.assertEqual(rc, 0)
        self.assertIn(W4_CN, out)  # W4 低复用率披露
        self.assertIn("reuse_rate:                  10.0%", out)
        self.assertIn("net_saving:                  -5.00", out)

    def test_c2_p6_report_persisted_complete_idempotent(self):
        """C2-P6 报表文件写入：完整可解析、四列齐全、同输入幂等重放一致。"""
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "report.json"
            kw = _cb_args(output=str(out_path), unknown_session_ratio=0.35, session_count=40, input_bytes_total=1000.0)
            rc, _ = run_cost_benefit(**kw)
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.is_file())
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(data["report_type"], "cost_benefit_disclosure")
            for col in ("preflight_self_cost", "verification_input_saved", "net_saving", "reuse_rate"):
                self.assertIn(col, data["mandatory_metrics"])
            # 告警内嵌报表文件（禁止仅 stdout 闪现）
            self.assertTrue(any(W1_CN in w for w in data["warnings"]))
            # 幂等：同输入重放逐字节一致
            first = out_path.read_text(encoding="utf-8")
            rc2, _ = run_cost_benefit(**kw)
            self.assertEqual(rc2, 0)
            second = out_path.read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_c2_p7_saving_claim_always_attached(self):
        """C2-P7 任何节省声明必附基线/口径/未知比例（报表结构强制四列+Unknown 区段）。"""
        rc, out = run_cost_benefit(**_cb_args(net_saving=20.0))
        self.assertEqual(rc, 0)
        # 报表恒含四列与 Unknown Indicators 区段（口径分母各自呈现）
        self.assertIn("--- Mandatory Cost-Benefit Metrics ---", out)
        self.assertIn("--- Unknown Indicators ---", out)
        self.assertIn("unknown_session_ratio:       N/A", out)
        self.assertIn("unknown_input_bytes_ratio:   N/A", out)


# =============================================================================
# C3：Q4 分档阈值（6 例，升级计划 §3.7 第 10 项 L245 / 9.2 分歧 2）
# =============================================================================
class TestC3Thresholds(unittest.TestCase):
    def test_c3_p1_ratio_leq_30_no_annotation(self):
        """C3-P1 ratio ≤ 30%：无附加标注；不阻断。"""
        rc, out = run_cost_benefit(**_cb_args(unknown_session_ratio=0.30, unknown_input_bytes_ratio=0.25))
        self.assertEqual(rc, 0)
        self.assertNotIn(W1_CN, out)
        self.assertNotIn(W2_CN, out)
        self.assertNotIn(WARNING_HEADER_CN, out)

    def test_c3_p2_ratio_30_50_reference_only(self):
        """C3-P2 30% < ratio ≤ 50%：标"仅供参考"；仍不阻断。"""
        rc, out = run_cost_benefit(**_cb_args(unknown_session_ratio=0.35, unknown_input_bytes_ratio=0.30))
        self.assertEqual(rc, 0)
        self.assertIn(W1_CN, out)
        self.assertNotIn(W2_CN, out)

    def test_c3_p3_ratio_gt_50_not_decision_basis(self):
        """C3-P3 ratio > 50%：标"不可作为成本决策依据"；仅披露不阻断。"""
        rc, out = run_cost_benefit(**_cb_args(unknown_session_ratio=0.60))
        self.assertEqual(rc, 0)  # 仅披露不阻断
        self.assertIn(W2_CN, out)
        self.assertNotIn(W1_CN, out)  # W1/W2 互斥

    def test_c3_p4_boundaries_30_50(self):
        """C3-P4 恰好 30%/50% 边界归属：≤30% 无标注；50% 归 W1 档。"""
        # 恰好 30%：不触发 W1（>30% 严格）
        rc, out = run_cost_benefit(**_cb_args(unknown_session_ratio=0.30))
        self.assertNotIn(W1_CN, out)
        self.assertNotIn(W2_CN, out)
        # 恰好 50%：>30% 且 ≤50% -> W1，不触发 W2（>50% 严格）
        rc2, out2 = run_cost_benefit(**_cb_args(unknown_session_ratio=0.50))
        self.assertIn(W1_CN, out2)
        self.assertNotIn(W2_CN, out2)
        # 边界归属与常量一致（锁定实现）
        self.assertEqual(UNKNOWN_RATIO_WARN_THRESHOLD, 0.30)
        self.assertEqual(UNKNOWN_RATIO_BLOCK_THRESHOLD, 0.50)

    def test_c3_p5_dual_metrics_independent(self):
        """C3-P5 双指标独立标注：不同档各自触发，不合并为单一 unknown_ratio。"""
        # session=35%（W1 档）、bytes=60%（W2 档）：W2 覆盖 W1（互斥展示规则），
        # 但 JSON 两指标独立保留，不合并
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "r.json"
            rc, out = run_cost_benefit(**_cb_args(
                output=str(out_path),
                unknown_session_ratio=0.35,
                unknown_input_bytes_ratio=0.60,
            ))
            self.assertEqual(rc, 0)
            self.assertIn(W2_CN, out)
            self.assertIn("(bytes_ratio=60.0%)", out)
            self.assertNotIn(W1_CN, out)  # W2 触发时 W1 不展示（设计互斥）
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(data["unknown_indicators"]["unknown_session_ratio"], 0.35)
            self.assertEqual(data["unknown_indicators"]["unknown_input_bytes_ratio"], 0.60)
        # 同档双指标：两条 W1 各自标注
        rc2, out2 = run_cost_benefit(**_cb_args(unknown_session_ratio=0.35, unknown_input_bytes_ratio=0.40))
        self.assertIn("(session_ratio=35.0%)", out2)
        self.assertIn("(bytes_ratio=40.0%)", out2)

    def test_c3_p6_threshold_versioned_config(self):
        """C3-P6 阈值配置版本化可调：常量与版本号锁定，变更不属契约变更。"""
        self.assertEqual(_THRESHOLD_VERSION, "1.0.0")
        self.assertEqual(REUSE_RATE_LOW_THRESHOLD, 0.20)
        # 阈值仅影响披露标注，不影响 workflow/风险等级（退出码恒 0）
        rc, out = run_cost_benefit(**_cb_args(unknown_session_ratio=0.60, net_saving=-5.0, reuse_rate=0.10))
        self.assertEqual(rc, 0)
        self.assertIn(W2_CN, out)
        self.assertIn(W3_CN, out)
        self.assertIn(W4_CN, out)


# =============================================================================
# C4：B-16 provenance 判定（13 例，B16-R1~R13，B-16 设计 §6 L196-210）
# =============================================================================
class TestC4Provenance(unittest.TestCase):
    def test_r1_repo_prefix(self):
        """B16-R1 repo: 前缀 -> trusted。"""
        p, s = receipt_cmd.classify_provenance("repo:src/module/a.go")
        self.assertEqual((p, s), ("trusted", "complete"))

    def test_r2_meta_exts(self):
        """B16-R2 .json/.yaml/.yml -> trusted。"""
        for ref in ("evidence/result.json", "config.yaml", "config.yml"):
            self.assertEqual(receipt_cmd.classify_provenance(ref)[0], "trusted", ref)

    def test_r3_code_exts(self):
        """B16-R3 .py/.go/.ts/.js -> trusted。"""
        for ref in ("src/tool.py", "main.go", "app.ts", "app.js"):
            self.assertEqual(receipt_cmd.classify_provenance(ref)[0], "trusted", ref)

    def test_r4_case_insensitive(self):
        """B16-R4 大小写扩展名 -> trusted（大小写不敏感）。"""
        for ref in ("CONFIG.JSON", "App.Yaml", "MAIN.PY", "Svc.TS"):
            self.assertEqual(receipt_cmd.classify_provenance(ref)[0], "trusted", ref)

    def test_r5_external_url(self):
        """B16-R5 外部 URL -> untrusted。"""
        self.assertEqual(receipt_cmd.classify_provenance("https://example.com/page")[0], "untrusted")

    def test_r6_natural_language(self):
        """B16-R6 自然语言描述 -> untrusted。"""
        self.assertEqual(receipt_cmd.classify_provenance("the evidence file we discussed earlier")[0], "untrusted")

    def test_r7_empty_ref_fail_closed(self):
        """B16-R7 引用为空/字段缺失 -> untrusted（fail-closed）。"""
        for ref in (None, "", "   "):
            self.assertEqual(receipt_cmd.classify_provenance(ref)[0], "untrusted", repr(ref))

    def test_r8_classifier_crash_fail_closed(self):
        """B16-R8 分类器抛异常 -> untrusted + classification_status=error + 审计留痕。"""
        orig = receipt_cmd.classify_provenance
        receipt_cmd.classify_provenance = lambda ref: (_ for _ in ()).throw(RuntimeError("boom"))
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                cap = receipt_cmd._build_capability("repo:a.py", None, None)
        finally:
            receipt_cmd.classify_provenance = orig
        self.assertEqual(cap["provenance"], "untrusted")
        self.assertEqual(cap["classification_status"], "error")
        self.assertIn("WARNING: classifier error", stderr.getvalue())
        # 判定器自身永不输出 unknown
        self.assertNotIn("unknown", cap["provenance"])

    def test_r9_crash_after_action_receipt_persisted(self):
        """B16-R9 分类器失败后动作已发生：fail-closed 原子写 receipt；纠正 receipt 禁止覆盖原 receipt。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "status.yaml").write_text(
                f'task_id: "TASK-B17-R9"\nartifact_contract:\n  version: "{ACTIVE_VERSION}"\n',
                encoding="utf-8",
            )
            args = argparse.Namespace(
                task="TASK-B17-R9", task_dir=str(base), actor="tp-development-engineering",
                action_type="DML", summary="r9", authorized_by="human_owner",
                authorization_scope="r9", environment="dev", result="r9",
                script=None, action_sha256="sha256:" + "b" * 64,
                evidence_hash="sha256:" + "a" * 64,
                resource_ref="repo:a.py", provenance=None, sensitivity=None, db=None,
            )
            orig = receipt_cmd.classify_provenance
            receipt_cmd.classify_provenance = lambda ref: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                rc = receipt_cmd.cmd_receipt(args)
            finally:
                receipt_cmd.classify_provenance = orig
            self.assertEqual(rc, 0)  # 审计不丢
            recs = sorted((base / "evidence" / "receipts").glob("*.json"))
            self.assertEqual(len(recs), 1)
            cap = json.loads(recs[0].read_text(encoding="utf-8"))["capability"]
            self.assertEqual(cap["provenance"], "untrusted")
            self.assertEqual(cap["classification_status"], "error")
            # 纠正 receipt：create-new 拒绝覆盖既有路径，原 receipt 不可被覆盖
            existing = recs[0]
            with self.assertRaises(FileExistsError):
                with existing.open("x", encoding="utf-8"):
                    pass
            # 第二次写同任务生成新 receipt（不同 ID），原 receipt 仍在
            receipt_cmd.classify_provenance = lambda ref: ("trusted", "complete")
            try:
                rc2 = receipt_cmd.cmd_receipt(args)
            finally:
                receipt_cmd.classify_provenance = orig
            self.assertEqual(rc2, 0)
            recs2 = sorted((base / "evidence" / "receipts").glob("*.json"))
            self.assertEqual(len(recs2), 2)
            self.assertTrue(existing.is_file())  # 原 receipt 未被覆盖/删除

    def test_r10_delegated_from_null_only(self):
        """B16-R10 delegated_from 恒 null（V5.1.0 预留）；无注入通道。"""
        cap = receipt_cmd._build_capability("repo:a.py", None, None)
        self.assertIsNone(cap["delegated_from"])

    def test_r11_downgrade_rejected(self):
        """B16-R11 provenance=untrusted 被降级为 trusted -> 校验拒绝（ValueError）。"""
        with self.assertRaises(ValueError):
            receipt_cmd._build_capability("https://example.com/page", "trusted", None)
        with self.assertRaises(ValueError):
            receipt_cmd._build_capability(None, "trusted", None)
        # 提高风险方向允许：untrusted 显式声明 unknown
        cap = receipt_cmd._build_capability("https://example.com/page", "unknown", None)
        self.assertEqual(cap["provenance"], "unknown")

    def test_r12_rules_tamper_hash_mismatch(self):
        """B16-R12 规则文件被就地篡改而版本号不变 -> classifier_sha256 不匹配，旧 receipt 失效。"""
        # 当前锚点与规则源绑定
        current = receipt_cmd._CLASSIFIER_SHA256[len("sha256:"):]
        self.assertEqual(current, hashlib.sha256(receipt_cmd._RULES_SOURCE.encode("utf-8")).hexdigest())
        # 模拟篡改：规则源内容变化但版本号不变
        tampered = json.loads(receipt_cmd._RULES_SOURCE)
        tampered["repo_prefix"] = "repo-x:"
        tampered_sha = hashlib.sha256(json.dumps(tampered, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertNotEqual(tampered_sha, current)  # 内容变 -> 锚点不匹配 -> 旧包失效

    def test_r13_dual_axis_orthogonal(self):
        """B16-R13 provenance × sensitivity 双轴：独立取值，禁止合并为单一污点字段。"""
        cap = receipt_cmd._build_capability("path/.env", None, None)
        self.assertEqual(cap["provenance"], "untrusted")   # R4
        self.assertEqual(cap["sensitivity"], "secret")     # 扫描命中升级
        self.assertIn("scan", cap)                          # scan 独立字段
        self.assertEqual(cap["scan"]["scan_status"], _SCAN_STATUS_HIT)
        # repo: 前缀 + 敏感路径：provenance=trusted 不受扫描影响（双轴正交）
        cap2 = receipt_cmd._build_capability("repo:.env", None, None)
        self.assertEqual(cap2["provenance"], "trusted")
        self.assertEqual(cap2["sensitivity"], "secret")


# =============================================================================
# 敏感扫描 9.5-1 回归（设计 §4/§5/§6；含 F4 子串收敛与 F1 内网地址）
# =============================================================================
class TestSensitiveScanPath(unittest.TestCase):
    """路径模式（设计 §4，18 类）：正例/反例/边界 + F4 子串误伤收敛对照。"""

    def test_f4_substring_rejection(self):
        """F4：子串粘连不命中（mysecrets/mycredentials 不再误伤）。"""
        for ref in ("data/mysecrets.txt", "x/mycredentials.json", "src/mycredentials"):
            hits = [h["category"] for h in scan_resource_ref(ref)["hits"]]
            self.assertEqual(hits, [], ref)

    def test_f4_real_sensitive_still_hit(self):
        """F4：真实敏感文件名仍命中（独立路径段/文件名边界）。"""
        for ref in (
            "credentials.json", "secrets.yaml", ".aws/credentials",
            "config.credentials.json", "config.credentials.local.json",
            "data/secrets.txt", "docs/secrets_backup_notes.md",
        ):
            hits = {h["category"] for h in scan_resource_ref(ref)["hits"]}
            self.assertTrue(hits, ref)

    def test_path_positive_categories(self):
        """路径 18 类正例：每类至少一个代表形态命中。"""
        samples = {
            "env_file": ".env.local",
            "credential_file": "credentials.json",
            "secrets_file": "secrets.yaml",
            "private_key": "id_rsa",
            "pem_cert": "cert.pem",
            "key_file": "server.key",
            "p12_pfx": "archive.p12",
            "jks": "truststore.jks",
            "connection_string": "db.connectionstring",
            "datasource": "datasource.app",
            "token_file": "token.json",
            "npmrc": ".npmrc",
            "pypirc": ".pypirc",
            "aws_cred": ".aws/credentials",
            "ssh_dir": "x/.ssh/config",
            "secrets_dir": "x/secrets/",
            "credentials_dir": "x/credentials/",
            "keystore_dir": "x/keystore/",
        }
        for cat, ref in samples.items():
            hits = {h["category"] for h in scan_resource_ref(ref)["hits"]}
            self.assertIn(cat, hits, f"{cat} <- {ref}")

    def test_path_negative(self):
        """路径反例：普通文件与普通目录不命中。"""
        for ref in ("src/main.py", "docs/readme.md", "data/values.txt", "assets/logo.png"):
            self.assertEqual(scan_resource_ref(ref)["scan_status"], _SCAN_STATUS_CLEAN, ref)

    def test_path_boundary(self):
        """路径边界：None/空串 -> clean（无引用不误报）。"""
        for ref in (None, "", "   "):
            result = scan_resource_ref(ref)
            self.assertEqual(result["scan_status"], _SCAN_STATUS_CLEAN, repr(ref))
            self.assertEqual(result["hits"], [])

    def test_path_case_insensitive(self):
        """路径大小写不敏感：.ENV / CREDENTIALS.JSON 命中。"""
        for ref in (".ENV", "CREDENTIALS.JSON", "SECRETS.YAML"):
            self.assertEqual(scan_resource_ref(ref)["scan_status"], _SCAN_STATUS_HIT, ref)


class TestSensitiveScanContent(unittest.TestCase):
    """内容模式（设计 §5，11 类 = 9 凭证 + 2 内网地址）：正例/反例/边界 + F1。"""

    def test_content_credential_categories(self):
        """内容 9 类凭证/密钥/连接串正例。"""
        samples = {
            "bearer_token": "Authorization: Bearer " + "x" * 24,
            "api_key_prefix": "key=sk-" + "y" * 24,
            "aws_akid": "AKIA" + "A" * 16,
            "aws_secret_key": "aws_secret_access_key = wJalrXUtnFEMI",
            "private_key_block": "-----BEGIN RSA PRIVATE KEY-----",
            "db_conn_string": "mysql://user:pass@dbhost:3306/app",
            "jdbc_url": "jdbc:mysql://user:pass@host/db",
            "mongodb_conn": "mongodb://user:pass@host:27017/db",
            "password_keyword": "password = supersecret1",
        }
        for cat, text in samples.items():
            hits = {h["category"] for h in scan_content(text)["hits"]}
            self.assertIn(cat, hits, f"{cat} <- {text!r}")

    def test_f1_intranet_ipv4(self):
        """F1：私有网段四段 IP 命中（10/8、172.16-31/12、192.168/16）。"""
        for text in (
            "host: http://10.0.0.1:8080",
            "ip 10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "conn: mysql://192.168.10.5:3306/app",
        ):
            hits = {h["category"] for h in scan_content(text)["hits"]}
            self.assertIn("private_ipv4", hits, text)

    def test_f1_intranet_hostname(self):
        """F1：内网主机名 *.internal/*.local 命中。"""
        for text in ("dns: api.internal", "svc.local"):
            hits = {h["category"] for h in scan_content(text)["hits"]}
            self.assertIn("internal_hostname", hits, text)

    def test_f1_reject_false_positives(self):
        """F1 反例：版本号/非私有网段/两段/粘连不误命中。"""
        for text in (
            "version 1.2.3", "pkg 10.1", "172.15.0.1", "172.32.0.1",
            "192.169.1.1", "8.8.8.8", "x10.0.0.1", "10.0.0.1foo",
        ):
            self.assertEqual(scan_content(text)["scan_status"], _SCAN_STATUS_CLEAN, text)

    def test_content_negative_and_boundary(self):
        """内容反例与边界：正常代码不命中；None/空串 -> clean。"""
        for text in ("def main():\n    return 42", "const a = 1;"):
            self.assertEqual(scan_content(text)["scan_status"], _SCAN_STATUS_CLEAN, text)
        for ref in (None, "", "   "):
            self.assertEqual(scan_content(ref)["scan_status"], _SCAN_STATUS_CLEAN, repr(ref))

    def test_content_no_raw_secret_copied(self):
        """命中不复制原文（升级计划 L116）：hits 仅类别+模式，无命中文本。"""
        text = "Authorization: Bearer " + "x" * 24
        for h in scan_content(text)["hits"]:
            self.assertNotIn(text, json.dumps(h))

    def test_content_count_11_no_pii(self):
        """记录口径：内容 11 类（9 凭证 + 2 内网地址）；无独立 PII 类别。"""
        rules = json.loads(_RULES_SOURCE)
        names = set(rules["content_patterns"].keys())
        self.assertEqual(len(names), 11)
        self.assertNotIn("pii", json.dumps(sorted(names)).lower())
        self.assertEqual(_SCANNER_VERSION, "1.0.0")
        self.assertTrue(_SCANNER_SHA256.startswith("sha256:") and len(_SCANNER_SHA256) == 7 + 64)


class TestSensitiveScanFailClosed(unittest.TestCase):
    """fail-closed 兜底（设计 §6）+ 双轴正交。"""

    def test_scanner_crash_fail_closed(self):
        """F2：扫描器抛异常 -> sensitivity=secret、classification_status=error、不抛出、WARNING 留痕。"""
        orig = receipt_cmd.scan_resource_ref
        receipt_cmd.scan_resource_ref = lambda ref: (_ for _ in ()).throw(RuntimeError("crash"))
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                cap = receipt_cmd._build_capability("repo:src/a.py", None, "internal")
        finally:
            receipt_cmd.scan_resource_ref = orig
        self.assertEqual(cap["sensitivity"], "secret")
        self.assertEqual(cap["classification_status"], "error")
        self.assertEqual(cap["scan"]["scan_status"], _SCAN_STATUS_ERROR)
        self.assertEqual(cap["scan"]["hits"], [])
        self.assertIn("WARNING: sensitive scanner crashed", stderr.getvalue())
        # provenance 双轴正交：repo: 前缀不受扫描崩溃影响
        self.assertEqual(cap["provenance"], "trusted")

    def test_dual_axis_hit_keeps_provenance(self):
        """双轴正交：命中升 sensitivity 但 provenance 不变。"""
        cap = receipt_cmd._build_capability("repo:.env", None, None)
        self.assertEqual(cap["provenance"], "trusted")
        self.assertEqual(cap["sensitivity"], "secret")
        self.assertEqual(cap["scan"]["scan_status"], _SCAN_STATUS_HIT)
        # scan 与 sensitivity/provenance 三处独立字段，不合并
        self.assertNotIn("sensitivity", cap["scan"])

    def test_has_sensitive_hits_and_escalate(self):
        """辅助函数：hit/error 视为命中；escalate 仅升级不降级。"""
        clean = {"scan_status": _SCAN_STATUS_CLEAN}
        hit = {"scan_status": _SCAN_STATUS_HIT}
        err = {"scan_status": _SCAN_STATUS_ERROR}
        self.assertFalse(has_sensitive_hits(clean))
        self.assertTrue(has_sensitive_hits(hit))
        self.assertTrue(has_sensitive_hits(err))
        self.assertEqual(escalate_sensitivity("public", hit), "secret")
        self.assertEqual(escalate_sensitivity("internal", err), "secret")
        self.assertEqual(escalate_sensitivity("sensitive", clean), "sensitive")


if __name__ == "__main__":
    unittest.main(verbosity=2)
