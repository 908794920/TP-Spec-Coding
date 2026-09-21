# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from cli.content_systems import junction_relation, load_content_systems
from .common import CANONICAL_SUBDIRS, meta_paths, write_json, resolve_knowledge_project, read_note
from .eval import evaluate
from .ingest import convert_batch, disposition, finalize_batch, ingest_status, register_batch
from .migration import migration_plan
from .normalization import normalization_plan, apply_normalization
from .lint import lint_knowledge, lint_canonical_note
from .projection import build_projection, projection_status, search, telemetry_summary, update_projection, update_canonical_note_projection
from .state import commit_snapshot, create_audit_plan, maintain, record_audit, stage_scan, status as knowledge_status, verify


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


def _task_convergence_request(conn, task_id: str, request_event_id: int):
    from cli import event_policies

    candidates = event_policies.load_trusted_governance_events(
        conn, task_id,
        event_type="KNOWLEDGE_CONVERGENCE_REQUEST",
        actor="tp-integration-engineer",
    )
    for item in candidates:
        if int(item.row["id"]) == int(request_event_id):
            return item
    raise ValueError(f"trusted Knowledge convergence request not found: {request_event_id}")


def _task_convergence_sources(task_dir: Path, values: List[str]) -> tuple[List[str], List[Dict[str, Any]]]:
    from cli import evidence

    refs: List[str] = []
    items: List[Dict[str, Any]] = []
    for raw in values:
        checked = evidence.validate_evidence_path(task_dir, raw, require_evidence_dir=False)
        if not checked.ok:
            raise ValueError(f"invalid Knowledge source: {checked.error}")
        ref = str(checked.path or "").replace("\\", "/")
        if ref not in refs:
            refs.append(ref)
            items.append(dict(checked.item or {"type": "local_file", "path": ref, "sha256": checked.sha256}))
    if not refs:
        raise ValueError("Knowledge convergence requires at least one Task source")
    return refs, items


def _search_receipt(cfg, query: str) -> Dict[str, Any]:
    from cli.delivery_contract import validate_receipt_payload

    hits = search(cfg, query, scope="project", record_telemetry=True)
    matched = sorted({
        str(hit.get("id") or "").strip()
        for hit in hits
        if str(hit.get("layer") or "") == "canonical" and str(hit.get("id") or "").strip()
    })
    receipt = {
        "schema": "tp-spec.knowledge-search/v1",
        "status": "PASS",
        "scope": "project+shared",
        "query": query,
        "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "count": len(hits),
        "results": hits,
        "matched_canonical_refs": matched,
    }
    errors = validate_receipt_payload("search", receipt)
    if errors:
        raise ValueError("invalid Knowledge search receipt: " + "; ".join(errors))
    return receipt


def _resolve_exact_canonical_note(cfg, knowledge_ref: str) -> Dict[str, Any]:
    """按稳定 ID 在受控 canonical 目录中精确定位一条知识，不扫描整个知识库。"""
    resolved = resolve_knowledge_project(cfg, require=True)
    candidates: List[Path] = []
    project_root = Path(str(resolved.get("project_root") or ""))
    for subdir in CANONICAL_SUBDIRS:
        directory = project_root / subdir
        if directory.is_dir():
            candidates.extend(sorted(directory.glob(f"{knowledge_ref}-*.md")))
    shared_dir = cfg.paths.knowledge_physical_root / str(cfg.knowledge_canonical.get("shared_dir") or "20-shared")
    if shared_dir.is_dir():
        candidates.extend(sorted(shared_dir.glob(f"{knowledge_ref}-*.md")))
    unique = list(dict.fromkeys(path.resolve() for path in candidates if path.is_file()))
    if len(unique) != 1:
        raise ValueError(f"canonical Knowledge ref must resolve to exactly one note: {knowledge_ref}")
    root = cfg.paths.knowledge_physical_root.resolve()
    note = read_note(unique[0], root=root, scope="canonical")
    if str(note.get("id") or "") != knowledge_ref:
        raise ValueError(f"canonical Knowledge ref/id mismatch: {knowledge_ref}")
    return note


def _validate_knowledge_ref(cfg, *, disposition: str, knowledge_ref: str,
                            receipts: List[Dict[str, Any]], task_id: str,
                            source_refs: List[str]) -> Dict[str, Any] | None:
    from cli.delivery_contract import validate_canonical_binding

    matched = {
        ref
        for receipt in receipts
        for ref in (receipt.get("matched_canonical_refs") or [])
        if str(ref or "").strip()
    }
    if disposition == "DUPLICATE":
        if not knowledge_ref or knowledge_ref not in matched:
            raise ValueError("DUPLICATE knowledge-ref must be returned by targeted search")
        return None
    if disposition not in {"CREATED", "UPDATED"}:
        if knowledge_ref:
            raise ValueError(f"{disposition} must not declare knowledge-ref")
        return None
    if not knowledge_ref:
        raise ValueError(f"{disposition} requires --knowledge-ref")
    if disposition == "UPDATED" and knowledge_ref not in matched:
        raise ValueError("UPDATED knowledge-ref must be returned by targeted search")

    note = _resolve_exact_canonical_note(cfg, knowledge_ref)
    lint_receipt = lint_canonical_note(cfg, note)
    if lint_receipt.get("status") != "PASS":
        raise ValueError("canonical Knowledge lint failed: " + json.dumps(lint_receipt.get("violations") or [], ensure_ascii=False))
    errors = validate_canonical_binding(
        note.get("frontmatter") or {},
        task_id=task_id,
        evidence_paths=source_refs,
        source_refs=[],
    )
    if errors:
        raise ValueError("invalid canonical Knowledge binding: " + "; ".join(errors))
    index_receipt = update_canonical_note_projection(cfg, note)
    return {"lint": lint_receipt, "index": index_receipt}


def cmd_task_converge(args) -> int:
    """Execute a typed Task-scoped effect; legacy receipts keep their old contract."""
    if getattr(args, "assessment", None):
        from .convergence_cmd import cmd_converge
        return cmd_converge(args)
    from cli import db as dbmod, event_contract, orchestration, record_first, workflow_records
    from cli.version import active_version

    conn = None
    try:
        task_dir = Path(args.task_dir).resolve()
        if not task_dir.is_dir():
            raise ValueError(f"task directory not found: {task_dir}")
        db_path = dbmod.resolve_db_path(args.db, task_id=args.task)
        conn = dbmod.connect(db_path)
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        if task is None:
            raise ValueError(f"task not found: {args.task}")

        request = _task_convergence_request(conn, args.task, int(args.request_event_id))
        request_detail = dict(request.detail or {})
        if request_detail.get("learning_schema"):
            raise ValueError("Task learning requires --assessment FILE|- with input coverage, Knowledge and Memory")
        if task["current_state"] in record_first.TERMINAL_STATES:
            raise ValueError("legacy terminal task is read-only")
        if not all(getattr(args, field, None) for field in ("disposition", "reason_code", "query", "source")):
            raise ValueError("legacy task-converge requires disposition, reason-code, query and source")
        task_facts, events = orchestration._load_task_facts(args.task, db_path=db_path, connection=conn, task_dir=task_dir)
        orchestration.resolve_route(args.task, db_path=db_path, _facts=(task_facts, events), task_dir=task_dir)
        delivery_event = orchestration._delivery_completion_event(events, task_dir, task=task_facts)
        if delivery_event is None or int(request_detail.get("delivery_event_id") or 0) != int(delivery_event.get("id") or 0):
            raise ValueError("Knowledge convergence request is stale: current READY delivery differs")

        prerequisites = workflow_records._delivery_prerequisites(conn, args.task, task_dir, db_path)
        verification = prerequisites["verification"]
        current_change_set_id = str(prerequisites["snapshot"].get("content_digest") or "")
        if str(request_detail.get("change_set_id") or "") != current_change_set_id:
            raise ValueError("Knowledge convergence request change_set is stale")
        if int(request_detail.get("verification_event_id") or 0) != (int(verification.row["id"]) if verification else 0):
            raise ValueError("Knowledge convergence request verification binding is stale")

        cfg = _cfg(args)
        resolved = resolve_knowledge_project(cfg, require=True)
        if str(resolved.get("project_id") or "") != str(task["project_id"] or ""):
            raise ValueError("Knowledge project scope does not match Runtime task project")

        source_refs, source_items = _task_convergence_sources(task_dir, list(args.source or []))
        request_sources = {str(ref or "").replace("\\", "/").strip() for ref in (request_detail.get("source_refs") or []) if str(ref or "").strip()}
        unbound_sources = sorted(ref for ref in source_refs if ref not in request_sources)
        if unbound_sources:
            raise ValueError("Knowledge source is not bound to the trusted request: " + ", ".join(unbound_sources))
        queries = [str(q or "").strip() for q in (args.query or []) if str(q or "").strip()]
        if not queries:
            raise ValueError("Knowledge convergence requires at least one targeted query")
        receipts = [_search_receipt(cfg, query) for query in queries]
        disposition = str(args.disposition or "").upper()
        knowledge_ref = str(args.knowledge_ref or "").strip()
        canonical_receipt = _validate_knowledge_ref(
            cfg,
            disposition=disposition,
            knowledge_ref=knowledge_ref,
            receipts=receipts,
            task_id=args.task,
            source_refs=source_refs,
        )

        now = dbmod.now_iso()
        flush_id = f"KNOWLEDGE-CONVERGE-{uuid.uuid4().hex}"
        written: Dict[str, Any] = {}

        def writer(dbconn, transaction_id=""):
            detail: Dict[str, Any] = {
                "transaction_id": transaction_id,
                "flush_id": flush_id,
                "schema_version": active_version(),
                "task_id": args.task,
                "actor_role": "tp-knowledge",
                "created_at": now,
                "request_event_id": int(request.row["id"]),
                "change_set_id": current_change_set_id,
                "knowledge_disposition": disposition,
                "query_receipts": receipts,
                "source_refs": source_refs,
                "source_items": source_items,
                "reason_code": str(args.reason_code or "").strip().upper(),
            }
            if knowledge_ref:
                detail["knowledge_ref"] = knowledge_ref
            if canonical_receipt is not None:
                detail["canonical_receipt"] = canonical_receipt
            detail = event_contract.add_event_semantics(
                detail,
                event_type="KNOWLEDGE_CONVERGENCE_RESULT",
                operation="KNOWLEDGE_CONVERGE",
                result_status="COMPLETED",
                producer="knowledge_task_converge",
                reason_code=detail["reason_code"],
            )
            cursor = dbconn.execute(
                "INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,workflow_version,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    args.task, "KNOWLEDGE_CONVERGENCE_RESULT", "delivery", "delivery",
                    "tp-knowledge", detail["reason_code"],
                    f"Knowledge convergence: {disposition}",
                    json.dumps(detail, ensure_ascii=False), active_version(), now,
                ),
            )
            written["event_id"] = int(cursor.lastrowid)
            dbconn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, args.task))

        record_first._write_with_projection(
            conn, task_dir, task,
            operation="knowledge_task_converge",
            target_state=str(task["current_state"] or "ACTIVE"),
            owner_after=str(task["owner_role"] or "tp-integration-engineer"),
            flush_id=flush_id,
            writer=writer,
            summary=f"Knowledge convergence: {disposition}",
        )
        _emit({
            "schema": "tp-spec.knowledge-task-convergence/v1",
            "status": "PASS",
            "task_id": args.task,
            "request_event_id": int(request.row["id"]),
            "result_event_id": written.get("event_id"),
            "change_set_id": current_change_set_id,
            "knowledge_disposition": disposition,
            "knowledge_ref": knowledge_ref or None,
            "canonical_receipt": canonical_receipt,
            "query_receipts": receipts,
            "source_refs": source_refs,
            "reason_code": str(args.reason_code or "").strip().upper(),
        })
        return 0
    except Exception as exc:
        _emit({
            "schema":"tp-spec.knowledge-task-convergence/v1",
            "status":"FAIL",
            "error":f"{type(exc).__name__}: {exc}",
        })
        return 1
    finally:
        if conn is not None:
            conn.close()


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

    from .convergence_cmd import cmd_inputs
    p = sub.add_parser("task-inputs", help="Read-only Task input index and changed/reusable judgment navigation")
    p.add_argument("--task", required=True); p.add_argument("--task-dir", required=True)
    p.add_argument("--db", required=True); p.add_argument("--request-event-id", type=int)
    p.add_argument("--item", help="Read an indexed Task, delivery, event or Work; files retain their source reference")
    p.set_defaults(func=cmd_inputs)
    p = sub.add_parser("task-converge", help="Record assessed Task inputs, targeted Knowledge results and Memory readback")
    _common(p)
    p.add_argument("--task", required=True); p.add_argument("--task-dir", required=True)
    p.add_argument("--db", required=True); p.add_argument("--request-event-id", required=True, type=int)
    p.add_argument("--assessment", help="Task learning JSON file, or - for stdin; required for new requests")
    p.add_argument("--disposition", choices=["CREATED", "UPDATED", "DUPLICATE", "NO_DURABLE_INSIGHT"])
    p.add_argument("--reason-code"); p.add_argument("--query", action="append")
    p.add_argument("--source", action="append"); p.add_argument("--knowledge-ref")
    p.set_defaults(func=cmd_task_converge)

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
