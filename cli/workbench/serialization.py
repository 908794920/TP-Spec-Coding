"""Preserve the existing presentation sensitive-field policy."""
from pathlib import Path
from typing import Any
import re

_SENSITIVE_KEY = re.compile(r"(?:password|passwd|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|credential|authorization|cookie)", re.I)

def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _strip_sensitive(v) for k, v in value.items() if not _SENSITIVE_KEY.search(str(k))}
    if isinstance(value, list):
        return [_strip_sensitive(v) for v in value]
    if isinstance(value, tuple):
        return [_strip_sensitive(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value
