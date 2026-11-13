"""Capture a local release evidence subject without contacting a deployment target."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .change_set import OPS_SUBJECT_SCHEMA
from .evidence import validate_evidence_path
from .execution import digest

_IMAGE_ID = re.compile(r"(?:[^@\s]+@)?sha256:[0-9a-f]{64}")
_CHECKSUM_ROW = re.compile(r"\\?[0-9a-fA-F]{64} [ *].+")


def _file(task_dir: Path, field: str, path: object) -> dict:
    if not isinstance(path, str) or Path(path).anchor or '..' in Path(path).parts:
        raise ValueError(f"ops subject {field} must be a task-relative file path")
    try:
        from .project_surface import project_path_issue
        from .transaction_commit import _terminal_manifest_excluded
        ref = Path(path).as_posix()
        if _terminal_manifest_excluded(ref) or project_path_issue(task_dir / ref, task_dir):
            raise ValueError('reference cannot be sealed in the terminal manifest')
        checked = validate_evidence_path(task_dir, ref)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"ops subject {field}: {exc}") from exc
    if not checked.ok:
        raise ValueError(f"ops subject {field}: {checked.error}")
    return checked.item


def _read_text(task_dir: Path, item: dict) -> str:
    try:
        path = (task_dir / item["path"]).resolve()
        path.relative_to(task_dir)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("evidence changed while capturing the subject")
        return data.decode("utf-8-sig")
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"ops subject {item['path']}: {exc}") from exc


def capture(task_dir: str | Path, manifest_ref: str) -> dict:
    """Bind the manifest, checksum list, final config and cutover receipts by SHA-256."""
    root = Path(task_dir).resolve()
    manifest = _file(root, "manifest_ref", manifest_ref)
    try:
        release = json.loads(_read_text(root, manifest))
    except json.JSONDecodeError as exc:
        raise ValueError(f"ops subject manifest {manifest['path']} is not valid JSON: {exc}") from exc
    if not isinstance(release, dict):
        raise ValueError("ops subject manifest must be a JSON object")
    image_id = release.get("image_id")
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        raise ValueError("ops subject image_id must be an immutable sha256 image ID or name@sha256 digest")
    receipts = release.get("cutover_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("ops subject cutover_receipts must be a non-empty list of task-relative file paths")
    checksums = _file(root, "artifact_manifest", release.get("artifact_manifest"))
    # A release may retain only its checksum list locally, with the payload stored elsewhere.
    rows = [line for line in _read_text(root, checksums).splitlines() if line.strip()]
    if not rows or any(not _CHECKSUM_ROW.fullmatch(line) for line in rows):
        raise ValueError(f"ops subject artifact_manifest must contain valid SHA256SUMS rows: {checksums['path']}")
    snapshot = {
        "schema": OPS_SUBJECT_SCHEMA,
        "manifest_ref": manifest["path"],
        "image_id": image_id,
        "evidence_items": [manifest, checksums, _file(root, "deployment_config", release.get("deployment_config")),
                           *(_file(root, "cutover_receipts", ref) for ref in receipts)],
        "repositories": [],
    }
    subject_digest = "sha256:" + digest(snapshot)
    return {**snapshot, "content_digest": subject_digest, "snapshot_digest": subject_digest}
