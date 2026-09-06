---
artifact: architecture-decision
decision_id: ADR-V531-GRAPHIFY-PROVIDER
artifact_contract:
  version: "5.3.1"
status: accepted
decision: NO_GO
decided_on: "2026-09-04"
source_evidence_sha256: "07f68374944031acfa2f3929a9345b16e75a94f151ee5585cc21b65a43819c64"
---

# v5.3.1 Graphify Provider M2 Decision

- **Decision: NO_GO**
- **Source Graph v1: NOT_IMPLEMENTED**
- **Remaining v5.3.1 feature scope:** Requirement Frontier and release convergence
- **Provider baseline:** `graphifyy==0.9.53`
- **Upstream commit:** `33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2`
- **Evaluated platform:** Windows 11 / Python 3.13.5
- **TP baseline:** `48fca09ee8978e058510aac90f3700e50a35a5b8`

## Decision Basis

The pinned public `extract(...)` path produced graphs that failed Graphify's own `assert_valid` contract before TP normalization or consumption:

1. The 18-file Java fixture failed with a dangling endpoint: edge target `retentionpolicy` had no matching node id.
2. The representative RuoYi scope (611 Java files) failed with the same class of error across JDK, framework, annotation, utility, and project symbols, including `list`, `set`, `autowired`, `stringutils`, and other targets with no node endpoint.
3. Because the upstream graph is invalid, TP-Spec-Coding's fail-closed evidence rule prohibits filtering, partially accepting, or silently repairing it inside an Adapter.

This directly fails **AC-SPIKE-003** (the upstream validator must pass with no dangling endpoint) and the required-valid-output portion of **FR-SPIKE-008**. FR-SPIKE-008 states that failure of any core condition is sufficient for No-Go.

## Root Cause Classification

### Decisive failure

Graphify extraction and Graphify validation disagree on the graph contract for the evaluated Java inputs: extraction emits edges to symbols for which no node is emitted, while `assert_valid` requires every edge endpoint to exist. This is an upstream provider-output contract failure at the pinned version, not a TP normalization failure.

### Cascading or inconclusive observations

The M1 candidate report listed additional red results. They are retained as evidence, but they are not treated as independent proven defects:

- The expected edge matrix reports 13 missing required edges only because extraction exited before `02_fixture_normalized.json` existed; every source/target candidate count is zero. It does **not** establish that all 13 relationships are independently unsupported.
- Cold/warm stability and project-move portability have `null` hashes because no valid normalized graph was produced. Those checks were blocked, not separately disproved.
- The same-size/same-mtime cache probe has `same_size: false` and `null` before/after hashes. It does not independently prove cache invalidation failure.
- `extract_signature`, package version, and parallel fields are `null` in the post-run API summary because the worker failed before the success-path report was completed; installation and invocation evidence show that the public extraction path was present.

## Cost Evidence (Non-decisive)

The isolated Windows environment installed 31 packages and occupied 167,648,044 bytes. Install time was 27.56–48.49 seconds and import time was approximately 0.77 seconds. Network-attempt count during guarded extraction was zero. These costs reinforce the optional-provider boundary but are not the reason for No-Go.

## Why M2 Does Not Require More Runs

A Linux run, Usage Footprint A/B/C comparison, or further cache/performance measurement cannot make the current pinned provider satisfy AC-SPIKE-003. Under FR-SPIKE-008, continuing those measurements is unnecessary for the M2 decision after a deterministic core gate has failed on both a focused fixture and a representative project.

Reconsidering a later Graphify release, applying an upstream patch, vendoring, forking, filtering dangling edges, or building a replacement AST engine is a new requirement and must receive a new Spike and review. None is authorized in this v5.3.1 task.

## Product and Release Consequences

- Do not add `graphifyy` to `requirements.txt` or `requirements-dev.txt`.
- Do not add a Graphify Provider Adapter, TP Source Graph Contract, `.tp-spec/source-graph/` product path, consumer integration, MCP, Neo4j, Graph UI, or background service.
- Do not claim Graph analysis PASS or Source Graph availability.
- Preserve the existing `rg + framework-aware Usage Footprint` behavior without regression.
- Continue with Requirement Frontier as an internal method of the existing `requirement-clarification` capability; do not create a parallel Skill, workflow stage, Runtime state, Task Event, or database structure.
