# -*- coding: utf-8 -*-
"""Deterministic L4 semantic-audit sampling plan.

The model performs the semantic review; this module chooses and records a stable,
traceable scope so scheduled AI runs do not invent a different audit procedure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json

from .manifest import load_manifest
from .snapshot import snapshot_paths, utc_now, wiki_subject_digest

AUDIT_PLAN_SCHEMA = "ai-work.wiki-semantic-audit-plan/v1"

# Stable adversarial checks carried by every audit plan.  These are intentionally
# few and high-value: they target the error class that survives hash/citation gates
# most often in low-cost model output (truthful code existence, wrong product status
# or responsibility attribution).
SEMANTIC_CHALLENGES = [
    {
        "id": "currentity",
        "question": "What is the CURRENT primary path/contract described by this document? If competing legacy/compatibility/recovery paths exist in source, why are they not CURRENT?",
    },
    {
        "id": "existence-vs-authority",
        "question": "Does the prose infer current authority/recommendation merely because a file, function, state or template still exists?",
    },
    {
        "id": "responsibility-attribution",
        "question": "For every strong claim such as owns/guarantees/decides/only/enforces, which concrete layer actually enforces it and does the cited source support that attribution?",
    },
    {
        "id": "pipeline-stage-owner",
        "question": "When a pipeline is described, are discovery, fingerprinting, classification, eligibility, topology, planning, semantic update, verification, coverage, audit and baseline commit assigned to the correct owners? For every stage named, verify the concrete function/entrypoint that performs it; module names or nearby data flow are not sufficient evidence of ownership.",
    },
    {
        "id": "active-contract",
        "question": "Do current-version claims, active configuration, runtime entrypoints and routing/dispatch evidence agree with the document's description of the active architecture?",
    },
    {
        "id": "cite-strength",
        "question": "Does each citation support the prose conclusion itself, rather than only proving that related code exists? Are key citations placed next to the substantive claim/section they support instead of only in a generic provenance/reference section?",
    },
    {
        "id": "interface-scope-exactness",
        "question": "For every claimed command, CLI option, config key, threshold, default, mandatory step or scope, does the actual parser/schema/config/canonical protocol or runtime entrypoint prove the exact claim? Check especially that first-build-only rules are not generalized to daily maintenance and that no plausible-looking option or mandatory step was inferred rather than implemented.",
    },
]


def build_audit_plan(wiki_repo_root: Path, quality_cfg: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    paths = snapshot_paths(wiki_repo_root)
    manifest = load_manifest(wiki_repo_root)
    docs = [d for d in (manifest.get("documents") or []) if isinstance(d, dict) and d.get("path")]
    staged_plan = {}
    verification = {}
    changeset = {}
    if paths["plan"].is_file():
        staged_plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
    if paths["verification"].is_file():
        verification = json.loads(paths["verification"].read_text(encoding="utf-8"))
    if paths["changeset"].is_file():
        changeset = json.loads(paths["changeset"].read_text(encoding="utf-8"))

    sample_n = max(1, int(quality_cfg.get("semantic_audit_sample_docs", 3)))
    by_path = {str(d["path"]).replace("\\", "/"): d for d in docs}
    selected: Dict[str, Dict[str, Any]] = {}

    affected = [row for row in (staged_plan.get("affected_documents") or []) if isinstance(row, dict)]
    affected.sort(
        key=lambda row: (
            -sum(1 for r in (row.get("reasons") or []) if isinstance(r, dict) and r.get("role") == "primary"),
            -len(row.get("reasons") or []),
            str(row.get("document") or ""),
        )
    )

    # Trust rule:
    # - first adoption/migration of an existing Wiki has no trusted baseline, so every
    #   durable Wiki document must be semantically reviewed once;
    # - later incremental runs must review every document the deterministic planner says
    #   is affected.  We never truncate affected docs to a sample because doing so can
    #   certify stale pages while advancing the source baseline;
    # - a small additional risk sample may be taken from unaffected docs.
    initial = bool(changeset.get("initial"))
    if full or initial:
        reason_kind = "initial-baseline-semantic-migration" if initial else "explicit-full-repo-quality-audit"
        priority = "initial-full-repo" if initial else "full-repo-quality-audit"
        for rel, doc in sorted(by_path.items()):
            selected[rel] = {
                "document": rel,
                "priority": priority,
                "reasons": [{"kind": reason_kind}],
            }
        audit_scope = "initial-full-repo" if initial else "standalone-full-repo"
    else:
        for row in affected:
            rel = str(row.get("document") or "").replace("\\", "/")
            if rel and rel in by_path:
                selected[rel] = {
                    "document": rel,
                    "priority": "changed",
                    "reasons": row.get("reasons") or [],
                }
        audit_scope = "all-affected"

    # Add deterministic risk samples only after the mandatory scope is complete.
    audit_candidates = [d for d in docs if d.get("type") != "module-index"] or docs
    ranked = sorted(
        audit_candidates,
        key=lambda d: (
            0 if d.get("type") == "content-doc" else 1,
            -len(d.get("dependencies") or []),
            str(d.get("path") or ""),
        ),
    )
    added_samples = 0
    for doc in ranked:
        if added_samples >= sample_n:
            break
        rel = str(doc.get("path") or "").replace("\\", "/")
        if not rel or rel in selected:
            continue
        selected[rel] = {
            "document": rel,
            "priority": "sample",
            "reasons": [{"kind": "risk-sample", "dependency_count": len(doc.get("dependencies") or [])}],
        }
        added_samples += 1

    subject = wiki_subject_digest(wiki_repo_root)
    mode = "change-set" if verification.get("change_set_id") else "standalone"
    receipt_required = bool(verification.get("semantic_audit_required"))
    topology_review = list(staged_plan.get("topology_review") or [])
    plan = {
        "schema": AUDIT_PLAN_SCHEMA,
        "created_at": utc_now(),
        "mode": mode,
        "audit_scope": audit_scope,
        "change_set_id": verification.get("change_set_id"),
        "subject_digest": subject,
        "verification_result": verification.get("result"),
        "receipt_required": receipt_required,
        "coverage": {
            "manifest_documents_total": len(docs),
            "affected_documents_total": len(affected),
            "affected_documents_selected": len(affected) if not initial else len(docs),
            "mandatory_documents_selected": len(selected) - added_samples,
            "risk_sample_target": sample_n,
            "risk_samples_added": added_samples,
            "sampling_of_affected_documents": False,
        },
        "documents": list(selected.values()),
        "topology_review": topology_review,
        "topology_review_required": bool(topology_review),
        "semantic_challenges": SEMANTIC_CHALLENGES,
        "instructions": [
            "read every mandatory Wiki document in this plan and the real cited/dependent source",
            "for initial-full-repo, validate every durable Wiki document because no trusted semantic baseline exists",
            "for standalone-full-repo, validate every durable Wiki document as an explicit quality audit even when source did not change",
            "for incremental all-affected, validate every affected document; do not replace mandatory review with sampling",
            "check that responsibilities, flows, current-version claims and relationships are supported by source facts",
            "review every topology_review item and decide whether it changes durable Wiki structure/content",
            "treat existing citations as evidence pointers, not as proof that the prose conclusion is correct",
            "apply every relevant semantic_challenge adversarially; do not reuse the generation-time interpretation as its own proof",
            "when a challenge is relevant but source evidence is insufficient, report uncertainty or FAIL instead of inventing a current/authority conclusion",
            "report risk sampling truthfully; only initial-full-repo or standalone-full-repo may claim full-repo semantic validation",
        ],
    }
    paths["audit_plan"].parent.mkdir(parents=True, exist_ok=True)
    paths["audit_plan"].write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return plan
