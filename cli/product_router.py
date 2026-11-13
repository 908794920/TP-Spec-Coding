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
    ("wiki", (" wiki", "wiki ", "wiki", "维基", "项目事实", "代码理解")),
    ("video", ("视频制作", "制作视频", "拍摄视频", "剪辑视频", "视频剪辑", "短片", "漫剧",
               "视频成片", "video production", "video editing", "tp-video-production")),
    ("knowledge", ("knowledge", "知识库", "知识", "memory", "经验沉淀")),
    ("base", ("基座", "base maintenance", "upgrade base", "安装配置", "tp-spec 配置")),
    ("software", (
        "review", "commit", "代码", "开发", "需求", "架构", "测试", "bug", "修复",
        "实现", "接口", "数据库", "sql", "feature", "task", "合并", "集成",
    )),
)


DOMAINS = tuple(domain for domain, _ in _SIGNAL_GROUPS)


def route_domain(text: str, *, active_task_domain: str | None = None,
                 explicit_domain: str | None = None) -> DomainDecision:
    raw = str(text or "").strip()
    lowered = f" {raw.lower()} "
    if explicit_domain in DOMAINS:
        return DomainDecision(explicit_domain, "high", "explicit_domain")
    active = str(active_task_domain or "").strip().lower()
    video_intent = ("视频" in raw and any(word in raw for word in ("制作", "剪辑", "讲解", "拍摄", "分镜", "成片")))
    software_intent = any(word in raw for word in ("软件开发", "代码开发", "开发功能", "产品功能", "开发系统"))
    for domain, needles in _SIGNAL_GROUPS:
        matched = any(needle.lower() in lowered for needle in needles)
        if domain == "video":
            matched = (matched or video_intent) and not software_intent
        if matched:
            if active == "video" and domain in {"software", "knowledge"} and not software_intent:
                continue
            return DomainDecision(domain, "high", f"{domain}_signal", False)
    if active in DOMAINS:
        return DomainDecision(active, "medium", "active_task_domain", False)
    return DomainDecision("unknown", "low", "ambiguous_signal", True)
