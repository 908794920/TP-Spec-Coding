# -*- coding: utf-8 -*-
"""架构评审正式执行链（Hardening P0-2/P0-6）。

依据：《V5.2.5 执行AI统一修复与自验证任务》§7 与《V5.2.5 源码级发布审查报告》
P0-2（无架构评审可 DEVELOPING）/P0-6（新增角色不能通过正式 CLI 执行）。

提供 ``tp-spec review record``：
- 由 ``tp-software-architect`` 写入 ``REVIEW_COMPLETED`` 事件（detail 含
  review_kind=ARCHITECTURE、round、artifact、artifact_digest、design_digest、
  requirement_decisions_digest、findings_count、evidence、transaction_id）；
- 同步更新 ``architecture-review.md`` front matter（review.decision/round/
  reviewed_at/evidence/findings_count）；
- 经 durable journal + projection 原子提交（复用 transaction_commit._commit_with_recovery），
  失败保留恢复依据，不产生半提交。

Architecture Review 是风险触发的历史事实，不是 DEVELOPING 许可证。
事件仍绑定 review artifact / subject / evidence digest 以便审计，但后续文本变化
不会自动阻止开发；是否需要重新评审由实际风险和变更语义决定。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db as dbmod
from . import event_policies
from . import frontmatter
from . import projection_cmd
from . import transaction_journal
from .digest import compute_architecture_subject_digest
from .transaction_commit import (
    _commit_with_recovery,
    _current_view_rel,
    _finalize_texts,
    _probe_writable,
    _rebuild_current_view_text,
)
from .frontmatter import FrontMatterError
from .version import active_version
from .workflow_loader import load_workflow


ACTIVE_CONTRACT = active_version()
_REVIEW_ACTORS = {"tp-software-architect", "tp-code-reviewer"}
_DECISIONS = ("PASS", "REVISE", "BLOCKED", "NEEDS_FIX", "FAIL")
_ARCHITECTURE_DECISIONS = {"PASS", "REVISE", "BLOCKED"}
_CODE_REVIEW_DECISIONS = {"PASS", "NEEDS_FIX", "FAIL", "REVISE", "BLOCKED"}


def _read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(_read(path).encode("utf-8")).hexdigest()


def _design_digest(task_dir: Path) -> str:
    """设计/受评审内容 digest。

    Third Hardening（P0-2）：统一为 ``cli.digest.compute_architecture_subject_digest``
    （含 task/knowledge/clarifications/decisions/test-guide/acceptance），
    review record 与 transition gate 共用同一算法；排除 implementation.md。
    """
    return compute_architecture_subject_digest(task_dir)


def _set_nested_frontmatter(text: str, parent: str, values: Dict[str, str]) -> str:
    """在 front matter 的嵌套块（如 review:）内替换指定 key（格式保真）。

    仅修改 parent 块内缩进为 parent+2 的 key 行；key 不存在则跳过（不新增，
    避免破坏模板结构）。返回新文本；front matter 缺失/损坏抛 FrontMatterError。
    """
    parts = frontmatter.split(text)
    if parts is None:
        raise FrontMatterError("missing or invalid YAML front matter")
    front, rest, eol = parts
    lines = front.splitlines()
    parent_re = re.compile(r"^" + re.escape(parent) + r":\s*$")
    out: List[str] = []
    in_parent = False
    parent_indent: Optional[int] = None
    for line in lines:
        if parent_re.match(line):
            in_parent = True
            parent_indent = 0
            out.append(line)
            continue
        if in_parent:
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                in_parent = False
            else:
                # parent 块内：匹配 parent+2 缩进的 key 行
                key = line.strip().split(":", 1)[0].strip()
                if key in values:
                    val = json.dumps(values[key], ensure_ascii=False)
                    out.append("  " + key + ": " + val)
                    continue
        out.append(line)
    new_front = "\n".join(out)
    # 用 frontmatter.split 的 eol 拼回：保留 BOM 与正文原样
    bom = ""
    if text.startswith("\ufeff"):
        bom = "\ufeff"
        text_no_bom = text[1:]
    else:
        text_no_bom = text
    head = bom + "---" + eol + new_front
    # 需要保留 opening/closing delimiter 的原始 EOL：重新提取
    m = frontmatter.FRONTMATTER_RE.match(text_no_bom)
    if m is None:
        raise FrontMatterError("missing or invalid YAML front matter")
    pre_close = m.group("pre_close_eol")
    close = m.group("close_eol")
    return head + pre_close + "---" + close + rest


def _build_review_artifact_text(text: str, decision: str, round_no: int,
                                reviewed_at: str, evidence: List[str],
                                findings_count: int) -> str:
    """生成 review record 最终 architecture-review.md 全文（纯函数，不写盘）。

    Final Hardening（Task 3）：prepare 阶段生成最终字节，事务内原子替换；
    禁止在 DB 提交后再改写 artifact。
    """
    if not frontmatter.has(text):
        raise ValueError("architecture-review.md is missing YAML front matter")
    values = {
        "decision": decision,
        "round": round_no,
        "reviewed_at": reviewed_at,
        "evidence": evidence,
        "findings_count": findings_count,
    }
    new_text = _set_nested_frontmatter(text, "review", values)
    # 顶层 status 同步 decision（非 PASS → draft；PASS → review-passed）
    top_status = "review-passed" if decision == "PASS" else "draft"
    try:
        new_text = frontmatter.set_value(new_text, "status", top_status)
    except FrontMatterError:
        pass
    return new_text


def _update_review_artifact(task_dir: Path, decision: str, round_no: int,
                            reviewed_at: str, evidence: List[str],
                            findings_count: int) -> None:
    """改写 architecture-review.md front matter（review 嵌套块）。"""
    path = task_dir / "architecture-review.md"
    text = _read(path)
    new_text = _build_review_artifact_text(text, decision, round_no, reviewed_at, evidence, findings_count)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(new_text)




def _validate_review_isolation(*, design_context_id: str, review_context_id: str,
                               context_policy: str, subject_digest: str) -> Optional[str]:
    """Validate the formal architecture-review isolation proof.

    Review identity stays the formal Software Architect role; independence is
    proven by distinct execution contexts and a bound subject digest rather
    than by inventing a second permanent role.
    """
    if str(context_policy or "").strip().lower() != "isolated":
        return "formal architecture review requires context_policy=isolated"
    design_id = str(design_context_id or "").strip()
    review_id = str(review_context_id or "").strip()
    if not design_id or not review_id:
        return "formal architecture review requires design and review execution context ids"
    if design_id == review_id:
        return "formal architecture review requires distinct design and review execution contexts"
    if not str(subject_digest or "").strip():
        return "formal architecture review requires a non-empty subject digest"
    return None


def _check_pass_content_gate(task_dir: Path, artifact_text: str, args, task) -> Optional[str]:
    """PASS 内容门禁（任务书 §5.4/P0-5）：空模板、无证据、blocking finding、
    错误阶段、错误 actor、blocking clarification 一律拒绝 PASS。返回错误消息或 None。
    """
    if args.decision != "PASS":
        return None
    state = str(task["current_state"] or "")
    # Record-first review is an optional risk tool while work is live, not a
    # permission state. Legacy design states remain accepted for migrated/recovery tasks.
    allowed = {
        "NEW", "ACTIVE", "RISK_ANALYZING", "REQUIREMENT_CLARIFYING", "TECHNICAL_DISCOVERY",
        "TECH_DESIGNING", "PRODUCT_DESIGNING", "PRODUCT_CONFIRMING",
        "DISCOVERY_REVIEW_REQUIRED", "CHANGE_CONFIRMING",
    }
    if state not in allowed:
        return f"architecture review cannot be recorded from terminal/non-work state {state}"
    if args.actor != "tp-software-architect":
        return "architecture review PASS requires actor tp-software-architect"
    isolation_error = _validate_review_isolation(
        design_context_id=getattr(args, "design_context_id", ""),
        review_context_id=getattr(args, "review_context_id", ""),
        context_policy=getattr(args, "context_policy", ""),
        subject_digest=_design_digest(task_dir),
    )
    if isolation_error:
        return isolation_error
    # artifact 非模板：正文实质内容 + 不再含模板占位符
    parts = frontmatter.split(artifact_text)
    body = parts[1] if parts else ""
    if not body or len(body.strip()) < 200:
        return "architecture-review body is empty or template placeholder"
    if "DRAFT / PASS / REVISE / BLOCKED" in body:
        return "architecture-review body is still template placeholder (decision block unfilled)"
    # 所有检查项有明确结论：'## 检查项结论' 段不得留有未填写项
    section = re.search(r"## 检查项结论\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    if not section:
        return "architecture-review lacks '检查项结论' section"
    unanswered = [
        line for line in section.group(1).splitlines()
        if re.search(r"[:：]\s*($|是 / 否 / 部分|是否存在)", line)
    ]
    if unanswered:
        return "architecture-review has unanswered check items"
    # evidence 至少一项且全部为真实 local_file（Fourth Hardening P0-2/P1-2）
    if not (args.evidence or []):
        return "PASS requires at least one evidence item"
    from .evidence import validate_evidence_path
    for ev in args.evidence:
        check = validate_evidence_path(task_dir, ev, require_evidence_dir=True)
        if not check.ok:
            return f"architecture review PASS evidence invalid: {check.error}"
    # blocking finding 为零
    try:
        if int(args.findings_count or 0) > 0:
            return "PASS requires zero blocking findings"
    except (TypeError, ValueError):
        return "findings_count must be an integer"
    # design digest 非空
    if not _design_digest(task_dir):
        return "design digest must not be empty"
    # 不存在 blocking clarification
    cl_path = task_dir / "requirement-clarifications.md"
    if cl_path.is_file():
        try:
            from .artifact_validation import YamlValidationError, parse_frontmatter_yaml
            cl = parse_frontmatter_yaml(_read(cl_path), "requirement-clarifications.md")
            bo = cl.get("blocking_open")
            if bo is not None:
                try:
                    if int(bo) > 0:
                        return "blocking clarification is open; cannot PASS"
                except (TypeError, ValueError):
                    return "blocking clarification blocking_open is invalid"
        except YamlValidationError as e:
            return f"requirement-clarifications.yaml invalid: {e}"
    return None




def _code_review_subject_digest(task_dir: Path) -> str:
    from .digest import compute_verification_subject_digest
    return compute_verification_subject_digest(task_dir)


def _cmd_code_review_record(args) -> int:
    """Record a trusted CODE/IMPLEMENTATION/ULTRA_REVIEW result.

    Code review is a professional judgement over the current technical subject,
    not an architecture artifact mutation.  The Runtime therefore writes a
    compact machine result under .execution/<TASK>/review/ and binds the
    REVIEW_COMPLETED event to that artifact + current subject digest.
    """
    task_id = args.task
    task_dir = Path(args.task_dir).resolve()
    if not task_dir.is_dir():
        print(f"ERROR: task-dir not found: {task_dir}", file=sys.stderr)
        return 4
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        print("ERROR: task directory has no status.yaml", file=sys.stderr)
        return 4
    if args.actor != "tp-code-reviewer":
        print("ERROR: code review requires actor tp-code-reviewer", file=sys.stderr)
        return 8
    if str(args.decision).upper() not in _CODE_REVIEW_DECISIONS:
        print(f"ERROR: unsupported code review decision: {args.decision}", file=sys.stderr)
        return 8

    status_text = _read(status_path)
    m = re.search(r"(?ms)^artifact_contract:\s*\n\s+version:\s*[\"']?([^\"'\n#]+)", status_text)
    contract_version = m.group(1).strip() if m else ""
    if contract_version != ACTIVE_CONTRACT:
        print(
            f"ERROR: legacy contract task is a frozen static archive; review record requires artifact_contract.version={ACTIVE_CONTRACT}",
            file=sys.stderr,
        )
        return 4

    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    if not Path(db_path).is_file():
        print(f"ERROR: v{ACTIVE_CONTRACT} review record requires an initialized SQLite DB", file=sys.stderr)
        return 4
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found in DB: {task_id}", file=sys.stderr)
            return 4
        if event_policies.is_task_retired(conn, task_id):
            print("ERROR: retired historical tasks are immutable archives", file=sys.stderr)
            return 5
        if (task["base_version"] or "") != ACTIVE_CONTRACT:
            print("ERROR: legacy contract task is a frozen static archive", file=sys.stderr)
            return 4
        if str(task["current_state"] or "") in {"COMPLETED", "CANCELLED"}:
            print("ERROR: code review cannot be recorded on a terminal task", file=sys.stderr)
            return 5

        timestamp = dbmod.now_iso()
        flush_id = f"REVIEW-{uuid.uuid4().hex}"
        subject_digest = _code_review_subject_digest(task_dir)
        evidence = list(args.evidence or [])
        evidence_items: List[Dict[str, str]] = []
        if evidence:
            from .evidence import validate_evidence_path
            for ev in evidence:
                checked = validate_evidence_path(task_dir, ev, require_evidence_dir=True)
                if not checked.ok:
                    print(f"ERROR: code review evidence invalid: {checked.error}", file=sys.stderr)
                    return 8
                evidence_items.append(dict(checked.item))

        result_payload = {
            "schema": "tp-spec.code-review-result/v1",
            "task_id": task_id,
            "review_kind": str(args.kind).upper(),
            "actor_role": args.actor,
            "decision": str(args.decision).upper(),
            "round": int(args.round or 1),
            "findings_count": int(args.findings_count or 0),
            "summary": str(args.summary or ""),
            "subject_digest": subject_digest,
            "evidence": evidence,
            "recorded_at": timestamp,
        }
        canonical = json.dumps(result_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        artifact_rel = f".execution/{task_id}/review/result-{result_id}.json"
        artifact_text = json.dumps(result_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        from .digest import compute_text_artifact_digest
        artifact_digest = compute_text_artifact_digest(artifact_text)

        detail = {
            "flush_id": flush_id,
            "review_kind": str(args.kind).upper(),
            "round": int(args.round or 1),
            "artifact": artifact_rel,
            "artifact_digest": artifact_digest,
            "subject_digest": subject_digest,
            "findings_count": int(args.findings_count or 0),
            "decision": str(args.decision).upper(),
            # REVIEW_COMPLETED keeps an evidence identity field.  When the
            # reviewer has no separate evidence file, the machine review result
            # itself is the durable review evidence.
            "evidence": evidence or [artifact_rel],
            "evidence_items": evidence_items,
            "summary": str(args.summary or ""),
            "transaction_id": "",
            "producer": "review_record",
            "schema_version": ACTIVE_CONTRACT,
        }
        view_rel = _current_view_rel(task["current_state"])

        def db_and_render(conn, transaction_id=""):
            detail["transaction_id"] = transaction_id
            conn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,evidence_path,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    task_id,
                    "REVIEW_COMPLETED",
                    args.actor,
                    str(args.decision).upper(),
                    json.dumps(detail, ensure_ascii=False),
                    evidence[0] if evidence else artifact_rel,
                    timestamp,
                ),
            )
            conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (timestamp, task_id))
            refreshed = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
            status_yaml, events_jsonl, warnings = projection_cmd.render_projection(conn, refreshed)
            for warning in warnings:
                print(f"WARN: {warning}", file=sys.stderr)
            return _finalize_texts(
                task_dir,
                {
                    "status.yaml": status_yaml,
                    "events.jsonl": events_jsonl,
                    artifact_rel: artifact_text,
                },
                view_rel,
                lambda: _rebuild_current_view_text(task_dir, refreshed, args.summary, flush_id),
            )

        rel_paths = ["status.yaml", "events.jsonl", artifact_rel, view_rel]
        _commit_with_recovery(
            task_dir, conn, rel_paths, db_and_render,
            task_id=task_id, operation="review_record",
            db_state_before=task["current_state"], target_state=task["current_state"],
            owner_before=task["owner_role"] or "", owner_after=task["owner_role"] or "",
            flush_id=flush_id,
        )
        print(
            f"review record: {str(args.kind).upper()} decision={str(args.decision).upper()} "
            f"round={args.round} subject_digest={subject_digest[:12]}... flush_id={flush_id}"
        )
        return 0
    finally:
        conn.close()

def cmd_review_record(args) -> int:
    """Record a formal architecture or code-review result."""
    kind = str(args.kind or "").upper()
    if kind in {"CODE", "IMPLEMENTATION", "ULTRA_REVIEW"}:
        return _cmd_code_review_record(args)
    if kind != "ARCHITECTURE":
        print(f"ERROR: unsupported review kind: {args.kind}", file=sys.stderr)
        return 8
    if args.actor != "tp-software-architect":
        print("ERROR: architecture review requires actor tp-software-architect", file=sys.stderr)
        return 8
    if str(args.decision).upper() not in _ARCHITECTURE_DECISIONS:
        print(f"ERROR: unsupported architecture review decision: {args.decision}", file=sys.stderr)
        return 8
    task_id = args.task
    task_dir = Path(args.task_dir).resolve()
    if not task_dir.is_dir():
        print(f"ERROR: task-dir not found: {task_dir}", file=sys.stderr)
        return 4
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        print(f"ERROR: task directory has no status.yaml", file=sys.stderr)
        return 4
    status_text = _read(status_path)
    m = re.search(r"(?ms)^artifact_contract:\s*\n\s+version:\s*[\"']?([^\"'\n#]+)", status_text)
    contract_version = m.group(1).strip() if m else ""
    if contract_version != ACTIVE_CONTRACT:
        print(f"ERROR: legacy contract task is a frozen static archive; review record requires artifact_contract.version={ACTIVE_CONTRACT}", file=sys.stderr)
        return 4
    artifact_rel = args.artifact or "architecture-review.md"
    artifact_path = task_dir / artifact_rel
    if not artifact_path.is_file():
        print(f"ERROR: review artifact not found: {artifact_rel}", file=sys.stderr)
        return 4
    if not frontmatter.has(_read(artifact_path)):
        print(f"ERROR: review artifact is missing YAML front matter: {artifact_rel}", file=sys.stderr)
        return 4
    # task 在 DB 中存在且为活动契约
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    if not Path(db_path).is_file():
        print(f"ERROR: v{ACTIVE_CONTRACT} review record requires an initialized SQLite DB", file=sys.stderr)
        return 4
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found in DB: {task_id}", file=sys.stderr)
            return 4
        if event_policies.is_task_retired(conn, task_id):
            print("ERROR: retired historical tasks are immutable archives", file=sys.stderr)
            return 5
        if (task["base_version"] or "") != ACTIVE_CONTRACT:
            print(f"ERROR: legacy contract task is a frozen static archive", file=sys.stderr)
            return 4
        # ---- Task 3 Prepare 阶段：先计算最终 artifact 字节与全部 digest ----
        timestamp = dbmod.now_iso()
        flush_id = f"REVIEW-{uuid.uuid4().hex}"
        evidence = args.evidence or []
        from . import context_usage as context_usage_mod
        decoded_usage, parse_warnings = context_usage_mod.parse_context_usage_json(args.context_usage_json)
        context_usage_mod.emit_warnings(parse_warnings)
        usage, usage_warnings = context_usage_mod.normalize_context_usage(decoded_usage)
        context_usage_mod.emit_warnings(usage_warnings)
        final_artifact_text = _build_review_artifact_text(
            _read(artifact_path), args.decision, args.round, timestamp, evidence, args.findings_count,
        )
        from .digest import compute_text_artifact_digest
        artifact_digest = compute_text_artifact_digest(final_artifact_text)
        design_digest = _design_digest(task_dir)
        decisions_digest = ""
        dp = task_dir / "requirement-decisions.md"
        if dp.is_file():
            decisions_digest = _file_sha256(dp)
        # PASS 内容门禁（§5.4/P0-5 + Fourth Hardening P0-2）：失败则零写入
        # （DB 未动、无事件、artifact 未改）。PASS 必须至少一项真实 local_file 证据。
        gate_error = _check_pass_content_gate(task_dir, final_artifact_text, args, task)
        if gate_error:
            print(f"ERROR: REVIEW_PASS_CONTENT_GATE: {gate_error}", file=sys.stderr)
            return 8
        # Fourth Hardening（P0-2）：结构化 evidence（path + sha256）绑定事件，
        # 证据删除/替换使旧 PASS 失效（门禁侧按 detail.evidence_items 校验）。
        # 若证据就是本次被改写的 artifact 自身，digest 必须绑定最终字节
        # （与 artifact_digest 一致），否则事件↔文件 digest 会漂移。
        evidence_items: List[Dict[str, str]] = []
        if args.decision == "PASS":
            from .evidence import validate_evidence_path
            for ev in evidence:
                ev_check = validate_evidence_path(task_dir, ev, require_evidence_dir=True)
                if not ev_check.ok:
                    print(f"ERROR: REVIEW_PASS_CONTENT_GATE: evidence invalid: {ev_check.error}", file=sys.stderr)
                    return 8
                evidence_items.append(dict(ev_check.item))
        detail = {
            "flush_id": flush_id,
            "review_kind": args.kind,
            "round": args.round,
            "artifact": artifact_rel,
            "artifact_digest": artifact_digest,  # normalized text digest; CRLF/BOM rewrites do not invalidate PASS
            "design_digest": design_digest,
            "subject_digest": design_digest,  # INV-03：subject/design digest 绑定受评审内容
            "review_subject_digest": design_digest,
            "context_policy": getattr(args, "context_policy", "isolated"),
            "design_execution_context_id": getattr(args, "design_context_id", ""),
            "review_execution_context_id": getattr(args, "review_context_id", ""),
            "requirement_decisions_digest": decisions_digest,
            "findings_count": args.findings_count,
            "decision": args.decision,
            "evidence": evidence,
            "evidence_items": evidence_items,  # Fourth Hardening P0-2：结构化证据链
            "summary": args.summary,
            # Final Hardening（INV-03/§8.1）：transaction_id 由 _commit_with_recovery
            # 内部事务生成并在 db_and_render 内注入，形成事件↔journal↔DB 身份链。
            "transaction_id": "",
            "producer": "review_record",
            "schema_version": ACTIVE_CONTRACT,
        }
        if usage:
            detail["context_usage"] = usage
        view_rel = _current_view_rel(task["current_state"])

        # ---- Task 3 Transaction 阶段：同一 durable transaction 处理
        # artifact + 事件 + 投影 + journal/backup（禁止 DB 提交后再改 artifact）----
        def db_and_render(conn, transaction_id=""):
            detail["transaction_id"] = transaction_id
            conn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,evidence_path,created_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, "REVIEW_COMPLETED", args.actor, args.decision, json.dumps(detail, ensure_ascii=False), evidence[0] if evidence else None, timestamp),
            )
            conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (timestamp, task_id))
            refreshed = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
            status_yaml, events_jsonl, warnings = projection_cmd.render_projection(conn, refreshed)
            for w in warnings:
                print(f"WARN: {w}", file=sys.stderr)
            return _finalize_texts(
                task_dir,
                {"status.yaml": status_yaml, "events.jsonl": events_jsonl,
                 artifact_rel: final_artifact_text},
                view_rel,
                lambda: _rebuild_current_view_text(task_dir, refreshed, args.summary, flush_id),
            )

        rel_paths = ["status.yaml", "events.jsonl", artifact_rel, view_rel]
        _commit_with_recovery(
            task_dir, conn, rel_paths, db_and_render,
            task_id=task_id, operation="review_record",
            db_state_before=task["current_state"], target_state=task["current_state"],
            owner_before=task["owner_role"] or "", owner_after=task["owner_role"] or "",
            flush_id=flush_id,
        )
        print(f"review record: {args.kind} decision={args.decision} round={args.round} "
              f"design_digest={design_digest[:12]}... flush_id={flush_id}")
        return 0
    finally:
        conn.close()


def add_review_subparsers(subparsers) -> None:
    p = subparsers.add_parser("review", help="V5.2.5: formal architecture/code review commands")
    sub = p.add_subparsers(dest="subcommand", required=True)

    pr = sub.add_parser("record", help="Record a formal ARCHITECTURE or CODE review decision")
    pr.add_argument("--task", required=True, help="task id")
    pr.add_argument("--task-dir", required=True, help="task directory path")
    pr.add_argument("--actor", required=True, choices=sorted(_REVIEW_ACTORS), help="formal review actor")
    pr.add_argument("--kind", required=True, choices=["ARCHITECTURE", "CODE", "IMPLEMENTATION", "ULTRA_REVIEW"], default="ARCHITECTURE", help="review kind")
    pr.add_argument("--decision", required=True, choices=sorted(_DECISIONS), help="PASS | REVISE | BLOCKED | NEEDS_FIX | FAIL")
    pr.add_argument("--artifact", required=False, default=None, help="architecture review artifact; CODE results use a Runtime-generated machine artifact")
    pr.add_argument("--round", type=int, required=False, default=1, help="review round number")
    pr.add_argument("--findings-count", type=int, required=False, default=0, help="findings count")
    pr.add_argument("--evidence", action="append", help="evidence path(s)")
    pr.add_argument("--summary", required=False, default="architecture review", help="review summary")
    pr.add_argument("--context-usage-json", default=None, help="best-effort JSON array of Context Usage receipts; telemetry never blocks review record")
    pr.add_argument("--context-policy", default="isolated", choices=["isolated"], help="formal architecture review context policy")
    pr.add_argument("--design-context-id", default="", help="execution context id used to produce the architecture design")
    pr.add_argument("--review-context-id", default="", help="distinct execution context id used for formal architecture review")
    pr.add_argument("--project", required=False, default=None)
    pr.add_argument("--db", required=False, default=None)
    pr.set_defaults(func=cmd_review_record)
