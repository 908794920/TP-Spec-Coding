# V5.2.0 Namespace Migration

TP-Spec-Coding v5.2.0 completes the namespace cutover. Active surfaces use only:

- command: `tp-spec`
- project state: `.tp-spec/`
- user state: `~/.tp-spec/`
- environment variables: `TP_SPEC_*`
- protocol/schema prefix: `tp-spec.*`

Legacy `ai-work` / `.ai-work` / `AI_WORK_*` names are migration input only. Normal runtime does not silently fall back to them.

## Existing installations

From the TP-Spec-Coding Base checkout, before normal work:

```powershell
python -m cli.main base namespace-migrate --workspace-root "<project-root>"
python -m cli.main base namespace-migrate --workspace-root "<project-root>" --apply
python -m cli.main base configure --base-root "<base-root>" --wiki-root "<wiki-root>" --knowledge-root "<knowledge-root>"
```

If both the legacy and new project/user roots exist, migration fails closed. Reconcile them manually; TP-Spec-Coding will not guess which copy is authoritative.

Historical changelog/evidence may retain the old spelling because it describes past facts. Active Runtime, Task control surfaces, docs and launchers use only the new namespace.
