# External Knowledge Ingestion Standard

External ingestion is a **source accountability** workflow, not a coverage-maximization workflow.

## Core invariant

Every registered source must have a disposition:

`pending | canonicalized | merged | source_only | duplicate | superseded | quarantined | excluded`

The target is 100% **registered-source accountability**, not 100% source-to-canonical conversion. Templates, duplicates, archives and low-value material must not be turned into canonical notes merely to raise a percentage.

## Standard flow

```text
REGISTER
→ MANIFEST / HASH
→ DEDUP
→ CONVERT or QUARANTINE
→ GROUP / TRIAGE
→ SEARCH EXISTING CANONICAL
→ AI READ / UPDATE / CREATE / MERGE
→ FINAL TRUTH SCAN
→ INDEX
→ L1-L3 VERIFY
→ L4 when required
→ BATCH FINALIZE / BASELINE
```


Before INDEX/VERIFY/L4, run `tp-spec knowledge scan` **after the final canonical/evidence/disposition write**. The staged change set is the trust subject for audit/baseline; an earlier pre-AI change set must never be reused. If truth changes after staging, re-scan.

## Safety rules

- Source file scope and write boundary must be explicit. External originals are not silently modified.
- Hash duplicates before semantic processing.
- Conversion failure enters quarantine; no silent drop.
- Update existing canonical before creating another node for the same semantic object.
- Multi-model/parallel ingestion must have deterministic progress ownership; SQLite projection writes are serialized.
- Destructive source cleanup, ambiguous project assignment, merge/split uncertainty and evidence conflicts are fail-closed for unattended maintenance.

The default local conversion adapter is Microsoft MarkItDown, invoked through TP-Spec-Coding's narrow `convert_local` boundary. Base does not reimplement PDF/Office parsers and does not let document normalization silently become HTTP/URL retrieval. Registered-source hash drift blocks conversion before output/manifest mutation; per-source conversion failure enters `quarantined`. OCR/cloud-specific enhancement remains an optional adapter concern rather than a user-machine-specific office path requirement.
