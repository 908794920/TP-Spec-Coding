"""Direct Knowledge contracts, separate from data truth and from each other."""
from __future__ import annotations

import hashlib
import inspect
from importlib.metadata import PackageNotFoundError, version

from .common import base_schema_path, load_project_registry, meta_paths, read_jsonl, stable_hash


def _functions(*functions):
    return {function.__module__ + "." + function.__name__: hashlib.sha256(
        inspect.getsource(function).encode("utf-8")).hexdigest() for function in functions}


def projection_source_subject(cfg):
    from . import common
    return stable_hash({"registered_sources": read_jsonl(meta_paths(cfg)["source_registry"]),
                        "source_path_ids": common.source_path_ids(cfg),
                        "registered_conversion_versions": common.registered_conversion_versions(cfg)})


def projection_contract(cfg):
    from . import common, documents, projection, reading
    registry, _ = load_project_registry(cfg)
    identity_registry = {field: [{key: row[key] for key in
        ("id", "display_name", "source_dir", "aliases", "name", "title", "status") if key in row}
        for row in registry.get(field) or [] if isinstance(row, dict)]
        for field in ("projects", "shared_scopes")}
    body = {
        "schema": "tp-spec.knowledge-projection-contract/v1",
        "implementation": _functions(_functions, projection_contract, projection_source_subject, common.read_note, common.parse_frontmatter, common.normalize_yaml_scalars, common.collect_notes,
            common.canonical_dirs, common.source_dirs, common.effective_project_identity, common.apply_note_identity,
            common.load_project_registry, common.load_source_registry, common.source_registry_records, common.source_path_ids, common.registered_conversion_versions,
            documents.source_identity, documents.document_key, documents._relative, documents.metadata,
            documents.scopes, documents.scope_condition, documents.document_root, documents.document_path, documents._conversion_for_row,
            documents.registered_conversion_path, projection.tokenize, projection.chunk_markdown,
            projection._note_metadata, projection._registered_sources, projection._source_id,
            projection._insert_doc, projection._rebuild_graph, projection.build_projection,
            projection.update_projection, projection.update_canonical_note_projection, reading._text),
        "schema_digest": hashlib.sha256(projection.CORE_SCHEMA.encode("utf-8")).hexdigest(),
        "canonical_layout": cfg.knowledge_canonical,
        "canonical_subdirs": common.CANONICAL_SUBDIRS,
        "source_identity": documents.source_identity(cfg),
        "yaml_version": common.yaml.__version__,
        "graph_mode": str(cfg.knowledge_projection.get("graph_mode") or "optional"),
        "registry": identity_registry,
        "chunk_limits": [projection.MAX_CHUNK_LINES, projection.MIN_CHUNK_LINES],
        "patterns": [projection.CJK_RE.pattern, projection.HEADING_RE.pattern, common.FRONTMATTER_RE.pattern],
    }
    body["contract_id"] = stable_hash(body)
    return body


def quality_contract(cfg):
    from . import common, lint, state
    implementation = [value for key, value in vars(lint).items()
                      if inspect.isfunction(value) and value.__module__ == lint.__name__]
    try:
        schema_library = version("jsonschema")
    except PackageNotFoundError:
        schema_library = "unavailable"
    body = {
        "schema": "tp-spec.knowledge-quality-contract/v1",
        "implementation": _functions(_functions, quality_contract, *implementation, common.parse_frontmatter, common.normalize_yaml_scalars, common.read_note,
            common.collect_notes, common.canonical_dirs, common.source_dirs,
            common.effective_project_identity, common.apply_note_identity, common.load_project_registry, common.load_source_registry, common.source_registry_records, common.source_path_ids,
            common.find_source_ids, common.source_accountability, common.registered_conversion_versions, state.apply_quality_policy,
            state.load_quality_policy, state.code_dependency_snapshot, state._affected_canonical,
            state._verification_binding, state.stage_scan, state.maintain, state.verify,
            state.create_audit_plan, state._audit_assertions, state.record_audit, state.commit_snapshot),
        "rules": {name: hashlib.sha256(base_schema_path(name).read_bytes()).hexdigest() for name in
                  ("canonical-note.schema.json", "project-registry.schema.json",
                   "source-registry-record.schema.json", "relation-types.yaml")},
        "effective_policy": state.load_quality_policy(cfg),
        "semantic_audit_sample_docs": int(cfg.knowledge_quality.get("semantic_audit_sample_docs") or 3),
        "direct_libraries": {"yaml": common.yaml.__version__, "jsonschema": schema_library},
        "constants": {"id_pattern": common.ID_PATTERN.pattern, "kinds": sorted(common.KINDS),
                      "frontmatter_pattern": common.FRONTMATTER_RE.pattern, "wikilink_pattern": common.WIKILINK_RE.pattern,
                      "canonical_subdirs": common.CANONICAL_SUBDIRS,
                      "source_ref": common.SRC_REF_RE.pattern, "task_ref": common.TASK_REF_RE.pattern,
                      "link_prefixes": lint.ALLOWED_LINK_PREFIXES, "generated_segments": sorted(lint.GENERATED_SEGMENTS)},
    }
    body["contract_id"] = stable_hash(body)
    return body
