# -*- coding: utf-8 -*-
"""V5.2.3 legacy commit compatibility / recovery surface.

Normal V5.2.3 roles do not use ``tp-spec commit`` to advance work.  The public daily
API is ``task checkpoint/block/resume/verify/complete`` in :mod:`cli.record_first`.
This module is retained because its durable-journal / atomic-projection primitives are
also useful to Record-first writes and because historical long-state tasks/admin
recovery still need a lossless compatibility implementation.

The legacy command continues to enforce its historical transition/review/closing
rules when it is explicitly invoked.  Those rules must not be interpreted as the
active five-state Record-first workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import db as dbmod
from . import event_policies
from . import projection_cmd
from . import transaction_journal
from .commit_errors import ProjectionCommitFailedError, ReconciliationRequiredError
from .encoding_guard import EncodingValidationError, validate_input, validate_list
from .frontmatter import FrontMatterError
from .path_identity import same_path
from . import frontmatter
from .transaction_journal import (
    JOURNAL_SCHEMA,
    PHASE_DB_COMMITTED,
    PHASE_FILES_REPLACED,
    PHASE_PREPARED,
)
from .version import active_version
from .workflow_loader import load_workflow
from .transition_service import validate_transition


ACTIVE_CONTRACT = active_version()
_ALLOWED_ACTORS = {"tp-product-design", "tp-architecture-design", "tp-development-engineering", "tp-verification-engineering", "tp-delivery-convergence", "human_owner", "tp-requirement-analysis", "tp-architecture-review"}


def _read(path: Path) -> str:
    # Preserve CRLF/LF exactly: generated-view digests must agree with the
    # PowerShell validator, whose Get-Content -Raw does not normalize line ends.
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def _yaml_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*[\"']?([^\"'\n#]+)", text)
    return match.group(1).strip() if match else ""


def _artifact_version(task_dir: Path) -> str:
    status = _read(task_dir / "status.yaml")
    match = re.search(r"(?ms)^artifact_contract:\s*\n\s+version:\s*[\"']?([^\"'\n#]+)", status)
    return match.group(1).strip() if match else ""


def _continuation_sources(task_dir: Path, state: str) -> List[Path]:
    """Return the formal artifacts completed before the current owner starts work."""
    names = ["status.yaml", "events.jsonl", "task.md", "acceptance.md"]
    if state in {"CLOSING", "COMPLETED"}:
        names.extend(["implementation.md", "codex-review.md"])
    elif state == "VERIFYING":
        names.append("implementation.md")
    # V5.2.3 §3.8/§10.2：新工件经集中注册表纳入 source digest（存在才纳入）
    names.extend(projection_cmd.projection_source_names())
    return [task_dir / name for name in names if (task_dir / name).is_file()]


def _source_digest(paths: List[Path], task_dir: Path) -> str:
    parts: List[str] = []
    for path in sorted(paths):
        rel = path.relative_to(task_dir).as_posix()
        parts.append(rel + "\n" + hashlib.sha256(_read(path).encode("utf-8")).hexdigest() + "\n")
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def _generated_view_text(task_dir: Path, name: str, body: str, sources: List[Path], flush_id: str) -> str:
    """渲染 generated view 文本（不落盘）。"""
    digest = _source_digest(sources, task_dir)
    source_lines = "\n".join(f'  - "{p.relative_to(task_dir).as_posix()}"' for p in sorted(sources))
    return (
        "---\n"
        "generated_view: true\n"
        f'generator_version: "{ACTIVE_CONTRACT}"\n'
        f'generated_at: "{dbmod.now_iso()}"\n'
        "source_files:\n" + source_lines + "\n"
        f'source_digest: "sha256:{digest}"\n'
        f'flush_id: "{flush_id}"\n'
        f'content_digest: "sha256:{hashlib.sha256(body.encode("utf-8")).hexdigest()}"\n'
        "---\n\n" + body
    )


def _deferred_acceptance_items(task_dir: Path) -> List[str]:
    """返回验收矩阵中 verdict 为 DEFERRED_ACCEPTED 且已在 deferred_acceptance
    YAML 中登记的 AC 编号（P1-4：不再仅按正则提取，YAML 登记为准）。"""
    path = task_dir / "acceptance.md"
    if not path.is_file():
        return []
    text = _read(path)
    # 1) 真实解析 deferred_acceptance YAML（fail-closed；解析失败视为无登记）
    from . import yaml_checks
    registered: set = set()
    try:
        result = yaml_checks.check_acceptance_yaml(text)
        for entry in result.deferred_entries:
            ac = entry.get("ac")
            if ac:
                registered.add(str(ac))
    except Exception:
        registered = set()
    # 2) 表格 DEFERRED_ACCEPTED 且已登记
    items: List[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        verdict = cells[8] if len(cells) > 8 else ""
        ac_id = match.group(1)
        if re.match(r"^DEFERRED_ACCEPTED\b", verdict) and ac_id in registered:
            items.append(ac_id)
    return items


def _current_view_rel(state: str) -> str:
    """当前视图投影的相对路径（按状态选择 continuation/final-result）。"""
    return "generated/final-result.md" if state == "COMPLETED" else "generated/continuation.md"


def _latest_projected_verification(task_dir: Path) -> str:
    """Return the latest verification fact and mark subject changes as stale."""
    path = task_dir / "events.jsonl"
    if not path.is_file():
        return "NOT_RECORDED"
    latest = "NOT_RECORDED"
    latest_subject = ""
    try:
        for line in _read(path).splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("type") in {"REVIEW_COMPLETED", "VERIFICATION"} and obj.get("actor") == "tp-verification-engineering":
                latest = str(obj.get("decision") or "NOT_RECORDED").upper()
                latest_subject = str(obj.get("subject_digest") or "")
        if latest_subject:
            from .digest import compute_verification_subject_digest
            if compute_verification_subject_digest(task_dir) != latest_subject:
                return f"{latest}_STALE"
    except Exception:
        return "UNKNOWN"
    return latest


def _rebuild_current_view_text(task_dir: Path, task, summary: str, flush_id: str) -> str:
    """Render the readable current view from ledger facts.

    V5.2.3 intentionally exposes state/phase/result facts, not handoff bureaucracy.
    """
    state = str(task["current_state"] or "NEW")
    owner = str(task["owner_role"] or "unknown")
    phase = str(task["current_stage"] or "intake")
    sources = _continuation_sources(task_dir, state)
    verification = _latest_projected_verification(task_dir)
    if state == "COMPLETED":
        body = (
            "# 生成的结项摘要\n\n"
            f"- 任务状态：COMPLETED\n"
            f"- 最后阶段：{phase}\n"
            f"- 最后执行角色：{owner}\n"
            f"- 技术验证事实：{verification}\n"
            f"- 结论：{summary}\n"
        )
        deferred = _deferred_acceptance_items(task_dir)
        if deferred:
            body += "- 延期验收项：" + "、".join(deferred) + "（见 acceptance.md）\n"
        if verification != "PASS":
            body += "- 提示：COMPLETED 表示任务工作已结束，不代表未记录/失败/延期的验证被改写为 PASS。\n"
        return _generated_view_text(task_dir, "final-result.md", body, sources, flush_id)
    body = (
        "# 任务接续区\n\n"
        f"- 状态：{state}\n"
        f"- 当前阶段：{phase}\n"
        f"- 最近执行角色：{owner}\n"
        f"- 最近记录：{summary}\n"
        "\n> V5.2.3：phase 是查询事实，不是流程门禁；继续完成业务工作即可。\n"
    )
    return _generated_view_text(task_dir, "continuation.md", body, sources, flush_id)

def _handoff_record(task_dir: Path, args, flush_id: str, owner: str) -> Dict[str, Any]:
    """构造 handoff.json record（V5.2.3 §5：同时入 HANDOFF 事件 payload 供无损重建）。"""
    handoff_id = f"HANDOFF-{args.task}-{uuid.uuid4().hex[:10].upper()}"
    return {
        "schema_version": ACTIVE_CONTRACT,
        "handoff_id": handoff_id,
        "flush_id": flush_id,
        "consumed": True,
        "consumed_at": dbmod.now_iso(),
        "status": "committed",
        "actor": args.actor,
        "summary": args.summary,
        "changes": args.change or [],
        "risks": args.risk or [],
        "evidence": args.evidence or [],
        "next": {"state": args.to, "owner": owner},
        "next_prompt": {
            "target_role": owner,
            "task_id": args.task,
            "target_state": args.to,
            "entry": "generated/continuation.md" if args.to != "COMPLETED" else "generated/final-result.md",
            "actions": args.action or ["读取正式工件并执行当前状态职责"],
            "constraints": args.constraint or ["正式事实以任务工件和事件账本为准"],
        },
    }


def _handoff_text(task_dir: Path, args, flush_id: str, owner: str) -> str:
    """渲染 handoff.json 文本（不落盘）。"""
    return json.dumps(_handoff_record(task_dir, args, flush_id, owner), ensure_ascii=False, indent=2) + "\n"


def _validate_db_requirement(task_dir: Path, args) -> None:
    acceptance = _read(task_dir / "acceptance.md")
    requires_dml = bool(re.search(r'(?m)^\s*action:\s*["\']?DML["\']?\s*(?:#.*)?$', acceptance))
    if not requires_dml:
        return
    evidence = "\n".join(args.evidence or []) + "\n" + acceptance
    has_execution = "dml_execution: passed" in acceptance or "DML_EXECUTED" in evidence
    risk_accepted = "dml_residual_risk: accepted" in acceptance
    if not has_execution and not risk_accepted:
        raise ValueError("DML acceptance requires execution evidence; read-only evidence cannot satisfy it")
    if args.database_verification and args.database_verification != "DML":
        raise ValueError("database-verification conflicts with acceptance DML requirement")


# =============================================================================
# V5.2.3 A-05：--payload-json 稳定输入
# =============================================================================

_PAYLOAD_LIST_FIELDS = ("changes", "risks", "evidence", "action", "constraint")
_PAYLOAD_SCALAR_FIELDS = ("summary", "decision", "authorization")


def _load_payload(path: str) -> Dict[str, Any]:
    """读取 UTF-8 JSON payload 文件（容忍 BOM），返回 dict。"""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as e:
        raise ValueError(f"cannot read payload file {path}: {e}")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"payload file is not valid UTF-8: {e}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"payload file has invalid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    return data


def _apply_payload(args, payload: Dict[str, Any]):
    """payload 字段覆盖 CLI 参数（--payload-json 优先），并做类型/取值校验。"""
    for key in _PAYLOAD_LIST_FIELDS:
        if key in payload:
            val = payload[key]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise ValueError(f"payload field '{key}' must be an array of strings")
            setattr(args, _ATTR_BY_PAYLOAD[key], val)
            print(f"payload: {key} overrides CLI argument")
    for key in _PAYLOAD_SCALAR_FIELDS:
        if key in payload:
            val = payload[key]
            if not isinstance(val, str):
                raise ValueError(f"payload field '{key}' must be a string")
            setattr(args, _ATTR_BY_PAYLOAD[key], val)
            print(f"payload: {key} overrides CLI argument")
    # argparse choices 不覆盖 payload：手动校验取值
    if args.decision not in (None, "PASS", "FAIL", "NEEDS_FIX"):
        raise ValueError("payload 'decision' must be PASS, FAIL or NEEDS_FIX")
    return args


_ATTR_BY_PAYLOAD = {
    "changes": "change", "risks": "risk", "evidence": "evidence",
    "action": "action", "constraint": "constraint",
    "summary": "summary", "decision": "decision",
    "authorization": "authorization",
}


def _validate_utf8_inputs(args) -> None:
    """A-05：所有进入账本/交接的文本写入前做 UTF-8 round-trip 与乱码检测。"""
    validate_input(args.summary or "", "summary")
    for field in ("change", "risk", "evidence", "action", "constraint"):
        validate_list(getattr(args, field, None), field)
    for field in ("decision", "authorization"):
        val = getattr(args, field, None)
        if val:
            validate_input(val, field)


# =============================================================================
# V5.2.3 A-02：preflight（任何写入前完成，失败零副作用）
# =============================================================================

def _fm_artifact_rel(args, current: str, to_state: str) -> Optional[str]:
    """本次 commit 将改写 front matter 的工件相对路径；不改写返回 None。

    stage_handoff 描述的是“离开当前阶段时交给下游”的声明，而不是进入该
    角色内部阶段时的状态镜像。因此只有 actor 正在退出自己拥有的正式阶段时
    才允许 Runtime 标记 ready/intended_next；例如 NEW -> TECH_DESIGNING 仍是
    tp-architecture-design 的同 owner 微循环，绝不能污染 task.md 中原本声明的
    TECH_DESIGNING 出口（通常为 DEVELOPING）。
    """
    if args.actor == "tp-architecture-design":
        # 架构角色的 NEW/RISK_ANALYZING/REQUIREMENT_CLARIFYING/TECH_DESIGNING 等
        # 属同 owner 微循环；进入这些状态不能把“阶段出口”改成内部状态。
        target_owner = load_workflow().get_state_owner(to_state)
        if target_owner == "tp-architecture-design":
            return None
        return "task.md"
    if args.actor == "tp-development-engineering" and current in {"DEVELOPING", "ASSISTING"}:
        return "implementation.md"
    if args.actor == "tp-delivery-convergence" and current == "CLOSING":
        return "quality-and-knowledge.md"
    if args.actor == "tp-verification-engineering":
        # review-only owns nested review metadata. A later VERIFYING->DEVELOPING
        # rework transition must not mutate codex-review with generic stage_handoff keys.
        return None
    return None


def _frontmatter_text(path: Path, values: Dict[str, str]) -> str:
    """返回改写 front matter 后的完整文本（不落盘）；缺失/损坏抛 ValueError。"""
    text = frontmatter.read(str(path))
    if not frontmatter.has(text):
        raise ValueError(f"{path.name} is missing YAML front matter")
    try:
        return frontmatter.set_values(text, values)
    except FrontMatterError as e:
        raise ValueError(f"{path.name}: {e}")


def _validate_yaml_frontmatter(name: str, text: str) -> None:
    """front matter body 必须可被真实 YAML 解析（pyyaml 可用时）；失败抛 ValueError。"""
    parts = frontmatter.split(text)
    if parts is None:
        raise ValueError(f"{name}: missing or invalid YAML front matter")
    front, _, _ = parts
    try:
        import yaml  # type: ignore
    except ImportError:
        return  # pyyaml 不可用：frontmatter.has/split 结构校验仍强制
    try:
        data = yaml.safe_load(front)
    except Exception as e:
        raise ValueError(f"{name}: YAML front matter is not parseable: {e}")
    if data is not None and not isinstance(data, dict):
        raise ValueError(f"{name}: YAML front matter must be a mapping")


def _probe_writable(task_dir: Path) -> None:
    """任务目录可写探测（探测文件立即删除，无持久副作用）。"""
    probe = task_dir / f".v511-write-probe-{uuid.uuid4().hex[:8]}"
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("")
    except OSError as e:
        raise ValueError(f"task-dir is not writable: {e}")
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def run_transition_preflight(task_id: str, from_state: str, to_state: str, actor: str,
                             task_dir: Optional[Path] = None, conn=None):
    """阶段 preflight hook（V5.2.3 §10.1，真实业务 validator）。

    Hardening：替换 AI-A 的空实现。委托 cli/transition_service.validate_transition
    执行 L0~L3 风险等级工件门禁、架构评审 PASS/stale 校验、验收/结单门禁。
    失败返回 issues（稳定错误码），调用点在任何 DB/事件/投影写入前终止。

    返回 SimpleNamespace(ok: bool, errors: list[str])。
    """
    if task_dir is None or conn is None:
        # 向后兼容：缺 task-dir/conn 时 fail-closed，禁止静默放行。
        return SimpleNamespace(
            ok=False,
            errors=["transition preflight requires task_dir and db connection (missing context)"],
        )
    result = validate_transition(
        task_id=task_id,
        task_dir=Path(task_dir),
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        conn=conn,
    )
    if result.ok:
        return SimpleNamespace(ok=True, errors=[])
    return SimpleNamespace(ok=False, errors=[f"{i.code}: {i.message}" for i in result.issues])


def _preflight_files(task_dir: Path, args, current: str, to_state: str) -> None:
    """A-02 preflight 文件侧检查（只读；失败抛 ValueError，零副作用）。"""
    if not task_dir.is_dir():
        raise ValueError(f"task-dir not found: {task_dir}")
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        raise ValueError("commit requires status.yaml in task-dir (run task create first)")
    rel = _fm_artifact_rel(args, current, to_state)
    if rel:
        artifact = task_dir / rel
        if not artifact.is_file():
            raise ValueError(f"artifact required for this commit is missing: {rel}")
        text = frontmatter.read(str(artifact))
        if not frontmatter.has(text):
            raise ValueError(f"{rel} is missing YAML front matter")
        _validate_yaml_frontmatter(rel, text)
    # handoff 输入 JSON 可序列化（summary 等已在 _validate_utf8_inputs 校验）
    try:
        json.dumps({"summary": args.summary})
    except (TypeError, ValueError) as e:
        raise ValueError(f"handoff input is not JSON-serializable: {e}")
    _probe_writable(task_dir)



def _verification_next_state(decision: str) -> str:
    """Runtime-owned review routing. Roles never hand-author the target state."""
    value = str(decision or "").upper()
    if value == "PASS":
        return "CLOSING"
    if value == "NEEDS_FIX":
        return "VERIFYING"
    if value == "FAIL":
        return "DEVELOPING"
    return "VERIFYING"


def _collect_commit_preflight(task_dir: Path, args, conn, task) -> Dict[str, Any]:
    """Return all detectable transition blockers without writing DB or task files.

    This is the user-facing "one shot" phase-exit preflight.  It intentionally
    aggregates independent failures instead of failing on the first exception.
    """
    issues: List[Dict[str, Any]] = []

    def add(code: str, message: str, artifact: Optional[str] = None, field: Optional[str] = None):
        issues.append({
            'code': code, 'message': message, 'artifact': artifact,
            'field': field, 'severity': 'ERROR',
        })

    current = str(task['current_state'] or '')
    target = str(args.to or '')
    if not task_dir.is_dir():
        add('TASK_DIR_MISSING', f'task-dir not found: {task_dir}')
        return {'ok': False, 'current_state': current, 'to_state': target, 'issues': issues}

    status_path = task_dir / 'status.yaml'
    if not status_path.is_file():
        add('STATUS_MISSING', 'status.yaml is required', 'status.yaml')
    else:
        try:
            version = _artifact_version(task_dir)
            if version != ACTIVE_CONTRACT:
                add('CONTRACT_VERSION_MISMATCH',
                    f'artifact_contract.version={version!r}; active contract is {ACTIVE_CONTRACT}',
                    'status.yaml', 'artifact_contract.version')
        except Exception as e:  # noqa: BLE001
            add('STATUS_INVALID', str(e), 'status.yaml')

    if (task['base_version'] or '') != ACTIVE_CONTRACT:
        add('DB_CONTRACT_VERSION_MISMATCH',
            f"task.base_version={task['base_version']!r}; active contract is {ACTIVE_CONTRACT}",
            None, 'task.base_version')

    if args.refresh:
        add('DRY_RUN_UNSUPPORTED_MODE', '--dry-run is not needed for --refresh')
        return {'ok': False, 'current_state': current, 'to_state': target, 'issues': issues}

    if args.review_only:
        # Verification preflight is intentionally performed *before* the trusted
        # REVIEW_COMPLETED event exists.  It checks the hypothetical final review
        # artifact plus every ordinary CLOSING prerequisite, but does not require
        # the PASS event that this command is about to create.
        if args.actor != 'tp-verification-engineering':
            add('ACTOR_MISMATCH', '--review-only is reserved for tp-verification-engineering')
        if current != 'VERIFYING':
            add('REVIEW_STATE_INVALID', '--review-only may only be recorded in VERIFYING')
        if not args.decision:
            add('REVIEW_DECISION_MISSING', '--review-only requires --decision')
        review_path = task_dir / 'codex-review.md'
        if not review_path.is_file():
            add('ARTIFACT_REQUIRED', 'codex-review.md is required for review-only', 'codex-review.md')
        else:
            try:
                timestamp = dbmod.now_iso()
                intended_next = _verification_next_state(args.decision)
                evidence0 = (args.evidence or [''])[0]
                final_crx = _frontmatter_text(
                    review_path,
                    {'decision': args.decision or '', 'evidence': evidence0,
                     'timestamp': timestamp, 'next_state': intended_next},
                )
                _validate_yaml_frontmatter('codex-review.md', final_crx)
                gate_error = _check_verification_pass_content_gate(
                    task_dir, final_crx, args.decision or '', evidence0
                )
                if gate_error:
                    add('VERIFICATION_PASS_CONTENT_GATE', gate_error, 'codex-review.md')
            except Exception as e:  # noqa: BLE001
                add('CODEX_REVIEW_INVALID', str(e), 'codex-review.md')

        if args.decision == 'PASS':
            try:
                _require_explicit_pass_evidence(args)
            except Exception as e:  # noqa: BLE001
                add('VERIFICATION_PASS_EVIDENCE_REQUIRED', str(e), 'codex-review.md', 'review.evidence')
            # Aggregate all non-event closure prerequisites.  Do not call the
            # trusted PASS gate here; that event does not exist until review-only
            # is committed.
            from . import transition_service as ts
            closing_issues = []
            ts._check_acceptance(task_dir, closing_issues, enforce_no_pending=True, enforce_yaml=True, conn=conn, task_id=args.task, allow_human_pending=True)
            ts._check_test_guide(task_dir, closing_issues, require_verification=True, to_state='CLOSING')
            ts._check_scope_change(task_dir, closing_issues)
            ts._check_text_integrity(task_dir, closing_issues, include_quality=False)
            for item in closing_issues:
                issues.append(item.to_dict())

        unique = []
        seen = set()
        for item in issues:
            key = (item.get('code'), item.get('message'), item.get('artifact'), item.get('field'))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return {
            'ok': not unique,
            'command': 'commit --review-only --dry-run',
            'task_id': args.task,
            'current_state': current,
            'decision': args.decision,
            'next_state': _verification_next_state(args.decision),
            'issues': unique,
            'next_action': 'record the review without --dry-run after all ERROR items are resolved' if unique else 'ready to record review',
        }

    try:
        wf = load_workflow()
        if not target or not wf.is_valid_transition(current, target):
            add('INVALID_TRANSITION', f'invalid transition {current} -> {target or "<missing>"}')
        else:
            expected_owner = wf.get_state_owner(target) or wf.get_completion_owner(task['risk_level'], task['flow_level'])
            if target == 'COMPLETED':
                expected_owner = 'tp-delivery-convergence'
            if not expected_owner:
                add('TARGET_OWNER_MISSING', f'no owner for target state {target}')
    except Exception as e:  # noqa: BLE001
        add('WORKFLOW_LOAD_ERROR', str(e))

    if target not in {'CLOSING', 'COMPLETED'} and args.actor != (task['owner_role'] or ''):
        add('ACTOR_MISMATCH',
            f"only current owner {task['owner_role']!r} may advance {current} -> {target}; got {args.actor!r}")
    if target == 'CLOSING' and args.actor != 'tp-delivery-convergence':
        add('ACTOR_MISMATCH', 'only tp-delivery-convergence may enter CLOSING')
    if target == 'COMPLETED' and (current != 'CLOSING' or args.actor != 'tp-delivery-convergence'):
        add('COMPLETION_OWNER_MISMATCH', 'COMPLETED requires CLOSING + tp-delivery-convergence')
    if args.phase_exit and args.actor != (task['owner_role'] or ''):
        add('PHASE_EXIT_OWNER_MISMATCH', '--phase-exit may only be submitted by the current owner')

    rel = _fm_artifact_rel(args, current, target)
    if rel:
        artifact = task_dir / rel
        if not artifact.is_file():
            add('ARTIFACT_REQUIRED', f'artifact required for this commit is missing: {rel}', rel)
        else:
            try:
                text = frontmatter.read(str(artifact))
                if not frontmatter.has(text):
                    add('FRONTMATTER_MISSING', f'{rel} is missing YAML front matter', rel)
                else:
                    _validate_yaml_frontmatter(rel, text)
            except Exception as e:  # noqa: BLE001
                add('FRONTMATTER_INVALID', str(e), rel)

    acceptance = task_dir / 'acceptance.md'
    if acceptance.is_file():
        try:
            _validate_db_requirement(task_dir, args)
        except Exception as e:  # noqa: BLE001
            add('DATABASE_VERIFICATION_INCOMPLETE', str(e), 'acceptance.md')

    if target:
        try:
            result = validate_transition(
                task_id=args.task, task_dir=task_dir, from_state=current,
                to_state=target, actor=args.actor, conn=conn,
            )
            for issue in result.issues:
                issues.append(issue.to_dict())
        except Exception as e:  # noqa: BLE001
            add('TRANSITION_PREFLIGHT_ERROR', str(e))

    if target == 'CLOSING':
        try:
            from .digest import compute_verification_subject_digest, compute_text_artifact_file_digest
            trusted = event_policies.load_trusted_governance_event(
                conn, args.task, event_type='REVIEW_COMPLETED',
                actor='tp-verification-engineering', decision='PASS', review_kind='VERIFICATION',
                artifact_path=task_dir / 'codex-review.md',
                expected_subject_digest=compute_verification_subject_digest(task_dir),
                evidence_dir=task_dir,
            )
            if trusted is None:
                add('TRUSTED_VERIFICATION_PASS_MISSING',
                    'CLOSING requires a trusted verification PASS bound to current review and subject digests',
                    'codex-review.md')
        except Exception as e:  # noqa: BLE001
            add('TRUSTED_VERIFICATION_CHECK_ERROR', str(e), 'codex-review.md')

    # Stable de-duplication: the same low-level issue can be found by both file and
    # transition validators; show it once to the role.
    unique: List[Dict[str, Any]] = []
    seen = set()
    for item in issues:
        key = (item.get('code'), item.get('message'), item.get('artifact'), item.get('field'))
        if key not in seen:
            seen.add(key); unique.append(item)
    return {
        'ok': not unique,
        'command': 'commit --dry-run',
        'task_id': args.task,
        'current_state': current,
        'to_state': target,
        'actor': args.actor,
        'issues': unique,
        'next_action': 'run commit without --dry-run after all ERROR items are resolved' if unique else 'ready to commit',
    }

# =============================================================================
# V5.2.3 A-03：一致性提交（备份 → 事务 → 暂存 → 原子替换 → COMMIT）
# =============================================================================

def _backup(task_dir: Path, bak_dir: Path, rel_paths: List[str]) -> None:
    """备份现有投影到 bak_dir（保持相对路径结构）。

    仅备份常规文件（目录等异常占用不备份，交由替换阶段失败并回滚）。
    原不存在的文件在恢复时按删除目标处理。
    """
    for rel in rel_paths:
        src = task_dir / rel
        if src.is_file():
            dst = bak_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _restore(task_dir: Path, bak_dir: Path, rel_paths: List[str], journal: Optional[dict] = None) -> None:
    """从备份严格恢复（Final Hardening Task 6 / P0-8）。

    统一复用 transaction_journal.strict_restore：逐文件核验 before_digest/备份存在/
    删除目标；恢复失败抛出异常（调用方必须保留 journal+backup，禁止声称恢复成功）。
    """
    if journal is not None:
        result = transaction_journal.strict_restore(task_dir, journal)
        if not result.ok:
            raise RuntimeError(
                "strict restore failed: " + "; ".join(result.failed + result.digest_mismatches)
            )
        return
    # 无 journal 的兼容路径（正常流程不触发；保留原语义）
    for rel in rel_paths:
        src = task_dir / rel
        bak = bak_dir / rel
        if bak.is_file():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak, src)
        elif src.exists():
            try:
                src.unlink()
            except OSError:
                pass


def _stage_and_replace(task_dir: Path, texts: Dict[str, str], rel_paths: List[str]) -> None:
    """写全部临时文件后逐个 os.replace 原子替换；中途失败清理未替换的临时文件。

    texts 中不存在的 rel 跳过（reconcile 修复集是动态的；commit 的 texts 恒含全部 rel）。
    """
    staged: List[Tuple[Path, Path]] = []
    try:
        for rel in rel_paths:
            if rel not in texts:
                continue
            target = task_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(texts[rel])
            staged.append((tmp, target))
        for tmp, target in staged:
            os.replace(tmp, target)
    except Exception:
        for tmp, _ in staged:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        raise


def _sha256_file(path: Path) -> Optional[str]:
    """文件字节 sha256；不存在返回 None。"""
    if not path.is_file():
        return None
    import hashlib
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _assert_task_workspace_identity(conn, task_dir: Path, task_id: str) -> None:
    """Fail closed when a canonical task directory belongs to another project root.

    This is the mutation-time defense for stale or externally corrupted registry
    state.  Custom task directories that do not prove a canonical workspace root are
    left to their existing explicit-path semantics rather than guessed about.
    """
    if not task_id:
        return
    resolved = task_dir.resolve()
    parent = resolved.parent
    if parent.name != "tasks" or parent.parent.name != ".tp-spec":
        return
    workspace_root = parent.parent.parent.resolve()
    task = conn.execute("SELECT project_id FROM task WHERE task_id=?", (task_id,)).fetchone()
    if task is None:
        return
    project_id = str(task["project_id"] or "")
    project = conn.execute("SELECT root_path FROM project WHERE project_id=?", (project_id,)).fetchone()
    stored_root = str(project["root_path"] or "").strip() if project is not None else ""
    if not stored_root or not os.path.isabs(stored_root) or not same_path(stored_root, workspace_root):
        raise ValueError(
            f"PROJECT_WORKSPACE_MISMATCH: Runtime project '{project_id}' is bound to "
            f"{stored_root or '<missing>'}, but task directory belongs to workspace {workspace_root}; "
            "refusing cross-workspace mutation"
        )


def _commit_with_recovery(task_dir: Path, conn, rel_paths: List[str], db_and_render: Callable,
                         task_id: str = "", operation: str = "commit",
                         db_state_before: str = "", target_state: str = "",
                         owner_before: str = "", owner_after: str = "",
                         flush_id: str = "") -> Dict[str, str]:
    """一致性提交核心（V5.2.3 durable journal 版）：

    1. BEGIN IMMEDIATE 获取 SQLite writer serialization；2. 读取 revision 并备份现有投影；
    3. 写 durable journal（PREPARED）；4. db_and_render(conn) 写 DB 并渲染投影；
    5. 暂存并原子替换文件；6. journal(FILES_REPLACED)；7. COMMIT；
    8. journal(DB_COMMITTED)；成功后清理并删除 journal。

    任一步失败：未提交时 ROLLBACK；只有正式投影已进入 journal 管理后才执行严格恢复。
    该机制用于进程被 kill、解释器崩溃等 process-crash recovery；由于没有对文件和目录
    执行 fsync/等价持久化屏障，不保证突然断电或存储缓存丢失后的 power-loss durability。
    返回渲染文本（供调用方打印摘要）。
    """
    tx_id = transaction_journal.new_transaction_id()
    bak_dir = task_dir / f".v511-bak-{tx_id}"
    journal: Dict[str, Any] = {}
    journal_prepared = False
    db_committed = False
    transaction_started = False
    texts: Dict[str, str] = {}

    try:
        try:
            # Acquire SQLite's single-writer lock before reading revision or copying
            # projection backups.  Concurrent writers therefore cannot prepare file
            # recovery state against a DB snapshot that another writer may advance.
            conn.execute("BEGIN IMMEDIATE")
            transaction_started = True
            _assert_task_workspace_identity(conn, task_dir, task_id)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise ValueError(
                    "TASK_WRITER_BUSY: Runtime is already being updated by another writer; retry after it finishes"
                ) from exc
            raise

        rev_before = transaction_journal.current_revision(conn, task_id)
        _backup(task_dir, bak_dir, rel_paths)
        journal = {
            "schema": JOURNAL_SCHEMA,
            "transaction_id": tx_id,
            "task_id": task_id,
            "operation": operation,
            "phase": PHASE_PREPARED,
            "db_state_before": db_state_before,
            "target_state": target_state,
            "owner_before": owner_before,
            "owner_after": owner_after,
            "flush_id": flush_id,
            "db_revision_before": rev_before,
            "expected_revision_after": None,
            "expected_event_ids": [],
            "expected_event_types": [],
            "expected_state_event_id": None,
            "expected_handoff_event_id": None,
            "backup_dir": str(bak_dir),
            "temp_dir": "",
            "files": [
                transaction_journal.make_files_entry(
                    rel_path=rel,
                    backup=str(bak_dir / rel) if (bak_dir / rel).is_file() else None,
                    temp=None,
                    before_digest=_sha256_file(bak_dir / rel),
                    target_digest=None,
                )
                for rel in rel_paths
            ],
            "created_at": dbmod.now_iso(),
            "updated_at": dbmod.now_iso(),
        }
        transaction_journal.write_journal(task_dir, journal)
        journal_prepared = True

        texts = db_and_render(conn, transaction_id=tx_id)
        journal["expected_revision_after"] = transaction_journal.current_revision(conn, task_id)
        _stage_and_replace(task_dir, texts, rel_paths)
        journal["phase"] = PHASE_FILES_REPLACED
        for entry in journal["files"]:
            entry["target_digest"] = _sha256_file(task_dir / entry["path"])
        if flush_id:
            rows = conn.execute(
                "SELECT id, event_type FROM task_event WHERE task_id=? "
                "AND detail_json LIKE ? ORDER BY id",
                (task_id, f'%"{flush_id}"%'),
            ).fetchall()
            for row in rows:
                journal["expected_event_ids"].append(row["id"])
                journal["expected_event_types"].append(row["event_type"])
                if row["event_type"] == "STATE" and journal["expected_state_event_id"] is None:
                    journal["expected_state_event_id"] = row["id"]
                if row["event_type"] == "HANDOFF" and journal["expected_handoff_event_id"] is None:
                    journal["expected_handoff_event_id"] = row["id"]
        transaction_journal.write_journal(task_dir, journal)
        conn.execute("COMMIT")
        transaction_started = False
        db_committed = True
        journal["phase"] = PHASE_DB_COMMITTED
        transaction_journal.write_journal(task_dir, journal)
    except BaseException as exc:
        if transaction_started and not db_committed:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            transaction_started = False

        if db_committed:
            raise ReconciliationRequiredError(
                f"DB committed but post-commit step failed: {exc}; "
                f"evidence preserved (journal={tx_id}, backup={bak_dir}); "
                "run 'tp-spec reconcile' to resolve"
            ) from exc

        if journal_prepared:
            try:
                _restore(task_dir, bak_dir, rel_paths, journal)
            except Exception as restore_err:
                raise ReconciliationRequiredError(
                    f"DB rolled back but file restore FAILED: {restore_err}; "
                    f"evidence preserved (journal={tx_id}, backup={bak_dir}); "
                    "run 'tp-spec reconcile' to resolve"
                ) from exc
            transaction_journal.remove_journal(task_dir, tx_id)
        else:
            # No formal projection replacement could have occurred before PREPARED;
            # cleanup only copied backup/journal preparation artifacts.
            transaction_journal.remove_journal(task_dir, tx_id)

        shutil.rmtree(bak_dir, ignore_errors=True)
        if isinstance(exc, (ValueError, EncodingValidationError)):
            raise
        raise ProjectionCommitFailedError(
            f"commit write failed and was rolled back (db restored, files restored): {exc}"
        ) from exc

    transaction_journal.remove_journal(task_dir, tx_id)
    shutil.rmtree(bak_dir, ignore_errors=True)
    return texts

def _warn_projection(warnings: List[str]) -> None:
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)


def _finalize_texts(task_dir: Path, texts: Dict[str, str], view_rel: str, render_view: Callable[[], str]) -> Dict[str, str]:
    """先行落盘非 view 投影，再渲染 view 并入 texts。

    current view 的 source_digest 基于 source_files 的最终文件内容；
    若与其他投影同批替换前渲染，会读到旧内容导致
    GENERATED_SOURCE_DIGEST_MISMATCH（PowerShell 校验器逐文件重算）。
    先替换 status/events/handoff/front matter 工件，再渲染 view，digest 才自洽。
    """
    non_view = {k: v for k, v in texts.items() if k != view_rel}
    _stage_and_replace(task_dir, non_view, list(non_view))
    texts[view_rel] = render_view()
    return texts


# =============================================================================
# commit 分支实现
# =============================================================================

def _cmd_commit_refresh(args, conn, task_dir: Path, task) -> int:
    current = task["current_state"]
    timestamp = dbmod.now_iso()
    flush_id = f"REFRESH-{uuid.uuid4().hex}"
    detail = {"flush_id": flush_id, "summary": args.summary, "operation": "ARTIFACT_REFRESH"}
    view_rel = _current_view_rel(current)

    def db_and_render(conn, transaction_id=""):
        detail.update({
            "transaction_id": transaction_id,
            "producer": "commit",
            "schema_version": ACTIVE_CONTRACT,
        })
        conn.execute(
            "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,created_at) VALUES (?,?,?,?,?,?)",
            (args.task, "ARTIFACT_REFRESH", args.actor, args.summary, json.dumps(detail, ensure_ascii=False), timestamp),
        )
        conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (timestamp, args.task))
        refreshed = conn.execute("SELECT * FROM task WHERE task_id = ?", (args.task,)).fetchone()
        status_yaml, events_jsonl, warnings = projection_cmd.render_projection(conn, refreshed)
        _warn_projection(warnings)
        return _finalize_texts(
            task_dir,
            {"status.yaml": status_yaml, "events.jsonl": events_jsonl},
            view_rel,
            lambda: _rebuild_current_view_text(task_dir, refreshed, args.summary, flush_id),
        )

    rel_paths = ["status.yaml", "events.jsonl", view_rel]
    _commit_with_recovery(task_dir, conn, rel_paths, db_and_render,
                          task_id=args.task, operation="refresh",
                          db_state_before=current, target_state=current,
                          owner_before=task["owner_role"] or "", owner_after=task["owner_role"] or "",
                          flush_id=flush_id)
    print(f"refresh: state={current}; owner={task['owner_role']}; flush_id={flush_id}")
    return 0


def _check_verification_pass_content_gate(task_dir: Path, final_crx: str, decision: str,
                                          evidence0: str) -> Optional[str]:
    """Third Hardening（P0-7）+ Fourth Hardening（P0-3/P1-2）：verification review PASS 内容门禁。

    PASS 必须：正文实质（>200 字符且含结论/证据/残余风险）+ 至少一项真实
    local_file evidence（禁止 ``--evidence none`` 绕过；PASS 不允许无真实证据）。
    失败返回错误消息（VERIFICATION_PASS_CONTENT_GATE），不产生任何写入。
    """
    if decision != "PASS":
        return None
    parts = frontmatter.split(final_crx)
    body = parts[1] if parts else ""
    if not body or len(body.strip()) < 200:
        return "codex-review body is empty or template placeholder"
    for label in ("结论", "证据", "残余风险"):
        if label not in body:
            return f"codex-review body must contain {label} section"
    if not evidence0:
        return "verification review PASS requires at least one real local_file evidence"
    from .evidence import validate_evidence_path
    check = validate_evidence_path(task_dir, evidence0, require_evidence_dir=True)
    if not check.ok:
        return f"codex-review PASS evidence invalid: {check.error}"
    return None


def _require_explicit_pass_evidence(args) -> List[str]:
    """Final Night Hardening（P0-4）：PASS 必须显式提供至少一项真实 evidence。

    禁止默认兜底 events.jsonl：调用者不传 ``--evidence`` 时不得自动使用任何
    始终存在的文件作为评审证据（证据门禁不得退化为形式检查）。
    events.jsonl、status.yaml、handoff.json 和 review artifact 均不得作为 PASS evidence；证据必须位于 evidence/。
    """
    if not (args.evidence or []):
        raise ValueError(
            "VERIFICATION_PASS_CONTENT_GATE: PASS requires at least one explicit "
            "--evidence item (defaulting to events.jsonl is forbidden; provide a "
            "real test evidence file)"
        )
    return list(args.evidence)


def _cmd_commit_review_only(args, conn, task_dir: Path, task) -> int:
    current = task["current_state"]
    timestamp = dbmod.now_iso()
    flush_id = f"REVIEW-{uuid.uuid4().hex}"
    view_rel = _current_view_rel(current)
    # Final Night Hardening（P0-4）：PASS 必须显式声明证据；非 PASS 结论无强制
    # 证据要求（front matter evidence 字段取显式声明首项，缺省为空）。
    if args.decision == "PASS":
        _require_explicit_pass_evidence(args)
    evidence0 = (args.evidence or [""])[0]
    # Third Hardening（P0-7）：prepare 阶段——先生成最终 codex-review bytes 与 digest，
    # 事件 digest 必须等于最终文件 digest（禁止先算旧文件 digest 再改 front matter）。
    intended_next = _verification_next_state(args.decision)
    final_crx = _frontmatter_text(
        task_dir / "codex-review.md",
        {"decision": args.decision, "evidence": evidence0, "timestamp": timestamp, "next_state": intended_next},
    )
    from .digest import compute_text_artifact_digest
    artifact_digest = compute_text_artifact_digest(final_crx)
    gate_error = _check_verification_pass_content_gate(task_dir, final_crx, args.decision, evidence0)
    if gate_error:
        print(f"ERROR: VERIFICATION_PASS_CONTENT_GATE: {gate_error}", file=sys.stderr)
        return 8
    # Fourth Hardening（P0-3/P1-2）：结构化 evidence（path + sha256）绑定事件
    evidence_items: List[Dict[str, Any]] = []
    if args.decision == "PASS":
        from .evidence import validate_evidence_path
        ev_check = validate_evidence_path(task_dir, evidence0, require_evidence_dir=True)
        if not ev_check.ok:
            print(f"ERROR: VERIFICATION_PASS_CONTENT_GATE: evidence invalid: {ev_check.error}", file=sys.stderr)
            return 8
        evidence_items.append(ev_check.item)
    detail = {
        "flush_id": flush_id,
        "summary": args.summary,
        "operation": "REVIEW_ONLY",
        "decision": args.decision,
        "review_kind": "VERIFICATION",
        "artifact": "codex-review.md",
        "artifact_digest": artifact_digest,
        "evidence": [evidence0],
        "evidence_items": evidence_items,
    }

    def db_and_render(conn, transaction_id=""):
        # Fourth Hardening（P0-4）：verification subject digest 统一算法——
        # acceptance.md/implementation.md/requirement-test-guide.md + 测试证据索引，
        # 排除 codex-review.md（artifact 用独立 artifact_digest）。
        from .digest import compute_verification_subject_digest, compute_text_artifact_file_digest
        detail.update({
            "transaction_id": transaction_id,
            "producer": "commit",
            "schema_version": ACTIVE_CONTRACT,
            "subject_digest": compute_verification_subject_digest(task_dir),
        })
        conn.execute(
            "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,evidence_path,created_at) VALUES (?,?,?,?,?,?,?)",
            (args.task, "REVIEW_COMPLETED", "tp-verification-engineering", args.decision, json.dumps(detail, ensure_ascii=False), evidence0, timestamp),
        )
        conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (timestamp, args.task))
        reviewed = conn.execute("SELECT * FROM task WHERE task_id = ?", (args.task,)).fetchone()
        status_yaml, events_jsonl, warnings = projection_cmd.render_projection(conn, reviewed)
        _warn_projection(warnings)
        texts = {
            "status.yaml": status_yaml,
            "events.jsonl": events_jsonl,
            "codex-review.md": final_crx,
        }
        return _finalize_texts(
            task_dir,
            texts,
            view_rel,
            lambda: _rebuild_current_view_text(task_dir, reviewed, args.summary, flush_id),
        )

    rel_paths = ["status.yaml", "events.jsonl", "codex-review.md", view_rel]
    _commit_with_recovery(task_dir, conn, rel_paths, db_and_render,
                          task_id=args.task, operation="review_only",
                          db_state_before=current, target_state=current,
                          owner_before=task["owner_role"] or "", owner_after=task["owner_role"] or "",
                          flush_id=flush_id)
    print(f"review-only: state={current}; decision={args.decision}; flush_id={flush_id}")
    return 0


def _cmd_commit_transition(args, conn, task_dir: Path, task, current: str, to: str, owner: str) -> int:
    """普通 commit 统一转调 transition_service.transition_task（唯一状态写入服务）。

    Final Hardening（Task 2）：不再复制 STATE/HANDOFF/UPDATE/投影写入逻辑，所有
    状态转换（normal commit / admin recovery / 合法状态操作）共用同一实现。
    """
    from .transition_service import transition_task
    timestamp = dbmod.now_iso()
    extra_detail = {
        "changes": args.change or [],
        "risks": args.risk or [],
        "authorization": args.authorization or "",
        "database_verification": args.database_verification or "",
        "decision": args.decision or "",
    }
    # 附加治理事件（与 STATE/HANDOFF 同一事务、同一 transaction_id）
    extra_events = []
    if args.phase_exit:
        extra_events.append({"type": "PHASE_EXIT"})
    if args.direct_change:
        extra_events.append({"type": "DECISION", "summary": "DIRECT_CHANGE"})
    if args.actor == "tp-verification-engineering" and args.decision == "PASS":
        # Fourth Hardening（P0-3/P1-2）：transition 路径同样强制 verification PASS
        # 内容门禁（真实 local_file evidence，禁止 --evidence none / 无证据绕过）。
        _crx_path = task_dir / "codex-review.md"
        if not _crx_path.is_file():
            raise ValueError("VERIFICATION_PASS_CONTENT_GATE: codex-review.md missing")
        _gate_crx = _read(_crx_path)
        # Final Night Hardening（P0-4）：PASS 必须显式提供证据，禁止 events.jsonl 默认兜底
        _require_explicit_pass_evidence(args)
        _gate_ev = args.evidence[0]
        _gate_err = _check_verification_pass_content_gate(task_dir, _gate_crx, "PASS", _gate_ev)
        if _gate_err:
            raise ValueError(f"VERIFICATION_PASS_CONTENT_GATE: {_gate_err}")
        # Third Hardening（P0-7）+ Fourth Hardening（P0-3/P0-4）：
        # REVIEW_COMPLETED(VERIFICATION PASS) 携带完整身份链（review_kind/
        # artifact_digest/subject_digest/evidence_items），CLOSING 门禁据此绑定
        # 当前 codex-review.md 与受评审内容（acceptance/implementation/test-guide/
        # 测试证据索引），排除 codex-review.md。
        from .digest import compute_verification_subject_digest, compute_text_artifact_file_digest
        _ev0 = args.evidence[0]
        _evidence_items: List[Dict[str, Any]] = []
        from .evidence import validate_evidence_path
        _ev_check = validate_evidence_path(task_dir, _ev0, require_evidence_dir=True)
        if _ev_check.ok:
            _evidence_items.append(_ev_check.item)
        extra_events.append({
            "type": "REVIEW_COMPLETED",
            "actor": "tp-verification-engineering",
            "summary": "PASS",
            "evidence_path": _ev0,
            "detail_extra": {
                "review_kind": "VERIFICATION",
                "artifact": "codex-review.md",
                "artifact_digest": compute_text_artifact_file_digest(_crx_path),
                "subject_digest": compute_verification_subject_digest(task_dir),
                "decision": "PASS",
                "evidence": list(args.evidence),
                "evidence_items": _evidence_items,
            },
        })
    fm_rel = _fm_artifact_rel(args, current, to)
    frontmatter_updates = {}
    if fm_rel:
        fm_values = {"status": "ready", "intended_next": to,
                     "declared_by": args.actor, "declared_at": timestamp}
        frontmatter_updates[fm_rel] = fm_values

    result = transition_task(
        task_id=args.task,
        task_dir=task_dir,
        to_state=to,
        actor=args.actor,
        summary=args.summary,
        evidence=args.evidence,
        source_command="commit",
        conn=conn,
        extra_detail=extra_detail,
        extra_events=extra_events,
        frontmatter_updates=frontmatter_updates,
        handoff_args=args,
        on_projection_warnings=_warn_projection,
    )
    if not result.ok:
        raise ValueError(result.message)
    print(f"commit: {current} -> {to}; owner={owner}; flush_id={result.flush_id}")
    return 0


def cmd_commit(args) -> int:
    # V5.2.3 A-05：payload-json 合并先于一切校验（稳定 UTF-8 输入通道）
    if getattr(args, "payload_json", None):
        args = _apply_payload(args, _load_payload(args.payload_json))
    if not args.summary and not getattr(args, "dry_run", False):
        if getattr(args, "refresh", False):
            # refresh 是 Runtime 自身的确定性投影重建动作，不承载业务决策。
            # 缺省 summary 由 Runtime 生成，避免调用者为无业务语义字段反复试错。
            args.summary = "refresh generated projections"
        else:
            raise ValueError("--summary is required (or provide \"summary\" in --payload-json)")
    if not args.summary and getattr(args, "dry_run", False):
        args.summary = "preflight only"
    _validate_utf8_inputs(args)
    if args.actor not in _ALLOWED_ACTORS:
        raise ValueError("unsupported actor")
    task_dir = Path(args.task_dir).resolve()
    if not args.refresh and not args.review_only and not args.to:
        raise ValueError("--to is required unless --refresh or --review-only is used")
    if (args.refresh or args.review_only) and args.to:
        raise ValueError("--refresh/--review-only cannot be combined with --to")
    if args.refresh and args.review_only:
        raise ValueError("--refresh cannot be combined with --review-only")
    if args.phase_exit and (args.refresh or args.review_only):
        raise ValueError("--phase-exit is a formal transition and requires --to")
    if not getattr(args, "dry_run", False):
        if _artifact_version(task_dir) != ACTIVE_CONTRACT:
            raise ValueError(f"commit only supports artifact_contract.version={ACTIVE_CONTRACT}; legacy contracts are frozen static archives")
        _validate_db_requirement(task_dir, args)
    db_path = dbmod.resolve_db_path(args.db, task_id=args.task)
    if not os.path.isfile(db_path):
        raise ValueError(f"v{ACTIVE_CONTRACT} commit requires an initialized SQLite DB. commit/--refresh are audited Runtime writes: they may write SQLite governance events; the prohibition is only against direct/manual SQLite edits. Resolve the registered DB or pass --db explicitly.")
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (args.task,)).fetchone()
        if task is None:
            raise ValueError(f"task not found in DB: {args.task}")
        if event_policies.is_task_retired(conn, args.task):
            raise ValueError("retired historical tasks are immutable archives")
        if getattr(args, "dry_run", False):
            report = _collect_commit_preflight(task_dir, args, conn, task)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report.get("ok") else 7
        current = task["current_state"]
        if args.refresh:
            if args.actor != task["owner_role"]:
                raise ValueError("--refresh may only be submitted by the current owner")
            _preflight_files(task_dir, args, current, current)
            return _cmd_commit_refresh(args, conn, task_dir, task)
        if args.review_only:
            # V5.2.3：tp-验收工程 在 VERIFYING 记录独立验收结论，不流转、不结单。
            if args.actor != "tp-verification-engineering":
                raise ValueError("--review-only is reserved for tp-verification-engineering")
            if current != "VERIFYING":
                raise ValueError("--review-only may only be recorded in VERIFYING")
            if not args.decision:
                raise ValueError("--review-only requires --decision")
            _preflight_files(task_dir, args, current, current)
            return _cmd_commit_review_only(args, conn, task_dir, task)
        wf = load_workflow()
        if not wf.is_valid_transition(current, args.to):
            raise ValueError(f"invalid transition {current} -> {args.to}")
        owner = wf.get_state_owner(args.to) or wf.get_completion_owner(task["risk_level"], task["flow_level"])
        if args.to == "COMPLETED":
            owner = "tp-delivery-convergence"
        if not owner:
            raise ValueError(f"no owner for target state {args.to}")
        # Hardening（审查报告 P0-3）：正式 transition 的提交者必须等于当前
        # 状态 owner（离开方），防止非 canonical owner 伪造推进。CLOSING/COMPLETED
        # 由专门角色负责，沿用下方专门校验。
        if args.to not in {"CLOSING", "COMPLETED"}:
            if args.actor != (task["owner_role"] or ""):
                raise ValueError(
                    f"actor mismatch: only the current owner {task['owner_role']!r} may "
                    f"advance state {current} -> {args.to} (got {args.actor!r})"
                )
        if args.to == "CLOSING":
            # V5.2.3 personal mode：只有 tp-交付收敛可以进入 CLOSING；依赖自动质量门禁。
            if args.actor != "tp-delivery-convergence":
                raise ValueError("only tp-delivery-convergence may enter CLOSING (V5.2.3 closing chain)")
        if args.to == "COMPLETED" and current != "CLOSING":
            raise ValueError(f"v{ACTIVE_CONTRACT} completion must be committed from CLOSING")
        if args.to == "COMPLETED" and args.actor != "tp-delivery-convergence":
            raise ValueError("only tp-delivery-convergence may commit COMPLETED (V5.2.3 closing chain)")
        if args.phase_exit and args.actor != task["owner_role"]:
            raise ValueError("--phase-exit may only be submitted by the current owner")
        if args.direct_change:
            if args.actor != "tp-verification-engineering" or not args.authorization:
                raise ValueError("DIRECT_CHANGE requires tp-verification-engineering actor and explicit --authorization")
        if args.actor == "tp-verification-engineering" and args.decision != "PASS" and args.to in {"CLOSING", "COMPLETED"}:
            raise ValueError("tp-verification-engineering must supply --decision PASS before downstream closure")
        # A-02：preflight 文件侧（业务规则全部通过后、任何写入前）
        _preflight_files(task_dir, args, current, args.to)
        # V5.2.3 §10.1：阶段 preflight hook（真实业务 validator，任何写入之前）
        preflight_result = run_transition_preflight(
            args.task, current, args.to, args.actor,
            task_dir=task_dir, conn=conn,
        )
        if not getattr(preflight_result, "ok", False):
            errors = getattr(preflight_result, "errors", []) or []
            raise ValueError("transition preflight failed: " + "; ".join(errors))
        # Third Hardening（P0-7）+ Fourth Hardening（P0-4）：删除三元组 SQL，
        # 改走统一可信事件门禁——REVIEW_COMPLETED(VERIFICATION PASS) 必须绑定当前
        # codex-review.md artifact digest + 当前 verification subject digest
        # （acceptance/implementation/test-guide/证据索引）+ 结构化证据链。
        if args.to == "CLOSING":
            from .digest import compute_verification_subject_digest, compute_text_artifact_file_digest
            trusted_review = event_policies.load_trusted_governance_event(
                conn, args.task,
                event_type="REVIEW_COMPLETED",
                actor="tp-verification-engineering",
                decision="PASS",
                review_kind="VERIFICATION",
                artifact_path=task_dir / "codex-review.md",
                expected_subject_digest=compute_verification_subject_digest(task_dir),
                evidence_dir=task_dir,
            )
            if trusted_review is None:
                raise ValueError(
                    "CLOSING requires a trusted tp-verification-engineering REVIEW_COMPLETED PASS "
                    "bound to the current codex-review.md and verification subject (acceptance/"
                    "implementation/test-guide/evidence digest chain)"
                )
        return _cmd_commit_transition(args, conn, task_dir, task, current, args.to, owner)
    finally:
        conn.close()


def add_commit_subparsers(parser: argparse.ArgumentParser) -> None:
    p = parser.add_parser(
        "commit",
        help=f"Commit a v{ACTIVE_CONTRACT} handoff through the SQLite ledger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "--payload-json schema (UTF-8 JSON object):\n"
            "  scalar strings: summary, decision, authorization\n"
            "  string arrays:  changes, risks, evidence, action, constraint\n"
            "  decision values: PASS | FAIL | NEEDS_FIX\n"
            "Example: {\"summary\":\"done\",\"changes\":[\"x\"],"
            "\"constraint\":[\"keep compatibility\"]}\n"
            "Note: --refresh may omit --summary; Runtime records the deterministic summary "
            "'refresh generated projections'."
        ),
    )
    p.add_argument("--task", required=True)
    p.add_argument("--task-dir", required=True)
    p.add_argument("--actor", required=True, choices=sorted(_ALLOWED_ACTORS))
    p.add_argument("--to")
    p.add_argument("--refresh", action="store_true", help="Record ARTIFACT_REFRESH and rebuild the current generated view without a state transition")
    p.add_argument("--review-only", action="store_true", help="tp-verification-engineering only: record REVIEW_COMPLETED and codex-review.md metadata in VERIFYING without a state transition")
    p.add_argument("--phase-exit", action="store_true", help="Mark this transition as the one-shot phase-exit summary of the current owner's micro-loop work")
    p.add_argument("--dry-run", action="store_true", help="Read-only phase-exit preflight; report all detectable blockers as JSON without writing DB/files")
    # V5.2.3 A-05：--summary 改为可选（--payload-json 可提供）；稳定性由 cmd_commit 强制
    p.add_argument("--summary")
    p.add_argument("--change", action="append")
    p.add_argument("--risk", action="append")
    p.add_argument("--evidence", action="append")
    p.add_argument("--action", action="append")
    p.add_argument("--constraint", action="append")
    p.add_argument("--decision", choices=["PASS", "FAIL", "NEEDS_FIX"])
    p.add_argument("--authorization")
    p.add_argument("--database-verification", choices=["NONE", "READ", "DDL", "DML"])
    p.add_argument("--direct-change", action="store_true")
    p.add_argument(
        "--payload-json",
        help=("V5.2.3 UTF-8 JSON file; summary/decision/authorization are strings; "
              "changes/risks/evidence/action/constraint are arrays of strings"),
    )
    p.add_argument("--db")
    p.set_defaults(func=cmd_commit)
