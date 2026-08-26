# Temporary Artifact and Work Session Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move TP-Spec test/runtime temporary artifacts out of project workspaces into owned system-temp run roots with safe cleanup/recovery, and make role work-time reporting pair overlapping work sessions by `session_id` instead of event order.

**Architecture:** Keep Runtime SQLite and the five Task states unchanged. Add one machine-local `temp_artifacts` module that owns system-temp paths plus durable JSON ownership manifests under the TP-Spec user root; existing `task artifact-path --kind execution-temp`, work-session lifecycle, task terminal lifecycle, and a small `temp orphan-check/cleanup` CLI reuse that module. Role timing remains read-only over existing `WORK_SESSION_STARTED/ENDED` events and is fixed to correlate by `detail_json.session_id` and aggregate by `actor_role`.

**Tech Stack:** Python 3.10+, pathlib/tempfile/json/os/shutil/sqlite3, existing argparse CLI and unittest/pytest suite. No new third-party dependency, database table, background service, polling, or external network.

**Spec:** User-approved scope in this conversation, grounded by `/mnt/data/4dccaf6f-d5fb-4edb-84a8-960933800e59.txt` and current Base source resolved as v5.2.7 from `/mnt/data/tp_src_check`.

## Global Constraints

- Keep public Task states exactly `NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED`.
- `CLEANUP_PENDING` is only a temporary-artifact cleanup status; never a Task state.
- Do not edit Runtime SQLite directly outside existing Runtime APIs; do not change `db/schema.sql`.
- Do not edit historical `status.yaml`, `events.jsonl`, `generated/*`, Task evidence, IDC business code, Wiki, Knowledge, Memory, or intake files.
- User source files are immutable: they may be read or copied into an owned temp root, but never overwritten, moved, or deleted by cleanup.
- Cleanup may delete only a path that has a valid ownership manifest and remains inside the configured TP-Spec system temp root at cleanup time.
- Cleanup must not follow symlinks, Windows Junction/reparse points, or any resolved path escaping the owned run root.
- Historical/unmanaged `.tmp` directories are report-only; never auto-delete without ownership evidence.
- Normal success/failure/cancel paths perform best-effort idempotent cleanup. Hard crashes/reboots are handled by persistent manifests plus later reconcile/orphan detection, not by pretending `finally` can run after process death.
- All new source-code comments added for this feature use Chinese.
- Existing offline/Web Artifact card behavior must not regress.

---

### Task 1: Owned system-temp roots and durable manifests

**Files:**
- Create: `cli/temp_artifacts.py`
- Create: `scripts/tests/test_v526_temp_artifacts.py`

**Interfaces:**
- Produces `create_run_root(project_id, task_id, creator_role, creator_agent="", run_id=None, user_root=None, temp_root=None) -> TempArtifactRecord`.
- Produces `cleanup_run(run_id, user_root=None, temp_root=None) -> CleanupResult`.
- Produces `list_records(user_root=None)`, `orphan_report(...)`, and safe path predicates reused by CLI/lifecycle hooks.

- [ ] Write failing tests proving a run root is created under `tempfile.gettempdir()/tp-spec/<project>/<task>/<run>` rather than under the workspace.
- [ ] Run the targeted test and confirm it fails because `cli.temp_artifacts` does not exist.
- [ ] Implement minimal path/manifest creation with atomic JSON manifest writes and statuses `ACTIVE`, `CLEANED`, `CLEANUP_PENDING`.
- [ ] Add failing tests for idempotent cleanup, missing root, Chinese/space path values, concurrent run ids, and immutable source files outside the owned root.
- [ ] Implement cleanup so it revalidates manifest identity and controlled-root containment immediately before deletion.
- [ ] Add failing tests for path traversal, symlink escape and a simulated Windows reparse-point predicate; implement fail-closed deletion that removes only the link itself and never traverses its target.
- [ ] Verify all Task 1 tests pass.

### Task 2: Migrate `execution-temp` to the owned temp API and expose maintenance CLI

**Files:**
- Modify: `cli/task_cmd.py`
- Modify: `cli/main.py`
- Create: `cli/temp_cmd.py`
- Test: `scripts/tests/test_v526_temp_artifacts.py`

**Interfaces:**
- `task artifact-path --kind execution-temp` resolves the project from the formal binding/project context, creates or reuses an owned run root, and supports an explicit run id/session id; verification/evidence artifact paths remain unchanged.
- New read/maintenance commands: `tp-spec temp orphan-check` (report only), `tp-spec temp cleanup --run-id <ID>` (owned paths only), and `tp-spec temp summary`.

- [ ] Write failing CLI tests showing `execution-temp --ensure` no longer creates `<workspace>/.tp-spec/.execution/...` or `<workspace>/.tmp/...`.
- [ ] Implement the minimal adapter from `cmd_task_artifact_path` to `temp_artifacts` while preserving `verification-sql` and `test-evidence` behavior.
- [ ] Write failing tests showing missing/ambiguous project identity fails closed rather than deriving `project_id` from a directory name.
- [ ] Implement `temp orphan-check`, `temp cleanup`, and `temp summary`; make orphan-check report unmanaged candidates without deleting them.
- [ ] Verify Task 2 tests pass.

### Task 3: Work-session and terminal lifecycle cleanup hooks

**Files:**
- Modify: `cli/work_session_cmd.py`
- Modify: `cli/record_first.py`
- Modify: `cli/temp_artifacts.py`
- Test: `scripts/tests/test_v526_temp_artifacts.py`

**Interfaces:**
- `work start` keeps its existing Runtime event and makes its `session_id` usable as a temp run id; no temp directory is created until requested.
- `work end` best-effort cleans manifests owned by that `session_id` after the authoritative END event succeeds.
- `task complete` and `task cancel` perform a second idempotent cleanup pass for all owned temp runs for that Task and return/report a cleanup summary without changing successful Runtime results into failures.

- [ ] Write failing tests proving `work end` cleans the matching owned session root and leaves another role/run untouched.
- [ ] Implement session-bound cleanup after `WORK_SESSION_ENDED` commit; on failure persist `CLEANUP_PENDING` and print a warning.
- [ ] Write failing tests for task complete/cancel cleanup, repeated cleanup, and cleanup failure that leaves Task state success intact.
- [ ] Implement terminal Task cleanup hooks and compact summary `{created, cleaned, pending}`.
- [ ] Add crash-recovery tests: an `ACTIVE` manifest from a no-longer-open work session appears in orphan/reconcile reporting and can be explicitly cleaned; no automatic deletion of unregistered historical `.tmp` is allowed.
- [ ] Verify Task 3 tests pass.

### Task 4: Test Engineer contract and lifecycle policy

**Files:**
- Modify: `skills/roles/tp-test-engineer/SKILL.md`
- Modify: `agents/tp-software-lifecycle/SKILL.md`
- Modify: `governance/runtime-api.yaml`
- Test: `scripts/tests/test_v526_temp_artifacts.py`

**Interfaces:**
- Policy requires standard owned system-temp roots for generated test fixtures and prohibits ad-hoc workspace `.tmp` for new runs.
- It explicitly distinguishes immutable user input/intake/evidence from disposable owned temp copies.

- [ ] Write failing contract tests for the required temp-root, ownership, cleanup-pending, unmanaged-report-only, and immutable-source rules.
- [ ] Update the role/lifecycle/runtime API documentation with concise Chinese rules; do not create a new Role or Task state.
- [ ] Verify the contract tests and role-catalog consistency inputs pass.

### Task 5: Fix overlapping Work Session timing and add role totals

**Files:**
- Modify: `cli/report_cmd.py`
- Test: `scripts/tests/test_v526_temp_artifacts.py`

**Interfaces:**
- Stage-time pairing uses `detail_json.session_id`, falling back conservatively for legacy events without ids.
- Completed sessions are attributed to the stage active at their START timestamp.
- Output adds role-level measured work-session totals and does not call event gaps “work time”.

- [ ] Write a failing test with interleaved sessions: Test START, Reviewer START, Test END, Reviewer END; prove the current single `open_session` implementation mispairs durations.
- [ ] Implement session-id keyed pairing plus legacy fallback without changing event schema.
- [ ] Write failing tests for two sessions of the same role, unmatched start/end events, waiting reasons, and role aggregation.
- [ ] Implement compact role totals and measured/unmeasured labels; never infer time for roles without paired sessions.
- [ ] Verify Task 5 tests pass.

### Task 6: Release convergence, deterministic gates, and incremental delivery

**Files:**
- Modify: `CHANGELOG.md`
- Modify as generated by official tooling: `governance/role-catalog.yaml`, `manifest.sha256`
- Test: existing suite plus `scripts/tests/test_v526_temp_artifacts.py`

**Interfaces:**
- No release-version bump; this remains v5.2.7 hardening on the supplied working-tree baseline.
- Delivery is an incremental ZIP plus patch relative to the exact uploaded source state captured before this work.

- [ ] Run targeted new tests and relevant Runtime/Record-first/maintenance/report regressions.
- [ ] Run `python scripts/check_version_consistency.py`.
- [ ] Run `python scripts/update_role_catalog.py` (or repository-prescribed refresh) and then `--verify`.
- [ ] Run `python scripts/check_portability.py`.
- [ ] Run `python scripts/update_manifest.py`, stage the candidate release surface if required by the verifier, and run release verification without committing.
- [ ] Run `git diff --check`.
- [ ] Run the full pytest collection; if the sandbox timeout prevents one-shot completion, split by complete test-file batches and report exact totals rather than claiming an unobserved green run.
- [ ] Build an incremental ZIP and patch relative to `/mnt/data/tp_temp_hardening_baseline`, then reconstruct a clean copy from that baseline and verify both artifacts reproduce the candidate files and targeted gates.
