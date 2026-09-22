"""Read-only Wiki presentation. Never builds an index or records page activity."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cli import context_effectiveness
from cli.content_systems import load_content_systems
from cli.path_identity import path_identity_key
from cli.wiki import registry, retrieval


def _date(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _problem(code, message):
    return {"code": code, "message": str(message)}


def _latest_time(values):
    valid = [parsed for value in values if (parsed := _date(value)) is not None]
    return max(valid).isoformat() if valid else None


def _time_key(value):
    return _date(value) or datetime.min.replace(tzinfo=timezone.utc)


def _page(items, page):
    return {"items": items[(page - 1) * 20:page * 20], "total": len(items), "page": page, "page_size": 20}


def _body_read(event):
    return (event.get("operation") == "read" and event.get("status") == "completed"
            and bool(event.get("result_count", len(event.get("results", [])))))


class WikiView:
    def __init__(self, service, contexts, issues, *, days=30, project=""):
        self.service = service
        self.days, self.selected = days, project
        self.until = datetime.now(timezone.utc)
        self.since = self.until - timedelta(days=days)
        self.problems = list(issues)
        self.sources, self.projects, self.documents = {}, {}, {}
        self.repositories, self.events, self.usage, self.indexes = [], [], [], []
        self.runtime_available, self.runtime_total = set(), set()
        self.runtime_projects = set()
        self.runtime_failed_projects = set()
        self.source_failures = 0
        self._load_sources(contexts)
        if project and project not in self.projects:
            from .service import ReadError
            raise ReadError("WIKI_PROJECT_NOT_FOUND", "Wiki 项目不存在或注册已变化", 404)
        self._load_telemetry()
        self._load_usage(contexts)
        self._decorate_documents()

    def _load_sources(self, contexts):
        self.context_projects = {}
        loaded = {}
        for context in contexts:
            try:
                self.service._context(context.context_key)
                cfg = load_content_systems(context.workspace_root)
                cfg_identity = (path_identity_key(cfg.paths.wiki_system_root), path_identity_key(cfg.paths.wiki_registry), cfg.paths.wiki_layout,
                                getattr(cfg, "data", {}).get("systems", {}).get("wiki", {}).get("workspace_dir_template", "projects/{workspace_id}"))
                catalog = loaded.get(cfg_identity)
                if catalog is None:
                    catalog = retrieval.inventory(cfg)
                    loaded[cfg_identity] = catalog
                source = catalog["source_id"]
                if not source:
                    self.source_failures += 1
                    self.problems.extend(catalog.get("problems", []))
                    continue
                identity = registry.resolve_workspace_identity(cfg)
                key = source + ":" + str(identity.get("workspace_id") or "")
                if identity.get("resolved"):
                    self.context_projects[context.context_key] = key
                if source in self.sources:
                    continue
                self.sources[source] = {"cfg": cfg, "catalog": catalog}
                self.problems.extend(catalog.get("problems", []))
                for project in catalog.get("projects", []):
                    project_key = source + ":" + str(project["id"])
                    self.projects[project_key] = {"key": project_key, "id": project["id"],
                                                  "name": project.get("name") or project["id"], "source_id": source}
                for doc in catalog.get("documents", []):
                    project_key = source + ":" + str(doc["project_id"])
                    key = source + "|" + doc["id"]
                    self.documents[key] = {**doc, "key": key, "source_id": source, "project_key": project_key,
                        "project_name": self.projects.get(project_key, {}).get("name", doc["project_id"])}
                for repo in catalog.get("repositories", []):
                    project_key = source + ":" + str(repo["project_id"])
                    self.repositories.append({**repo, "project_key": project_key,
                        "project_name": self.projects.get(project_key, {}).get("name", repo["project_id"]),
                        "report": repo.get("report", repo.get("maintenance", {}))})
                try:
                    self.indexes.append({**retrieval.index_status(cfg), "source_id": source})
                except (OSError, ValueError, RuntimeError) as exc:
                    self.indexes.append({"source_id": source, "status": "unavailable"})
                    self.problems.append(_problem("WIKI_INDEX_UNREADABLE", exc))
            except Exception as exc:
                self.source_failures += 1
                self.problems.append(_problem("WIKI_SOURCE_UNREADABLE", f"{context.name}: {exc}"))

    def _in_window(self, value):
        moment = _date(value)
        return moment is not None and self.since <= moment <= self.until

    def _selected(self, key):
        return not self.selected or self.selected == key

    def _load_telemetry(self):
        self.collection_sources = {}
        for source, entry in self.sources.items():
            if self.selected and not self.selected.startswith(source + ":"):
                continue
            try:
                report = retrieval.telemetry(entry["cfg"], days=90)
                self.collection_sources[source] = report
                if report.get("status") not in {"available", "not_collected", "missing"}:
                    self.problems.append(_problem("WIKI_TELEMETRY_UNREADABLE",
                        report.get("error") or "该 Wiki 来源的使用日志不可读取，统计不代表零使用。"))
                for event in report.get("events", []):
                    project_key = source + ":" + str(event.get("project_id") or "")
                    if not self._in_window(event.get("created_at")):
                        continue
                    if not self._selected(project_key):
                        continue
                    # Unknown attribution stays unknown, never assigned to the active project.
                    self.events.append({**event, "key": source + "|" + str(event["receipt_id"]),
                        "source_id": source, "project_key": project_key,
                        "repo": event.get("repo", event.get("repo_id", "")),
                        "error": event.get("error", event.get("error_code", "")),
                        "project_name": self.projects.get(project_key, {}).get("name", "全局范围" if event.get("scope") == "all" else "未关联项目")})
            except Exception as exc:
                self.collection_sources[source] = {"status": "unavailable"}
                self.problems.append(_problem("WIKI_TELEMETRY_UNREADABLE", exc))

    def _asset_key(self, source, project_key, asset):
        exact = source + "|" + asset
        if exact in self.documents and self.documents[exact]["project_key"] == project_key:
            return exact
        # Historic IDs have no single mandatory path prefix. Only exact, unambiguous aliases
        # within the independently resolved project can be related to a current document.
        matches = []
        for key, doc in self.documents.items():
            if doc["project_key"] != project_key:
                continue
            aliases = {"wiki:" + doc["path"], "wiki:" + doc["repo_id"] + "/" + doc["path"]}
            if asset in aliases:
                matches.append(key)
        return matches[0] if len(matches) == 1 else ""

    def _load_usage(self, contexts):
        seen = set()
        for context in contexts:
            key = self.context_projects.get(context.context_key)
            if not key or not self._selected(key):
                continue
            identity = (path_identity_key(context.db_path), context.project_id)
            if identity in seen:
                continue
            seen.add(identity)
            self.runtime_total.add(identity)
            try:
                with self.service._database(context) as conn:
                    rows = context_effectiveness.fetch_context_event_rows(conn, project_id=context.project_id,
                                                                          since_iso=(self.since - timedelta(days=1)).date().isoformat())
                    usage = context_effectiveness.context_usage_records(rows)
                self.runtime_available.add(identity)
                self.runtime_projects.add(key)
                runtime_key = hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
                source = key.split(":", 1)[0]
                for item in usage:
                    if item.get("source_type") != "wiki" or not self._in_window(item.get("created_at")):
                        continue
                    self.usage.append({**item, "project_key": key,
                        "project_name": self.projects[key]["name"],
                        "document_key": self._asset_key(source, key, item["asset_id"]),
                        "task_key": runtime_key + ":" + item["task_id"]})
                unmatched = sum(u["project_key"] == key and not u["document_key"] for u in self.usage)
                if unmatched:
                    self.problems.append(_problem("WIKI_HISTORICAL_ASSET_UNMAPPED",
                        f"{context.name}: {unmatched} 条历史使用记录无法唯一关联当前文档，已保留原记录，未猜测链接。"))
            except Exception as exc:
                self.runtime_failed_projects.add(key)
                self.problems.append(_problem("WIKI_ADOPTION_UNREADABLE", f"{context.name}: {exc}"))

    def _decorate_documents(self):
        self.reads = Counter()
        self.doc_tasks, self.last_used = defaultdict(set), {}
        for event in self.events:
            if not _body_read(event):
                continue
            for result in event.get("results", []):
                key = event["source_id"] + "|" + result["id"]
                self.reads[key] += 1
                self.last_used[key] = _latest_time([self.last_used.get(key), event["created_at"]])
        for item in self.usage:
            key = item["document_key"]
            if key and item["stage"] == "adopted":
                self.doc_tasks[key].add(item["task_key"])
                self.last_used[key] = _latest_time([self.last_used.get(key), item["created_at"]])
        for key, doc in self.documents.items():
            collected = self.collection_sources.get(doc["source_id"], {}).get("status") == "available"
            doc.update(reads=self.reads[key] if collected else None,
                       adopted_tasks=len(self.doc_tasks[key]) if self._runtime_complete(doc["project_key"]) else None,
                       last_used=self.last_used.get(key))

    def collection(self):
        reports = list(self.collection_sources.values())
        available = [r for r in reports if r.get("status") == "available"]
        failed = [r for r in reports if r.get("status") not in {"available", "not_collected", "missing"}]
        started = [r["started_at"] for r in reports if r.get("started_at")]
        unresolved = self.source_failures if not self.selected else 0
        if failed or unresolved:
            status = "partial" if len(reports) > len(failed) else "unavailable"
        else:
            status = "partial" if available and len(available) != len(reports) else "available" if available else "not_collected"
        missing_sources = [source for source, report in self.collection_sources.items() if report.get("status") != "available"]
        missing_projects = [p["name"] for p in self.projects.values() if self._selected(p["key"]) and p["source_id"] in missing_sources]
        return {"status": status, "missing_projects": missing_projects, "unresolved_contexts": unresolved,
                "started_at": min(started) if started else None, "retention_days": 90,
                "accessible_projects": sum(self.collection_sources.get(p["source_id"], {}).get("status") == "available"
                                           for k, p in self.projects.items() if self._selected(k)),
                "total_projects": sum(self._selected(k) for k in self.projects),
                "note": "仅统计统一 CLI 的 AI 检索与读取；页面浏览和人工搜索不计数，直接文件读取不在采集范围。采用来自可信任务记录，历史未记录不代表未使用。"}

    def adoption_collection(self):
        projects = [p for p in self.projects.values() if self._selected(p["key"])]
        readable = [p for p in projects if self._runtime_complete(p["key"])]
        status = "available" if self._runtime_complete() else "partial" if readable else "unavailable" if projects or self.source_failures else "not_collected"
        adopted = any(u.get("stage") == "adopted" for u in self.usage)
        return {"status": status, "accessible_projects": len(readable), "total_projects": len(projects),
                "missing_projects": [p["name"] for p in projects if p not in readable],
                "note": "当前范围未记录采用" if status == "available" and not adopted else
                        "已读取可信任务采用记录" if status == "available" else
                        "部分项目任务记录不可读，仅展示已知证据" if status == "partial" else
                        "任务记录读取失败，不代表未采用" if status == "unavailable" else "尚无可读取的任务范围"}

    def recent_activity(self):
        def latest(rows, status):
            return {"at": _latest_time(r.get("created_at") for r in rows), "status": status}
        collection = self.collection()["status"]
        return {
            "search": latest([e for e in self.events if e.get("operation") == "search" and e.get("status") == "completed"], collection),
            "read": latest([e for e in self.events if _body_read(e)], collection),
            "adopted": latest([u for u in self.usage if u.get("stage") == "adopted"], self.adoption_collection()["status"]),
        }

    def _collected(self, project=""):
        if project:
            return self.collection_sources.get(project.split(":", 1)[0], {}).get("status") == "available"
        return bool(self.collection_sources) and not (self.source_failures and not self.selected) and all(
            r.get("status") == "available" for r in self.collection_sources.values())

    def _runtime_complete(self, project=""):
        projects = {project} if project else {k for k in self.projects if self._selected(k)}
        return bool(projects) and not (self.source_failures and not self.selected and not project) and projects.issubset(self.runtime_projects) and not projects.intersection(self.runtime_failed_projects)

    def _metrics(self, project=""):
        events = [e for e in self.events if not project or e["project_key"] == project]
        usage = [u for u in self.usage if not project or u["project_key"] == project]
        searches = [e for e in events if e.get("operation") == "search" and e.get("status") == "completed"]
        hits = sum(bool(e.get("result_count")) for e in searches)
        adopted = [u for u in usage if u["stage"] == "adopted"]
        collected = self._collected(project)
        has_runtime = self._runtime_complete(project)
        return {"searches": len(searches) if collected else None, "hits": hits if collected else None,
                "hit_rate": hits / len(searches) if collected and searches else None,
                "reads": sum(_body_read(e) for e in events) if collected else None,
                "failures": sum(e.get("status") == "failed" for e in events) if collected else None,
                "adopted_tasks": len({u["task_key"] for u in adopted}) if has_runtime else None,
                "adopted_documents": len({(u["project_key"], u["document_key"] or u["asset_id"]) for u in adopted}) if has_runtime else None}

    def overview(self):
        docs = [d for d in self.documents.values() if self._selected(d["project_key"])]
        repos = [r for r in self.repositories if self._selected(r["project_key"])]
        dates = {}
        collected = self._collected()
        has_runtime = self._runtime_complete()
        starts = [_date(r.get("started_at")) for r in self.collection_sources.values()]
        collection_start = max((s.astimezone().date().isoformat() for s in starts if s), default="")
        for offset in range(self.days + 1):
            day = (self.since + timedelta(days=offset)).astimezone().date().isoformat()
            day_collected = collected and bool(collection_start) and day >= collection_start
            dates[day] = {"date": day, "searches": 0 if day_collected else None, "hits": 0 if day_collected else None,
                          "adopted_tasks": 0 if has_runtime else None}
        day_tasks = defaultdict(set)
        for event in self.events:
            day = _date(event["created_at"]).astimezone().date().isoformat()
            if collected and day in dates and event.get("operation") == "search" and event.get("status") == "completed":
                dates[day]["searches"] = (dates[day]["searches"] or 0) + 1
                dates[day]["hits"] = (dates[day]["hits"] or 0) + bool(event.get("result_count"))
        for item in self.usage:
            if item["stage"] == "adopted":
                day_tasks[_date(item["created_at"]).astimezone().date().isoformat()].add(item["task_key"])
        for day, tasks in day_tasks.items():
            if has_runtime and day in dates:
                dates[day]["adopted_tasks"] = len(tasks)
        project_usage = []
        for key, project in self.projects.items():
            if not self._selected(key):
                continue
            times = [e["created_at"] for e in self.events if e["project_key"] == key and
                     ((e.get("operation") == "search" and e.get("status") == "completed") or _body_read(e))]
            times += [u["created_at"] for u in self.usage if u["project_key"] == key and u.get("stage") == "adopted"]
            project_usage.append({**project, **self._metrics(key), "last_used": _latest_time(times)})
        zeros = Counter((e["project_key"], e.get("query", ""), e.get("scope", ""), e.get("repo", ""), e.get("kind", ""))
                        for e in self.events if e.get("operation") == "search" and e.get("status") == "completed" and not e.get("result_count"))
        attention = [{"kind": "zero", "title": query or "未保存搜索词", "count": count, "project_key": key, "query": query}
                     for (key, query, _scope, _repo, _kind), count in zeros.most_common() if count >= 2]
        stale = Counter(u["document_key"] for u in self.usage if u.get("outcome") == "stale" and u["document_key"])
        for doc in docs:
            if stale[doc["key"]] or doc.get("status") in {"stale", "outdated", "expired"}:
                attention.append({"kind": "stale", "title": doc["title"], "document_key": doc["key"],
                                  "project_key": doc["project_key"], "count": stale[doc["key"]] or 1})
            if (doc["reads"] or 0) >= 3 and doc["adopted_tasks"] == 0:
                attention.append({"kind": "unadopted", "title": doc["title"], "document_key": doc["key"],
                                  "project_key": doc["project_key"], "count": doc["reads"]})
        popular = sorted([d for d in docs if d["reads"] or d["adopted_tasks"]],
                         key=lambda d: (-(d["adopted_tasks"] or 0), -(d["reads"] or 0), d["title"]))[:10]
        return {"projects": list(self.projects.values()), "selected_project": self.selected, "days": self.days,
                "collection": self.collection(), "adoption_collection": self.adoption_collection(),
                "recent_activity": self.recent_activity(), "metrics": self._metrics(), "trend": list(dates.values()),
                "project_usage": project_usage, "attention": attention[:30], "popular": popular,
                "maintenance": {"document_count": len(docs), "repo_count": len(repos),
                    "updated_at": max((r.get("updated_at") or "" for r in repos), default="") or None,
                    "repositories": [{k: r.get(k) for k in ("project_key", "project_name", "repo_id", "document_count", "updated_at", "status", "report")} for r in repos]},
                "indexes": [{k: i.get(k) for k in ("source_id", "status", "indexed_at")} for i in self.indexes], "problems": self.problems}

    def documents_view(self, *, page=1, query="", repo="", kind="", adopted=False):
        docs = [d for d in self.documents.values() if self._selected(d["project_key"])]
        repositories = sorted({d["repo_id"] for d in docs})
        types = sorted({d.get("type") or "unknown" for d in docs})
        docs = [d for d in docs if (not repo or d["repo_id"] == repo) and (not kind or d.get("type") == kind)
                and (not adopted or (d["adopted_tasks"] or 0) > 0)]
        search_total = None
        if query:
            matches = {}
            search_total = 0
            # Top page*20 from each source is sufficient for a merged page. Never walk the
            # entire index merely to display the first page; the query provides exact totals.
            for source, entry in self.sources.items():
                if self.selected and not self.selected.startswith(source + ":"):
                    continue
                if adopted and not any(d["source_id"] == source for d in docs):
                    continue
                project = self.projects[self.selected]["id"] if self.selected else ""
                try:
                    offset = 0
                    while True:
                        result = retrieval.search(entry["cfg"], query, project=project, repo=repo, kind=kind,
                                                  limit=100, offset=offset, scope="current" if project else "all", record_telemetry=False)
                        if result.get("error"):
                            explanation = {
                                "INDEX_MISSING": "Wiki 检索索引尚未建立；可通过 tp-spec wiki index build 显式建立。文档浏览仍可使用。",
                                "INDEX_STALE": "Wiki 索引与当前文档不一致；请通过 tp-spec wiki index update 显式更新，页面不会自动维护索引。",
                            }.get(result["error"], result.get("message") or result["error"])
                            self.problems.append(_problem("WIKI_SEARCH_UNAVAILABLE", explanation))
                            break
                        if offset == 0:
                            search_total += result.get("total", result.get("count", 0))
                        batch = result.get("results", [])
                        for row in batch:
                            matches[source + "|" + row["id"]] = row
                        offset += len(batch)
                        if not batch or offset >= result.get("total", result.get("count", len(batch))) or (not adopted and offset >= page * 20):
                            break
                except Exception as exc:
                    self.problems.append(_problem("WIKI_SEARCH_UNAVAILABLE", exc))
            docs = [{**d, "snippet": matches[d["key"]].get("snippet", ""), "score": matches[d["key"]].get("score", 0)}
                    for d in docs if d["key"] in matches]
            docs.sort(key=lambda d: (-d.get("score", 0), d["title"]))
        else:
            docs.sort(key=lambda d: (d["project_name"], d["repo_id"], d["path"]))
        paged = _page(docs, page)
        if search_total is not None and not adopted:
            paged["total"] = search_total
        return {**paged, "repositories": [{"id": r, "name": r} for r in repositories],
                "types": types, "indexes": self.indexes, "problems": self.problems}

    def document_view(self, key):
        from .service import ReadError
        doc = self.documents.get(key)
        if not doc:
            raise ReadError("WIKI_DOCUMENT_NOT_FOUND", "文档不在当前注册清单中", 404)
        try:
            result = retrieval.read_document(self.sources[doc["source_id"]]["cfg"], doc["id"], record_telemetry=False, full=True)
        except (ValueError, OSError) as exc:
            raise ReadError("WIKI_DOCUMENT_UNREADABLE", str(exc), 404) from exc
        if result.get("error") or not result.get("document"):
            raise ReadError("WIKI_DOCUMENT_UNREADABLE", result.get("error") or "文档无法读取", 404)
        content = result["content"]
        links = []
        repo_roots = {(r["project_key"], r["repo_id"]): r.get("wiki_repo_root") for r in self.repositories}
        registered_paths = None
        # Browser links are a lookup of known manifest documents, never file paths accepted
        # from a client. Non-Wiki source citations remain plain references.
        for href in set(re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", content)):
            try:
                parsed = urlsplit(href)
            except ValueError:
                continue
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = unquote(parsed.path).replace("\\", "/")
            if path.startswith("/"):
                continue
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(doc["path"]), path))
            target = next((d for d in self.documents.values() if d["source_id"] == doc["source_id"] and
                           d["project_key"] == doc["project_key"] and d["repo_id"] == doc["repo_id"] and d["path"] == relative), None)
            origin_root = repo_roots.get((doc["project_key"], doc["repo_id"]))
            if target is None and origin_root:
                resolved = path_identity_key(Path(origin_root) / relative)
                if registered_paths is None:
                    registered_paths = {}
                    for candidate in self.documents.values():
                        candidate_root = repo_roots.get((candidate["project_key"], candidate["repo_id"]))
                        if candidate["source_id"] == doc["source_id"] and candidate_root:
                            registered_paths[path_identity_key(Path(candidate_root) / candidate["path"])] = candidate
                target = registered_paths.get(resolved)
            if target:
                links.append({"href": href, "key": target["key"], "title": target["title"]})
        usage = [{k: v for k, v in item.items() if k not in {"task_key", "document_key"}}
                 for item in self.usage if item["document_key"] == key]
        for event in self.events:
            if _body_read(event) and any(r["id"] == doc["id"] for r in event.get("results", [])) and event["source_id"] == doc["source_id"]:
                usage.append({"task_id": event.get("task_id"), "actor_role": event.get("actor_role"), "stage": "read",
                              "created_at": event["created_at"], "receipt_id": event["receipt_id"]})
        return {"document": {**doc, **result.get("document", {})}, "content": content,
                "links": links, "usage": sorted(usage, key=lambda u: _time_key(u["created_at"]), reverse=True), "problems": self.problems}

    def records_view(self, *, page=1, status="all", date="", query=""):
        items = []
        for event in self.events:
            if event.get("operation") != "search":
                continue
            hit = event.get("status") == "completed" and bool(event.get("result_count"))
            zero = event.get("status") == "completed" and not event.get("result_count")
            if status == "hit" and not hit or status == "zero" and not zero or status == "failed" and event.get("status") != "failed":
                continue
            if date and _date(event["created_at"]).astimezone().date().isoformat() != date:
                continue
            if query and query.casefold() not in (event.get("query") or "").casefold():
                continue
            results = []
            for row in event.get("results", []):
                key = event["source_id"] + "|" + row["id"]
                current = self.documents.get(key)
                results.append({**row, "key": key if current else None, "title": current["title"] if current else row["id"],
                    "current_hash": current.get("content_hash") if current else None,
                    "version_status": "missing" if not current else "unknown" if not row.get("content_hash") or not current.get("content_hash") else "same" if row.get("content_hash") == current.get("content_hash") else "changed"})
            items.append({**event, "results": results})
        items.sort(key=lambda r: _time_key(r["created_at"]), reverse=True)
        return {**_page(items, page), "collection": self.collection(), "problems": self.problems}
