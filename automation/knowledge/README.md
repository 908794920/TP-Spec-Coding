# Knowledge Automation

Knowledge scheduled maintenance is executed by a **conversational model session**. The external scheduler stores only the short bootstrap in `SCHEDULER_BOOTSTRAP.md`; the model must read the current Base protocol on every run.

Setup guidance: `SCHEDULER_SETUP.md`.

Canonical protocols:

- `daily-maintenance.md` — unattended incremental health/maintenance
- `ingest-batch.md` — explicit external-document batch ingestion
- `quality-audit.md` — L4 semantic audit contract
- `legacy-normalization.md` — one-time/explicit legacy schema normalization and targeted review protocol

Do not duplicate these protocols into a scheduler configuration. Ambiguity and destructive actions are fail-closed.

Daily retrieval and targeted content decisions default to the resolved current project + shared scopes. Whole-Vault/global retrieval is explicit only. Deterministic maintenance state is Vault-wide: group workspaces by resolved physical Knowledge System Root and execute one serial scan/index/verify/audit/baseline chain per consistent, authorized Vault. Report content outcomes per project; do not present shared state as independent project baselines. See `daily-maintenance.md` for configuration conflicts and unresolved-project handling.
