# Knowledge Legacy Normalization Standard

## Purpose

Legacy Knowledge migration must reduce deterministic schema noise before a model spends tokens on semantic review.

Use:

```text
tp-spec knowledge migrate-normalize --workspace-root <workspace>
tp-spec knowledge migrate-normalize --workspace-root <workspace> --apply
```

Dry-run is the default.

## Safe automatic normalization

Only semantics-preserving transformations are automatic:

- legacy `relations` mapping → relation object array;
- `relates_to` → `related_to`;
- `kind: ops` → `operation`;
- `kind: canonical` → kind encoded by the stable canonical ID when that ID is valid;
- legacy `confidence: high|medium|low` → `0.90|0.60|0.30` using `legacy-qualitative-v1` compatibility encoding;
- numeric aliases → strings;
- missing `canonical: true` on canonical-layer notes;
- missing `source_refs: []` only when non-empty structured `evidence_refs` already proves traceability.

The numeric confidence mapping is a compatibility representation of an old qualitative scale. It is **not** measured probability and must not be described as one.

## Never automatic

The normalizer must not guess:

- missing confidence;
- missing `last_verified` date;
- missing evidence;
- unknown relation semantics such as `implemented_by` / `evolves_into`;
- ambiguous project assignment;
- semantic relation-kind contract changes.

These enter the review queue for `tp-knowledge`.

## Relation hierarchy compatibility

`part_of` is hierarchical containment and may target `feature` or `data` in addition to project/domain/system/module. This supports real feature nesting, interface-to-feature containment, and data hierarchy without degrading these edges to generic `related_to` merely to satisfy a narrow schema.

## Receipt

`--apply` writes machine-owned receipts under `.ai-kb/meta/` and does not advance the trusted Knowledge baseline. After normalization, re-run `lint`, then targeted AI review, then the normal scan/index/verify/L4/snapshot chain.
