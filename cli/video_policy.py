# -*- coding: utf-8 -*-
"""Video role and local media constraints, separate from the software policy."""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import stat

from .task_coordinator import VIDEO_COORDINATOR_ROLE as PRODUCER, VIDEO_CREATION_ACTOR as DOMAIN_AGENT

DIRECTOR = "tp-video-director"
VISUAL = "tp-video-visual-artist"
SOUND = "tp-video-sound-designer"
EDITOR = "tp-video-editor"
REVIEWER = "tp-video-reviewer"
ROLES = {PRODUCER, DIRECTOR, VISUAL, SOUND, EDITOR, REVIEWER}
PHASE_ROLES = {
    "intake": {PRODUCER},
    "creative": {PRODUCER, DIRECTOR, VISUAL},
    "asset_production": {PRODUCER, DIRECTOR, VISUAL, SOUND},
    "post_production": {PRODUCER, EDITOR, SOUND, VISUAL},
    "media_quality": ROLES,
    "delivery": {PRODUCER, EDITOR},
}


def phase_allowed(phase, roles):
    return phase in PHASE_ROLES and set(roles) <= PHASE_ROLES[phase]


def validate_phase_actor(domain, phase, actor, *, waiting=False):
    if domain == "video":
        if phase not in PHASE_ROLES or ((actor != "human_owner" or not waiting) and not phase_allowed(phase, [actor])):
            raise ValueError(f"VIDEO_PHASE_ROLE_INVALID: {phase} / {actor}")
    else:
        from .record_first import PHASES
        if phase not in PHASES or actor in ROLES | {DOMAIN_AGENT}:
            raise ValueError(f"SOFTWARE_PHASE_ROLE_INVALID: {phase} / {actor}")


def media_root(workspace, value):
    from .work_units import paths
    root = Path(workspace).resolve()
    relative = paths([value])[0]
    return bound_media_root(root, root / relative)


def bound_media_root(workspace, candidate):
    result = Path(candidate).resolve(strict=True)
    if not result.is_dir() or not result.is_relative_to(Path(workspace).resolve()):
        raise ValueError(f"VIDEO_MEDIA_ROOT_INVALID: {candidate}")
    return result


def media_files(root, values, *, hash_content=True, check_work_path=None):
    from .recording import _collection_stream
    from .work_units import paths
    root = Path(root).resolve(strict=True)
    records = []
    for relative in paths(values):
        if any(character in relative for character in "*?["):
            raise ValueError(f"VIDEO_EXACT_PATH_REQUIRED: {relative}")
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError(f"VIDEO_MEDIA_PATH_INVALID: {relative}")
            if check_work_path is not None:
                check_work_path(relative, resolved)
            before = resolved.stat()
            record = {"path": relative, "size": before.st_size}
            if hash_content:
                with _collection_stream(resolved, root) as source:
                    opened = os.fstat(source.fileno())
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                    after = os.fstat(source.fileno())
                identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                final_path = resolved.lstat()
                # Windows 的路径 stat 与句柄 fstat 可能使用不同的 ctime 语义。
                if (not identity(before) == identity(opened) == identity(after) == identity(final_path)
                        or before.st_ctime_ns != final_path.st_ctime_ns or opened.st_ctime_ns != after.st_ctime_ns):
                    raise ValueError(f"VIDEO_MEDIA_CHANGED_DURING_READ: {relative}")
                record["sha256"] = "sha256:" + digest.hexdigest()
        except OSError as exc:
            raise ValueError(f"VIDEO_MEDIA_UNAVAILABLE: {relative}") from exc
        records.append(record)
    return records
