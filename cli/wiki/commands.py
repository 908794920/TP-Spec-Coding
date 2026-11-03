# -*- coding: utf-8 -*-
"""CLI surface for the standardized TP-Spec-Coding Wiki subsystem."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .audit import build_audit_plan
from .anchors import anchor_health_report, repair_anchor_baseline, plan_cosmetic_citation_relocations
from .candidate import (active_candidate, begin_candidate, discard_candidate,
                        recover_publication, publish_candidate, cleanup_candidate)
from .config import junction_relation, load_content_systems
from .coverage import compute_wiki_coverage, evaluate_first_build_readiness, write_coverage_report
from .manifest import refresh_manifest, write_manifest, load_manifest
from .planner import build_plan
from .quality import record_semantic_audit, verify_repo
from .registry import RepoTarget, resolve_targets, write_local_registry
from cli.knowledge.common import resolve_knowledge_project
from .snapshot import (commit_baseline, snapshot_paths, stage_scan, prepare_source_config,
                       no_change_fast_path, validate_staged_source, build_current_snapshot,
                       classify_changes, wiki_subject_digest)
from cli.sensitive_scanner import redact_credential_values
from .source import read_source_bytes, decode_text, sha256_bytes
from .stable_source import source_view, relative_path
from .retrieval import update_index as update_retrieval_index
from .retrieval_commands import add_retrieval_subparsers
from .policy import record_policy_review, archive_rules, policy_review_hint


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _resolve(args) -> tuple[Any, List[RepoTarget]]:
    cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
    targets = resolve_targets(
        cfg,
        repo_id=getattr(args, "repo", None),
        repo_root=getattr(args, "repo_root", None),
        include_disabled=getattr(args, "include_disabled", False),
    )
    command = getattr(args, "wiki_cmd", "")
    candidate_commands = {"plan", "manifest-refresh", "verify", "coverage", "audit", "audit-record"}
    if command in candidate_commands or (command == "source-read" and not getattr(args, "baseline", False)):
        routed = []
        for target in targets:
            candidate = active_candidate(target.wiki_repo_root)
            if candidate is None and command in {"plan", "manifest-refresh"}:
                raise ValueError("WIKI_CANDIDATE_MISSING: run wiki maintain/build/scan first; published prose/manifest cannot be rewritten by maintenance")
            routed.append(replace(target, wiki_repo_root=candidate) if candidate else target)
        targets = routed
    return cfg, targets


def _candidate_target(target: RepoTarget) -> tuple[RepoTarget, Dict[str, Any]]:
    recovery = recover_publication(target.wiki_repo_root)
    discarded = discard_candidate(target.wiki_repo_root)
    candidate = begin_candidate(target.wiki_repo_root)
    return replace(target, wiki_repo_root=candidate), {
        "published_wiki_repo_root": str(target.wiki_repo_root), "candidate_wiki_repo_root": str(candidate),
        "publication_recovery": recovery, "previous_candidate": discarded,
    }


def _filesystem_no_change(cfg, target: RepoTarget, source_cfg: Dict[str, Any], args) -> Dict[str, Any] | None:
    if (getattr(args, "repair", False) or getattr(args, "initialize_source", False) or
            source_view(target.repo_root, source_cfg).mode != "FILESYSTEM"):
        return None
    paths = snapshot_paths(target.wiki_repo_root)
    if not paths["baseline"].is_file() or any(paths[n].exists() for n in
            ("pending", "changeset", "plan", "verification", "audit_plan", "audit")):
        return None
    baseline = json.loads(paths["baseline"].read_text(encoding="utf-8"))
    completion = baseline.get("completion") or {}
    if (completion.get("status") != "SUCCESS" or
            baseline.get("maintenance_digest") != source_cfg.get("_maintenance_digest") or
            completion.get("subject_digest") != wiki_subject_digest(target.wiki_repo_root)):
        return None
    current = build_current_snapshot(target.repo_id, target.repo_root, source_cfg, old=baseline)
    changes = classify_changes(baseline, current, cfg.snapshot)
    if changes["changes"] or baseline.get("source") != current.get("source"):
        return None
    return {"state": "NO_CHANGE", "fast_path": False, "source_scanned": True,
            "requires_ai_update": False, "llm_dispatch": False, "plan": None}


def _assert_candidate_scope(canonical: Path, candidate: Path, repo_root: Path, source_cfg: Dict[str, Any]) -> None:
    from .subject import MANIFEST, subject_files
    paths = snapshot_paths(candidate)
    changeset = json.loads(paths["changeset"].read_text(encoding="utf-8"))
    if changeset.get("initial"):
        return
    before, after = subject_files(canonical), subject_files(candidate)
    durable_changes = {rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel)}
    unknown = {rel for rel in durable_changes if rel != MANIFEST and not rel.endswith(".md")}
    if unknown:
        raise ValueError("WIKI_CANDIDATE_SCOPE_CHANGED: unreviewed durable files changed: " + ", ".join(sorted(unknown)))
    plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
    allowed = {row["document"] for row in plan.get("affected_documents", [])}
    audit = json.loads(paths["audit"].read_text(encoding="utf-8")) if paths["audit"].is_file() else {}
    if plan.get("topology_review") and audit.get("topology_reviewed"):
        allowed.update(audit.get("documents") or [])
        deleted_sources = {row["file"] for row in plan["topology_review"] if row.get("change_kind") == "DELETED"}
        for document in load_manifest(canonical).get("documents") or []:
            if any(dep.get("file") in deleted_sources for dep in document.get("dependencies") or []):
                allowed.add(document["path"])
    old = {p.relative_to(canonical).as_posix(): p.read_bytes() for p in canonical.rglob("*.md")}
    new = {p.relative_to(candidate).as_posix(): p.read_bytes() for p in candidate.rglob("*.md")}
    unexpected = {rel for rel in old.keys() | new.keys() if old.get(rel) != new.get(rel)} - allowed
    if unexpected and plan.get("cosmetic_files"):
        relocations = plan_cosmetic_citation_relocations(wiki_repo_root=canonical, repo_root=repo_root,
                                                       source_cfg=source_cfg, changeset=changeset)
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in relocations.get("replacements", []):
            grouped.setdefault(row["document"], []).append(row)
        for rel in unexpected & grouped.keys():
            text = (canonical / rel).read_text(encoding="utf-8")
            for row in sorted(grouped[rel], key=lambda row: row["start"], reverse=True):
                text = text[:row["start"]] + row["new_tag"] + text[row["end"]:]
            if new[rel] == text.encode("utf-8"):
                unexpected.remove(rel)
    if unexpected:
        raise ValueError("WIKI_CANDIDATE_SCOPE_CHANGED: changed prose outside current affected/reviewed topology scope: " + ", ".join(sorted(unexpected)))


def _coverage_cfg(cfg, target: RepoTarget) -> Dict[str, Any]:
    """Merge global coverage policy with optional per-repo registry override."""
    merged = dict(cfg.coverage)
    override = dict(target.coverage or {})
    for key, value in override.items():
        merged[key] = value
    return merged


def _source_cfg(cfg, target: RepoTarget, *, staged: bool = True, committed: bool = False) -> Dict[str, Any]:
    merged = {**cfg.source, **(target.source or {})}
    result = prepare_source_config(target.repo_root, target.wiki_repo_root, merged,
        cfg.snapshot, cfg.quality, _coverage_cfg(cfg, target), staged=staged, committed=committed)
    if staged and not committed and snapshot_paths(target.wiki_repo_root)["pending"].is_file():
        validate_staged_source(target.wiki_repo_root, target.repo_root, result)
    return result


def _scan(cfg, target: RepoTarget, source_cfg: Dict[str, Any], args) -> Dict[str, Any]:
    return stage_scan(target.repo_id, target.repo_root, target.wiki_repo_root, source_cfg, cfg.snapshot,
        initialize_source=bool(getattr(args, "initialize_source", False)),
        repair=bool(getattr(args, "repair", False)), documents=getattr(args, "document", None))


def _workspace_physical_root(cfg, targets: List[RepoTarget]) -> Path:
    if cfg.paths.wiki_layout == "legacy-central" and targets:
        # repo root is .../projects/<workspace-id>[/group]/<repo-id>
        ws_id = targets[0].workspace_id
        template = str(cfg.data["systems"]["wiki"].get("workspace_dir_template") or "projects/{workspace_id}")
        return (cfg.paths.wiki_system_root / template.format(workspace_id=ws_id)).resolve(strict=False)
    return cfg.paths.wiki_system_root.resolve(strict=False)


def cmd_doctor(args) -> int:
    try:
        cfg, targets = _resolve(args)
        physical_ws = _workspace_physical_root(cfg, targets)
        knowledge_scope = resolve_knowledge_project(cfg, require=False)
        knowledge_project_root = Path(knowledge_scope["project_root"]) if knowledge_scope.get("project_root") else cfg.paths.knowledge_physical_root
        result = {
            "schema": "tp-spec.wiki-doctor/v1",
            "status": "PASS",
            "config": cfg.paths.as_dict(),
            "wiki_mount": junction_relation(cfg.paths.wiki_logical_root, physical_ws),
            "knowledge_mount": junction_relation(cfg.paths.knowledge_logical_root, knowledge_project_root),
            "knowledge_scope": knowledge_scope,
            "registry_exists": cfg.paths.wiki_registry.is_file(),
            "targets": [t.as_dict() for t in targets],
            "issues": [],
        }
        for t in targets:
            if not t.repo_root.is_dir():
                result["issues"].append({"severity": "ERROR", "code": "REPO_ROOT_MISSING", "repo_id": t.repo_id, "path": str(t.repo_root)})
            try:
                prepared = _source_cfg(cfg, t, staged=False)
                next(row for row in result["targets"] if row["repo_id"] == t.repo_id)["resolved_source"] = source_view(t.repo_root, prepared).identity()
            except ValueError as exc:
                result["issues"].append({"severity": "ERROR", "code": "SOURCE_NEEDS_REVIEW", "repo_id": t.repo_id, "error": str(exc)})
        if any(i["severity"] == "ERROR" for i in result["issues"]):
            result["status"] = "FAIL"
        _emit(result)
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-doctor/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_init(args) -> int:
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        if getattr(args, "create_local_registry", False) and not cfg.paths.wiki_registry.exists():
            rid = args.repo or Path(args.repo_root or args.workspace_root).resolve(strict=False).name
            rroot = str(Path(args.repo_root or args.workspace_root).resolve(strict=False))
            write_local_registry(cfg, args.workspace_id or Path(args.workspace_root).resolve(strict=False).name, [{"id": rid, "repo_root": rroot, "enabled": True}])
        targets = resolve_targets(cfg, repo_id=args.repo, repo_root=args.repo_root)
        initialized = []
        for t in targets:
            (t.wiki_repo_root / "meta").mkdir(parents=True, exist_ok=True)
            mpath = t.wiki_repo_root / "meta" / "wiki-manifest.yaml"
            if not mpath.exists():
                manifest = {
                    "schema": "tp-spec.wiki-manifest/v1",
                    "workspace_id": t.workspace_id,
                    "repo_id": t.repo_id,
                    "repo_root": str(t.repo_root),
                    "provenance": {"semantic_content": {"type": "not-recorded", "model": "not-recorded"}},
                    "documents": [],
                    "stats": {"total_documents": 0, "total_citations": 0},
                }
                write_manifest(t.wiki_repo_root, manifest)
            initialized.append(t.as_dict())
        _emit({"schema": "tp-spec.wiki-init/v1", "status": "PASS", "targets": initialized, "registry": str(cfg.paths.wiki_registry)})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-init/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_build(args) -> int:
    """Prepare a first Wiki build; prose generation remains an AI responsibility."""
    return _stage_targets(args, build=True)


def cmd_scan(args) -> int:
    return _stage_targets(args, build=False)


def _stage_targets(args, *, build: bool) -> int:
    results = []
    try:
        cfg, targets = _resolve(args)
        for t in targets:
            try:
                if build and snapshot_paths(t.wiki_repo_root)["baseline"].is_file():
                    raise ValueError("Wiki baseline already exists; use wiki maintain")
                t, candidate_info = _candidate_target(t)
                source_cfg = _source_cfg(cfg, t, staged=False)
                changeset = _scan(cfg, t, source_cfg, args)
                row = {"repo_id": t.repo_id, "target": t.as_dict(), "changeset": changeset, "state": "STAGED", **candidate_info}
                if build:
                    plan = build_plan(t.wiki_repo_root, repo_root=t.repo_root, source_cfg=source_cfg, coverage_cfg=_coverage_cfg(cfg, t))
                    row.update(plan=plan, state="WAITING_FOR_AI" if plan["requires_ai_update"] else "DETERMINISTIC_FINALIZE")
                results.append(row)
            except (ValueError, OSError) as exc:
                results.append({"repo_id": t.repo_id, "state": "BLOCKED", "error": str(exc)})
        blocked = any(row["state"] == "BLOCKED" for row in results)
        status = "BLOCKED" if blocked else ("WAITING_FOR_AI" if build and any(row["state"] == "WAITING_FOR_AI" for row in results) else "PASS")
        _emit({"schema": "tp-spec.wiki-build/v1" if build else "tp-spec.wiki-scan-run/v1", "status": status,
               "results": results, "baseline_advanced": False})
        return 1 if blocked else 0
    except Exception as exc:
        _emit({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "results": results, "baseline_advanced": False})
        return 1


def cmd_plan(args) -> int:
    try:
        cfg, targets = _resolve(args)
        results = []
        for t in targets:
            source_cfg = _source_cfg(cfg, t)
            plan = build_plan(t.wiki_repo_root, allow_mass_change=bool(args.allow_mass_change), mass_change_reason=str(getattr(args, "mass_change_reason", "") or ""), repo_root=t.repo_root, source_cfg=source_cfg, coverage_cfg=_coverage_cfg(cfg, t))
            results.append({"repo_id": t.repo_id, "wiki_repo_root": str(t.wiki_repo_root), "plan": plan})
        _emit({"schema": "tp-spec.wiki-plan-run/v1", "status": "PASS", "results": results})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-plan-run/v1", "status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_manifest_refresh(args) -> int:
    try:
        cfg, targets = _resolve(args)
        results = []
        for t in targets:
            source_cfg = _source_cfg(cfg, t)
            manifest = refresh_manifest(workspace_id=t.workspace_id, repo_id=t.repo_id, repo_root=t.repo_root, wiki_repo_root=t.wiki_repo_root, source_cfg=source_cfg)
            plan = None
            if snapshot_paths(t.wiki_repo_root)["changeset"].is_file():
                existing_plan = {}
                ppath = snapshot_paths(t.wiki_repo_root)["plan"]
                if ppath.is_file():
                    try:
                        existing_plan = json.loads(ppath.read_text(encoding="utf-8"))
                    except Exception:
                        existing_plan = {}
                approved = bool(existing_plan.get("mass_change_approved"))
                reason = str(existing_plan.get("mass_change_review_reason") or "")
                try:
                    plan = build_plan(t.wiki_repo_root, allow_mass_change=approved, mass_change_reason=reason, repo_root=t.repo_root, source_cfg=source_cfg, coverage_cfg=_coverage_cfg(cfg, t))
                except ValueError as exc:
                    if "mass change guard" not in str(exc):
                        raise
            results.append({"repo_id": t.repo_id, "documents": len(manifest.get("documents") or []), "manifest": str(t.wiki_repo_root / "meta" / "wiki-manifest.yaml"), "plan_refreshed": plan is not None,
                            "cite_relocations_last_refresh": int((manifest.get("stats") or {}).get("cite_relocations_last_refresh") or 0)})
        _emit({"schema": "tp-spec.wiki-manifest-refresh/v1", "status": "PASS", "results": results})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-manifest-refresh/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_verify(args) -> int:
    try:
        cfg, targets = _resolve(args)
        reports = []
        failed = False
        for t in targets:
            print(f"[wiki verify] {t.repo_id}: starting", file=sys.stderr, flush=True)
            source_cfg = _source_cfg(cfg, t)
            def progress(message: str) -> None:
                print(f"[wiki verify] {t.repo_id}: {message}", file=sys.stderr, flush=True)
            report = verify_repo(repo_root=t.repo_root, wiki_repo_root=t.wiki_repo_root,
                                 source_cfg=source_cfg, quality_cfg=cfg.quality,
                                 coverage_cfg=_coverage_cfg(cfg, t), progress=progress)
            reports.append({"repo_id": t.repo_id, "report": report})
            failed = failed or report.get("result") != "PASS"
        _emit({"schema": "tp-spec.wiki-verify-run/v1", "status": "FAIL" if failed else "PASS", "results": reports})
        return 1 if failed else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-verify-run/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_coverage(args) -> int:
    """Report auditable source/Wiki file coverage; never edits Wiki prose or baseline."""
    try:
        cfg, targets = _resolve(args)
        results = []
        total_eligible = 0
        total_covered = 0
        total_discovered = 0
        total_dep_linked = 0
        for t in targets:
            source_cfg = _source_cfg(cfg, t)
            report = compute_wiki_coverage(
                repo_root=t.repo_root,
                wiki_repo_root=t.wiki_repo_root,
                source_cfg=source_cfg,
                coverage_cfg=_coverage_cfg(cfg, t),
                include_details=bool(getattr(args, "details", False)),
            )
            readiness = evaluate_first_build_readiness(
                t.wiki_repo_root,
                report,
                minimum_effective_coverage=float(cfg.quality.get("initial_build_effective_coverage_min", 0.95)),
            )
            report["first_build_readiness"] = readiness
            path = write_coverage_report(t.wiki_repo_root, report)
            s = report["summary"]
            total_eligible += int(s["wiki_eligible_files"])
            total_covered += int(s["trusted_covered_files"])
            total_discovered += int(s["discovered_source_files"])
            total_dep_linked += int(s["source_dependency_linked_files"])
            results.append({"repo_id": t.repo_id, "report_path": str(path), "report": report})

        aggregate = {
            "repos": len(results),
            "discovered_source_files": total_discovered,
            "wiki_eligible_files": total_eligible,
            "trusted_covered_files": total_covered,
            "uncovered_files": max(0, total_eligible - total_covered),
            "effective_wiki_coverage": (total_covered / total_eligible) if total_eligible else None,
            "source_dependency_coverage": (total_dep_linked / total_discovered) if total_discovered else None,
            "aggregation": "sum covered / sum eligible; percentages are not averaged",
        }
        _emit({"schema": "tp-spec.wiki-coverage-run/v1", "status": "PASS", "aggregate": aggregate, "results": results})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-coverage-run/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_audit(args) -> int:
    """Create a deterministic L4 semantic-audit scope for the model."""
    try:
        cfg, targets = _resolve(args)
        results = []
        for t in targets:
            source_cfg = _source_cfg(cfg, t)
            coverage_report = compute_wiki_coverage(
                repo_root=t.repo_root,
                wiki_repo_root=t.wiki_repo_root,
                source_cfg=source_cfg,
                coverage_cfg=_coverage_cfg(cfg, t),
                include_details=False,
            )
            readiness = evaluate_first_build_readiness(
                t.wiki_repo_root,
                coverage_report,
                minimum_effective_coverage=float(cfg.quality.get("initial_build_effective_coverage_min", 0.95)),
            )
            if readiness.get("status") == "BUILD_INCOMPLETE":
                raise ValueError(
                    "initial Wiki build incomplete: effective coverage "
                    f"{float(readiness.get('effective_wiki_coverage') or 0.0):.1%} below readiness "
                    f"threshold {float(readiness.get('threshold') or 0.0):.1%}; "
                    f"{int(readiness.get('uncovered') or 0)} wiki-eligible files remain uncovered"
                )
            plan = build_audit_plan(t.wiki_repo_root, cfg.quality, full=bool(getattr(args, "full", False)))
            plan["first_build_readiness"] = readiness
            results.append({"repo_id": t.repo_id, "audit_plan": plan})
        _emit({"schema": "tp-spec.wiki-audit-plan-run/v1", "status": "PASS", "results": results})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-audit-plan-run/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_audit_record(args) -> int:
    try:
        cfg, targets = _resolve(args)
        if len(targets) != 1:
            raise ValueError("audit-record requires exactly one repo; use --repo")
        source_cfg = _source_cfg(cfg, targets[0])
        claims_file = getattr(args, "claims_file", None)
        claims = json.loads(Path(claims_file).read_text(encoding="utf-8-sig")) if claims_file else None
        receipt = record_semantic_audit(targets[0].wiki_repo_root, result=args.result, summary=args.summary,
            documents=args.document or [], topology_reviewed=bool(args.topology_reviewed), claims=claims,
            repo_root=targets[0].repo_root, source_cfg=source_cfg)
        _emit(receipt)
        return 0 if receipt["result"] == "PASS" else 1
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-semantic-audit/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_anchors_doctor(args) -> int:
    """Report committed precise-citation anchor coverage without writes."""
    try:
        cfg, targets = _resolve(args)
        results = []
        degraded = False
        for t in targets:
            source_cfg = _source_cfg(cfg, t, committed=True)
            report = anchor_health_report(
                wiki_repo_root=t.wiki_repo_root, repo_root=t.repo_root,
                repo_id=t.repo_id, source_cfg=source_cfg,
            )
            results.append({"repo_id": t.repo_id, "report": report})
            degraded = degraded or report.get("status") != "PASS"
        _emit({"schema": "tp-spec.wiki-anchors-doctor/v1", "status": "DEGRADED" if degraded else "PASS", "results": results})
        return 1 if degraded else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-anchors-doctor/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_anchors_repair(args) -> int:
    """Safely rebuild partial committed anchors without advancing source baseline."""
    try:
        cfg, targets = _resolve(args)
        results = []
        blocked = False
        for t in targets:
            source_cfg = _source_cfg(cfg, t, committed=True)
            try:
                result = repair_anchor_baseline(
                    wiki_repo_root=t.wiki_repo_root, repo_root=t.repo_root,
                    repo_id=t.repo_id, source_cfg=source_cfg, apply=bool(args.apply),
                )
                results.append({"repo_id": t.repo_id, "result": result})
            except ValueError as exc:
                blocked = True
                results.append({"repo_id": t.repo_id, "status": "BLOCKED", "error": str(exc)})
        _emit({
            "schema": "tp-spec.wiki-anchors-repair/v1",
            "status": "BLOCKED" if blocked else ("PASS" if args.apply else "PLAN"),
            "apply": bool(args.apply),
            "results": results,
        })
        return 1 if blocked else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-anchors-repair/v1", "status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_snapshot_commit(args) -> int:
    results = []
    try:
        cfg, targets = _resolve(args)
        for t in targets:
            try:
                canonical = t.wiki_repo_root
                candidate = active_candidate(canonical)
                if candidate is None:
                    raise ValueError("WIKI_CANDIDATE_MISSING: run wiki maintain/build/scan first")
                t = replace(t, wiki_repo_root=candidate)
                source_cfg = _source_cfg(cfg, t)
                validate_staged_source(t.wiki_repo_root, t.repo_root, source_cfg)
                coverage_report = compute_wiki_coverage(
                    repo_root=t.repo_root, wiki_repo_root=t.wiki_repo_root, source_cfg=source_cfg,
                    coverage_cfg=_coverage_cfg(cfg, t), include_details=False)
                readiness = evaluate_first_build_readiness(t.wiki_repo_root, coverage_report,
                    minimum_effective_coverage=float(cfg.quality.get("initial_build_effective_coverage_min", 0.95)))
                if readiness.get("status") == "BUILD_INCOMPLETE":
                    raise ValueError("baseline blocked: initial Wiki build coverage incomplete")
                _assert_candidate_scope(canonical, candidate, t.repo_root, source_cfg)
                result = commit_baseline(t.wiki_repo_root, repo_id=t.repo_id, repo_root=t.repo_root,
                                         source_cfg=source_cfg, require_verification=True)
                publication = publish_candidate(canonical, expected_candidate=candidate)
                results.append({"repo_id": t.repo_id, "first_build_readiness": readiness, **result,
                                "publication": publication,
                                "cleanup_pending": result.get("cleanup_pending", []) + publication.get("cleanup_pending", [])})
            except (ValueError, OSError) as exc:
                results.append({"repo_id": t.repo_id, "result": "BLOCKED", "error": str(exc), "baseline_advanced": False})
        # A fully successful Wiki baseline batch is the maintenance success
        # boundary for retrieval. Refresh the isolated user-root projection
        # only when every target committed; projection/telemetry problems are
        # reported as warnings and never undo a committed baseline.
        committed = [row for row in results if row.get("result") == "COMMITTED"]
        blocked = any(row.get("result") == "BLOCKED" for row in results)
        if committed and not blocked:
            try:
                index_result = update_retrieval_index(cfg)
                for row in committed:
                    row["retrieval_index_update"] = index_result
            except Exception as exc:
                warning = {"status": "WARN", "error": f"{type(exc).__name__}: {exc}"}
                for row in committed:
                    row["retrieval_index_update"] = warning
        elif committed and blocked:
            for row in committed:
                row["retrieval_index_update"] = {
                    "status": "SKIPPED",
                    "reason": "batch contains a blocked snapshot-commit; current manifests are not a whole-batch success",
                }
        failed = blocked
        _emit({"schema": "tp-spec.wiki-baseline-commit/v1", "status": "BLOCKED" if failed else "PASS",
               "results": results, "committed_repos": [row["repo_id"] for row in results if row["result"] == "COMMITTED"]})
        return 1 if failed else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-baseline-commit/v1", "status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}", "results": results})
        return 1


def cmd_candidate_cleanup(args) -> int:
    results = []
    try:
        _, targets = _resolve(args)
        for target in targets:
            try:
                result = cleanup_candidate(target.wiki_repo_root, apply=args.apply,
                    retirement_receipts=[Path(path) for path in args.retirement_receipt])
                results.append({"repo_id": target.repo_id, **result})
            except (ValueError, OSError) as exc:
                results.append({"repo_id": target.repo_id, "status": "BLOCKED", "error": str(exc)})
        blocked = any(row["status"] == "BLOCKED" for row in results)
        pending = any(row["status"] == "WARN" for row in results)
        _emit({"schema": "tp-spec.wiki-candidate-cleanup/v1", "apply": args.apply,
               "status": "BLOCKED" if blocked else ("WARN" if pending else ("APPLIED" if args.apply else "PLAN")), "results": results})
        return 1 if blocked else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-candidate-cleanup/v1", "status": "BLOCKED", "error": str(exc), "results": results})
        return 1


def cmd_status(args) -> int:
    try:
        _, targets = _resolve(args)
        results = []
        for t in targets:
            paths = snapshot_paths(t.wiki_repo_root)
            row = {"repo_id": t.repo_id, "repo_root": str(t.repo_root), "wiki_repo_root": str(t.wiki_repo_root)}
            candidate = active_candidate(t.wiki_repo_root)
            row["candidate_wiki_repo_root"] = str(candidate) if candidate else None
            for name, path in paths.items():
                row[name] = {"path": str(path), "exists": path.is_file()}
                if path.is_file() and path.suffix == ".json":
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        row[name]["id"] = data.get("change_set_id") or data.get("snapshot_id")
                        row[name]["result"] = data.get("result")
                        if data.get("source"):
                            row[name]["source"] = data["source"]
                        if data.get("completion"):
                            row[name]["completion"] = data["completion"]
                    except Exception:
                        row[name]["parse_error"] = True
            results.append(row)
        _emit({"schema": "tp-spec.wiki-status/v1", "status": "PASS", "results": results})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-status/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_policy_archive(args) -> int:
    try:
        result = archive_rules(Path(__file__).resolve().parents[2], args.output_root, scope=args.rule_scope)
        _emit(result)
        return 0
    except (ValueError, OSError) as exc:
        _emit({"status": "BLOCKED", "error": str(exc), "semantic_review_recorded": False})
        return 1


def cmd_policy_review(args) -> int:
    try:
        cfg, targets = _resolve(args)
        if len(targets) != 1:
            raise ValueError("policy-review requires exactly one resolved repository")
        target = targets[0]
        review = record_policy_review(target.wiki_repo_root, _source_cfg(cfg, target, staged=False),
            old_root=args.old_base_root, old_ref=args.old_base_ref, scope=args.old_rule_scope,
            summary=args.summary, evidence_file=args.evidence_file)
        _emit({"status": "RECORDED", "review": review})
        return 0
    except Exception as exc:
        _emit({"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_maintain(args) -> int:
    """Pin -> successful-baseline fast path -> diff/plan. Never advances baseline."""
    results = []
    try:
        cfg, targets = _resolve(args)
        if getattr(args, "document", None) and not getattr(args, "repair", False):
            raise ValueError("--document requires --repair")
        for t in targets:
            try:
                recovery = recover_publication(t.wiki_repo_root)
                discarded = discard_candidate(t.wiki_repo_root)
                source_cfg = _source_cfg(cfg, t, staged=False)
                fast = no_change_fast_path(t.wiki_repo_root, t.repo_root, source_cfg,
                    repair=bool(getattr(args, "repair", False) or getattr(args, "initialize_source", False)))
                if fast is None:
                    fast = _filesystem_no_change(cfg, t, source_cfg, args)
                if fast is not None:
                    results.append({"repo_id": t.repo_id, **fast, "publication_recovery": recovery,
                                    "previous_candidate": discarded})
                    continue
                canonical = t.wiki_repo_root
                candidate = begin_candidate(canonical)
                t = replace(t, wiki_repo_root=candidate)
                candidate_info = {"published_wiki_repo_root": str(canonical), "candidate_wiki_repo_root": str(candidate),
                                  "publication_recovery": recovery, "previous_candidate": discarded}
                hint = policy_review_hint(canonical, source_cfg)
                if hint is not None:
                    candidate_info["policy_review_hint"] = hint
                paths = snapshot_paths(t.wiki_repo_root)
                changeset = _scan(cfg, t, source_cfg, args)
                approved, reason = False, ""
                if (changeset.get("guard") or {}).get("status") == "MASS_CHANGE_REVIEW_REQUIRED":
                    prior_plan = json.loads(paths["plan"].read_text(encoding="utf-8")) if paths["plan"].is_file() else {}
                    reason = str(prior_plan.get("mass_change_review_reason") or "").strip()
                    approved = (prior_plan.get("change_set_id") == changeset.get("change_set_id")
                                and prior_plan.get("mass_change_approved") is True and bool(reason))
                    if not approved:
                        results.append({"repo_id": t.repo_id, "state": "MASS_CHANGE_REVIEW_REQUIRED", "changeset": changeset, **candidate_info})
                        continue
                plan = build_plan(t.wiki_repo_root, allow_mass_change=approved, mass_change_reason=reason,
                                  repo_root=t.repo_root, source_cfg=source_cfg, coverage_cfg=_coverage_cfg(cfg, t))
                state = "WAITING_FOR_AI" if plan.get("requires_ai_update") else "DETERMINISTIC_FINALIZE"
                results.append({"repo_id": t.repo_id, "state": state, "fast_path": False,
                                "changeset": changeset, "plan": plan, "requires_ai_update": plan["requires_ai_update"], **candidate_info})
            except (ValueError, OSError) as exc:
                results.append({"repo_id": t.repo_id, "state": "BLOCKED", "error": str(exc), "baseline_advanced": False})
        states = {row["state"] for row in results}
        if states & {"BLOCKED", "MASS_CHANGE_REVIEW_REQUIRED"}:
            overall = "BLOCKED"
        elif "WAITING_FOR_AI" in states:
            overall = "WAITING_FOR_AI"
        elif "DETERMINISTIC_FINALIZE" in states:
            overall = "DETERMINISTIC_FINALIZE"
        else:
            overall = "NO_CHANGE"
        _emit({"schema": "tp-spec.wiki-maintain/v1", "status": overall, "results": results, "baseline_advanced": False})
        return 1 if overall == "BLOCKED" else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-maintain/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "results": results, "baseline_advanced": False})
        return 1


def cmd_source_read(args) -> int:
    """Bounded source reads for the AI author/auditor, using the same pinned object."""
    try:
        cfg, targets = _resolve(args)
        if len(targets) != 1:
            raise ValueError("source-read requires exactly one repo; use --repo")
        if args.start_line < 1 or (args.end_line is not None and args.end_line < args.start_line):
            raise ValueError("line range must satisfy 1 <= start-line <= end-line")
        target = targets[0]
        paths = snapshot_paths(target.wiki_repo_root)
        recorded = paths["baseline"] if args.baseline else (paths["pending"] if paths["pending"].is_file() else paths["baseline"])
        if not recorded.is_file():
            raise ValueError("source-read needs a staged or successful source snapshot; run wiki scan first")
        source_cfg = _source_cfg(cfg, target, committed=recorded == paths["baseline"])
        rel = relative_path(args.path)
        data = read_source_bytes(target.repo_root, rel, source_cfg)
        if source_view(target.repo_root, source_cfg).mode == "FILESYSTEM":
            recorded_snapshot = json.loads(recorded.read_text(encoding="utf-8"))
            entry = recorded_snapshot.get("files", {}).get(rel) or {}
            if entry.get("content_hash") != sha256_bytes(data):
                raise ValueError("FILESYSTEM_SOURCE_CHANGED: no matching recorded bytes; scan again (historical bytes cannot be reconstructed from hashes)")
        text, encoding, status = decode_text(data)
        if text is None or status == "uncertain":
            raise ValueError("source text encoding is uncertain; cannot present reliable source lines")
        safe = redact_credential_values(text)
        if safe.get("error"):
            raise ValueError(safe["error"])
        lines = safe["text"].splitlines()
        if len(lines) != len(text.splitlines()):
            raise ValueError("credential redaction could not preserve source line layout")
        end = args.end_line if args.end_line is not None else len(lines)
        if args.start_line > max(1, len(lines)) or end > len(lines):
            raise ValueError("requested lines exceed pinned source line count")
        _emit({"schema": "tp-spec.wiki-source-read/v1", "status": "PASS", "repo_id": target.repo_id,
               "source": source_view(target.repo_root, source_cfg).identity(), "path": rel,
               "content_hash": sha256_bytes(data), "encoding": encoding, "line_count": len(lines),
               "text_view": "credential-redacted", "redactions": [row for row in safe["redactions"]
                   if row["line_start"] <= end and row["line_end"] >= args.start_line],
               "line_start": args.start_line if lines else None, "line_end": end if lines else None, "text": "\n".join(lines[args.start_line-1:end])})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-source-read/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def _add_common(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    defaults = {"default": argparse.SUPPRESS} if suppress_defaults else {}
    parser.add_argument("--workspace-root", help="opened workspace root", **({"default": "."} if not suppress_defaults else defaults))
    parser.add_argument("--content-config", help="optional project Content Systems config override", **defaults)
    parser.add_argument("--repo", help="repo id; omitted means all enabled repos in matched workspace", **defaults)
    parser.add_argument("--repo-root", help="explicit repo root when no registry entry exists", **defaults)


def add_wiki_subparsers(root_subparsers) -> None:
    wiki = root_subparsers.add_parser("wiki", help="Standardized code-understanding Wiki operations")
    subs = wiki.add_subparsers(dest="wiki_cmd", required=True)

    p = subs.add_parser("doctor", help="Resolve Content Systems paths and report Wiki/Knowledge mount health")
    _add_common(p); p.set_defaults(func=cmd_doctor)

    p = subs.add_parser("init", help="Initialize deterministic Wiki metadata without generating prose")
    _add_common(p)
    p.add_argument("--workspace-id")
    p.add_argument("--create-local-registry", action="store_true")
    p.set_defaults(func=cmd_init)

    p = subs.add_parser("build", help="Prepare an initial Wiki build plan; AI writes prose, baseline remains unchanged")
    _add_common(p); p.set_defaults(func=cmd_build)

    p = subs.add_parser("scan", help="Stage source snapshot diff; never advances baseline")
    _add_common(p)
    p.add_argument("--initialize-source", action="store_true", help="explicitly initialize a legacy/changed source identity; retain old baseline until validated")
    p.set_defaults(func=cmd_scan)

    p = subs.add_parser("plan", help="Build dependency/topology-aware rebuild plan from staged scan")
    _add_common(p)
    p.add_argument("--allow-mass-change", action="store_true", help="only after confirming a real mass semantic/structural change")
    p.add_argument("--mass-change-reason", help="required audit reason when --allow-mass-change is used")
    p.set_defaults(func=cmd_plan)

    p = subs.add_parser("maintain", help="AI-maintenance deterministic preflight: scan + guard + plan, baseline unchanged")
    _add_common(p)
    p.add_argument("--initialize-source", action="store_true", help="explicit source-identity initialization, not a history-force override")
    p.add_argument("--repair", action="store_true", help="explicitly re-evaluate Wiki even at an unchanged commit")
    p.add_argument("--document", action="append", default=[], help="limit explicit repair to a declared Wiki document; requires --repair")
    p.set_defaults(func=cmd_maintain)

    p = subs.add_parser("policy-archive", help="Preserve complete current rule bytes before Base edits; never records a policy review")
    p.add_argument("--output-root", required=True, help="stable archive directory outside Base rule directories; differing existing bytes are never overwritten")
    p.add_argument("--rule-scope", choices=["maintenance", "whole-all"], default="maintenance")
    p.set_defaults(func=cmd_policy_archive)

    p = subs.add_parser("policy-review", help="Record an evidenced review of exact maintenance-policy differences; never records L4 PASS")
    _add_common(p)
    old = p.add_mutually_exclusive_group(required=True)
    old.add_argument("--old-base-root", help="read-only archived Base containing original rule bytes")
    old.add_argument("--old-base-ref", help="explicit historical Base Git revision; read objects without executing old code")
    p.add_argument("--old-rule-scope", required=True, choices=["whole-all", "maintenance"],
                   help="use maintenance for a maintenance_digest baseline; whole-all only for a matching legacy whole-All baseline; scope is never switched automatically")
    p.add_argument("--summary", required=True, help="actual semantic-equivalence review judgment")
    p.add_argument("--evidence-file", required=True, help="existing actual review evidence, retained by path and SHA256")
    p.set_defaults(func=cmd_policy_review)

    p = subs.add_parser("manifest-refresh", help="Regenerate machine-owned manifest hashes/citations after AI edits")
    _add_common(p); p.set_defaults(func=cmd_manifest_refresh)

    p = subs.add_parser("verify", help="Run deterministic L1-L3 quality gates and write verification receipt")
    _add_common(p); p.set_defaults(func=cmd_verify)

    p = subs.add_parser("coverage", help="Report truthful scanner/effective Wiki file coverage")
    _add_common(p)
    p.add_argument("--details", action="store_true", help="include full eligible/covered/uncovered file lists")
    p.set_defaults(func=cmd_coverage)

    p = subs.add_parser("audit", help="Create deterministic L4 semantic-audit scope for the model")
    _add_common(p)
    p.add_argument("--full", action="store_true", help="explicit standalone full-repo semantic audit; initial baseline is full automatically")
    p.set_defaults(func=cmd_audit)

    p = subs.add_parser("audit-record", help="Record model semantic-audit result for the current staged change set")
    _add_common(p)
    p.add_argument("--result", required=True, choices=["PASS", "FAIL", "pass", "fail"])
    p.add_argument("--summary", required=True)
    p.add_argument("--claims-file", help="optional JSON list of representative claims actually inspected; source/subject inherit this verified audit")
    p.add_argument("--document", action="append", default=[])
    p.add_argument("--topology-reviewed", action="store_true", help="confirm every item in the deterministic audit plan topology_review was actually examined")
    p.set_defaults(func=cmd_audit_record)

    p = subs.add_parser("anchors-doctor", help="Diagnose committed precise-citation anchor baseline coverage")
    _add_common(p); p.set_defaults(func=cmd_anchors_doctor)

    p = subs.add_parser("anchors-repair", help="Plan/apply safe partial anchor baseline rebuild without advancing source snapshot")
    _add_common(p)
    p.add_argument("--apply", action="store_true", help="write rebuilt anchor metadata only when committed source/Wiki subjects are unchanged")
    p.set_defaults(func=cmd_anchors_repair)

    p = subs.add_parser("snapshot-commit", help="Advance source baseline only after current verification/audit PASS")
    _add_common(p); p.set_defaults(func=cmd_snapshot_commit)

    p = subs.add_parser("source-read", help="Read source lines from the staged snapshot (or successful baseline), never a Git worktree")
    _add_common(p)
    p.add_argument("--path", required=True, help="repository-relative source path")
    p.add_argument("--start-line", type=int, default=1)
    p.add_argument("--end-line", type=int)
    p.add_argument("--baseline", action="store_true", help="read the last successful snapshot instead of the pending candidate")
    p.set_defaults(func=cmd_source_read)

    p = subs.add_parser("status", help="Show baseline/pending/plan/verification/audit state")
    _add_common(p); p.set_defaults(func=cmd_status)

    p = subs.add_parser("candidate-cleanup", help="Plan/apply owned retired-draft cleanup without changing published Wiki")
    _add_common(p)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--retirement-receipt", action="append", default=[], help="existing maintain receipt proving a legacy discard; unique durable bytes remain protected")
    p.set_defaults(func=cmd_candidate_cleanup)

    add_retrieval_subparsers(subs, _add_common)
