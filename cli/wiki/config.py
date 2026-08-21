# -*- coding: utf-8 -*-
"""Compatibility import surface for the shared Content Systems resolver.

The resolver moved to :mod:`cli.content_systems` when Knowledge became a
first-class V5.2.5 content system.  Existing Wiki imports remain stable.
"""
from cli.content_systems import (  # noqa: F401
    BASE_ROOT,
    DEFAULT_CONFIG,
    ContentPaths,
    ContentSystemsConfigError,
    ResolvedConfig,
    junction_relation,
    load_content_systems,
    same_path,
)

__all__ = [
    "BASE_ROOT",
    "DEFAULT_CONFIG",
    "ContentPaths",
    "ContentSystemsConfigError",
    "ResolvedConfig",
    "junction_relation",
    "load_content_systems",
    "same_path",
]
