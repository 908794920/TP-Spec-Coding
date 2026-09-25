from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

import yaml

AGENT_BEGIN = "<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->"
AGENT_END = "<!-- TP-SPEC:AGENT-TOPOLOGY-END -->"
DOCS_AGENT_BEGIN = "<!-- TP-SPEC:AGENT-MAP-BEGIN -->"
DOCS_AGENT_END = "<!-- TP-SPEC:AGENT-MAP-END -->"
DELETED_PROCESS_PREFIXES = (
    "docs/cloud-ai-prompts/",
    "docs/superpowers/",
    "docs/history/",
)
CORE_DOCUMENTS = (
    "README.md",
    "docs/README.md",
    "docs/GETTING_STARTED.md",
    "docs/AGENTS_AND_SKILLS.md",
)

_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_ANGLE_RE = re.compile(r"<([^<>\s]+)>")
_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)


def _load_catalog(catalog_path: Path) -> dict:
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("roles"), list):
        raise ValueError(f"invalid role catalog: {catalog_path}")
    return data


def load_public_agent_ids(catalog_path: Path) -> list[str]:
    result: list[str] = []
    for row in _load_catalog(catalog_path)["roles"]:
        if not isinstance(row, dict):
            continue
        role_id = str(row.get("workflow_role") or "")
        skill_path = str(row.get("skill_path") or "")
        if role_id == "tp-spec-coding":
            continue
        if skill_path.startswith("agents/") and skill_path.endswith("/SKILL.md"):
            result.append(role_id)
    return result


def load_software_role_ids(catalog_path: Path) -> list[str]:
    return [
        str(row["workflow_role"])
        for row in _load_catalog(catalog_path)["roles"]
        if isinstance(row, dict)
        and row.get("type") == "workflow-role"
        and row.get("domain") == "software"
        and row.get("workflow_role")
    ]


def _catalog_rows(catalog_path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in _load_catalog(catalog_path)["roles"]:
        if isinstance(row, dict) and row.get("workflow_role"):
            rows[str(row["workflow_role"])] = row
    return rows


def _strip_fenced_code(text: str) -> str:
    return _FENCE_RE.sub("", text)


def iter_markdown_links(path: Path) -> list[tuple[str, str]]:
    text = _strip_fenced_code(path.read_text(encoding="utf-8"))
    result: list[tuple[str, str]] = []
    for match in _LINK_RE.finditer(text):
        target = match.group(2).strip()
        # Markdown optional title: [x](target "title"). Repository paths do not contain spaces.
        if " " in target and not target.startswith("<"):
            target = target.split(" ", 1)[0]
        target = target.strip("<>")
        result.append((match.group(1).strip(), target))
    for match in _ANGLE_RE.finditer(text):
        target = match.group(1).strip()
        # Ignore prose placeholders such as <project-root>; only treat path-like/autolink targets as links.
        if target.startswith(("http://", "https://", "mailto:", "app://")) or "/" in target or "." in target:
            result.append((target, target))
    return result


def _is_external(target: str) -> bool:
    lower = target.lower()
    return lower.startswith(("http://", "https://", "mailto:", "app://"))


def resolve_document_link(source: Path, target: str, *, base: Path | None = None) -> Path | None:
    target0 = unquote(target.strip())
    if not target0 or target0.startswith("#") or _is_external(target0):
        return None
    path_part = target0.split("#", 1)[0].split("?", 1)[0]
    if not path_part:
        return source.resolve()
    candidate = (source.parent / path_part).resolve()
    if base is not None:
        base0 = base.resolve()
        try:
            candidate.relative_to(base0)
        except ValueError:
            return candidate
    return candidate


def _relative_link(from_file: Path, target: str, base: Path) -> str:
    import os
    rel = Path(os.path.relpath(base / target, from_file.parent)).as_posix()
    if not rel.startswith("."):
        rel = "./" + rel
    return rel


def _render_agent_topology(base: Path, agent_id: str) -> str:
    catalog_path = base / "governance" / "role-catalog.yaml"
    rows = _catalog_rows(catalog_path)
    row = rows[agent_id]
    guide = base / "docs" / "agents" / f"{agent_id}.md"
    display = str(row.get("display_name") or agent_id)
    skill_path = str(row["skill_path"])
    lines = [
        AGENT_BEGIN,
        "<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->",
        "",
        f"- **Agent**：{display} · `{agent_id}`",
        f"- **执行契约**：[`{skill_path}`]({_relative_link(guide, skill_path, base)})",
    ]
    capabilities = [str(x) for x in row.get("capabilities", []) if str(x)]
    if capabilities:
        lines.append("- **能力 ID**：" + "、".join(f"`{x}`" for x in capabilities))

    if agent_id == "tp-software-lifecycle":
        lines.extend(["", "### Formal Role", "", "| Name | ID | 执行契约 |", "| --- | --- | --- |"])
        for role_id in load_software_role_ids(catalog_path):
            role = rows[role_id]
            path = str(role["skill_path"])
            lines.append(
                f"| {role.get('display_name') or role_id} | `{role_id}` | "
                f"[`{path}`]({_relative_link(guide, path, base)}) |"
            )
    domain_skills = row.get("domain_skills") or []
    if domain_skills:
        lines.extend(["", "### Domain / Capability Skill", ""])
        for item in domain_skills:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            sid = str(item.get("id") or Path(str(item["path"])).parent.name)
            path = str(item["path"])
            mode = str(item.get("mode") or "")
            lines.append(f"- `{sid}` ({mode or 'declared'}) → [`{path}`]({_relative_link(guide, path, base)})")
    lines.extend(["", AGENT_END])
    return "\n".join(lines)


def _render_docs_agent_map(base: Path) -> str:
    catalog = base / "governance" / "role-catalog.yaml"
    rows = _catalog_rows(catalog)
    docs = base / "docs" / "README.md"
    lines = [
        DOCS_AGENT_BEGIN,
        "<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->",
        "",
        "| Domain Agent | ID | 导航 | 执行契约 |",
        "| --- | --- | --- | --- |",
    ]
    for agent_id in load_public_agent_ids(catalog):
        row = rows[agent_id]
        guide_target = f"docs/agents/{agent_id}.md"
        skill_target = str(row["skill_path"])
        lines.append(
            f"| {row.get('display_name') or agent_id} | `{agent_id}` | "
            f"[打开]({_relative_link(docs, guide_target, base)}) | "
            f"[`{skill_target}`]({_relative_link(docs, skill_target, base)}) |"
        )
    lines.extend(["", DOCS_AGENT_END])
    return "\n".join(lines)


def _replace_generated_block(text: str, begin: str, end: str, rendered: str) -> str:
    start = text.find(begin)
    stop = text.find(end)
    if start < 0 or stop < start:
        raise ValueError(f"missing generated block markers: {begin} ... {end}")
    stop += len(end)
    return text[:start] + rendered + text[stop:]


def sync_generated_navigation(base: Path) -> list[str]:
    changed: list[str] = []
    docs_readme = base / "docs" / "README.md"
    if docs_readme.exists():
        text = docs_readme.read_text(encoding="utf-8")
        new = _replace_generated_block(text, DOCS_AGENT_BEGIN, DOCS_AGENT_END, _render_docs_agent_map(base))
        if new != text:
            docs_readme.write_text(new, encoding="utf-8")
            changed.append("docs/README.md")
    for agent_id in load_public_agent_ids(base / "governance" / "role-catalog.yaml"):
        guide = base / "docs" / "agents" / f"{agent_id}.md"
        if not guide.exists():
            continue
        text = guide.read_text(encoding="utf-8")
        new = _replace_generated_block(text, AGENT_BEGIN, AGENT_END, _render_agent_topology(base, agent_id))
        if new != text:
            guide.write_text(new, encoding="utf-8")
            changed.append(guide.relative_to(base).as_posix())
    return changed


def validate_agent_guides(base: Path) -> list[str]:
    errors: list[str] = []
    catalog = base / "governance" / "role-catalog.yaml"
    rows = _catalog_rows(catalog)
    for agent_id in load_public_agent_ids(catalog):
        guide = base / "docs" / "agents" / f"{agent_id}.md"
        if not guide.is_file():
            errors.append(f"missing agent guide: {guide.relative_to(base).as_posix()}")
            continue
        text = guide.read_text(encoding="utf-8")
        expected = _render_agent_topology(base, agent_id)
        start = text.find(AGENT_BEGIN)
        end = text.find(AGENT_END)
        if start < 0 or end < start:
            errors.append(f"missing generated topology markers: {guide.relative_to(base).as_posix()}")
        else:
            actual = text[start : end + len(AGENT_END)]
            if actual != expected:
                errors.append(f"stale generated topology: {guide.relative_to(base).as_posix()}")
        skill_path = str(rows[agent_id]["skill_path"])
        if not (base / skill_path).is_file():
            errors.append(f"missing catalog skill path for {agent_id}: {skill_path}")
    return errors


def _public_markdown_files(base: Path) -> list[Path]:
    result = [base / rel for rel in CORE_DOCUMENTS]
    result.extend((base / "docs" / "agents").glob("*.md") if (base / "docs" / "agents").exists() else [])
    for rel in ("wiki/README.md", "knowledge/README.md", "automation/README.md", "automation/autonomy/README.md"):
        path = base / rel
        if path.is_file():
            result.append(path)
    return sorted({p.resolve() for p in result if p.is_file()})


def retired_process_files(base: Path) -> list[str]:
    """Return retired process *files* that would be part of the repository surface.

    Git does not track directories. Applying a patch to an existing checkout can
    therefore leave an empty directory behind after its last tracked file is
    deleted. Empty directories are not release artifacts and must not make the
    release gate non-reproducible.
    """
    base = base.resolve()
    found: list[str] = []
    for prefix in DELETED_PROCESS_PREFIXES:
        root = base / prefix.rstrip("/")
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() or path.is_symlink():
                found.append(path.relative_to(base).as_posix())
    return sorted(found)


# 版本专用过程文档：文件名内嵌基座版本号（如 V531_xxx.md、MIGRATION_V529.md）。
# 拼接式声明，避免扫描器自身保存完整版本字面量。
_VERSION_IN_DOC_NAME_RE = re.compile(
    r"(?:^|[_-])v?5\.\d+\.\d+|(?:^|[_-])v?5\d{2}(?=[_-]|\.md$)",
    re.IGNORECASE,
)


def version_specific_doc_files(base: Path) -> list[str]:
    """Return version-specific process documents that must not re-enter the release surface.

    Retired designs, migration investigations and one-off implementation notes are
    kept in Git history and ``CHANGELOG.md`` only (see "历史与过程文档政策" in
    ``docs/README.md``).  Two shapes are rejected:

    * any file under ``docs/decisions/`` — ADR / one-off decision archives;
    * any ``docs/`` file whose name embeds a base contract version.

    Git does not track directories and an emptied directory is not a release
    artifact, so only files are reported — the same rule ``retired_process_files``
    applies to retired prefixes.
    """
    docs = base / "docs"
    if not docs.is_dir():
        return []
    found: list[str] = []
    for path in sorted(docs.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        rel = path.relative_to(base).as_posix()
        if rel.startswith("docs/decisions/") or _VERSION_IN_DOC_NAME_RE.search(path.name):
            found.append(rel)
    return sorted(found)


def validate_document_navigation(base: Path) -> list[str]:
    base = base.resolve()
    errors: list[str] = []
    for rel in CORE_DOCUMENTS:
        if not (base / rel).is_file():
            errors.append(f"missing document entrypoint: {rel}")
    for rel in retired_process_files(base):
        errors.append(f"retired process document file still exists: {rel}")
    for rel in version_specific_doc_files(base):
        errors.append(
            "version-specific process document must not re-enter the release surface: " + rel
        )

    errors.extend(validate_agent_guides(base))
    docs_readme = base / "docs" / "README.md"
    if docs_readme.is_file():
        text = docs_readme.read_text(encoding="utf-8")
        expected = _render_docs_agent_map(base)
        start = text.find(DOCS_AGENT_BEGIN)
        end = text.find(DOCS_AGENT_END)
        if start < 0 or end < start:
            errors.append("missing generated Agent map markers: docs/README.md")
        elif text[start : end + len(DOCS_AGENT_END)] != expected:
            errors.append("stale generated Agent map: docs/README.md")

    for source in _public_markdown_files(base):
        rel_source = source.relative_to(base).as_posix()
        text = source.read_text(encoding="utf-8")
        for prefix in DELETED_PROCESS_PREFIXES:
            if prefix in text:
                errors.append(f"retired process document reference in {rel_source}: {prefix}")
        for label, target in iter_markdown_links(source):
            if _is_external(target) or target.startswith("#"):
                continue
            clean = unquote(target).split("#", 1)[0].lstrip("./")
            if any(clean.startswith(prefix) for prefix in DELETED_PROCESS_PREFIXES):
                errors.append(f"retired document link in {rel_source}: {target}")
                continue
            resolved = resolve_document_link(source, target, base=base)
            if resolved is None:
                continue
            try:
                resolved.relative_to(base)
            except ValueError:
                errors.append(f"document link escapes repository in {rel_source}: {target}")
                continue
            if not resolved.exists():
                errors.append(f"broken document link in {rel_source}: {label} -> {target}")
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate TP-Spec public document navigation.")
    parser.add_argument("--base", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--write", action="store_true", help="Refresh generated Agent navigation blocks before validation.")
    args = parser.parse_args(argv)
    base = Path(args.base).resolve()
    if args.write:
        changed = sync_generated_navigation(base)
        if changed:
            print("Document navigation generated: " + ", ".join(changed))
    errors = validate_document_navigation(base)
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("Document navigation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
