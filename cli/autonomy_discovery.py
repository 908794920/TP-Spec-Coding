# -*- coding: utf-8 -*-
"""Deterministic bookkeeping for AI-proposed autonomous Task discovery.

Semantic discovery remains an AI responsibility.  This module only enforces
cycle fencing, ceilings, deduplication, Task identity allocation and provenance.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import autonomy_cycle, autonomy_git, autonomy_profile, autonomy_records
from . import db as dbmod
from . import task_cmd

_TASK_DAY_RE = re.compile(r"^TASK-(\d{8})-(\d+)$")


class DiscoveryError(ValueError):
    pass


def _runtime(profile_id: str):
    profile = autonomy_profile.load_profile(profile_id)
    root = Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    db_path = root / ".tp-spec" / "db" / f"{runtime_id}.db"
    return profile, root, runtime_id, str(db_path)


def _parse_detail(raw: Any) -> Dict[str, Any]:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _discovered_rows(conn, profile_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT e.task_id,e.detail_json,e.created_at,t.current_state,t.title FROM task_event e JOIN task t ON t.task_id=e.task_id "
        "WHERE e.event_type='AUTONOMY_DISCOVERED' ORDER BY e.id",
    ).fetchall()
    out=[]
    for row in rows:
        detail=_parse_detail(row["detail_json"])
        if detail.get("profile_id") == profile_id:
            out.append({**dict(row), "detail": detail})
    return out


def find_duplicate(profile_id: str, discovery_key: str) -> Optional[Dict[str, Any]]:
    _, _, _, db_path = _runtime(profile_id)
    conn=dbmod.connect_readonly(db_path)
    try:
        for row in reversed(_discovered_rows(conn, profile_id)):
            if str((row["detail"] or {}).get("discovery_key") or "") == discovery_key:
                return row
        return None
    finally:
        conn.close()


def _pending_user_decisions(conn, profile_id: str) -> List[str]:
    tasks = conn.execute("SELECT task_id,current_state FROM task WHERE current_state='BLOCKED' ORDER BY task_id").fetchall()
    out=[]
    for row in tasks:
        task_id=str(row["task_id"])
        blockers=conn.execute("SELECT detail_json FROM task_event WHERE task_id=? AND event_type='BLOCKER' ORDER BY id DESC",(task_id,)).fetchall()
        for b in blockers:
            d=_parse_detail(b["detail_json"])
            if d.get("operation") == "AUTONOMY_BOUNDARY" and d.get("profile_id") == profile_id:
                out.append(task_id); break
    return out


def _new_count_for_cycle(conn, profile_id: str, cycle_id: str) -> int:
    count=0
    for row in _discovered_rows(conn, profile_id):
        if str((row["detail"] or {}).get("cycle_id") or "") == cycle_id:
            count += 1
    return count


def allocate_task_id(conn) -> str:
    day = dbmod.now_iso()[:10].replace("-", "")
    max_n=0
    rows=conn.execute("SELECT task_id FROM task WHERE task_id LIKE ?",(f"TASK-{day}-%",)).fetchall()
    for row in rows:
        m=_TASK_DAY_RE.match(str(row["task_id"] or ""))
        if m and m.group(1)==day:
            max_n=max(max_n,int(m.group(2)))
    return f"TASK-{day}-{max_n+1}"


def _assert_discovery_repos_clean(profile: Dict[str, Any]) -> None:
    root = Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    repos = (profile.get("canonical") or {}).get("repositories") or {}
    for scope in ("mutable", "support"):
        for item in repos.get(scope) or []:
            rid = str(item.get("id") or item.get("path") or "")
            repo = root / str(item.get("path") or "")
            if autonomy_git.dirty(repo):
                raise DiscoveryError(f"DISCOVERY_REPO_DIRTY: {scope}:{rid}:{repo}")


def _staging_heads(profile: Dict[str, Any]) -> Dict[str, str]:
    root=Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    repos=((profile.get("canonical") or {}).get("repositories") or {}).get("mutable") or []
    return {str(item.get("id")): autonomy_git.head(root / str(item.get("path"))) for item in repos}


def _create_task(profile_id: str, *, task_id: str, title: str, summary: str, risk: str, flow: str) -> Path:
    profile, root, runtime_id, db_path = _runtime(profile_id)
    args=type("AutonomyTaskCreateArgs",(),{
        "id":task_id,"project":runtime_id,"title":title,"risk":risk,"flow":flow,"summary":summary,
        "db":db_path,"scaffold":True,"from_intake":None,"task_dir":None,
    })()
    old=Path.cwd(); out=io.StringIO(); err=io.StringIO()
    try:
        os.chdir(root)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc=task_cmd.cmd_task_create(args)
    finally:
        os.chdir(old)
    if rc != 0:
        raise DiscoveryError(f"AUTONOMY_TASK_CREATE_FAILED: {err.getvalue().strip() or out.getvalue().strip()}")
    return root / ".tp-spec" / "tasks" / task_id


def discover(*, profile_id: str, cycle_id: str, generation: int, discovery_key: str,
             title: str, summary: str, risk: str, flow: str) -> Dict[str, Any]:
    autonomy_cycle.require_cycle_token(profile_id, cycle_id, generation)
    profile, root, runtime_id, db_path = _runtime(profile_id)
    # Semantic discovery is read-only.  A model cannot smuggle code changes into
    # staging before the Task / approval boundary is established.
    _assert_discovery_repos_clean(profile)
    level_order={"L0":0,"L1":1,"L2":2,"L3":3}
    ceiling=str((profile.get("policy") or {}).get("difficulty_ceiling") or "L0")
    if risk not in level_order or flow not in level_order:
        raise DiscoveryError("DISCOVERY_LEVEL_INVALID")
    if max(level_order[risk], level_order[flow]) > level_order[ceiling]:
        raise DiscoveryError(f"DIFFICULTY_CEILING_EXCEEDED: proposed={max(risk,flow)} ceiling={ceiling}")
    key=str(discovery_key or "").strip()
    if not key:
        raise DiscoveryError("DISCOVERY_KEY_REQUIRED")
    dup=find_duplicate(profile_id,key)
    if dup:
        _record_suppressed(profile_id, cycle_id, generation, key, str(dup["task_id"]), "previously_discovered")
        return {"schema":"tp-spec.autonomy-discovery/v1","status":"SUPPRESSED","discovery_key":key,"matched_task":dup["task_id"]}

    conn=dbmod.connect_readonly(db_path)
    try:
        pending=_pending_user_decisions(conn,profile_id)
        pending_limit=int((profile.get("safety") or {}).get("max_pending_user_decisions") or 5)
        if len(pending) >= pending_limit:
            raise DiscoveryError(f"DISCOVERY_PAUSED_PENDING_BACKLOG: pending={len(pending)} limit={pending_limit}")
        count=_new_count_for_cycle(conn,profile_id,cycle_id)
        max_new=int((((profile.get("policy") or {}).get("discovery") or {}).get("max_new_tasks_per_cycle") or 0))
        if count >= max_new:
            raise DiscoveryError(f"DISCOVERY_CEILING_REACHED: created={count} max={max_new}")
        task_id=allocate_task_id(conn)
    finally:
        conn.close()
    heads=_staging_heads(profile)
    tdir=_create_task(profile_id,task_id=task_id,title=title,summary=summary,risk=risk,flow=flow)
    autonomy_records.record_discovered(profile_id,task_id,str(tdir),discovery_key=key,cycle_id=cycle_id,generation=generation)
    # Bind exact code truth used for semantic discovery without copying source content into the ledger.
    _append_discovery_context(profile_id, task_id, str(tdir), heads)
    return {"schema":"tp-spec.autonomy-discovery/v1","status":"CREATED","task_id":task_id,
            "discovery_key":key,"staging_heads":heads,"risk":risk,"flow":flow}


def _append_discovery_context(profile_id: str, task_id: str, task_dir: str, heads: Dict[str,str]) -> None:
    # Reuse one ordinary autonomy fact rather than creating another public state.
    autonomy_records._write_fact(
        profile_id,task_id,task_dir,operation="DISCOVERY_CONTEXT",event_type="AUTONOMY_DISCOVERY_CONTEXT",
        summary="autonomy discovery staging subjects",detail={"staging_heads":heads},
    )


def _record_suppressed(profile_id: str, cycle_id: str, generation: int, key: str, matched_task: str, reason: str) -> None:
    profile, root, _, _ = _runtime(profile_id)
    path=root / ".tp-spec" / "autonomy" / "cycles" / f"{cycle_id}.discoveries.jsonl"
    path.parent.mkdir(parents=True,exist_ok=True)
    item={"schema":"tp-spec.autonomy-suppressed/v1","profile_id":profile_id,"cycle_id":cycle_id,"generation":generation,
          "discovery_key":key,"matched_task":matched_task,"reason":reason}
    with open(path,"a",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(item,ensure_ascii=False)+"\n")
