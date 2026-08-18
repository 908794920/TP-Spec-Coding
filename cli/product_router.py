# -*- coding: utf-8 -*-
"""Low-context product/domain routing for the tp-spec-coding entry agent.

The router classifies only the current user signal plus an optional compact
active-task domain. It deliberately does not read repositories, tasks, Wiki,
Knowledge, or spawn model work; deep understanding belongs to the selected
Domain Agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DomainDecision:
    domain: str
    confidence: str
    reason_code: str
    needs_clarification: bool = False

    def to_dict(self):
        return asdict(self)


_SIGNAL_GROUPS = (
    ("autonomy", ("autonomy", "自治", "cycle", "proposal", "batch")),
    ("wiki", (" wiki", "wiki ", "wiki", "维基", "项目事实", "代码理解")),
    ("knowledge", ("knowledge", "知识库", "知识", "memory", "经验沉淀")),
    ("base", ("基座", "base maintenance", "upgrade base", "安装配置", "tp-spec 配置")),
    ("software", (
        "review", "commit", "代码", "开发", "需求", "架构", "测试", "bug", "修复",
        "实现", "接口", "数据库", "sql", "feature", "task", "合并", "集成",
    )),
)


def route_domain(text: str, *, active_task_domain: str | None = None) -> DomainDecision:
    raw = str(text or "").strip()
    lowered = f" {raw.lower()} "
    for domain, needles in _SIGNAL_GROUPS:
        if any(needle.lower() in lowered for needle in needles):
            return DomainDecision(domain, "high", f"{domain}_signal", False)
    active = str(active_task_domain or "").strip().lower()
    if active in {"software", "wiki", "knowledge", "base", "autonomy"}:
        return DomainDecision(active, "medium", "active_task_domain", False)
    return DomainDecision("unknown", "low", "ambiguous_signal", True)
