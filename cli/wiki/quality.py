# -*- coding: utf-8 -*-
"""Deterministic Wiki quality gates L1-L3 and semantic-audit receipt support.

L1 protects structural truth/integrity, L2 protects traceability/coverage and L3
surfaces content-quality risks. Semantic correctness is intentionally left to the
model-driven L4 audit and is bound to the exact verified Wiki subject digest.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
import hashlib
import json
import re

from .anchors import plan_cosmetic_citation_relocations
from .coverage import compute_wiki_coverage
from .manifest import (
    DEPENDENCY_ROLES,
    DOCUMENT_TYPES,
    MANIFEST_SCHEMA,
    extract_citations,
    extract_citation_sections,
    load_manifest,
    resolve_wiki_relative,
    resolve_wiki_link,
)
from .snapshot import snapshot_paths, utc_now, wiki_subject_digest
from .source import decode_text, discover_source_files, fingerprint_file, resolve_repo_relative

REQUIRED_CONTENT_SECTIONS = ("概述", "模块结构", "核心逻辑", "数据流", "接口", "配置", "依赖")
STRONG_FILLER_SIGNALS = ("该文件是本仓的核心实现", "承载主要业务逻辑", "其类与方法实现细节")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _issue(level: str, severity: str, code: str, message: str, **detail: Any) -> Dict[str, Any]:
    return {"level": level, "severity": severity, "code": code, "message": message, "detail": detail}


def _line_count(path: Path) -> int:
    try:
        text, _, status = decode_text(path.read_bytes())
        return len((text or "").splitlines()) if status != "uncertain" else 0
    except OSError:
        return 0


def _repeated_paragraphs(text: str, threshold: int) -> List[str]:
    blocks = [re.sub(r"\s+", " ", b.strip()) for b in re.split(r"\n\s*\n", text) if len(b.strip()) >= 40]
    counts = Counter(blocks)
    return [block[:120] for block, n in counts.items() if n >= threshold]


def _canonical_cites(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    clean: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {k: row[k] for k in ("file", "line_start", "line_end", "line_raw") if k in row}
        if item.get("file"):
            item["file"] = str(item["file"]).replace("\\", "/")
        clean.append(item)
    return clean


def verify_repo(
    *,
    repo_root: Path,
    wiki_repo_root: Path,
    source_cfg: Dict[str, Any],
    quality_cfg: Dict[str, Any],
    coverage_cfg: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    paths = snapshot_paths(wiki_repo_root)
    changeset = json.loads(paths["changeset"].read_text(encoding="utf-8")) if paths["changeset"].is_file() else {}
    manifest = load_manifest(wiki_repo_root)
    issues: List[Dict[str, Any]] = []
    coverage_cfg = dict(coverage_cfg or {})

    # Deterministic guard for explicit current-version assertions. Historical
    # version references remain legal; only claims that say they are current are checked.
    canonical_version = ""
    version_path = repo_root / "VERSION"
    if version_path.is_file():
        try:
            value = version_path.read_text(encoding="utf-8-sig").strip()
            if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", value):
                canonical_version = value
        except (OSError, UnicodeError):
            canonical_version = ""

    # ------------------------------------------------------------------
    # L1 Integrity
    # ------------------------------------------------------------------
    if not manifest:
        issues.append(_issue("L1", "ERROR", "MANIFEST_MISSING", "meta/wiki-manifest.yaml is missing or empty"))
        docs: List[Any] = []
    else:
        if manifest.get("schema") != MANIFEST_SCHEMA:
            issues.append(_issue("L1", "ERROR", "MANIFEST_SCHEMA_INVALID", f"manifest schema must be {MANIFEST_SCHEMA}", actual=manifest.get("schema")))
        for field in ("workspace_id", "repo_id", "repo_root"):
            if not str(manifest.get(field) or "").strip():
                issues.append(_issue("L1", "ERROR", "MANIFEST_REQUIRED_FIELD_MISSING", f"manifest.{field} is required", field=field))
        docs = manifest.get("documents") if isinstance(manifest.get("documents"), list) else []
        if not isinstance(manifest.get("documents"), list):
            issues.append(_issue("L1", "ERROR", "MANIFEST_DOCUMENTS_INVALID", "manifest.documents must be a list"))

    if changeset:
        uncertain_changes = [str(c.get("file") or "") for c in changeset.get("changes", []) if c.get("kind") == "UNCERTAIN"]
        if uncertain_changes:
            issues.append(_issue("L1", "ERROR", "UNCERTAIN_SOURCE_CHANGE", "uncertain source changes remain unresolved", files=uncertain_changes))
        semantic_like = [c for c in changeset.get("changes", []) if c.get("kind") in {"SEMANTIC", "STRUCTURAL", "DELETED", "UNCERTAIN"}]
        if semantic_like and not paths["plan"].is_file():
            issues.append(_issue("L1", "ERROR", "REBUILD_PLAN_MISSING", "semantic/structural source changes require a current rebuild plan"))
        if str((changeset.get("guard") or {}).get("status") or "") == "MASS_CHANGE_REVIEW_REQUIRED":
            plan = json.loads(paths["plan"].read_text(encoding="utf-8")) if paths["plan"].is_file() else {}
            if plan.get("change_set_id") != changeset.get("change_set_id") or not plan.get("mass_change_approved"):
                issues.append(_issue("L1", "ERROR", "MASS_CHANGE_NOT_APPROVED", "mass semantic/structural change requires an explicitly approved rebuild plan"))
        if any(c.get("kind") == "COSMETIC" for c in changeset.get("changes", [])):
            try:
                anchor_plan = plan_cosmetic_citation_relocations(
                    wiki_repo_root=wiki_repo_root, repo_root=repo_root, source_cfg=source_cfg
                )
                if anchor_plan.get("replacements"):
                    issues.append(_issue(
                        "L1", "ERROR", "CITE_ANCHOR_STALE",
                        "cosmetic source drift moved precise cite anchors; run wiki manifest-refresh before verify",
                        relocations=len(anchor_plan.get("replacements") or []),
                    ))
            except ValueError as exc:
                issues.append(_issue(
                    "L1", "ERROR", "CITE_ANCHOR_RELOCATION_UNAVAILABLE", str(exc)
                ))

    all_cites = 0
    line_eligible_cites = 0
    cites_with_lines = 0
    dep_files: set[str] = set()
    seen_docs: set[str] = set()

    actual_wiki_docs: set[str] = set()
    if wiki_repo_root.is_dir():
        for md in wiki_repo_root.rglob("*.md"):
            if not md.is_file():
                continue
            rel_md = md.relative_to(wiki_repo_root).as_posix()
            if rel_md.startswith("meta/"):
                continue
            actual_wiki_docs.add(rel_md)
    declared_paths = {str(d.get("path") or "").replace("\\", "/") for d in docs if isinstance(d, dict) and d.get("path")}
    for rel_md in sorted(actual_wiki_docs - declared_paths):
        issues.append(_issue("L1", "ERROR", "WIKI_DOC_UNINDEXED", f"Wiki Markdown is not declared in manifest: {rel_md}", document=rel_md))

    # Navigation is part of the durable Wiki contract. Every directory on a document
    # path needs index.md so an Agent can navigate without rescanning the tree.
    required_indexes = {"index.md"} if actual_wiki_docs else set()
    for rel_md in actual_wiki_docs:
        if rel_md.endswith("/index.md") or rel_md == "index.md":
            continue
        parent = Path(rel_md).parent
        while str(parent) not in {".", ""}:
            required_indexes.add((parent / "index.md").as_posix())
            parent = parent.parent
    for idx in sorted(required_indexes):
        if idx not in actual_wiki_docs:
            issues.append(_issue("L1", "ERROR", "NAV_INDEX_MISSING", f"Wiki navigation index missing: {idx}", document=idx))

    for doc in docs:
        if not isinstance(doc, dict):
            issues.append(_issue("L1", "ERROR", "MANIFEST_DOCUMENT_INVALID", "manifest document entry is not a mapping"))
            continue

        rel = str(doc.get("path") or "").replace("\\", "/")
        if not rel:
            issues.append(_issue("L1", "ERROR", "DOC_PATH_MISSING", "manifest document path missing"))
            continue
        if rel in seen_docs:
            issues.append(_issue("L1", "ERROR", "DOC_PATH_DUPLICATE", f"duplicate manifest document path: {rel}", document=rel))
        seen_docs.add(rel)

        dtype = str(doc.get("type") or "")
        if dtype not in DOCUMENT_TYPES:
            issues.append(_issue("L1", "ERROR", "DOC_TYPE_INVALID", f"unsupported Wiki document type: {dtype or '<empty>'}", document=rel, allowed=sorted(DOCUMENT_TYPES)))

        try:
            path = resolve_wiki_relative(wiki_repo_root, rel)
        except ValueError as exc:
            issues.append(_issue("L1", "ERROR", "DOC_PATH_UNSAFE", str(exc), document=rel))
            continue

        if str(doc.get("status") or "") == "completed" and (not path.is_file() or path.stat().st_size == 0):
            issues.append(_issue("L1", "ERROR", "COMPLETED_DOC_MISSING", f"completed document missing/empty: {rel}", document=rel))

        text = ""
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                issues.append(_issue("L1", "ERROR", "WIKI_DOC_ENCODING_INVALID", f"Wiki Markdown must be UTF-8: {rel}", document=rel))
            expected_doc_hash = str(doc.get("content_hash") or "")
            if not HEX64.match(expected_doc_hash):
                issues.append(_issue("L1", "ERROR", "DOC_HASH_MISSING", f"document content_hash missing/invalid: {rel}", document=rel))
            else:
                current = hashlib.sha256(path.read_bytes()).hexdigest()
                if current != expected_doc_hash.lower():
                    issues.append(_issue("L1", "ERROR", "DOC_HASH_MISMATCH", f"document hash mismatch: {rel}", document=rel))

            # Citations are machine-derived from the exact Markdown bytes. A stale/manual
            # citation array must not be accepted simply because document hash happens to exist.
            actual_cites = _canonical_cites(extract_citations(text))
            indexed_cites = _canonical_cites(doc.get("citations") or [])
            if actual_cites != indexed_cites:
                issues.append(_issue("L1", "ERROR", "CITATION_INDEX_MISMATCH", f"manifest citations do not match Wiki Markdown: {rel}", document=rel))

            if canonical_version and text:
                current_patterns = (
                    r"(?:当前(?:活动)?(?:基座|系统)?版本|当前契约)\s*(?:为|是|[:：=])?\s*[`\"']?[vV]?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)",
                    r"ACTIVE_CONTRACT\s*(?:为|是|[:：=])\s*[`\"']?[vV]?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)",
                )
                stale_assertions = []
                for pattern in current_patterns:
                    for match in re.finditer(pattern, text, flags=re.I):
                        declared = match.group(1)
                        if declared != canonical_version:
                            stale_assertions.append({"declared": declared, "snippet": match.group(0)[:120]})
                if stale_assertions:
                    issues.append(_issue(
                        "L2", "ERROR", "CANONICAL_VERSION_ASSERTION_STALE",
                        f"Wiki asserts a current version/contract different from source VERSION: {rel}",
                        document=rel, source_version=canonical_version, assertions=stale_assertions[:8],
                    ))

        dependencies = doc.get("dependencies") or []
        if not isinstance(dependencies, list):
            issues.append(_issue("L1", "ERROR", "DEPENDENCIES_INVALID", f"document dependencies must be a list: {rel}", document=rel))
            dependencies = []
        if len(dependencies) > 1000:
            issues.append(_issue("L3", "WARN", "DEPENDENCY_BLOAT", f"document has unusually many dependencies: {rel}", document=rel, dependency_count=len(dependencies)))

        seen_deps: set[str] = set()
        for dep in dependencies:
            if not isinstance(dep, dict):
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_INVALID", f"dependency entry is not a mapping in {rel}", document=rel))
                continue
            file = str(dep.get("file") or "").replace("\\", "/")
            if not file:
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_PATH_MISSING", f"dependency path missing in {rel}", document=rel))
                continue
            if file in seen_deps:
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_DUPLICATE", f"duplicate dependency in {rel}: {file}", document=rel, source=file))
            seen_deps.add(file)
            dep_files.add(file)

            role = str(dep.get("role") or "")
            if role not in DEPENDENCY_ROLES:
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_ROLE_INVALID", f"invalid dependency role for {file}: {role or '<empty>'}", document=rel, source=file, allowed=sorted(DEPENDENCY_ROLES)))
            if dep.get("sections") is not None and not isinstance(dep.get("sections"), list):
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_SECTIONS_INVALID", f"dependency sections must be a list: {file}", document=rel, source=file))

            try:
                src = resolve_repo_relative(repo_root, file)
            except ValueError as exc:
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_PATH_UNSAFE", str(exc), document=rel, source=file))
                continue
            if not src.is_file():
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_SOURCE_MISSING", f"dependency source missing: {file}", document=rel, source=file))
                continue
            content_hash = str(dep.get("content_hash") or "")
            normalized_hash = str(dep.get("normalized_hash") or "")
            if not HEX64.match(content_hash) or not HEX64.match(normalized_hash):
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_HASH_MISSING", f"dependency hashes missing/invalid: {file}", document=rel, source=file))
                continue
            fp = fingerprint_file(repo_root, file, source_cfg)
            if fp.decode_status == "uncertain":
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_ENCODING_UNCERTAIN", f"dependency encoding cannot be safely decoded: {file}", document=rel, source=file))
            if fp.content_hash != content_hash.lower():
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_CONTENT_HASH_MISMATCH", f"source content hash mismatch: {file}", document=rel, source=file))
            if fp.normalized_hash != normalized_hash.lower():
                issues.append(_issue("L1", "ERROR", "DEPENDENCY_NORMALIZED_HASH_MISMATCH", f"source normalized hash mismatch: {file}", document=rel, source=file))

        citations = doc.get("citations") or []
        if not isinstance(citations, list):
            issues.append(_issue("L1", "ERROR", "CITATIONS_INVALID", f"document citations must be a list: {rel}", document=rel))
            citations = []
        if str(doc.get("status") or "") == "completed" and dtype in {"content-doc", "concept-card"} and not citations:
            issues.append(_issue("L2", "ERROR", "DOCUMENT_CITATION_MISSING", f"completed Wiki content has no source citation: {rel}", document=rel))
        for cite in citations:
            if not isinstance(cite, dict) or not cite.get("file"):
                issues.append(_issue("L1", "ERROR", "CITATION_INVALID", f"invalid citation entry in {rel}", document=rel))
                continue
            all_cites += 1
            file = str(cite["file"]).replace("\\", "/")
            try:
                src = resolve_repo_relative(repo_root, file)
            except ValueError as exc:
                issues.append(_issue("L1", "ERROR", "CITE_PATH_UNSAFE", str(exc), document=rel, source=file))
                continue
            if not src.is_file():
                issues.append(_issue("L1", "ERROR", "CITE_SOURCE_MISSING", f"citation source missing: {file}", document=rel, source=file))
                continue
            start = cite.get("line_start")
            end = cite.get("line_end")
            count = _line_count(src)
            # V3.4 iron rule: line-level provenance is the default. A genuinely
            # single-line source is the only deterministic exception.
            if count > 1:
                line_eligible_cites += 1
            if isinstance(start, int):
                if count > 1:
                    cites_with_lines += 1
                end = end if isinstance(end, int) else start
                if start < 1 or end < start or end > count:
                    issues.append(_issue("L1", "ERROR", "CITE_LINE_INVALID", f"citation line out of range: {file}:{start}-{end}", document=rel, source=file, line_count=count))
                elif count > 30 and start == 1 and end >= max(2, int(count * 0.90)):
                    issues.append(_issue("L1", "ERROR", "CITE_LINE_SUSPICIOUS_FULL_FILE", f"citation looks like an imprecise whole-file range: {file}:{start}-{end}", document=rel, source=file, line_count=count))

        # Local Markdown navigation links are part of the Wiki map. Ignore web/mail/anchor
        # links; relative links must stay inside this repo Wiki and point to an existing file.
        if text:
            for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", text):
                raw_target = target.strip().split()[0].strip("<>\"")
                if not raw_target or raw_target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                path_part = raw_target.split("#", 1)[0].split("?", 1)[0]
                if not path_part:
                    continue
                try:
                    linked = resolve_wiki_link(wiki_repo_root, rel, path_part)
                except ValueError as exc:
                    issues.append(_issue("L1", "ERROR", "WIKI_LINK_UNSAFE", str(exc), document=rel, target=raw_target))
                    continue
                if not linked.is_file():
                    issues.append(_issue("L1", "ERROR", "WIKI_LINK_BROKEN", f"local Wiki link target missing: {rel} -> {raw_target}", document=rel, target=raw_target))

        # ------------------------------------------------------------------
        # L3 Content quality / structure
        # ------------------------------------------------------------------
        if text:
            observed_cites = extract_citations(text)
            observed_cite_sections = extract_citation_sections(text)
            if dtype != "module-index" and observed_cites and not observed_cite_sections:
                issues.append(_issue(
                    "L2", "WARN", "CITATION_TARGETING_WEAK",
                    f"citations are not placed in substantive Wiki sections: {rel}",
                    document=rel,
                    guidance="place key cites next to the claims they support; a provenance/reference section may summarize but should not be the only cite location",
                ))
            if dtype == "content-doc":
                missing = [section for section in REQUIRED_CONTENT_SECTIONS if not re.search(rf"(?m)^#{{2,6}}\s*.*{re.escape(section)}", text)]
                if missing:
                    issues.append(_issue("L3", "ERROR", "CONTENT_SECTIONS_MISSING", f"content-doc missing standard sections: {rel}", document=rel, missing=missing))
                if re.search(r"<!--\s*(?:待填|TODO)\s*-->", text, flags=re.I):
                    issues.append(_issue("L3", "ERROR", "CONTENT_PLACEHOLDER", f"completed content-doc contains TODO/待填 placeholder: {rel}", document=rel))
                for section in REQUIRED_CONTENT_SECTIONS:
                    m = re.search(rf"(?ms)^#{{2,6}}\s*[^\n]*{re.escape(section)}[^\n]*\n(.*?)(?=^#{{1,6}}\s|\Z)", text)
                    if m:
                        body = re.sub(r"<cite\b[^>]*?/?>", "", m.group(1), flags=re.I)
                        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
                        body = re.sub(r"```.*?```", "", body, flags=re.S)
                        body = re.sub(r"\s+", "", body)
                        if len(body) < 5:
                            issues.append(_issue("L3", "ERROR", "CONTENT_SECTION_EMPTY", f"content-doc section has no substantive body: {rel} / {section}", document=rel, section=section))
            mermaid_opens = len(re.findall(r"```mermaid", text, flags=re.I))
            mermaid_closed = len(re.findall(r"(?is)```mermaid.*?```", text))
            if mermaid_opens != mermaid_closed:
                issues.append(_issue("L1", "ERROR", "MERMAID_UNCLOSED", f"unclosed mermaid block: {rel}", document=rel, opens=mermaid_opens, closed=mermaid_closed))
            strong_hits = [phrase for phrase in STRONG_FILLER_SIGNALS if phrase in text]
            if strong_hits:
                issues.append(_issue("L3", "WARN", "STRONG_FILLER_SIGNAL", f"known filler signal detected: {rel}", document=rel, phrases=strong_hits))
            repeated = _repeated_paragraphs(text, int(quality_cfg.get("filler_repetition_warn", 4)))
            if repeated:
                issues.append(_issue("L3", "WARN", "REPETITIVE_FILLER", f"repeated prose detected: {rel}", document=rel, samples=repeated[:3]))
            if len(re.sub(r"\s+", "", text)) < 180 and dtype not in {"module-index"}:
                issues.append(_issue("L3", "WARN", "LOW_INFORMATION_DENSITY", f"document is unusually short: {rel}", document=rel))

    # ------------------------------------------------------------------
    # L2 Traceability
    # ------------------------------------------------------------------
    cite_coverage = cites_with_lines / max(1, line_eligible_cites)
    cite_target = float(quality_cfg.get("citation_line_coverage_target", 0.90))
    if line_eligible_cites and cite_coverage < cite_target:
        issues.append(_issue("L2", "ERROR", "CITATION_LINE_COVERAGE_LOW", f"citation line coverage {cite_coverage:.1%} below required target {cite_target:.1%}", coverage=cite_coverage, target=cite_target, eligible=line_eligible_cites))

    source_files = set(discover_source_files(repo_root, source_cfg))
    if source_files and not docs:
        issues.append(_issue("L1", "ERROR", "NO_WIKI_DOCUMENTS", "source repo is non-empty but manifest has no Wiki documents"))

    coverage_report = compute_wiki_coverage(
        repo_root=repo_root,
        wiki_repo_root=wiki_repo_root,
        source_cfg=source_cfg,
        coverage_cfg=coverage_cfg,
        include_details=False,
    )
    coverage_summary = coverage_report["summary"]
    dep_coverage_raw = coverage_summary["source_dependency_coverage"]
    effective_coverage_raw = coverage_summary["effective_wiki_coverage"]
    dep_coverage = float(dep_coverage_raw) if dep_coverage_raw is not None else 0.0
    effective_coverage = float(effective_coverage_raw) if effective_coverage_raw is not None else 0.0

    dep_warn = float(quality_cfg.get("source_dependency_coverage_warn", 0.10))
    if source_files and dep_coverage < dep_warn:
        issues.append(_issue("L2", "WARN", "SOURCE_DEPENDENCY_COVERAGE_LOW", f"source dependency coverage {dep_coverage:.1%} below warning threshold {dep_warn:.1%}", coverage=dep_coverage, threshold=dep_warn))

    effective_warn = float(quality_cfg.get("effective_wiki_coverage_warn", 0.0))
    if coverage_summary["wiki_eligible_files"] and effective_warn > 0 and effective_coverage < effective_warn:
        issues.append(_issue(
            "L2", "WARN", "EFFECTIVE_WIKI_COVERAGE_LOW",
            f"effective Wiki coverage {effective_coverage:.1%} below warning threshold {effective_warn:.1%}",
            coverage=effective_coverage, threshold=effective_warn,
            covered=coverage_summary["trusted_covered_files"],
            eligible=coverage_summary["wiki_eligible_files"],
        ))

    # A staged plan may expose newly added/unbound topology even when existing deps are valid.
    if paths["plan"].is_file():
        plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
        if plan.get("change_set_id") != changeset.get("change_set_id"):
            issues.append(_issue("L1", "ERROR", "REBUILD_PLAN_STALE", "rebuild plan does not belong to the current change set"))
        unbound = plan.get("topology_review") or []
        if unbound:
            # This stays WARN rather than ERROR: L4 may truthfully conclude that an added
            # low-level source needs no durable Wiki representation. It may not be ignored
            # silently because any structural change also requires L4 before baseline commit.
            issues.append(_issue("L2", "WARN", "TOPOLOGY_REVIEW_REQUIRED", f"{len(unbound)} source topology changes require AI review", count=len(unbound)))
        if plan.get("uncertain_files"):
            issues.append(_issue("L1", "ERROR", "UNCERTAIN_SOURCE_CHANGE", "uncertain source changes remain unresolved", files=plan.get("uncertain_files")))

    errors = [i for i in issues if i["severity"] == "ERROR"]
    warns = [i for i in issues if i["severity"] == "WARN"]
    changes = changeset.get("changes", []) if changeset else []
    semantic_audit_required = any(c.get("kind") in {"SEMANTIC", "STRUCTURAL", "DELETED"} for c in changes)
    result = "PASS" if not errors else "FAIL"
    subject_digest = wiki_subject_digest(wiki_repo_root)
    report = {
        "schema": "ai-work.wiki-verification/v1",
        "verified_at": utc_now(),
        "change_set_id": changeset.get("change_set_id"),
        "result": result,
        "subject_digest": subject_digest,
        "semantic_audit_required": semantic_audit_required,
        "summary": {
            "errors": len(errors),
            "warnings": len(warns),
            "citations": all_cites,
            "citation_line_eligible": line_eligible_cites,
            "citation_line_coverage": cite_coverage,
            "source_dependency_coverage": dep_coverage_raw,
            "effective_wiki_coverage": effective_coverage_raw,
            "wiki_eligible_files": coverage_summary["wiki_eligible_files"],
            "trusted_covered_files": coverage_summary["trusted_covered_files"],
            "uncovered_files": coverage_summary["uncovered_files"],
        },
        "issues": issues,
    }
    paths["verification"].parent.mkdir(parents=True, exist_ok=True)
    paths["verification"].write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report


def record_semantic_audit(wiki_repo_root: Path, *, result: str, summary: str, documents: List[str], topology_reviewed: bool = False) -> Dict[str, Any]:
    """Record a semantic audit bound to the exact verified Wiki subject.

    Supports both staged change-set audits and standalone quality audits.  PASS always
    requires a deterministic ``wiki audit`` plan and must cover every mandatory document
    in that plan; a model cannot invent a smaller scope at record time.
    """
    paths = snapshot_paths(wiki_repo_root)
    changeset = json.loads(paths["changeset"].read_text(encoding="utf-8")) if paths["changeset"].is_file() else {}
    result = result.upper()
    if result not in {"PASS", "FAIL"}:
        raise ValueError("semantic audit result must be PASS or FAIL")
    if result == "PASS" and not summary.strip():
        raise ValueError("semantic audit PASS requires a non-empty summary")

    verification = json.loads(paths["verification"].read_text(encoding="utf-8")) if paths["verification"].is_file() else {}
    current_subject = wiki_subject_digest(wiki_repo_root)
    audit_plan = json.loads(paths["audit_plan"].read_text(encoding="utf-8")) if paths["audit_plan"].is_file() else {}

    if result == "PASS":
        if verification.get("result") != "PASS":
            raise ValueError("semantic audit PASS requires current deterministic verification PASS")
        if changeset and verification.get("change_set_id") != changeset.get("change_set_id"):
            raise ValueError("semantic audit PASS verification does not belong to the current change set")
        if verification.get("subject_digest") != current_subject:
            raise ValueError("Wiki subject changed after deterministic verification; verify again before semantic audit")
        if not audit_plan:
            raise ValueError("semantic audit PASS requires a deterministic audit plan; run wiki audit first")
        if audit_plan.get("change_set_id") != verification.get("change_set_id") or audit_plan.get("subject_digest") != current_subject:
            raise ValueError("semantic audit plan is stale; run wiki audit again")

    clean_documents: List[str] = []
    for rel in sorted(set(documents)):
        try:
            path = resolve_wiki_relative(wiki_repo_root, rel)
        except ValueError as exc:
            raise ValueError(f"semantic audit document path invalid: {rel}") from exc
        if not path.is_file():
            raise ValueError(f"semantic audit document does not exist: {rel}")
        clean_documents.append(rel.replace("\\", "/"))

    if result == "PASS":
        required = {
            str(row.get("document") or "").replace("\\", "/")
            for row in audit_plan.get("documents", [])
            if isinstance(row, dict) and row.get("document")
        }
        missing = sorted(required - set(clean_documents))
        if missing:
            raise ValueError(f"semantic audit PASS does not cover deterministic audit plan documents: {missing}")
        if audit_plan.get("topology_review_required") and not topology_reviewed:
            raise ValueError("semantic audit PASS requires explicit topology review for this audit scope")

    receipt = {
        "schema": "ai-work.wiki-semantic-audit/v1",
        "recorded_at": utc_now(),
        "mode": audit_plan.get("mode") or ("change-set" if changeset else "standalone"),
        "audit_scope": audit_plan.get("audit_scope"),
        "change_set_id": verification.get("change_set_id"),
        "result": result,
        "subject_digest": current_subject,
        "summary": summary.strip(),
        "documents": clean_documents,
        "topology_reviewed": bool(topology_reviewed),
    }
    paths["audit"].write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt
