# -*- coding: utf-8 -*-
"""Invocation-local reuse and diagnostic timings, never a workflow authority.

Intervals are inclusive (nested intervals must not be summed). The total covers
main/parser/dispatch, not interpreter startup, pre-main imports, stdio setup
or diagnostic persistence.
Each receipt is atomic and independent; concurrent CLI writers do not share a log.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import json
import math
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from typing import Any, Iterator
import uuid

_SEGMENTS = ("parse", "config", "changeset", "lock_wait", "lock_held", "db_write", "db_commit", "evidence", "projection", "card")
_CURRENT: ContextVar["CommandContext | None"] = ContextVar("tp_spec_command", default=None)


@dataclass
class CommandContext:
    invocation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started: float = field(default_factory=perf_counter)
    command: str = "unparsed"
    task_id: str | None = None
    exit_code: int = 1
    completion: str = "finished"
    segments: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_cache: dict[tuple, dict] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    bindings: dict[str, Any] = field(default_factory=dict)

    def bind(self, args) -> None:
        group = str(getattr(args, "group", "") or "")
        action = str(getattr(args, "subcommand", "") or getattr(args, "card_type", "") or "")
        self.command = " ".join(value for value in (group, action) if value)
        task_id = getattr(args, "id", None) if group == "task" and action == "create" else getattr(args, "task", None)
        # Invalid input is not an established identity. Do not copy arbitrary
        # user strings (including misplaced secrets) into a diagnostic receipt.
        self.task_id = task_id if isinstance(task_id, str) and re.fullmatch(r"TASK-[A-Za-z0-9][A-Za-z0-9._-]*", task_id) else None

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "tp-spec.cli-timing/v1", "invocation_id": self.invocation_id,
            "started_at": self.started_at, "command": self.command,
            "task_id": self.task_id, "exit_code": self.exit_code, "completion": self.completion,
            "scope": "main parser/dispatch; excludes interpreter startup, imports before main, stdio setup and diagnostic persistence",
            "inclusive_segments": True,
            "measurement_notes": {
                "lock_wait": "explicit BEGIN IMMEDIATE only; deferred transaction waits remain inside db_write",
                "lock_held": "explicit immediate transactions after acquisition until COMMIT/ROLLBACK (or failed rollback attempt); includes nested work, not deferred transactions",
                "db_write": "writer callback or deferred transaction body; includes nested work",
                "projection": "render/replace spans; inclusive of nested work",
            },
            "total_ms": round((perf_counter() - self.started) * 1000, 3),
            "segments": {
                name: self.segments.get(name, {"calls": 0, "elapsed_ms": 0.0, "status": "not_entered"})
                for name in _SEGMENTS
            },
            "counters": dict(self.counters),
            "bindings": dict(self.bindings),
        }


def current() -> CommandContext | None:
    return _CURRENT.get()


def invocation_id() -> str | None:
    context = current()
    return context.invocation_id if context is not None else None


def count(name: str, amount: int = 1) -> None:
    context = current()
    if context is not None:
        context.counters[name] = context.counters.get(name, 0) + amount


@contextlib.contextmanager
def span(name: str) -> Iterator[None]:
    context = current()
    if context is None:
        yield
        return
    entry = context.segments.setdefault(name, {"calls": 0, "elapsed_ms": 0.0, "status": "completed"})
    entry["calls"] += 1
    started = perf_counter()
    try:
        yield
    except BaseException as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
            entry["status"] = "failed"
        raise
    finally:
        entry["elapsed_ms"] = round(entry["elapsed_ms"] + (perf_counter() - started) * 1000, 3)


def measured(name: str):
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            with span(name):
                return func(*args, **kwargs)
        return wrapped
    return decorate


def _root() -> Path:
    return Path(os.environ.get("TP_SPEC_USER_ROOT") or (Path.home() / ".tp-spec")).expanduser().resolve() / "diagnostics" / "cli"


def _persist(receipt: dict) -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    # Only our validated names participate in pruning; never delete unrelated files.
    stamp = receipt["started_at"].replace(":", "").replace("+", "_")
    target = root / f"{stamp}-{receipt['invocation_id']}.json"
    temp = target.with_suffix(".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            os.chmod(temp, 0o600)
            json.dump(receipt, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        os.replace(temp, target)
        raw = os.environ.get("TP_SPEC_DIAGNOSTICS_KEEP", "200")
        keep = int(raw)
        if not 1 <= keep <= 10000:
            raise ValueError("TP_SPEC_DIAGNOSTICS_KEEP must be 1..10000")
        files = sorted((p for p in root.glob("*.json") if re.fullmatch(r"[0-9T._-]+-[a-f0-9]{32}\.json", p.name)), reverse=True)
        for path in files[keep:]:
            path.unlink(missing_ok=True)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def command() -> Iterator[CommandContext]:
    context = CommandContext()
    token = _CURRENT.set(context)
    try:
        yield context
    except KeyboardInterrupt:
        context.exit_code = 130
        context.completion = "interrupted"
        raise
    finally:
        # Restore invocation isolation even if building the optional receipt fails.
        _CURRENT.reset(token)
        try:
            _persist(context.receipt())
        except Exception as exc:
            # The warning channel is optional too; never override the business
            # return value or an in-flight exception with a diagnostic failure.
            try:
                print(f"DIAGNOSTIC_WRITE_WARNING: {type(exc).__name__}", file=sys.stderr)
            except Exception:
                pass


def cmd_timings(args) -> int:
    rows, corrupt = [], 0
    limit = int(args.limit)
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be 1..10000")
    for path in sorted(_root().glob("*.json"), reverse=True):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict) or row.get("schema") != "tp-spec.cli-timing/v1":
                raise ValueError("unknown diagnostic schema")
            if (not isinstance(row.get("invocation_id"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", row["invocation_id"])
                    or not isinstance(row.get("command"), str)
                    or type(row.get("exit_code")) is not int
                    or type(row.get("total_ms")) not in (int, float)
                    or not math.isfinite(row["total_ms"]) or row["total_ms"] < 0
                    or not isinstance(row.get("segments"), dict)):
                raise ValueError("malformed diagnostic receipt")
            for segment in row["segments"].values():
                if (not isinstance(segment, dict)
                        or type(segment.get("calls")) is not int or segment["calls"] < 0
                        or type(segment.get("elapsed_ms")) not in (int, float)
                        or not math.isfinite(segment["elapsed_ms"]) or segment["elapsed_ms"] < 0
                        or not isinstance(segment.get("status"), str)
                        or segment["status"] not in {"not_entered", "completed", "failed"}
                        or (segment["status"] == "not_entered" and (segment["calls"] != 0 or segment["elapsed_ms"] != 0))
                        or (segment["status"] != "not_entered" and segment["calls"] == 0)):
                    raise ValueError("malformed diagnostic segment")
        except (OSError, ValueError, OverflowError):
            corrupt += 1
            continue
        if args.task and row.get("task_id") != args.task:
            continue
        if args.invocation and row.get("invocation_id") != args.invocation:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    result = {"schema": "tp-spec.cli-timings/v1", "records": rows, "corrupt_records_skipped": corrupt}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['invocation_id']}  {row['command']}  rc={row['exit_code']}  {row['total_ms']:.3f} ms")
        if corrupt:
            print(f"DIAGNOSTIC_CORRUPT: {corrupt}", file=sys.stderr)
    return 0
