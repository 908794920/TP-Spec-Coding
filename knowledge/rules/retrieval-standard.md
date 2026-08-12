# Knowledge Retrieval Standard

## Current authority

The active retrieval path is local and deterministic:

```text
Canonical Markdown / Source evidence
        ↓ projection build/update
SQLite FTS5
        ↓
canonical-first retrieval
        ↓ only when useful/available
source fallback
```

The configured projection DB is a rebuildable **Knowledge Retrieval Projection**, not Knowledge truth.


## Project scope

The projection database can be global while retrieval remains project-scoped. Default Agent search resolves the current workspace through project binding/project-registry and searches:

```text
current project + registered shared scopes
→ canonical first
→ source fallback only when needed
```

Other projects are excluded by default. Use `--scope global` only for explicit cross-project research, deduplication or human-requested global search. `global_fallback` is disabled by default so a weak project query cannot silently leak unrelated projects into results.

## FTS5 and retired vector compatibility

- `systems.knowledge.retrieval.strategy = canonical-first-fts5` is the current authority.
- `systems.knowledge.projection.vector_mode = retired-compatible|disabled` means vector retrieval is not active.
- Legacy `chunk_embeddings`, `model_metadata` or vector-related tables may remain in an old DB for migration evidence. Existence != authority.
- Do not re-enable an embedding service merely because compatible tables exist. A future change requires a new Golden Query evaluation that demonstrates a material quality/cost benefit.
- Graph is an optional rebuildable projection and must not become a hidden retrieval dependency.

The Base intentionally does not hard-code a historical benchmark percentage. Historical reports may represent different datasets/service availability; the current Golden Set is the decision authority for future retrieval changes.

## Golden Query evaluation

Use:

```text
ai-work knowledge eval --workspace-root <workspace>
```

The default Golden Set is configured under `systems.knowledge.evaluation.golden_set`. Evaluation is local and must not pollute real usage telemetry.

Standard metrics:

- Recall@20
- MRR
- nDCG@5
- Top-5 hit rate
- no-answer false-recall rate
- p50 / p95 latency

`canonical_first_fts` is the product mode. `source_only_fts` and `filename_search` are comparison baselines only.

## Usage telemetry

Normal `knowledge search` stores only a hash of the query plus retrieval mode, fallback/result metadata and latency. It must not persist raw query text.

Use:

```text
ai-work knowledge telemetry --days 7
```

Product-facing signals are query volume, canonical-only hits, source fallback, no-result rate and latency. These are more useful than Markdown count for deciding whether Knowledge helps Agents.
