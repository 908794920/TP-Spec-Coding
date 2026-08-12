# Knowledge Legacy Normalization Protocol — V5.2.0

Use this protocol for Stage 3A style migration of an existing Knowledge Vault. It is **not** the daily maintenance protocol.

1. Run `knowledge migrate-plan`; resolve only control-root classification blockers first.
2. Run `knowledge migrate-normalize` in dry-run mode.
3. Review `safe_changes` and `review_queue`. Do not edit hundreds of notes manually before deterministic normalization.
4. If the safe plan is correct, run `knowledge migrate-normalize --apply`.
5. Re-run `knowledge lint`.
6. For remaining semantic findings, use targeted AI review only:
   - register legitimate projects missing from project-registry;
   - decide unknown relation vocabulary from real meaning/evidence;
   - supply missing confidence/verification date only from real evidence;
   - repair missing evidence by reading the actual source/task/code evidence;
   - never fabricate a source ref or verification date.
7. Re-run lint until `BLOCKER=0` and `SHOULD_FIX_BEFORE_BASELINE=0` under the migration policy.
8. Only then enter standardized baseline establishment: `scan → index update → verify → required L4 → audit-record → snapshot-commit`.

`KEEP_LOCAL_OUT_OF_SCOPE` roots are read from current Base configuration; they stay in place and are not indexed or maintained as project Knowledge unless explicitly ingested later.
