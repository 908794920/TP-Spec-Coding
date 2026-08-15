# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 config 命令组（M5-B）。

DB 后端开关与项目级配置，复用 M0 的 config 表。
config 表主键 (key, scope, scope_id)。

包含：
- config get    --key <k> [--scope <s>] [--scope-id <sid>]
- config set    --key <k> --value <v> [--scope <s>] [--scope-id <sid>]
- config list   [--scope <s>]

DB 后端开关约定：
- key = "db_backend_enabled"
- scope = "project"
- scope_id = <project_id>
- value_json = "true" 或 "false"
"""

from __future__ import annotations

import json
import sys
from typing import Optional

from . import db as dbmod


# config 表默认 scope
_DEFAULT_SCOPE = "project"


def _resolve_db(args) -> str:
    """config 命令的 db 解析：--db > --project > scope_id(当 scope=project) > registry > cwd 兜底。

    G1 治本：scope=project 时，scope_id 即 project_id（D 文档启用命令
    `config set --scope project --scope-id <pid>` 不传 --project 也能命中项目库）。
    这样 tp-spec.ps1 自动检测（按 task_id 扫 registry 读项目库）才能读到 flag。
    """
    project = getattr(args, "project", None)
    if not project and (getattr(args, "scope", None) or _DEFAULT_SCOPE) == "project":
        project = getattr(args, "scope_id", None)
    return dbmod.resolve_db_path(args.db, project_id=project)


def cmd_config_get(args) -> int:
    key = args.key
    scope = args.scope or _DEFAULT_SCOPE
    scope_id = args.scope_id
    db_path = _resolve_db(args)
    conn = dbmod.connect(db_path)
    try:
        if scope_id:
            row = conn.execute(
                "SELECT value_json, updated_at FROM config WHERE key = ? AND scope = ? AND scope_id = ?",
                (key, scope, scope_id),
            ).fetchone()
        else:
            # scope_id 未指定，查同 scope 下所有该 key 的行
            rows = conn.execute(
                "SELECT scope_id, value_json, updated_at FROM config WHERE key = ? AND scope = ? ORDER BY scope_id",
                (key, scope),
            ).fetchall()
            if not rows:
                print(f"(no config: key={key}, scope={scope})", file=sys.stderr)
                return 4
            for r in rows:
                print(f"{key} [{scope}/{r['scope_id'] or '-'}] = {r['value_json']}  (updated {r['updated_at']})")
            return 0
        if row is None:
            print(f"(no config: key={key}, scope={scope}, scope_id={scope_id})", file=sys.stderr)
            return 4
        print(f"{key} [{scope}/{scope_id}] = {row['value_json']}  (updated {row['updated_at']})")
        return 0
    finally:
        conn.close()


def cmd_config_set(args) -> int:
    key = args.key
    scope = args.scope or _DEFAULT_SCOPE
    scope_id = args.scope_id
    value = args.value
    # value 统一以 JSON 字符串存储（value_json 列）
    # 若 value 是 true/false/数字，转为 JSON 字面量；否则作为 JSON 字符串
    low = value.lower()
    if low in ("true", "false"):
        value_json = low
    elif value.lstrip("-").isdigit():
        value_json = value
    else:
        value_json = json.dumps(value, ensure_ascii=False)
    db_path = _resolve_db(args)
    conn = dbmod.connect(db_path)
    try:
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                """
                INSERT INTO config (key, scope, scope_id, value_json, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, scope, scope_id) DO UPDATE SET
                  value_json = excluded.value_json,
                  updated_at = excluded.updated_at
                """,
                (key, scope, scope_id, value_json, None, now),
            )
        print(f"Config set: {key} [{scope}/{scope_id or '-'}] = {value_json}")
        return 0
    finally:
        conn.close()


def cmd_config_list(args) -> int:
    scope = args.scope
    db_path = _resolve_db(args)
    conn = dbmod.connect(db_path)
    try:
        if scope:
            rows = conn.execute(
                "SELECT key, scope, scope_id, value_json, updated_at FROM config WHERE scope = ? ORDER BY key, scope_id",
                (scope,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, scope, scope_id, value_json, updated_at FROM config ORDER BY scope, key, scope_id"
            ).fetchall()
        if not rows:
            print("(no config entries)")
            return 0
        print(f"config entries ({len(rows)}):")
        for r in rows:
            print(f"  {r['key']} [{r['scope']}/{r['scope_id'] or '-'}] = {r['value_json']}  (updated {r['updated_at']})")
        return 0
    finally:
        conn.close()


# --- V5.2.2 C-01.4: controlled governed-YAML load subcommands ---

def _schema_to_jsonable(schema):
    """Render a schema dict with Python type objects as type-name strings."""
    out = {}
    for k, v in schema.items():
        if k == "properties" and isinstance(v, dict):
            props = {}
            for name, spec in v.items():
                s = dict(spec)
                if "type" in s and isinstance(s["type"], type):
                    s["type"] = s["type"].__name__
                props[name] = s
            out[k] = props
        else:
            out[k] = v
    return out


def _emit_load_error(exc) -> int:
    """Print a ConfigLoadError as JSON on stderr and return its exit code."""
    print(json.dumps(exc.to_json_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
    return exc.exit_code


def cmd_config_load(args) -> int:
    from cli import config_loader as cl
    try:
        data = cl.load_config(args.file, schema_name=args.schema, base_root=args.base_root)
    except cl.ConfigLoadError as exc:
        return _emit_load_error(exc)
    version = None
    if args.schema:
        from cli import config_schemas
        vf = config_schemas.get_schema(args.schema).get("version_field")
        if vf:
            version = cl._get_dotted(data, vf)
    print(json.dumps(
        {"status": "ok", "file": args.file, "schema": args.schema, "version": version, "data": data},
        ensure_ascii=False, indent=2,
    ))
    return 0


def cmd_config_validate(args) -> int:
    from cli import config_loader as cl
    try:
        data = cl.load_config(args.file, schema_name=args.schema, base_root=args.base_root)
    except cl.ConfigLoadError as exc:
        return _emit_load_error(exc)
    version = None
    if args.schema:
        from cli import config_schemas
        vf = config_schemas.get_schema(args.schema).get("version_field")
        if vf:
            version = cl._get_dotted(data, vf)
    print(json.dumps(
        {"status": "ok", "file": args.file, "schema": args.schema, "version": version, "valid": True},
        ensure_ascii=False, indent=2,
    ))
    return 0


def cmd_config_schema(args) -> int:
    from cli import config_schemas
    if args.name:
        try:
            schema = config_schemas.get_schema(args.name)
        except KeyError:
            print(json.dumps({"status": "error", "message": f"unknown schema: {args.name}"},
                             ensure_ascii=False), file=sys.stderr)
            return 4
        print(json.dumps(
            {"status": "ok", "schema": args.name, "definition": _schema_to_jsonable(schema)},
            ensure_ascii=False, indent=2,
        ))
        return 0
    print(json.dumps(
        {"status": "ok", "schemas": {n: _schema_to_jsonable(s) for n, s in config_schemas.SCHEMAS.items()}},
        ensure_ascii=False, indent=2,
    ))
    return 0


def cmd_config_dump(args) -> int:
    from cli import config_loader as cl
    from cli import config_schemas
    try:
        all_data = cl.load_all_governance(base_root=args.base_root)
    except cl.ConfigLoadError as exc:
        return _emit_load_error(exc)
    files = {}
    for name, data in all_data.items():
        vf = config_schemas.get_schema(name).get("version_field")
        files[name] = {"version": cl._get_dotted(data, vf) if vf else None, "data": data}
    print(json.dumps({"status": "ok", "files": files}, ensure_ascii=False, indent=2))
    return 0


def cmd_config_gate(args) -> int:
    from cli import config_loader as cl
    try:
        cl.gate_task_contract(args.task_version, base_root=args.base_root)
    except cl.ConfigLoadError as exc:
        return _emit_load_error(exc)
    base_version = cl.read_base_version(args.base_root)
    print(json.dumps(
        {"status": "ok", "task_version": args.task_version, "base_version": base_version, "accepted": True},
        ensure_ascii=False, indent=2,
    ))
    return 0


def add_config_subparsers(config_parser) -> None:
    """注册 config 命令组的子命令。"""
    sub = config_parser.add_subparsers(dest="subcommand", required=True)

    # config get
    p_get = sub.add_parser("get", help="Get a config value")
    p_get.add_argument("--key", required=True, help="config key")
    p_get.add_argument("--scope", required=False, default=None, help="scope (default: project)")
    p_get.add_argument("--scope-id", required=False, default=None, help="scope id (e.g. project_id)")
    p_get.add_argument("--project", required=False, default=None, help="resolve db via registry by project_id")
    p_get.add_argument("--db", required=False, default=None)
    p_get.set_defaults(func=cmd_config_get)

    # config set
    p_set = sub.add_parser("set", help="Set a config value (upsert)")
    p_set.add_argument("--key", required=True, help="config key")
    p_set.add_argument("--value", required=True, help="config value (true/false/number/string)")
    p_set.add_argument("--scope", required=False, default=None, help="scope (default: project)")
    p_set.add_argument("--scope-id", required=False, default=None, help="scope id (e.g. project_id)")
    p_set.add_argument("--project", required=False, default=None, help="resolve db via registry by project_id")
    p_set.add_argument("--db", required=False, default=None)
    p_set.set_defaults(func=cmd_config_set)

    # config list
    p_list = sub.add_parser("list", help="List config entries")
    p_list.add_argument("--scope", required=False, default=None)
    p_list.add_argument("--project", required=False, default=None, help="resolve db via registry by project_id")
    p_list.add_argument("--db", required=False, default=None)
    p_list.set_defaults(func=cmd_config_list)

    # --- V5.2.2 C-01.4: controlled governed-YAML load subcommands ---
    p_load = sub.add_parser("load", help="Load a governed YAML file, output read-only JSON")
    p_load.add_argument("--file", required=True, help="YAML file path (relative to base root or absolute)")
    p_load.add_argument("--schema", required=False, default=None, help="schema name for validation")
    p_load.add_argument("--base-root", required=False, default=None, help="base root directory")
    p_load.set_defaults(func=cmd_config_load)

    p_validate = sub.add_parser("validate", help="Validate a governed YAML file (no data output)")
    p_validate.add_argument("--file", required=True)
    p_validate.add_argument("--schema", required=False, default=None)
    p_validate.add_argument("--base-root", required=False, default=None)
    p_validate.set_defaults(func=cmd_config_validate)

    p_schema = sub.add_parser("schema", help="Show registered schema definition(s)")
    p_schema.add_argument("--name", required=False, default=None, help="schema name (omit to list all)")
    p_schema.set_defaults(func=cmd_config_schema)

    p_dump = sub.add_parser("dump", help="Load all governance files, output combined JSON")
    p_dump.add_argument("--base-root", required=False, default=None)
    p_dump.set_defaults(func=cmd_config_dump)

    p_gate = sub.add_parser("gate", help="Gate a task contract version against base (full exact match, M2)")
    p_gate.add_argument("--task-version", required=True, help="task artifact_contract.version")
    p_gate.add_argument("--base-root", required=False, default=None)
    p_gate.set_defaults(func=cmd_config_gate)
