# -*- coding: utf-8 -*-
"""Redacted cycle/inbox projections. SQLite/Git remain the truth sources."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from . import autonomy_cycle, autonomy_profile, autonomy_workspace
from . import db as dbmod


def _parse(raw):
    try:
        d=json.loads(raw) if raw else {}
    except Exception:
        return {}
    return d if isinstance(d,dict) else {}


def build_digest(profile_id: str, cycle_id: str, generation: int) -> Dict[str, Any]:
    cycle_marker=autonomy_cycle.require_cycle_token(profile_id,cycle_id,generation)
    event_watermark=int(cycle_marker.get("task_event_watermark") or 0)
    profile=autonomy_profile.load_profile(profile_id)
    root=Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    runtime_id=str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    db_path=root/".tp-spec"/"db"/f"{runtime_id}.db"
    conn=dbmod.connect_readonly(str(db_path))
    try:
        tasks=[dict(r) for r in conn.execute("SELECT task_id,title,current_state,current_stage,updated_at FROM task ORDER BY created_at,task_id").fetchall()]
        new=[]; waiting=[]; progress=[]; failed=[]; completed=[]
        for t in tasks:
            tid=t["task_id"]
            events=[dict(r) for r in conn.execute("SELECT id,event_type,summary,detail_json,created_at,to_state FROM task_event WHERE task_id=? ORDER BY id",(tid,)).fetchall()]
            discovered_this=False; waiting_reason=None; completed_this=False
            for e in events:
                d=_parse(e.get("detail_json"))
                if e.get("event_type")=="AUTONOMY_DISCOVERED" and d.get("profile_id")==profile_id and d.get("cycle_id")==cycle_id:
                    discovered_this=True
                if e.get("event_type")=="BLOCKER" and d.get("operation")=="AUTONOMY_BOUNDARY" and d.get("profile_id")==profile_id:
                    waiting_reason=d.get("waiting_reason")
                if e.get("event_type")=="STATE" and e.get("to_state")=="COMPLETED" and int(e.get("id") or 0)>event_watermark:
                    completed_this=True
            item={"task_id":tid,"title":t.get("title") or "","state":t.get("current_state"),"phase":t.get("current_stage")}
            if discovered_this: new.append(item)
            if t.get("current_state")=="BLOCKED" and waiting_reason:
                item=dict(item); item["reason"]=waiting_reason; waiting.append(item)
            elif t.get("current_state") in {"NEW","ACTIVE"}:
                progress.append(item)
            elif t.get("current_state")=="CANCELLED":
                failed.append(item)
            elif t.get("current_state")=="COMPLETED" and completed_this:
                completed.append(item)
    finally:
        conn.close()
    ws=autonomy_workspace.workspace_status(profile_id,refresh_canonical=True)
    drift={r["id"]:r.get("drift") for r in ws["repositories"] if r.get("scope")=="mutable"}
    awaiting_integration=[]
    batch_dir=root/".tp-spec"/"autonomy"/"batches"
    if batch_dir.is_dir():
        for p in sorted(batch_dir.glob("*.json")):
            try: b=json.loads(p.read_text(encoding="utf-8"))
            except Exception: continue
            if b.get("status") in {"READY","PARTIAL_READY","READY_FOR_INTEGRATION"}:
                awaiting_integration.append({"batch_id":b.get("batch_id"),"status":b.get("status"),"tasks":list(b.get("tasks") or [])})
    return {
        "schema":"tp-spec.autonomy-digest/v1","profile_id":profile_id,"cycle_id":cycle_id,"generation":generation,
        "cycle_result":"RUNNING","canonical_staging_drift":drift,
        "new_tasks_created":new,"awaiting_user_decision":waiting,"in_progress":progress,
        "completed_this_cycle":completed,"failed_or_cancelled":failed,"awaiting_integration":awaiting_integration,
        "next_user_actions":[
            *[f"decide {x['task_id']}" for x in waiting],
            *[f"review {x['batch_id']}" for x in awaiting_integration],
        ],
    }


def write_digest(profile_id: str, cycle_id: str, generation: int) -> Dict[str, Any]:
    data=build_digest(profile_id,cycle_id,generation)
    profile=autonomy_profile.load_profile(profile_id)
    root=Path((profile.get("autonomous") or {}).get("workspace_root") or "").resolve()
    adir=root/".tp-spec"/"autonomy"; (adir/"cycles").mkdir(parents=True,exist_ok=True)
    for path in (adir/"status.json", adir/"cycles"/f"{cycle_id}.json"):
        tmp=path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
        os.replace(tmp,path)
    return data
