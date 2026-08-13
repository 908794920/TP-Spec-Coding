# Knowledge Configuration Contract

## 1. Two-level root model

Knowledge has two different path concepts and they must not be conflated:

```text
Knowledge System Root
→ whole central Vault

Knowledge Project Root
→ current project's canonical/source subset
```

System Root is resolved from, in precedence order:

1. project Content Systems override;
2. user Installation `systems.knowledge.root`;
3. Base default `systems.knowledge.root`;
4. zero-config fallback `<workspace>/.tp-spec/knowledge`.

Default user Installation path:

```text
~/.tp-spec/installation.yaml
```

Project identity comes from `<workspace>/.tp-spec/config/project-binding.yaml` and/or exact `project-registry.yaml.workspace_roots` mapping. During one-time convergence only, an existing `.tp-spec/knowledge` Junction/symlink may seed the binding **only when its resolved target exactly equals one registered `10-projects/<id>` directory**. Runtime must not guess project ID from folder names when a registry exists; once the binding is written, the legacy-link fallback is no longer needed.

Registry, projection DB and meta stay relative to the **System Root**:

- registry: `00-system/project-registry.yaml` unless configured otherwise;
- projection DB: `.ai-kb/knowledge.db` by default, with legacy candidates declared only in Base configuration;
- machine meta: `.ai-kb/meta`;
- Golden evaluation: configured `evaluation.golden_set/output_root`.

A `.tp-spec/knowledge` Junction is compatibility-only and may be removed after Resolver equivalence is verified.

## 2. Project-scoped retrieval

A global SQLite projection may contain all projects without forcing global search.

Default product retrieval:

```yaml
retrieval:
  strategy: canonical-first-fts5
  default_scope: project
  include_shared: true
  global_fallback: false
  source_fallback: true
```

This resolves to:

```text
current project canonical
→ registered shared scopes
→ current project/shared source fallback
```

Other projects are excluded unless the caller explicitly requests `--scope global` or a specific `--project`.

## 3. Configuration, not code, owns local facts

The following must not be hard-coded in Base:

- user Base/Wiki/Knowledge absolute roots;
- workspace/task evidence roots;
- project IDs, aliases and workspace mappings;
- external source roots;
- user dictionaries;
- Golden query set;
- project-specific conversion adapters.

## 4. Retrieval authority

Current supported default:

```yaml
projection:
  engine: sqlite-fts5
  graph_mode: optional
  vector_mode: retired-compatible
retrieval:
  strategy: canonical-first-fts5
```

`chunk_embeddings` or vector-related tables may remain for compatibility. Their existence does **not** mean vector retrieval is active. Existence != authority.

## 5. Project registry

`project-registry.yaml` is user/data-owned. IDs are stable. `workspace_roots` provides exact workspace → Knowledge project mapping. Aliases/entries may be added, but an established ID must not be silently renamed or reused. Base supplies the schema; the Vault supplies the actual projects.
