# -*- coding: utf-8 -*-
"""Wiki manifest loading, compatibility refresh, and citation extraction."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Tuple
import hashlib
import re

import yaml

from .anchors import apply_cosmetic_citation_relocations
from .source import fingerprint_file, resolve_repo_relative
from .snapshot import snapshot_paths

MANIFEST_SCHEMA = "tp-spec.wiki-manifest/v1"
DOCUMENT_TYPES = {"content-doc", "concept-card", "module-index"}
DEPENDENCY_ROLES = {"primary", "context", "reference"}
_CITE_RE = re.compile(
    r'<cite\s+[^>]*path=["\'](?P<path>[^"\']+)["\'][^>]*?(?:line=["\'](?P<line>[^"\']+)["\'])?[^>]*/?>',
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def manifest_path(wiki_repo_root: Path) -> Path:
    return wiki_repo_root / "meta" / "wiki-manifest.yaml"


def load_manifest(wiki_repo_root: Path) -> Dict[str, Any]:
    path = manifest_path(wiki_repo_root)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"wiki manifest must be a mapping: {path}")
    return data


def write_manifest(wiki_repo_root: Path, manifest: Dict[str, Any]) -> Path:
    path = manifest_path(wiki_repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def extract_citations(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Use a permissive attribute parser because old docs vary in attribute order.
    for raw in re.findall(r"<cite\b[^>]*?/?>", text, flags=re.I):
        p = re.search(r'\bpath=["\']([^"\']+)["\']', raw, flags=re.I)
        if not p:
            continue
        line_match = re.search(r'\bline=["\']([^"\']+)["\']', raw, flags=re.I)
        entry: Dict[str, Any] = {"file": p.group(1).replace("\\", "/")}
        if line_match:
            line = line_match.group(1).strip()
            m = re.match(r"^(\d+)(?:\s*-\s*(\d+))?$", line)
            if m:
                entry["line_start"] = int(m.group(1))
                entry["line_end"] = int(m.group(2) or m.group(1))
            else:
                entry["line_raw"] = line
        out.append(entry)
    return out




_GENERIC_CITATION_SECTION_KEYS = {
    "溯源", "引用", "参考", "参考资料", "证据", "证据索引",
    "references", "reference", "sources", "source", "provenance", "evidence",
}


def _citation_section_key(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\d+(?:\.\d+)*[.、)]?\s*", "", text).strip()
    text = re.sub(r"\s*[（(][A-Za-z][A-Za-z0-9 /_&-]*[）)]\s*$", "", text).strip()
    return text.casefold()


def is_generic_citation_section(value: str) -> bool:
    return _citation_section_key(value) in _GENERIC_CITATION_SECTION_KEYS


def extract_citation_sections(text: str) -> Dict[str, List[str]]:
    """Map cited source files to the Wiki headings that actually contain the cites.

    This is machine-observable targeting metadata, not an AI-authored dependency role.
    It lets later source changes target the relevant Wiki section even when the semantic
    model never hand-maintains primary/context dependency bookkeeping.
    """
    headings = list(re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", text))
    out: Dict[str, set[str]] = {}
    for match in re.finditer(r"<cite\b[^>]*?/?>", text, flags=re.I):
        raw = match.group(0)
        p = re.search(r'\bpath=["\']([^"\']+)["\']', raw, flags=re.I)
        if not p:
            continue
        rel = p.group(1).replace("\\", "/")
        section = ""
        for heading in headings:
            if heading.start() >= match.start():
                break
            section = heading.group(1).strip()
        if section and not is_generic_citation_section(section):
            out.setdefault(rel, set()).add(section)
    return {rel: sorted(sections) for rel, sections in sorted(out.items())}


def resolve_wiki_relative(wiki_repo_root: Path, rel: str) -> Path:
    text = str(rel or "").replace("\\", "/").strip()
    pure = PurePosixPath(text)
    if not text or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe wiki-relative path: {rel!r}")
    root = wiki_repo_root.resolve(strict=False)
    candidate = (root / pure).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes wiki root: {rel!r}") from exc
    return candidate


def resolve_wiki_link(wiki_repo_root: Path, source_doc_rel: str, target: str) -> Path:
    """Resolve a Markdown navigation target relative to its source document.

    Unlike manifest document/source paths, ``..`` is legitimate Markdown navigation
    when it stays inside the same Wiki repo (for example ``../index.md``).  The
    resolved physical path, not the lexical token, is the security boundary.
    """
    text = str(target or "").replace("\\", "/").strip()
    pure = PurePosixPath(text)
    if not text or pure.is_absolute():
        raise ValueError(f"unsafe wiki link target: {target!r}")
    root = wiki_repo_root.resolve(strict=False)
    source = PurePosixPath(str(source_doc_rel or "").replace("\\", "/"))
    candidate = (root / source.parent / pure).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"wiki link escapes wiki root: {target!r}") from exc
    return candidate

def _doc_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()



def _infer_document(wiki_repo_root: Path, path: Path) -> Dict[str, Any]:
    rel = path.relative_to(wiki_repo_root).as_posix()
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    title = title_match.group(1).strip() if title_match else path.stem.replace("-", " ")
    headings = [m.group(1).strip() for m in re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", text)]
    if path.name.lower() == "index.md":
        dtype = "module-index"
    elif all(any(section in h for h in headings) for section in ("概述", "模块结构", "核心逻辑", "数据流", "接口", "配置", "依赖")):
        dtype = "content-doc"
    else:
        dtype = "concept-card"
    return {"path": rel, "type": dtype, "title": title, "status": "completed", "sections": headings}


def _discover_documents(wiki_repo_root: Path) -> List[Path]:
    out: List[Path] = []
    for path in wiki_repo_root.rglob("*.md"):
        if not path.is_file():
            continue
        rel = path.relative_to(wiki_repo_root).as_posix()
        if rel.startswith("meta/"):
            continue
        out.append(path)
    return sorted(out)

def refresh_manifest(
    *,
    workspace_id: str,
    repo_id: str,
    repo_root: Path,
    wiki_repo_root: Path,
    source_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Refresh machine-owned provenance fields without inventing AI document structure.

    Existing document declarations are preserved. Wiki Markdown created by the AI is
    discovered and added with a conservative inferred type/title so machine provenance can
    be refreshed without forcing the model to hand-edit manifest bookkeeping. Semantic
    scope remains represented by the document itself and its dependency/citation evidence.

    Before hashing Markdown, precise ``<cite line>`` anchors for COSMETIC source changes
    are deterministically relocated from the previous committed anchor baseline. This keeps
    blank/comment-only source drift from either spending model Tokens or leaving stale line
    numbers behind.
    """
    relocation = apply_cosmetic_citation_relocations(
        wiki_repo_root=wiki_repo_root, repo_root=repo_root, source_cfg=source_cfg
    )
    manifest = load_manifest(wiki_repo_root)
    if not manifest:
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "workspace_id": workspace_id,
            "repo_id": repo_id,
            "repo_root": str(repo_root),
            "generated_at": utc_now(),
            "provenance": {
                "manifest_refresh": {"type": "deterministic", "tool": "tp-spec wiki manifest-refresh", "refreshed_at": utc_now()},
                "semantic_content": {"type": "mixed-or-not-recorded", "model": "not-recorded"},
            },
            "documents": [],
        }
    manifest["schema"] = MANIFEST_SCHEMA
    manifest["workspace_id"] = workspace_id
    manifest["repo_id"] = repo_id
    manifest["repo_root"] = str(repo_root)
    manifest["generated_at"] = utc_now()
    # A single manifest-level AI generator is not truthful after incremental maintenance:
    # documents may come from different models/runs.  Keep deterministic refresh provenance
    # separate and explicitly mark semantic authorship as mixed/not-recorded.
    manifest.pop("generator", None)
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    provenance["manifest_refresh"] = {
        "type": "deterministic",
        "tool": "tp-spec wiki manifest-refresh",
        "refreshed_at": manifest["generated_at"],
    }
    provenance.setdefault("semantic_content", {"type": "mixed-or-not-recorded", "model": "not-recorded"})
    manifest["provenance"] = provenance
    manifest.pop("last_commit_id", None)
    # Git branch metadata is neither required nor trustworthy for snapshot-based Wiki maintenance;
    # old central Wiki copies often preserve a stale branch name after re-download/migration.
    manifest.pop("branch", None)

    changeset_path = snapshot_paths(wiki_repo_root)["changeset"]
    if changeset_path.is_file():
        import json
        changeset = json.loads(changeset_path.read_text(encoding="utf-8"))
        manifest["source_change_set_id"] = changeset.get("change_set_id")
        manifest["candidate_snapshot_id"] = changeset.get("candidate_snapshot_id")

    docs = manifest.get("documents")
    if not isinstance(docs, list):
        raise ValueError("manifest.documents must be a list")
    by_path = {str(d.get("path") or "").replace("\\", "/"): d for d in docs if isinstance(d, dict) and d.get("path")}
    for discovered in _discover_documents(wiki_repo_root):
        rel = discovered.relative_to(wiki_repo_root).as_posix()
        if rel not in by_path:
            inferred = _infer_document(wiki_repo_root, discovered)
            docs.append(inferred)
            by_path[rel] = inferred
    # Remove manifest document declarations whose Wiki document no longer exists.
    docs[:] = [d for d in docs if isinstance(d, dict) and resolve_wiki_relative(wiki_repo_root, str(d.get("path") or "")).is_file()]
    total_cites = 0
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        # Deterministic schema migration: historical Wiki V3.x called durable
        # concept/explanation pages "knowledge-card". In TP-Spec-Coding this name
        # collides with the separate canonical Knowledge system, so the Wiki type
        # is now "concept-card" without forcing a prose rewrite or path rename.
        if doc.get("type") == "knowledge-card":
            doc["type"] = "concept-card"
        rel = str(doc.get("path") or "").replace("\\", "/")
        doc_path = resolve_wiki_relative(wiki_repo_root, rel)
        if doc_path.is_file():
            doc["content_hash"] = _doc_hash(doc_path)
            current_text = doc_path.read_text(encoding="utf-8")
            # Sections are machine-observable document structure. Refresh them on every
            # pass so stale historical section names cannot mislead rebuild targeting or
            # inflate semantic coverage after the prose/headings changed.
            doc["sections"] = [m.group(1).strip() for m in re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", current_text)]
            cites = extract_citations(current_text)
            citation_sections = extract_citation_sections(current_text)
            doc["citations"] = cites
            total_cites += len(cites)
        else:
            cites = []
            citation_sections = {}
        dependencies = doc.get("dependencies") or []
        if not isinstance(dependencies, list):
            dependencies = []
        cited_files = {str(c.get("file") or "").replace("\\", "/") for c in cites if c.get("file")}
        # Stale dependencies whose source disappeared and are no longer cited are safe to prune
        # during deterministic refresh. Existing live context dependencies are preserved.
        kept_dependencies = []
        for d in dependencies:
            if not isinstance(d, dict) or not d.get("file"):
                continue
            dep_file = str(d.get("file")).replace("\\", "/")
            try:
                source_exists = resolve_repo_relative(repo_root, dep_file).is_file()
            except ValueError:
                source_exists = False
            # Preserve cited/unsafe missing edges so L1 can report them instead of
            # silently erasing evidence authored by the AI. Uncited stale paths can
            # be pruned once the prose no longer refers to them.
            if source_exists or dep_file in cited_files or ".." in PurePosixPath(dep_file).parts or PurePosixPath(dep_file).is_absolute():
                kept_dependencies.append(d)
        dependencies = kept_dependencies
        known = {str(d.get("file") or "").replace("\\", "/") for d in dependencies}
        for cited in sorted(cited_files - known):
            dependencies.append({"file": cited, "role": "reference", "sections": citation_sections.get(cited, [])})
        # For citation-derived reference edges, section targeting is deterministic and
        # safe to refresh from the current Markdown.  For AI-authored primary/context
        # roles preserve semantic bindings, but union any directly observed cite sections.
        for dep in dependencies:
            if not isinstance(dep, dict) or not dep.get("file"):
                continue
            dep_file = str(dep.get("file") or "").replace("\\", "/")
            if dep_file not in cited_files:
                continue
            observed = set(citation_sections.get(dep_file, []))
            role = str(dep.get("role") or "reference").lower()
            if role == "reference":
                dep["sections"] = sorted(observed)
            elif observed:
                existing = {str(x).strip() for x in (dep.get("sections") or []) if str(x).strip()}
                dep["sections"] = sorted(existing | observed)
        doc["dependencies"] = dependencies
        for dep in dependencies:
            if not isinstance(dep, dict):
                continue
            file = str(dep.get("file") or "").replace("\\", "/")
            if not file:
                continue
            try:
                src = resolve_repo_relative(repo_root, file)
            except ValueError:
                src = None
            if src is not None and src.is_file():
                fp = fingerprint_file(repo_root, file, source_cfg)
                dep["content_hash"] = fp.content_hash
                dep["normalized_hash"] = fp.normalized_hash
                dep["encoding"] = fp.encoding
            # Missing sources intentionally remain without refreshed hashes so L1 fails.
    manifest["stats"] = {
        **(manifest.get("stats") or {}),
        "total_documents": len(docs),
        "total_citations": total_cites,
        "cite_relocations_last_refresh": int(relocation.get("relocated") or 0),
    }
    write_manifest(wiki_repo_root, manifest)
    return manifest
