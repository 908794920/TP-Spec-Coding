"""Knowledge locator 的有限历史路径兼容；不改变治理证据校验。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


@dataclass(frozen=True)
class LocatorFile:
    path: Path
    ref: str
    source_root: str


def resolve_locator_file(task: dict, task_dir: Path, ref: str) -> LocatorFile | None:
    """只解析明确的项目文档或同 Task evidence 别名，不搜索归档副本。"""
    normalized = ref.replace("\\", "/").strip()
    relative = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    if relative.is_absolute() or windows.drive or windows.root or ":" in normalized:
        raise ValueError("locator must be an unambiguous relative local path")

    parts = relative.parts
    legacy_docs = parts[:3] == ("..", "..", "docs")
    project_docs = parts[:2] == (".tp-spec", "docs")
    project_task = parts[:2] == (".tp-spec", "tasks")
    archived_task = parts[:2] == (".tp-spec", "tasksHistory")
    if not (legacy_docs or project_docs or project_task or archived_task):
        return None  # 普通 Task-relative 引用继续走原校验器。

    declared_root = task.get("project_root_path")
    if not isinstance(declared_root, str) or not declared_root.strip() or not Path(declared_root).is_absolute():
        raise ValueError("registered project root is unavailable for this locator")
    project_root = Path(declared_root).resolve(strict=True)
    selected = task_dir.absolute()
    try:
        selected_parts = selected.relative_to(project_root).parts
    except ValueError as exc:
        raise ValueError("selected Task directory is outside the registered project") from exc
    task_id = task["task_id"]
    active = selected_parts == (".tp-spec", "tasks", task_id)
    archived = (len(selected_parts) == 4 and selected_parts[:2] == (".tp-spec", "tasksHistory")
                and re.fullmatch(r"[1-9][0-9]{3}(?:0[1-9]|1[0-2])", selected_parts[2])
                and selected_parts[3] == task_id)
    if not (active or archived) or selected.resolve(strict=True) != selected:
        raise ValueError("selected directory is not the exact registered Task or archive directory")

    if legacy_docs or project_docs:
        # 归档不改变旧 ../../docs 的活动 Task 语义锚。
        tail = parts[3:] if legacy_docs else parts[2:]
        allowed_root = project_root / ".tp-spec" / "docs"
        source_root = "project"
    else:
        prefix = (".tp-spec", "tasks", task_id, "evidence")
        if archived_task:
            prefix = (*selected_parts, "evidence")
            if not archived:
                raise ValueError("archive locator does not match the selected Task archive")
        if parts[:len(prefix)] != prefix:
            raise ValueError("project evidence locator must identify this exact Task and archive")
        tail = parts[len(prefix):]
        allowed_root = selected / "evidence"
        source_root = "task"

    if not tail or any(part in {"..", "."} for part in tail):
        raise ValueError("locator suffix must stay inside its declared source root")
    # 根目录本身的链接也不能将授权范围重定向到别处。
    if allowed_root.resolve(strict=True) != allowed_root:
        raise ValueError("locator source root is redirected by a filesystem link")
    target = (allowed_root / Path(*tail)).resolve(strict=True)
    if not target.is_relative_to(allowed_root):
        raise ValueError("locator target escapes its declared source root")
    if not target.is_file():
        raise ValueError("locator target is not a regular file")
    if target.stat().st_size == 0:
        raise ValueError("locator file is empty (0 bytes)")
    reference_root = project_root if source_root == "project" else selected
    return LocatorFile(target, target.relative_to(reference_root).as_posix(), source_root)
