# Knowledge Vault Agent Boundary

This directory is the physical storage for the TP-Spec-Coding Knowledge Content System. It stores long-lived Knowledge data and rebuildable machine state; it is **not** the Knowledge Runtime source repository.

## Authority

- Canonical Knowledge + registered evidence/source records are Knowledge truth.
- The configured projection DB is a rebuildable retrieval projection, not truth.
- Active runtime/rules come from the resolved TP-Spec-Coding: `agents/tp-knowledge`, `cli/knowledge`, `knowledge/rules`, `knowledge/schema`, `automation/knowledge`.
- Project paths/configuration come from Content Systems and `00-system/project-registry.yaml`.

## Allowed

- Read registered source/evidence and canonical Knowledge.
- Maintain canonical/source/meta through the current `tp-knowledge` protocol.
- Rebuild/query FTS5 projection through `ai-work knowledge ...`.

## Forbidden

- Do not keep a second active `tools/kb-*` runtime, rule schema or scheduler protocol in this Vault.
- Do not treat legacy migration/quality reports as current product authority.
- Do not re-enable vector retrieval because compatible DB tables exist.
- Do not modify project source code from Knowledge maintenance.
- Do not infer project IDs, destructive merges or evidence truth from folder names.

Junction/symlink mounts are optional compatibility/browsing entries. The Content Systems Resolver is authoritative for physical paths.
