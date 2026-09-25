# -*- coding: utf-8 -*-
"""Compact, read-only explanations of existing Task facts and derived files.

No imports into Runtime, no repair, no inferred approval and no second state
machine. Archive reads are explicitly file observations, not authenticated DB
facts. Canonical prose is linked, never summarized into a competing truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import current_context, frontmatter

SCHEMA = "tp-spec.task-view/v1"
TERMINAL = {"COMPLETED", "CANCELLED"}
CONTINUATION = "generated/continuation.md"
FINAL = "generated/final-result.md"


def read_text(path: Path) -> str:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def excerpt(value: Any, limit: int = 320) -> str:
    """Presentation excerpt only; full source and all subject digests stay intact."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "…（摘录；全文见来源记录）"


def parse_status(text: str) -> dict[str, Any]:
    """Read this producer's flat scalars/JSON fields and quality map, not arbitrary YAML."""
    out: dict[str, Any] = {"quality_facts": {}}
    in_quality = False
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "quality_facts:":
            in_quality = True
            continue
        if line.startswith(" "):
            if in_quality and ":" in line:
                key, value = line.strip().split(":", 1)
                out["quality_facts"][key] = value.strip().strip('"\'')
            continue
        in_quality = False
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        try:
            out[key] = json.loads(value)
        except ValueError:
            out[key] = value.strip('"\'')
    return out


def execution_brief(facts: dict[str, Any]) -> dict[str, Any]:
    """Only navigation-sized facts from cli.execution's existing replay."""
    def step(item):
        if not item:
            return None
        return {key: item.get(key) for key in (
            "id", "title", "status", "roles", "waiting_work_items", "wait_reason", "expected_next_actor")}
    return {"status": facts.get("status", "NOT_RECORDED"), "source": "task_event.execution",
            "plan_version": facts.get("plan_version", 0), "coordinator": facts.get("coordinator"),
            "current_step": step(facts.get("current_step")), "next_step": step(facts.get("next_step")),
            "current_roles": facts.get("current_roles", []), "last_recorded_at": facts.get("last_recorded_at"),
            "issues": facts.get("issues", []), "runtime_status": "UNKNOWN"}


def learning_brief(detail: dict) -> dict:
    """Describe recorded results; never claim that an old NOT_REQUIRED meant assessed."""
    knowledge = detail.get("knowledge_results") or []
    memory = detail.get("memory_assessment") or {}
    if (not isinstance(knowledge, list) or not isinstance(memory, dict)
            or not isinstance(memory.get("items", []), list)):
        return {"status": "UNKNOWN", "note": "提炼记录格式无法识别"}
    return {"input_digest": detail.get("input_digest"),
            "knowledge_disposition": detail.get("knowledge_disposition", "NOT_RECORDED"),
            "knowledge": [{"id": row.get("id"), "disposition": row.get("disposition"),
                           "target": row.get("knowledge_ref"), "reason": excerpt(row.get("reason"))}
                          for row in knowledge if isinstance(row, dict)],
            "memory_summary": excerpt(memory.get("summary")),
            "memory": [{**{key: row.get(key) for key in ("id", "kind", "disposition", "target")},
                        **{key: excerpt(row.get(key)) for key in ("reason", "responsibility", "recovery_condition")}}
                       for row in memory.get("items", []) if isinstance(row, dict)],
            "note": "已记录处置，不等于当前输入仍适用；详细覆盖/检索/读回凭据在 Runtime Result。"}


def source_names(task_dir: Path, state: str) -> list[str]:
    from .projection_cmd import projection_source_names
    names = ["status.yaml", "events.jsonl", "task.md", "acceptance.md"]
    if state in {"CLOSING", "COMPLETED"}:
        names += ["implementation.md", "codex-review.md"]
    elif state == "VERIFYING":
        names += ["implementation.md"]
    return sorted({name for name in [*names, *projection_source_names()] if (task_dir / name).is_file()})


def navigation(task_dir: Path, *, task_id: str = "", current: dict | None = None) -> dict:
    context = current if current is not None else current_context.read_current(task_dir, task_id=task_id)
    names = [("task.md", "有效范围、决定及历史入口"), ("requirement.md", "独立需求正文（如已采用）"),
             ("requirement-decisions.md", "决定与替代依据"), ("acceptance.md", "验收矩阵及操作声明"),
             ("events.jsonl", "正式事件投影、批次过程与来源"), ("evidence/", "证据（按引用读取）")]
    return {"current_region_status": context["status"], "current_source": context.get("source"),
            "issues": context.get("issues", []),
            "references": [{"path": name, "label": label} for name, label in names if (task_dir / name).exists()],
            "note": "业务声明不等于当前进度、授权或 PASS；历史过程按需读取，不在派生视图复制正文。"}


def render_navigation(nav: dict) -> str:
    lines = ["\n## 范围、验收与历史导航\n", "> " + nav["note"], ""]
    for item in nav["references"]:
        lines.append(f"- [{item['label']}](../{item['path']})")
    if nav["current_region_status"] in current_context.UNUSABLE:
        lines.append(f"- 当前区待核对：{nav['current_region_status']}。仅报告，不截断或改写来源。")
    elif nav.get("current_source"):
        lines.append(f"- 有效范围唯一维护于 `{nav['current_source']}` 的 current 区；此处不重复展开。")
    else:
        lines.append("- 未声明独立 current 区；沿来源定向核对，不补造当前决定。")
    return "\n".join(lines) + "\n"


def inspect_generated(task_dir: Path, rel: str, *, task_id: str = "", state: str = "", base_version: str = "") -> dict:
    """Validate a derived view's declared inputs/body; never use it to decide Task state."""
    from .version import active_version
    result = {"path": rel, "status": "MISSING", "issues": [], "generated_at": None,
              "declared_state": None, "schema": None, "source_files": []}
    path = task_dir / rel
    if not path.is_file():
        result["issues"].append("生成视图缺失；不等于业务未完成。")
        return result
    try:
        text = read_text(path)
        parts = frontmatter.split(text)
        meta = frontmatter.parse(text)
        if parts is None or meta is None or meta.get("generated_view") != "true":
            raise ValueError("generated view front matter invalid")
        front, body, _ = parts
        result.update(status="CURRENT", generated_at=meta.get("generated_at"), schema=meta.get("view_schema"))
        # Legacy generators had no state field. Only read their generated header,
        # never an arbitrary status mentioned in copied business/history prose.
        declared = meta.get("task_state")
        if not declared:
            header = re.split(r"(?m)^##\s", body, maxsplit=1)[0]
            match = re.search(r"(?m)^- (?:任务状态|状态)：([A-Z_]+)\s*$", header)
            declared = match.group(1) if match else None
        result["declared_state"] = declared
        if meta.get("task_id") and meta["task_id"] != task_id:
            raise ValueError("view task_id does not match selected Task")
        issues = result["issues"]
        if state and declared and declared != state:
            issues.append(f"生成时状态为 {declared}，当前记录为 {state}；不能继续执行旧接续。")
        if not declared:
            issues.append("生成时状态未记录，不能确认接续语义。")
        if state not in TERMINAL and base_version == active_version() and meta.get("generator_version") != active_version():
            issues.append("生成器版本与当前活动契约不符。")
        names: list[str] = []
        in_sources = False
        for line in front.splitlines():
            if line == "source_files:":
                in_sources = True
                continue
            if in_sources and re.match(r"^\s+- ", line):
                value = line.strip()[2:].strip()
                name = json.loads(value) if value.startswith('"') else value.strip("'")
                if not isinstance(name, str) or not name:
                    raise ValueError("invalid view source path")
                names.append(name)
            elif line and not line.startswith(" "):
                in_sources = False
        if len(set(names)) != len(names):
            raise ValueError("duplicate view source_files")
        result["source_files"] = names
        required = set(source_names(task_dir, state)) | {"status.yaml", "events.jsonl"}
        absent = required - set(names)
        if absent:
            issues.append("来源集合变化或未绑定：" + ", ".join(sorted(absent)))
        chunks = []
        for name in sorted(names):
            candidate = Path(name)
            if (candidate.is_absolute() or ".." in candidate.parts or "\\" in name
                    or not (task_dir / candidate).resolve().is_relative_to(task_dir.resolve())):
                raise ValueError("view source is outside selected task directory")
            source = task_dir / candidate
            if not source.is_file():
                issues.append("已绑定来源缺失：" + name)
                continue
            chunks.append(name + "\n" + hashlib.sha256(read_text(source).encode("utf-8")).hexdigest() + "\n")
        actual = "sha256:" + hashlib.sha256("".join(chunks).encode("utf-8")).hexdigest()
        content = "sha256:" + hashlib.sha256(body.lstrip("\r\n").encode("utf-8")).hexdigest()
        missing_binding = not all(re.fullmatch(r"sha256:[0-9a-f]{64}", meta.get(key, ""))
                                  for key in ("source_digest", "content_digest"))
        if missing_binding:
            issues.append("来源或正文摘要缺失/格式无效，不能确认生成成功。")
        else:
            if meta["source_digest"] != actual:
                issues.append("source_digest mismatch：来源已变化，生成视图过期。")
            if meta["content_digest"] != content:
                issues.append("content_digest mismatch：生成正文与已登记摘要不一致。")
        if issues:
            result["status"] = "UNKNOWN" if missing_binding or not declared else "STALE"
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result.update(status="INVALID")
        result["issues"].append(str(exc))
    return result


def inspect_task_views(task_dir: Path, task=None, *, task_id: str = "", events=None, execution=None) -> dict:
    """Read Runtime-backed or DB-free archive views without touching sealed material."""
    root = Path(task_dir)
    runtime = dict(task) if task is not None else None
    task_id = str((runtime or {}).get("task_id") or task_id)
    problems: list[dict[str, str]] = []
    def problem(code, message):
        problems.append({"code": code, "message": str(message)})
    status: dict = {}
    projected_events: list[dict] = []
    try:
        status = parse_status(read_text(root / "status.yaml"))
        if status.get("task_id") != task_id:
            raise ValueError("status.yaml task_id 与选定 Task 不一致")
    except (OSError, UnicodeError, ValueError) as exc:
        problem("STATUS_PROJECTION_UNAVAILABLE", exc)
        status = {}
    try:
        for number, line in enumerate(read_text(root / "events.jsonl").splitlines(), 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"events.jsonl 第 {number} 行不是事件对象")
            projected_events.append(item)
    except (OSError, UnicodeError, ValueError) as exc:
        problem("EVENT_PROJECTION_UNAVAILABLE", exc)
        projected_events = []  # A partial log cannot supply a reliable last state.
    last_state = next((e for e in reversed(projected_events) if e.get("type") == "STATE"), {})
    state = str((runtime or {}).get("current_state") or status.get("current_state") or "UNKNOWN")
    if status and status.get("current_state") != state:
        problem("STATUS_PROJECTION_STALE", "status.yaml 与 Runtime 正式状态不符；不采用旧状态。")
    if not last_state.get("state") or last_state["state"] != state:
        problem("STATE_OBSERVATION_CONFLICT", "未取得与当前状态相符的最后 STATE；不根据修改时间或长摘要猜测。")
        if runtime is None:
            state = "UNKNOWN"
    if events is not None:
        if len(projected_events) != len(events):
            problem("EVENT_PROJECTION_STALE", "事件投影数量与本次 Runtime 读取不符。")
        if status.get("projection_schema") == SCHEMA:
            from .projection_cmd import _build_events_jsonl
            expected, _ = _build_events_jsonl(events, task_id)
            if projected_events != [json.loads(line) for line in expected.splitlines() if line.strip()]:
                problem("EVENT_PROJECTION_STALE", "事件投影内容与本次 Runtime 读取不符。")
            if status.get("fact_revision") != len(events):
                problem("STATUS_PROJECTION_STALE", "status.yaml 的事实版本落后于 Runtime。")
    terminal = state in TERMINAL
    brief = execution_brief(execution) if execution is not None else status.get("execution", {})
    if not isinstance(brief, dict):
        brief = {}
    if execution is None and any(p["code"].startswith(("STATUS_", "EVENT_", "STATE_")) for p in problems):
        brief = {"status": "UNKNOWN", "current_step": None, "next_step": None, "current_roles": []}
    if terminal:
        brief = {**brief, "current_step": None, "next_step": None, "current_roles": []}
    selected = FINAL if state == "COMPLETED" else CONTINUATION
    versions = [inspect_generated(root, rel, task_id=task_id, state=state,
                                  base_version=str((runtime or {}).get("base_version") or status.get("base_version") or ""))
                for rel in (CONTINUATION, FINAL) if rel == selected or (root / rel).exists()]
    for view in versions:
        view["selected"] = view["path"] == selected
        if view["status"] != "CURRENT":
            problem("DERIVED_VIEW_" + view["status"], view["path"] + "：" + "；".join(view["issues"]))
    nav = navigation(root, task_id=task_id)
    if nav["issues"]:
        problem("CURRENT_CONTEXT_UNAVAILABLE", "有效业务当前区待核对；见范围导航。")
    latest = (dict(events[-1]) if events else {}) if events is not None else (projected_events[-1] if projected_events else {})
    activity = {"actor": latest.get("actor_role") or latest.get("actor"),
                "time": latest.get("created_at") or latest.get("time"),
                "event_id": latest.get("id"), "summary": excerpt(latest.get("summary") or latest.get("note"))}
    reliable_projection = not any(p["code"].startswith(("STATUS_", "EVENT_", "STATE_")) for p in problems)
    return {"schema": SCHEMA, "task_id": task_id, "state": state, "terminal": terminal,
            "state_source": "runtime.task" if runtime else "archive.status+last_STATE (not authenticated Runtime)",
            "current_roles": [] if terminal else brief.get("current_roles", []),
            "next_responsibility": None if terminal else (status.get("next_responsibility") if reliable_projection else None),
            "execution": brief, "last_activity": activity, "selected_view": selected, "views": versions,
            "quality": status.get("quality_facts", {}) if reliable_projection else {},
            "quality_source": "historical_projection" if terminal else "projection_not_closeout_verdict",
            "navigation": nav, "problems": problems, "read_only": True,
            "recovery": ("终态仅查询；保留旧接续、源材料及 terminal manifest，不覆盖、不重算旧 hash。"
                         if terminal else ("来源缺失或冲突；先核对正式 Runtime，不按未知状态自动修复归档。" if state == "UNKNOWN" else
                                           "在途任务先核对事实；仅派生视图过期可用 projection rebuild --view-only；正式投影漂移用 reconcile。")),
            "note": ("任务已结束；没有当前执行角色或下一动作。旧当前区/最后阶段是历史，不能覆盖终态；旧任务不追补新步骤或学习义务。"
                     if terminal else "当前角色来自已登记参与，不代表 Agent 在线；生成视图仅供导航，行动以 Runtime 与实际授权为准。")}
