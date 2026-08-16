# -*- coding: utf-8 -*-
"""Generation-fenced unattended cycle control.

A cycle spans many short-lived CLI processes, so ownership is represented by a
durable marker plus a monotonically increasing generation.  A short OS lock is
used only around marker compare-and-swap; no process holds a lock for the whole
AI session.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

from . import autonomy_profile
from . import db as dbmod
from .path_identity import canonical_path

CYCLE_SCHEMA = "tp-spec.autonomy-cycle/v1"
GRACE_SECONDS = 60


class CycleError(ValueError):
    pass


class CycleAlreadyRunning(CycleError):
    pass


class StaleCycleFenced(CycleError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def autonomy_dir(profile_id: str) -> Path:
    p = autonomy_profile.load_profile(profile_id)
    return canonical_path((p.get("autonomous") or {}).get("workspace_root")) / ".tp-spec" / "autonomy"


def marker_path(profile_id: str) -> Path:
    return autonomy_dir(profile_id) / "cycle.json"


def lock_path(profile_id: str) -> Path:
    return autonomy_dir(profile_id) / ".cycle.lock"


@contextmanager
def _critical_lock(path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    if f.tell() == 0:
        f.write(b"0")
        f.flush()
    start = time.monotonic()
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() - start >= timeout_seconds:
                        raise CycleError(f"CYCLE_LOCK_TIMEOUT: {path}")
                    time.sleep(0.02)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError:
                    if time.monotonic() - start >= timeout_seconds:
                        raise CycleError(f"CYCLE_LOCK_TIMEOUT: {path}")
                    time.sleep(0.02)
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def _read(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CycleError(f"CYCLE_MARKER_INVALID: {path}: {exc}") from exc
    if not isinstance(data, dict) or (data and data.get("schema") != CYCLE_SCHEMA):
        raise CycleError(f"CYCLE_MARKER_INVALID: {path}")
    return data


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _deadline_passed(marker: Dict[str, Any], now: datetime) -> bool:
    if marker.get("state") != "RUNNING":
        return False
    try:
        deadline = _parse(str(marker.get("deadline") or ""))
    except Exception as exc:
        raise CycleError("CYCLE_MARKER_INVALID: missing/invalid deadline") from exc
    return now > deadline


def _reclaimable(marker: Dict[str, Any], now: datetime) -> bool:
    if marker.get("state") != "RUNNING":
        return False
    try:
        deadline = _parse(str(marker.get("deadline") or ""))
    except Exception as exc:
        raise CycleError("CYCLE_MARKER_INVALID: missing/invalid deadline") from exc
    return now > deadline + timedelta(seconds=GRACE_SECONDS)


def _task_event_watermark(profile: Dict[str, Any]) -> int:
    root = canonical_path((profile.get("autonomous") or {}).get("workspace_root"))
    runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    db_path = root / ".tp-spec" / "db" / f"{runtime_id}.db"
    if not db_path.is_file():
        return 0
    conn = dbmod.connect_readonly(str(db_path))
    try:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM task_event").fetchone()
        return int(row["n"] if row is not None else 0)
    finally:
        conn.close()


def begin_cycle(profile_id: str, *, executor_kind: str = "local-agent", executor_pid: int | None = None) -> Dict[str, Any]:
    profile = autonomy_profile.load_profile(profile_id)
    if not bool(profile.get("enabled", True)):
        raise CycleError(f"PROFILE_DISABLED: {profile_id}")
    adir = autonomy_dir(profile_id)
    if not adir.parent.exists():
        raise CycleError(f"AUTONOMY_WORKSPACE_NOT_INITIALIZED: {adir.parent.parent}")
    path = marker_path(profile_id)
    now = _now()
    safety = profile.get("safety") or {}
    minutes = int(safety.get("max_cycle_minutes") or 240)
    with _critical_lock(lock_path(profile_id)):
        old = _read(path)
        if old.get("state") == "RUNNING" and not _reclaimable(old, now):
            raise CycleAlreadyRunning(
                f"CYCLE_ALREADY_RUNNING: profile={profile_id} cycle={old.get('cycle_id')} generation={old.get('generation')}"
            )
        generation = int(old.get("generation") or 0) + 1
        cycle_id = f"CYCLE-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        marker = {
            "schema": CYCLE_SCHEMA,
            "profile_id": profile_id,
            "cycle_id": cycle_id,
            "generation": generation,
            "state": "RUNNING",
            "task_event_watermark": _task_event_watermark(profile),
            "started_at": _iso(now),
            "last_seen_at": _iso(now),
            "deadline": _iso(now + timedelta(minutes=minutes)),
            "executor": {"kind": executor_kind, "pid": int(executor_pid or os.getpid())},
        }
        if old:
            marker["previous_cycle"] = {
                "cycle_id": old.get("cycle_id"), "generation": old.get("generation"),
                "state": old.get("state"), "reclaimed": bool(old.get("state") == "RUNNING"),
            }
        _write(path, marker)
        return dict(marker)


def require_cycle_token(profile_id: str, cycle_id: str, generation: int, *, touch: bool = True) -> Dict[str, Any]:
    path = marker_path(profile_id)
    now = _now()
    with _critical_lock(lock_path(profile_id)):
        marker = _read(path)
        if (
            marker.get("state") != "RUNNING"
            or str(marker.get("cycle_id") or "") != str(cycle_id)
            or int(marker.get("generation") or 0) != int(generation)
            or _deadline_passed(marker, now)
        ):
            raise StaleCycleFenced(
                f"STALE_CYCLE_FENCED: profile={profile_id} caller={cycle_id}/{generation} "
                f"current={marker.get('cycle_id')}/{marker.get('generation')} state={marker.get('state')}"
            )
        # hard deadline is not extended; only diagnostic last_seen is touched.
        if touch:
            marker["last_seen_at"] = _iso(now)
            _write(path, marker)
        return dict(marker)



def _mutate_current_marker(profile_id: str, cycle_id: str, generation: int, mutator):
    path = marker_path(profile_id)
    now = _now()
    with _critical_lock(lock_path(profile_id)):
        marker = _read(path)
        if (
            marker.get("state") != "RUNNING"
            or str(marker.get("cycle_id") or "") != str(cycle_id)
            or int(marker.get("generation") or 0) != int(generation)
            or _deadline_passed(marker, now)
        ):
            raise StaleCycleFenced(
                f"STALE_CYCLE_FENCED: profile={profile_id} caller={cycle_id}/{generation}"
            )
        mutator(marker)
        marker["last_seen_at"] = _iso(now)
        _write(path, marker)
        return dict(marker)


def claim_task(profile_id: str, cycle_id: str, generation: int, task_id: str) -> Dict[str, Any]:
    profile = autonomy_profile.load_profile(profile_id)
    limit = int((profile.get("safety") or {}).get("max_existing_tasks_per_cycle") or 5)
    task = str(task_id or "").strip()
    if not task:
        raise CycleError("CYCLE_TASK_ID_REQUIRED")
    def mutate(marker):
        claimed = [str(x) for x in (marker.get("claimed_tasks") or []) if str(x)]
        if task in claimed:
            return
        if len(claimed) >= limit:
            raise CycleError(f"CYCLE_TASK_LIMIT_REACHED: claimed={len(claimed)} max={limit}")
        claimed.append(task); marker["claimed_tasks"] = claimed
    return _mutate_current_marker(profile_id, cycle_id, generation, mutate)


def claim_rework(profile_id: str, cycle_id: str, generation: int, task_id: str) -> Dict[str, Any]:
    profile = autonomy_profile.load_profile(profile_id)
    limit = int((profile.get("safety") or {}).get("max_rework_attempts_per_task") or 2)
    task = str(task_id or "").strip()
    if not task:
        raise CycleError("CYCLE_TASK_ID_REQUIRED")
    def mutate(marker):
        counts = dict(marker.get("rework_attempts") or {})
        current = int(counts.get(task) or 0)
        if current >= limit:
            raise CycleError(f"TASK_REWORK_LIMIT_REACHED: task={task} attempts={current} max={limit}")
        counts[task] = current + 1; marker["rework_attempts"] = counts
    return _mutate_current_marker(profile_id, cycle_id, generation, mutate)

def end_cycle(profile_id: str, cycle_id: str, generation: int, *, result: str = "COMPLETED") -> Dict[str, Any]:
    path = marker_path(profile_id)
    now = _now()
    with _critical_lock(lock_path(profile_id)):
        marker = _read(path)
        if (
            marker.get("state") != "RUNNING"
            or str(marker.get("cycle_id") or "") != str(cycle_id)
            or int(marker.get("generation") or 0) != int(generation)
        ):
            raise StaleCycleFenced(
                f"STALE_CYCLE_FENCED: profile={profile_id} caller={cycle_id}/{generation}"
            )
        marker["state"] = str(result or "COMPLETED").upper()
        marker["completed_at"] = _iso(now)
        marker["last_seen_at"] = _iso(now)
        _write(path, marker)
        return dict(marker)


def cycle_status(profile_id: str) -> Dict[str, Any]:
    path = marker_path(profile_id)
    marker = _read(path)
    if not marker:
        return {"schema": CYCLE_SCHEMA, "profile_id": profile_id, "state": "IDLE", "generation": 0}
    data = dict(marker)
    if data.get("state") == "RUNNING":
        try:
            data["expired"] = _deadline_passed(data, _now())
            data["reclaimable"] = _reclaimable(data, _now())
        except CycleError:
            data["expired"] = True
    return data
