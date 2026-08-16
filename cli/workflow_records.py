from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .delivery_contract import delivery_result_matches_verification, validate_canonical_binding, validate_delivery_result, validate_receipt_payload


def build_confirmation_detail(*, task_id: str, binding: Dict[str, Any], transaction_id: str,
                              flush_id: str, created_at: str, schema_version: str) -> Dict[str, Any]:
    return {
        'operation': 'WORKFLOW_CONFIRM',
        'flush_id': flush_id,
        'transaction_id': transaction_id,
        'producer': 'workflow_confirm',
        'schema_version': schema_version,
        'task_id': task_id,
        'actor_role': 'human_owner',
        'created_at': created_at,
        **binding,
    }


def build_delivery_detail(*, task_id: str, transaction_id: str, flush_id: str,
                          created_at: str, schema_version: str,
                          verification_event_id: int, verification_subject_digest: str,
                          knowledge_disposition: str, reason: str,
                          knowledge_refs: Optional[Iterable[str]] = None,
                          search_receipts: Optional[Iterable[Dict[str, Any]]] = None,
                          lint_receipts: Optional[Iterable[Dict[str, Any]]] = None,
                          index_receipts: Optional[Iterable[Dict[str, Any]]] = None,
                          evidence: Optional[Iterable[str]] = None,
                          source_refs: Optional[Iterable[str]] = None,
                          recovery_condition: Optional[str] = None,
                          blocker_kind: Optional[str] = None,
                          responsibility: Optional[str] = None,
                          residual_risks: Optional[Iterable[str]] = None,
                          evidence_items: Optional[Iterable[Dict[str, Any]]] = None,
                          context_usage: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        'operation': 'DELIVERY_CONVERGE',
        'flush_id': flush_id,
        'transaction_id': transaction_id,
        'producer': 'delivery_converge',
        'schema_version': schema_version,
        'task_id': task_id,
        'actor_role': 'tp-delivery-convergence',
        'created_at': created_at,
        'verification_event_id': int(verification_event_id),
        'verification_subject_digest': str(verification_subject_digest),
        'knowledge_disposition': str(knowledge_disposition or '').upper(),
        'reason': str(reason or '').strip(),
    }
    optional_lists = {
        'knowledge_refs': knowledge_refs,
        'search_receipts': search_receipts,
        'lint_receipts': lint_receipts,
        'index_receipts': index_receipts,
        'evidence': evidence,
        'source_refs': source_refs,
        'residual_risks': residual_risks,
        'evidence_items': evidence_items,
        'context_usage': context_usage,
    }
    for key, values in optional_lists.items():
        items = list(values or [])
        if items:
            detail[key] = items
    if str(recovery_condition or '').strip():
        detail['recovery_condition'] = str(recovery_condition).strip()
    if str(blocker_kind or '').strip():
        detail['blocker_kind'] = str(blocker_kind).strip().upper()
    if str(responsibility or '').strip():
        detail['responsibility'] = str(responsibility).strip()
    errors = validate_delivery_result(detail)
    if errors:
        raise ValueError('invalid delivery result: ' + '; '.join(errors))
    return detail


def _checked_evidence_items(task_dir: Path, values: Optional[Iterable[str]]) -> tuple[list[str], list[Dict[str, Any]]]:
    from .evidence import validate_evidence_path

    paths: list[str] = []
    items: list[Dict[str, Any]] = []
    for raw in values or []:
        checked = validate_evidence_path(task_dir, raw, require_evidence_dir=True)
        if not checked.ok:
            raise ValueError(f'delivery evidence invalid: {checked.error}')
        paths.append(str(checked.item['path']))
        items.append(dict(checked.item))
    return paths, items


def _knowledge_context(workspace_root: Path):
    from .content_systems import load_content_systems
    from .knowledge.common import resolve_knowledge_project

    cfg = load_content_systems(workspace_root)
    resolved = resolve_knowledge_project(cfg, require=True)
    if not resolved.get('resolved'):
        raise ValueError('Knowledge Resolver did not resolve the current project')
    return cfg, resolved


def _run_targeted_search(cfg, queries: list[str]) -> list[Dict[str, Any]]:
    from .knowledge.projection import search

    normalized = []
    for raw in queries:
        value = str(raw or '').strip()
        if value and value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError('successful Delivery convergence requires at least one --knowledge-query')
    if len(normalized) > 3:
        raise ValueError('Delivery targeted Knowledge search is limited to 3 focused queries')
    receipts: list[Dict[str, Any]] = []
    retrieval = cfg.knowledge_retrieval
    original_global_fallback = retrieval.get('global_fallback', False)
    retrieval['global_fallback'] = False
    try:
        for query in normalized:
            hits = search(cfg, query, scope='project', limit=5, record_telemetry=True)
            compact = []
            for hit in hits:
                compact.append({
                    key: hit.get(key) for key in ('id', 'path', 'project', 'kind', 'layer', 'source_refs')
                    if hit.get(key) not in (None, '', [])
                })
            receipts.append({
                'schema': 'tp-spec.knowledge-search/v1',
                'status': 'PASS',
                'scope': 'project',
                'scope_semantics': 'current project + shared',
                'query': query,
                'query_hash': hashlib.sha256(query.encode('utf-8')).hexdigest(),
                'count': len(hits),
                'results': compact,
            })
    finally:
        retrieval['global_fallback'] = original_global_fallback
    for receipt in receipts:
        errors = validate_receipt_payload('search', receipt)
        if errors:
            raise ValueError('internal targeted search receipt invalid: ' + '; '.join(errors))
    return receipts


def _run_targeted_knowledge_quality(cfg, resolved_refs: list[Dict[str, str]]) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Lint and index only the exact canonical notes changed by this Delivery.

    The standalone tp-knowledge maintenance path may still run full-vault lint/index.
    Delivery must not pay that global scan cost merely to close one Task.
    """
    from .knowledge.common import load_source_registry, now_iso, parse_frontmatter, read_note
    try:
        import jsonschema  # noqa: F401 -- fail closed if schema validation dependency is missing
    except ImportError as exc:
        raise ValueError('jsonschema is required for targeted canonical lint') from exc
    from .knowledge.lint import _schema_errors
    from .knowledge.projection import _connect, _insert_doc

    root = cfg.paths.knowledge_physical_root.resolve(strict=False)
    lint_issues: list[str] = []
    checked: list[str] = []
    for item in resolved_refs:
        rel = str(item.get('path') or '')
        path = (root / rel).resolve(strict=False)
        fm, _body, parse_error, _line = parse_frontmatter(path.read_text(encoding='utf-8-sig'))
        if parse_error or not isinstance(fm, dict):
            lint_issues.append(f'{rel}: {parse_error or "frontmatter missing"}')
            continue
        for location, message in _schema_errors(fm):
            lint_issues.append(f'{rel}:{location}: {message}')
        checked.append(rel)
    if lint_issues:
        raise ValueError('targeted canonical lint failed: ' + '; '.join(lint_issues[:20]))
    lint_receipt = {
        'schema': 'tp-spec.knowledge-lint/v1',
        'status': 'PASS',
        'mode': 'delivery-exact-canonical',
        'checked_refs': checked,
        'errors': 0,
    }

    db = cfg.paths.knowledge_projection_db
    if not db.is_file():
        raise ValueError('Knowledge projection database missing; run knowledge index build before CREATED/UPDATED delivery convergence')
    registry = load_source_registry(cfg)
    conn = _connect(db)
    updated: list[Dict[str, str]] = []
    try:
        graph_mode = str(cfg.knowledge_projection.get('graph_mode') or 'optional')
        for item in resolved_refs:
            rel = str(item.get('path') or '')
            path = (root / rel).resolve(strict=False)
            note = read_note(path, root=root, scope='canonical')
            old = conn.execute('SELECT id,canonical_id FROM documents WHERE rel_path=?', (rel,)).fetchone()
            new_id = str((note.get('frontmatter') or {}).get('id') or '')
            duplicate = conn.execute(
                "SELECT rel_path FROM documents WHERE canonical_id=? AND rel_path<>? LIMIT 1", (new_id, rel)
            ).fetchone() if new_id else None
            if duplicate is not None:
                raise ValueError(f'canonical stable ID conflicts with existing indexed note: {new_id} -> {duplicate[0]}')
            if old is not None and str(old[1] or '') and str(old[1] or '') != new_id:
                raise ValueError(f'canonical stable ID changed at {rel}; use explicit Knowledge migration instead of Delivery convergence')
            if old is not None:
                doc_id = int(old[0])
                for (chunk_id,) in conn.execute('SELECT id FROM chunks WHERE doc_id=?', (doc_id,)).fetchall():
                    conn.execute('DELETE FROM fts_chunks WHERE rowid=?', (chunk_id,))
                conn.execute('DELETE FROM doc_links WHERE doc_id=?', (doc_id,))
                conn.execute('DELETE FROM chunks WHERE doc_id=?', (doc_id,))
                conn.execute('DELETE FROM documents WHERE id=?', (doc_id,))
            _insert_doc(conn, note, registry)

            fm = note.get('frontmatter') or {}
            cid = str(fm.get('id') or '')
            if cid:
                conn.execute('DELETE FROM graph_edges WHERE source_canonical_id=?', (cid,))
                conn.execute('DELETE FROM graph_nodes WHERE canonical_id=?', (cid,))
                if graph_mode != 'disabled':
                    try:
                        confidence = float(fm.get('confidence', 0) or 0)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    source_values = [str(x) for x in fm.get('source_refs') or []]
                    conn.execute(
                        'INSERT INTO graph_nodes(canonical_id,kind,title,project,status,layer,rel_path,source_refs,confidence,last_verified) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (cid, str(fm.get('kind') or ''), str(fm.get('title') or ''), str(fm.get('project') or ''),
                         str(fm.get('status') or 'active'), 'canonical', rel,
                         json.dumps(source_values, ensure_ascii=False), confidence, str(fm.get('last_verified') or '')),
                    )
                    for relation in fm.get('relations') or []:
                        if not isinstance(relation, dict) or not relation.get('type') or not relation.get('target'):
                            continue
                        relation_type = str(relation['type'])
                        target = str(relation['target'])
                        edge_id = 'E-' + hashlib.sha256(f'{cid}|{relation_type}|{target}'.encode()).hexdigest()[:24]
                        conn.execute(
                            'INSERT OR REPLACE INTO graph_edges(edge_id,source_canonical_id,target_id,relation_type,evidence_source_ids,origin,reason) '
                            'VALUES(?,?,?,?,?,?,?)',
                            (edge_id, cid, target, relation_type, json.dumps(source_values, ensure_ascii=False),
                             'canonical', str(relation.get('note') or '')),
                        )
                    for source_ref in source_values:
                        edge_id = 'E-' + hashlib.sha256(f'{cid}|source_refs|{source_ref}'.encode()).hexdigest()[:24]
                        conn.execute(
                            'INSERT OR REPLACE INTO graph_edges(edge_id,source_canonical_id,target_id,relation_type,evidence_source_ids,origin) '
                            'VALUES(?,?,?,?,?,?)',
                            (edge_id, cid, source_ref, 'source_refs', json.dumps([source_ref], ensure_ascii=False), 'canonical'),
                        )
            updated.append({'path': rel, 'id': cid, 'sha256': str(note.get('sha256') or '')})
        # Keep projection metadata self-consistent from indexed document rows only;
        # no Knowledge file traversal is needed for this Delivery-local update.
        subject_map = {
            str(row[0]): str(row[1])
            for row in conn.execute('SELECT rel_path,sha256 FROM documents ORDER BY rel_path').fetchall()
        }
        indexed_subject = hashlib.sha256(
            json.dumps(subject_map, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('projection_subject',?)", (indexed_subject,))
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('last_update',?)", (now_iso(),))
        conn.commit()
        for expected in updated:
            row = conn.execute(
                'SELECT canonical_id,sha256,scope FROM documents WHERE rel_path=?', (expected['path'],)
            ).fetchone()
            if row is None or str(row[0] or '') != expected['id'] or str(row[1] or '') != expected['sha256'] or str(row[2] or '') != 'canonical':
                raise ValueError(f"targeted Knowledge index verification failed: {expected['path']}")
    finally:
        conn.close()
    index_receipt = {
        'status': 'PASS',
        'fresh': True,
        'scope': 'exact-canonical',
        'updated_refs': updated,
        'global_projection_scan_performed': False,
    }
    for kind, receipt in (('lint', lint_receipt), ('index', index_receipt)):
        errors = validate_receipt_payload(kind, receipt)
        if errors:
            raise ValueError(f'internal targeted {kind} receipt invalid: ' + '; '.join(errors))
    return [lint_receipt], [index_receipt]


def _resolve_and_validate_canonical_refs(*, cfg, resolved_project: Dict[str, Any], task_id: str,
                                         knowledge_refs: list[str], evidence_paths: list[str],
                                         source_refs: list[str], search_receipts: list[Dict[str, Any]]) -> list[Dict[str, str]]:
    """Resolve only explicitly named canonical refs; never scan the whole Knowledge vault."""
    from .knowledge.common import ID_PATTERN, parse_frontmatter

    project_id = str(resolved_project.get('project_id') or '')
    root = cfg.paths.knowledge_physical_root.resolve(strict=False)
    projects_dir = str(cfg.knowledge_canonical.get('projects_dir') or '10-projects').strip('/\\')
    shared_dir = str(cfg.knowledge_canonical.get('shared_dir') or '20-shared').strip('/\\')
    result_paths: Dict[str, str] = {}
    for payload in search_receipts:
        for item in payload.get('results') or []:
            if isinstance(item, dict) and item.get('id') and item.get('path'):
                result_paths[str(item['id'])] = str(item['path'])

    resolved_refs: list[Dict[str, str]] = []
    for raw in knowledge_refs:
        ref = str(raw or '').strip()
        rel = result_paths.get(ref, ref)
        if ref not in result_paths and ID_PATTERN.match(ref):
            # A newly CREATED canonical may not exist in the old FTS projection yet.
            # Resolve only the exact stable-ID filename prefix inside the current
            # project + shared roots; do not read or semantically scan unrelated notes.
            candidates = []
            project_root = root / projects_dir / project_id if project_id else None
            if project_root and project_root.is_dir():
                candidates.extend(project_root.glob(f'*/{ref}-*.md'))
            shared_root = root / shared_dir
            if shared_root.is_dir():
                candidates.extend(shared_root.rglob(f'{ref}-*.md'))
            unique = sorted({p.resolve(strict=False) for p in candidates if p.is_file()})
            if len(unique) != 1:
                raise ValueError(f'stable canonical ID must resolve to exactly one current project/shared note: {ref}; matches={len(unique)}')
            rel = unique[0].relative_to(root).as_posix()
        rel_norm = rel.replace('\\', '/').lstrip('/')
        if ':' in rel_norm[:3] or rel_norm.startswith('../') or '/..' in rel_norm:
            raise ValueError(f'knowledge ref must be a Knowledge-root relative path or targeted-search stable ID: {ref}')
        allowed_project = bool(project_id and rel_norm.startswith(f'{projects_dir}/{project_id}/'))
        allowed_shared = rel_norm == shared_dir or rel_norm.startswith(shared_dir + '/')
        if not (allowed_project or allowed_shared):
            raise ValueError(f'knowledge ref is outside current project + shared scope: {ref}')
        path = (root / rel_norm).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f'knowledge ref escapes Knowledge root: {ref}') from exc
        if not path.is_file():
            raise ValueError(f'canonical Knowledge ref not found: {ref} -> {rel_norm}')
        fm, _body, parse_error, _line = parse_frontmatter(path.read_text(encoding='utf-8-sig'))
        if parse_error or not isinstance(fm, dict):
            raise ValueError(f'canonical Knowledge frontmatter invalid: {rel_norm}: {parse_error or "missing mapping"}')
        if allowed_project and str(fm.get('project') or '') != project_id:
            raise ValueError(f'canonical Knowledge project mismatch: {rel_norm}: expected {project_id}, found {fm.get("project")!r}')
        if allowed_shared:
            shared_ids = {str(v) for v in (resolved_project.get('shared_ids') or []) if str(v)}
            if str(fm.get('project') or '') not in shared_ids:
                raise ValueError(f'shared canonical is not in a resolved shared scope: {rel_norm}: project={fm.get("project")!r}')
        errors = validate_canonical_binding(
            fm, task_id=task_id, evidence_paths=evidence_paths, source_refs=source_refs,
        )
        if errors:
            raise ValueError(f'canonical Knowledge binding invalid: {rel_norm}: ' + '; '.join(errors))
        stable_id = str(fm.get('id') or '').strip()
        if ID_PATTERN.match(ref) and stable_id != ref:
            raise ValueError(f'canonical stable ID mismatch: requested {ref}, canonical declares {stable_id or "<missing>"}')
        resolved_refs.append({'ref': ref, 'path': rel_norm, 'id': stable_id})
    return resolved_refs


def _latest_trusted_verification(conn, task_id: str, task_dir: Path):
    from . import event_policies
    from .digest import compute_verification_subject_digest

    current_subject = compute_verification_subject_digest(task_dir)
    trusted = event_policies.load_trusted_governance_event(
        conn,
        task_id,
        event_type='VERIFICATION_COMPLETED',
        actor='tp-verification-engineering',
        decision='PASS',
        expected_subject_digest=current_subject,
        evidence_dir=task_dir,
    )
    if trusted is None:
        raise ValueError('DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS')
    return trusted, current_subject


def confirm_boundary(*, task_id: str, task_dir: str, db: Optional[str] = None,
                     confirmation_policy: Optional[str] = None) -> Dict[str, Any]:
    from . import db as dbmod
    from . import orchestration, record_first
    from .version import active_version

    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    route = orchestration.resolve_route(task_id, db_path=db_path, confirmation_policy=confirmation_policy)
    autonomy_pending = None
    if route.get('recommended_action') != 'await_confirmation':
        try:
            from . import autonomy_records
            autonomy_pending = autonomy_records.pending_workflow_confirmation_any(task_id, db_path)
        except Exception:
            autonomy_pending = None
    if autonomy_pending:
        confirmation_reason = str(autonomy_pending.get('confirmation_reason') or '')
        binding = autonomy_pending.get('confirmation_binding')
    else:
        confirmation_reason = str(route.get('confirmation_reason') or '')
        binding = route.get('confirmation_binding')
    if confirmation_reason not in {'EACH_STAGE_POLICY', 'MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION'}:
        raise ValueError('workflow confirm requires an active bound ordinary/material workflow confirmation')
    if not isinstance(binding, dict) or not binding:
        raise ValueError('workflow confirmation binding missing')

    tdir = record_first._task_dir(task_dir)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task['current_state'] or '')
        if current in record_first.TERMINAL_STATES:
            raise ValueError(f'terminal task cannot accept workflow confirmation: {current}')
        if current == 'BLOCKED' and not autonomy_pending:
            raise ValueError("task is BLOCKED; use 'task resume' after the blocker is resolved")
        now = dbmod.now_iso()
        flush_id = f'WF-CONFIRM-{uuid.uuid4().hex}'
        owner = str(task['owner_role'] or '')

        def writer(dbconn, transaction_id=''):
            detail = build_confirmation_detail(
                task_id=task_id, binding=binding, transaction_id=transaction_id,
                flush_id=flush_id, created_at=now, schema_version=active_version(),
            )
            if autonomy_pending:
                detail['autonomy_next_cycle_effective'] = True
                detail['autonomy_blocked_generation'] = autonomy_pending.get('generation')
            kind = str(binding.get('confirmation_kind') or 'ordinary')
            dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (task_id, 'WORKFLOW_CONFIRMATION', 'human_owner', confirmation_reason,
                 f"confirmed {kind} role boundary {binding['source_role']} -> {binding['target_role']}",
                 json.dumps(detail, ensure_ascii=False), active_version(), now),
            )
            dbconn.execute('UPDATE task SET updated_at=? WHERE task_id=?', (now, task_id))

        record_first._write_with_projection(
            conn, tdir, task, operation='workflow_confirm', target_state=current,
            owner_after=owner, flush_id=flush_id, writer=writer,
            summary=f"confirmed {binding.get('confirmation_kind', 'ordinary')} role boundary {binding['source_role']} -> {binding['target_role']}",
        )
    finally:
        conn.close()

    if autonomy_pending:
        return {
            'schema': 'tp-spec.workflow-route/v1', 'task_id': task_id,
            'recommended_action': 'next_cycle_resume', 'next_cycle_effective': True,
            'confirmation_reason': confirmation_reason, 'confirmation_binding': binding,
            'decision_schema': 'tp-spec.workflow-decision/v1', 'decision': 'AWAIT_NEXT_CYCLE',
            'requires_human': False, 'required_effects': [], 'reason': 'confirmed_next_cycle',
        }
    resolved = orchestration.resolve_route(task_id, db_path=db_path, confirmation_policy=confirmation_policy)
    if resolved.get('recommended_action') != 'dispatch_role':
        raise ValueError('workflow confirmation was recorded but current route no longer dispatches; re-run workflow next')
    return resolved

def record_delivery_result(*, task_id: str, task_dir: str, knowledge_disposition: str,
                           reason: str, knowledge_refs: Optional[Iterable[str]] = None,
                           knowledge_queries: Optional[Iterable[str]] = None,
                           evidence: Optional[Iterable[str]] = None,
                           source_refs: Optional[Iterable[str]] = None,
                           recovery_condition: Optional[str] = None,
                           blocker_kind: Optional[str] = None,
                           responsibility: Optional[str] = None,
                           residual_risks: Optional[Iterable[str]] = None,
                           context_usage: Optional[Iterable[Dict[str, Any]]] = None,
                           db: Optional[str] = None) -> Dict[str, Any]:
    from . import db as dbmod
    from . import record_first
    from . import context_usage as context_usage_mod
    from .version import active_version

    caller_usage, caller_warnings = context_usage_mod.normalize_context_usage(context_usage)
    context_usage_mod.emit_warnings(caller_warnings)
    tdir = record_first._task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task['current_state'] or '')
        if current in record_first.TERMINAL_STATES:
            raise ValueError(f'terminal task cannot accept delivery result: {current}')
        if current == 'BLOCKED':
            raise ValueError('task is BLOCKED; resolve the blocker before delivery convergence')
        effective_level = max(
            str(task['risk_level'] or 'L0'), str(task['flow_level'] or 'L0'),
            key=lambda value: ('L0', 'L1', 'L2', 'L3').index(value) if value in ('L0', 'L1', 'L2', 'L3') else -1,
        )
        if effective_level not in {'L2', 'L3'}:
            raise ValueError('structured delivery convergence applies only to L2/L3 tasks')

        verification, subject_digest = _latest_trusted_verification(conn, task_id, tdir)
        evidence_paths, evidence_items = _checked_evidence_items(tdir, evidence)
        knowledge_ref_list = list(knowledge_refs or [])
        source_ref_list = list(source_refs or [])
        disposition = str(knowledge_disposition or '').upper()
        search_receipts: list[Dict[str, Any]] = []
        lint_receipts: list[Dict[str, Any]] = []
        index_receipts: list[Dict[str, Any]] = []
        resolved_knowledge_refs: list[Dict[str, str]] = []
        if disposition in {'CREATED', 'UPDATED', 'NO_CHANGE'}:
            project = conn.execute('SELECT root_path FROM project WHERE project_id=?', (task['project_id'],)).fetchone()
            workspace_text = str(project['root_path'] or '').strip() if project is not None else ''
            if not workspace_text:
                raise ValueError('current project workspace root is unavailable for Knowledge Resolver')
            cfg, resolved_project = _knowledge_context(Path(workspace_text))
            search_receipts = _run_targeted_search(cfg, list(knowledge_queries or []))
            if disposition in {'CREATED', 'UPDATED'}:
                resolved_knowledge_refs = _resolve_and_validate_canonical_refs(
                    cfg=cfg, resolved_project=resolved_project, task_id=task_id, knowledge_refs=knowledge_ref_list,
                    evidence_paths=evidence_paths, source_refs=source_ref_list, search_receipts=search_receipts,
                )
                lint_receipts, index_receipts = _run_targeted_knowledge_quality(cfg, resolved_knowledge_refs)
        try:
            automatic_usage = context_usage_mod.knowledge_usage_from_delivery(
                search_receipts,
                resolved_knowledge_refs,
            )
        except Exception as exc:
            context_usage_mod.emit_warnings([f"automatic Delivery Knowledge telemetry dropped: {exc}"])
            automatic_usage = []
        combined_usage = context_usage_mod.merge_context_usage(caller_usage, automatic_usage)

        now = dbmod.now_iso()
        flush_id = f'DELIVERY-{uuid.uuid4().hex}'
        detail_args = dict(
            task_id=task_id,
            flush_id=flush_id,
            created_at=now,
            schema_version=active_version(),
            verification_event_id=int(verification.row['id']),
            verification_subject_digest=subject_digest,
            knowledge_disposition=knowledge_disposition,
            reason=reason,
            knowledge_refs=knowledge_ref_list,
            search_receipts=search_receipts,
            lint_receipts=lint_receipts,
            index_receipts=index_receipts,
            evidence=evidence_paths,
            source_refs=source_ref_list,
            recovery_condition=recovery_condition,
            blocker_kind=blocker_kind,
            responsibility=responsibility,
            residual_risks=list(residual_risks or []),
            evidence_items=evidence_items,
            context_usage=combined_usage,
        )

        def writer(dbconn, transaction_id=''):
            detail = build_delivery_detail(transaction_id=transaction_id, **detail_args)
            if resolved_knowledge_refs:
                detail['resolved_knowledge_refs'] = resolved_knowledge_refs
            dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,evidence_path,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (task_id, 'DELIVERY_RESULT', task['current_stage'], 'delivery', 'tp-delivery-convergence',
                 str(detail['knowledge_disposition']),
                 f"delivery knowledge disposition: {detail['knowledge_disposition']} — {detail['reason']}",
                 json.dumps(detail, ensure_ascii=False),
                 (detail.get('evidence') or [None])[0],
                 active_version(), now),
            )
            dbconn.execute(
                "UPDATE task SET current_state='ACTIVE', current_stage='delivery', owner_role='tp-delivery-convergence', updated_at=? WHERE task_id=?",
                (now, task_id),
            )

        record_first._write_with_projection(
            conn, tdir, task, operation='delivery_converge', target_state='ACTIVE',
            owner_after='tp-delivery-convergence', flush_id=flush_id, writer=writer,
            summary=f'delivery knowledge disposition: {str(knowledge_disposition).upper()}',
        )
        return {
            'task_id': task_id,
            'state': 'ACTIVE',
            'phase': 'delivery',
            'knowledge_disposition': str(knowledge_disposition).upper(),
            'verification_event_id': int(verification.row['id']),
            'verification_subject_digest': subject_digest,
            'flush_id': flush_id,
        }
    finally:
        conn.close()


def accept_delivery_deferred(*, task_id: str, task_dir: str, reason: str,
                             db: Optional[str] = None) -> Dict[str, Any]:
    from . import db as dbmod
    from . import record_first
    from .version import active_version
    from .workflow_controls import event_digest

    if len(str(reason or '').strip()) < 8:
        raise ValueError('deferred acceptance requires a concrete human_owner reason')
    tdir = record_first._task_dir(task_dir)
    db_path = dbmod.resolve_db_path(db, task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = record_first._load(conn, task_id)
        current = str(task['current_state'] or '')
        if current in record_first.TERMINAL_STATES:
            raise ValueError(f'terminal task cannot accept delivery deferral: {current}')
        row = conn.execute(
            "SELECT * FROM task_event WHERE task_id=? AND event_type='DELIVERY_RESULT' AND actor_role='tp-delivery-convergence' ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError('no delivery result exists to defer')
        from .workflow_controls import trusted_event_detail
        delivery_event = dict(row)
        delivery_detail = trusted_event_detail(
            delivery_event, event_type='DELIVERY_RESULT', producer='delivery_converge',
            actor='tp-delivery-convergence',
        )
        if delivery_detail is None or validate_delivery_result(delivery_detail):
            raise ValueError('latest delivery result is not trusted/valid')
        if str(delivery_detail.get('knowledge_disposition') or '').upper() != 'DEFERRED':
            raise ValueError('only DEFERRED delivery result can be accepted')
        verification, subject_digest = _latest_trusted_verification(conn, task_id, tdir)
        if not delivery_result_matches_verification(delivery_detail, int(verification.row['id']), subject_digest):
            raise ValueError('latest DEFERRED delivery result is stale against the current Verification PASS')
        delivery_digest = event_digest(delivery_event)
        now = dbmod.now_iso()
        flush_id = f'DELIVERY-DEFER-{uuid.uuid4().hex}'
        owner = str(task['owner_role'] or '')

        def writer(dbconn, transaction_id=''):
            detail = {
                'operation': 'DELIVERY_DEFERRED_ACCEPT',
                'flush_id': flush_id,
                'transaction_id': transaction_id,
                'producer': 'delivery_deferred_accept',
                'schema_version': active_version(),
                'task_id': task_id,
                'actor_role': 'human_owner',
                'created_at': now,
                'delivery_event_id': int(row['id']),
                'delivery_event_digest': delivery_digest,
                'reason': str(reason).strip(),
            }
            dbconn.execute(
                'INSERT INTO task_event (task_id,event_type,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (task_id, 'DELIVERY_DEFERRED_ACCEPTED', 'human_owner', 'DEFERRED_ACCEPTED',
                 'human_owner accepted deferred Knowledge convergence', json.dumps(detail, ensure_ascii=False),
                 active_version(), now),
            )
            dbconn.execute('UPDATE task SET updated_at=? WHERE task_id=?', (now, task_id))

        record_first._write_with_projection(
            conn, tdir, task, operation='delivery_deferred_accept', target_state=current,
            owner_after=owner, flush_id=flush_id, writer=writer,
            summary='human_owner accepted deferred Knowledge convergence',
        )
        return {'task_id': task_id, 'delivery_event_id': int(row['id']), 'accepted': True, 'flush_id': flush_id}
    finally:
        conn.close()
