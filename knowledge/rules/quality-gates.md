# Knowledge Quality Gates

Knowledge quality is split into deterministic gates plus targeted semantic audit. A daily model must use these gates rather than declaring the Vault healthy from intuition.

## L1 — Integrity

Checks canonical syntax and stable structure:

- frontmatter/schema
- canonical ID format/uniqueness
- project registration
- kind/status/filename contract
- relation enum and relation-target kind
- broken vault-root wikilinks; legacy basename-only links are migration advisories, not false hard failures
- cycle constraints

### Gate 定级策略

lint 只产生事实（`violations`/`warnings`/`advisories`）；verify 硬门通过质量政策
`knowledge/rules/quality-policy.yaml` 定级（workspace 可在 `.tp-spec/config/quality-policy.yaml` 按 rule_id 覆盖）：

- `block`: violations 计入 `gate_errors`（决定 FAIL），warnings 计入 `gate_warnings`
- `warn`: violations/warnings 计入 `gate_warnings`（决定 WARN，不 FAIL）
- `backlog`: 不参与 verify 硬门，作为 LEGACY/INFORMATIONAL 遗留随 baseline 保留，须在验收报告中单独列出

当前 backlog 规则：K011（断链 wikilink）、K018（related_to 缺 note）、K010（legacy basename/non-standard wikilink）、K015（未本地解析的 legacy SRC 引用）。
verify receipt 保留原始 lint 计数（`lint.errors/warnings/advisories`），不因 gate 排除而隐藏。

## L2 — Traceability

Checks that a canonical claim has durable evidence identity:

- non-empty `source_refs` or `evidence_refs`
- local `SRC-*` refs resolve when explicitly registered/locally managed; unresolved legacy symbolic refs are migration advisories
- structured evidence fields are valid
- registered source records have SHA-256 and disposition
- no silent source loss

Compatibility `TASK-*` refs without a configured task root are reported as externally-resolvable evidence, not falsely marked locally verified.

## L3 — Content/Projection Quality

Checks:

- duplicate/near-empty canonical warnings
- stale or missing FTS projection
- excluded paths accidentally indexed
- vector rows while vector mode is retired
- source-accountability metrics
- canonical-first retrieval invariants
- optional Golden Query regression (`knowledge eval`) when retrieval behavior changes

Projection health is not canonical truth. Rebuilding the DB must not change canonical Markdown.

## L4 — Semantic Audit

A conversational model reads the targeted canonical plus supporting evidence and challenges:

1. Is the claim actually supported by the cited evidence?
2. Is an observation being presented as a timeless fact?
3. Is a compatibility/retired mechanism being described as current authority?
4. Is responsibility attributed to the correct enforcing layer?
5. Is there an existing canonical that should be updated/merged instead of a duplicate?
6. Did the source change materially enough to require canonical change?
7. Are numeric/API/config assertions copied from real evidence rather than inferred?

Unattended L4 must not ask the user questions. Ambiguity produces `BLOCKED/NEEDS_REVIEW` and leaves the previous trusted baseline intact.
