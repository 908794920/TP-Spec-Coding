# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.2.1 project / db 基础命令组。

仅依赖 Python 标准库。包含 project bootstrap/init/list 与 db verify；其他活动命令组
由 ``cli.main`` 分别注册。本模块不定义 Task 工作流语义。
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

from . import db as dbmod
from .config_loader import ConfigLoadError, gate_task_contract
from .environment import EnvironmentConfigError, load_project_binding, write_project_binding
from .path_identity import canonical_path, same_path
from .version import active_version

# project_id 合法字符：小写字母、数字、连字符
_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def cmd_project_init(args) -> int:
    project_id = args.id
    if not _PROJECT_ID_RE.match(project_id):
        print(
            f"ERROR: invalid project id '{project_id}' (must match ^[a-z0-9][a-z0-9-]*$)",
            file=sys.stderr,
        )
        return 2
    root_path = str(canonical_path(args.root or "."))
    base_version = args.base_version or active_version()
    try:
        binding = load_project_binding(root_path)
    except EnvironmentConfigError as exc:
        print(f"ERROR: invalid project binding: {exc}", file=sys.stderr)
        return 4
    if binding.exists and binding.project_id and binding.project_id != project_id:
        print(
            f"ERROR: project binding already identifies this workspace as '{binding.project_id}', "
            f"refusing init as '{project_id}'",
            file=sys.stderr,
        )
        return 4
    # 唯一活动契约门控：显式传入任何非当前版本立即拒绝（审计 P0-1 修复）
    try:
        gate_task_contract(base_version)
    except ConfigLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    # 解析 db 路径：--db 优先，否则 <root>/.tp-spec/db/<pid>.db
    if args.db:
        db_path = args.db
    else:
        db_path = os.path.join(root_path, ".tp-spec", "db", f"{project_id}.db")
    # 创建父目录
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    # 幂等创建已完成任务归档目录与持久执行区。
    # 只创建目录，绝不移动、删除、清空或扫描迁移其中内容；归档由用户手动管理。
    tp_spec_root = os.path.join(os.path.abspath(root_path), ".tp-spec")
    os.makedirs(os.path.join(tp_spec_root, "tasksHistory"), exist_ok=True)
    os.makedirs(os.path.join(tp_spec_root, ".execution"), exist_ok=True)
    # 连接 + init_schema
    conn = dbmod.connect(db_path)
    try:
        dbmod.init_schema(conn)
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                """
                INSERT OR REPLACE INTO project
                  (project_id, project_name, root_path, base_version,
                   schema_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    args.name or project_id,
                    root_path,
                    base_version,
                    dbmod.EXPECTED_SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
    finally:
        conn.close()
    # 写入 registry
    reg_path = dbmod.register_project(
        project_id=project_id,
        db_path=db_path,
        root_path=root_path,
        base_version=base_version,
        schema_version=dbmod.EXPECTED_SCHEMA_VERSION,
        project_name=args.name,
        registry_path=getattr(args, "registry", None),
    )
    if not binding.exists:
        binding_path = write_project_binding(
            root_path,
            project_id=project_id,
            base_version=base_version,
        )
        print(f"Project binding created: {binding_path}")
    print(f"Project initialized: {project_id} -> {db_path}")
    print(f"Registry updated: {reg_path}")
    return 0



def _dir_has_entries(path: str) -> bool:
    """Return True when a task/history directory contains any durable entry."""
    if not os.path.isdir(path):
        return False
    try:
        with os.scandir(path) as entries:
            return next(entries, None) is not None
    except OSError:
        # An unreadable ledger directory is ambiguous history, so bootstrap must fail closed.
        return True


def _registered_project(project_id: str, registry_path: Optional[str] = None):
    for item in dbmod.list_projects(registry_path=registry_path):
        if item.get("project_id") == project_id:
            return item
    return None


def cmd_project_bootstrap(args) -> int:
    """Safely initialize Runtime storage only for a strictly pristine project.

    This command is safe for Base health checks when ``--check-only`` is used:
    - an already-ready project is a no-op;
    - a missing DB is initialized only when there are no active/history task ledgers
      and no stale registry entry for the project;
    - ambiguous/non-pristine states fail closed and never rewrite SQLite/history.
    """
    project_id = args.id
    if not _PROJECT_ID_RE.match(project_id):
        print(
            f"ERROR: invalid project id '{project_id}' (must match ^[a-z0-9][a-z0-9-]*$)",
            file=sys.stderr,
        )
        return 2

    root_path = os.path.abspath(args.root or ".")
    registry_path = getattr(args, "registry", None)
    registered = _registered_project(project_id, registry_path)
    if args.db:
        db_path = args.db
    elif registered is not None:
        # Registry remains the resolver authority for custom DB locations. Do not silently
        # create a second default DB next to an already-registered project.
        registered_db = registered.get("db_path")
        db_path = dbmod._resolve_project_db_abs(registered_db) if registered_db else os.path.join(
            root_path, ".tp-spec", "db", f"{project_id}.db"
        )
    else:
        db_path = os.path.join(root_path, ".tp-spec", "db", f"{project_id}.db")

    # Existing DB: only report READY when the schema/project row are actually usable.
    if os.path.isfile(db_path):
        try:
            conn = dbmod.connect_readonly(db_path)
            try:
                ok, details = dbmod.verify_schema(conn)
                if not ok:
                    print(
                        "PROJECT_BOOTSTRAP_UNSAFE: existing database is not a valid Runtime database: "
                        + "; ".join(details),
                        file=sys.stderr,
                    )
                    return 4
                row = conn.execute(
                    "SELECT project_id, root_path, base_version FROM project WHERE project_id=?",
                    (project_id,),
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            print(
                f"PROJECT_BOOTSTRAP_UNSAFE: existing database cannot be verified: {exc}",
                file=sys.stderr,
            )
            return 4
        if row is None:
            print(
                f"PROJECT_BOOTSTRAP_UNSAFE: database exists but project '{project_id}' is not initialized in it",
                file=sys.stderr,
            )
            return 4
        if (row["base_version"] or "") != active_version():
            print(
                f"PROJECT_BOOTSTRAP_UNSAFE: project '{project_id}' uses contract {row['base_version']}; "
                f"run project upgrade-contract instead of bootstrap",
                file=sys.stderr,
            )
            return 4
        stored_root = str(row["root_path"] or "").strip()
        same_root = bool(stored_root and os.path.isabs(stored_root) and same_path(stored_root, root_path))
        if stored_root and not same_root:
            print(
                f"PROJECT_REBIND_REQUIRED: Runtime root_path={row['root_path']} differs from current workspace={root_path}; "
                "run base sync-project --apply after verifying project identity",
                file=sys.stderr,
            )
            return 4
        print(f"PROJECT_READY: {project_id} -> {db_path}")
        return 0

    # A registry entry whose DB vanished is historical/ambiguous, not pristine.
    if registered is not None:
        print(
            f"PROJECT_BOOTSTRAP_UNSAFE: project '{project_id}' is already registered but its database is missing; "
            "recover/prune the stale registration explicitly before bootstrap",
            file=sys.stderr,
        )
        return 4

    tp_spec_root = os.path.join(root_path, ".tp-spec")
    active_tasks = os.path.join(tp_spec_root, "tasks")
    history_tasks = os.path.join(tp_spec_root, "tasksHistory")
    if _dir_has_entries(active_tasks) or _dir_has_entries(history_tasks):
        print(
            "PROJECT_BOOTSTRAP_UNSAFE: task/history artifacts already exist while the Runtime DB is missing; "
            "refusing to create a new ledger over ambiguous history",
            file=sys.stderr,
        )
        return 4

    # Strict pristine state confirmed. A read-only Base health check stops here.
    if bool(getattr(args, "check_only", False)):
        print(f"PROJECT_BOOTSTRAP_AVAILABLE: pristine project can be initialized safely ({project_id})")
        return 0

    # Explicit bootstrap delegates the actual write to the official init path.
    init_args = type("ProjectInitArgs", (), {
        "id": project_id,
        "name": getattr(args, "name", None),
        "root": root_path,
        "base_version": None,
        "db": db_path,
        "registry": registry_path,
    })()
    rc = cmd_project_init(init_args)
    if rc == 0:
        print(f"PROJECT_BOOTSTRAPPED: pristine project initialized ({project_id})")
    return rc


def cmd_project_upgrade_contract(args) -> int:
    """Switch the project's active task contract without rewriting task history.

    This is the official project-level precursor to `task migration-plan` / `task migrate`.
    It changes only project.base_version plus the local registry resolver cache; each active
    task keeps its own base_version until explicitly migrated.
    """
    project_id = args.id
    if not _PROJECT_ID_RE.match(project_id):
        print(f"ERROR: invalid project id '{project_id}'", file=sys.stderr)
        return 2
    target = args.to or active_version()
    if target != active_version():
        print(f"ERROR: project upgrade-contract supports only active contract {active_version()}", file=sys.stderr)
        return 2
    db_path = dbmod.resolve_db_path(args.db, project_id=project_id)
    if not os.path.isfile(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 4
    conn = dbmod.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM project WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            print(f"ERROR: project not found in DB: {project_id}", file=sys.stderr)
            return 4
        old = str(row["base_version"] or "")
        if args.dry_run:
            print(f"project upgrade-contract dry-run: {project_id} {old or '<empty>'} -> {target}; task rows unchanged")
            return 0
        if old == target:
            updated_registry = dbmod.update_registered_project_contract(project_id, target, getattr(args, "registry", None))
            print(f"project upgrade-contract: already current ({project_id} -> {target}); registry_updated={str(updated_registry).lower()}")
            return 0
        now = dbmod.now_iso()
        audit = {
            "from_version": old,
            "to_version": target,
            "actor": args.actor,
            "changed_at": now,
            "policy": "project_contract_switch_only; active tasks require explicit task migrate",
        }
        import json
        with dbmod.transactional(conn):
            conn.execute("UPDATE project SET base_version=?, updated_at=? WHERE project_id=?", (target, now, project_id))
            conn.execute("""
                INSERT INTO config (key, scope, scope_id, value_json, description, updated_at)
                VALUES ('contract_upgrade_last', 'project', ?, ?, 'Last official project contract switch', ?)
                ON CONFLICT(key, scope, scope_id) DO UPDATE SET
                  value_json=excluded.value_json, description=excluded.description, updated_at=excluded.updated_at
            """, (project_id, json.dumps(audit, ensure_ascii=False), now))
        updated_registry = dbmod.update_registered_project_contract(project_id, target, getattr(args, "registry", None))
        print(
            f"project upgrade-contract: {project_id} {old or '<empty>'} -> {target}; "
            f"task rows unchanged; registry_updated={str(updated_registry).lower()}"
        )
        return 0
    finally:
        conn.close()


def cmd_project_list(args) -> int:
    projects = dbmod.list_projects(registry_path=getattr(args, "registry", None))
    if not projects:
        print("(no projects registered)")
        return 0
    headers = ["project_id", "project_name", "base_version", "schema_version", "db_ok", "root_path", "db_path"]
    rows = [
        [
            p.get("project_id", ""),
            p.get("project_name", ""),
            p.get("base_version", ""),
            str(p.get("schema_version", "")),
            "Y" if dbmod.project_db_exists(p) else "N",
            p.get("root_path", ""),
            p.get("db_path", ""),
        ]
        for p in projects
    ]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(v))

    def fmt_row(cells):
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    print(fmt_row(headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(fmt_row(r))
    # 标注失效库汇总
    invalid = [r[0] for r in rows if r[4] == "N"]
    if invalid:
        print(f"({len(invalid)} project(s) with missing db: {', '.join(invalid)}; run 'project prune' to clean)")
    return 0


def cmd_project_remove(args) -> int:
    project_id = args.id
    if not _PROJECT_ID_RE.match(project_id):
        print(
            f"ERROR: invalid project id '{project_id}' (must match ^[a-z0-9][a-z0-9-]*$)",
            file=sys.stderr,
        )
        return 2
    removed = dbmod.remove_project(project_id, registry_path=getattr(args, "registry", None))
    if removed:
        print(f"Project removed from registry: {project_id} (db file NOT deleted)")
        return 0
    print(f"ERROR: project not found in registry: {project_id}", file=sys.stderr)
    return 4


def cmd_project_prune(args) -> int:
    removed, kept = dbmod.prune_projects(registry_path=getattr(args, "registry", None))
    print(f"Prune complete: removed={len(removed)}, kept={len(kept)}")
    if removed:
        print(f"  removed: {', '.join(removed)}")
    if kept:
        print(f"  kept:    {', '.join(kept)}")
    return 0


def cmd_db_verify(args) -> int:
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None))
    conn = dbmod.connect(db_path)
    try:
        ok, details = dbmod.verify_schema(conn)
        if ok:
            # 业务表统计（排除 schema_meta 元数据表与 sqlite_ 内部表）
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'schema_meta'"
            ).fetchall()
            tables = [r["name"] for r in rows]
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            indexes = [r["name"] for r in rows]
            print(
                f"Schema OK: version={dbmod.EXPECTED_SCHEMA_VERSION}, "
                f"tables={len(tables)}, indexes={len(indexes)}"
            )
            return 0
        else:
            print("Schema FAIL:", file=sys.stderr)
            for d in details:
                print(f"  - {d}", file=sys.stderr)
            return 1
    finally:
        conn.close()


def add_project_subparsers(project_parser) -> None:
    """注册 project 命令组的子命令。"""
    sub = project_parser.add_subparsers(dest="subcommand", required=True)
    # project bootstrap (safe/idempotent health-check entry)
    p_bootstrap = sub.add_parser("bootstrap", help="Initialize Runtime storage only when the project is strictly pristine")
    p_bootstrap.add_argument("--id", required=True, help="project id (^[a-z0-9][a-z0-9-]*$)")
    p_bootstrap.add_argument("--name", required=False, default=None, help="project display name")
    p_bootstrap.add_argument("--root", required=False, default=".", help="workspace root (default: .)")
    p_bootstrap.add_argument("--db", required=False, default=None, help="db path (default: <root>/.tp-spec/db/<id>.db)")
    p_bootstrap.add_argument("--registry", required=False, default=None, help="registry path override")
    p_bootstrap.add_argument("--check-only", action="store_true", help="read-only health/pristine check; never initializes storage")
    p_bootstrap.set_defaults(func=cmd_project_bootstrap)

    # project init
    p_init = sub.add_parser("init", help="Initialize a project and register in DB")
    p_init.add_argument("--id", required=True, help="project id (^[a-z0-9][a-z0-9-]*$)")
    p_init.add_argument("--name", required=False, default=None, help="project display name")
    p_init.add_argument("--root", required=False, default=".", help="project root path (default: .)")
    p_init.add_argument(
        "--base-version", required=False, default=None, help="base_version (default: from VERSION)"
    )
    p_init.add_argument(
        "--db",
        required=False,
        default=None,
        help="db path (default: <root>/.tp-spec/db/<pid>.db)",
    )
    p_init.add_argument(
        "--registry",
        required=False,
        default=None,
        help="registry.local.json path (default: machine-local ~/.tp-spec/registry.local.json)",
    )
    p_init.set_defaults(func=cmd_project_init)

    # project upgrade-contract (switch project active contract; task migration remains explicit)
    p_upgrade = sub.add_parser("upgrade-contract", help="Switch project active contract; does not rewrite task history")
    p_upgrade.add_argument("--id", required=True, help="project id")
    p_upgrade.add_argument("--to", required=False, default=None, help="target contract (default: active VERSION)")
    p_upgrade.add_argument("--actor", required=False, default="human_owner", choices=["human_owner"])
    p_upgrade.add_argument("--db", required=False, default=None)
    p_upgrade.add_argument("--registry", required=False, default=None)
    p_upgrade.add_argument("--dry-run", action="store_true", help="report only; zero writes")
    p_upgrade.set_defaults(func=cmd_project_upgrade_contract)
    # project list
    p_list = sub.add_parser("list", help="List registered projects")
    p_list.add_argument("--registry", required=False, default=None)
    p_list.set_defaults(func=cmd_project_list)
    # project remove
    p_remove = sub.add_parser("remove", help="Remove a project from registry (db file kept)")
    p_remove.add_argument("--id", required=True, help="project id to remove")
    p_remove.add_argument("--registry", required=False, default=None)
    p_remove.set_defaults(func=cmd_project_remove)
    # project prune
    p_prune = sub.add_parser("prune", help="Prune registry entries whose db file is missing")
    p_prune.add_argument("--registry", required=False, default=None)
    p_prune.set_defaults(func=cmd_project_prune)


def add_db_subparsers(db_parser) -> None:
    """注册 db 命令组的子命令（M0 只实现 verify）。"""
    sub = db_parser.add_subparsers(dest="subcommand", required=True)
    # db verify
    p_verify = sub.add_parser("verify", help="Verify DB schema (5 tables + 8 indexes + version=1)")
    p_verify.add_argument("--db", required=False, default=None, help="db path")
    p_verify.add_argument(
        "--project",
        required=False,
        default=None,
        help="resolve db via registry by project_id",
    )
    p_verify.set_defaults(func=cmd_db_verify)
