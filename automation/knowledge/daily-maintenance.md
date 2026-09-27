# Knowledge Daily Maintenance Protocol

## 1. Execution model

This protocol is run by an unattended **conversational model**, not by a blind cron script. The model supplies semantic judgment; deterministic CLI supplies inventory, hashes, lint, projection and baseline enforcement.

Never call `AskUserQuestion`. If a required business decision cannot be derived from configured authority/evidence, return `NEEDS_REVIEW` and make no trust-advancing write.

## 2. Bootstrap

1. Resolve the current Base and Content Systems for each enabled, registered, non-archived workspace/project. Group by the resolved physical Knowledge System Root, normalizing equivalent paths according to the host filesystem. Multiple workspaces sharing a Vault are one maintenance unit; do not run a full chain per workspace or run writers concurrently against the same Vault.
2. Before choosing a command workspace, check that the group's registry, projection DB, meta root, effective Knowledge maintenance/quality configuration (including workspace quality-policy overrides) agree. Different project identities are expected; conflicting shared-state paths or policies are not. If consistency cannot be established, mark that Vault `NEEDS_REVIEW` without choosing one project's settings over another's.
3. Check that the scheduled scope permits the Vault-level scan/index/verification/baseline operations. These commands cover the physical Vault, not only the chosen workspace's project. A project-only authorization cannot silently become a whole-Vault write. Content outside the configured project/shared scope must not be rewritten or assigned by guess; unresolved or out-of-scope changes prevent advancing that Vault's baseline.
4. Select one resolved workspace from each consistent, authorized group for that run's Vault-level commands. Read `agents/tp-knowledge/SKILL.md`, follow its scheduled-maintenance capability, and read the applicable `knowledge/rules/*` plus this file from the current Base. Execute one serial chain per Vault:

```text
tp-spec knowledge doctor --workspace-root <workspace>
tp-spec knowledge maintain --workspace-root <workspace>
```

Do not treat a missing optional Junction as a Knowledge failure. Do not use legacy `tools/kb-*` from the Vault as runtime authority.

`doctor` and `index status` inspect the existing projection without initializing or repairing its schema. A missing, incomplete or corrupt index is reported; only explicit index build/update initializes or migrates it. Checking freshness still reads the Vault's canonical/source files. `maintain`/`scan` write the shared change set, `verify` writes a verification receipt, and index/audit/snapshot operations have their documented write effects; none of these should be presented as read-only diagnostics.

Keep project content decisions and retrieval scoped to the corresponding resolved workspace or explicit project ID, with current project + registered shared as the default. Grouping maintenance by Vault does not authorize `--scope global` retrieval. If any project remains unresolved, safe content work may continue elsewhere in the group, but do not commit the shared baseline until all staged changes have valid dispositions and the normal gates pass. Independent Vaults may continue.

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

Daily maintenance must not silently turn an unknown Vault into a trusted baseline. Use read-only `doctor/index status` to report initial-baseline work required, then stop unless the scheduled task was explicitly created for first initialization. `verify` writes a receipt and is not part of this read-only branch; do not build an index or create a trusted baseline just to clear this status.

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

Keep the report short. Report scan/index/verify/L4/baseline once per physical Vault, then list each workspace/project's content changes, dispositions and blockers. Do not claim independent per-project baseline commits when the state is shared. A project `NEEDS_REVIEW` must remain visible and prevent a successful whole-Vault conclusion.

```text
Knowledge Daily: PASS | NEEDS_REVIEW | BLOCKED
Vault / command workspace: ...
Projects in scope: ...
Truth changes: ...
Canonical updated: ...
Source dispositions: ...
Verify: ...
Index: ...
L4: ...
Baseline: ...
Retrieval 7d: queries / canonical-hit / source-fallback / no-result / avg latency
Human review: ...
Per-project content results: ...
```
