# -*- coding: utf-8 -*-
"""Canonical read-only presentation semantics for Runtime task events.

Only structured machine values determine status/colour. Human summaries are
display text and never enter this resolver.
"""
from __future__ import annotations

from typing import Dict

EVENT_LABELS: Dict[str, str] = {
    "FACT": "事实记录", "CHECKPOINT": "检查点", "BLOCKER": "阻塞记录",
    "VERIFICATION_COMPLETED": "验证完成", "REVIEW_COMPLETED": "复审完成",
    "WORK_SESSION_STARTED": "工作会话开始", "WORK_SESSION_ENDED": "工作会话结束",
    "WORKFLOW_CONFIRMATION": "工作流确认", "DELIVERY_RESULT": "交付结果",
    "STATE": "状态变更", "TASK_CREATED": "任务创建", "TASK_STARTED": "任务开始",
}

DECISION_LABELS: Dict[str, str] = {
    "PASS": "通过", "REVISE": "需修改", "NEEDS_FIX": "需要修复",
    "FAIL": "失败", "ERROR": "错误", "BLOCKED": "存在阻塞",
    "NOT_RECORDED": "状态未声明",
}
DECISION_STATUS: Dict[str, str] = {
    "PASS": "ok", "REVISE": "bad", "NEEDS_FIX": "bad",
    "FAIL": "bad", "ERROR": "bad", "BLOCKED": "warn",
    "NOT_RECORDED": "info",
}
RESULT_LABELS: Dict[str, str] = {
    "COMPLETED": "已完成", "PENDING": "待处理", "BLOCKED": "存在阻塞",
    "STARTED": "普通事务", "RECORDED": "普通事务", "CANCELLED": "已取消",
    "NOT_RECORDED": "状态未声明",
}
RESULT_STATUS: Dict[str, str] = {
    "COMPLETED": "ok", "PENDING": "warn", "BLOCKED": "warn",
    "STARTED": "info", "RECORDED": "info", "CANCELLED": "info",
    "NOT_RECORDED": "info",
}


def _upper(value: object) -> str:
    return str(value or "").strip().upper()


def resolve_event_presentation(event_type: object, decision: object, result_status: object) -> Dict[str, str]:
    raw_event_type = str(event_type or "").strip()
    event_key = _upper(raw_event_type)
    raw_decision = _upper(decision)
    raw_result = _upper(result_status) or "NOT_RECORDED"
    event_label = EVENT_LABELS.get(event_key, raw_event_type or "未记录")

    if raw_decision:
        reason_label = DECISION_LABELS.get(raw_decision, raw_decision)
        status_class = DECISION_STATUS.get(raw_decision, "info")
    else:
        reason_label = RESULT_LABELS.get(raw_result, raw_result or "状态未声明")
        status_class = RESULT_STATUS.get(raw_result, "info")
    return {
        "event_label": event_label, "reason_label": reason_label,
        "status_class": status_class, "decision": raw_decision,
        "result_status": raw_result,
    }
