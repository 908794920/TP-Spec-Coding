# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 数据库连接与 schema 管理（M0）。

仅依赖 Python 标准库（sqlite3/json/os/pathlib/datetime/typing）。
兼容 Python 3.8+。

职责：
- connect / init_schema / migrate / verify_schema
- resolve_db_path（按 §2.4 优先级：--db > TP_SPEC_DB > registry > cwd/.tp-spec/db/{project}.db）
- register_project / list_projects（machine-local registry.local.json 读写）
- transactional 上下文管理器（单事务语义）
- now_iso（统一 +08:00 时间格式）
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from cli.path_identity import canonical_path, same_path

# 模块基目录（cli/db.py 所在目录）
_MODULE_DIR = Path(__file__).resolve().parent
# tp-spec-base 根目录
_BASE_ROOT = _MODULE_DIR.parent
# schema.sql 路径（cli/../db/schema.sql）
_SCHEMA_SQL_PATH = (_MODULE_DIR / ".." / "db" / "schema.sql").resolve()
# migrations 目录
_MIGRATIONS_DIR = (_MODULE_DIR / ".." / "db" / "migrations").resolve()
# Runtime registry is machine-local state.  V5.2.3 originally stored the
# default under the Base checkout; that location remains read-only compatibility
# input so old installations can be migrated without losing registrations.
_LEGACY_REGISTRY_PATH = (_BASE_ROOT / "db" / "registry.local.json").resolve()

# 当前 CLI 期望的 schema 版本（M0）
EXPECTED_SCHEMA_VERSION = 1

# 时区：+08:00
_TZ_CN = timezone(timedelta(hours=8))


def now_iso() -> str:
    """返回 ISO 8601 +08:00 时间字符串，与既有 events.jsonl 一致。"""
    return datetime.now(_TZ_CN).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def connect(db_path: str) -> sqlite3.Connection:
    """连接 SQLite，开启 WAL 与外键，row_factory=Row。

    使用 isolation_level=None（autocommit），由 transactional 上下文器
    显式管理 BEGIN/COMMIT/ROLLBACK，保证单事务语义。
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """以 SQLite URI read-only 模式打开已有数据库，不创建/改写文件。"""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """读取 db/schema.sql 并 executescript；若无 schema_meta 记录则插入 (1, now)。

    executescript 在 autocommit 模式下立即生效，随后的事务插入 schema_meta。
    初始化核心 schema；当前个人模式不包含人员审批扩展表。
    """
    if not _SCHEMA_SQL_PATH.exists():
        raise FileNotFoundError(f"schema.sql not found: {_SCHEMA_SQL_PATH}")
    with open(_SCHEMA_SQL_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    conn.executescript(sql)
    row = conn.execute("SELECT COUNT(*) AS c FROM schema_meta").fetchone()
    if row["c"] == 0:
        with transactional(conn):
            # 核心 schema 版本为 1。
            conn.execute(
                "INSERT INTO schema_meta (schema_version, applied_at) VALUES (?, ?)",
                (1, now_iso()),
            )
    migrate(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """扫描 db/migrations/NNNN_*.sql，按 NNNN 升序应用未执行的迁移。

    初始 schema 视为 0001（由 init_schema 写入 schema_meta.schema_version=1）。
    目录为空或所有迁移已应用时直接返回。每个迁移在单事务内执行。
    """
    if not _MIGRATIONS_DIR.exists():
        return
    files: List[Tuple[int, Path]] = []
    for p in _MIGRATIONS_DIR.iterdir():
        if p.is_file() and p.suffix == ".sql":
            parts = p.stem.split("_", 1)
            if len(parts) == 2 and parts[0].isdigit():
                files.append((int(parts[0]), p))
    if not files:
        return
    files.sort(key=lambda x: x[0])
    row = conn.execute(
        "SELECT schema_version FROM schema_meta ORDER BY schema_version DESC LIMIT 1"
    ).fetchone()
    current_version = row["schema_version"] if row else 0
    for version, path in files:
        if version <= current_version:
            continue
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        # executescript 会隐式提交 DDL（不能包在 transactional 内，否则后续
        # COMMIT 会报 no transaction is active）。
        conn.executescript(sql)
        with transactional(conn):
            conn.execute(
                "UPDATE schema_meta SET schema_version = ?, applied_at = ?",
                (version, now_iso()),
            )


def verify_schema(conn: sqlite3.Connection) -> Tuple[bool, List[str]]:
    """校验核心 schema 与 schema_version=1。"""
    details: List[str] = []
    expected_tables = {"schema_meta", "project", "task", "task_event", "work_item", "config"}
    expected_indexes = {
        "idx_task_project",
        "idx_task_state",
        "idx_task_risk",
        "idx_event_task",
        "idx_event_type",
        "idx_event_time",
        "idx_workitem_task",
        "idx_workitem_status",
    }
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    actual_tables = {r["name"] for r in rows}
    missing_tables = expected_tables - actual_tables
    if missing_tables:
        details.append(f"missing tables: {sorted(missing_tables)}")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    actual_indexes = {r["name"] for r in rows if r["name"]}
    missing_indexes = expected_indexes - actual_indexes
    if missing_indexes:
        details.append(f"missing indexes: {sorted(missing_indexes)}")
    if "schema_meta" in actual_tables:
        row = conn.execute(
            "SELECT schema_version FROM schema_meta ORDER BY schema_version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            details.append("schema_meta empty")
        elif row["schema_version"] != EXPECTED_SCHEMA_VERSION:
            details.append(
                f"schema_version mismatch: expected {EXPECTED_SCHEMA_VERSION}, got {row['schema_version']}"
            )
    ok = not details
    return ok, details


def user_tp_spec_root() -> Path:
    """Return the machine-local TP-Spec-Coding state root without importing Base resolvers."""
    env = os.environ.get("TP_SPEC_USER_ROOT")
    if env:
        return canonical_path(env)
    return canonical_path(Path.home() / ".tp-spec")


def registry_default_path() -> Path:
    """Machine-local registry path, overridable with ``TP_SPEC_REGISTRY``."""
    env = os.environ.get("TP_SPEC_REGISTRY")
    if env:
        return canonical_path(env)
    return user_tp_spec_root() / "registry.local.json"


def legacy_registry_default_path() -> Path:
    """Former Base-local registry path kept only for migration compatibility."""
    return _LEGACY_REGISTRY_PATH


def registry_read_path(registry_path: Optional[str] = None) -> Path:
    """Resolve the registry authority for reads.

    Explicit/modern machine-local registry wins.  The old Base-local registry is
    consulted only when no modern registry exists, so new writes never recreate
    machine state inside the Base checkout.
    """
    if registry_path:
        return canonical_path(registry_path)
    current = registry_default_path()
    if current.exists():
        return current
    legacy = legacy_registry_default_path()
    if legacy.exists():
        return legacy
    return current


def _registry_mutation_paths(registry_path: Optional[str] = None) -> Tuple[Path, Path, bool]:
    """Return (read_source, write_target, remove_legacy_after_write).

    Machine-local runtime state must never be newly written into the Base checkout.
    When callers omit an explicit registry path and only the legacy Base-local
    registry exists, mutations are copy-on-write migrated to the modern
    machine-local registry and the legacy file is removed after a successful
    write. Explicit registry paths retain their caller-selected semantics.
    """
    if registry_path:
        explicit = canonical_path(registry_path)
        return explicit, explicit, False
    target = registry_default_path()
    if target.exists():
        return target, target, False
    legacy = legacy_registry_default_path()
    if legacy.exists():
        return legacy, target, True
    return target, target, False


def _write_registry_payload(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _finish_registry_copy_on_write(source: Path, target: Path, remove_source: bool) -> None:
    if remove_source and source != target and source.is_file():
        source.unlink()


def resolve_db_path(
    args_db: Optional[str] = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    """按优先级解析 db 路径：

    1. --db <path>
    2. TP_SPEC_DB 环境变量
    3. registry 中 project_id 对应的 db
    4. registry 中扫描包含 task_id 的 db
    5. cwd/.tp-spec/db/{project}.db（或 tpspec.db）

    legacy registry 中的相对路径仅作为兼容输入按 tp-spec-base 根解析；现代 machine-local registry 写入绝对路径。
    """
    if args_db:
        return args_db
    env_db = os.environ.get("TP_SPEC_DB")
    if env_db:
        return env_db
    reg_path = registry_read_path()
    if reg_path.exists() and project_id:
        resolved = _lookup_db_in_registry(reg_path, project_id=project_id)
        if resolved:
            return resolved
    if reg_path.exists() and task_id:
        resolved = _lookup_db_for_task(reg_path, task_id)
        if resolved:
            return resolved
    if project_id:
        return str((Path.cwd() / ".tp-spec" / "db" / f"{project_id}.db").resolve())
    return str((Path.cwd() / ".tp-spec" / "db" / "tpspec.db").resolve())


def _lookup_db_in_registry(reg_path: Path, project_id: str) -> Optional[str]:
    """在 registry 中按 project_id 查找 db 路径。"""
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    for proj in data.get("projects", []):
        if proj.get("project_id") == project_id:
            db_path = proj.get("db_path")
            if db_path:
                if os.path.isabs(db_path):
                    return db_path
                return str((_BASE_ROOT / db_path).resolve())
    return None


def _lookup_db_for_task(reg_path: Path, task_id: str) -> Optional[str]:
    """扫描 registry 中所有 db，找到包含该 task_id 的 db 路径。"""
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    for proj in data.get("projects", []):
        db_path = proj.get("db_path")
        if not db_path:
            continue
        if not os.path.isabs(db_path):
            db_path = str((_BASE_ROOT / db_path).resolve())
        if not os.path.exists(db_path):
            continue
        try:
            conn = connect(db_path)
            try:
                row = conn.execute(
                    "SELECT task_id FROM task WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is not None:
                    return db_path
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    return None


def register_project(
    project_id: str,
    db_path: str,
    root_path: str,
    base_version: str,
    schema_version: int,
    project_name: Optional[str] = None,
    registry_path: Optional[str] = None,
) -> Path:
    """将项目注册到 registry.local.json。

    db_path/root_path 作为 machine-local resolver cache 写入绝对路径。
    同 project_id 旧记录会被覆盖；portable identity 不依赖本文件。
    """
    reg_path = canonical_path(registry_path) if registry_path else registry_default_path()
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {"projects": []}
    seed_path = reg_path if reg_path.exists() else (registry_read_path() if registry_path is None else reg_path)
    if seed_path.exists():
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
                data = {"projects": []}
        except (json.JSONDecodeError, OSError):
            data = {"projects": []}
    projects = [p for p in data.get("projects", []) if p.get("project_id") != project_id]
    db_path_abs = str(canonical_path(db_path))
    root_path_abs = str(canonical_path(root_path))
    projects.append(
        {
            "project_id": project_id,
            "project_name": project_name or project_id,
            "db_path": db_path_abs,
            "root_path": root_path_abs,
            "base_version": base_version,
            "schema_version": schema_version,
        }
    )
    data["projects"] = projects
    # UTF-8 无 BOM
    with open(reg_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return reg_path



def update_registered_project_contract(
    project_id: str,
    base_version: str,
    registry_path: Optional[str] = None,
) -> bool:
    """Update only a registered project's base_version, preserving local paths/metadata.

    The registry is a local resolver cache, not the authoritative workflow ledger.
    Returns False when the project is not registered or the registry is unavailable.
    """
    read_path, write_path, remove_legacy = _registry_mutation_paths(registry_path)
    if not read_path.exists():
        return False
    try:
        with open(read_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        return False
    found = False
    for proj in data["projects"]:
        if isinstance(proj, dict) and proj.get("project_id") == project_id:
            proj["base_version"] = base_version
            found = True
            break
    if not found:
        return False
    _write_registry_payload(write_path, data)
    _finish_registry_copy_on_write(read_path, write_path, remove_legacy)
    return True


def list_projects(registry_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read project registrations from explicit/current registry, with legacy fallback."""
    reg_path = registry_read_path(registry_path)
    if not reg_path.exists():
        return []
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        return list(data.get("projects", []))
    except (json.JSONDecodeError, OSError):
        return []


def _resolve_project_db_abs(db_path: str) -> str:
    """将 registry 中的 db_path 解析为绝对路径（相对路径以 tp-spec-base 根为基准）。"""
    if os.path.isabs(db_path):
        return db_path
    return str((_BASE_ROOT / db_path).resolve())


def _read_registry_payload(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"projects": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid runtime registry {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ValueError(f"invalid runtime registry shape: {path}")
    return data


def migrate_legacy_registry_to_user(
    *,
    apply: bool = False,
    legacy_path: Optional[str] = None,
    target_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Plan/apply migration of Base-local runtime registry to machine-local state.

    Conflicting project identities fail closed.  On successful apply, the legacy
    file is removed only after the machine-local replacement is durably written.
    """
    legacy = canonical_path(legacy_path) if legacy_path else legacy_registry_default_path()
    target = canonical_path(target_path) if target_path else registry_default_path()
    if same_path(legacy, target):
        return {"status": "CURRENT", "legacy_path": str(legacy), "target_path": str(target), "actions": [], "conflicts": []}
    if not legacy.is_file():
        return {"status": "CURRENT", "legacy_path": str(legacy), "target_path": str(target), "actions": [], "conflicts": []}
    old = _read_registry_payload(legacy)
    current = _read_registry_payload(target) if target.is_file() else {"projects": []}
    merged = {str(p.get("project_id") or ""): dict(p) for p in current.get("projects", []) if isinstance(p, dict) and p.get("project_id")}
    actions: List[Dict[str, Any]] = []
    conflicts: List[str] = []
    for item in old.get("projects", []):
        if not isinstance(item, dict) or not item.get("project_id"):
            continue
        pid = str(item["project_id"])
        existing = merged.get(pid)
        if existing is None:
            merged[pid] = dict(item)
            actions.append({"action": "MIGRATE_RUNTIME_REGISTRY_ENTRY", "project_id": pid})
            continue
        old_root_raw = str(item.get("root_path") or "").strip()
        new_root_raw = str(existing.get("root_path") or "").strip()
        old_db_raw = str(item.get("db_path") or "").strip()
        new_db_raw = str(existing.get("db_path") or "").strip()
        roots_equal = bool(old_root_raw and new_root_raw and os.path.isabs(old_root_raw) and os.path.isabs(new_root_raw) and same_path(old_root_raw, new_root_raw))
        dbs_equal = bool(old_db_raw and new_db_raw and os.path.isabs(old_db_raw) and os.path.isabs(new_db_raw) and same_path(old_db_raw, new_db_raw))
        if old_root_raw and new_root_raw and not roots_equal:
            old_live = os.path.isabs(str(item.get("root_path") or "")) and Path(str(item.get("root_path"))).exists()
            new_live = os.path.isabs(str(existing.get("root_path") or "")) and Path(str(existing.get("root_path"))).exists()
            if old_live and new_live:
                conflicts.append(f"project {pid} has two live workspace roots in legacy and machine-local registries")
            elif old_live and not new_live:
                conflicts.append(f"project {pid} legacy registry points to a live workspace while machine-local root is stale")
            else:
                actions.append({"action": "DROP_STALE_LEGACY_RUNTIME_ENTRY", "project_id": pid, "legacy_root": item.get("root_path"), "current_root": existing.get("root_path")})
        elif old_db_raw and new_db_raw and not dbs_equal:
            old_db_live = os.path.isabs(str(item.get("db_path") or "")) and Path(str(item.get("db_path"))).exists()
            new_db_live = os.path.isabs(str(existing.get("db_path") or "")) and Path(str(existing.get("db_path"))).exists()
            if old_db_live and new_db_live:
                conflicts.append(f"project {pid} has two live Runtime DB paths in legacy and machine-local registries")
            elif old_db_live and not new_db_live:
                conflicts.append(f"project {pid} legacy Runtime DB is live while machine-local DB path is stale")
            else:
                actions.append({"action": "DROP_STALE_LEGACY_RUNTIME_ENTRY", "project_id": pid, "legacy_db": item.get("db_path"), "current_db": existing.get("db_path")})
    if conflicts:
        return {"status": "BLOCKED", "legacy_path": str(legacy), "target_path": str(target), "actions": actions, "conflicts": conflicts}
    actions.append({"action": "REMOVE_LEGACY_BASE_REGISTRY_AFTER_COPY", "path": str(legacy)})
    if not apply:
        return {"status": "MIGRATION_AVAILABLE", "legacy_path": str(legacy), "target_path": str(target), "actions": actions, "conflicts": []}
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"projects": sorted(merged.values(), key=lambda x: str(x.get("project_id") or ""))}
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    legacy.unlink()
    return {"status": "MIGRATED", "legacy_path": str(legacy), "target_path": str(target), "actions": actions, "conflicts": []}


def remove_project(project_id: str, registry_path: Optional[str] = None) -> bool:
    """从 registry 移除指定 project_id（不删 db 文件）。返回是否移除成功。

    仅操作 registry.local.json；db 文件保留由调用方决定是否物理删除。
    """
    read_path, write_path, remove_legacy = _registry_mutation_paths(registry_path)
    if not read_path.exists():
        return False
    try:
        with open(read_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        return False
    before = len(data["projects"])
    data["projects"] = [p for p in data["projects"] if p.get("project_id") != project_id]
    after = len(data["projects"])
    if after == before:
        return False
    _write_registry_payload(write_path, data)
    _finish_registry_copy_on_write(read_path, write_path, remove_legacy)
    return True


def prune_projects(registry_path: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """清理指向已删除 db 文件的 registry 条目。返回 (removed, kept)。

    遍历 registry projects，解析每个 db_path（相对路径以 tp-spec-base 根为基准），
    若文件不存在则移除该条目。db 存在但 schema 不兼容的不删（由 db verify 报告）。
    """
    read_path, write_path, remove_legacy = _registry_mutation_paths(registry_path)
    if not read_path.exists():
        return ([], [])
    try:
        with open(read_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ([], [])
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        return ([], [])
    removed: List[str] = []
    kept: List[str] = []
    survivors: List[Dict[str, Any]] = []
    for p in data["projects"]:
        pid = p.get("project_id", "")
        db_path = p.get("db_path")
        if not db_path:
            removed.append(pid)
            continue
        abs_db = _resolve_project_db_abs(db_path)
        if os.path.exists(abs_db):
            survivors.append(p)
            kept.append(pid)
        else:
            removed.append(pid)
    data["projects"] = survivors
    # 仅当有移除时才回写
    if removed:
        _write_registry_payload(write_path, data)
        _finish_registry_copy_on_write(read_path, write_path, remove_legacy)
    return (removed, kept)


def project_db_exists(project_entry: Dict[str, Any]) -> bool:
    """判断 registry 中单个 project 条目的 db_path 是否存在（供 list 标注用）。"""
    db_path = project_entry.get("db_path")
    if not db_path:
        return False
    return os.path.exists(_resolve_project_db_abs(db_path))


@contextmanager
def transactional(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """事务上下文：正常 commit，异常 rollback。

    配合 connect(isolation_level=None) 使用，显式 BEGIN/COMMIT/ROLLBACK。
    嵌套调用时内层 BEGIN 会失败（SQLite 不支持嵌套事务）——M0 不嵌套。
    """
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
