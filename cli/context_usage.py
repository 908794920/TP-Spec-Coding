from __future__ import annotations

import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, Optional

SOURCE_TYPES = {"wiki", "knowledge", "memory_project", "memory_skill"}
USAGE_STAGES = {"retrieved", "adopted"}
OUTCOMES = {"success", "stale", "fallback", "unknown"}
CONFIDENCE = {"high", "medium"}
SOURCE_FOLLOWUP = {"none", "targeted", "broad", "unknown"}
MEMORY_PROJECT_FRAGMENTS = {
    "index", "runtime", "structure", "constraints", "verification", "navigation",
}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
MAX_ITEMS_PER_EVENT = 32
_PREFIX = {
    "wiki": "wiki:",
    "knowledge": "knowledge:",
    "memory_project": "memory_project:",
    "memory_skill": "memory_skill:",
}
_STAGE_RANK = {"retrieved": 0, "adopted": 1}


def parse_context_usage_json(raw: Optional[str]) -> tuple[Any, list[str]]:
    if raw is None or not str(raw).strip():
        return [], []
    try:
        return json.loads(raw), []
    except Exception as exc:  # telemetry must never become a Runtime failure
        return [], [f"invalid --context-usage-json dropped: {exc}"]


def _contains_machine_absolute(value: str) -> bool:
    if WINDOWS_ABSOLUTE_RE.match(value):
        return True
    if value.startswith(("/", "\\\\")):
        return True
    # Asset IDs and evidence refs often have a semantic prefix before the path.
    for part in value.split(":"):
        if WINDOWS_ABSOLUTE_RE.match(part) or part.startswith(("/", "\\")):
            return True
    return bool(re.search(r"(?:^|:)[A-Za-z]:[\\/]", value))


def _portable(value: str) -> bool:
    if not value or _contains_machine_absolute(value):
        return False
    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    if ".." in PurePosixPath(normalized).parts:
        return False
    return True


def _valid_asset_id(source_type: str, asset_id: str) -> bool:
    if not _portable(asset_id) or not asset_id.startswith(_PREFIX[source_type]):
        return False
    payload = asset_id[len(_PREFIX[source_type]):]
    if not payload or not _portable(payload):
        return False
    if source_type == "memory_project":
        if "#" not in payload:
            return False
        project, fragment = payload.rsplit("#", 1)
        return bool(project) and fragment in MEMORY_PROJECT_FRAGMENTS
    return True


def _normalize_context_usage(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if value in (None, ""):
        return [], warnings
    if not isinstance(value, list):
        return [], ["context usage payload must be a JSON array; payload dropped"]
    if len(value) > MAX_ITEMS_PER_EVENT:
        warnings.append(
            f"context usage payload limited to first {MAX_ITEMS_PER_EVENT} items; extras dropped"
        )
    normalized_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(value[:MAX_ITEMS_PER_EVENT]):
        if not isinstance(raw, dict):
            warnings.append(f"context usage item #{index + 1} is not an object; item dropped")
            continue
        source_type = str(raw.get("source_type") or "").strip()
        asset_id = str(raw.get("asset_id") or "").strip()
        stage = str(raw.get("stage") or "").strip().lower()
        if source_type not in SOURCE_TYPES:
            warnings.append(f"context usage item #{index + 1} has invalid source_type; item dropped")
            continue
        if not _valid_asset_id(source_type, asset_id):
            warnings.append(f"context usage item #{index + 1} has invalid/non-portable asset_id; item dropped")
            continue
        if stage not in USAGE_STAGES:
            warnings.append(f"context usage item #{index + 1} has invalid stage; item dropped")
            continue

        outcome = str(raw.get("outcome") or "unknown").strip().lower()
        confidence = str(raw.get("confidence") or "medium").strip().lower()
        source_followup = str(raw.get("source_followup") or "unknown").strip().lower()
        if outcome not in OUTCOMES:
            warnings.append(f"context usage item #{index + 1} has invalid outcome; item dropped")
            continue
        if confidence not in CONFIDENCE:
            warnings.append(f"context usage item #{index + 1} has invalid confidence; item dropped")
            continue
        if source_followup not in SOURCE_FOLLOWUP:
            warnings.append(f"context usage item #{index + 1} has invalid source_followup; item dropped")
            continue

        evidence_raw = raw.get("evidence", [])
        if not isinstance(evidence_raw, list):
            warnings.append(f"context usage item #{index + 1} evidence is not a list; evidence dropped")
            evidence_raw = []
        evidence: list[str] = []
        for ev in evidence_raw:
            ev_text = str(ev or "").strip()
            if not ev_text or not _portable(ev_text):
                warnings.append(f"context usage item #{index + 1} contains invalid evidence; evidence entry dropped")
                continue
            if ev_text not in evidence:
                evidence.append(ev_text)
        if source_followup != "unknown" and not evidence:
            warnings.append(
                f"context usage item #{index + 1} source_followup downgraded because no explicit evidence was supplied"
            )
            source_followup = "unknown"

        item: dict[str, Any] = {
            "source_type": source_type,
            "asset_id": asset_id,
            "stage": stage,
            "outcome": outcome,
            "confidence": confidence,
            "source_followup": source_followup,
            "evidence": evidence,
        }
        query_hash = str(raw.get("query_hash") or "").strip().lower()
        if query_hash:
            if SHA256_RE.fullmatch(query_hash):
                item["query_hash"] = query_hash
            else:
                warnings.append(f"context usage item #{index + 1} has invalid query_hash; field omitted")

        key = (source_type, asset_id)
        existing = normalized_by_key.get(key)
        if existing is not None:
            warnings.append(f"duplicate context asset collapsed: {source_type}/{asset_id}")
            if _STAGE_RANK[stage] < _STAGE_RANK[str(existing["stage"])]:
                continue
        normalized_by_key[key] = item
    return list(normalized_by_key.values()), warnings


def normalize_context_usage(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return _normalize_context_usage(value)
    except Exception as exc:  # hard soft-fail boundary
        return [], [f"context usage normalization failed and was dropped: {exc}"]


def emit_warnings(warnings: Iterable[str]) -> None:
    for warning in warnings:
        print(f"WARN: context telemetry: {warning}", file=sys.stderr)


def merge_context_usage(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for group in groups:
        combined.extend(list(group or []))
    items, _warnings = normalize_context_usage(combined)
    return items


def knowledge_usage_from_delivery(
    search_receipts: Iterable[dict[str, Any]],
    resolved_knowledge_refs: Iterable[dict[str, str]],
) -> list[dict[str, Any]]:
    usage: list[dict[str, Any]] = []
    for receipt in search_receipts or []:
        if not isinstance(receipt, dict):
            continue
        query_hash = str(receipt.get("query_hash") or "").strip().lower()
        for result in receipt.get("results") or []:
            if not isinstance(result, dict):
                continue
            stable_id = str(result.get("id") or "").strip()
            if not stable_id:
                continue
            layer = str(result.get("layer") or "").strip().lower()
            item: Dict[str, Any] = {
                "source_type": "knowledge",
                "asset_id": f"knowledge:{stable_id}",
                "stage": "retrieved",
                # V5.2.6 telemetry convention: a source-layer hit is represented as
                # fallback, even though an explicit source-layer query can also cause it.
                "outcome": "fallback" if layer == "source" else "success",
                "confidence": "high",
                "source_followup": "unknown",
                "evidence": [],
            }
            if SHA256_RE.fullmatch(query_hash):
                item["query_hash"] = query_hash
            usage.append(item)
    for ref in resolved_knowledge_refs or []:
        if not isinstance(ref, dict):
            continue
        stable_id = str(ref.get("id") or "").strip()
        if not stable_id:
            continue
        usage.append({
            "source_type": "knowledge",
            "asset_id": f"knowledge:{stable_id}",
            "stage": "adopted",
            "outcome": "success",
            "confidence": "high",
            "source_followup": "unknown",
            "evidence": [],
        })
    return merge_context_usage(usage)


def extract_context_usage(detail_json: str | None) -> list[dict[str, Any]]:
    if not detail_json:
        return []
    try:
        detail = json.loads(detail_json)
    except Exception:
        return []
    if not isinstance(detail, dict):
        return []
    items, _warnings = normalize_context_usage(detail.get("context_usage"))
    return items
