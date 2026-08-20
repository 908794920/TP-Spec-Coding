# -*- coding: utf-8 -*-
"""Narrow local-file to Markdown normalization backed by Microsoft MarkItDown."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Dict, Tuple, Type
import hashlib
import os
import tempfile

MARKITDOWN_REQUIREMENT = "markitdown[pdf,docx,xlsx,xls,pptx]==0.1.7"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_markitdown() -> Tuple[Type[Any], str]:
    """Load MarkItDown lazily so unrelated TP commands do not require the extra at import time."""
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise RuntimeError(
            f"Microsoft MarkItDown is not installed; install runtime requirement: {MARKITDOWN_REQUIREMENT}"
        ) from exc
    try:
        installed = package_version("markitdown")
    except PackageNotFoundError:
        installed = "unknown"
    return MarkItDown, installed


def markitdown_runtime() -> Dict[str, str]:
    """Return the concrete converter runtime used by the local normalization boundary."""
    _converter, installed = _load_markitdown()
    return {"name": "microsoft/markitdown", "version": installed, "api": "convert_local"}


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise


def convert_local_file(source: Path | str, output: Path | str, *, overwrite: bool = False) -> Dict[str, Any]:
    """Convert one existing local file to Markdown through MarkItDown's local-only API.

    This boundary intentionally does not accept or resolve HTTP/HTTPS URIs.  Callers must
    provide a real local file, which keeps document normalization separate from retrieval.
    """
    source_path = Path(source).expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise ValueError(f"source is not a file: {source_path}")

    output_path = Path(output).expanduser()
    if output_path.suffix.lower() != ".md":
        raise ValueError(f"output must use .md extension: {output_path}")
    output_resolved = output_path.resolve(strict=False)
    if output_resolved == source_path:
        raise ValueError("output path must differ from source path")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output_path}")

    MarkItDown, installed = _load_markitdown()
    converter = MarkItDown(enable_plugins=False)
    result = converter.convert_local(source_path)
    markdown = getattr(result, "markdown", None)
    if markdown is None:
        markdown = getattr(result, "text_content", None)
    if not isinstance(markdown, str):
        raise TypeError("MarkItDown conversion result did not contain Markdown text")

    source_sha256 = _sha256(source_path)
    _atomic_write_text(output_path, markdown)
    output_sha256 = _sha256(output_path)
    return {
        "source": str(source_path),
        "output": str(output_path.resolve(strict=False)),
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
        "converter": {"name": "microsoft/markitdown", "version": installed, "api": "convert_local"},
    }
