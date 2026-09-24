"""Knowledge-only read presentation over registered projections and trusted Runtime facts.

No index build/status scan, migration, maintenance, cleanup or telemetry writer is
called by this module. Content is paginated in SQLite; result receipts are loaded
only when a record is expanded. Request project and content scope stay separate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sqlite3
from urllib.parse import unquote, urlsplit

from cli import context_effectiveness
from cli.content_systems import load_content_systems
from cli.path_identity import path_identity_key
from cli.knowledge import documents, reading, telemetry
from cli.knowledge.common import meta_paths, read_json, read_jsonl, resolve_knowledge_project


_TIME_MIN = datetime.min.replace(tzinfo=timezone.utc)
_UTC_PLUS_8 = timezone(timedelta(hours=8))


def _date(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _utc_plus_8_date(value):
    moment = _date(value)
    return moment.astimezone(_UTC_PLUS_8).date() if moment else None


def _latest(values):
    moments = [moment for value in values if (moment := _date(value)) is not None]
    return max(moments).isoformat() if moments else None


def _first(values):
    moments = [moment for value in values if (moment := _date(value)) is not None]
    return min(moments).isoformat() if moments else None


def _json(raw, default):
    try:
        value = json.loads(raw or "null")
        return value if isinstance(value, type(default)) else default
    except (TypeError, ValueError):
        return default


def _db_identity(path):
    return hashlib.sha256(path_identity_key(path).encode("utf-8")).hexdigest()[:24]


def _number(value, complete):
    return value if complete or value else None


class KnowledgeView:
    def __init__(self, service, contexts, issues, *, days=30, project="", purpose="development"):
        self.service, self.days, self.selected, self.purpose = service, days, project, purpose
        self.until = datetime.now(timezone.utc)
        self.since = self.until - timedelta(days=days)
        # Registry parser exceptions may contain configuration fragments. Publish
        # capability gaps, not raw local configuration/exception text.
        self.problems = [{"code": row.get("code", "KNOWLEDGE_CONTEXT_UNAVAILABLE"),
                          "message": "重复项目注册已按解析身份去重。" if row.get("code") == "CONTEXT_DUPLICATE"
                                     else "项目注册上下文未完整取得；缺失来源未被推测或初始化。"}
                         for row in issues]
        self.sources, self.stores, self.projects, self.context_scopes = {}, {}, {}, {}
        self.source_failures = [str(row.get("code") or "未知注册上下文") for row in issues if row.get("code") != "CONTEXT_DUPLICATE"]
        self.events, self.reads, self.usage, self.historical = [], [], [], []
        self.collections, self.runtime_available, self.runtime_failed = {}, set(), set()
        self.runtime_sources, self.document_cache, self.asset_cache = [], {}, {}
        self._load_sources(contexts)
        if project and project not in self.projects:
            from .service import ReadError
            raise ReadError("KNOWLEDGE_PROJECT_NOT_FOUND", "知识范围不存在或注册已变化", 404)
        self._load_telemetry()
        self._load_usage(contexts)

    def problem(self, code, name=""):
        # Never leak config contents, query text or exception messages through HTTP logs/errors.
        self.problems.append({"code": code, "message": (name + "：" if name else "") + {
            "KNOWLEDGE_SOURCE_UNAVAILABLE": "知识来源不可读；没有初始化或修复来源。",
            "KNOWLEDGE_INDEX_UNAVAILABLE": "索引不存在、不可读或不兼容；请显式执行 knowledge index build/update。",
            "KNOWLEDGE_LOG_UNAVAILABLE": "检索/读取日志不可用，不代表零使用。",
            "KNOWLEDGE_RUNTIME_UNAVAILABLE": "可信任务记录不可读，不代表未采用。",
            "KNOWLEDGE_SEARCH_UNAVAILABLE": "所选范围的查询执行失败，不能作为成功的零结果。",
            "KNOWLEDGE_MULTIPLE_INDEXES": "同一知识来源注册了多个投影；内容只使用一个索引，已知日志按数据库与回执去重。",
            "KNOWLEDGE_RUNTIME_SCOPE_AMBIGUOUS": "同一 Runtime 项目存在冲突的知识范围，未猜测采用归属。",
            "KNOWLEDGE_MAINTENANCE_UNREADABLE": "已有维护报告或来源登记不可读；页面未运行维护。",
        }.get(code, code)})

    def _load_sources(self, contexts):
        for context in contexts:
            try:
                self.service._context(context.context_key)
                cfg = load_content_systems(context.workspace_root)
                catalog = documents.scopes(cfg)
                source = documents.source_identity(cfg)
                db_key = _db_identity(cfg.paths.knowledge_projection_db)
                entry = {"cfg": cfg, "source_id": source, "db_key": db_key, "catalog": catalog}
                old = self.sources.get(source)
                if old and old["db_key"] != db_key:
                    self.problem("KNOWLEDGE_MULTIPLE_INDEXES", source)
                if old is None or (not old["cfg"].paths.knowledge_projection_db.is_file() and cfg.paths.knowledge_projection_db.is_file()):
                    self.sources[source] = entry
                # The same resolved projection is never counted once per workspace.
                if db_key in self.stores and self.stores[db_key]["source_id"] != source:
                    raise telemetry.KnowledgeError("KNOWLEDGE_PROJECTION_SOURCE_CONFLICT")
                self.stores.setdefault(db_key, entry)
                for row in catalog:
                    key = source + ":" + row["id"]
                    self.projects[key] = {**row, "key": key, "source_id": source,
                                          "name": ("共享 · " if row["shared"] else "") + row["name"]}
                resolved = resolve_knowledge_project(cfg, require=False)
                if resolved.get("resolved"):
                    self.context_scopes[context.context_key] = source + ":" + resolved["project_id"]
            except Exception:
                self.source_failures.append(context.name)
                self.problem("KNOWLEDGE_SOURCE_UNAVAILABLE", context.name)

    def _source_selected(self, source):
        return not self.selected or self.projects[self.selected]["source_id"] == source

    def _in_window(self, value):
        stamp = _date(value)
        return stamp is not None and self.since <= stamp <= self.until

    def _requested(self, row, source):
        project = str(row.get("requested_project") or "")
        key = source + ":" + project if project else ""
        return key, self.projects.get(key, {}).get("name") or ("显式全局范围" if row.get("request_scope") == "global" else "历史未归因")

    def _selected_event(self, row, source):
        key, _ = self._requested(row, source)
        if self.selected and self.projects[self.selected]["shared"]:
            if source != self.projects[self.selected]["source_id"]:
                return False
            actual = row.get("returned_projects") or []
            actual = _json(actual, []) if isinstance(actual, str) else actual
            return self.projects[self.selected]["id"] in actual or key == self.selected
        return not self.selected or key == self.selected

    def _load_telemetry(self):
        seen_receipts = set()
        for db_key, entry in self.stores.items():
            source, cfg = entry["source_id"], entry["cfg"]
            if not self._source_selected(source):
                continue
            report = {"source_id": source, "database_id": db_key, "status": "missing",
                      "retention_days": telemetry.retention_days(cfg), "started_at": None,
                      "earliest_retained_at": None, "latest_retained_at": None, "coverage_start": None}
            self.collections[db_key] = report
            if not cfg.paths.knowledge_projection_db.is_file():
                continue
            try:
                with telemetry.connect_readonly(cfg.paths.knowledge_projection_db) as conn:
                    fields = telemetry.columns(conn, "retrieval_runs")
                    if not fields:
                        report["status"] = "not_collected"
                        continue
                    modern = telemetry.ready(conn)
                    meta = dict(conn.execute("SELECT key,value FROM build_meta")) if telemetry.columns(conn, "build_meta") else {}
                    report.update(status="available" if modern else "legacy", started_at=meta.get("usage_started_at"),
                                  coverage_start=_latest([meta.get("usage_started_at"), meta.get("usage_pruned_before")]),
                                  enabled=bool(cfg.knowledge_retrieval.get("telemetry", True)),
                                  legacy_history_complete=False)
                    if modern and not report["enabled"]:
                        report["status"] = "disabled"
                    spans = []
                    for table in ("retrieval_runs", "knowledge_reads") if modern else ("retrieval_runs",):
                        for ordering in ("ASC", "DESC"):
                            row = conn.execute(f"SELECT created_at FROM {table} WHERE julianday(created_at) IS NOT NULL ORDER BY julianday(created_at) {ordering} LIMIT 1").fetchone()
                            if row: spans.append(row[0])
                    report.update(earliest_retained_at=_first(spans), latest_retained_at=_latest(spans))
                    names = ["id", "query_hash", "candidate_count", "answerability", "layer", "elapsed_ms", "fallback_reason", "created_at"]
                    extra = [name for name in telemetry.SEARCH_COLUMNS if name != "results_json"]
                    select = names + [name if name in fields else "NULL AS " + name for name in extra]
                    for raw in conn.execute(f"SELECT {','.join(select)} FROM retrieval_runs WHERE julianday(created_at) BETWEEN julianday(?) AND julianday(?)",
                                            (self.since.isoformat(), self.until.isoformat())):
                        row = dict(raw)
                        is_new = row.get("contract_version") == 2 and row.get("status") in {"completed", "failed"}
                        key = source + ":" + row["receipt_id"] if row.get("receipt_id") else db_key + ":legacy:" + str(row["id"])
                        if key in seen_receipts:
                            continue
                        seen_receipts.add(key)
                        project_key, project_name = self._requested(row, source)
                        row.update(key=key, source_id=source, database_id=db_key, project_key=project_key,
                                   project_name=project_name, historical=not is_new,
                                   requested_projects=_json(row.get("requested_projects"), []),
                                   returned_projects=_json(row.get("returned_projects"), []),
                                   purpose=row.get("purpose") or "unknown", caller=row.get("caller") or "unknown")
                        if not is_new:
                            # Old candidate_count remains a chunk count, never a deduplicated count.
                            row.update(status="historical", document_count=None, task_id=None, actor_role=None)
                            if not self.selected:
                                self.historical.append(row)
                        if self._selected_event(row, source):
                            self.events.append(row)
                    if modern:
                        for raw in conn.execute("SELECT * FROM knowledge_reads WHERE julianday(created_at) BETWEEN julianday(?) AND julianday(?)",
                                                (self.since.isoformat(), self.until.isoformat())):
                            row = dict(raw)
                            key = source + ":" + row["receipt_id"]
                            if key in seen_receipts or not self._selected_event(row, source):
                                continue
                            seen_receipts.add(key)
                            project_key, project_name = self._requested(row, source)
                            row.update(key=key, source_id=source, database_id=db_key, project_key=project_key, project_name=project_name,
                                       results=_json(row.pop("results_json", ""), []),
                                       requested_projects=_json(row.get("requested_projects"), []),
                                       returned_projects=_json(row.get("returned_projects"), []))
                            self.reads.append(row)
            except (ValueError, OSError, sqlite3.Error):
                report["status"] = "unavailable"
                self.problem("KNOWLEDGE_LOG_UNAVAILABLE", source)

    def _get_document(self, key):
        if key in self.document_cache:
            return self.document_cache[key]
        source = key.split(":")[1] if key.startswith("knowledge:") and len(key.split(":")) == 3 else ""
        entry = self.sources.get(source)
        if not entry:
            return None
        try:
            row = documents.find_document(entry["cfg"], key)
            result = documents.public_document(entry["cfg"], row)
            result["source_identity"] = source
            result["project_key"] = source + ":" + result["project"]
            result["project_name"] = self.projects.get(result["project_key"], {}).get("name", result["project"])
            self.document_cache[key] = result
            return result
        except (ValueError, OSError, sqlite3.Error):
            return None

    def _asset(self, source, project, asset):
        cache_key = (source, project, asset)
        if cache_key in self.asset_cache:
            return self.asset_cache[cache_key]
        cfg = self.sources[source]["cfg"]
        choices = [project] + [row["id"] for row in self.sources[source]["catalog"] if row["shared"]]
        matches = []
        try:
            with telemetry.connect_readonly(cfg.paths.knowledge_projection_db) as conn:
                key_expr, meta_expr = documents.configure_connection(conn, cfg)
                scope_where, values = documents.scope_condition(cfg, choices)
                legacy = asset.removeprefix("knowledge:")
                rows = conn.execute(f"SELECT d.*, {meta_expr} AS public_metadata FROM documents d WHERE {scope_where} "
                    f"AND ({key_expr}=? OR d.canonical_id=? OR d.source_id=? OR d.rel_path=? OR json_extract({meta_expr},'$.conversion')=?) LIMIT 3",
                    [*values, asset, legacy, legacy, legacy, legacy]).fetchall()
                for row in rows:
                    item = documents.public_document(cfg, dict(row))
                    matches.append(item["key"])
        except (ValueError, OSError, sqlite3.Error):
            pass
        result = matches[0] if len(matches) == 1 else None
        self.asset_cache[cache_key] = result
        return result

    def _load_usage(self, contexts):
        grouped = defaultdict(list)
        for context in contexts:
            key = self.context_scopes.get(context.context_key)
            if not key or (self.selected and key != self.selected and not self.projects[self.selected]["shared"]):
                continue
            grouped[(_db_identity(context.db_path), context.project_id)].append((context, key))
        for (db_key, _project), entries in grouped.items():
            scope_keys = {key for _, key in entries}
            if len(scope_keys) != 1:
                self.runtime_failed.update(scope_keys)
                self.problem("KNOWLEDGE_RUNTIME_SCOPE_AMBIGUOUS")
                continue
            context, key = entries[0]
            source, project = self.projects[key]["source_id"], self.projects[key]["id"]
            try:
                with self.service._database(context) as conn:
                    # Coarse date prefilter includes all timezone offsets; exact comparisons below.
                    rows = context_effectiveness.fetch_context_event_rows(conn, project_id=context.project_id,
                        since_iso=(self.since-timedelta(days=2)).date().isoformat())
                    usage = context_effectiveness.context_usage_records(rows)
                    first = conn.execute("SELECT e.created_at FROM task_event e JOIN task t ON t.task_id=e.task_id "
                        "WHERE t.project_id=? AND julianday(e.created_at) IS NOT NULL ORDER BY julianday(e.created_at) LIMIT 1", (context.project_id,)).fetchone()
                self.runtime_available.add(key)
                self.runtime_sources.append({"project_key": key, "name": self.projects[key]["name"],
                    "status": "available", "started_at": first[0] if first else None,
                    "note": "最早现存任务事件，不代表曾有完整采用采集；采用日志保留未由知识投影推断。"})
                seen = set()
                for item in usage:
                    if item.get("source_type") != "knowledge" or not self._in_window(item.get("created_at")):
                        continue
                    identity = (item["event_id"], item["asset_id"], item["stage"])
                    if identity in seen:
                        continue
                    seen.add(identity)
                    doc_key = self._asset(source, project, item["asset_id"])
                    if self.selected and self.projects[self.selected]["shared"]:
                        doc = self._get_document(doc_key or "")
                        if not doc or doc["project_key"] != self.selected:
                            continue
                    self.usage.append({**item, "project_key": key, "project_name": self.projects[key]["name"],
                        "document_key": doc_key, "asset_identity": doc_key or source + ":legacy:" + item["asset_id"],
                        "task_key": db_key + ":" + item["task_id"], "source_id": source})
            except Exception:
                self.runtime_failed.add(key)
                self.runtime_sources.append({"project_key": key, "name": self.projects[key]["name"], "status": "unavailable"})
                self.problem("KNOWLEDGE_RUNTIME_UNAVAILABLE", context.name)

    def _purpose(self, row):
        return self.purpose == "all" or row.get("purpose", "unknown") == self.purpose

    def _identified(self, row):
        return not row.get("historical") and row.get("caller") in {"ai_cli", "task_convergence"}

    def _scope_projects(self):
        return [row for key, row in self.projects.items() if not self.selected or key == self.selected]

    def collection(self):
        reports = list(self.collections.values())
        available = [row for row in reports if row["status"] == "available"]
        status = ("available" if reports and len(available) == len(reports) and not (self.source_failures and not self.selected)
                  else "partial" if available else "unavailable" if any(r["status"] == "unavailable" for r in reports) or self.source_failures
                  else "legacy" if any(r["status"] == "legacy" for r in reports) else "missing" if reports and all(r["status"] == "missing" for r in reports)
                  else "disabled" if reports and all(r["status"] == "disabled" for r in reports) else "not_collected")
        complete_sources = {row["source_id"] for row in available}
        failed_sources = {row["source_id"] for row in reports if row["status"] != "available"}
        usable = [row["name"] for row in self._scope_projects() if row["source_id"] in complete_sources-failed_sources]
        missing = [row["name"] for row in self._scope_projects() if row["name"] not in usable]
        return {"status": status, "available_projects": usable, "missing_projects": missing,
                "unresolved_contexts": self.source_failures if not self.selected else [], "sources": reports,
                "started_at": _first(row.get("started_at") for row in available),
                "recent_at": _latest(row.get("latest_retained_at") for row in reports),
                "window_complete": status == "available" and all(_date(r.get("coverage_start")) and _date(r["coverage_start"]) <= self.since for r in reports),
                "note": "仅记录实际支持入口；人工页面搜索/阅读与普通文件工具读取不计数。来源未识别的记录不称为 AI 搜索。保留期限是配置，不代表存在完整 90 天数据；旧清理数据无法恢复。"}

    def adoption_collection(self):
        required = {row["key"] for row in self._scope_projects() if not row["shared"]}
        if self.selected and self.projects[self.selected]["shared"]:
            source = self.projects[self.selected]["source_id"]
            required = {key for key, row in self.projects.items() if row["source_id"] == source and not row["shared"]}
        available = required & self.runtime_available - self.runtime_failed
        complete = bool(required) and required == available and not (self.source_failures and not self.selected)
        return {"status": "available" if complete else "partial" if available else "unavailable" if required or self.source_failures else "not_collected",
                "available_projects": [self.projects[key]["name"] for key in sorted(available)],
                "missing_projects": [self.projects[key]["name"] for key in sorted(required-available)],
                "sources": self.runtime_sources, "started_at": _first(row.get("started_at") for row in self.runtime_sources),
                "recent_at": _latest(row.get("created_at") for row in self.usage if row["stage"] == "adopted"),
                "unmapped_assets": len({u["asset_identity"] for u in self.usage if not u["document_key"]}),
                "note": "采用仅来自可信 knowledge + adopted，按 Runtime/Task 与资产去重；命中、读取、验收、收敛均不是采用。采用是独立事实，不随检索用途筛选；历史无回执或无法唯一链接时仍保留。"}

    def metrics(self, project=""):
        events = [row for row in self.events if self._identified(row) and self._purpose(row) and (not project or row["project_key"] == project)]
        searches = [row for row in events if row["status"] == "completed"]
        hits = sum(bool(row.get("document_count")) for row in searches)
        adopted = [row for row in self.usage if row["stage"] == "adopted" and (not project or row["project_key"] == project)]
        reads = [row for row in self.reads if row["status"] == "completed" and row["body_returned"] and self._identified(row) and self._purpose(row) and (not project or row["project_key"] == project)]
        collected = self.collection()["status"] == "available"
        trusted = self.adoption_collection()["status"] == "available" if not project else project in self.runtime_available-self.runtime_failed
        return {"searches": _number(len(searches), collected), "hits": _number(hits, collected),
                "hit_rate": hits/len(searches) if searches and not (self.selected and self.projects[self.selected]["shared"]) else None,
                "reads": _number(len(reads), collected), "failures": _number(sum(row["status"] == "failed" for row in events), collected),
                "adopted_tasks": _number(len({row["task_key"] for row in adopted}), trusted),
                "adopted_documents": _number(len({row["asset_identity"] for row in adopted}), trusted),
                "canonical_searches": _number(sum(bool(row.get("has_canonical")) for row in searches), collected),
                "source_searches": _number(sum(bool(row.get("has_source")) for row in searches), collected),
                "fallback_reasons": dict(Counter(row["fallback_reason"] for row in searches if row["fallback_reason"])),
                "last_used": _latest([*[row["created_at"] for row in searches], *[row["created_at"] for row in reads], *[row["created_at"] for row in adopted]])}

    def _decorate(self, doc):
        doc = dict(doc)
        key = doc["key"]
        source = key.split(":")[1]
        doc["source_identity"] = source
        doc["project_key"] = source + ":" + doc["project"]
        doc["project_name"] = self.projects.get(doc["project_key"], {}).get("name", doc["project"])
        reads = [r for r in self.reads if r["document_key"] == key and r["status"] == "completed" and r["body_returned"] and self._purpose(r)]
        adopted = [u for u in self.usage if u["document_key"] == key and u["stage"] == "adopted"]
        source_reports = [r for r in self.collections.values() if r["source_id"] == source]
        complete = bool(source_reports) and all(r["status"] == "available" for r in source_reports)
        doc.update(reads=_number(len(reads), complete),
                   adopted_tasks=_number(len({u["task_key"] for u in adopted}), self.adoption_collection()["status"] == "available"),
                   last_used=_latest([*[r["created_at"] for r in reads], *[u["created_at"] for u in adopted]]))
        return doc

    def documents_view(self, *, page=1, query="", layer="", kind="", maintenance="", adopted=False):
        totals, successful, kinds, states, blocks, items = 0, 0, set(), set(), [], []
        adopted_keys = {u["document_key"] for u in self.usage if u["stage"] == "adopted" and u["document_key"]} if adopted else None
        expected = sum(self._source_selected(source) for source in self.sources)
        # Cross-index BM25 scores are not comparable. Order canonical first, then
        # resolved source identity, with relevance/title inside each SQLite index.
        # Count in SQL and fetch ONLY intersecting 20-row page slices, even deep
        # in a multi-source library. No page*20 prefix is materialized in Python.
        with ExitStack() as stack:
            for source, entry in sorted(self.sources.items()):
                if not self._source_selected(source):
                    continue
                selected = [self.projects[self.selected]["id"]] if self.selected else None
                try:
                    conn = stack.enter_context(telemetry.connect_readonly(entry["cfg"].paths.knowledge_projection_db))
                    current = []
                    for part in ([layer] if layer else ["canonical", "source"]):
                        options = dict(projects=selected, layer=part, kind=kind, maintenance=maintenance, keys=adopted_keys)
                        count = documents.query_documents(entry["cfg"], query, conn=conn, count_only=True, **options)["total"]
                        current.append((part, source, entry["cfg"], conn, options, count))
                    _, meta_expr = documents.configure_connection(conn, entry["cfg"])
                    where, values = documents.scope_condition(entry["cfg"], selected)
                    for row in conn.execute(f"SELECT DISTINCT d.kind,json_extract({meta_expr},'$.status') FROM documents d WHERE {where}", values):
                        if row[0]: kinds.add(row[0])
                        if row[1]: states.add(str(row[1]))
                    successful += 1
                    totals += sum(block[-1] for block in current)
                    blocks.extend(current)
                except (ValueError, sqlite3.Error, OSError):
                    self.problem("KNOWLEDGE_SEARCH_UNAVAILABLE" if query else "KNOWLEDGE_INDEX_UNAVAILABLE", source)
            offset = (page-1)*20
            for part, source, cfg, conn, options, count in sorted(blocks, key=lambda block: (0 if block[0] == "canonical" else 1, block[1])):
                if offset >= count:
                    offset -= count
                    continue
                if len(items) == 20:
                    break
                try:
                    result = documents.query_documents(cfg, query, conn=conn, limit=20-len(items), offset=offset, **options)
                    items.extend(self._decorate(row) for row in result["items"])
                    offset = 0
                except (ValueError, sqlite3.Error, OSError):
                    self.problem("KNOWLEDGE_SEARCH_UNAVAILABLE" if query else "KNOWLEDGE_INDEX_UNAVAILABLE", source)
                    successful = max(0, successful-1)
                    break  # A failed page segment must not masquerade as the next segment.
        status = "available" if successful == expected and expected and not (self.source_failures and not self.selected) else "partial" if successful else "unavailable"
        return {"items": items, "total": totals if successful else None, "page": page, "page_size": 20,
                "status": status, "kinds": sorted(kinds), "maintenance_states": sorted(states),
                "projects": list(self.projects.values()), "problems": self.problems,
                "note": "每页 20 篇去重文档；时间只筛选使用量。canonical 优先；跨来源分组，单个索引内按相关度/标题排序。项目为内容所属范围。"}

    def _maintenance(self):
        summary = {"canonical_documents": 0, "source_documents": 0, "registered_sources": 0, "sources": []}
        success = 0
        registry_complete = True
        attention = []
        for source, entry in self.sources.items():
            if not self._source_selected(source):
                continue
            cfg = entry["cfg"]
            selected = [self.projects[self.selected]["id"]] if self.selected else None
            detail = {"source_id": source, "status": "unavailable", "reports": []}
            summary["sources"].append(detail)
            try:
                with telemetry.connect_readonly(cfg.paths.knowledge_projection_db) as conn:
                    key_expr, meta_expr = documents.configure_connection(conn, cfg)
                    where, values = documents.scope_condition(cfg, selected)
                    counts = dict(conn.execute(f"SELECT d.scope,count(DISTINCT {key_expr}) FROM documents d WHERE {where} GROUP BY d.scope", values))
                    summary["canonical_documents"] += counts.get("canonical", 0)
                    summary["source_documents"] += counts.get("source", 0)
                    meta = dict(conn.execute("SELECT key,value FROM build_meta"))
                    detail.update(status="available", indexed_at=_latest([meta.get("build_at"), meta.get("last_update")]), **counts)
                    rows = conn.execute(f"SELECT d.*, {meta_expr} AS public_metadata FROM documents d WHERE {where} AND ("
                        f"json_extract({meta_expr},'$.status') IN ('stale','outdated','expired','conflict','superseded') OR "
                        f"(julianday(json_extract({meta_expr},'$.expires_at')) < julianday('now')) OR "
                        f"(d.scope='canonical' AND json_extract({meta_expr},'$.metadata_version')=1 AND d.source_refs='[]' AND json_array_length(json_extract({meta_expr},'$.evidence_refs'))=0)) LIMIT 30", values).fetchall()
                    for row in rows:
                        doc = documents.public_document(cfg, dict(row))
                        state = doc["status"]
                        expiry = _date(documents.metadata(dict(row)).get("expires_at"))
                        fact = state if state in {"stale", "outdated", "expired", "conflict", "superseded"} else "expired" if expiry and expiry < self.until else "missing_evidence"
                        attention.append({"kind": fact, "title": doc["title"], "document_key": doc["key"]})
                success += 1
            except (ValueError, sqlite3.Error, OSError):
                self.problem("KNOWLEDGE_INDEX_UNAVAILABLE", source)
            try:
                registered = read_jsonl(meta_paths(cfg)["source_registry"])
                summary["registered_sources"] = (summary["registered_sources"] or 0) + len({(row.get("batch"), row.get("origin_path"), row.get("source_id")) for row in registered if not selected or row.get("project") in selected})
                for name in ("verification", "audit_receipt", "snapshot"):
                    path = meta_paths(cfg)[name]
                    if path.is_file():
                        report = read_json(path, {})
                        detail["reports"].append({"name": name, "status": report.get("status") or report.get("result"),
                            "at": _latest([report.get("created_at"), report.get("updated_at"), report.get("verified_at"), report.get("committed_at")]),
                            "file_updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                            "scope": "source", "note": "已有来源级报告，不代表本次执行或当前单项目已验证。"})
            except (ValueError, OSError):
                self.problem("KNOWLEDGE_MAINTENANCE_UNREADABLE", source)
                registry_complete = False
        if not registry_complete:
            summary["registered_sources"] = None
        if not success:
            summary.update(canonical_documents=None, source_documents=None)
        summary["status"] = "available" if success == len(summary["sources"]) and success else "partial" if success else "unavailable"
        return summary, attention

    def overview(self):
        collection, adoption = self.collection(), self.adoption_collection()
        relevant = [e for e in self.events if self._identified(e) and self._purpose(e)]
        read_events = [r for r in self.reads if self._identified(r) and self._purpose(r) and r["status"] == "completed" and r["body_returned"]]
        adopted = [u for u in self.usage if u["stage"] == "adopted"]
        recent = {
            "search": {"at": _latest(e["created_at"] for e in relevant if e["status"] == "completed"), "status": collection["status"]},
            "read": {"at": _latest(r["created_at"] for r in read_events), "status": collection["status"]},
            "adopted": {"at": _latest(u["created_at"] for u in adopted), "status": adoption["status"]},
        }
        trend = []
        first_day = self.since.astimezone(_UTC_PLUS_8).date()
        last_day = self.until.astimezone(_UTC_PLUS_8).date()
        for offset in range((last_day - first_day).days + 1):
            date = first_day + timedelta(days=offset)
            rows = [e for e in relevant if _utc_plus_8_date(e["created_at"]) == date and e["status"] == "completed"]
            uses = [u for u in adopted if _utc_plus_8_date(u["created_at"]) == date]
            complete = collection["status"] == "available" and all(
                _utc_plus_8_date(r.get("coverage_start")) and _utc_plus_8_date(r["coverage_start"]) < date
                for r in self.collections.values())
            trend.append({"date": date.isoformat(), "searches": _number(len(rows), complete),
                          "hits": _number(sum(bool(r.get("document_count")) for r in rows), complete),
                          "adopted_tasks": _number(len({u["task_key"] for u in uses}), adoption["status"] == "available")})
        maintenance, attention = self._maintenance()
        streaks = {}
        for event in sorted(relevant, key=lambda e: _date(e["created_at"]) or _TIME_MIN):
            context_hash = event.get("scope_fingerprint")
            if not context_hash: continue
            group = (event["source_id"], event["query_hash"], context_hash)
            if event["status"] == "completed" and event["document_count"] == 0:
                streaks[group] = (streaks.get(group, (0, None))[0]+1, event)
            else:
                streaks[group] = (0, event)
        for (_, digest, _), (count, event) in streaks.items():
            if count >= 2:
                attention.append({"kind": "zero", "title": "同一匿名查询连续零命中 · " + digest[:12],
                                  "query_hash": digest, "project_key": event["project_key"], "count": count})
        keys = {r["document_key"] for r in read_events} | {u["document_key"] for u in adopted if u["document_key"]}
        popular = []
        for key in keys:
            doc = self._get_document(key)
            if doc:
                decorated = self._decorate(doc)
                popular.append(decorated)
                if (decorated["reads"] or 0) >= 3 and decorated["adopted_tasks"] == 0:
                    attention.append({"kind": "unadopted", "title": doc["title"], "document_key": key})
        popular.sort(key=lambda d: (-(d["adopted_tasks"] or 0), -(d["reads"] or 0), d["title"]))
        project_usage = [{**p, **self.metrics(p["key"])} for p in self._scope_projects() if not p["shared"]]
        unidentified = [e for e in self.events if not e["historical"] and not self._identified(e)]
        return {"projects": list(self.projects.values()), "days": self.days, "purpose": self.purpose,
                "statistics_note": "共享范围按实际返回内容筛选；请求项目身份仍保留。不能重建未命中共享的分母，故不展示共享有结果占比。" if self.selected and self.projects[self.selected]["shared"] else "搜索和读取按请求项目归因；文档按内容所属范围去重。",
                "selected_project": self.selected, "collection": collection, "adoption_collection": adoption,
                "metrics": self.metrics(), "recent_activity": recent, "trend": trend, "project_usage": project_usage,
                "popular": popular[:10], "attention": attention[:30], "maintenance": maintenance,
                "unidentified_searches": len(unidentified),
                "history": {"scope": "历史未归因检索", "count": len(self.historical) if not self.selected else None,
                            "count_kind": "legacy_runs", "earliest_at": _first(e["created_at"] for e in self.historical),
                            "note": "旧记录缺任务/角色/请求范围/去重文档数/结果回执，不归入单项目或 AI 研发次数，不补造历史。"},
                "problems": self.problems}

    def _links(self, cfg, document, content):
        links = []
        seen = set()
        # No external requests. Links resolve only against indexed registered documents.
        hrefs = re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", content)
        hrefs += [v.split("|", 1)[0] for v in re.findall(r"(?<!!)\[\[([^\]]+)\]\]", content)]
        for href in hrefs:
            if href in seen: continue
            seen.add(href)
            try:
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc or not parsed.path: continue
                decoded = unquote(parsed.path)
                if decoded.startswith(("/", "\\")) or "\\" in decoded or ":" in decoded or "\x00" in decoded: continue
                # Vault links may name a document relative to this note or from
                # the registered Vault root, with or without its .md suffix.
                paths = set()
                for parent in (posixpath.dirname(document["path"]), ""):
                    relative = posixpath.normpath(posixpath.join(parent, decoded))
                    if relative in {"", ".", ".."} or relative.startswith("../"): continue
                    paths.add(relative)
                    if not posixpath.splitext(relative)[1]:
                        paths.add(relative + ".md")
                if not paths: continue
                with telemetry.connect_readonly(cfg.paths.knowledge_projection_db) as conn:
                    _, meta_expr = documents.configure_connection(conn, cfg)
                    where, params = documents.scope_condition(cfg)
                    placeholders = ",".join("?" for _ in paths)
                    candidates = conn.execute(f"SELECT d.*, {meta_expr} AS public_metadata FROM documents d WHERE {where} AND "
                        f"(d.rel_path IN ({placeholders}) OR d.canonical_id=?) LIMIT 2", [*params, *sorted(paths), decoded]).fetchall()
                if len(candidates) != 1: continue
                row = dict(candidates[0])
                if not documents.metadata(row).get("metadata_only"):
                    documents.document_path(cfg, row)
                target = documents.public_document(cfg, row)
                links.append({"href": href, "key": target["key"], "title": target["title"]})
            except (ValueError, OSError, RuntimeError, sqlite3.Error):
                continue
        return links

    def document_view(self, key):
        from .service import ReadError
        current = self._get_document(key)
        if not current:
            raise ReadError("KNOWLEDGE_DOCUMENT_NOT_FOUND", "文档不在当前注册索引中，可能已删除、改名或来源不可用", 404)
        source = current["source_identity"]
        cfg = self.sources[source]["cfg"]
        try:
            result = reading.read_document(cfg, key, scope="global", full=True, record_telemetry=False, caller="unknown")
        except telemetry.KnowledgeError as exc:
            raise ReadError(exc.code, "文档无法安全读取；注册、路径或版本状态可能已变化", 404) from None
        doc = self._decorate({**current, **result["document"]})
        links = self._links(cfg, doc, result["content"])
        # A converted file, source ID or replacement only links when it resolves uniquely.
        references = []
        for kind, values in (("source", doc.get("source_refs") or []), ("replaced_by", [doc.get("replaced_by")]),
                             ("superseded", [doc.get("superseded")]), ("conversion", [doc.get("conversion")])):
            for value in values:
                if not isinstance(value, str) or not value: continue
                target = self._asset(source, doc["project"], value if value.startswith("knowledge:") else "knowledge:" + value)
                references.append({"kind": kind, "ref": value, "key": target})
        for relation in doc.get("relations") or []:
            target_ref = relation if isinstance(relation, str) else str(relation.get("target") or relation.get("to") or "") if isinstance(relation, dict) else ""
            target = self._asset(source, doc["project"], target_ref if target_ref.startswith("knowledge:") else "knowledge:" + target_ref) if target_ref else None
            references.append({"kind": "relation", "ref": relation, "key": target})
        usage = [{k: v for k, v in item.items() if k not in {"task_key", "asset_identity"}}
                 for item in self.usage if item["document_key"] == key]
        usage += [{"task_id": r.get("task_id"), "actor_role": r.get("actor_role"), "stage": "read",
                   "purpose": r["purpose"], "receipt_id": r["receipt_id"], "created_at": r["created_at"],
                   "project_name": r["project_name"], "read_mode": r["read_mode"]}
                  for r in self.reads if r["document_key"] == key and r["status"] == "completed" and r["body_returned"]]
        usage.sort(key=lambda r: _date(r["created_at"]) or _TIME_MIN, reverse=True)
        return {"document": doc, "content": result["content"], "read_mode": result["read_mode"],
                "outline": result["outline"], "links": links, "references": references, "usage": usage,
                "collection": self.collection(), "adoption_collection": self.adoption_collection(),
                "note": result.get("note"), "problems": self.problems}

    def _record_results(self, event):
        if event["historical"]:
            return None
        cfg = self.stores[event["database_id"]]["cfg"]
        with telemetry.connect_readonly(cfg.paths.knowledge_projection_db) as conn:
            row = conn.execute("SELECT results_json FROM retrieval_runs WHERE id=? AND receipt_id=?", (event["id"], event["receipt_id"])).fetchone()
        if not row or row[0] is None:
            return None
        result = []
        for item in _json(row[0], []):
            if not isinstance(item, dict): continue
            key = item.get("document_key")
            current = self._get_document(key or "")
            version = item.get("version") or item.get("content_hash")
            kind = item.get("version_kind") or ("chunk" if item.get("content_hash") else "unknown")
            current_version, state = None, "missing" if not current else "unknown"
            if current:
                try:
                    current_cfg = self.sources[current["source_identity"]]["cfg"]
                    indexed = documents.find_document(current_cfg, key)
                    if kind == "document" and not current.get("metadata_only"):
                        current_version = hashlib.sha256(reading._text(current_cfg, indexed).encode("utf-8")).hexdigest()
                    elif kind == "registered_source":
                        current_version = indexed["sha256"]
                    elif kind == "chunk":
                        with telemetry.connect_readonly(current_cfg.paths.knowledge_projection_db) as conn:
                            chunk = conn.execute("SELECT content_hash FROM chunks WHERE doc_id=? AND line_start=? AND line_end=? LIMIT 1",
                                                 (indexed["id"], item.get("line_start"), item.get("line_end"))).fetchone()
                            current_version = chunk[0] if chunk else None
                    state = "same" if version and current_version == version else "changed" if current_version and version else "unknown"
                except (ValueError, OSError, RuntimeError, sqlite3.Error):
                    state = "missing"
            result.append({**item, "key": key if current else None, "version": version,
                           "version_kind": kind, "current_version": current_version, "version_status": state})
        return result

    def records_view(self, *, page=1, status="all", task="", query_hash="", date="", receipt=""):
        rows = []
        for event in self.events:
            if not self._purpose(event): continue
            if status == "hit" and not (event["status"] == "completed" and event["document_count"]): continue
            if status == "zero" and not (event["status"] == "completed" and event["document_count"] == 0): continue
            if status == "failed" and event["status"] != "failed": continue
            if task and event.get("task_id") != task: continue
            if query_hash and not event["query_hash"].startswith(query_hash): continue
            if date and str(_utc_plus_8_date(event["created_at"])) != date: continue
            if receipt and event["key"] != receipt: continue
            # Internal fingerprints are never needed for UI display.
            rows.append({k: v for k, v in event.items() if k not in {"request_fingerprint", "scope_fingerprint"}})
        rows.sort(key=lambda r: (_date(r["created_at"]) or _TIME_MIN, r["key"]), reverse=True)
        total = len(rows)
        selected = rows[:1] if receipt else rows[(page-1)*20:page*20]
        if receipt:
            if not selected:
                from .service import ReadError
                raise ReadError("KNOWLEDGE_RECEIPT_NOT_FOUND", "回执不在所选范围，可能已过保留期", 404)
            try:
                selected[0]["results"] = self._record_results(selected[0])
            except (ValueError, OSError, sqlite3.Error):
                from .service import ReadError
                raise ReadError("KNOWLEDGE_RECEIPT_UNREADABLE", "回执明细读取失败，不代表无结果", 503) from None
        return {"items": selected, "total": total, "page": page, "page_size": 20,
                "collection": self.collection(), "projects": list(self.projects.values()), "problems": self.problems}
