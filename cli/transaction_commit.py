# -*- coding: utf-8 -*-
"""Neutral durable transaction/projection primitives for Record-first Runtime.

This module contains no legacy long-state workflow or Action-role policy.  Migration-only
compatibility remains under :mod:`cli.migrations.v5_2_3`.
"""
from __future__ import annotations
from . import command_context

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import db as dbmod
from . import projection_cmd
from . import transaction_journal
from .commit_errors import ProjectionCommitFailedError, ReconciliationRequiredError
from .encoding_guard import EncodingValidationError
from .path_identity import same_path
from .transaction_journal import JOURNAL_SCHEMA, PHASE_DB_COMMITTED, PHASE_FILES_REPLACED, PHASE_PREPARED
from .version import active_version

ACTIVE_CONTRACT = active_version()
TERMINAL_MANIFEST_REL = "generated/terminal-manifest.json"
TERMINAL_MANIFEST_SCHEMA = "tp-spec.terminal-manifest/v1"

def _read(path: Path) -> str:
    # Preserve CRLF/LF exactly: generated-view digests must agree with the
    # PowerShell validator, whose Get-Content -Raw does not normalize line ends.
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return handle.read()

def _continuation_sources(task_dir: Path, state: str) -> List[Path]:
    """Shared input registry for generation, freshness checks and navigation."""
    from .task_views import source_names
    return [task_dir / name for name in source_names(task_dir, state)]

def _source_digest(paths: List[Path], task_dir: Path, source_digests: Optional[Dict[str, str]] = None) -> str:
    parts: List[str] = []
    for path in sorted(paths):
        rel = path.relative_to(task_dir).as_posix()
        captured = (source_digests or {}).get(rel)
        digest = captured if captured is not None else hashlib.sha256(_read(path).encode("utf-8")).hexdigest()
        parts.append(rel + "\n" + digest + "\n")
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()

def _generated_view_text(task_dir: Path, name: str, body: str, sources: List[Path], flush_id: str,
                         source_digests: Optional[Dict[str, str]] = None,
                         identity: Optional[Dict[str, str]] = None) -> str:
    """渲染 generated view 文本（不落盘）。"""
    digest = _source_digest(sources, task_dir, source_digests)
    source_lines = "\n".join(f'  - "{p.relative_to(task_dir).as_posix()}"' for p in sorted(sources))
    from .task_views import SCHEMA
    identity_lines = "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in (identity or {}).items())
    return (
        "---\n"
        "generated_view: true\n"
        f'view_schema: "{SCHEMA}"\n'
        + identity_lines
        + f'generator_version: "{ACTIVE_CONTRACT}"\n'
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

def _acceptance_projection_summary(task_dir: Path) -> dict:
    """Presentation only; missing/invalid declarations are not a zero-PENDING verdict."""
    try:
        from . import yaml_checks
        result = yaml_checks.check_acceptance_yaml(
            _read(task_dir / "acceptance.md"), enforce_completion=False, allow_human_pending=True
        )
        return {"known": not result.issues, "counts": dict(result.verdict_counts),
                "operations": list(result.database_operations), "issues": list(result.issues),
                "not_required": result.no_acceptance_required}
    except (OSError, UnicodeError, ValueError) as exc:
        return {"known": False, "counts": {}, "operations": [], "issues": [str(exc)], "not_required": None}

def _terminal_manifest_excluded(rel: str) -> bool:
    """终态清单忽略 Runtime 事务工件和清单自身。"""
    if rel == TERMINAL_MANIFEST_REL:
        return True
    parts = Path(rel).parts
    if not parts:
        return True
    if parts[0] == ".tp-spec" or parts[0].startswith(".v511-bak-"):
        return True
    name = parts[-1]
    if name.startswith(".") and name.endswith(".tmp"):
        return True
    return False


def _terminal_file_records(
    task_dir: Path, overlays: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """构建确定性的终态文件身份；overlays 表示同一事务尚未最终落盘的文本。"""
    records: Dict[str, Dict[str, Any]] = {}
    for path in sorted(task_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(task_dir).as_posix()
        if _terminal_manifest_excluded(rel):
            continue
        data = path.read_bytes()
        records[rel] = {
            "path": rel,
            "size": len(data),
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        }
    for rel, text in sorted((overlays or {}).items()):
        rel0 = Path(rel).as_posix()
        if _terminal_manifest_excluded(rel0):
            continue
        data = str(text).encode("utf-8")
        records[rel0] = {
            "path": rel0,
            "size": len(data),
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        }
    return records


def build_terminal_manifest_text(
    task_dir: Path,
    *,
    task_id: str,
    terminal_state: str,
    terminal_event_id: int,
    overlays: Optional[Dict[str, str]] = None,
) -> str:
    """生成结单时的只读文件清单；调用方负责与 DB/投影同事务提交。"""
    records = _terminal_file_records(task_dir, overlays)
    payload = {
        "schema": TERMINAL_MANIFEST_SCHEMA,
        "task_id": task_id,
        "terminal_state": terminal_state,
        "terminal_event_id": int(terminal_event_id),
        "generated_at": dbmod.now_iso(),
        "runtime_version": ACTIVE_CONTRACT,
        "files": [records[key] for key in sorted(records)],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def terminal_integrity(task_dir: Path, *, task_id: str) -> Dict[str, Any]:
    """只读比较当前任务目录与结单清单；不修改 DB、事件或任务状态。"""
    manifest_path = task_dir / TERMINAL_MANIFEST_REL
    empty = {"task_id": task_id, "status": "MISSING", "added": [], "modified": [], "deleted": []}
    if not manifest_path.is_file():
        return empty
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**empty, "error": f"invalid terminal manifest: {exc}"}
    if manifest.get("schema") != TERMINAL_MANIFEST_SCHEMA or str(manifest.get("task_id") or "") != task_id:
        return {**empty, "error": "terminal manifest identity mismatch"}

    expected: Dict[str, Dict[str, Any]] = {}
    for item in manifest.get("files") or []:
        if isinstance(item, dict) and str(item.get("path") or ""):
            expected[str(item["path"])] = item
    current = _terminal_file_records(task_dir)
    added = sorted(set(current) - set(expected))
    deleted = sorted(set(expected) - set(current))
    modified = sorted(
        rel for rel in set(current) & set(expected)
        if current[rel].get("sha256") != expected[rel].get("sha256")
        or current[rel].get("size") != expected[rel].get("size")
    )
    return {
        "task_id": task_id,
        "status": "DRIFTED" if added or modified or deleted else "CURRENT",
        "added": added,
        "modified": modified,
        "deleted": deleted,
    }


def _status_context(task_dir: Path) -> Dict[str, Any]:
    """Read the just-written projection; a missing file remains unknown."""
    from .task_views import parse_status
    try:
        return parse_status(_read(task_dir / "status.yaml"))
    except (OSError, UnicodeError):
        return {}


def _rebuild_current_view_text(task_dir: Path, task, summary: str, flush_id: str) -> str:
    """从账本投影生成当前人类视图，不把展示事实升级成新状态。"""
    state = str(task["current_state"] or "NEW")
    owner = str(task["owner_role"] or "unknown")
    phase = str(task["current_stage"] or "intake")
    from . import current_context, task_views
    current = current_context.read_current(task_dir, task_id=str(task["task_id"]))
    # Stamp the source bytes actually consumed for the slice. A concurrent edit
    # must leave a detectable stale view, not a freshly hashed old summary.
    source_digests = {item["path"]: item["digest"].removeprefix("sha256:") for item in current["sources"]}
    sources = _continuation_sources(task_dir, state)
    captured_names = set(source_digests)
    current_names = {p.name for p in sources if p.name in current_context.SOURCE_NAMES}
    if current["status"] in {"AVAILABLE", "ABSENT", "CONFLICT"} and captured_names != current_names:
        # A newly created competing document (or a deleted source) cannot be
        # stamped as current using a slice read from the previous source set.
        raise ValueError("CURRENT_CONTEXT_SOURCES_CHANGED: rebuild the view from current canonical sources")
    status_context = _status_context(task_dir)
    quality = status_context.get("quality_facts") or {}
    verification = quality.get("verification", "NOT_RECORDED")
    execution = status_context.get("execution") or {}
    latest = status_context.get("last_activity") or {}
    last_actor = latest.get("actor") or "历史未记录"
    summary = task_views.excerpt(summary)
    identity = {"task_id": str(task["task_id"]), "task_state": state}
    nav = task_views.navigation(task_dir, task_id=str(task["task_id"]), current=current)
    blockers = status_context.get("blockers") or []
    blocker_text = "、".join(str(item) for item in blockers) if blockers else "无"

    if state == "COMPLETED":
        body = (
            "# 生成的结项摘要\n\n"
            "- 任务状态：COMPLETED\n"
            f"- 最后阶段：{phase}\n"
            f"- 最后记录角色（历史）：{last_actor}\n"
            "- 当前执行角色 / 下一责任：无（任务已结束）\n"
            f"- 结论：{summary}\n"
        )
        acceptance = _acceptance_projection_summary(task_dir)
        counts, database_operations = acceptance["counts"], acceptance["operations"]
        not_required = counts.get("NOT_REQUIRED", 0) + counts.get("N/A", 0)
        unresolved = counts.get("PENDING", 0) + counts.get("BLOCKED", 0)
        if not acceptance["known"]:
            body += "- 验收计数：未确认；" + task_views.excerpt("；".join(acceptance["issues"])) + "\n"
        elif not counts and acceptance["not_required"]:
            body += "- 验收声明：no_acceptance_required；" + task_views.excerpt(acceptance["not_required"].get("reason")) + "\n"
        else:
            body += (
                f"- 验收结论：PASS：{counts.get('PASS', 0)}；"
                f"NOT_REQUIRED/N/A：{not_required}；"
                f"DEFERRED_ACCEPTED：{counts.get('DEFERRED_ACCEPTED', 0)}；"
                f"OWNER_WAIVED：{counts.get('OWNER_WAIVED', 0)}；未处置：{unresolved}\n"
            )
        if database_operations:
            db_items = [
                f"{item.get('id', '?')}={item.get('type', '?')}/{item.get('status', '?')}"
                for item in database_operations
            ]
            body += "- 数据库操作：" + "、".join(db_items) + "\n"
        else:
            body += "- 数据库操作：未列出操作条目（不能从 UI 人验推断执行）\n"
        body += (
            f"- Verification：{quality.get('verification', 'NOT_RECORDED')}\n"
            f"- Code Review：{quality.get('review', 'NOT_RECORDED')}\n"
            f"- Delivery：{quality.get('delivery', 'NOT_RECORDED')}\n"
            f"- Knowledge：{quality.get('knowledge', 'NOT_RECORDED')}\n"
            f"- Memory：{quality.get('memory', 'NOT_RECORDED')}\n"
            f"- 未解决阻塞：{blocker_text}\n"
            "- 终态完整性：CAPTURED（同一结单事务生成 terminal manifest；后续使用 `task terminal-check` 检查漂移）\n"
        )
        deferred = _deferred_acceptance_items(task_dir)
        if deferred:
            body += "- 延期验收项：" + "、".join(deferred) + "（见 acceptance.md）\n"
        if verification != "PASS":
            body += "- 提示：COMPLETED 表示任务工作已结束，不代表未记录/失败/延期的验证被改写为 PASS。\n"
        body += _delivery_view_text(task_dir)
        body += _learning_view_text(task_dir)
        body += task_views.render_navigation(nav)
        body += "\n> 终态按 Runtime 记录解释；业务文档中的旧进度、模板注释和最后阶段不能覆盖已完成事实。\n"
        return _generated_view_text(task_dir, "final-result.md", body, sources, flush_id, source_digests, identity)

    # A handoff is an instruction surface: phase flexibility must not override
    # an actual wait or terminal state recorded by the Runtime.
    if state == "BLOCKED":
        guidance = "任务处于 BLOCKED：保持等待；满足恢复条件后通过 `task resume` 重新校验，不因接续自动启动新的开发或验收。"
    elif state == "CANCELLED":
        guidance = "任务已 CANCELLED：当前工作已终止；本接续记录仅供查询，不继续开发或验收。"
    elif blockers:
        guidance = "受阻动作保持等待；按以上恢复条件取得有效新事实后重新查询 `workflow next`，不把 BLOCKED 当作开发缺陷，不重复必败操作。"
    elif current["status"] in current_context.UNUSABLE:
        guidance = current_context.RECOVERY
    elif "TECHNICAL" in verification:
        guidance = "技术限定结果不代表整体验收通过；按 workflow next 完成必要代码审查，保留完整验证及视觉/人验缺口，不直接交付或结单。"
    else:
        guidance = "读取 workflow next 确认适用步骤、责任及授权；历史 phase 不是新的执行指令，不因摘要自动重做已完成工作。"

    step = execution.get("current_step") or {}
    next_step = execution.get("next_step") or {}
    terminal = state in task_views.TERMINAL
    step_text = "无（任务已结束）" if terminal else (f"{step.get('id')} · {step.get('title')} · {step.get('status')}" if step else "历史未记录 / 尚无已开始步骤")
    roles = "无（任务已结束）" if terminal else "、".join(execution.get("current_roles") or []) or "未记录（计划角色不等于已参与）"
    next_role = "无（任务已结束）" if terminal else status_context.get("next_responsibility") or "未知"
    next_text = "无（任务已结束）" if terminal else (f"{next_step.get('id')} · {next_step.get('title')}（计划，尚未发生）" if next_step else "未知 / 无后续计划步骤")
    body = (
        "# 任务接续区\n\n"
        f"- 状态：{state}\n"
        f"- 当前步骤：{step_text}\n"
        f"- 当前执行角色：{roles}\n"
        f"- 计划版本：{execution.get('plan_version', '历史未记录')}\n"
        f"- Task 协调责任：{(execution.get('coordinator') or {}).get('role') or '历史未记录'}\n"
        f"- 最后阶段（历史）：{phase}\n"
        f"- 最近记录角色（历史）：{last_actor}；时间：{latest.get('time') or '历史未记录'}\n"
        f"- 最新 Change Set：{status_context.get('change_set_id') or quality.get('change_set_id') or 'NOT_RECORDED'}\n"
        f"- 当前阻塞：{blocker_text}\n"
        f"- 等待子工作：{'、'.join(step.get('waiting_work_items') or []) or '未记录'}\n"
        f"- 步骤等待原因：{task_views.excerpt(step.get('wait_reason')) or '未记录'}\n"
        f"- 下一责任：{next_role}\n"
        f"- 下一计划步骤：{next_text}\n"
        f"- 技术验证事实：{verification}\n"
        f"- 最近记录摘录（events.jsonl）：{summary}\n"
        f"\n> {guidance} 未闭合参与不证明执行者在线。\n"
    )
    body += task_views.render_navigation(nav)
    return _generated_view_text(task_dir, "continuation.md", body, sources, flush_id, source_digests, identity)


def _delivery_view_text(task_dir: Path) -> str:
    try:
        rows = [json.loads(line) for line in _read(task_dir / "events.jsonl").splitlines() if line.strip()]
        row = next((item for item in reversed(rows) if isinstance(item, dict) and item.get("delivery")), None)
    except (OSError, UnicodeError, ValueError):
        return "- 交付处置与遗留风险：读取失败；见正式交付记录。\n"
    if row is None:
        return "- 交付处置与遗留风险：历史未记录；不得推断为无风险。\n"
    value = row["delivery"]
    from .task_views import excerpt
    lines = [f"- 交付来源：`events.jsonl` `{row['id']}` / Runtime event `{row.get('runtime_event_id')}`；"
             f"已登记 {value.get('status') or 'UNKNOWN'}（适用性见上方质量事实）。",
             "- 交付说明：" + (excerpt(value.get("reason")) or "未记录")]
    risks = value.get("residual_risks")
    if not isinstance(risks, list):
        lines.append("- 遗留风险：记录无法识别，待核对。")
    elif risks:
        lines.append(f"- 已登记遗留风险：{len(risks)} 项；最多显示 5 项，完整内容见来源事件。")
        lines.extend("  - " + excerpt(risk, 160) for risk in risks[:5])
    else:
        lines.append("- 遗留风险：交付记录未列出条目；不是无风险保证。")
    return "\n".join(lines) + "\n"


def _learning_view_text(task_dir: Path) -> str:
    """Keep outcomes short and link to the existing event, not four new reports."""
    try:
        rows = [json.loads(line) for line in _read(task_dir / "events.jsonl").splitlines() if line.strip()]
        row = next((row for row in reversed(rows) if isinstance(row, dict) and row.get("learning")), None)
    except (OSError, UnicodeError, ValueError):
        return "- 提炼详细记录：读取失败；不得视为已处理。\n"
    if row is None:
        return "- 提炼详细记录：历史未记录；旧 NOT_REQUIRED 不证明已评估，无新增追补义务。\n"
    value = row["learning"]
    lines = [f"- 提炼来源：`events.jsonl` `{row['id']}` / Runtime event `{row.get('runtime_event_id')}`。"]
    knowledge = value.get("knowledge") or []
    memory = value.get("memory") or []
    from .task_views import excerpt
    for label, items in (("知识处置", knowledge), ("记忆处置", memory)):
        lines.append(f"- {label}：{len(items)} 项；以下最多显示 5 项，全部处置按来源事件读取。")
        for item in items[:5]:
            lines.append(f"  - {item.get('id')}：{item.get('disposition')}；目标：`{item.get('target') or '未写入'}`；{excerpt(item.get('reason'), 160)}")
    if value.get("memory_summary"):
        lines.append("- 记忆判断摘要：" + excerpt(value["memory_summary"]))
    return "\n".join(lines) + "\n"


def _terminal_continuation_text(final_text: str) -> str:
    """An explicit terminal redirect, sealed with the final result's exact inputs."""
    from . import frontmatter
    parts = frontmatter.split(final_text)
    if parts is None:
        raise ValueError("terminal final view is not generated text")
    body = ("# 任务接续区\n\n- 状态：COMPLETED\n- 当前执行角色：无（任务已结束）\n"
            "- 下一责任 / 下一动作：无（任务已结束）\n\n"
            "> 此入口已随结单同步终态，仅供查询；不继续旧 ACTIVE 接续，不补造验收或新义务。\n\n"
            "[读取最终结项摘要](./final-result.md)；[范围与历史](../task.md)；[验收记录](../acceptance.md)。\n")
    text = "---\n" + parts[0] + "\n---\n\n" + body
    return frontmatter.set_value(text, "content_digest", "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest())

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

@command_context.measured("projection")
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
                         flush_id: str = "", before_prepare=None) -> Dict[str, str]:
    """一致性提交核心（durable journal 版）：

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
    effective_rel_paths = list(rel_paths)
    if target_state == "COMPLETED" and TERMINAL_MANIFEST_REL not in effective_rel_paths:
        effective_rel_paths.append(TERMINAL_MANIFEST_REL)
    if target_state == "COMPLETED" and "generated/continuation.md" not in effective_rel_paths:
        effective_rel_paths.append("generated/continuation.md")
    bak_dir = task_dir / f".v511-bak-{tx_id}"
    journal: Dict[str, Any] = {}
    journal_prepared = False
    db_committed = False
    transaction_started = False
    texts: Dict[str, str] = {}
    lock_scope = contextlib.ExitStack()

    try:
        try:
            # Acquire SQLite's single-writer lock before reading revision or copying
            # projection backups.  Concurrent writers therefore cannot prepare file
            # recovery state against a DB snapshot that another writer may advance.
            with command_context.span("lock_wait"):
                conn.execute("BEGIN IMMEDIATE")
            transaction_started = True
            lock_scope.enter_context(command_context.span("lock_held"))
            _assert_task_workspace_identity(conn, task_dir, task_id)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise ValueError(
                    "TASK_WRITER_BUSY: Runtime is already being updated by another writer; retry after it finishes"
                ) from exc
            raise

        if before_prepare is not None:
            before_prepare(conn)
        rev_before = transaction_journal.current_revision(conn, task_id)
        _backup(task_dir, bak_dir, effective_rel_paths)
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
                for rel in effective_rel_paths
            ],
            "created_at": dbmod.now_iso(),
            "updated_at": dbmod.now_iso(),
        }
        transaction_journal.write_journal(task_dir, journal)
        journal_prepared = True

        texts = db_and_render(conn, transaction_id=tx_id)
        if target_state == "COMPLETED":
            # Both entrypoints belong to the same recovery boundary and terminal seal.
            texts["generated/continuation.md"] = _terminal_continuation_text(texts["generated/final-result.md"])
            state_event = conn.execute(
                "SELECT id FROM task_event WHERE task_id=? AND event_type='STATE' "
                "AND to_state='COMPLETED' AND detail_json LIKE ? ORDER BY id DESC LIMIT 1",
                (task_id, f'%"{flush_id}"%'),
            ).fetchone()
            if state_event is None:
                raise ValueError("TERMINAL_MANIFEST_EVENT_MISSING: completion STATE event not found")
            texts[TERMINAL_MANIFEST_REL] = build_terminal_manifest_text(
                task_dir,
                task_id=task_id,
                terminal_state=target_state,
                terminal_event_id=int(state_event["id"]),
                overlays=texts,
            )
        journal["expected_revision_after"] = transaction_journal.current_revision(conn, task_id)
        _stage_and_replace(task_dir, texts, effective_rel_paths)
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
        with command_context.span("db_commit"):
            conn.execute("COMMIT")
        transaction_started = False
        db_committed = True
        lock_scope.close()
        journal["phase"] = PHASE_DB_COMMITTED
        transaction_journal.write_journal(task_dir, journal)
    except BaseException as exc:
        if transaction_started and not db_committed:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            transaction_started = False

        lock_scope.__exit__(type(exc), exc, exc.__traceback__)
        if db_committed:
            raise ReconciliationRequiredError(
                f"DB committed but post-commit step failed: {exc}; "
                f"evidence preserved (journal={tx_id}, backup={bak_dir}); "
                "run 'tp-spec reconcile' to resolve"
            ) from exc

        if journal_prepared:
            try:
                _restore(task_dir, bak_dir, effective_rel_paths, journal)
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
    finally:
        lock_scope.close()

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


@command_context.measured("projection")
def refresh_current_view(conn, task_dir: Path, task_id: str, *, summary: str = "",
                         flush_id: str = "", expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Rebuild only an unsealed view, after the fact transaction has committed.

    The writer lock prevents an older renderer overwriting a newer snapshot. A
    stale/missing view is detectable from its source digest, including after a
    process crash before this function. No new event or business state is written.
    Terminal manifests/final results remain in their existing atomic seal.
    """
    started = False
    lock_scope = contextlib.ExitStack()
    failure = (None, None, None)
    try:
        with command_context.span("lock_wait"):
            conn.execute("BEGIN IMMEDIATE")
        started = True
        lock_scope.enter_context(command_context.span("lock_held"))
        _assert_task_workspace_identity(conn, task_dir, task_id)
        if any(transaction_journal.transactions_dir(task_dir).glob("*.json")):
            # A malformed journal is unresolved too, not an absent transaction.
            raise ValueError("unresolved transaction journal; reconcile first")
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            raise ValueError("task not found")
        revision = transaction_journal.current_revision(conn, task_id)
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("fact revision advanced; rebuild against the latest projection")
        if str(task["current_state"] or "") in {"COMPLETED", "CANCELLED"}:
            conn.execute("ROLLBACK")
            started = False
            lock_scope.close()
            return {"view_status": "SEALED"}
        errors = projection_cmd.validate_projection_files(conn, task, task_dir)
        if errors:
            raise ValueError("required projections are stale; reconcile first")
        events = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        expected_events, _ = projection_cmd._build_events_jsonl(events, task_id)
        if (task_dir / "events.jsonl").read_text(encoding="utf-8") != expected_events:
            raise ValueError("required event projection differs from DB facts; reconcile first")
        if not summary:
            latest = conn.execute("SELECT summary FROM task_event WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
            summary = str(latest["summary"] or "") if latest else ""
        rel = _current_view_rel(str(task["current_state"] or ""))
        text = _rebuild_current_view_text(task_dir, task, summary, flush_id or f"VIEW-{uuid.uuid4().hex}")
        _stage_and_replace(task_dir, {rel: text}, [rel])
        # No DB write is part of a derived-only refresh.
        conn.execute("ROLLBACK")
        started = False
        lock_scope.close()
        return {"view_status": "CURRENT"}
    except Exception as exc:
        failure = (type(exc), exc, exc.__traceback__)
        try:
            print(f"DERIVED_VIEW_PENDING: view not updated; no business write attempted here; {type(exc).__name__}: {exc}; "
                  "use projection rebuild --view-only (reconcile first if required projections drifted)", file=sys.stderr)
        except Exception:
            # The machine result below still exposes PENDING and its recovery path.
            # A closed optional warning stream cannot undo committed facts.
            pass
        return {"view_status": "PENDING", "view_recovery": "projection rebuild --view-only"}
    finally:
        try:
            if started:
                conn.execute("ROLLBACK")
        finally:
            lock_scope.__exit__(*(sys.exc_info() if sys.exc_info()[0] else failure))
