# External Knowledge Ingest Batch Protocol — V5.2.0

This protocol is invoked explicitly for a named external-document/source batch. It is not part of every daily maintenance run.

## Flow

```text
REGISTER
→ MANIFEST/HASH
→ DEDUP
→ CONVERT or QUARANTINE
→ GROUP/TRIAGE
→ SEARCH CANONICAL
→ AI READ / UPDATE / CREATE / MERGE
→ FINAL TRUTH SCAN
→ INDEX
→ VERIFY
→ L4 as required
→ FINALIZE
→ BASELINE
```

## Deterministic start

```text
ai-work knowledge ingest register --workspace-root <workspace> --project <id> --batch <name> --source-root <path>
ai-work knowledge ingest status   --workspace-root <workspace> --batch <name>
```

Registration writes only machine-owned manifest/progress under the configured ingest root. It never modifies external source files.

## AI rules

- Project ID must already be registered or explicitly supplied/approved; never infer it from a folder name.
- Hash/deduplicate before spending model tokens.
- Search canonical before creating new knowledge.
- Prefer update/merge over duplicate canonical creation.
- Conversion adapters are environment-specific; failure becomes `quarantined`, not silent loss.
- `pending` means not yet adjudicated; finalization requires every registered source to have a terminal disposition.
- `source_only`, `duplicate`, `superseded`, `quarantined`, `excluded` are valid outcomes and do not lower source accountability.
- Deleting originals, moving external archives, ambiguous merge/split, or conflicting evidence is forbidden in unattended mode.

## Source disposition

After processing a source, record it deterministically:

```text
ai-work knowledge ingest disposition ... --source-id <id> --disposition canonicalized --canonical-id <CID>
```

or an appropriate terminal disposition plus reason.

## Batch finalization

After the last canonical edit and the last source disposition write, bind the final truth explicitly:

```text
knowledge scan
→ knowledge index update
→ knowledge verify
→ knowledge audit (if the staged change set requires L4)
→ knowledge audit-record ...
→ knowledge ingest finalize
→ knowledge snapshot-commit
```

Do not reuse the change set created before AI UPDATE/disposition changes. A batch with `pending` sources cannot finalize. “100%” here means every registered source is accounted for, not every source was converted to canonical.
