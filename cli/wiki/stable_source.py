# -*- coding: utf-8 -*-
"""One pinned source per Wiki run; Git reads never consult or switch the worktree."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
import os
import re
import subprocess


class SourceError(ValueError):
    """An unavailable/ambiguous source needs review, not a filesystem fallback."""


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        env.pop(key, None)
    # Object reads must not fetch promisor objects or consult replacement refs.
    # GIT_ALLOW_PROTOCOL also prevents transports on Git versions predating
    # GIT_NO_LAZY_FETCH. These settings are confined to this subprocess.
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_TERMINAL_PROMPT="0",
               GIT_LITERAL_PATHSPECS="1")
    try:
        result = subprocess.run(["git", "-C", str(root), *args], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"GIT_UNAVAILABLE: {exc}") from exc
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SourceError(f"GIT_SOURCE_UNAVAILABLE: {' '.join(args[:2])}: {detail}")
    return result


def relative_path(rel: str) -> str:
    text = str(rel or "").replace("\\", "/")
    pure = PurePosixPath(text)
    if (not text or pure.is_absolute() or ".." in pure.parts or "\x00" in text
            or re.match(r"^[A-Za-z]:", text) or text == "."):
        raise ValueError(f"unsafe repo-relative path: {rel!r}")
    return pure.as_posix()


def _commit(root: Path, ref: str) -> str:
    value = git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").stdout.decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise SourceError("INVALID_COMMIT_ID: Git did not return a full object identity")
    return value


def remote_ref_name(root: Path, value: Any) -> str:
    """Validate configuration without resolving a potentially moved pinned ref."""
    if value is None or value == "":
        raise SourceError("STABLE_REF_REQUIRED: configure source.stable_ref as refs/remotes/<remote>/<branch>; Wiki does not choose or synchronize a branch")
    if not isinstance(value, str):
        raise SourceError("STABLE_REF_INVALID: source.stable_ref must be a full remote-tracking reference")
    ref = value.strip()
    if not ref:
        raise SourceError("STABLE_REF_REQUIRED: configure source.stable_ref as refs/remotes/<remote>/<branch>")
    if (not re.fullmatch(r"refs/remotes/[^/]+/.+", ref) or "\x00" in ref or ref.endswith("/HEAD") or
            git(root, "check-ref-format", ref, check=False).returncode):
        raise SourceError(f"STABLE_REF_INVALID: {ref!r}; use refs/remotes/<remote>/<branch>, not a local branch, tag, SHA or revision expression")
    return ref


@dataclass
class SourceView:
    root: Path
    mode: str
    stable_ref: str = ""
    commit: str = ""
    prefix: str = ""
    _entries: dict[str, tuple[str, str, str]] | None = field(default=None, repr=False)
    _blobs: dict[str, bytes] = field(default_factory=dict, repr=False)

    def identity(self) -> dict[str, str]:
        # Paths are resolved by the registry, never persisted as snapshot identity.
        return {"source_mode": self.mode, "stable_ref": self.stable_ref,
                "commit": self.commit, "repo_prefix": self.prefix}

    def tree(self) -> dict[str, tuple[str, str, str]]:
        if self._entries is None:
            treeish = self.commit + (":" + self.prefix.rstrip("/") if self.prefix else "")
            data = git(self.root, "ls-tree", "-r", "-z", treeish).stdout
            entries = {}
            for record in data.split(b"\x00"):
                if not record:
                    continue
                meta, path = record.split(b"\t", 1)
                mode, kind, oid = meta.decode("ascii").split()
                try:
                    rel = path.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceError("GIT_PATH_ENCODING_UNSUPPORTED: use a UTF-8 source path") from exc
                if "\\" in rel:
                    raise SourceError("GIT_PATH_UNSUPPORTED: literal backslash in a Git source name")
                entries[relative_path(rel)] = (mode, kind, oid)
            self._entries = entries
        return self._entries

    def file_entry(self, rel: str) -> tuple[str, str, str] | None:
        rel = relative_path(rel)
        if self._entries is not None:
            return self._entries.get(rel)
        # Direct path lookup does not enumerate all sources for an incremental scan.
        raw = git(self.root, "ls-tree", "--full-tree", "-z", self.commit,
                  "--", self.prefix + rel).stdout
        for record in raw.split(b"\x00"):
            if not record:
                continue
            meta, path = record.split(b"\t", 1)
            if path.decode("utf-8") == self.prefix + rel:
                mode, kind, oid = meta.decode("ascii").split()
                return mode, kind, oid
        return None

    def is_file(self, rel: str) -> bool:
        row = self.file_entry(rel)
        if row and row[0] not in {"100644", "100755"}:
            raise SourceError(f"GIT_ENTRY_UNSUPPORTED: {rel} mode={row[0]}; do not follow worktree links")
        return row is not None and row[1] == "blob"

    def blob(self, oid: str) -> bytes:
        if oid not in self._blobs:
            self._blobs[oid] = git(self.root, "cat-file", "blob", oid).stdout
        return self._blobs[oid]

    def read_bytes(self, rel: str) -> bytes:
        row = self.file_entry(rel)
        if not row:
            raise FileNotFoundError(f"source absent at {self.commit}: {rel}")
        if row[0] not in {"100644", "100755"} or row[1] != "blob":
            raise SourceError(f"GIT_ENTRY_UNSUPPORTED: {rel} mode={row[0]}")
        return self.blob(row[2])

    def require_ancestor(self, previous: dict[str, Any]) -> str:
        """Initialization must not bypass the existing Git history boundary."""
        old = str(previous.get("commit") or "")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", old):
            raise SourceError("BASELINE_COMMIT_UNAVAILABLE: no valid prior commit")
        _commit(self.root, old)  # No fetching, even for shallow/partial repositories.
        ancestry = git(self.root, "merge-base", "--is-ancestor", old, self.commit, check=False)
        if ancestry.returncode == 1:
            raise SourceError("NON_ANCESTOR_HISTORY: stable source is not a descendant of the successful baseline; review history before rebuilding")
        if ancestry.returncode:
            raise SourceError("HISTORY_UNAVAILABLE: cannot establish baseline ancestry locally")
        return old

    def diff(self, previous: dict[str, Any]) -> list[dict[str, str]]:
        if previous.get("source_mode") != "GIT_REF" or previous.get("repo_prefix", "") != self.prefix:
            raise SourceError("SOURCE_INITIALIZATION_REQUIRED: prior source identity is not comparable")
        old = self.require_ancestor(previous)
        data = git(self.root, "diff-tree", "-r", "--raw", "--no-abbrev", "--no-renames",
                   "--no-ext-diff", "--no-textconv", "-z", old, self.commit, "--").stdout
        parts = data.split(b"\x00")
        rows = []
        for index in range(0, len(parts) - 1, 2):
            if not parts[index]:
                continue
            before_mode, after_mode, before_oid, after_oid, status = parts[index].decode("ascii").lstrip(":").split()
            try:
                path = parts[index + 1].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SourceError("GIT_PATH_ENCODING_UNSUPPORTED") from exc
            if "\\" in path:
                raise SourceError("GIT_PATH_UNSUPPORTED: literal backslash in a Git source name")
            if self.prefix and not path.startswith(self.prefix):
                continue
            rel = relative_path(path[len(self.prefix):])
            rows.append({"file": rel, "status": status, "before_mode": before_mode,
                         "after_mode": after_mode, "before_oid": before_oid, "after_oid": after_oid})
        return rows


def resolve_source(root: Path, config: dict[str, Any], *, identity: dict[str, Any] | None = None) -> SourceView:
    root = Path(root).resolve(strict=False)
    if not root.is_dir():
        raise SourceError(f"REPO_ROOT_MISSING: {root}")
    mode = str(config.get("source_mode") or "AUTO").upper()
    if mode not in {"AUTO", "GIT_REF", "FILESYSTEM"}:
        raise SourceError("source_mode must be AUTO|GIT_REF|FILESYSTEM")
    marker = any((p / ".git").exists() for p in (root, *root.parents)) or ((root / "HEAD").is_file() and (root / "objects").is_dir())
    try:
        probe = git(root, "rev-parse", "--git-dir", check=False)
    except SourceError:
        if marker or mode == "GIT_REF" or (identity or {}).get("source_mode") == "GIT_REF":
            raise
        probe = None
    is_git = probe is not None and probe.returncode == 0
    if not is_git and marker:
        raise SourceError("GIT_REPOSITORY_UNAVAILABLE: .git exists but Git cannot resolve it")
    if mode == "FILESYSTEM" and is_git:
        raise SourceError("GIT_WORKTREE_NOT_STABLE_SOURCE: use GIT_REF with a stable_ref; FILESYSTEM is for non-Git sources")
    if not is_git:
        if mode == "GIT_REF" or (identity or {}).get("source_mode") == "GIT_REF":
            raise SourceError("GIT_REPOSITORY_REQUIRED: no filesystem fallback for a Git snapshot")
        if config.get("stable_ref"):
            raise SourceError("STABLE_REF_WITHOUT_GIT: configured ref cannot be read from a filesystem export")
        return SourceView(root, "FILESYSTEM")
    if identity and identity.get("source_mode") != "GIT_REF":
        raise SourceError("SOURCE_INITIALIZATION_REQUIRED: recorded filesystem source is now a Git repository")
    bare = git(root, "rev-parse", "--is-bare-repository").stdout.strip() == b"true"
    prefix = "" if bare else git(root, "rev-parse", "--show-prefix").stdout.decode("utf-8").rstrip("\n")
    git_root = root if bare else Path(git(root, "rev-parse", "--show-toplevel").stdout.decode("utf-8").rstrip("\n"))
    if identity:
        if identity.get("repo_prefix", "") != prefix:
            raise SourceError("SOURCE_SCOPE_CHANGED: recorded repository prefix differs")
        oid = str(identity.get("commit") or "")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            raise SourceError("BASELINE_COMMIT_UNAVAILABLE: recorded full commit is missing")
        return SourceView(git_root, "GIT_REF", str(identity.get("stable_ref") or ""), _commit(git_root, oid), prefix)
    ref = remote_ref_name(git_root, config.get("stable_ref"))
    symbolic = git(git_root, "symbolic-ref", "-q", ref, check=False)
    if symbolic.returncode == 0:
        raise SourceError(f"STABLE_REF_SYMBOLIC: {ref}; configure the concrete remote-tracking branch, not an alias")
    if symbolic.returncode != 1:
        raise SourceError(f"STABLE_REF_UNAVAILABLE: cannot inspect {ref}; review the local repository")
    # Read the ref identity separately from its object so missing commits are
    # distinguishable from missing refs. Exact matching avoids prefix/DWIM fallbacks.
    resolved = git(git_root, "for-each-ref", "--format=%(refname)%09%(objectname)", ref, check=False)
    rows = [line.split("\t", 1) for line in resolved.stdout.decode("utf-8").splitlines()]
    matches = [row[1] for row in rows if len(row) == 2 and row[0] == ref]
    if resolved.returncode or len(matches) != 1:
        raise SourceError(f"STABLE_REF_UNAVAILABLE: {ref} is missing or unreadable locally; the user controls synchronization, Wiki will not fetch or pull")
    oid = matches[0]
    try:
        commit = _commit(git_root, oid)
    except SourceError as exc:
        raise SourceError(f"STABLE_REF_OBJECT_UNAVAILABLE: {ref}; required commit is unavailable locally, no objects will be downloaded") from exc
    return SourceView(git_root, "GIT_REF", ref, commit, prefix)


def bind_source(root: Path, config: dict[str, Any], *, identity: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {k: v for k, v in config.items() if not k.startswith("_")}
    result["_source_view"] = resolve_source(root, result, identity=identity)
    return result


def source_view(root: Path, config: dict[str, Any]) -> SourceView:
    view = config.get("_source_view")
    if (not isinstance(view, SourceView) or
            (view.root / view.prefix).resolve(strict=False) != Path(root).resolve(strict=False)):
        # Internal callers without the CLI also pin once for the provided config.
        view = resolve_source(root, config)
        config["_source_view"] = view
    return view
