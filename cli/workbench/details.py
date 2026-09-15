# -*- coding: utf-8 -*-
"""On-demand task explanations; consumers of existing rules, never a new gate.

Recorded claims, ledger trust and current applicability are different fields.
Only opening task details evaluates file/product bindings; graph navigation does
not call this module. No verify/review/complete operation is executed here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from cli import delivery_contract, event_policies, waiting, workflow_records, yaml_checks
from cli.change_set import capture_change_set, same_bound_product_content
from .evidence_view import build_evidence_view, inspect_evidence_view

HISTORY_LIMIT = 20


def event_record(row: dict[str, Any]) -> dict[str, Any]:
    """Keep raw structured outcomes; summaries never create a decision."""
    try:
        detail = json.loads(row.get("detail_json") or "{}")
        valid = isinstance(detail, dict)
    except (TypeError, ValueError):
        detail, valid = {}, False
    if not valid:
        detail = {}
    return {
        "event_id": row.get("id"), "event_type": row.get("event_type"),
        "created_at": row.get("created_at"), "actor": row.get("actor_role"),
        "work_item_id": row.get("work_item_id"), "summary": row.get("summary"),
        "decision": detail.get("decision") or "NOT_RECORDED",
        "result_status": detail.get("result_status") or "NOT_RECORDED",
        "detail_valid": valid, "detail": detail, "source": "task_event",
    }


def acceptance_view(task_dir: Path) -> dict[str, Any]:
    """Expose the existing table/YAML declarations, not effective PASS claims."""
    path = task_dir / "acceptance.md"
    result: dict[str, Any] = {"source": str(path), "status": "not_recorded", "rows": [], "issues": []}
    if not path.is_file():
        return result
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        checked = yaml_checks.check_acceptance_yaml(text, enforce_completion=False, allow_human_pending=True)
        rows = []
        # Use the same column positions/AC grammar as check_acceptance_yaml.
        for number, line in enumerate(text.splitlines(), 1):
            match = re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
            if not match:
                continue
            cells = [part.strip() for part in line.split("|")]
            if len(cells) <= 8:
                rows.append({"ac": match.group(1), "line": number, "raw": line, "parse_error": "验收表列不足"})
                continue
            rows.append(dict(zip(
                ("ac", "condition", "requirement_source", "risk", "method", "evidence", "witness", "declared_verdict"),
                cells[1:9],
            ), line=number))
        result.update(status="read", rows=rows, sha256=hashlib.sha256(raw).hexdigest(),
                      issues=checked.issues, pending=checked.pending_rows,
                      page_verification=checked.page_verification,
                      deferred=checked.deferred_entries, waived=checked.owner_waiver_entries,
                      database_operations=checked.database_operations,
                      no_acceptance_required=checked.no_acceptance_required)
    except (OSError, UnicodeError, ValueError) as exc:
        result.update(status="unreadable", issues=[str(exc)])
    return result


def _channel(events: list[dict[str, Any]], event_type: str, actor: str) -> dict[str, Any]:
    rows = [row for row in reversed(events) if row.get("event_type") == event_type and row.get("actor_role") == actor]
    return {"recorded": event_record(rows[0]) if rows else None,
            "history": [event_record(row) for row in rows[:HISTORY_LIMIT]],
            "history_scope": {"total": len(rows), "returned": min(len(rows), HISTORY_LIMIT), "limit": HISTORY_LIMIT},
            "applicability": "not_confirmed" if rows else "not_recorded",
            "reasons": [], "source": "task_event + existing Runtime readers"}


def _check_verification(conn, task_id: str, task_dir: Path, channel: dict):
    recorded = channel["recorded"]
    if not recorded:
        return None
    trusted = event_policies.load_trusted_governance_event(
        conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer", latest_only=True)
    channel["ledger_trusted"] = bool(trusted)
    if trusted is None:
        channel["reasons"].append("最新记录未通过既有可信事件读取，不能从摘要认定 PASS。")
        return None
    detail = trusted.detail
    channel["scope"] = event_policies.verification_scope(detail)
    if detail.get("subject_digest") and not event_policies.verification_subject_matches(detail, task_dir):
        channel.update(applicability="stale", reasons=["原记录 subject 与当前任务工件不匹配。"])
        return None
    current = event_policies.load_current_verification(conn, task_id, task_dir)
    if current is None:
        channel["reasons"].append("未取得既有 load_current_verification 的当前 PASS；可能为非 PASS、证据无效或范围不匹配，未细分的原因不推断。")
        return None
    roots = tuple(str(value) for value in current.detail.get("repo_roots") or [])
    if not roots or not current.detail.get("change_set_id"):
        channel["reasons"].append("任务工件/证据校验通过，但记录缺少产品 ChangeSet 绑定；不能确认产品仍适用。")
        return None
    product = capture_change_set(list(roots))
    if not same_bound_product_content(current.detail, product):
        channel.update(applicability="stale", reasons=["当前产品内容与验证绑定的 ChangeSet 不匹配。"])
        return None
    channel.update(applicability="current", reasons=[], checks=current.detail.get("checks") or [],
                   source="load_current_verification + same_bound_product_content")
    return current


def build_task_details(conn, task: dict[str, Any], task_dir: Path) -> dict[str, Any]:
    task_id = str(task["task_id"])
    events = [dict(row) for row in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,))]
    problems: list[dict[str, str]] = []

    def problem(code: str, exc: object) -> None:
        problems.append({"code": code, "message": str(exc)})

    acceptance = acceptance_view(task_dir)
    if acceptance["status"] != "read" or acceptance["issues"]:
        problem("ACCEPTANCE_DECLARATION_UNCONFIRMED", "; ".join(acceptance["issues"]) or "未取得 acceptance.md；不等于没有验收义务。")
    verification = _channel(events, "VERIFICATION_COMPLETED", "tp-test-engineer")
    review = _channel(events, "REVIEW_COMPLETED", "tp-code-reviewer")
    delivery = _channel(events, "DELIVERY_RESULT", "tp-integration-engineer")
    owner = _channel(events, "OWNER_ACCEPTANCE_DECISION", "human_owner")
    current = reviewed = None
    try:
        current = _check_verification(conn, task_id, task_dir, verification)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        verification["reasons"].append(str(exc))
        problem("VERIFICATION_APPLICABILITY_UNAVAILABLE", exc)

    if review["recorded"]:
        try:
            review["ledger_trusted"] = bool(event_policies.load_trusted_governance_event(
                conn, task_id, event_type="REVIEW_COMPLETED", actor="tp-code-reviewer", latest_only=True))
            if current is None:
                review["reasons"].append("未取得当前产品上的 Verification PASS，未将历史 Review 认定为当前可用。")
            else:
                reviewed = workflow_records._latest_trusted_code_review(
                    conn, task_id, subject_digest=str(current.detail.get("subject_digest") or ""),
                    change_set_id=str(current.detail.get("change_set_id") or ""),
                    verification_event_id=int(current.row["id"]), task_dir=task_dir)
                review.update(applicability="current", source="workflow_records._latest_trusted_code_review")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            # The existing reader reports missing/invalid/stale together. Do not invent a more precise verdict.
            review["reasons"].append(str(exc))

    if delivery["recorded"]:
        try:
            delivery["ledger_trusted"] = bool(event_policies.load_trusted_governance_event(
                conn, task_id, event_type="DELIVERY_RESULT", actor="tp-integration-engineer", latest_only=True))
            if current is None or reviewed is None or event_policies.verification_scope(current.detail) != "full":
                delivery["reasons"].append("未取得当前 full Verification 与匹配 Review；READY 历史记录不等于可正式结单。")
            else:
                ready = delivery_contract.find_delivery_completion_event(
                    events, verification_event=dict(current.row),
                    current_subject_digest=str(current.detail.get("subject_digest") or ""), task_dir=task_dir)
                if ready is not None:
                    delivery.update(applicability="current", source="delivery_contract.find_delivery_completion_event")
                else:
                    delivery["reasons"].append("既有 Delivery 读取未返回匹配的 READY；不推断缺失/失效的具体分支。")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            delivery["reasons"].append(str(exc))

    # The authoritative owner reader preserves legacy waive/defer meanings and evaluates accept bindings.
    try:
        trusted_owner = event_policies.load_owner_acceptance_decisions(conn, task_id)
        trusted_ids = {row["_event_id"] for row in trusted_owner}
        effective = event_policies.effective_owner_acceptance(conn, task_id, task_dir=task_dir)
        owner.update(effective=effective, evaluation="evaluated", source="event_policies.effective_owner_acceptance")
        for row in owner["history"]:
            row["ledger_trusted"] = row["event_id"] in trusted_ids
        if owner["recorded"]:
            owner["ledger_trusted"] = owner["recorded"]["event_id"] in trusted_ids
        # A disposition may apply only to some ACs. Never label the entire owner history current.
        owner["applicability"] = "per_ac" if trusted_owner else owner["applicability"]
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        owner.update(evaluation="unavailable", effective={})
        owner["reasons"].append(str(exc))
        problem("OWNER_APPLICABILITY_UNAVAILABLE", exc)

    wait = {}
    try:
        wait = waiting.active_wait(events, str(task.get("current_state") or ""))
    except ValueError as exc:
        problem("WAITING_FACT_UNAVAILABLE", exc)
    blocked_event = next((row for row in reversed(events) if row.get("event_type") == "BLOCKER"), None)
    blockers = {"waiting": wait,
                "legacy_blocker": event_record(blocked_event) if blocked_event and task.get("current_state") == "BLOCKED" else None,
                "source": "waiting.active_wait + task_event", "note": "没有结构化责任方或恢复条件时保持未记录；结单预检另行按需读取。"}

    evidence = inspect_evidence_view(build_evidence_view(events, task_id=task_id, project_root=str(task_dir.parents[2])), task_dir=task_dir)
    if any(row.get("inspection_error") for row in evidence):
        problem("EVIDENCE_READ_PARTIAL", "部分证据不可读取，见各引用的 inspection_error；不将读取失败当作业务 FAIL。")
    # A vanished declaration is the same consistency failure as changed bytes.
    declaration_changed = ""
    if acceptance.get("sha256"):
        try:
            if hashlib.sha256((task_dir / "acceptance.md").read_bytes()).hexdigest() != acceptance["sha256"]:
                declaration_changed = "读取期间 acceptance.md 发生变化。"
        except OSError as exc:
            declaration_changed = f"读取结束时 acceptance.md 已无法取得：{exc}"
    if declaration_changed:
        problem("ACCEPTANCE_CHANGED_DURING_READ", declaration_changed + " 请重新读取，不能合并为当前有效结果。")
        for channel in (verification, review, delivery):
            if channel["applicability"] == "current":
                channel.update(applicability="not_confirmed", reasons=[declaration_changed])
        owner.update(evaluation="unavailable", effective={})
    return {"task": {"task_id": task_id, "state": task.get("current_state"), "phase": task.get("current_stage"),
                     "owner": task.get("owner_role"), "completed_at": task.get("completed_at")},
            "task_dir": str(task_dir), "acceptance": acceptance, "verification": verification,
            "review": review, "delivery": delivery, "owner_acceptance": owner,
            "blockers": blockers, "evidence": evidence, "problems": problems,
            "note": "按需读取既有事实与绑定，不运行测试/Review/Complete。矩阵是声明，证据哈希匹配不等于验收通过；当前结单能力以独立预检为准。"}
