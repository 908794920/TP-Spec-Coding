# -*- coding: utf-8 -*-
"""Truthful file-oriented Wiki coverage metrics.

The headline metric is *Effective Wiki Coverage*:

    trusted covered wiki-eligible source files / all wiki-eligible source files

The denominator is deliberately narrower than the source scanner.  Source scanning
must notice every potentially relevant change; Wiki coverage should only judge files
that have durable code-understanding value.  Every exclusion is reported with a
reason so the percentage remains auditable instead of becoming a vanity number.

A file counts as trusted covered only when both sides of the provenance edge are
current: the Wiki document bytes still match the manifest document hash, the source
normalized fingerprint still matches manifest provenance, and either:
- it is a primary/context dependency bound to a real current document section; or
- the document contains a real <cite> pointing at it.

An uncited ``reference`` dependency alone does not count, nor does a primary/context
edge with an empty/nonexistent section binding.  This prevents coverage inflation by
adding metadata-only dependency edges.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple
import fnmatch
import hashlib
import json
import re

from .manifest import extract_citations, load_manifest, resolve_wiki_relative
from .source import discover_source_files, fingerprint_file, resolve_repo_relative

COVERAGE_SCHEMA = "ai-work.wiki-coverage/v1"


def _norm(rel: str) -> str:
    return str(rel or "").replace("\\", "/").removeprefix("./")


def _list_setting(cfg: Dict[str, Any], name: str) -> List[Any]:
    value = cfg.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"wiki coverage setting {name} must be a list")
    return value


def _matches(rel: str, patterns: Iterable[str]) -> bool:
    value = _norm(rel)
    for raw in patterns:
        pattern = str(raw or "").replace("\\", "/").strip()
        if not pattern:
            continue
        if fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch("/" + value, pattern):
            return True
        # ``**/Foo`` should also match a root-level Foo.
        if pattern.startswith("**/") and fnmatch.fnmatch(value, pattern[3:]):
            return True
    return False


def classify_wiki_eligible_sources(
    repo_root: Path,
    source_cfg: Dict[str, Any],
    coverage_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify scanner-visible files into Wiki-eligible and explained exclusions."""
    discovered = discover_source_files(repo_root, source_cfg)
    force_include = _list_setting(coverage_cfg, "include_globs")
    no_doc = _list_setting(coverage_cfg, "no_doc_globs")
    excluded_exts = {str(x).lower() for x in _list_setting(coverage_cfg, "excluded_extensions")}
    markdown_roots = {str(x).strip("/\\") for x in _list_setting(coverage_cfg, "markdown_contract_roots") if str(x).strip("/\\")}

    eligible: List[str] = []
    excluded: List[Dict[str, str]] = []
    reasons: Counter[str] = Counter()

    for rel in discovered:
        rel = _norm(rel)
        path = Path(rel)
        ext = path.suffix.lower()
        parts = rel.split("/")

        if _matches(rel, force_include):
            eligible.append(rel)
            continue

        if _matches(rel, no_doc):
            reason = "no-independent-wiki-value"
        elif ext in excluded_exts:
            reason = "low-signal-asset"
        elif ext == ".md" and (not parts or parts[0] not in markdown_roots):
            # General README/docs are useful source references but are not code files whose
            # absence should lower Code Intelligence coverage.  Behaviour-defining Markdown
            # under agents/skills/automation/templates/wiki remains eligible.
            reason = "documentation-artifact"
        else:
            reason = ""

        if reason:
            excluded.append({"file": rel, "reason": reason})
            reasons[reason] += 1
        else:
            eligible.append(rel)

    return {
        "discovered": sorted(set(discovered)),
        "eligible": sorted(set(eligible)),
        "excluded": excluded,
        "excluded_by_reason": dict(sorted(reasons.items())),
    }


def _trusted_dependency(
    repo_root: Path,
    rel: str,
    dep: Dict[str, Any],
    source_cfg: Dict[str, Any],
    fp_cache: Dict[str, Any],
) -> Tuple[bool, str]:
    """Return whether a manifest edge still represents the current semantic source."""
    rel = _norm(rel)
    try:
        source = resolve_repo_relative(repo_root, rel)
    except ValueError:
        return False, "unsafe"
    if not source.is_file():
        return False, "missing"
    if rel not in fp_cache:
        fp_cache[rel] = fingerprint_file(repo_root, rel, source_cfg)
    fp = fp_cache[rel]
    recorded = str(dep.get("normalized_hash") or "")
    if not recorded:
        return False, "unverified"
    if recorded != fp.normalized_hash:
        return False, "stale"
    return True, "current"


def _wiki_doc_is_current(doc_path: Path, doc: Dict[str, Any]) -> bool:
    recorded = str(doc.get("content_hash") or "")
    if not recorded:
        return False
    return hashlib.sha256(doc_path.read_bytes()).hexdigest() == recorded


def _section_key(value: Any) -> str:
    text = str(value or "").strip()
    # Manifest history commonly stored logical names ("概述") while current headings
    # are numbered/bilingual ("1. 概述 (Overview)").  Numbering and the generated
    # English parenthetical label are presentation, not semantic identity.
    text = re.sub(r"^\d+(?:\.\d+)*[.、)]?\s*", "", text).strip()
    text = re.sub(r"\s*[（(][A-Za-z][A-Za-z0-9 /_&-]*[）)]\s*$", "", text).strip()
    return text.casefold()


def _has_current_section_binding(dep: Dict[str, Any], doc: Dict[str, Any]) -> bool:
    """Require a primary/context edge to name at least one section that still exists."""
    declared = {_section_key(x) for x in (dep.get("sections") or []) if _section_key(x)}
    if not declared:
        return False
    current = {_section_key(x) for x in (doc.get("sections") or []) if _section_key(x)}
    return bool(declared & current)


def compute_wiki_coverage(
    *,
    repo_root: Path,
    wiki_repo_root: Path,
    source_cfg: Dict[str, Any],
    coverage_cfg: Dict[str, Any],
    include_details: bool = False,
) -> Dict[str, Any]:
    """Compute scanner and effective Wiki file coverage with auditable counts."""
    classified = classify_wiki_eligible_sources(repo_root, source_cfg, coverage_cfg)
    discovered: Set[str] = set(classified["discovered"])
    eligible: Set[str] = set(classified["eligible"])
    manifest = load_manifest(wiki_repo_root)

    raw_dep_files: Set[str] = set()
    raw_cited_files: Set[str] = set()
    trusted_primary_context: Set[str] = set()
    trusted_cited: Set[str] = set()
    trusted_reference_only: Set[str] = set()
    stale_claims: Set[str] = set()
    unverified_claims: Set[str] = set()
    missing_claims: Set[str] = set()
    unsafe_claims: Set[str] = set()
    stale_wiki_documents: Set[str] = set()
    invalid_section_binding_files: Set[str] = set()
    file_documents: Dict[str, Set[str]] = defaultdict(set)
    fp_cache: Dict[str, Any] = {}

    docs = [d for d in (manifest.get("documents") or []) if isinstance(d, dict)]
    for doc in docs:
        if str(doc.get("status") or "completed").lower() not in {"completed", "current", "active"}:
            continue
        doc_rel = _norm(doc.get("path"))
        if not doc_rel:
            continue
        try:
            doc_path = resolve_wiki_relative(wiki_repo_root, doc_rel)
        except ValueError:
            continue
        if not doc_path.is_file():
            continue
        if not _wiki_doc_is_current(doc_path, doc):
            # A standalone coverage run must not trust semantic edges from prose that
            # changed after the last deterministic manifest refresh.
            stale_wiki_documents.add(doc_rel)
            continue

        try:
            citations = extract_citations(doc_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            citations = []
        cited_here = {_norm(c.get("file")) for c in citations if c.get("file")}
        raw_cited_files.update(cited_here)

        dep_by_file: Dict[str, Dict[str, Any]] = {}
        for dep in doc.get("dependencies") or []:
            if not isinstance(dep, dict) or not dep.get("file"):
                continue
            rel = _norm(dep.get("file"))
            raw_dep_files.add(rel)
            # Prefer the strongest role if duplicates somehow exist.
            old = dep_by_file.get(rel)
            if old is None or str(dep.get("role") or "") in {"primary", "context"}:
                dep_by_file[rel] = dep

        for rel, dep in dep_by_file.items():
            trusted, state = _trusted_dependency(repo_root, rel, dep, source_cfg, fp_cache)
            if not trusted:
                if state == "stale":
                    stale_claims.add(rel)
                elif state == "unverified":
                    unverified_claims.add(rel)
                elif state == "missing":
                    missing_claims.add(rel)
                elif state == "unsafe":
                    unsafe_claims.add(rel)
                continue
            role = str(dep.get("role") or "reference").lower()
            if role in {"primary", "context"}:
                if _has_current_section_binding(dep, doc):
                    trusted_primary_context.add(rel)
                    file_documents[rel].add(doc_rel)
                else:
                    invalid_section_binding_files.add(rel)
            if rel in cited_here:
                trusted_cited.add(rel)
                file_documents[rel].add(doc_rel)
            elif role == "reference":
                trusted_reference_only.add(rel)

    trusted_covered = (trusted_primary_context | trusted_cited) & eligible
    trusted_cited_eligible = trusted_cited & eligible
    trusted_primary_context_eligible = trusted_primary_context & eligible
    dual_evidence = trusted_cited_eligible & trusted_primary_context_eligible
    citation_only = trusted_cited_eligible - trusted_primary_context_eligible
    semantic_only = trusted_primary_context_eligible - trusted_cited_eligible
    uncovered = sorted(eligible - trusted_covered)
    discovered_dep = discovered & raw_dep_files

    def ratio(num: int, den: int):
        return (num / den) if den else None

    report: Dict[str, Any] = {
        "schema": COVERAGE_SCHEMA,
        "repo_root": str(repo_root),
        "wiki_repo_root": str(wiki_repo_root),
        "summary": {
            "discovered_source_files": len(discovered),
            "wiki_eligible_files": len(eligible),
            "excluded_files": len(classified["excluded"]),
            "trusted_covered_files": len(trusted_covered),
            "uncovered_files": len(uncovered),
            "raw_dependency_files": len(raw_dep_files),
            "raw_cited_files": len(raw_cited_files),
            # Backward-compatible scanner-wide indicator.  It is NOT the headline metric.
            "source_dependency_linked_files": len(discovered_dep),
            "source_dependency_coverage": ratio(len(discovered_dep), len(discovered)),
            # Headline metric: current, semantically fingerprinted, meaningfully represented files.
            "effective_wiki_coverage": ratio(len(trusted_covered), len(eligible)),
            "citation_evidence_files": len(trusted_cited_eligible),
            "citation_evidence_coverage": ratio(len(trusted_cited_eligible), len(eligible)),
            "primary_context_files": len(trusted_primary_context_eligible),
            "primary_context_coverage": ratio(len(trusted_primary_context_eligible), len(eligible)),
            "dual_evidence_files": len(dual_evidence),
            "citation_only_covered_files": len(citation_only),
            "semantic_only_covered_files": len(semantic_only),
            "reference_only_not_counted": len((trusted_reference_only & eligible) - trusted_covered),
            "stale_claimed_files": len(stale_claims),
            "unverified_claimed_files": len(unverified_claims),
            "missing_claimed_files": len(missing_claims),
            "unsafe_claimed_files": len(unsafe_claims),
            "stale_wiki_documents": len(stale_wiki_documents),
            "invalid_section_binding_files": len(invalid_section_binding_files),
        },
        "excluded_by_reason": classified["excluded_by_reason"],
        "uncovered_sample": uncovered[:50],
        "rules": {
            "headline": "effective_wiki_coverage",
            "denominator": "wiki_eligible_files",
            "covered_when": "current Wiki document hash AND current source normalized hash AND ((primary/context with current section binding) OR real citation)",
            "reference_only_dependency_counts": False,
            "aggregate_rule": "sum covered files / sum eligible files; never average per-repo percentages",
        },
    }
    if include_details:
        report["details"] = {
            "eligible_files": sorted(eligible),
            "covered_files": sorted(trusted_covered),
            "uncovered_files": uncovered,
            "cited_covered_files": sorted(trusted_cited_eligible),
            "primary_context_covered_files": sorted(trusted_primary_context_eligible),
            "dual_evidence_files": sorted(dual_evidence),
            "citation_only_covered_files": sorted(citation_only),
            "semantic_only_covered_files": sorted(semantic_only),
            "excluded_files": classified["excluded"],
            "reference_only_not_counted": sorted((trusted_reference_only & eligible) - trusted_covered),
            "stale_claimed_files": sorted(stale_claims),
            "unverified_claimed_files": sorted(unverified_claims),
            "missing_claimed_files": sorted(missing_claims),
            "unsafe_claimed_files": sorted(unsafe_claims),
            "stale_wiki_documents": sorted(stale_wiki_documents),
            "invalid_section_binding_files": sorted(invalid_section_binding_files),
            "file_documents": {k: sorted(v) for k, v in sorted(file_documents.items()) if k in eligible},
        }
    return report



def evaluate_first_build_readiness(
    wiki_repo_root: Path,
    report: Dict[str, Any],
    *,
    minimum_effective_coverage: float,
) -> Dict[str, Any]:
    """Return a separate first-build readiness decision without turning coverage into L1-L3.

    ``effective_wiki_coverage_warn`` remains a descriptive quality threshold.  A clean
    build is different: before the first trusted baseline is committed, the AI must not
    reinterpret a low percentage as an acceptable partial baseline merely because L1-L3
    has no coverage error.  This readiness decision is therefore consumed by the build/
    audit/commit orchestration, not by the ordinary verification gate.
    """
    from .snapshot import snapshot_paths

    threshold = float(minimum_effective_coverage)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("initial_build_effective_coverage_min must be between 0 and 1")
    paths = snapshot_paths(wiki_repo_root)
    changeset: Dict[str, Any] = {}
    if paths["changeset"].is_file():
        changeset = json.loads(paths["changeset"].read_text(encoding="utf-8"))
    initial = bool(changeset.get("initial"))
    summary = report.get("summary") or {}
    eligible = int(summary.get("wiki_eligible_files") or 0)
    covered = int(summary.get("trusted_covered_files") or 0)
    coverage = summary.get("effective_wiki_coverage")

    if not initial:
        return {
            "status": "NOT_APPLICABLE",
            "initial": False,
            "threshold": threshold,
            "effective_wiki_coverage": coverage,
            "covered": covered,
            "eligible": eligible,
            "uncovered": max(0, eligible - covered),
            "rule": "initial-build readiness applies only before the first source baseline",
        }
    ready = eligible == 0 or (coverage is not None and float(coverage) >= threshold)
    return {
        "status": "READY" if ready else "BUILD_INCOMPLETE",
        "initial": True,
        "threshold": threshold,
        "effective_wiki_coverage": coverage,
        "covered": covered,
        "eligible": eligible,
        "uncovered": max(0, eligible - covered),
        "rule": "initial build may proceed to full L4/baseline only after the configured effective coverage readiness threshold is met",
    }

def write_coverage_report(wiki_repo_root: Path, report: Dict[str, Any]) -> Path:
    path = wiki_repo_root / "meta" / "wiki-coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path
