# Knowledge Daily Maintenance Protocol — V5.2.1

## 1. Execution model

This protocol is run by an unattended **conversational model**, not by a blind cron script. The model supplies semantic judgment; deterministic CLI supplies inventory, hashes, lint, projection and baseline enforcement.

Never call `AskUserQuestion`. If a required business decision cannot be derived from configured authority/evidence, return `NEEDS_REVIEW` and make no trust-advancing write.

## 2. Bootstrap

1. Resolve workspace/Base version and Content Systems.
2. Read `agents/tp-knowledge/SKILL.md`, `knowledge/rules/*` and this file from the current Base.
3. Run:

```text
tp-spec knowledge doctor --workspace-root <workspace>
tp-spec knowledge maintain --workspace-root <workspace>
```

Do not treat a missing optional Junction as a Knowledge failure. Do not use legacy `tools/kb-*` from the Vault as runtime authority.

## 3. Act on `maintain` result

### `NO_CHANGE`

- If projection is fresh and verify state is current: report no-op.
- Do not rewrite canonical just to create activity.

### `INDEX_ONLY`

- Run `knowledge index update`.
- Run `knowledge verify`.
- If PASS, commit the deterministic snapshot only when there is a real pending truth change; projection-only refresh does not manufacture a new Knowledge baseline.

### `VALIDATE_AND_INDEX`

The staged truth change is confined to canonical content/config already written outside this maintenance decision. Do not invent a second semantic rewrite just to create activity. Re-bind the final truth, then validate it:

```text
knowledge scan
knowledge index update
knowledge verify
knowledge audit              # when the staged change set requires L4
knowledge audit-record ...
knowledge snapshot-commit
```

If any canonical/evidence content changes after `knowledge scan`, the staged change set is stale and must be regenerated before L4/baseline.

### `WAITING_FOR_AI`

Read only the affected source/canonical/evidence set from the change set. For each semantic source change:

1. search existing canonical first;
2. decide `no_knowledge_change | update | create | merge | needs_review`;
3. modify the smallest canonical scope consistent with evidence;
4. never invent project assignment, API/config numbers, dates or responsibility;
5. destructive delete/merge, ambiguous project assignment or evidence conflict → `NEEDS_REVIEW`.

After **all** AI content/evidence/disposition writes are final, re-stage the truth before any trust-advancing step:

```text
knowledge scan               # mandatory after final semantic writes
knowledge index update
knowledge verify
knowledge audit              # only when the staged change set requires semantic audit
knowledge audit-record ...   # after actually reviewing the deterministic plan
knowledge snapshot-commit
```

`knowledge audit` must reject a stale change set rather than silently auditing the wrong subject. `snapshot-commit` must fail if the staged scan, projection, verification or required audit do not bind the same current truth.

### `INITIAL_BASELINE_REQUIRED`

Daily maintenance must not silently turn an unknown Vault into a trusted baseline. Run read-only `doctor/verify/index status`, report initial-baseline work required, and stop unless the scheduled task was explicitly created for first initialization.

### `BLOCKED` / `NEEDS_REVIEW`

Do not repair by guess. Preserve the existing trusted baseline and report exact blocker/evidence/path.

## 4. Quality semantics

Knowledge does **not** have a Wiki-style “every eligible source must become a document” target.

Report separately:

- registered source accountability;
- canonical traceability;
- projection freshness;
- canonical/source document counts;
- pending/quarantined/duplicate/excluded source dispositions;
- retrieval telemetry summary when available.

100% source accountability means every registered source has a disposition; it does not mean every source produces canonical content.

## 5. Daily report

Keep the report short:

```text
Knowledge Daily: PASS | NEEDS_REVIEW | BLOCKED
Truth changes: ...
Canonical updated: ...
Source dispositions: ...
Verify: ...
Index: ...
L4: ...
Baseline: ...
Retrieval 7d: queries / canonical-hit / source-fallback / no-result / avg latency
Human review: ...
```
