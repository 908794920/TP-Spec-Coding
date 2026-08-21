# -*- coding: utf-8 -*-
"""Explicit local document-normalization CLI surface."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .document_conversion import convert_local_file


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_convert(args) -> int:
    try:
        result = convert_local_file(Path(args.source), Path(args.output), overwrite=bool(args.overwrite))
        _emit({"schema": "tp-spec.document-convert/v1", "status": "PASS", **result})
        return 0
    except Exception as exc:
        _emit(
            {
                "schema": "tp-spec.document-convert/v1",
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return 1


def add_document_subparsers(root_subparsers) -> None:
    document = root_subparsers.add_parser(
        "document",
        help="Normalize an explicit local document to Markdown with Microsoft MarkItDown",
    )
    sub = document.add_subparsers(dest="document_cmd", required=True)
    convert = sub.add_parser("convert", help="Convert one local file to a Markdown file")
    convert.add_argument("--source", required=True, help="existing local source file")
    convert.add_argument("--output", required=True, help="output .md path")
    convert.add_argument("--overwrite", action="store_true", help="replace an existing output file explicitly")
    convert.set_defaults(func=cmd_convert)
