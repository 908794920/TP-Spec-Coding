"""Isolate one Wiki maintenance draft and recover its directory publication."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Iterator
import uuid


def _safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(Path(path).expanduser()))
    for entry in (*reversed(path.parents), path):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("WIKI_CANDIDATE_UNSAFE_PATH: links and junctions are not supported")
    return path


def candidate_paths(canonical: Path) -> dict[str, Path]:
    canonical = _safe_path(Path(canonical))
    if canonical == canonical.parent:
        raise ValueError("WIKI_CANDIDATE_UNSAFE_PATH: a repository directory is required")
    root = _safe_path(canonical.parent / f".{canonical.name}.tp-wiki-candidate")
    paths = {"canonical": canonical, "root": root,
             "previous": root / "previous", "state": root / "state.json", "lock": root / "operation.lock"}
    for path in paths.values():
        _safe_path(path)
    data = _state(paths)
    paths["wiki"] = _safe_path(root / data.get("candidate_dir", "wiki"))
    paths["candidate"] = paths["wiki"]
    return paths


def _tree(path: Path) -> str:
    """Bind all names, directory types and file bytes, including volatile metadata."""
    _safe_path(path)
    if not path.exists():
        return "MISSING"
    if not path.is_dir():
        raise ValueError("WIKI_CANDIDATE_UNSAFE_PATH: Wiki root is not a directory")
    digest = hashlib.sha256(b"wiki-tree-v1\0")
    for entry in sorted(path.rglob("*")):
        _safe_path(entry)
        info = entry.lstat()
        digest.update(entry.relative_to(path).as_posix().encode("utf-8"))
        if stat.S_ISDIR(info.st_mode):
            digest.update(b"\0directory\n")
        elif stat.S_ISREG(info.st_mode):
            data = entry.read_bytes()
            after = entry.stat()
            if (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError("WIKI_CANDIDATE_CONFLICT: directory changed while reading")
            digest.update(b"\0file\0" + hashlib.sha256(data).digest() + b"\n")
        else:
            raise ValueError("WIKI_CANDIDATE_UNSAFE_PATH: unsupported filesystem entry")
    return digest.hexdigest()


def _rename_absent(source: Path, destination: Path) -> None:
    """Keep an independently created destination, including an empty directory."""
    _safe_path(source)
    _safe_path(destination)
    if destination.exists():
        raise ValueError("WIKI_CANDIDATE_CONFLICT: rename destination already exists")
    if os.name == "nt":
        os.rename(source, destination)  # Windows rename never replaces a destination.
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ValueError("WIKI_CANDIDATE_PUBLICATION_UNSUPPORTED: no safe non-replacing directory rename")
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _state(paths: dict[str, Path]) -> dict[str, Any]:
    _safe_path(paths["state"])
    if not paths["state"].exists():
        return {}
    data = json.loads(paths["state"].read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != "tp-spec.wiki-candidate/v1"
            or data.get("canonical") != str(paths["canonical"])
            or data.get("phase") not in {"active", "publishing", "published", "abandoned"}
            or not isinstance(data.get("old_tree"), str)):
        raise ValueError("WIKI_CANDIDATE_STATE_INVALID")
    if "candidate_dir" in data and (not isinstance(data["candidate_dir"], str) or
            re.fullmatch(r"wiki-[0-9a-f]{32}", data["candidate_dir"]) is None):
        raise ValueError("WIKI_CANDIDATE_STATE_INVALID: unsafe candidate directory name")
    return data


def _write_state(paths: dict[str, Path], data: dict[str, Any]) -> None:
    temporary = paths["root"] / f"state-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(paths["state"])
        os.replace(temporary, paths["state"])
    finally:
        temporary.unlink(missing_ok=True)


def _isolate_git(canonical: Path, *, apply: bool) -> dict[str, Any]:
    pattern = b".*.tp-wiki-candidate/"
    for parent in canonical.parents:
        if (parent / ".git").exists():
            ignore = _safe_path(parent / ".gitignore")
            before = ignore.read_bytes() if ignore.exists() else b""
            present = before.splitlines()[-1:] == [pattern]
            if apply and not present:
                with ignore.open("ab") as stream:
                    stream.write((b"\n" if before and not before.endswith(b"\n") else b"") + pattern + b"\n")
            return {"path": str(ignore), "status": "CURRENT" if present else ("UPDATED" if apply else "PLANNED")}
    return {"status": "NOT_IN_GIT"}


@contextmanager
def _operation(paths: dict[str, Path]) -> Iterator[None]:
    _isolate_git(paths["canonical"], apply=True)
    paths["root"].mkdir(parents=True, exist_ok=True)
    _safe_path(paths["root"])
    _safe_path(paths["lock"])
    with paths["lock"].open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("WIKI_CANDIDATE_BUSY: another maintenance operation is running") from exc
        try:
            # Another operation may have changed the selected round before this lock.
            paths.update(candidate_paths(paths["canonical"]))
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _remove_owned_tree(paths: dict[str, Path], path: Path, expected: str) -> None:
    path = _safe_path(path)
    if (path.parent != paths["root"] or
            not (path.name == "previous" or re.fullmatch(r"draft-[0-9a-f]{32}", path.name))):
        raise ValueError("WIKI_CANDIDATE_UNSAFE_PATH: cleanup target is not an owned child")
    if any(entry.name == ".git" for entry in path.rglob("*")):
        raise ValueError("WIKI_CANDIDATE_UNSAFE_PATH: embedded Git repository retained")
    if _tree(path) != expected:
        raise ValueError("WIKI_CANDIDATE_CONFLICT: cleanup target changed; retained")
    shutil.rmtree(path)


def _cleanup_retired(paths: dict[str, Path], data: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    records = data.get("retired_drafts", [])
    if not isinstance(records, list):
        raise ValueError("WIKI_CANDIDATE_STATE_INVALID: retired drafts must be a list")
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("name"), str)
                or re.fullmatch(r"draft-[0-9a-f]{32}", record["name"]) is None
                or not isinstance(record.get("tree"), str)
                or re.fullmatch(r"[0-9a-f]{64}", record["tree"]) is None):
            raise ValueError("WIKI_CANDIDATE_STATE_INVALID: invalid retirement identity")
    result = {"eligible": [], "removed": [], "retained": [], "cleanup_pending": []}
    expected = data.get("new_tree") if data.get("phase") == "published" else data.get("old_tree")
    ready = data.get("phase") != "publishing" and _tree(paths["canonical"]) == expected
    remaining = []
    for index, record in enumerate(records):
        path = paths["root"] / record["name"]
        if not path.exists():
            continue
        remaining.append(record)
        if not ready or (data.get("phase") != "published" and index == len(records) - 1):
            result["retained"].append({"path": str(path), "reason": "recovery pending, canonical changed, or latest failed draft"})
            continue
        try:
            _safe_path(path)
            if any(entry.name == ".git" for entry in path.rglob("*")) or _tree(path) != record["tree"]:
                result["retained"].append({"path": str(path), "reason": "retired tree changed or contains Git metadata"})
                continue
            result["eligible"].append(str(path))
            if apply:
                _remove_owned_tree(paths, path, record["tree"])
                remaining.pop()
                result["removed"].append(str(path))
        except (OSError, ValueError) as exc:
            result["cleanup_pending"].append(f"{path}: {exc}")
    known = {r["name"] for r in records}
    for path in paths["root"].iterdir():
        if path.is_dir() and path.name not in known:
            result["retained"].append({"path": str(path), "reason": "active, recovery copy, or no retirement record"})
    if apply and records != remaining:
        data["retired_drafts"] = remaining
        _write_state(paths, data)
    return result


def _legacy_retirements(paths: dict[str, Path], data: dict[str, Any], receipts: list[Path]) -> list[dict[str, str]]:
    """Adopt only receipted legacy discards with no unique durable Wiki bytes."""
    from .subject import subject_files

    if data.get("phase") != "published" or _tree(paths["canonical"]) != data.get("new_tree"):
        return []
    baseline = json.loads((paths["canonical"] / "meta/wiki-snapshot.json").read_text(encoding="utf-8"))
    if (baseline.get("schema") != "tp-spec.wiki-snapshot/v1" or not baseline.get("repo_id")
            or (baseline.get("completion") or {}).get("status") != "SUCCESS"):
        return []
    def payload(root):
        files = subject_files(root)
        files.pop("meta/wiki-manifest.yaml", None)
        return files
    current = payload(paths["canonical"])
    found = {}
    for receipt in receipts:
        raw = Path(receipt).read_bytes()
        saved = json.loads(raw.decode("utf-8"))
        if saved.get("schema") != "tp-spec.wiki-maintain/v1":
            raise ValueError("WIKI_CANDIDATE_RETIREMENT_INVALID: expected a maintain receipt")
        for row in saved.get("results", []):
            if row.get("published_wiki_repo_root") != str(paths["canonical"]):
                continue
            retired = row.get("previous_candidate") or {}
            if retired.get("status") != "DISCARDED" or not retired.get("draft_path"):
                continue
            path = _safe_path(Path(retired["draft_path"]))
            if path.parent != paths["root"] or re.fullmatch(r"draft-[0-9a-f]{32}", path.name) is None:
                raise ValueError("WIKI_CANDIDATE_RETIREMENT_INVALID: receipt target outside candidate root")
            if not path.exists():
                continue
            tree = _tree(path)
            old = json.loads((path / "meta/wiki-snapshot.json").read_text(encoding="utf-8"))
            if (old.get("schema") != "tp-spec.wiki-snapshot/v1"
                    or old.get("repo_id") != baseline.get("repo_id") or payload(path) != current):
                continue
            found[path.name] = {"name": path.name, "tree": tree,
                                "receipt": str(receipt), "receipt_sha256": hashlib.sha256(raw).hexdigest()}
    return list(found.values())


def cleanup_candidate(canonical: Path, *, apply: bool = False, retirement_receipts: list[Path] = ()) -> dict[str, Any]:
    paths = candidate_paths(canonical)
    isolation = _isolate_git(paths["canonical"], apply=False)
    if not paths["root"].exists():
        return {"status": "NO_CANDIDATE", "git_isolation": _isolate_git(paths["canonical"], apply=apply)}
    # A plan is advisory and read-only; apply rechecks every identity under the lock.
    with _operation(paths) if apply else nullcontext():
        data = _state(paths)
        records = data.get("retired_drafts", [])
        adopted = _legacy_retirements(paths, data, retirement_receipts) if retirement_receipts else []
        names = {record["name"] for record in records}
        adopted = [record for record in adopted if record["name"] not in names]
        if adopted:
            data["retired_drafts"] = records + adopted
            if apply:
                _write_state(paths, data)
        result = _cleanup_retired(paths, data, apply=apply)
        if data.get("phase") == "published" and paths["previous"].exists():
            if _tree(paths["canonical"]) == data.get("new_tree"):
                if apply:
                    result["cleanup_pending"].extend(_cleanup_previous(paths, data))
                    if not paths["previous"].exists():
                        result["removed"].append(str(paths["previous"]))
                        result["retained"] = [row for row in result["retained"] if row["path"] != str(paths["previous"])]
                elif _tree(paths["previous"]) == data.get("old_tree"):
                    result["eligible"].append(str(paths["previous"]))
        return {"status": "WARN" if result["cleanup_pending"] else ("APPLIED" if apply else "PLAN"),
                "phase": data.get("phase"), "adopted_retirements": adopted,
                "git_isolation": _isolate_git(paths["canonical"], apply=False) if apply else isolation, **result}


def _cleanup_previous(paths: dict[str, Path], data: dict[str, Any]) -> list[str]:
    if not paths["previous"].exists():
        return []
    try:
        if _tree(paths["canonical"]) != data.get("new_tree"):
            return ["previous: canonical changed; retained"]
        if _tree(paths["previous"]) != data["old_tree"]:
            return ["previous: contents changed; retained"]
        _remove_owned_tree(paths, paths["previous"], data["old_tree"])
        return []
    except (OSError, ValueError):
        return ["previous: cleanup pending"]


def _recover(paths: dict[str, Path]) -> dict[str, Any]:
    data = _state(paths)
    if data.get("phase") != "publishing":
        pending = _cleanup_previous(paths, data) if data.get("phase") == "published" else []
        return {"status": "NO_RECOVERY", "cleanup_pending": pending}
    old, new = data["old_tree"], data.get("new_tree")
    current, previous, draft = (_tree(paths[key]) for key in ("canonical", "previous", "wiki"))
    if current == new and draft == "MISSING" and previous in {old, "MISSING"}:
        data["phase"] = "published"
        _write_state(paths, data)
        return {"status": "PUBLISHED", "cleanup_pending": _cleanup_previous(paths, data)}
    if current == old and previous == "MISSING" and draft == new:
        data["phase"] = "abandoned"
        _write_state(paths, data)
        return {"status": "RESTORED_OLD", "cleanup_pending": []}
    if current == "MISSING" and previous == old and old != "MISSING" and draft == new:
        # rename refuses a newly appearing nonempty canonical directory; never replace it.
        if paths["canonical"].exists():
            raise ValueError("WIKI_CANDIDATE_CONFLICT: canonical reappeared during recovery")
        _rename_absent(paths["previous"], paths["canonical"])
        data["phase"] = "abandoned"
        _write_state(paths, data)
        return {"status": "RESTORED_OLD", "cleanup_pending": []}
    raise ValueError("WIKI_CANDIDATE_RECOVERY_CONFLICT: retain canonical, previous and draft for inspection")


def recover_publication(canonical: Path) -> dict[str, Any]:
    paths = candidate_paths(canonical)
    if not paths["root"].exists():
        return {"status": "NO_RECOVERY", "cleanup_pending": []}
    with _operation(paths):
        return _recover(paths)


def _discard(paths: dict[str, Path]) -> dict[str, Any]:
    _recover(paths)
    data = _state(paths)
    draft = None
    retained_previous = None
    if data.get("phase") == "published" and paths["previous"].exists():
        # A partial cleanup is retained; it must not block every later maintenance run.
        retained_previous = paths["root"] / f"previous-{uuid.uuid4().hex}"
        _rename_absent(paths["previous"], retained_previous)
    if paths["wiki"].exists():
        if not data:
            raise ValueError("WIKI_CANDIDATE_CONFLICT: unowned candidate directory already exists")
        retired_tree = _tree(paths["wiki"])
        draft = paths["root"] / f"draft-{uuid.uuid4().hex}"
        _rename_absent(paths["wiki"], draft)
        data.setdefault("retired_drafts", []).append({"name": draft.name, "tree": retired_tree})
    elif data.get("phase") == "active":
        raise ValueError("WIKI_CANDIDATE_STATE_INVALID: active draft is missing")
    if data and (draft or retained_previous):
        data["phase"] = "abandoned"
        _write_state(paths, data)
    cleanup = _cleanup_retired(paths, data, apply=True) if data else {}
    return {"status": "DISCARDED" if draft else "NO_CANDIDATE", "draft_path": str(draft) if draft else None,
            "retained_previous_path": str(retained_previous) if retained_previous else None, "retired_cleanup": cleanup}


def discard_candidate(canonical: Path) -> dict[str, Any]:
    paths = candidate_paths(canonical)
    if not paths["root"].exists():
        return {"status": "NO_CANDIDATE", "draft_path": None}
    with _operation(paths):
        return _discard(paths)


def begin_candidate(canonical: Path) -> Path:
    paths = candidate_paths(canonical)
    with _operation(paths):
        _discard(paths)
        if paths["previous"].exists():
            raise ValueError("WIKI_CANDIDATE_CONFLICT: previous publication cleanup remains pending")
        before = _tree(paths["canonical"])
        directory = f"wiki-{uuid.uuid4().hex}"
        paths["wiki"] = _safe_path(paths["root"] / directory)
        paths["candidate"] = paths["wiki"]
        data = {"schema": "tp-spec.wiki-candidate/v1", "canonical": str(paths["canonical"]),
                "phase": "abandoned", "old_tree": before, "candidate_dir": directory,
                "retired_drafts": _state(paths).get("retired_drafts", [])}
        _write_state(paths, data)
        if before == "MISSING":
            paths["wiki"].mkdir()
        else:
            shutil.copytree(paths["canonical"], paths["wiki"], symlinks=True)
        copied, after = _tree(paths["wiki"]), _tree(paths["canonical"])
        if before != after or (before != "MISSING" and copied != before):
            raise ValueError("WIKI_CANDIDATE_CONFLICT: canonical changed while copying")
        data["phase"] = "active"
        _write_state(paths, data)
    return paths["wiki"]


def active_candidate(canonical: Path) -> Path | None:
    paths = candidate_paths(canonical)
    data = _state(paths)
    if data.get("phase") == "publishing":
        raise ValueError("WIKI_PUBLICATION_INCOMPLETE: recover publication before maintenance")
    if data.get("phase") != "active":
        return None
    if not paths["wiki"].is_dir():
        raise ValueError("WIKI_CANDIDATE_STATE_INVALID: active draft is missing")
    return paths["wiki"]


def published_generation(canonical: Path) -> str:
    paths = candidate_paths(canonical)
    if _state(paths).get("phase") == "publishing":
        raise ValueError("WIKI_PUBLICATION_INCOMPLETE: published reads and indexing are blocked until recovery")
    baseline = _safe_path(paths["canonical"] / "meta" / "wiki-snapshot.json")
    identity = str(paths["canonical"].stat().st_ino) if paths["canonical"].exists() else "MISSING"
    raw = baseline.read_bytes() if baseline.is_file() else b""
    generation = hashlib.sha256(identity.encode("ascii") + b"\0" + raw).hexdigest()
    if _state(paths).get("phase") == "publishing":
        raise ValueError("WIKI_PUBLICATION_INCOMPLETE: publication began while reading")
    return generation


def assert_published_readable(canonical: Path) -> None:
    published_generation(canonical)


def publish_candidate(canonical: Path, *, expected_candidate: Path) -> dict[str, Any]:
    paths = candidate_paths(canonical)
    with _operation(paths):
        data = _state(paths)
        if data.get("phase") != "active":
            raise ValueError("WIKI_CANDIDATE_MISSING: run wiki maintain first")
        if paths["wiki"] != _safe_path(expected_candidate):
            raise ValueError("WIKI_CANDIDATE_CHANGED: active round differs from the verified candidate; run wiki maintain again")
        # The caller runs commit_baseline with all source/verification/L4 gates first.
        from .snapshot import wiki_subject_digest
        baseline_path = paths["wiki"] / "meta" / "wiki-snapshot.json"
        baseline_bytes = baseline_path.read_bytes()
        baseline = json.loads(baseline_bytes.decode("utf-8"))
        completion = baseline.get("completion") or {}
        if completion.get("status") != "SUCCESS" or completion.get("subject_digest") != wiki_subject_digest(paths["wiki"]):
            raise ValueError("WIKI_CANDIDATE_NOT_VERIFIED: successful candidate baseline required")
        new = _tree(paths["wiki"])
        if (baseline_path.read_bytes() != baseline_bytes or
                completion.get("subject_digest") != wiki_subject_digest(paths["wiki"])):
            raise ValueError("WIKI_CANDIDATE_NOT_VERIFIED: candidate changed while binding its successful baseline")
        if _tree(paths["canonical"]) != data["old_tree"]:
            raise ValueError("WIKI_CANDIDATE_CONFLICT: canonical changed after candidate began")
        if paths["previous"].exists():
            raise ValueError("WIKI_CANDIDATE_CONFLICT: previous publication directory already exists")
        data.update(phase="publishing", new_tree=new)
        _write_state(paths, data)
        if data["old_tree"] != "MISSING":
            _rename_absent(paths["canonical"], paths["previous"])
            if _tree(paths["previous"]) != data["old_tree"]:
                raise ValueError("WIKI_CANDIDATE_CONFLICT: canonical changed during publication; recovery required")
        if paths["canonical"].exists() or _tree(paths["wiki"]) != new:
            raise ValueError("WIKI_CANDIDATE_CONFLICT: publication inputs changed; recovery required")
        _rename_absent(paths["wiki"], paths["canonical"])
        if _tree(paths["canonical"]) != new:
            raise ValueError("WIKI_CANDIDATE_CONFLICT: published directory changed; inspection required")
        # Once new occupies canonical, cleanup trouble must not pretend publication failed.
        cleanup = []
        data["phase"] = "published"
        try:
            _write_state(paths, data)
            cleanup = _cleanup_previous(paths, data)
            cleanup.extend(_cleanup_retired(paths, data, apply=True)["cleanup_pending"])
        except (OSError, ValueError):
            cleanup = ["publication state/previous: cleanup pending; recover publication"]
        return {"status": "PUBLISHED", "canonical_wiki_repo_root": str(paths["canonical"]),
                "cleanup_pending": cleanup}
