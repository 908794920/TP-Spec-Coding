# -*- coding: utf-8 -*-
"""Read-only migration planning for legacy Knowledge Vault assets.

The planner never deletes or moves Vault content. It classifies legacy
construction/runtime surfaces from Base configuration so machine/editor-specific
folder names are not embedded in executable code.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Set


def _covered(rel: str, classified: Set[str]) -> bool:
    rel = rel.replace("\\", "/").strip("/")
    for base in classified:
        b = base.strip("/")
        if rel == b or rel.startswith(b + "/"):
            return True
    return False


def _relative_if_under(root: Path, raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    p = Path(text)
    if not p.is_absolute():
        return p.as_posix().strip("/")
    try:
        return p.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return ""


def migration_plan(cfg) -> Dict[str, Any]:
    root = cfg.paths.knowledge_physical_root
    maintenance = dict(cfg.knowledge.get("maintenance") or {})
    local_roots = [str(x).strip("/\\") for x in maintenance.get("local_out_of_scope_roots") or [] if str(x).strip("/\\")]
    projection = dict(cfg.knowledge_projection or {})
    rebuildable_dbs = []
    for raw in [projection.get("database"), *(projection.get("legacy_databases") or [])]:
        rel = _relative_if_under(root, raw)
        if rel and rel not in rebuildable_dbs:
            rebuildable_dbs.append(rel)

    candidates = {
        "KEEP_DATA": [
            "00-system/project-registry.yaml",
            "00-system/dictionaries",
            "00-system/eval/golden.jsonl",
            "10-projects",
            "20-shared",
            "90-archive",
            ".ai-kb/meta",
            ".ai-kb/ingest",
        ],
        "KEEP_LOCAL_OUT_OF_SCOPE": local_roots,
        "BASE_OWNS_AFTER_CUTOVER": [
            "tools/kb-index",
            "tools/kb-rebuild",
            "tools/kb-ingest",
            "00-system/schemas",
            "00-system/templates",
            "00-system/fixtures",
        ],
        "GENERATED_OR_REBUILDABLE": [
            "00-system/generated-indexes",
            "00-system/bases",
            "00-system/eval/results",
            *rebuildable_dbs,
            ".ai-kb/eval",
            ".pytest_cache",
        ],
        "ARCHIVE_AFTER_ACCEPTANCE": [
            "00-system/quality-reports",
            "00-system/migration",
            "00-system/runbooks",
            "00-system/model-services",
            "00-system/eval/golden-change-record-P3.md",
            "AI知识库维护体系V1.md",
            "外部文档知识沉淀流水线V1.md",
            "定时任务.txt",
        ],
        "REWRITE_FROM_BASE_TEMPLATE": ["AGENTS.md"],
    }
    groups: Dict[str, List[Dict[str, Any]]] = {}
    classified: Set[str] = set()
    for action, rels in candidates.items():
        rows = []
        for rel in rels:
            p = root / rel
            if p.exists():
                rows.append({"path": rel, "type": "directory" if p.is_dir() else "file", "action": action})
                classified.add(rel)
        groups[action] = rows

    review: List[Dict[str, Any]] = []
    roots_to_scan = [root, root / "00-system", root / "00-system" / "eval", root / ".ai-kb", root / "tools"]
    for parent in roots_to_scan:
        if not parent.is_dir():
            continue
        for p in sorted(parent.iterdir(), key=lambda x: x.name.casefold()):
            rel = p.relative_to(root).as_posix()
            if rel in {"00-system", "00-system/eval", ".ai-kb", "tools"}:
                continue
            if _covered(rel, classified):
                continue
            if parent == root and rel in {"10-projects", "20-shared", "90-archive"}:
                continue
            review.append({"path": rel, "type": "directory" if p.is_dir() else "file", "action": "UNCLASSIFIED_REVIEW"})
    seen = set(); review_unique = []
    for row in review:
        if row["path"] in seen:
            continue
        seen.add(row["path"]); review_unique.append(row)
    groups["UNCLASSIFIED_REVIEW"] = review_unique

    return {
        "schema": "ai-work.knowledge-migration-plan/v1",
        "status": "PASS" if not review_unique else "NEEDS_REVIEW",
        "root": str(root),
        "read_only": True,
        "groups": groups,
        "unclassified_count": len(review_unique),
        "principles": [
            "canonical/source/evidence data stays in the Knowledge Vault",
            "runtime/rules/schema/templates move to TP-Spec-Coding to avoid dual authority",
            "retrieval projection is rebuildable and is never Knowledge truth",
            "retired embedding/model-service assets are historical evidence, not active Base runtime",
            "archive legacy construction evidence only after new CLI acceptance passes",
            "rewrite Vault AGENTS.md from the Base Knowledge template; do not copy the whole Knowledge Skill into the data Vault",
            "configured local editor/personal-note roots classified KEEP_LOCAL_OUT_OF_SCOPE remain in place and are excluded from Knowledge truth/index/automation",
            "unclassified control-root assets require human review before cleanup",
        ],
    }
