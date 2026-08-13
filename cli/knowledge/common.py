# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
import hashlib
import json
import os
import re

import yaml

from cli.content_systems import ResolvedConfig, load_content_systems, same_path
from cli.environment import load_project_binding

CANONICAL_SUBDIRS = (
    "00-project", "10-domain", "20-architecture", "30-features",
    "40-interfaces", "50-data", "60-jobs", "70-operations",
)
KIND_CODES = {
    "project": "PROJ", "domain": "DOM", "system": "SYS", "module": "MOD",
    "feature": "FEAT", "interface": "API", "data": "DATA", "job": "JOB",
    "operation": "OPS", "decision": "DEC", "source": "SRC",
}
KINDS = set(KIND_CODES)
ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*-(PROJ|DOM|SYS|MOD|FEAT|API|DATA|JOB|OPS|DEC|SRC)-\d{3,}$")
WIKILINK_RE = re.compile(r"!?\[\[([^\]]+)\]\]")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*\r?\n", re.DOTALL)
TASK_REF_RE = re.compile(r"^TASK-[A-Za-z0-9._-]+$")
SRC_REF_RE = re.compile(r"^(?:[A-Z][A-Z0-9]*-)?SRC-[A-Za-z0-9._-]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_yaml_scalars(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: normalize_yaml_scalars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_yaml_scalars(v) for v in obj]
    return obj


def parse_frontmatter(text: str) -> Tuple[Optional[Dict[str, Any]], str, Optional[str], int]:
    if text.startswith("\ufeff"):
        text = text[1:]
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, text, "no frontmatter", 1
    try:
        fm = yaml.safe_load(m.group(1))
        if not isinstance(fm, dict):
            return None, text[m.end():], "frontmatter not a mapping", text[:m.end()].count("\n") + 1
        fm = normalize_yaml_scalars(fm)
        return fm, text[m.end():], None, text[:m.end()].count("\n") + 1
    except Exception as exc:
        return None, text[m.end():], f"frontmatter parse error: {exc}", text[:m.end()].count("\n") + 1


def read_note(path: Path, *, root: Path, scope: str) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    fm, body, error, body_start_line = parse_frontmatter(text)
    rel = path.relative_to(root).as_posix()
    project = ""
    kind = ""
    note_id = ""
    title = ""
    source_refs: List[str] = []
    evidence_refs: List[Dict[str, Any]] = []
    if fm:
        project = str(fm.get("project") or "").strip()
        kind = str(fm.get("kind") or "").strip()
        note_id = str(fm.get("id") or "").strip()
        title = str(fm.get("title") or "").strip()
        raw_refs = fm.get("source_refs") or []
        if isinstance(raw_refs, list):
            source_refs = [str(v).strip() for v in raw_refs if str(v).strip()]
        raw_ev = fm.get("evidence_refs") or []
        if isinstance(raw_ev, list):
            evidence_refs = [v for v in raw_ev if isinstance(v, dict)]
    parts = rel.split("/")
    if not project and len(parts) >= 2 and parts[0] == "10-projects":
        project = parts[1]
    if scope == "source" and not kind:
        kind = "source"
    return {
        "path": path,
        "rel_path": rel,
        "scope": scope,
        "text": text,
        "body": body,
        "body_start_line": body_start_line,
        "frontmatter": fm,
        "parse_error": error,
        "project": project,
        "kind": kind,
        "id": note_id,
        "title": title,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "size": len(text.encode("utf-8")),
        "mtime_ns": path.stat().st_mtime_ns,
    }


def canonical_dirs(root: Path, cfg: ResolvedConfig) -> List[Path]:
    c = cfg.knowledge_canonical
    projects_dir = str(c.get("projects_dir") or "10-projects")
    shared_dir = str(c.get("shared_dir") or "20-shared")
    out: List[Path] = []
    pbase = root / projects_dir
    if pbase.is_dir():
        for project in sorted(p for p in pbase.iterdir() if p.is_dir()):
            for sub in CANONICAL_SUBDIRS:
                d = project / sub
                if d.is_dir():
                    out.append(d)
    shared = root / shared_dir
    if shared.is_dir():
        out.append(shared)
    return out


def source_dirs(root: Path, cfg: ResolvedConfig) -> List[Path]:
    c = cfg.knowledge_canonical
    projects_dir = str(c.get("projects_dir") or "10-projects")
    source_dir = str(c.get("source_dir") or "90-sources")
    pbase = root / projects_dir
    out: List[Path] = []
    if pbase.is_dir():
        for project in sorted(p for p in pbase.iterdir() if p.is_dir()):
            d = project / source_dir
            if d.is_dir():
                out.append(d)
    return out


def collect_notes(root: Path, cfg: ResolvedConfig) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    canonical: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    seen: set[Path] = set()
    for d in canonical_dirs(root, cfg):
        for p in sorted(d.rglob("*.md")):
            rp = p.resolve(strict=False)
            if rp in seen:
                continue
            seen.add(rp)
            canonical.append(read_note(p, root=root, scope="canonical"))
    for d in source_dirs(root, cfg):
        for p in sorted(d.rglob("*.md")):
            sources.append(read_note(p, root=root, scope="source"))
    canonical.sort(key=lambda n: n["rel_path"])
    sources.sort(key=lambda n: n["rel_path"])
    return canonical, sources


def load_project_registry(cfg: ResolvedConfig) -> Tuple[Dict[str, Any], set[str]]:
    path = cfg.paths.knowledge_registry
    if not path.is_file():
        return {}, set()
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    ids: set[str] = set()
    for p in data.get("projects", []) or []:
        if isinstance(p, dict) and p.get("id"):
            ids.add(str(p["id"]))
    for p in data.get("shared_scopes", []) or []:
        if isinstance(p, dict) and p.get("id"):
            ids.add(str(p["id"]))
    return data, ids



def resolve_knowledge_project(cfg: ResolvedConfig, *, require: bool = False) -> Dict[str, Any]:
    """Resolve the current workspace to a project-scoped Knowledge root.

    Resolution order is explicit project binding first, then exact
    ``project-registry.yaml`` workspace_roots matching.  No folder-name guessing is
    allowed when a registry exists because global fallback would pollute retrieval.
    """
    data, _ = load_project_registry(cfg)
    projects = [p for p in (data.get("projects") or []) if isinstance(p, dict) and p.get("id")]
    binding = load_project_binding(cfg.paths.workspace_root)
    requested = binding.knowledge_id or binding.project_id
    match = None
    if requested:
        rows = [p for p in projects if str(p.get("id")) == requested]
        if len(rows) > 1:
            raise ValueError(f"duplicate Knowledge project id in registry: {requested}")
        match = rows[0] if rows else None
        if match is None and projects:
            raise ValueError(f"project-binding knowledge id not registered: {requested}")
    if match is None:
        matches = []
        for project in projects:
            for raw in project.get("workspace_roots") or []:
                try:
                    if same_path(Path(str(raw)), cfg.paths.workspace_root):
                        matches.append(project); break
                except Exception:
                    continue
        if len(matches) > 1:
            raise ValueError(f"multiple Knowledge projects match workspace: {cfg.paths.workspace_root}")
        match = matches[0] if matches else None
    projects_dir = str(cfg.knowledge_canonical.get("projects_dir") or "10-projects")
    source = "project-binding" if requested and match is not None else ("knowledge-registry-workspace" if match is not None else "")

    # Compatibility-only migration fallback: an existing project-side Knowledge
    # Junction/symlink may prove the old project mapping.  Accept it only when
    # its resolved target exactly equals one registered 10-projects/<id> root.
    # Real directories are never treated as mapping authority.  Once
    # tp-base-maintenance writes project-binding.yaml this fallback is no longer
    # needed and the link can be removed safely.
    if match is None:
        legacy = cfg.paths.workspace_root / ".tp-spec" / "knowledge"
        link_like = legacy.is_symlink()
        try:
            checker = getattr(legacy, "is_junction", None)
            link_like = link_like or bool(checker and checker())
        except OSError:
            pass
        if link_like:
            try:
                resolved = legacy.resolve(strict=False)
                compat = []
                for project in projects:
                    pid = str(project.get("id") or "")
                    target = (cfg.paths.knowledge_physical_root / projects_dir / pid).resolve(strict=False)
                    if same_path(resolved, target):
                        compat.append(project)
                if len(compat) > 1:
                    raise ValueError(f"legacy Knowledge link matches multiple registered projects: {legacy}")
                if compat:
                    match = compat[0]
                    source = "legacy-project-link"
            except OSError:
                pass

    if match is None:
        if require and projects:
            raise ValueError(f"workspace is not mapped to a Knowledge project: {cfg.paths.workspace_root}")
        return {"project_id":"", "project_root":None, "shared_ids":[], "binding":str(binding.path), "resolved":False, "source":"unmapped"}
    project_id = str(match["id"])
    shared_ids = [str(x.get("id")) for x in (data.get("shared_scopes") or []) if isinstance(x, dict) and x.get("id") and str(x.get("status") or "active") != "archived"]
    return {
        "project_id": project_id,
        "project_root": str((cfg.paths.knowledge_physical_root / projects_dir / project_id).resolve(strict=False)),
        "shared_ids": shared_ids,
        "binding": str(binding.path),
        "resolved": True,
        "source": source or "knowledge-registry-workspace",
    }

def base_schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "schema" / name


def meta_paths(cfg: ResolvedConfig) -> Dict[str, Path]:
    root = cfg.paths.knowledge_meta_root
    return {
        "root": root,
        "snapshot": root / "knowledge-snapshot.json",
        "changeset": root / "knowledge-change-set.json",
        "verification": root / "knowledge-verification.json",
        "audit_plan": root / "knowledge-audit-plan.json",
        "audit_receipt": root / "knowledge-audit-receipt.json",
        "source_registry": root / "source-registry.jsonl",
    }


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            out.append(obj)
    return out


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def stable_hash(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def knowledge_truth_snapshot(cfg: ResolvedConfig) -> Dict[str, Any]:
    root = cfg.paths.knowledge_physical_root
    canonical, sources = collect_notes(root, cfg)
    files: Dict[str, Dict[str, Any]] = {}
    for note in canonical + sources:
        files[note["rel_path"]] = {
            "scope": note["scope"],
            "sha256": note["sha256"],
            "id": note["id"],
            "project": note["project"],
        }
    # Registry/dictionaries are data-owned knowledge configuration and affect interpretation.
    registry = cfg.paths.knowledge_registry
    if registry.is_file() and registry.is_relative_to(root):
        rel = registry.relative_to(root).as_posix()
        files[rel] = {"scope": "registry", "sha256": hashlib.sha256(registry.read_bytes()).hexdigest(), "id": "", "project": ""}
    dictionaries = root / "00-system" / "dictionaries"
    if dictionaries.is_dir():
        for p in sorted(x for x in dictionaries.rglob("*") if x.is_file()):
            rel = p.relative_to(root).as_posix()
            files[rel] = {"scope": "dictionary", "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "id": "", "project": ""}
    source_registry = meta_paths(cfg)["source_registry"]
    if source_registry.is_file():
        files[".ai-kb/meta/source-registry.jsonl"] = {"scope": "source-registry", "sha256": hashlib.sha256(source_registry.read_bytes()).hexdigest(), "id": "", "project": ""}
    subject = {"schema": "tp-spec.knowledge-snapshot/v1", "files": files}
    subject["snapshot_id"] = stable_hash(subject)
    return subject


def classify_snapshot(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    old_files = (old or {}).get("files") or {}
    new_files = new.get("files") or {}
    added = sorted(set(new_files) - set(old_files))
    deleted = sorted(set(old_files) - set(new_files))
    modified = sorted(k for k in set(old_files) & set(new_files) if old_files[k].get("sha256") != new_files[k].get("sha256"))
    changed = added + deleted + modified
    scopes: Dict[str, int] = {}
    for p in changed:
        item = new_files.get(p) or old_files.get(p) or {}
        s = str(item.get("scope") or "unknown")
        scopes[s] = scopes.get(s, 0) + 1
    semantic = any((new_files.get(p) or old_files.get(p) or {}).get("scope") in {"canonical", "source", "registry", "dictionary", "source-registry"} for p in changed)
    return {
        "initial": old is None,
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "changed": sorted(changed),
        "counts_by_scope": scopes,
        "semantic_audit_required": bool(changed and semantic),
    }


def load_source_registry(cfg: ResolvedConfig) -> Dict[str, Dict[str, Any]]:
    rows = read_jsonl(meta_paths(cfg)["source_registry"])
    by_id = {str(r.get("source_id")): r for r in rows if r.get("source_id")}
    # Compatibility: historical final source catalog remains readable as evidence mapping.
    legacy = cfg.paths.knowledge_physical_root / "00-system" / "migration" / "source-catalog.jsonl"
    for r in read_jsonl(legacy):
        sid = str(r.get("source_id") or "")
        if sid and sid not in by_id:
            by_id[sid] = {
                "source_id": sid,
                "project": str(r.get("project") or r.get("project_id") or ""),
                "origin_path": str(r.get("old_path") or r.get("origin_path") or "legacy"),
                "content_path": str(r.get("new_path") or ""),
                "sha256": str(r.get("sha256") or r.get("source_sha256") or ""),
                "disposition": "source_only",
                "legacy": True,
            }
    return by_id


def find_source_ids(source_notes: List[Dict[str, Any]], registry: Dict[str, Dict[str, Any]]) -> set[str]:
    ids = set(registry)
    for n in source_notes:
        if n.get("id"):
            ids.add(str(n["id"]))
    return ids


def source_accountability(cfg: ResolvedConfig) -> Dict[str, Any]:
    rows = read_jsonl(meta_paths(cfg)["source_registry"])
    terminal = {"canonicalized", "merged", "source_only", "duplicate", "superseded", "quarantined", "excluded"}
    valid = terminal | {"pending"}
    counts: Dict[str, int] = {}
    invalid = []
    for r in rows:
        d = str(r.get("disposition") or "")
        counts[d] = counts.get(d, 0) + 1
        if d not in valid:
            invalid.append(str(r.get("source_id") or "<missing>"))
    total = len(rows)
    accounted = sum(v for k, v in counts.items() if k in terminal)
    return {
        "registered": total,
        "accounted": accounted,
        "pending": counts.get("pending", 0),
        "accountability": (accounted / total) if total else None,
        "dispositions": counts,
        "invalid_records": invalid,
    }
