# -*- coding: utf-8 -*-
"""V5.2.1 C1 review-preflight 审查预检（B-17 C1-P1~P9）。

设计依据：历史设计记录 C1-review-preflight-design §3-§7
证据锚点：升级计划 §3.1 L96-119；评审表 9.4 第 1 行（L333）、9.5 第 1/2/3 行（L346-348）。

能力（T1-T6）：
- T1 输入校验（仓库/base/head SHA/工作区 clean-dirty/任务声明 contract=5.2.1）
  + 受控 diff 枚举稳定排序（路径字典序 + 状态分组，两次运行逐字节一致）；
- T2 风险规则集（rules_version/rules_sha256 双锚点）+ 关联候选生成
  （algorithm/rationale/confidence/evidence_level，OCR README 归并仅 S1/S3 不作实现依据）；
- T4 包生成（稳定序列化 sort_keys=True + 预算分包确定性阈值 + package_hash 防逃逸）
  + 候选包原子写入 .execution/<TASK-ID>/tp-development-engineering/review/；
- T5 ``--phase-exit`` 为兼容参数名：只封存 review package，不推进 Task phase/state；复用 cli/sensitive_scanner.py 扫描 resource/content，
  命中→封存阻断 + 仅写 SENSITIVE_REFERENCE_ONLY+源位置+sha256（不复制原文）；
  所有写入 create-new（真实先例 receipt_cmd.py L227）或 temp+rename，禁止原地覆写；
  写后 readback 重算 hash 不一致则丢弃临时文件并失败；同 hash 幂等返回 exit 0；
- T6 --simulate 零写入：完整计算但所有写入替换为拟写清单，.execution/evidence/账本/投影零写入。

全程无模型/API/网络调用（工具无关委托）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import anchor_check
from .version import active_version
from .sensitive_scanner import scan_resource_ref, scan_content, has_sensitive_hits
from . import s1_validator
from . import structured_refs

# --- 版本常量 ---
_PREFLIGHT_VERSION = "1.0.0"
SUMMARY_FORMAT_VERSION = "1.0.0"  # 摘要格式版本：同步自 V5.2.1-B14-lossless-summary-design.md §2.1；
# 预算分包阈值语义与摘要三域（产物 schema/内容分类规则/sentinel 保护规则）语义均受该版本治理，
# 版本变更使旧 package 失效（§3.1 L119 防逃逸）；值仍为 1.0.0（B-14 复合版本当前值）

# 预算分包确定性默认值（纳入 summary_format_version 语义，不得随机/环境依赖）
BUDGET_MAX_FILES_PER_PACK = 200
BUDGET_MAX_BYTES_PER_PACK = 1_048_576  # 1 MiB

# --- 错误码枚举 ---
PREFLIGHT_INPUT_INVALID = "PREFLIGHT_INPUT_INVALID"
PREFLIGHT_REPO_INVALID = "PREFLIGHT_REPO_INVALID"
PREFLIGHT_CONTRACT_MISMATCH = "PREFLIGHT_CONTRACT_MISMATCH"
RULES_HASH_MISMATCH = "RULES_HASH_MISMATCH"
SENSITIVE_REFERENCE_ONLY = "SENSITIVE_REFERENCE_ONLY"

# --- 风险规则集（版本化 + 内容双锚点）---
RISK_RULES_VERSION = "1.0.0"
_RISK_RULES = {
    "permission_change": r"\b(?:chmod|chown|acl|umask|sudo|su)\b",
    "dml_ddl": r"\b(?:insert|update|delete|merge|create\s+table|alter\s+table|drop\s+table)\b",
    "transaction": r"\b(?:begin|commit|rollback)\b",
    "config_change": r"\.(?:yaml|yml|json|toml|ini|conf|config)$",
    "null_handling": r"\b(?:null|None)\b",
    "external_call": r"\b(?:requests\.|urllib\.|httpx\.|subprocess\.|socket\.)",
    "sensitive_path": r"\.env|credentials|secret|token|\.pem|\.key",
}
RISK_RULES_SHA256 = "sha256:" + hashlib.sha256(
    json.dumps(_RISK_RULES, sort_keys=True).encode("utf-8")
).hexdigest()

# --- 关联候选算法（版本化 + 内容双锚点）---
ALGORITHM_VERSION = "1.0.0"
_ALGORITHM_SOURCE = {
    "basename_test": "test_* / *_test.py / *.spec.* 同 basename 归并（S2）",
    "same_basename": "同 basename 不同扩展名（实现/配置/测试映射，S2）",
    "ocr_readme": "OCR README 智能归并仅为 S1/S3，不作实现依据（S1 声明拒绝）",
}
ALGORITHM_SHA256 = "sha256:" + hashlib.sha256(
    json.dumps(_ALGORITHM_SOURCE, sort_keys=True).encode("utf-8")
).hexdigest()


def _run_git(repo: Path, args: list[str]) -> tuple[int, str, str]:
    """本地只读 git 调用（工具无关委托：无网络、无模型、无 API Key）。"""
    proc = subprocess.run(
        ["git", "-C", str(repo)] + args,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _load_findings(findings_file: str | None) -> list[dict[str, Any]]:
    """读取 finding 列表（外部输入，如开发者工具产出）；缺省空列表。"""
    if not findings_file:
        return []
    path = Path(findings_file)
    if not path.is_file():
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: findings file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: findings file must be a JSON list")
    return data


def _load_external_rules(rules_file: str | None) -> dict[str, str] | None:
    """加载外部规则集 {version, rules}；校验版本+内容双锚点防篡改逃逸（C1-P6）。

    声明版本与内置一致但内容哈希不一致 → RULES_HASH_MISMATCH 拒绝。
    """
    if not rules_file:
        return None
    path = Path(rules_file)
    if not path.is_file():
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: rules file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    version = data.get("version", "")
    rules = data.get("rules")
    if not version or not isinstance(rules, dict):
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: rules file must have version and rules dict")
    file_sha = "sha256:" + hashlib.sha256(
        json.dumps(rules, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if version == RISK_RULES_VERSION and file_sha != RISK_RULES_SHA256:
        # 版本号不变但内容被就地篡改 → 双锚点失配，旧包失效（§5.4 / C1-P6）
        print(f"ERROR: {RULES_HASH_MISMATCH}: rules content changed with version unchanged", file=sys.stderr)
        raise ValueError(RULES_HASH_MISMATCH)
    return {"version": version, "rules_sha256": file_sha, "rules": rules}


def _enumerate_diff(repo: Path, base_sha: str, head_sha: str) -> list[dict[str, Any]]:
    """T1 受控 diff 枚举（稳定排序：状态分组 + 路径字典序）。"""
    rc, out, err = _run_git(repo, ["diff", "--name-status", base_sha, head_sha])
    if rc != 0:
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: git diff failed: {err.strip()}")
    files: list[dict[str, Any]] = []
    for raw in out.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[1]
        files.append({"path": path, "status": status})
    # 稳定排序：状态分组（added/modified/deleted/renamed/其余）后按路径字典序
    status_order = {"added": 0, "modified": 1, "deleted": 2, "renamed": 3}
    files.sort(key=lambda f: (status_order.get(f["status"], 99), f["path"]))
    return files


def _read_head_file(repo: Path, head_sha: str, path: str) -> bytes | None:
    """读取 head 版本文件内容（deleted 文件返回 None）。"""
    rc, out, err = _run_git(repo, ["show", f"{head_sha}:{path}"])
    if rc != 0:
        return None
    return out.encode("utf-8")


def _detect_risk_hits(files: list[dict[str, Any]], rules: dict[str, str]) -> list[dict[str, Any]]:
    """T2 风险特征识别：版本化确定性规则匹配路径/内容特征。命中=需审查，不=缺陷成立。"""
    hits: list[dict[str, Any]] = []
    compiled = {name: re.compile(pat, re.IGNORECASE) for name, pat in rules.items()}
    for f in files:
        for rule_name, pattern in compiled.items():
            if pattern.search(f["path"]):
                hits.append({
                    "file": f["path"],
                    "rule": rule_name,
                    "status": f["status"],
                    "evidence_level": "S2",
                })
    hits.sort(key=lambda h: (h["file"], h["rule"]))
    return hits


def _generate_related_candidates(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """T2 关联候选生成（basename 规则；algorithm/rationale/confidence/evidence_level）。"""
    candidates: list[dict[str, Any]] = []
    by_basename: dict[str, list[dict[str, Any]]] = {}
    for f in files:
        base = Path(f["path"]).name
        by_basename.setdefault(base, []).append(f)
    for f in files:
        base = Path(f["path"]).name
        stem = Path(f["path"]).stem
        for other in by_basename.get(base, []):
            if other["path"] != f["path"]:
                candidates.append({
                    "algorithm": "same_basename",
                    "rationale": f"same basename as {f['path']}",
                    "confidence": "medium",
                    "evidence_level": "S2",
                    "file": other["path"],
                })
        if base.startswith("test_") or base.endswith("_test.py") or ".spec." in base:
            candidates.append({
                "algorithm": "basename_test",
                "rationale": f"test artifact for {stem}",
                "confidence": "high",
                "evidence_level": "S2",
                "file": f["path"],
            })
    # 稳定排序去重
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for c in sorted(candidates, key=lambda c: (c["file"], c["algorithm"])):
        key = (c["file"], c["algorithm"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _package_hash_inputs() -> dict[str, str]:
    """§3.3 package hash 输入（任一缺失/为空 → fail-closed 拒绝）。"""
    inputs = {
        "rules_version": RISK_RULES_VERSION,
        "rules_sha256": RISK_RULES_SHA256,
        "algorithm_version": ALGORITHM_VERSION,
        "algorithm_sha256": ALGORITHM_SHA256,
        "summary_format_version": SUMMARY_FORMAT_VERSION,
    }
    for key, value in inputs.items():
        if not value:
            raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: package hash input missing: {key}")
    return inputs


def _build_manifest(
    task_id: str,
    repo: Path,
    base_sha: str,
    head_sha: str,
    files: list[dict[str, Any]],
    risk_hits: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    workspace_dirty: bool,
    scanner_anchors: dict[str, str] | None,
    s1_validation: list[dict[str, Any]] | None = None,
    refs_validation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bytes, str]:
    """T4 包生成：稳定序列化 + manifest 组装 + package_hash（防逃逸）。

    两段式序列化解决 self-hash 循环依赖：
    ① body（无自引用）序列化 → content_hash；
    ② body + content_hash/package_hash 自引用 → 最终序列化（写入物）。
    s1_validation 为 V5.2.1 C5 扩展字段：未提供时（C1 既有行为）不写入，保持字节兼容。
    refs_validation 为 V5.2.1 B-12 扩展字段：未提供时（C1 既有行为）不写入，保持字节兼容。
    """
    inputs = _package_hash_inputs()
    manifest_body = {
        "preflight_version": _PREFLIGHT_VERSION,
        "rules_version": inputs["rules_version"],
        "rules_sha256": inputs["rules_sha256"],
        "algorithm_version": inputs["algorithm_version"],
        "algorithm_sha256": inputs["algorithm_sha256"],
        "summary_format_version": inputs["summary_format_version"],
        "base_sha": base_sha,
        "head_sha": head_sha,
        "workspace_dirty": workspace_dirty,
        "files": files,
        "risk_hits": risk_hits,
        "related_candidates": candidates,
        "test_evidence_index": [],
        "diff_index": [{"path": f["path"], "status": f["status"]} for f in files],
        "anchor_check": anchors,
    }
    if scanner_anchors:
        manifest_body["scanner_version"] = scanner_anchors["scanner_version"]
        manifest_body["scanner_sha256"] = scanner_anchors["scanner_sha256"]
    if s1_validation is not None:
        manifest_body["s1_validation"] = s1_validation
    if refs_validation is not None:
        manifest_body["refs_validation"] = refs_validation
    body_serialized = json.dumps(manifest_body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    content_hash = hashlib.sha256(body_serialized).hexdigest()
    package_hash = hashlib.sha256(
        "|".join([
            inputs["rules_version"], inputs["rules_sha256"],
            inputs["algorithm_version"], inputs["algorithm_sha256"],
            inputs["summary_format_version"], content_hash,
        ]).encode("utf-8")
    ).hexdigest()
    final_manifest = dict(manifest_body)
    final_manifest["content_hash"] = f"sha256:{content_hash}"
    final_manifest["package_hash"] = f"sha256:{package_hash}"
    serialized = json.dumps(
        final_manifest, ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    return final_manifest, serialized, package_hash


def _split_packs(files: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """预算分包：确定性阈值（文件数/字节预算）分块，阈值纳入 summary_format_version 语义。"""
    packs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for f in files:
        # 路径字节估算（确定性，不含内容；内容不入包，仅索引）
        est = len(f["path"].encode("utf-8")) + len(f["status"].encode("utf-8")) + 32
        if current and (len(current) >= BUDGET_MAX_FILES_PER_PACK or current_bytes + est > BUDGET_MAX_BYTES_PER_PACK):
            packs.append(current)
            current = []
            current_bytes = 0
        current.append(f)
        current_bytes += est
    if current:
        packs.append(current)
    return packs


def _atomic_write(path: Path, data: bytes) -> None:
    """temp+rename 原子写（禁止原地覆写）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os_replace(tmp, path)
    tmp.unlink(missing_ok=True)


def os_replace(tmp: Path, dst: Path) -> None:
    """跨平台原子替换（Windows 上 os.replace 语义）。"""
    import os
    os.replace(tmp, dst)


def _readback_verify(path: Path, expected_file_sha256: str) -> None:
    """写后 readback：重算文件字节 hash 不一致 → 丢弃临时文件、保持原内容不变并失败。"""
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_file_sha256:
        # 丢弃（临时文件已由原子写清理）；保持目标文件原状并失败
        raise ValueError(
            f"{PREFLIGHT_INPUT_INVALID}: readback hash mismatch: {path} "
            f"(expected {expected_file_sha256}, got {actual})"
        )


def _scan_for_seal(repo: Path, head_sha: str, files: list[dict[str, Any]], serialized: bytes) -> list[dict[str, Any]]:
    """T5 封存前敏感扫描（复用 sensitive_scanner；路径 + manifest 内容双轴）。

    路径命中时计算 head 版本文件 hash 一并记录（SENSITIVE_REFERENCE_ONLY 需源位置+hash）；
    扫描器异常 fail-closed 按命中处理（内部 catch 返回 error，此处再对调用点兜底）。
    """
    hits: list[dict[str, Any]] = []
    try:
        for f in files:
            res = scan_resource_ref(f["path"])
            if has_sensitive_hits(res):
                content = _read_head_file(repo, head_sha, f["path"])
                file_hash = (
                    "sha256:" + hashlib.sha256(content).hexdigest() if content is not None else None
                )
                hits.extend({
                    "kind": "path", "source": f["path"],
                    "category": h["category"], "sha256": file_hash,
                } for h in res["hits"])
        res = scan_content(serialized.decode("utf-8", errors="replace"))
        if has_sensitive_hits(res):
            hits.extend({
                "kind": "content", "source": "package-manifest",
                "category": h["category"], "sha256": None,
            } for h in res["hits"])
    except Exception as exc:
        # fail-closed：扫描器崩溃 → 按命中阻断（同 receipt_cmd F2 兜底先例）
        print(f"WARNING: sensitive scanner crashed during seal: {type(exc).__name__}: {exc}", file=sys.stderr)
        hits.append({"kind": "error", "source": "scanner", "category": "scanner_crash", "sha256": None})
    return hits


def _load_s1_declarations(s1_validate: str | None) -> list[dict[str, Any]] | None:
    """V5.2.1 C5：加载 evidence_declaration 列表（--s1-validate）。未提供返回 None。"""
    if not s1_validate:
        return None
    path = Path(s1_validate)
    if not path.is_file():
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: s1 declarations file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: s1 declarations file must be a JSON list")
    return data


def cmd_review_preflight(args) -> int:
    """review-preflight 主命令（T1-T6）。"""
    task_dir = Path(args.task_dir).resolve()
    repo = Path(args.repo).resolve()

    # --- T1 输入校验：任务声明（同 receipt_cmd 模式）---
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: task directory has no status.yaml: {task_dir}")
    status_text = status_path.read_text(encoding="utf-8-sig")
    task_match = re.search(r"(?m)^task_id:\s*[\"']?([^\"'\n#]+)", status_text)
    status_task_id = task_match.group(1).strip() if task_match else ""
    if status_task_id != args.task:
        raise ValueError(
            f"{PREFLIGHT_INPUT_INVALID}: --task '{args.task}' does not match status.yaml task_id '{status_task_id}'"
        )
    contract_match = re.search(
        r"(?ms)^artifact_contract:\s*\n\s+version:\s*[\"']?([^\"'\n#]+)", status_text
    )
    contract_version = contract_match.group(1).strip() if contract_match else ""
    if contract_version != active_version():
        raise ValueError(
            f"{PREFLIGHT_CONTRACT_MISMATCH}: review-preflight only runs on artifact_contract.version={active_version()}"
        )

    # --- T1 输入校验：仓库 / base/head SHA ---
    if not repo.is_dir():
        raise ValueError(f"{PREFLIGHT_REPO_INVALID}: repo not found: {repo}")
    rc, _, err = _run_git(repo, ["rev-parse", "--git-dir"])
    if rc != 0:
        raise ValueError(f"{PREFLIGHT_REPO_INVALID}: not a git repository: {err.strip()}")
    base_sha = args.base_sha.strip()
    head_sha = (args.head_sha or "HEAD").strip()
    for sha in (base_sha, head_sha):
        rc2, _, _ = _run_git(repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"])
        if rc2 != 0:
            raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: invalid sha: {sha}")
    # 工作区 clean/dirty 判定
    rc3, status_out, _ = _run_git(repo, ["status", "--porcelain"])
    workspace_dirty = rc3 == 0 and bool(status_out.strip())

    # --- T1 受控 diff 枚举（稳定排序）---
    files = _enumerate_diff(repo, base_sha, head_sha)

    # --- T2 外部规则集（双锚点校验，可选）---
    rules = _RISK_RULES
    if args.rules_file:
        ext = _load_external_rules(args.rules_file)
        rules = ext["rules"]

    # --- T2 风险识别 + 关联候选 ---
    risk_hits = _detect_risk_hits(files, rules)
    candidates = _generate_related_candidates(files)

    # --- T3 anchor_check 四项确定性校验（失败不删 finding）---
    findings = _load_findings(args.findings_file)
    anchors: list[dict[str, Any]] = []
    unverified = 0
    for finding in findings:
        content_bytes = _read_head_file(repo, head_sha, finding.get("file", ""))
        content = content_bytes.decode("utf-8", errors="replace") if content_bytes is not None else ""
        result = anchor_check.run_anchor_check(finding, content)
        anchors.append(result)
        if result["anchor_status"] == "unverified":
            unverified += 1
            for code in result["errors"]:
                print(f"ANCHOR: finding={result['finding_id']} error={code} file={result['file']}", file=sys.stderr)

    # --- V5.2.1 C5：S1 声明拒绝校验（--s1-validate，正交于 anchor_check/封存流程）---
    # getattr 兜底：C1 既有测试以手工 Namespace 调用，不传该参数时行为与 C1 完全一致
    s1_validate_arg = getattr(args, "s1_validate", None)
    s1_validation: list[dict[str, Any]] | None = None
    if s1_validate_arg:
        declarations = _load_s1_declarations(s1_validate_arg)
        s1_validation = s1_validator.validate_declarations(declarations)
        for result in s1_validation:
            if result["decision"] == "rejected":
                for code in result["errors"]:
                    print(
                        f"S1: declaration={result['declaration_id']} error={code} "
                        f"message={result['message']}",
                        file=sys.stderr,
                    )

    # --- V5.2.1 B-12：结构化引用校验（--refs-file，可选串联）---
    # getattr 兜底：不传该参数时行为与 C1 完全一致，不写 manifest.refs_validation[]
    refs_file_arg = getattr(args, "refs_file", None)
    refs_validation: dict[str, Any] | None = None
    if refs_file_arg:
        refs_path = Path(refs_file_arg)
        if not refs_path.is_file():
            raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: refs file not found: {refs_path}")
        with open(refs_path, "r", encoding="utf-8") as handle:
            refs_data = json.load(handle)
        # 支持 evidence_refs 和 code_refs 两种顶层 key
        if isinstance(refs_data, dict):
            refs_list = []
            refs_list.extend(refs_data.get("evidence_refs", []))
            refs_list.extend(refs_data.get("code_refs", []))
        elif isinstance(refs_data, list):
            refs_list = refs_data
        else:
            raise ValueError(f"{PREFLIGHT_INPUT_INVALID}: refs file must be a JSON list or object with evidence_refs/code_refs keys")
        refs_validation = structured_refs.validate_refs(refs_list)
        for result in refs_validation["results"]:
            if result["decision"] == "failed":
                for code in result["errors"]:
                    print(
                        f"REFS: ref_id={result['ref_id']} error={code} "
                        f"kind={result['kind']} value={result['value']}",
                        file=sys.stderr,
                    )
            elif result["decision"] == "warning":
                for code in result["warnings"]:
                    print(
                        f"REFS: ref_id={result['ref_id']} warning={code} "
                        f"kind={result['kind']} value={result['value']}",
                        file=sys.stderr,
                    )

    # --- T4 包生成（稳定序列化 + 预算分包 + package_hash 防逃逸）---
    packs = _split_packs(files)
    scanner_anchors = {"scanner_version": "1.0.0", "scanner_sha256": ""}
    try:
        from .sensitive_scanner import _SCANNER_VERSION, _SCANNER_SHA256
        scanner_anchors = {"scanner_version": _SCANNER_VERSION, "scanner_sha256": _SCANNER_SHA256}
    except ImportError:
        pass
    built: list[tuple[dict[str, Any], bytes, str]] = []
    for pack in packs:
        manifest, serialized, package_hash = _build_manifest(
            args.task, repo, base_sha, head_sha,
            pack, risk_hits, candidates, anchors, workspace_dirty, scanner_anchors,
            s1_validation=s1_validation,
            refs_validation=refs_validation,
        )
        built.append((manifest, serialized, package_hash))

    # --- T6 --simulate 零写入：全部写入替换为拟写清单 ---
    if args.simulate:
        print("=== PREFLIGHT SIMULATE (zero-write) ===")
        for manifest, serialized, package_hash in built:
            print(f"  would-write: .execution/{args.task}/tp-development-engineering/review/{package_hash}.json")
            if args.phase_exit:
                print(f"  would-seal:  evidence/review-packages/{package_hash}/manifest.json")
            print(f"  content-hash: sha256:{hashlib.sha256(serialized).hexdigest()}")
            print(f"  package-hash: {manifest['package_hash']}")
            print(f"  anchor-unverified: {unverified}")
        print("  (no files created or modified: .execution / evidence / ledger / projections untouched)")
        return 0

    # --- T4 候选包原子写（.execution/<TASK-ID>/tp-development-engineering/review/）---
    review_dir = task_dir / ".execution" / args.task / "tp-development-engineering" / "review"
    for manifest, serialized, package_hash in built:
        target = review_dir / f"{package_hash}.json"
        if target.is_file():
            # 同 hash 幂等：已存在则跳过（候选包区允许幂等）
            continue
        expected_file_sha = hashlib.sha256(serialized).hexdigest()
        _atomic_write(target, serialized)
        _readback_verify(target, expected_file_sha)

    # --- T5 兼容名 --phase-exit：仅封存 review package；不做 Task phase/state transition。 ---
    if args.phase_exit:
        seal_base = task_dir / "evidence" / "review-packages"
        for manifest, serialized, package_hash in built:
            seal_dir = seal_base / package_hash
            seal_manifest = seal_dir / "manifest.json"
            if seal_manifest.is_file():
                continue  # 同 hash 幂等返回 exit 0，不重复写入
            hits = _scan_for_seal(repo, head_sha, files, serialized)
            if hits:
                # 封存阻断：不复制原文，仅写 SENSITIVE_REFERENCE_ONLY + 源位置 + hash
                rejected = {
                    "status": SENSITIVE_REFERENCE_ONLY,
                    "package_hash": manifest["package_hash"],
                    "hits": hits,
                }
                rejected_path = seal_base / f"REJECTED-{package_hash}.json"
                _atomic_write(
                    rejected_path,
                    json.dumps(rejected, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
                )
                print(f"ERROR: {SENSITIVE_REFERENCE_ONLY}: seal blocked, reference only written: {rejected_path}", file=sys.stderr)
                return 1
            _atomic_write(seal_manifest, serialized)
            expected_file_sha = hashlib.sha256(serialized).hexdigest()
            _readback_verify(seal_manifest, expected_file_sha)
            print(f"sealed: evidence/review-packages/{package_hash}/manifest.json")

    # --- 退出码：任一 finding unverified → 预检未通过 ---
    if unverified:
        print(f"ERROR: {unverified} finding(s) unverified; hand over to tp-verification-engineering", file=sys.stderr)
        return 1
    # --- V5.2.1 C5：任一 S1 declaration decision==rejected → fail-closed 预检未通过 ---
    if s1_validation is not None and s1_validator.any_rejected(s1_validation):
        rejected = [r for r in s1_validation if r["decision"] == "rejected"]
        print(f"ERROR: {len(rejected)} S1 declaration(s) rejected; S1 不得作为实施依据", file=sys.stderr)
        return 1
    # --- V5.2.1 B-12：任一 refs validation decision==failed → fail-closed 预检未通过 ---
    if refs_validation is not None and structured_refs.any_failed(refs_validation["results"]):
        failed = [r for r in refs_validation["results"] if r["decision"] == "failed"]
        print(f"ERROR: {len(failed)} ref(s) validation failed; structured references not verifiable", file=sys.stderr)
        return 1
    print(f"preflight: ok ({len(built)} pack(s), {len(files)} file(s), {len(anchors)} anchor(s))")
    return 0


def add_review_preflight_subparsers(subparsers) -> None:
    p = subparsers.add_parser(
        "review-preflight",
        help="V5.2.1 C1 review preflight: anchor_check deterministic validation + sealed review package (no state change)",
    )
    p.add_argument("--task", required=True, help="task id (must match status.yaml)")
    p.add_argument("--task-dir", required=True, help="task directory containing status.yaml")
    p.add_argument("--repo", required=True, help="git repository path (base..head diff source)")
    p.add_argument("--base-sha", required=True, help="base commit SHA")
    p.add_argument("--head-sha", default="HEAD", help="head commit SHA (default HEAD)")
    p.add_argument("--findings-file", default=None, help="JSON list of findings {id,file,text,line,evidence_hash,hunk_context}")
    p.add_argument("--rules-file", default=None, help="external risk rules JSON {version,rules}; dual-anchor checked (C1-P6)")
    p.add_argument("--s1-validate", default=None, help="JSON list of evidence_declarations for S1/S2/S3 validation (V5.2.1 C5)")
    p.add_argument("--refs-file", default=None, help="JSON file with evidence_refs/code_refs for V5.2.1 B-12 structured refs validation")
    p.add_argument("--phase-exit", action="store_true", help="compatibility flag name: seal final package to evidence/review-packages/<package-hash>/; does not change Task state/phase")
    p.add_argument("--simulate", action="store_true", help="zero-write mode: compute everything, write nothing (C1-P9)")
    p.add_argument("--db", required=False, help="accepted for CLI consistency; preflight is file/git-only")
    p.set_defaults(func=cmd_review_preflight)
