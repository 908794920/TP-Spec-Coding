# -*- coding: utf-8 -*-
"""TP-Spec-Coding controlled YAML loader (V5.2.2 C-01.4 contract).

Single controlled read path for governed YAML files, built on PyYAML 6.0.3
SafeLoader (human_owner decision T1) with:

  - duplicate-key rejection (custom mapping constructor) -> DUPLICATE_KEY
  - forbidden tags / object construction rejected by SafeLoader -> YAML_SYNTAX
  - resource limits (file size, nesting depth, alias count, mapping keys)
    enforced on the event stream before construction -> RESOURCE_LIMIT
  - schema validation (version gate, required fields, exact types, unknown
    top-level fields) -> VERSION_MISMATCH / TYPE_MISMATCH / UNKNOWN_FIELD
  - version gating is FULL EXACT MATCH against supported_versions
    (ruling 8.6-M2); dotted version fields supported

Strictly read-only: never writes, never auto-repairs, never expands
placeholders such as ${CONTENT_SYSTEM_ROOT} (decision D-05), never compiles
regex pattern fields (decision D-04). Exit-code mapping for the CLI lives in
EXIT_CODES (10-15, contract §6).
"""

from __future__ import annotations

import io
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from cli import config_schemas


class ErrorCode(Enum):
    """Stable error codes; semantics must never change once defined."""

    YAML_SYNTAX = "YAML_SYNTAX"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


# contract §6: contiguous 10-15 so PowerShell can range-check; 1/2/4 stay
# reserved for the existing generic/argparse/config-not-found meanings
EXIT_CODES: Dict[ErrorCode, int] = {
    ErrorCode.YAML_SYNTAX: 10,
    ErrorCode.DUPLICATE_KEY: 11,
    ErrorCode.UNKNOWN_FIELD: 12,
    ErrorCode.TYPE_MISMATCH: 13,
    ErrorCode.VERSION_MISMATCH: 14,
    ErrorCode.RESOURCE_LIMIT: 15,
}

# contract §10 resource-limit defaults
MAX_FILE_SIZE_BYTES = 1_048_576
MAX_NESTING_DEPTH = 20
MAX_ALIASES = 100
MAX_MAPPING_KEYS = 1000
MAX_DOCUMENT_SIZE = 5_242_880


class ConfigLoadError(Exception):
    """Unified load failure carrying a stable error code."""

    def __init__(
        self,
        error_code: ErrorCode,
        file_path: str,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
    ):
        self.error_code = error_code
        self.file_path = file_path
        self.message = message
        self.detail = detail or {}
        super().__init__(f"[{error_code.value}] {file_path}: {message}")

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.error_code]

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "status": "error",
            "error_code": self.error_code.value,
            "exit_code": self.exit_code,
            "file": self.file_path,
            "message": self.message,
            "detail": self.detail,
        }


class _DuplicateKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys."""


def _construct_mapping_no_dup(loader, node, deep=False):
    mapping: Dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"__duplicate_key__:{key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    if len(mapping) > MAX_MAPPING_KEYS:
        raise yaml.constructor.ConstructorError(
            "while constructing a mapping",
            node.start_mark,
            f"__mapping_keys_limit__:{len(mapping)}",
            node.start_mark,
        )
    return mapping


_DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_dup
)

# process-level cache: resolved path -> (mtime_ns, size, data)
_CACHE: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}


def default_base_root() -> Path:
    """Base root defaults to the parent of the cli/ package directory."""
    return Path(__file__).resolve().parent.parent


def _resolve(file_path: "str | Path", base_root: "Optional[str | Path]") -> Path:
    p = Path(file_path)
    if not p.is_absolute():
        root = Path(base_root) if base_root else default_base_root()
        p = root / p
    return p.resolve()


def _scan_events(text: str, file_path: str) -> None:
    """Pre-construction resource-limit scan over the event stream."""
    depth = 0
    aliases = 0
    try:
        for event in yaml.parse(io.StringIO(text), Loader=yaml.SafeLoader):
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > MAX_NESTING_DEPTH:
                    raise ConfigLoadError(
                        ErrorCode.RESOURCE_LIMIT,
                        file_path,
                        f"nesting depth {depth} exceeds max {MAX_NESTING_DEPTH}",
                        {"limit_type": "nesting_depth", "actual": depth, "max": MAX_NESTING_DEPTH},
                    )
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.AliasEvent):
                aliases += 1
                if aliases > MAX_ALIASES:
                    raise ConfigLoadError(
                        ErrorCode.RESOURCE_LIMIT,
                        file_path,
                        f"alias count {aliases} exceeds max {MAX_ALIASES}",
                        {"limit_type": "aliases", "actual": aliases, "max": MAX_ALIASES},
                    )
    except yaml.YAMLError as exc:
        raise _syntax_error(exc, file_path)


def _syntax_error(exc: yaml.YAMLError, file_path: str) -> ConfigLoadError:
    detail: Dict[str, Any] = {}
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        detail = {"line": mark.line + 1, "column": mark.column + 1}
    return ConfigLoadError(
        ErrorCode.YAML_SYNTAX, file_path, f"YAML parse error: {exc}", detail
    )


def _get_dotted(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate_against_schema(
    data: Dict[str, Any],
    schema_name: str,
    *,
    file_path: str = "<memory>",
    strict: bool = True,
) -> None:
    """Validate loaded data. Order per contract §4.2:
    1. version gate  2. required fields  3. exact types  4. unknown fields.
    Version gate is full exact match (major.minor.patch all equal, M2)."""
    schema = config_schemas.get_schema(schema_name)

    version_field = schema.get("version_field")
    if version_field:
        file_version = _get_dotted(data, version_field)
        supported = schema.get("supported_versions", [])
        if file_version is not None and not isinstance(file_version, str):
            # a present-but-wrong-typed version is a type problem, not a
            # version-range problem (contract §4.3 example: version: 5.05)
            raise ConfigLoadError(
                ErrorCode.TYPE_MISMATCH,
                file_path,
                f"{version_field} expected str, got {type(file_version).__name__}",
                {"field": version_field, "expected": "str", "actual": type(file_version).__name__},
            )
        if file_version not in supported:
            raise ConfigLoadError(
                ErrorCode.VERSION_MISMATCH,
                file_path,
                f"{version_field}={file_version!r} not in supported {supported} "
                "(full exact match, major.minor.patch)",
                {"file_version": file_version, "supported": supported},
            )

    props: Dict[str, Any] = schema.get("properties", {})
    for name, spec in props.items():
        present = name in data
        if spec.get("required", False) and not present:
            raise ConfigLoadError(
                ErrorCode.TYPE_MISMATCH,
                file_path,
                f"required field '{name}' missing",
                {"field": name, "expected": spec["type"].__name__, "actual": "missing"},
            )
        if present:
            value = data[name]
            expected = spec["type"]
            # bool is an int subclass; keep the check exact
            if not isinstance(value, expected) or (
                expected is not bool and isinstance(value, bool) and expected is int
            ):
                raise ConfigLoadError(
                    ErrorCode.TYPE_MISMATCH,
                    file_path,
                    f"field '{name}' expected {expected.__name__}, got {type(value).__name__}",
                    {
                        "field": name,
                        "expected": expected.__name__,
                        "actual": type(value).__name__,
                    },
                )
            enum = spec.get("enum")
            if enum is not None and value not in enum:
                raise ConfigLoadError(
                    ErrorCode.TYPE_MISMATCH,
                    file_path,
                    f"field '{name}' value {value!r} not in enum {enum}",
                    {"field": name, "enum": enum, "actual": value},
                )

    if strict:
        unknown = [k for k in data.keys() if k not in props]
        if unknown:
            raise ConfigLoadError(
                ErrorCode.UNKNOWN_FIELD,
                file_path,
                f"unknown top-level field(s): {', '.join(sorted(unknown))}",
                {"fields": sorted(unknown), "path": "$"},
            )


def load_config(
    file_path: "str | Path",
    *,
    schema_name: Optional[str] = None,
    base_root: "Optional[str | Path]" = None,
    strict_unknown_fields: bool = True,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Load one governed YAML file and return its semantic data (read-only)."""
    path = _resolve(file_path, base_root)
    display = str(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")

    stat = path.stat()
    if stat.st_size > MAX_FILE_SIZE_BYTES:
        raise ConfigLoadError(
            ErrorCode.RESOURCE_LIMIT,
            display,
            f"file size {stat.st_size} exceeds max {MAX_FILE_SIZE_BYTES}",
            {"limit_type": "file_size", "actual": stat.st_size, "max": MAX_FILE_SIZE_BYTES},
        )

    cache_key = str(path)
    data: Optional[Dict[str, Any]] = None
    if use_cache and cache_key in _CACHE:
        mtime_ns, size, cached = _CACHE[cache_key]
        if mtime_ns == stat.st_mtime_ns and size == stat.st_size:
            data = cached
    if data is None:
        text = path.read_text(encoding="utf-8")
        _scan_events(text, display)
        try:
            data = yaml.load(text, Loader=_DuplicateKeySafeLoader)
        except yaml.constructor.ConstructorError as exc:
            problem = exc.problem or ""
            if problem.startswith("__duplicate_key__:"):
                key = problem.split(":", 1)[1]
                mark = exc.problem_mark
                raise ConfigLoadError(
                    ErrorCode.DUPLICATE_KEY,
                    display,
                    f"duplicate key '{key}' in mapping",
                    {
                        "key": key,
                        "line": (mark.line + 1) if mark else None,
                    },
                )
            if problem.startswith("__mapping_keys_limit__:"):
                actual = int(problem.split(":", 1)[1])
                raise ConfigLoadError(
                    ErrorCode.RESOURCE_LIMIT,
                    display,
                    f"mapping key count {actual} exceeds max {MAX_MAPPING_KEYS}",
                    {"limit_type": "mapping_keys", "actual": actual, "max": MAX_MAPPING_KEYS},
                )
            # forbidden tags / object construction end up here
            raise _syntax_error(exc, display)
        except yaml.YAMLError as exc:
            raise _syntax_error(exc, display)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigLoadError(
                ErrorCode.TYPE_MISMATCH,
                display,
                f"top-level document must be a mapping, got {type(data).__name__}",
                {"field": "$", "expected": "dict", "actual": type(data).__name__},
            )
        if use_cache:
            _CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, data)

    if schema_name is not None:
        validate_against_schema(
            data, schema_name, file_path=display, strict=strict_unknown_fields
        )
    return data


def load_all_governance(
    base_root: "Optional[str | Path]" = None,
) -> Dict[str, Dict[str, Any]]:
    """Load every governance file; fail-closed on the first error."""
    total = 0
    result: Dict[str, Dict[str, Any]] = {}
    root = Path(base_root) if base_root else default_base_root()
    for schema_name, rel in config_schemas.GOVERNANCE_FILES.items():
        p = _resolve(rel, root)
        if p.is_file():
            total += p.stat().st_size
            if total > MAX_DOCUMENT_SIZE:
                raise ConfigLoadError(
                    ErrorCode.RESOURCE_LIMIT,
                    rel,
                    f"cumulative governance size {total} exceeds max {MAX_DOCUMENT_SIZE}",
                    {"limit_type": "document_size", "actual": total, "max": MAX_DOCUMENT_SIZE},
                )
        result[schema_name] = load_config(rel, schema_name=schema_name, base_root=root)
    return result


def get_state_owner(
    state: str, base_root: "Optional[str | Path]" = None
) -> Optional[str]:
    """state -> owner from role-catalog state_owner_map (replaces $StateOwners
    / $expectedOwnerByState mirror tables)."""
    catalog = load_config(
        config_schemas.GOVERNANCE_FILES["role-catalog"],
        schema_name="role-catalog",
        base_root=base_root,
    )
    owner = catalog["state_owner_map"].get(state)
    if isinstance(owner, str):
        return owner
    # Frozen compatibility map is internal; active workflow/role-catalog stay small.
    from .legacy_workflow import LEGACY_STATE_OWNERS
    legacy_owner = LEGACY_STATE_OWNERS.get(state)
    return legacy_owner if isinstance(legacy_owner, str) else None


def get_workflow_transitions(
    base_root: "Optional[str | Path]" = None,
) -> Dict[str, List[str]]:
    """state -> next-state list from workflow.yaml (replaces
    $ShdWorkflowTransitions mirror table)."""
    wf = load_config(
        config_schemas.GOVERNANCE_FILES["workflow"],
        schema_name="workflow",
        base_root=base_root,
    )
    out: Dict[str, List[str]] = {}
    for state, spec in wf["transitions"].items():
        nxt = spec.get("next", []) if isinstance(spec, dict) else []
        out[state] = list(nxt) if isinstance(nxt, list) else []
    return out


def read_base_version(base_root: "Optional[str | Path]" = None) -> str:
    """Read the base contract version from the VERSION file."""
    root = Path(base_root) if base_root else default_base_root()
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def gate_task_contract(
    task_version: str,
    *,
    base_root: "Optional[str | Path]" = None,
) -> None:
    """Outer-layer gate (ruling 8.6-M2): the task artifact_contract.version must
    equal the base VERSION with FULL EXACT MATCH (major.minor.patch all equal).
    Any differing component, patch included, raises VERSION_MISMATCH; there is
    no lenient/minor-tolerant mode. compat-matrix.yaml is loaded through the
    controlled path to confirm the base contract is a declared contract."""
    base_version = read_base_version(base_root)
    matrix = load_config(
        config_schemas.SCHEMAS["compat-matrix"]["file"],
        schema_name="compat-matrix",
        base_root=base_root,
    )
    contracts = matrix.get("contracts", {})
    if base_version not in contracts:
        raise ConfigLoadError(
            ErrorCode.VERSION_MISMATCH,
            config_schemas.SCHEMAS["compat-matrix"]["file"],
            f"base VERSION {base_version!r} is not a declared contract in compat-matrix",
            {"base_version": base_version, "known": sorted(contracts.keys())},
        )
    if task_version != base_version:
        raise ConfigLoadError(
            ErrorCode.VERSION_MISMATCH,
            "<task>",
            f"task contract {task_version} incompatible with base {base_version} "
            "(full exact match, major.minor.patch)",
            {"task_version": task_version, "base_version": base_version},
        )
