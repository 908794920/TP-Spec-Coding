# Canonical Knowledge Content Standard

## Purpose

Canonical Knowledge is a high-information-density, evidence-bound answer layer. It should make future agents faster and more accurate, not maximize Markdown count.

## Canonical vs source

- `90-sources`: evidence preservation. Do not rewrite facts merely to make them prettier.
- canonical: deduplicated reusable knowledge that answers stable questions.
- projection: FTS/link/graph indexes derived from the above and safe to rebuild.

## Write rules

1. **Update before create.** Search canonical first; merge or extend an existing node when the semantic object is the same.
2. Keep stable IDs and readable titles.
3. Do not invent fields, thresholds, dates, owners, interfaces or current status when evidence is insufficient.
4. Separate fact, historical observation, inference and open question.
5. Time-sensitive observations must say they are observations and carry verification date/evidence.
6. Prefer one focused canonical node over a document dump; prefer a subsystem/feature node over one-note-per-source duplication.
7. `related_to` is a last resort. Use a typed relation when one exists; `verifies` is valid for a verification operation/job/decision pointing to a verified capability/contract.
8. Canonical must carry evidence through legacy-compatible `source_refs` and/or structured `evidence_refs`.

## Kinds

`project, domain, system, module, feature, interface, data, job, operation, decision, source`.

## Retrieval-first writing

Titles, aliases, section headings and key identifiers should contain the terms future agents are likely to search. Do not keyword-stuff. The purpose is accurate retrieval with low token cost.
