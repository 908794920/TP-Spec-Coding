# Knowledge Standardization — V5.2.5

Knowledge is the long-lived reusable context layer of TP-Spec-Coding. It stores **why a project behaves as it does, business rules, durable decisions, external-document knowledge, and reusable operating facts**. It is not a copy of Task history and it is not the current source-code authority.

## Authority model

```text
External docs / Task evidence / code evidence
                  ↓
          source/evidence layer
                  ↓
        Canonical Knowledge Markdown
                  ↓
   SQLite FTS5 / links / graph projection
                  ↓
             tp-knowledge
```

- Canonical Markdown + registered evidence are the Knowledge truth layer.
- The configured projection DB is a **rebuildable retrieval projection**, not the truth source.
- Default retrieval is `canonical-first-fts5` with source fallback, scoped to the **current project + registered shared scopes**. Cross-project/global retrieval is explicit only.
- Embedding/vector retrieval is `retired-compatible`: it was historically evaluated but the measured recall gain over FTS5 did not justify the operating cost. It must not silently become the default path.
- Graph data is optional, rebuildable navigation projection.

## Base-owned standard

The Base owns the active rules and executable behavior:

- `agents/tp-knowledge/SKILL.md`
- `cli/knowledge/`
- `knowledge/rules/` (including retrieval/evidence/ingestion/quality contracts)
- `knowledge/schema/`
- `knowledge/templates/`
- `automation/knowledge/`
- `governance/content-systems.yaml`

A Knowledge Vault should contain knowledge data, user dictionaries/registry, evidence and machine state. It should not carry a second competing runtime or a second copy of these Base rules.

## Default data layout

```text
<knowledge-root>/
├─ AGENTS.md                       # local physical/data boundary only
├─ 00-system/
│  ├─ project-registry.yaml
│  ├─ dictionaries/                # user/business dictionaries
│  └─ eval/golden.jsonl            # optional user-owned evaluation data
├─ 10-projects/<project-id>/
│  ├─ 00-project/
│  ├─ 10-domain/
│  ├─ 20-architecture/
│  ├─ 30-features/
│  ├─ 40-interfaces/
│  ├─ 50-data/
│  ├─ 60-jobs/
│  ├─ 70-operations/
│  └─ 90-sources/
├─ 20-shared/
├─ 90-archive/                     # optional canonical/archive history
└─ .ai-kb/
   ├─ knowledge.db                  # default rebuildable retrieval projection
   ├─ meta/                        # snapshot/verify/audit/source registry
   └─ ingest/                      # registered ingest batches
```

Use `tp-spec knowledge search` as the Agent retrieval entry and `tp-spec knowledge eval` for Golden Query regression. See the rule files in this directory for the executable contract. Project-specific paths belong in Content Systems configuration or the project registry; do not hard-code them into Base code or prompts.

## Trusted baseline binding

For truth-changing maintenance, the final trust sequence is:

```text
final canonical/evidence/source-registry writes
→ knowledge scan
→ index update
→ verify
→ L4/audit-record when required
→ snapshot-commit
```

`knowledge scan` must occur **after** the final semantic write. Audit and snapshot advancement fail closed when their staged change set does not bind the current Knowledge truth.

## Legacy normalization

Before a large legacy Vault spends model tokens on semantic repair, run `tp-spec knowledge migrate-normalize` in dry-run mode. `--apply` only performs semantics-preserving structural/alias conversions and writes a receipt/review queue under `.ai-kb/meta/`; missing evidence, unknown relation meaning, missing confidence/verification facts remain for targeted `tp-knowledge` review. See `knowledge/rules/migration-standard.md`.
