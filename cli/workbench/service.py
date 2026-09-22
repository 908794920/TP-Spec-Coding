# -*- coding: utf-8 -*-
"""Read service over the existing registry, snapshots and Runtime resolvers."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterator

from cli import db as dbmod, environment, record_first
from cli.path_identity import canonical_path, path_identity_key, same_path
from cli.version import active_version
from . import snapshot
from .details import build_task_details
from .serialization import _strip_sensitive

SCHEMA = "tp-spec.workbench/v1"
BASE_ROOT = Path(__file__).resolve().parents[2]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ReadError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Context:
    context_key: str
    project_id: str
    name: str
    project_root: str
    workspace_root: str
    db_path: str
    registry_path: str
    source: str

    @classmethod
    def from_entry(cls, entry: dict[str, Any], registry: Path, workspace: Path, source: str) -> "Context":
        root = canonical_path(str(entry["root_path"]))
        database = snapshot._registered_db_path(entry)
        identity = [str(entry["project_id"]), path_identity_key(root), path_identity_key(workspace),
                    path_identity_key(database) if database else ""]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
        return cls(key, identity[0], str(entry.get("project_name") or identity[0]), str(root),
                   str(workspace), str(database or ""), str(registry), source)

    def registry_entry(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "project_name": self.name,
                "root_path": self.project_root, "db_path": self.db_path}


def read_contexts() -> tuple[list[Context], list[dict[str, str]]]:
    """Only explicit registrations/bindings; no directory discovery or guessed IDs."""
    registry, entries, error = snapshot._read_registry()
    problems: list[dict[str, str]] = []
    if error:
        return [], [snapshot._problem("REGISTRY_INVALID", error, severity="error")]
    contexts: dict[str, Context] = {}
    usable: list[dict[str, Any]] = []
    for entry in entries:
        if not str(entry.get("project_id") or "").strip() or not str(entry.get("root_path") or "").strip():
            problems.append(snapshot._problem("CONTEXT_INCOMPLETE", "Registry 项缺少 project_id 或 root_path"))
            continue
        root = canonical_path(str(entry["root_path"]))
        context = Context.from_entry(entry, registry, root, "registry-root")
        if context.context_key in contexts:
            problems.append(snapshot._problem("CONTEXT_DUPLICATE", f"重复 Registry 项：{context.project_id}"))
        contexts[context.context_key] = context
        usable.append(entry)
    try:
        inventory = environment.load_workspace_inventory()
        for row in inventory.workspaces:
            raw = str(row.get("root") or "").strip()
            if not raw:
                continue
            root = Path(raw).expanduser()
            root = canonical_path(root if root.is_absolute() else inventory.path.parent / root)
            if any(same_path(root, ctx.workspace_root) for ctx in contexts.values()):
                continue
            binding = environment.load_project_binding(root)
            matches = [entry for entry in usable if str(entry["project_id"]) == binding.project_id]
            if len(matches) == 1:
                context = Context.from_entry(matches[0], registry, root, "workspace-inventory+project-binding")
                contexts[context.context_key] = context
            elif binding.project_id:
                problems.append(snapshot._problem("WORKSPACE_RUNTIME_UNRESOLVED",
                                                  f"工作区 {root} 没有唯一 Runtime 注册：{binding.project_id}"))
    except (OSError, ValueError, UnicodeError) as exc:
        problems.append(snapshot._problem("WORKSPACE_CONTEXT_UNREADABLE", str(exc)))
    return sorted(contexts.values(), key=lambda ctx: (ctx.name, ctx.workspace_root, ctx.db_path)), problems


class WorkbenchService:
    def __init__(self, *, instance_id: str = "standalone"):
        self.instance_id = instance_id

    def health(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "ready": True, "instance_id": self.instance_id,
                "source_root": str(BASE_ROOT), "version": active_version(BASE_ROOT),
                "python_executable": sys.executable, "user_root": str(environment.user_tp_spec_root()),
                "registry_path": str(dbmod.registry_read_path()), "read_only": True}

    def _context(self, key: str) -> Context:
        contexts, problems = read_contexts()
        matches = [ctx for ctx in contexts if ctx.context_key == key]
        if len(matches) != 1:
            if any(row["code"] == "REGISTRY_INVALID" for row in problems):
                raise ReadError("REGISTRY_INVALID", "当前 Registry 不可读，不能确认项目上下文")
            raise ReadError("CONTEXT_NOT_FOUND", "项目/工作区上下文不存在或注册已经变化，请刷新项目索引", 404)
        context = matches[0]
        try:
            binding = environment.load_project_binding(context.workspace_root)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReadError("PROJECT_BINDING_INVALID", str(exc), 409) from exc
        if binding.project_id and binding.project_id != context.project_id:
            raise ReadError("PROJECT_IDENTITY_CONFLICT", "选中工作区的 Binding 与 Registry 项目身份不一致", 409)
        return context

    @contextmanager
    def _database(self, context: Context) -> Iterator[sqlite3.Connection]:
        if not context.db_path or not Path(context.db_path).is_file():
            raise ReadError("RUNTIME_MISSING", f"Runtime 不存在：{context.db_path or '未配置'}；读取不会初始化数据库", 404)
        try:
            conn = dbmod.connect_readonly(context.db_path)
            try:
                conn.execute("BEGIN")
                project = conn.execute("SELECT * FROM project WHERE project_id=?", (context.project_id,)).fetchone()
                if project is None:
                    raise ReadError("PROJECT_NOT_IN_RUNTIME", "选中项目不属于该 Runtime", 409)
                if not project["root_path"] or not same_path(project["root_path"], context.project_root):
                    raise ReadError("PROJECT_ROOT_CONFLICT", "Registry 根目录与 Runtime 项目根目录不一致", 409)
                yield conn
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise ReadError("RUNTIME_READ_ERROR", f"Runtime 只读查询失败：{exc}") from exc

    @staticmethod
    def _task(conn: sqlite3.Connection, context: Context, task_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM task WHERE task_id=? AND project_id=?", (task_id, context.project_id)).fetchone()
        if row is None:
            raise ReadError("TASK_NOT_FOUND", "当前项目内不存在该 Task；不会搜索或使用其他项目同名任务", 404)
        return dict(row)

    @staticmethod
    def _task_revision(conn: sqlite3.Connection, task: dict[str, Any]) -> str:
        """Ledger observation marker only; it does not claim atomicity with files."""
        latest = conn.execute("SELECT MAX(id) FROM task_event WHERE task_id=?", (task["task_id"],)).fetchone()[0]
        payload = json.dumps([task, latest], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _response(data: dict[str, Any], context: Context | None, started: str, *, database: bool = False, task_revision: str = "") -> dict[str, Any]:
        data = dict(data)
        partial = bool(data.get("problems")) or data.get("health") in {"degraded", "unavailable"}
        return _strip_sensitive({"schema": SCHEMA, "context": asdict(context) if context else None,
                "read": {"started_at": started, "completed_at": timestamp(),
                         **({"task_revision": task_revision} if task_revision else {}),
                         "consistency": "sqlite_transaction+live_files" if database else "live_files",
                         "completeness": "partial" if partial else "complete",
                         "note": ("数据库字段来自同一只读事务；配置、任务工件和证据文件是实时读取，不承诺跨介质原子快照。"
                                  if database else "配置、注册表和工作区清单是实时文件读取，不承诺多个文件的原子快照。")},
                "data": data})

    def skill_document(self, node_id: str, document_path: str = "") -> dict[str, Any]:
        topology, error = snapshot._read_skill_topology(BASE_ROOT)
        if error:
            raise ReadError("TOPOLOGY_UNAVAILABLE", "能力目录读取失败")
        node = topology["nodes"].get(node_id)
        if not node:
            raise ReadError("NOT_FOUND", "未找到对应能力设定", 404)
        relative = document_path or str(node.get("path") or "")
        if document_path:
            try:
                published = {line.split("  ", 1)[1] for line in
                             (BASE_ROOT / "manifest.sha256").read_text(encoding="utf-8").splitlines()
                             if "  " in line and not line.startswith("#")}
            except OSError:
                raise ReadError("DOCUMENT_INDEX_UNAVAILABLE", "文档目录不可读取")
            if relative not in published:
                raise ReadError("DOCUMENT_NOT_PUBLISHED", "该链接不在公开文档目录中", 404)
        path = (BASE_ROOT / relative).resolve()
        if not path.is_relative_to(BASE_ROOT.resolve()) or path.suffix.lower() != ".md":
            raise ReadError("INVALID_DOCUMENT", "设定文档路径不受支持", 400)
        try:
            with path.open("rb") as handle:
                raw = handle.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ReadError("DOCUMENT_TOO_LARGE", "设定文档超过读取大小限制", 413)
            content = raw.decode("utf-8-sig")
        except (OSError, UnicodeError):
            raise ReadError("DOCUMENT_UNREADABLE", "设定文档不存在或无法读取", 404)
        return {"schema": SCHEMA, "id": node_id, "path": path.relative_to(BASE_ROOT.resolve()).as_posix(), "content": content}

    def global_view(self) -> dict[str, Any]:
        started = timestamp()
        data = snapshot.build_global_snapshot(active_base_root=BASE_ROOT)
        data["active_source_root"] = str(BASE_ROOT)
        contexts, issues = read_contexts()
        data["contexts"] = [asdict(ctx) for ctx in contexts]
        data["problems"] = [*data.get("problems", []), *issues]
        return self._response(data, None, started)

    def wiki_view(self, operation: str, parameters: dict[str, list[str]]) -> dict[str, Any]:
        if operation not in {"overview", "documents", "document", "search", "records"}:
            raise ReadError("NOT_FOUND", "Wiki 接口不存在", 404)
        from .wiki_view import WikiView
        started = timestamp()

        def value(name, default=""):
            values = parameters.get(name, [default])
            if len(values) != 1:
                raise ReadError("INVALID_QUERY", f"参数不能重复：{name}", 400)
            return values[0]

        try:
            days, page = int(value("days", "30")), int(value("page", "1"))
        except ValueError as exc:
            raise ReadError("INVALID_QUERY", "时间范围和页码必须为整数", 400) from exc
        if days not in {7, 30, 90} or not 1 <= page <= 100000:
            raise ReadError("INVALID_QUERY", "时间范围或页码不受支持", 400)
        query, status, date = value("q").strip(), value("status", "all"), value("date")
        if len(query) > 512 or status not in {"all", "hit", "zero", "failed"}:
            raise ReadError("INVALID_QUERY", "查询内容或状态不受支持", 400)
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError as exc:
                raise ReadError("INVALID_QUERY", "日期须为 YYYY-MM-DD", 400) from exc
        contexts, issues = read_contexts()
        view = WikiView(self, contexts, issues, days=days, project=value("project"))
        if operation == "overview":
            data = view.overview()
        elif operation in {"documents", "search"}:
            data = view.documents_view(page=page, query=query, repo=value("repo"), kind=value("kind"),
                                       adopted=value("adopted") == "1")
        elif operation == "document":
            data = view.document_view(value("id"))
        elif operation == "records":
            data = view.records_view(page=page, status=status, date=date, query=query)
        else:
            raise ReadError("NOT_FOUND", "Wiki 接口不存在", 404)
        result = self._response(data, None, started)
        result["read"].update(consistency="independent_readonly_snapshots+live_files",
            note="各项目 Runtime、Wiki 索引及日志分别只读；跨来源与实时文件不承诺原子快照。页面读取不会采集使用量。")
        return result

    def project_view(self, key: str) -> dict[str, Any]:
        started, context = timestamp(), self._context(key)
        with self._database(context) as conn:
            data = snapshot.build_project_snapshot(context.workspace_root,
                registry_path=context.registry_path, base_root=BASE_ROOT, connection=conn,
                registry_entries=[context.registry_entry()])
            if data.get("project", {}).get("runtime_status") != "available":
                raise ReadError("PROJECT_READ_FAILED", "项目快照未能读取当前 Runtime；请检查数据库结构")
        return self._response(data, context, started, database=True)

    def task_view(self, key: str, task_id: str) -> dict[str, Any]:
        started, context = timestamp(), self._context(key)
        with self._database(context) as conn:
            task = self._task(conn, context, task_id)
            revision = self._task_revision(conn, task)
            data = snapshot.build_task_snapshot(task_id, db_path=context.db_path, base_root=BASE_ROOT, connection=conn)
            if data.get("health") == "unavailable":
                raise ReadError("TASK_READ_FAILED", "Task 快照读取失败")
            # Evidence View and this top-level summary are historical projections,
            # not the current-subject verdict consumed by the Runtime itself.
            data["verification"] = {**data.get("verification", {}), "current_applicability": "not_evaluated",
                                    "source": "historical_task_event"}
            from cli.task_views import inspect_task_views
            from cli.execution import read_execution
            rows = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
            task_dir = Path(context.project_root) / ".tp-spec" / "tasks" / task_id
            data["documents"] = inspect_task_views(task_dir, task, events=rows,
                                                   execution=read_execution(conn, task, rows=rows))
            data["problems"] = [*data.get("problems", []), *data["documents"]["problems"]]
            data["timeline_scope"] = {"limit": 50, "returned": len(data.get("timeline", [])),
                "total": conn.execute("SELECT count(*) FROM task_event WHERE task_id=?", (task_id,)).fetchone()[0]}
        return self._response(data, context, started, database=True, task_revision=revision)

    def details_view(self, key: str, task_id: str) -> dict[str, Any]:
        started, context = timestamp(), self._context(key)
        with self._database(context) as conn:
            task = self._task(conn, context, task_id)
            revision = self._task_revision(conn, task)
            task_dir = Path(context.project_root) / ".tp-spec" / "tasks" / task_id
            data = build_task_details(conn, task, task_dir)
        return self._response(data, context, started, database=True, task_revision=revision)

    def closeout_view(self, key: str, task_id: str) -> dict[str, Any]:
        started, context = timestamp(), self._context(key)
        with self._database(context) as conn:
            task = self._task(conn, context, task_id)
            revision = self._task_revision(conn, task)
            task_dir = Path(context.project_root) / ".tp-spec" / "tasks" / task_id
            if not task_dir.is_dir():
                raise ReadError("TASK_ARTIFACTS_MISSING", "任务工件目录不存在，未取得结单预检；不会自动创建", 409)
            try:
                data = record_first.completion_check(task_id=task_id, task_dir=str(task_dir),
                                                     db=context.db_path, connection=conn, base_root=BASE_ROOT)
            except (OSError, UnicodeError, ValueError) as exc:
                raise ReadError("CLOSEOUT_UNAVAILABLE", f"既有结单预检未能完成：{exc}", 409) from exc
        data["source"] = "record_first.completion_check"
        if data.get("unknowns"):
            data["problems"] = [{"code": "CLOSEOUT_PARTIAL", "message": "部分必需检查尚未取得确定结果；已知问题保留，未知项不会视为通过。"}]
        return self._response(data, context, started, database=True, task_revision=revision)
