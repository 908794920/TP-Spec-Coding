# -*- coding: utf-8 -*-
"""Logical receipts and explicit artifact collection on the existing task ledger.

A retry refers to one past operation, never to a new test run or a current PASS.
Collection copies supplied outputs; it does not execute tools or certify results.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable
import uuid

from . import command_context, event_contract
from .evidence import validate_evidence_path


class RequestReplay(ValueError):
    def __init__(self, result: dict[str, Any]):
        super().__init__("logical request already committed")
        self.result = result


class LogicalRequest:
    def __init__(self, task_id: str, task_dir: Path, operation: str,
                 payload: dict[str, Any], request_id: str | None):
        self.task_id = task_id
        self.task_dir = task_dir
        self.operation = operation
        self.result_report_count = len(payload.get("result_reports") or [])
        self.report_artifact_root = payload.get("report_artifact_root")
        self.recorded_result_ids = list(payload.get("recorded_result_ids") or [])
        self.explicit = request_id is not None
        self.request_id = request_id if request_id is not None else uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", self.request_id):
            raise ValueError("REQUEST_ID_INVALID: use 1-128 ASCII letters, digits, . _ : or -")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.payload_sha256 = hashlib.sha256(encoded).hexdigest()

    def detail(self, response: dict[str, Any]) -> dict[str, Any]:
        return {"request_id": self.request_id, "operation": self.operation,
                "payload_sha256": self.payload_sha256, "response": dict(response)}

    def replay(self, conn) -> dict[str, Any] | None:
        if not self.explicit:
            return None
        rows = conn.execute(
            "SELECT * FROM task_event WHERE task_id=? "
            "AND event_type IN ('FACT','VERIFICATION_COMPLETED') ORDER BY id", (self.task_id,))
        found = None
        for row in rows:
            raw = str(row["detail_json"] or "{}")
            try:
                detail = json.loads(raw)
            except (ValueError, TypeError) as exc:
                if '"logical_request"' in raw:
                    raise ValueError("REQUEST_RECORD_INVALID: repair ledger through reconciliation") from exc
                continue
            if not isinstance(detail, dict):
                continue
            saved = detail.get("logical_request")
            if not isinstance(saved, dict) or saved.get("request_id") != self.request_id:
                continue
            if (detail.get("producer") != "record-first" or not detail.get("transaction_id")
                    or detail.get("schema") != event_contract.EVENT_SCHEMA):
                raise ValueError("REQUEST_RECORD_INVALID: logical receipt is not a trusted record-first event")
            if saved.get("operation") != self.operation or saved.get("payload_sha256") != self.payload_sha256:
                raise ValueError("REQUEST_ID_CONFLICT: the ID belongs to different semantics; use a new ID for new work")
            if found is not None or not isinstance(saved.get("response"), dict):
                raise ValueError("REQUEST_RECORD_INVALID: duplicate or malformed receipt; reconcile before retrying")
            response = saved["response"]
            expected_type = "FACT" if self.operation == "checkpoint" else "VERIFICATION_COMPLETED"
            if (response.get("task_id") != self.task_id or response.get("request_id") != self.request_id
                    or not response.get("flush_id") or response["flush_id"] != detail.get("flush_id")
                    or detail.get("operation") != self.operation.upper() or row["event_type"] != expected_type
                    or response.get("state") != "ACTIVE" or not response.get("phase")
                    or (self.operation == "verify" and response.get("decision") != detail.get("decision"))):
                raise ValueError("REQUEST_RECORD_INVALID: receipt does not match its committed event")
            if (response.get("summary") != row["summary"]
                    or response.get("change_set_id") != detail.get("change_set_id")
                    or (self.operation == "checkpoint" and (
                        response.get("actor") != row["actor_role"] or response.get("phase") != detail.get("phase")))
                    or (self.operation == "verify" and (
                        row["actor_role"] != "tp-test-engineer"
                        or response.get("verification_scope", "full") != detail.get("verification_scope", "full")
                        or response.get("checks", []) != detail.get("checks", [])))):
                raise ValueError("REQUEST_RECORD_INVALID: response changes the recorded actor, subject or scope")
            items = detail.get("evidence_items", [])
            if not isinstance(items, list):
                raise ValueError("REQUEST_RECORD_INVALID: malformed evidence items")
            if self.operation == "checkpoint" and response.get("collected_artifacts", []) != items:
                raise ValueError("REQUEST_RECORD_INVALID: response substituted the original evidence inventory")
            validate_bound_items(self.task_dir, items, replay=True)
            self._validate_observations(conn, detail, response)
            expected = recorded_results(conn, self.task_id, self.task_dir, self.recorded_result_ids)
            if (detail.get("recorded_results", []) != expected or response.get("recorded_results", []) != expected):
                raise ValueError("REQUEST_RECORD_INVALID: recorded result references changed")
            found = {**response, "replayed": True, "facts_committed": True,
                     "receipt_event_id": int(row["id"]), "view_status": "NOT_REFRESHED",
                     "result_scope": "original logical request, not current task state or a new execution"}
        context = command_context.current()
        if found is not None and context is not None:
            context.bindings.update({"request_id": self.request_id,
                                     "receipt_event_id": found["receipt_event_id"], "replayed": True})
        return found

    def _validate_observations(self, conn, detail: dict, response: dict) -> None:
        observations = response.get("result_observations")
        if not self.result_report_count and observations is None:
            return  # Legacy requests have no report observations to replay.
        if not isinstance(observations, list) or len(observations) != self.result_report_count:
            raise ValueError("REQUEST_RECORD_INVALID: report observation list changed")
        rows = conn.execute(
            "SELECT * FROM task_event WHERE task_id=? AND event_type='OBSERVATION' ORDER BY id",
            (self.task_id,)).fetchall()
        matching = []
        for row in rows:
            try:
                payload = json.loads(row["detail_json"] or "{}")
            except (TypeError, ValueError):
                # Only an associated observation can affect this request. The
                # expected event IDs are checked even if their detail is corrupt.
                payload = {}
            if isinstance(payload, dict) and payload.get("flush_id") == detail.get("flush_id"):
                matching.append((row, payload))
        if not isinstance(observations, list) or not observations or len(matching) != len(observations):
            raise ValueError("REQUEST_RECORD_INVALID: missing or duplicate batch observation")
        from .execution_reports import read_report
        for recorded, (row, payload) in zip(observations, matching):
            if not isinstance(recorded, dict) or type(recorded.get("event_id")) is not int:
                raise ValueError("REQUEST_RECORD_INVALID: malformed observation reference")
            report = {key: value for key, value in recorded.items() if key != "event_id"}
            if (row["id"] != recorded["event_id"] or row["actor_role"] != response.get("actor")
                    or payload.get("transaction_id") != detail.get("transaction_id")
                    or payload.get("producer") != "record-first" or payload.get("schema") != event_contract.EVENT_SCHEMA
                    or payload.get("operation") != "RECORD" or payload.get("result_status") != "RECORDED"
                    or payload.get("task_id") != self.task_id
                    or payload.get("actor_role") != response.get("actor")
                    or not any(report.get("evidence") == {key: item.get(key) for key in ("type", "path", "sha256")}
                               for item in detail.get("evidence_items", []))
                    or payload.get("execution_report") != report):
                raise ValueError("REQUEST_RECORD_INVALID: observation does not match the committed batch")
            try:
                actual = read_report(self.task_dir, report.get("evidence"), task_id=self.task_id)
                if self.report_artifact_root is not None:
                    from .browser_reports import bind_attachments
                    actual = bind_attachments(self.task_dir, actual, detail.get("evidence_items", []))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("REQUEST_RECORD_INVALID: invalid observation evidence") from exc
            if actual != report:
                raise ValueError("REQUEST_RECORD_INVALID: observation disagrees with original report")

    def reject_duplicate(self, conn) -> None:
        result = self.replay(conn)
        if result is not None:
            raise RequestReplay(result)


def checkpoint_request(task_id: str, task_dir: Path, request_id: str | None, *,
                       actor: str, phase: str, summary: str, evidence=(),
                       knowledge_signals=(), delivery_signals=(), repo_roots=(),
                       collect=(), context_usage=(), result_reports=(), recorded_result_ids=(),
                       report_artifact_root=None) -> LogicalRequest:
    """One payload definition for checkpoint writes and read-only recovery."""
    return LogicalRequest(task_id, task_dir, "checkpoint", {
        "actor": actor, "phase": phase, "summary": summary, "evidence": list(evidence),
        "knowledge_signals": list(knowledge_signals), "delivery_signals": list(delivery_signals),
        "repo_roots": list(repo_roots), "collect": list(collect), "context_usage": list(context_usage),
        **({"result_reports": list(result_reports)} if result_reports else {}),
        **({"recorded_result_ids": list(recorded_result_ids)} if recorded_result_ids else {}),
        **({"report_artifact_root": report_artifact_root} if report_artifact_root is not None else {}),
    }, request_id)


def validate_bound_items(task_dir: Path, items: Iterable[dict], *, replay: bool = False) -> None:
    code = "REQUEST_EVIDENCE_CHANGED" if replay else "EVIDENCE_CHANGED_BEFORE_COMMIT"
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("sha256"), str):
            raise ValueError(f"{code}: malformed bound evidence identity")
        checked = validate_evidence_path(task_dir, item, require_evidence_dir=True)
        if not checked.ok or checked.item.get("sha256") != item.get("sha256"):
            raise ValueError(f"{code}: restore the recorded evidence; do not rerun an already committed operation")


def _limits() -> tuple[int, int]:
    from .orchestration import load_contract
    values = load_contract().get("execution", {}).get("artifact_collection", {})
    if not isinstance(values, dict) or set(values) - {"max_files", "max_file_bytes"}:
        raise ValueError("ARTIFACT_COLLECTION_CONFIG_INVALID")
    limits = (values.get("max_files", 128), values.get("max_file_bytes", 268_435_456))
    if any(type(value) is not int or value < 1 for value in limits):
        raise ValueError("ARTIFACT_COLLECTION_CONFIG_INVALID: limits must be positive integers")
    return limits


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


@contextmanager
def _collection_stream(path: Path, source_root: Path | None):
    """Open scoped media without following a link swapped after report preflight."""
    if source_root is None:
        with path.open("rb") as stream:
            yield stream
        return
    if not path.is_absolute() or not path.is_relative_to(source_root):
        raise ValueError("ARTIFACT_SOURCE_OUTSIDE_ROOT")
    fd = None
    try:
        if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
            directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for component in path.parts[1:-1]:
                    following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory)
                    directory = following
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            finally:
                os.close(directory)
        elif os.name == "nt":
            # Verify the opened handle, not another path lookup, before reading.
            # This also rejects a parent junction redirected during preflight.
            import ctypes
            from ctypes import wintypes
            import msvcrt
            fd = os.open(str(path), os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
            api = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
            api.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            api.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            size = api(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
            if not size or size >= len(buffer):
                raise ValueError("ARTIFACT_SOURCE_HANDLE_UNVERIFIED")
            opened = buffer.value
            if opened.startswith("\\\\?\\UNC\\"):
                opened = "\\\\" + opened[8:]
            elif opened.startswith("\\\\?\\"):
                opened = opened[4:]
            if os.path.normcase(opened) != os.path.normcase(str(path)):
                raise ValueError("ARTIFACT_SOURCE_LINK_CHANGED")
        else:
            raise ValueError("ARTIFACT_SCOPED_OPEN_UNSUPPORTED: use explicitly reviewed --collect files")
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("ARTIFACT_SOURCE_NOT_REGULAR")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            yield stream
    finally:
        if fd is not None:
            os.close(fd)


def _trusted_collection_dir(base: Path, directory: Path) -> None:
    """Reject a collection directory that was replaced or redirected."""
    try:
        resolved = directory.resolve()
        if directory.is_symlink() or not directory.is_dir() or not resolved.is_relative_to(base):
            raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE")
    except OSError as exc:
        raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE") from exc


@contextmanager
def _posix_collection_directory(base: Path, directory: Path):
    """Pin every collection-directory component before creating output."""
    required = {"O_DIRECTORY", "O_NOFOLLOW"}
    supports_dir_fd = getattr(os, "supports_dir_fd", ())
    if (os.open not in supports_dir_fd or os.stat not in supports_dir_fd
            or os.rename not in supports_dir_fd or os.unlink not in supports_dir_fd
            or any(not hasattr(os, name) for name in required)):
        raise ValueError("ARTIFACT_COLLECTION_SCOPED_OUTPUT_UNSUPPORTED")
    try:
        relative = directory.relative_to(base)
    except ValueError as exc:
        raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    handle = os.open(str(base), flags)
    try:
        for component in relative.parts:
            child = os.open(component, flags, dir_fd=handle)
            os.close(handle)
            handle = child
        yield handle
    finally:
        os.close(handle)


def _open_posix_collection_temp(directory_handle: int) -> tuple[str, int]:
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
             | getattr(os, "O_CLOEXEC", 0))
    for _ in range(16):
        name = f".collect-{uuid.uuid4().hex}"
        try:
            return name, os.open(name, flags, 0o600, dir_fd=directory_handle)
        except FileExistsError:
            continue
        except FileNotFoundError as exc:
            # The pinned directory may have been removed after preflight.  Keep
            # the failure closed and expose the stable collection-boundary error
            # instead of leaking a platform-specific errno.
            raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE") from exc
    raise ValueError("ARTIFACT_COLLECTION_TEMP_CONFLICT")


def _collect_artifacts_windows(base: Path, request_id: str, paths: list[str], max_bytes: int,
                               source_root: Path | None) -> list[dict[str, Any]]:
    """Collect through rooted Windows handles; never write through a path string."""
    from . import windows_collection

    request_key = hashlib.sha256(request_id.encode("ascii")).hexdigest()[:24]
    attempt_name = f"a-{uuid.uuid4().hex[:12]}"
    artifacts = []
    with windows_collection.attempt(base, request_key, attempt_name) as (attempt_dir, attempt_handle):
        for index, raw in enumerate(paths):
            source = (Path(os.path.abspath(Path(raw).expanduser())) if source_root is not None
                      else Path(raw).expanduser().resolve())
            with _collection_stream(source, source_root) as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError(f"ARTIFACT_COLLECTION_INVALID: not a regular file: {source}")
                if before.st_size < 1 or before.st_size > max_bytes:
                    raise ValueError(f"ARTIFACT_COLLECTION_LIMIT: file must contain 1..{max_bytes} bytes: {source}")
                suffix = source.suffix.lower()
                if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                    suffix = ".bin"
                target_name = f"{index:03d}{suffix}"
                digest = hashlib.sha256()
                size = 0
                with windows_collection.output(attempt_handle, target_name) as dest:
                    try:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            size += len(block)
                            if size > max_bytes:
                                raise ValueError("ARTIFACT_COLLECTION_LIMIT: source grew during collection")
                            digest.update(block)
                            dest.write(block)
                        sha = digest.hexdigest()
                        after = source.stat(follow_symlinks=False)
                        signature = lambda value: (value.st_size, value.st_mtime_ns, value.st_ino, value.st_dev)
                        stream.seek(0)
                        again = hashlib.sha256()
                        reread_bytes = 0
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            reread_bytes += len(block)
                            if reread_bytes > max_bytes:
                                raise ValueError("ARTIFACT_COLLECTION_LIMIT: source grew during stability check")
                            again.update(block)
                        if (signature(before) != signature(after) or signature(before) != signature(os.fstat(stream.fileno()))
                                or size != before.st_size or again.hexdigest() != sha):
                            raise ValueError("ARTIFACT_SOURCE_CHANGED: collect only a stable completed output")
                        windows_collection.verify(dest, sha, size)
                    except BaseException:
                        # This call has not returned an inventory and therefore
                        # cannot have been submitted.  Delete only this known
                        # uncommitted object through its still-open handle.
                        windows_collection.discard(dest)
                        raise
            # The bytes were written through the pinned handle.  Re-check the
            # presentation path before returning a reference so a replacement
            # cannot publish an evidence path that later resolves elsewhere.
            _trusted_collection_dir(base, attempt_dir)
            rel = (attempt_dir / target_name).relative_to(base).as_posix()
            artifacts.append({"type": "local_file", "path": rel, "sha256": sha,
                              "source_name": source.name, "size_bytes": size,
                              "collection": "explicit local output copy; not execution or acceptance"})
    return artifacts


@command_context.measured("evidence")
def collect_artifacts(task_dir: Path, request_id: str, sources: Iterable[str], *,
                      source_root: Path | None = None) -> list[dict[str, Any]]:
    paths = list(sources)
    if not paths:
        return []
    max_files, max_bytes = _limits()
    if len(paths) > max_files:
        raise ValueError(f"ARTIFACT_COLLECTION_LIMIT: at most {max_files} explicit files")
    base = task_dir.resolve()
    if os.name == "nt":
        return _collect_artifacts_windows(base, request_id, paths, max_bytes, source_root)
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _trusted_collection_dir(base, evidence_dir)
    collection_dir = evidence_dir / "collected"
    collection_dir.mkdir(parents=True, exist_ok=True)
    _trusted_collection_dir(base, collection_dir)
    request_key = hashlib.sha256(request_id.encode("ascii")).hexdigest()[:24]
    request_dir = collection_dir / request_key
    request_dir.mkdir(parents=True, exist_ok=True)
    _trusted_collection_dir(base, request_dir)
    # This name only scopes one physical collection attempt; it is never a
    # logical request identifier.  Keep it short enough for Windows temporary
    # task roots, where a full UUID plus a SHA-256 filename can cross the
    # traditional 260-character Win32 path boundary.
    attempt_dir = request_dir / f"a-{uuid.uuid4().hex[:12]}"
    try:
        attempt_dir.mkdir()
    except FileExistsError as exc:
        raise ValueError("ARTIFACT_COLLECTION_ATTEMPT_CONFLICT") from exc
    _trusted_collection_dir(base, attempt_dir)
    artifacts = []
    with _posix_collection_directory(base, attempt_dir) as attempt_handle:
        for index, raw in enumerate(paths):
            source = (Path(os.path.abspath(Path(raw).expanduser())) if source_root is not None
                      else Path(raw).expanduser().resolve())
            temp_name = None
            temp_handle = None
            try:
                with _collection_stream(source, source_root) as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError(f"ARTIFACT_COLLECTION_INVALID: not a regular file: {source}")
                    if before.st_size < 1 or before.st_size > max_bytes:
                        raise ValueError(f"ARTIFACT_COLLECTION_LIMIT: file must contain 1..{max_bytes} bytes: {source}")
                    # The directory handle is pinned; path replacement cannot
                    # redirect this output to a location outside task evidence.
                    temp_name, temp_handle = _open_posix_collection_temp(attempt_handle)
                    with os.fdopen(temp_handle, "wb") as dest:
                        temp_handle = None
                        digest = hashlib.sha256()
                        size = 0
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            size += len(block)
                            if size > max_bytes:
                                raise ValueError("ARTIFACT_COLLECTION_LIMIT: source grew during collection")
                            digest.update(block)
                            dest.write(block)
                    after = source.stat(follow_symlinks=False)
                    # Windows may return a path-level ctime that differs from the
                    # already-open handle even when the file did not change.  The
                    # stable identity/content checks below rely on size, mtime,
                    # device/inode and the independent reread digest instead.
                    signature = lambda value: (value.st_size, value.st_mtime_ns, value.st_ino, value.st_dev)
                    sha = digest.hexdigest()
                    stream.seek(0)
                    again = hashlib.sha256()
                    reread_bytes = 0
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        reread_bytes += len(block)
                        if reread_bytes > max_bytes:
                            raise ValueError("ARTIFACT_COLLECTION_LIMIT: source grew during stability check")
                        again.update(block)
                    if (signature(before) != signature(after) or signature(before) != signature(os.fstat(stream.fileno()))
                            or size != before.st_size or again.hexdigest() != sha):
                        raise ValueError("ARTIFACT_SOURCE_CHANGED: collect only a stable completed output")
                suffix = source.suffix.lower()
                if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                    suffix = ".bin"
                # The attempt directory is exclusive, so the ordinal is sufficient
                # as a physical filename.  The full SHA-256 remains verified and
                # recorded in the evidence item rather than being duplicated in a
                # path that can exceed Windows path limits.
                target_name = f"{index:03d}{suffix}"
                try:
                    os.stat(target_name, dir_fd=attempt_handle, follow_symlinks=False)
                except FileNotFoundError:
                    os.replace(temp_name, target_name, src_dir_fd=attempt_handle, dst_dir_fd=attempt_handle)
                    temp_name = None
                else:
                    raise ValueError("ARTIFACT_DESTINATION_CONFLICT: existing evidence will not be overwritten")
                target = attempt_dir / target_name
                # The handle pins the write; this check protects the returned
                # presentation path if its parents were replaced concurrently.
                _trusted_collection_dir(base, attempt_dir)
                rel = target.relative_to(base).as_posix()
                checked = validate_evidence_path(base, rel, require_evidence_dir=True)
                if not checked.ok or checked.item["sha256"] != sha:
                    raise ValueError("ARTIFACT_COPY_INVALID")
                artifacts.append({**checked.item, "source_name": source.name, "size_bytes": size,
                                  "collection": "explicit local output copy; not execution or acceptance"})
            finally:
                if temp_handle is not None:
                    os.close(temp_handle)
                if temp_name is not None:
                    try:
                        os.unlink(temp_name, dir_fd=attempt_handle)
                    except FileNotFoundError:
                        pass
    return artifacts


def recorded_results(conn, task_id: str, task_dir: Path, event_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Reference already accepted results, without changing their authors or scopes.

    This is not an import path for untrusted review JSON or a new PASS producer.
    Current delivery gates still select/check their own original latest events.
    """
    from . import event_policies, workflow_controls
    ids = list(event_ids)
    if (len(ids) > _limits()[0] or any(type(value) is not int or value < 1 for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("RECORDED_RESULT_INVALID: expected distinct positive event IDs within collection limit")
    out = []
    for event_id in ids:
        row = conn.execute("SELECT * FROM task_event WHERE task_id=? AND id=?", (task_id, event_id)).fetchone()
        if row is None:
            raise ValueError("RECORDED_RESULT_INVALID: event does not belong to this task")
        try:
            detail = json.loads(row['detail_json'] or '{}')
            if not isinstance(detail, dict):
                raise ValueError('invalid detail')
            event_type = row['event_type']
            if (detail.get('schema') != event_contract.EVENT_SCHEMA or not detail.get('transaction_id')):
                raise ValueError('missing original producer binding')
            from .version import active_version
            if detail.get('schema_version') != active_version():
                raise ValueError('original result contract differs')
            items = detail.get('evidence_items', [])
            if not isinstance(items, list):
                raise ValueError('invalid original evidence list')
            validate_bound_items(task_dir, items)
            if event_type == 'FACT':
                if (detail.get('producer') != 'record-first' or detail.get('operation') != 'CHECKPOINT'
                        or detail.get('phase') != 'development' or row['actor_role'] != 'tp-development-engineer'
                        or not detail.get('change_set_id')):
                    raise ValueError('not a recorded development result')
            elif event_type in {'VERIFICATION_COMPLETED', 'REVIEW_COMPLETED'}:
                expected_actor = 'tp-test-engineer' if event_type == 'VERIFICATION_COMPLETED' else 'tp-code-reviewer'
                if row['actor_role'] != expected_actor:
                    raise ValueError('invalid original actor')
                if event_type == 'VERIFICATION_COMPLETED':
                    event_policies.verification_scope(detail)
                elif detail.get('verification_scope', 'full') not in {'full', 'technical'}:
                    raise ValueError('unknown review scope')
                options = {}
                if event_type == 'REVIEW_COMPLETED':
                    if detail.get('review_kind') not in {'CODE', 'IMPLEMENTATION', 'ULTRA_REVIEW'}:
                        raise ValueError('unsupported review kind')
                    artifact = task_dir / str(detail.get('artifact') or '')
                    if not artifact.resolve().is_relative_to(task_dir.resolve()) or not artifact.is_file():
                        raise ValueError('invalid review artifact')
                    options['artifact_path'] = artifact
                matches = event_policies.load_trusted_governance_events(
                    conn, task_id, event_type=event_type, actor=expected_actor,
                    evidence_dir=task_dir if detail.get('decision') == 'PASS' else None, **options)
                if not any(entry.row['id'] == event_id for entry in matches):
                    raise ValueError('original formal result is not trustworthy')
            else:
                raise ValueError('not a supported recorded result')
        except (ValueError, TypeError, OSError, KeyError) as exc:
            raise ValueError(f'RECORDED_RESULT_INVALID: event {event_id}: {exc}') from exc
        out.append({
            'event_id': event_id, 'event_digest': workflow_controls.event_digest(dict(row)),
            'event_type': event_type, 'actor': row['actor_role'], 'created_at': row['created_at'],
            'decision': detail.get('decision'), 'verification_scope': detail.get('verification_scope', 'full')
                if event_type != 'FACT' else None,
            'checks': detail.get('checks', []), 'review_kind': detail.get('review_kind'),
            'change_set_id': detail.get('change_set_id'), 'subject_digest': detail.get('subject_digest'),
            'evidence_items': items, 'authority': 'original_event_only',
            'applicability': 'historical reference; no new current PASS or independent identity attestation',
        })
    return out
