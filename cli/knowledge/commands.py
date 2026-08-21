# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from cli.content_systems import junction_relation, load_content_systems
from .common import meta_paths, write_json, resolve_knowledge_project
from .eval import evaluate
from .ingest import convert_batch, disposition, finalize_batch, ingest_status, register_batch
from .migration import migration_plan
from .normalization import normalization_plan, apply_normalization
from .lint import lint_knowledge
from .projection import build_projection, projection_status, search, telemetry_summary, update_projection
from .state import commit_snapshot, create_audit_plan, maintain, record_audit, stage_scan, status as knowledge_status, task_scoped_convergence, verify


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _cfg(args):
    return load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))


def cmd_doctor(args) -> int:
    try:
        cfg=_cfg(args); root=cfg.paths.knowledge_physical_root
        issues=[]; warnings=[]
        if not root.exists(): issues.append("knowledge physical root missing")
        if not cfg.paths.knowledge_registry.is_file(): issues.append("knowledge project registry missing")
        proj=projection_status(cfg)
        if proj.get("status")=="MISSING": warnings.append("retrieval projection missing; run knowledge index build")
        legacy=[]
        for rel in ("tools/kb-index","tools/kb-rebuild","tools/kb-ingest","00-system/schemas","00-system/templates","AI知识库维护体系V1.md","外部文档知识沉淀流水线V1.md"):
            if (root/rel).exists(): legacy.append(rel)
        if legacy: warnings.append("legacy Knowledge runtime/rule assets still exist in Vault; Base is the active runtime authority")
        scope = resolve_knowledge_project(cfg, require=False)
        project_root = Path(scope["project_root"]) if scope.get("project_root") else cfg.paths.knowledge_physical_root
        if not scope.get("resolved"):
            warnings.append("current workspace has no resolved Knowledge project scope; project-scoped search will fail closed until registry/binding is fixed")
        result={
            "schema":"tp-spec.knowledge-doctor/v1","status":"PASS" if not issues else "FAIL",
            "paths":cfg.paths.as_dict(),
            "mount":junction_relation(cfg.paths.knowledge_logical_root,project_root),
            "project_scope":scope,
            "projection":proj,"legacy_assets":legacy,"issues":issues,"warnings":warnings,
            "retrieval":{"strategy":cfg.knowledge_retrieval.get("strategy"),"default_scope":cfg.knowledge_retrieval.get("default_scope","project"),"include_shared":cfg.knowledge_retrieval.get("include_shared",True),"global_fallback":cfg.knowledge_retrieval.get("global_fallback",False),"vector_mode":cfg.knowledge_projection.get("vector_mode"),"graph_mode":cfg.knowledge_projection.get("graph_mode")},
        }
        _emit(result); return 0 if not issues else 1
    except Exception as exc:
        _emit({"schema":"tp-spec.knowledge-doctor/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_init(args) -> int:
    try:
        cfg=_cfg(args); paths=meta_paths(cfg); paths["root"].mkdir(parents=True,exist_ok=True)
        # Init only machine-owned state root. It never invents project registry/canonical prose.
        _emit({"schema":"tp-spec.knowledge-init/v1","status":"PASS","meta_root":str(paths["root"]),"database":str(cfg.paths.knowledge_projection_db),"baseline_created":False}); return 0
    except Exception as exc:
        _emit({"schema":"tp-spec.knowledge-init/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_scan(args) -> int:
    try: _emit(stage_scan(_cfg(args))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-change-set/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_maintain(args) -> int:
    try: _emit(maintain(_cfg(args))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-maintain/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_verify(args) -> int:
    try:
        r=verify(_cfg(args)); _emit(r); return 0 if r["status"]=="PASS" else 1
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-verification/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_lint(args) -> int:
    try:
        r=lint_knowledge(_cfg(args)); _emit(r); return 0 if r["status"]=="PASS" else 1
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-lint/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_index_build(args) -> int:
    try: _emit(build_projection(_cfg(args),clean=True)); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-index/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_index_update(args) -> int:
    try: _emit(update_projection(_cfg(args))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-index/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_index_status(args) -> int:
    try:
        r=projection_status(_cfg(args)); _emit(r); return 0 if r.get("status") in {"PASS","WARN"} else 1
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-index-status/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_search(args) -> int:
    try:
        cfg=_cfg(args)
        resolved = None
        if not args.project and args.scope != "global":
            resolved = resolve_knowledge_project(cfg, require=True)
        hits=search(cfg,args.query,project=args.project,kind=args.kind,layer=args.layer,limit=args.limit,record_telemetry=not args.no_telemetry,scope=args.scope)
        _emit({"schema":"tp-spec.knowledge-search/v1","status":"PASS","query_hash_only":True,"strategy":cfg.knowledge_retrieval.get("strategy"),"scope":args.scope or cfg.knowledge_retrieval.get("default_scope","project"),"resolved_project":(resolved or {}).get("project_id") if resolved else args.project,"count":len(hits),"results":hits}); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-search/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_telemetry(args) -> int:
    try: _emit({"schema":"tp-spec.knowledge-retrieval-telemetry/v1",**telemetry_summary(_cfg(args),days=args.days)}); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-retrieval-telemetry/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_eval(args) -> int:
    try:
        modes = None if args.mode == "all" else [args.mode]
        _emit(evaluate(_cfg(args), golden_path=args.golden, output=args.output, modes=modes)); return 0
    except Exception as exc:
        _emit({"schema":"tp-spec.knowledge-golden-eval/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_migrate_plan(args) -> int:
    try: _emit(migration_plan(_cfg(args))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-migration-plan/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1



def cmd_migrate_normalize(args) -> int:
    try:
        cfg=_cfg(args)
        result = apply_normalization(cfg) if args.apply else normalization_plan(cfg)
        _emit(result)
        return 0
    except Exception as exc:
        _emit({"schema":"tp-spec.knowledge-normalization/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1

def cmd_audit(args) -> int:
    try: _emit(create_audit_plan(_cfg(args),full=bool(args.full))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-semantic-audit-plan/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_audit_record(args) -> int:
    try: _emit(record_audit(_cfg(args),result=args.result,summary=args.summary,documents=args.document or [])); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-semantic-audit-receipt/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_snapshot_commit(args) -> int:
    try: _emit(commit_snapshot(_cfg(args))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-snapshot-commit/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}","baseline_advanced":False}); return 1


def cmd_status(args) -> int:
    try: _emit(knowledge_status(_cfg(args))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-status/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_task_converge(args) -> int:
    """Consume a compact verified handoff without re-reading Task/repository."""
    try:
        payload = json.loads(args.handoff_json)
        _emit(task_scoped_convergence(payload))
        return 0
    except Exception as exc:
        _emit({"schema":"tp-spec.knowledge-task-convergence/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}","blocks_delivery":False})
        return 1


def cmd_ingest_register(args) -> int:
    try: _emit(register_batch(_cfg(args),project=args.project,batch=args.batch,source_root=Path(args.source_root))); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-ingest-status/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_ingest_status(args) -> int:
    try: _emit(ingest_status(_cfg(args),args.batch)); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-ingest-status/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_ingest_convert(args) -> int:
    try:
        _emit(convert_batch(_cfg(args), batch=args.batch, source_id=args.source_id, origin_path=args.origin_path))
        return 0
    except Exception as exc:
        _emit({"schema":"tp-spec.knowledge-ingest-convert/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_ingest_disposition(args) -> int:
    try: _emit(disposition(_cfg(args),batch=args.batch,source_id=args.source_id,disposition_name=args.disposition,canonical_ids=args.canonical_id or [],reason=args.reason or "",origin_path=args.origin_path)); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-ingest-status/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_ingest_finalize(args) -> int:
    try: _emit(finalize_batch(_cfg(args),args.batch)); return 0
    except Exception as exc: _emit({"schema":"tp-spec.knowledge-ingest-status/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"}); return 1


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace-root",default=".",help="opened workspace root")
    p.add_argument("--content-config",help="optional project Content Systems override")


def add_knowledge_subparsers(root_subparsers) -> None:
    k=root_subparsers.add_parser("knowledge",help="Standardized long-lived Knowledge Content System")
    sub=k.add_subparsers(dest="knowledge_cmd",required=True)
    for name,help_text,fn in [
        ("doctor","Resolve Knowledge paths and health",cmd_doctor),("init","Initialize machine-owned Knowledge meta only",cmd_init),
        ("scan","Stage Knowledge truth diff",cmd_scan),("maintain","Daily deterministic preflight; baseline unchanged",cmd_maintain),
        ("lint","Run deterministic canonical/evidence lint",cmd_lint),("verify","Run L1-L3 Knowledge quality gates",cmd_verify),
        ("status","Show Knowledge truth/projection/baseline state",cmd_status),("snapshot-commit","Advance trusted Knowledge baseline after bound PASS",cmd_snapshot_commit),
    ]:
        p=sub.add_parser(name,help=help_text); _common(p); p.set_defaults(func=fn)
    p=sub.add_parser("search",help="Project-scoped canonical-first FTS5 retrieval with source fallback"); _common(p); p.add_argument("-q","--query",required=True); p.add_argument("--project"); p.add_argument("--scope",choices=["project","global"],default=None,help="default comes from Content Systems; global must be explicit when project scope is active"); p.add_argument("--kind"); p.add_argument("--layer",choices=["canonical","source"]); p.add_argument("--limit",type=int); p.add_argument("--no-telemetry",action="store_true"); p.set_defaults(func=cmd_search)
    p=sub.add_parser("telemetry",help="Summarize hashed retrieval telemetry"); _common(p); p.add_argument("--days",type=int,default=7); p.set_defaults(func=cmd_telemetry)
    p=sub.add_parser("eval",help="Run local Golden Query evaluation without retrieval telemetry pollution"); _common(p); p.add_argument("--golden",help="golden JSONL path; defaults to Content Systems evaluation.golden_set"); p.add_argument("--output",help="result JSON path; defaults to configured evaluation.output_root"); p.add_argument("--mode",choices=["all","filename_search","source_only_fts","canonical_first_fts"],default="all"); p.set_defaults(func=cmd_eval)
    p=sub.add_parser("migrate-plan",help="Read-only plan for legacy Knowledge Vault runtime/rule assets"); _common(p); p.set_defaults(func=cmd_migrate_plan)
    p=sub.add_parser("migrate-normalize",help="Deterministic legacy canonical frontmatter normalization; dry-run by default"); _common(p); p.add_argument("--apply",action="store_true",help="apply only semantics-preserving safe transformations and write a receipt/review queue"); p.set_defaults(func=cmd_migrate_normalize)
    p=sub.add_parser("audit",help="Create deterministic L4 semantic audit scope"); _common(p); p.add_argument("--full",action="store_true"); p.set_defaults(func=cmd_audit)
    p=sub.add_parser("audit-record",help="Record conversational-model L4 result"); _common(p); p.add_argument("--result",required=True,choices=["PASS","FAIL","pass","fail"]); p.add_argument("--summary",required=True); p.add_argument("--document",action="append",default=[]); p.set_defaults(func=cmd_audit_record)

    p=sub.add_parser("task-converge",help="Cheap task-scoped Knowledge disposition from a verified compact handoff"); p.add_argument("--handoff-json",required=True,help="compact tp-spec.knowledge-task-handoff/v1 JSON object"); p.set_defaults(func=cmd_task_converge)

    idx=sub.add_parser("index",help="Knowledge SQLite FTS5 projection"); idxsub=idx.add_subparsers(dest="index_cmd",required=True)
    p=idxsub.add_parser("build"); _common(p); p.set_defaults(func=cmd_index_build)
    p=idxsub.add_parser("update"); _common(p); p.set_defaults(func=cmd_index_update)
    p=idxsub.add_parser("status"); _common(p); p.set_defaults(func=cmd_index_status)

    ing=sub.add_parser("ingest",help="External source registration/disposition workflow"); isub=ing.add_subparsers(dest="ingest_cmd",required=True)
    p=isub.add_parser("register"); _common(p); p.add_argument("--project",required=True); p.add_argument("--batch",required=True); p.add_argument("--source-root",required=True); p.set_defaults(func=cmd_ingest_register)
    p=isub.add_parser("convert",help="Normalize pending registered local documents with Microsoft MarkItDown"); _common(p); p.add_argument("--batch",required=True); p.add_argument("--source-id"); p.add_argument("--origin-path"); p.set_defaults(func=cmd_ingest_convert)
    p=isub.add_parser("status"); _common(p); p.add_argument("--batch",required=True); p.set_defaults(func=cmd_ingest_status)
    p=isub.add_parser("disposition"); _common(p); p.add_argument("--batch",required=True); p.add_argument("--source-id",required=True); p.add_argument("--origin-path"); p.add_argument("--disposition",required=True,choices=["pending","canonicalized","merged","source_only","duplicate","superseded","quarantined","excluded"]); p.add_argument("--canonical-id",action="append",default=[]); p.add_argument("--reason"); p.set_defaults(func=cmd_ingest_disposition)
    p=isub.add_parser("finalize"); _common(p); p.add_argument("--batch",required=True); p.set_defaults(func=cmd_ingest_finalize)
