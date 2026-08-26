# TP-Spec-Coding v5.2.4 Role-first Software Engineering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut over TP-Spec-Coding from the v5.2.3 action-role model to one canonical v5.2.4 formal software-engineering role model without losing the existing lightweight lifecycle, Record-first runtime, migration discipline, Autonomy safety envelope, Wiki, Knowledge, Memory, UltraPlan, or UltraReview behavior.

**Architecture:** `tp-spec-coding` becomes the low-context product router and `tp-software-lifecycle` the sole software-domain agent. The active software model uses nine formal roles and role capabilities; lifecycle phase, formal role, execution mode, and effects remain orthogonal. Existing five public task states and SQLite schema remain unchanged; legacy v5.2.3 role/state mappings move to migration/history-only code and are denied in active runtime by a repo-wide no-tail scanner.

**Tech Stack:** Python 3, PyYAML, jsonschema, SQLite, Markdown/YAML Agent Skills, pytest, PowerShell compatibility scripts.

**Spec:** `docs/superpowers/specs/2026-08-18-v5.2.4-role-first-design.md`

## Global Constraints

- Active version must converge to exactly `5.2.4`; current branch keeps exactly one active contract.
- Public task states remain exactly `NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED`.
- `phase` remains an audit/query fact, never a public state or mandatory toll gate.
- No new database object may be introduced for lifecycle/role/skill/gate state.
- L0-L3 remain the first-level lifecycle cost controls; roles and sub-skills are additionally lazy-selected.
- `mode` is an execution strategy and `effects` are fail-closed safety capabilities; `repo_mutation` semantics must not weaken.
- AI must use existing atomic CLI writes; no new per-role/per-skill bookkeeping CLI.
- Pure governance overhead must remain within the existing 5% budget target.
- Historical actor/owner role values remain readable and immutable; active runtime contains only the new canonical role model.
- `project upgrade-contract` + `task migration-plan` + `task migrate` remains the official upgrade chain.

---

### Task 1: Freeze baseline and machine-generate old-role inventory

**Files:**
- Create: `scripts/role_reference_inventory.py`
- Create: `scripts/tests/test_v524_role_reference_inventory.py`
- Create: `docs/v5.2.4/V523_ROLE_REFERENCE_INVENTORY.md` (generated evidence)
- Create: `docs/v5.2.4/V523_LEGACY_CALL_GRAPH.md` (generated evidence)

**Interfaces:**
- Produces: `scan_role_references(root: Path) -> list[RoleReference]`
- Produces: `classify_reference(path: Path, line: str) -> str`
- Produces: CLI `python scripts/role_reference_inventory.py --root . --write-report`

- [ ] **Step 1: Write failing tests** proving inventory finds `commit_cmd.py`, `receipt_cmd.py`, `config_loader.py`, `workflow_loader.py`, and classifies active vs migration/history references.
- [ ] **Step 2: Run** `python -m pytest scripts/tests/test_v524_role_reference_inventory.py -q` and confirm failure because scanner does not exist.
- [ ] **Step 3: Implement** immutable v5.2.3 role-id set, tracked-text-file scan, line-level classification, and deterministic JSON/Markdown report generation.
- [ ] **Step 4: Re-run** the focused test and generate the two baseline reports.
- [ ] **Step 5: Commit** baseline scanner and evidence.

### Task 2: Introduce the v5.2.4 formal Agent/Role/Capability catalog

**Files:**
- Create: `agents/tp-spec-coding/SKILL.md`
- Create: `agents/tp-software-lifecycle/SKILL.md`
- Create: `skills/tp-product-manager/SKILL.md`
- Create: `skills/tp-software-architect/SKILL.md`
- Create: `skills/tp-tech-lead/SKILL.md`
- Create: `skills/tp-security-engineer/SKILL.md`
- Create: `skills/tp-development-engineer/SKILL.md`
- Create: `skills/tp-database-engineer/SKILL.md`
- Create: `skills/tp-test-engineer/SKILL.md`
- Create: `skills/tp-code-reviewer/SKILL.md`
- Create: `skills/tp-integration-engineer/SKILL.md`
- Modify: `agents/role-catalog.yaml`
- Modify: `scripts/update_role_catalog.py`
- Create: `scripts/tests/test_v524_role_catalog.py`

**Interfaces:**
- Role catalog keeps `workflow_role` for runtime identity but adds optional `domain`, `phases`, `capabilities`, `orchestration_capabilities`, and `subskills` metadata.
- `update_role_catalog.py --verify` validates all declared subskill paths and canonical role frontmatter.

- [ ] **Step 1:** Add failing tests for exact canonical role ids, no old active role ids, subskill-path validation, capability host metadata, and `NEW` ownership by `tp-software-lifecycle`.
- [ ] **Step 2:** Run focused tests and confirm failure on old catalog.
- [ ] **Step 3:** Create the two agents and nine role Skills by migrating all useful v5.2.3 responsibilities into formal-role boundaries; link existing generic skills where useful.
- [ ] **Step 4:** Upgrade catalog schema/validator and regenerate hashes.
- [ ] **Step 5:** Re-run role-catalog tests and `python scripts/update_role_catalog.py --verify`.

### Task 3: Cut governance from action-role to role-first lifecycle policy

**Files:**
- Modify: `governance/ai-role.yaml`
- Modify: `governance/orchestration.yaml`
- Modify: `governance/workflow.yaml`
- Modify: `governance/risk-rule.yaml`
- Modify: `governance/planning-strategy.yaml`
- Modify: `cli/config_schemas.py`
- Create: `scripts/tests/test_v524_role_first_contract.py`

**Interfaces:**
- Orchestration steps retain `stage`, `phase`, `mode`, `effects`, and use `role` as canonical formal role.
- Contract adds `conditional_roles` and capability-host checks while keeping existing route schema compatible.

- [ ] **Step 1:** Add failing contract tests for single software-domain agent, nine canonical roles, discovery phase preservation, mode capability hosts, conditional security/database roles, and unchanged five states.
- [ ] **Step 2:** Run focused contract tests and confirm failure.
- [ ] **Step 3:** Rewrite governance to the approved role-first matrix and preserve L0-L3 cost behavior.
- [ ] **Step 4:** Extend schema validation only as needed; do not add state-machine schema.
- [ ] **Step 5:** Run focused tests plus existing orchestration-contract tests updated for v5.2.4 semantics.

### Task 4: Make orchestration capability-based while preserving effects fail-closed

**Files:**
- Modify: `cli/orchestration.py`
- Modify: `cli/orchestration_cmd.py`
- Create: `scripts/tests/test_v524_role_resolver.py`
- Create: `scripts/tests/test_v524_effects_parity.py`

**Interfaces:**
- Add `role_capabilities(catalog, role_id) -> set[str]`.
- Add `conditional_roles_for(stage, task, events, signals, contract) -> list[dict]`.
- Route output may add `recommended_roles`, `recommended_skills`, and `reason_codes` without persistence.
- `AUTO_PLANNING` requires `auto_planning_host`; `AUTO_REVIEW` requires `auto_review_host`.

- [ ] **Step 1:** Write failing tests for mode-host capability checks, security/database conditional recommendation, and repo-mutation denial when not in allowed effects.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Replace old-id mode checks with capability checks and add read-only role/subskill recommendations.
- [ ] **Step 4:** Preserve material/each-stage confirmation semantics and effects at assignment level.
- [ ] **Step 5:** Run focused tests and existing v5.1.4 orchestration adversarial/integration/router suites.

### Task 5: Separate Test, Code Review, Architecture Review, and Security trust contracts

**Files:**
- Modify: `cli/review_cmd.py`
- Modify: `cli/record_first.py`
- Modify: `cli/workflow_records.py`
- Modify: `cli/delivery_contract.py`
- Modify: `cli/context_effectiveness.py`
- Modify: `cli/autonomy_integration.py`
- Create: `scripts/tests/test_v524_review_isolation.py`
- Create: `scripts/tests/test_v524_trusted_role_results.py`

**Interfaces:**
- Formal architecture review actor is `tp-software-architect` with explicit `review_kind=architecture` and isolation proof.
- Test PASS actor is `tp-test-engineer`.
- Code-review PASS actor is `tp-code-reviewer`.
- Security findings never cancel deterministic scanner findings.

- [ ] **Step 1:** Write failing tests for same-context architecture review rejection, stale subject rejection, separate test/review actors, and autonomy verification binding.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement trusted-result rules using existing events/evidence, not new states/tables.
- [ ] **Step 4:** Preserve v5.2.3 evidence truthfulness and rework routing.
- [ ] **Step 5:** Run focused tests plus v5.2.2 contracts/context-effectiveness and v5.2.3 autonomy-integration suites.

### Task 6: Migrate task/session/projection ownership away from old roles

**Files:**
- Modify: `cli/task_cmd.py`
- Modify: `cli/work_session_cmd.py`
- Modify: `cli/rework_cmd.py`
- Modify: `cli/projection_cmd.py`
- Modify: `cli/receipt_cmd.py`
- Modify: `cli/reuse_warnings.py`
- Modify: `cli/anchor_check.py`
- Create: `scripts/tests/test_v524_task_role_ownership.py`

**Interfaces:**
- New task starts with `owner_role=tp-software-lifecycle`, then deterministic routing assigns the formal role.
- Historical old actor/owner values remain displayable without active catalog membership.

- [ ] **Step 1:** Write failing tests for task creation owner, session fallback, rework owner, receipt actor list, and historical projection readability.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Replace active old-role fallback/choice sets with catalog-derived formal roles.
- [ ] **Step 4:** Keep history rendering tolerant without adding old roles back to active catalog.
- [ ] **Step 5:** Run focused tests and existing runtime-hardening/record-first/portability suites.

### Task 7: Retire active legacy workflow dependencies

**Files:**
- Create: `cli/migrations/v5_2_3/__init__.py`
- Move/adapt: `cli/legacy_workflow.py` -> `cli/migrations/v5_2_3/legacy_workflow.py`
- Refactor: `cli/transition_service.py`
- Modify: `cli/config_loader.py`
- Modify: `cli/workflow_loader.py`
- Modify: `cli/event_cmd.py`
- Modify: `cli/commit_cmd.py`
- Modify: `cli/main.py`
- Create: `scripts/tests/test_v524_legacy_runtime_retirement.py`

**Interfaces:**
- Active workflow/config loaders parse only active five-state workflow.
- Migration/history readers explicitly import `cli.migrations.v5_2_3.legacy_workflow`.
- Normal daily runtime no longer exposes legacy long-state `commit` as a canonical path.

- [ ] **Step 1:** Write failing tests asserting active loaders do not import legacy maps and migration reader still decodes legacy data.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Split current-runtime helpers from old transition matrix, move frozen mappings to migration namespace, and remove active fallbacks.
- [ ] **Step 4:** Keep admin/migration recovery explicit and fail closed.
- [ ] **Step 5:** Run legacy-removal and existing migration/recovery suites.

### Task 8: Add product router and low-context domain routing

**Files:**
- Create: `cli/product_router.py`
- Create: `cli/product_cmd.py`
- Modify: `cli/main.py`
- Create: `scripts/tests/test_v524_product_router.py`

**Interfaces:**
- `route_domain(text: str, *, active_task_domain: str|None=None) -> DomainDecision`.
- CLI `tp-spec route --text ... --json` is read-only and performs no repo/knowledge/task-full scan.

- [ ] **Step 1:** Write failing tests for explicit software/wiki/knowledge/base/autonomy routing and ambiguous fallback behavior with spies proving no deep readers are called.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement deterministic shallow signals and compact route result.
- [ ] **Step 4:** Add Status/Explain hooks only from existing compact runtime facts; no new ledger.
- [ ] **Step 5:** Run router cost tests.

### Task 9: Normalize pre-task Product/Requirement handoff without making Task heavier

**Files:**
- Modify: `cli/task_cmd.py`
- Modify: `templates/5.2.4/requirement-clarifications.md`
- Create: `templates/5.2.4/requirement.md`
- Modify: `templates/5.2.4/task.md`
- Create: `scripts/tests/test_v524_requirement_ready.py`

**Interfaces:**
- Existing `task create --from-intake` accepts canonical requirement input and still permits pre-task work with no TaskId.
- Simple Requirement Ready input does not require empty artifacts.

- [ ] **Step 1:** Write failing tests for raw/ready intake behavior, no empty-document requirement, and preserved mature-requirement fast path.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement canonical requirement template/ingestion with source provenance and minimal required semantics.
- [ ] **Step 4:** Preserve existing clarifications/decisions when they contain real information.
- [ ] **Step 5:** Run focused tests and existing task-create crash-recovery tests.

### Task 10: Strengthen Code Reviewer using deterministic review scaffolding

**Files:**
- Create: `cli/review_locator.py`
- Modify: `cli/anchor_check.py`
- Modify: `cli/review_preflight.py`
- Modify: `skills/tp-code-reviewer/SKILL.md`
- Create: `scripts/tests/test_v524_review_locator.py`

**Interfaces:**
- `locate_existing_code(existing_code, diffs) -> unique location | None` uses deterministic hunk/full-file/cross-file unique matching.
- OCR integration remains optional adapter guidance; TP-Spec runtime truth remains authoritative.

- [ ] **Step 1:** Write failing tests for hunk match, full-file fallback, unique cross-file relocation, and ambiguous cross-file refusal.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement the small deterministic locator adapted from the Apache-2.0 Alibaba OpenCodeReview algorithm with attribution.
- [ ] **Step 4:** Integrate as best-effort anchor enhancement; never turn ambiguity into a guessed line.
- [ ] **Step 5:** Run focused review-preflight/anchor tests.

### Task 11: Add task-scoped Knowledge handoff and lightweight Integration git facts

**Files:**
- Modify: `cli/workflow_records.py`
- Modify: `cli/knowledge/commands.py`
- Modify: `cli/knowledge/state.py`
- Modify: `skills/tp-integration-engineer/SKILL.md`
- Modify: `agents/tp-knowledge/SKILL.md`
- Create: `scripts/tests/test_v524_delivery_knowledge_handoff.py`

**Interfaces:**
- Delivery result stores lightweight `repo_snapshot.before_head/after_head/merge_commit` in existing event detail JSON.
- `tp-knowledge` owns `task-scoped convergence`; Integration only hands off verified facts.
- `NO_CHANGE` remains a valid low-cost outcome.

- [ ] **Step 1:** Write failing tests for repo snapshot facts, Integration-not-owning Knowledge decisions, and task-scoped Knowledge `NO_CHANGE` fast path.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement compact handoff using existing storage/event structures only.
- [ ] **Step 4:** Ensure no delivery blocking solely because Knowledge returns NO_CHANGE/DEFERRED.
- [ ] **Step 5:** Run delivery/knowledge/context usage tests.

### Task 12: Implement official v5.2.3 -> v5.2.4 migration and one-active-contract cutover

**Files:**
- Create: `cli/migrations/v5_2_3/role_map.py`
- Modify: `cli/task_cmd.py`
- Modify: `cli/project_cmd.py`
- Modify: `governance/compat-matrix.yaml`
- Modify: `governance/runtime-api.yaml`
- Modify: `cli/config_schemas.py`
- Create: `templates/5.2.4/*` migrated active templates
- Modify: all active Agent/Skill frontmatter versions
- Modify: `VERSION`
- Create: `scripts/tests/test_v524_migration.py`

**Interfaces:**
- Completed history unchanged.
- Active task owner mapping is deterministic and idempotent.
- Active project contract must be upgraded before task migration.

- [ ] **Step 1:** Write failing migration tests for each old active owner, BLOCKED task, repeated migration, interrupted migration, and project-before-task ordering.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement migration-only old->new role map and active task conversion.
- [ ] **Step 4:** Cut all active versioned governance/templates/frontmatter to `5.2.4` and keep compat-matrix single-active.
- [ ] **Step 5:** Run migration/integrated-upgrade/version-purity tests.

### Task 13: Remove active old Action Skills/Agent and enforce repo-wide no-tail

**Files:**
- Delete: `agents/tp-workflow-orchestrator/SKILL.md`
- Delete: seven old active Action Skill directories after capability parity is proven
- Modify: current docs/help/scripts/PowerShell utilities referring to old active roles
- Modify: `scripts/role_reference_inventory.py` to support `--no-tail`
- Create: `scripts/tests/test_v524_no_tail.py`

**Interfaces:**
- Old role ids are allowed only under explicit migration/history/test-fixture/CHANGELOG paths.
- Active source/governance/docs/help must be clean.

- [ ] **Step 1:** Write failing no-tail test with DEFAULT DENY and explicit migration/history allowlist.
- [ ] **Step 2:** Verify RED and capture every remaining active old-role reference.
- [ ] **Step 3:** Migrate/remove each active reference; do not widen allowlist to hide problems.
- [ ] **Step 4:** Delete old Agent/Skills once catalog/orchestration no longer references them.
- [ ] **Step 5:** Run `python scripts/role_reference_inventory.py --no-tail` and tests until PASS.

### Task 14: Release convergence, docs, manifest, and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/AGENTS_AND_SKILLS.md`
- Modify: `docs/GETTING_STARTED.md`
- Modify: `CHANGELOG.md`
- Modify: `manifest.sha256`
- Update/create: release/snapshot tests as required by active contract

**Interfaces:**
- Current product docs show `tp-spec-coding` as default entry, `tp-software-lifecycle` as sole software domain agent, and nine formal roles.

- [ ] **Step 1:** Add/update release tests before changing current docs/snapshot expectations; confirm RED.
- [ ] **Step 2:** Update user-facing docs and changelog with R3 rationale and migration command sequence.
- [ ] **Step 3:** Regenerate role hashes and manifest/snapshot with existing project scripts.
- [ ] **Step 4:** Run focused v5.2.4 tests, all v5.2.x regression suites, then full `python -m pytest scripts/tests -q` in chunks if a single run exceeds harness timeout.
- [ ] **Step 5:** Run `python scripts/update_role_catalog.py --verify`, workflow doctor, version-purity, no-tail, migration rehearsal, and package smoke.
- [ ] **Step 6:** Produce `git diff --binary 6ae4259..HEAD` / working-tree patch and an incremental ZIP containing only added/modified files plus deletion manifest.
