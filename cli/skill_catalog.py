# -*- coding: utf-8 -*-
"""Read-only built-in/external skill discovery and source-scoped documents.

The Role Catalog stays authoritative for built-ins. User-owned source packages
are an overlay, never installed into Base or a business project. Nothing here
creates directories, executes source scripts, or records Runtime usage.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path, PureWindowsPath
from typing import Any

from . import config_loader, environment, frontmatter, orchestration
from .path_identity import canonical_path, path_identity_key
from .yaml_checks import YamlValidationError, parse_yaml_fail_closed

CATALOG_SCHEMA = "tp-spec.skill-catalog/v1"
DOCUMENT_SCHEMA = "tp-spec.skill-document/v1"
EXTERNAL_SCHEMA = "tp-spec.external-skills/v1"
MAX_DOCUMENT_BYTES = 512 * 1024
_CONFIG_FIELDS = {"entry", "name", "description", "enabled", "applies_to", "upstream", "version"}


class SkillCatalogError(ValueError):
    """Stable read failure, independent of the workbench/HTTP service."""

    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.status = status


def _problem(code: str, message: str, node_id: str = "") -> dict[str, str]:
    return {"code": code, "message": message, **({"node_id": node_id} if node_id else {})}


def _read_document(path: Path) -> tuple[str, str]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise SkillCatalogError("DOCUMENT_TOO_LARGE", "设定文档超过 512 KiB 读取限制", 413)
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise SkillCatalogError("DOCUMENT_UNREADABLE", f"文档不存在或不能按 UTF-8 读取：{path}", 404) from exc


def _document_path(root: Path, relative: str) -> Path:
    # Locators are source-relative paths, not URLs. Link fragments/URL decoding
    # belong to the caller; this also keeps literal '%' filenames addressable.
    if not isinstance(relative, str) or not relative or "\0" in relative:
        raise SkillCatalogError("INVALID_DOCUMENT", "文档相对路径无效", 400)
    relative = relative.replace("\\", "/")
    if relative.startswith("/") or PureWindowsPath(relative).drive:
        raise SkillCatalogError("INVALID_DOCUMENT", "文档路径必须相对于其来源目录", 400)
    try:
        path = (root / relative).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SkillCatalogError("INVALID_DOCUMENT", "文档路径不能解析", 400) from exc
    if not path.is_relative_to(root) or path.suffix.lower() != ".md":
        raise SkillCatalogError("INVALID_DOCUMENT", "仅支持本来源包内的 Markdown 文档", 400)
    return path


def _valid_package_name(name: Any) -> bool:
    return (isinstance(name, str) and bool(name.strip()) and name not in {".", ".."}
            and not any(char in name for char in "/\\:\0"))


def _configuration(path: Path) -> tuple[dict[str, Any], str]:
    try:
        path.lstat()
    except FileNotFoundError:
        return {}, ""
    except OSError as exc:
        return {}, f"外部配置不能读取：{exc}"
    try:
        # No cache: an edit/disable/removal must take effect on the next read,
        # including multiple reads within one CLI invocation.
        data = config_loader.load_config(path, use_cache=False)
        if data.get("schema") != EXTERNAL_SCHEMA:
            raise ValueError(f"schema 必须为 {EXTERNAL_SCHEMA}")
        if set(data) - {"schema", "skills"}:
            raise ValueError("外部配置仅支持 schema、skills 顶层字段")
        entries = data.get("skills", {})
        if not isinstance(entries, dict):
            raise ValueError("skills 必须为以来源包目录名为键的映射")
        if any(not isinstance(name, str) for name in entries):
            # A YAML bool/number key loses the original directory spelling.
            # Ignoring it could silently re-enable that directory's auto entry.
            raise ValueError("来源包键必须为字符串；数字或 on/off 等 YAML 隐式值请加引号")
        return entries, ""
    except (config_loader.ConfigLoadError, OSError, UnicodeError, ValueError, TypeError, RuntimeError) as exc:
        return {}, str(exc)


def _metadata(text: str, name: str) -> dict[str, Any]:
    # Reuse the existing delimiter parser; the appended newline is parse-only
    # for a closing delimiter at EOF and never changes returned file content.
    parts = frontmatter.split(text if text.endswith("\n") else text + "\n")
    if parts is not None:
        return parse_yaml_fail_closed(parts[0], name)
    lines = text.splitlines()
    if lines and lines[0] == "---":
        if len(lines) > 1 and lines[1] == "---":
            return {}
        raise YamlValidationError(f"{name}: front matter 未闭合或格式无效")
    return {}


def _text_field(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须为字符串")
    return value.strip()


def _descriptor_values(values: dict[str, Any], name: str) -> dict[str, Any]:
    version = values.get("version", "")
    if isinstance(version, bool) or not isinstance(version, (str, int, float)):
        raise ValueError("version 必须为字符串或数字声明")
    enabled = values.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须为 true 或 false")
    targets = values.get("applies_to", [])
    if not isinstance(targets, list) or any(not isinstance(x, str) or not x.strip() for x in targets):
        raise ValueError("applies_to 必须为非空角色/领域 ID 的列表")
    return {"name": _text_field(values, "name", name) or name,
            "description": _text_field(values, "description"),
            "upstream": _text_field(values, "upstream"), "version": str(version),
            "enabled": enabled, "applies_to": list(dict.fromkeys(x.strip() for x in targets))}


def _external_node(name: str, overrides: Any, library: Path, blocked: str,
                   problems: list[dict[str, str]]) -> dict[str, Any]:
    node_id = f"external:local:{name}"
    node: dict[str, Any] = {
        "id": node_id, "name": name, "kind": "capability-skill", "path": "SKILL.md",
        "source_kind": "external", "source_root": "", "description": "",
        "enabled": False, "status": "invalid", "reason": "", "auto_selectable": False,
        "applies_to": [], "upstream": "", "version": "", "entry_sha256": "",
    }

    def fail(code: str, message: str, status: str = "invalid") -> dict[str, Any]:
        node.update(status=status, reason=message, auto_selectable=False)
        problems.append(_problem(code, message, node_id))
        return node

    if not _valid_package_name(name):
        return fail("EXTERNAL_PACKAGE_INVALID", "来源包键必须是单个有效目录名")
    try:
        source = (library / name).resolve()
        if source == library or not source.is_relative_to(library):
            return fail("EXTERNAL_PACKAGE_INVALID", "来源包必须位于用户级 external-skills 目录内")
        node["source_root"] = str(source)
        if blocked:
            return fail("EXTERNAL_CONFIG_INVALID", blocked)
        if not isinstance(overrides, dict):
            return fail("EXTERNAL_ENTRY_INVALID", "来源包登记信息必须为映射")
        if set(overrides) - _CONFIG_FIELDS:
            return fail("EXTERNAL_ENTRY_INVALID", "来源包登记包含未知字段")
        # Keep explicit source labels/disable state visible even if its file is missing.
        node.update(_descriptor_values(overrides, name))
        entry = overrides.get("entry", "SKILL.md")
        node["path"] = entry if isinstance(entry, str) else ""
        path = _document_path(source, entry)
        node["path"] = path.relative_to(source).as_posix()
        try:
            path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return fail("EXTERNAL_ENTRY_MISSING", f"入口文档缺失：{node['path']}", "missing")
        text, digest = _read_document(path)
        metadata = _metadata(text, name)
        node.update(_descriptor_values({**metadata, **overrides}, name))
        enabled = node["enabled"]
        node.update(status="available" if enabled else "disabled",
                    reason="" if enabled else "用户已停用此能力", entry_sha256=digest,
                    auto_selectable=enabled and bool(node["description"]))
        return node
    except SkillCatalogError as exc:
        return fail(exc.code, str(exc))
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        return fail("EXTERNAL_ENTRY_INVALID", str(exc))


def load_skill_catalog(*, base_root: Path | None = None,
                       user_root: Path | None = None) -> dict[str, Any]:
    """Merge live external descriptors into a copy of the built-in projection."""
    base = canonical_path(base_root if base_root is not None else config_loader.default_base_root())
    user = canonical_path(user_root) if user_root is not None else environment.user_tp_spec_root()
    library = canonical_path(user / "external-skills")
    config = user / "external-skills.yaml"
    try:
        catalog = deepcopy(orchestration.load_role_topology(base))
    except (config_loader.ConfigLoadError, orchestration.OrchestrationError, OSError, ValueError, TypeError, RuntimeError) as exc:
        raise SkillCatalogError("TOPOLOGY_UNAVAILABLE", "内置能力目录读取失败") from exc
    catalog.update(schema=CATALOG_SCHEMA, generated=False, problems=[])
    nodes = catalog["nodes"]
    for node in nodes.values():
        node.update(source_kind="builtin", source_root=str(base), status="available", enabled=True)
    problems = catalog["problems"]
    entries, blocked = _configuration(config)
    if blocked:
        problems.append(_problem("EXTERNAL_CONFIG_INVALID", blocked))

    # Coalesce an enumerated directory with its explicitly registered locator.
    # This matters on Windows (case and 8.3 aliases). Ambiguous registrations
    # are diagnosed, rather than letting a second key undo a disable override.
    candidates: dict[str, Any] = {}
    identities: dict[str, list[str]] = {}
    for name, overrides in entries.items():
        candidates[name] = overrides
        if _valid_package_name(name):
            identities.setdefault(path_identity_key(library / name), []).append(name)
    try:
        children = sorted(library.iterdir(), key=lambda p: p.name)
    except FileNotFoundError:
        children = []
    except OSError as exc:
        children = []
        blocked = blocked or f"外部目录不能读取：{exc}"
        problems.append(_problem("EXTERNAL_DIRECTORY_UNREADABLE", str(exc)))
    for child in children:
        try:
            if not child.is_dir() or not (child / "SKILL.md").is_file():
                continue
        except OSError:
            # Keep the entry visible so its own read can report the failure.
            pass
        if path_identity_key(child) not in identities:
            candidates.setdefault(child.name, {})
    for name, overrides in candidates.items():
        aliases = identities.get(path_identity_key(library / name), []) if _valid_package_name(name) else []
        conflict = "多个登记键指向同一来源包：" + ", ".join(aliases) if len(aliases) > 1 else ""
        node = _external_node(name, overrides, library, blocked or conflict, problems)
        nodes[node["id"]] = node
        for target in node["applies_to"]:
            parent = nodes.get(target)
            if not parent or parent.get("kind") not in {"formal-role", "domain-agent"} or parent.get("source_kind") != "builtin":
                problems.append(_problem("EXTERNAL_ASSOCIATION_INVALID", f"关联不是已知领域/角色：{target}", node["id"]))
                continue
            catalog["edges"].append({"from": target, "to": node["id"], "relation": "uses", "mode": "declared"})
    catalog["external"] = {
        "root": str(library), "config_path": str(config),
        "status": "invalid" if blocked else "partial" if problems else "available" if candidates else "empty",
    }
    return catalog


def read_skill_document(node_id: str, document_path: str = "", *,
                        base_root: Path | None = None, user_root: Path | None = None,
                        allow_disabled: bool = False) -> dict[str, Any]:
    """Read a live Markdown file relative to its own source, never a project cwd.

    ``document_path`` is source-root-relative, not relative to the previously
    opened document. Callers resolve relative links and anchors before calling.
    ``allow_disabled`` is for an explicit human inspection, not skill selection.
    """
    catalog = load_skill_catalog(base_root=base_root, user_root=user_root)
    node = catalog["nodes"].get(node_id)
    if node is None:
        raise SkillCatalogError("NOT_FOUND", "未找到对应能力设定", 404)
    if node["status"] == "disabled" and not allow_disabled:
        raise SkillCatalogError("SKILL_DISABLED", "此能力已停用；不能作为当前执行能力读取", 409)
    if node["status"] not in {"available", "disabled"}:
        code = "SKILL_MISSING" if node["status"] == "missing" else "SKILL_INVALID"
        raise SkillCatalogError(code, node["reason"] or "能力来源当前不可用", 404 if code == "SKILL_MISSING" else 409)
    root = Path(node["source_root"])
    relative = document_path or node["path"]
    if node["source_kind"] == "builtin" and document_path:
        # Preserve the existing workbench publication check and error codes.
        try:
            published = {line.split("  ", 1)[1] for line in
                         (root / "manifest.sha256").read_text(encoding="utf-8").splitlines()
                         if "  " in line and not line.startswith("#")}
        except (OSError, UnicodeError) as exc:
            raise SkillCatalogError("DOCUMENT_INDEX_UNAVAILABLE", "文档目录不可读取") from exc
        if relative not in published:
            raise SkillCatalogError("DOCUMENT_NOT_PUBLISHED", "该链接不在公开文档目录中", 404)
    path = _document_path(root, relative)
    content, digest = _read_document(path)
    return {
        "schema": DOCUMENT_SCHEMA, "id": node_id, "path": path.relative_to(root).as_posix(),
        "content": content, "content_sha256": digest,
        "source_kind": node["source_kind"], "source_root": str(root),
        "status": node["status"], "enabled": node["enabled"], "entry_path": node["path"],
        "entry_sha256": node.get("entry_sha256", ""), "name": node["name"],
        "upstream": node.get("upstream", ""), "version": node.get("version", ""),
    }
