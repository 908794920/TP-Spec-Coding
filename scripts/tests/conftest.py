from __future__ import annotations

import os
from pathlib import Path

import pytest

from test_catalog import DOMAIN_MARKERS, PRIMARY_LAYERS, SMOKE_NODEIDS, metadata_for_path

BASE = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_process_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Keep machine-local Base state and CWD changes inside one test."""
    original_cwd = Path.cwd()
    monkeypatch.setenv("TP_SPEC_USER_ROOT", str(tmp_path / "tp-spec-user-root"))
    try:
        yield
    finally:
        os.chdir(original_cwd)


def _relative_test_path(item: pytest.Item) -> str:
    path = Path(str(item.path)).resolve()
    try:
        return path.relative_to(BASE).as_posix()
    except ValueError as exc:
        raise pytest.UsageError(f"test item is outside repository test catalog: {path}") from exc


def _marker_names(item: pytest.Item, allowed: set[str]) -> set[str]:
    return {marker.name for marker in item.iter_markers() if marker.name in allowed}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply catalog defaults and reject unclassified tests.

    Classification is explicit and file-based. Resource scans are audit evidence only;
    they never auto-promote a test into unit/contract/integration.
    """
    for item in items:
        rel = _relative_test_path(item)
        try:
            meta = metadata_for_path(rel)
        except KeyError as exc:
            raise pytest.UsageError(str(exc)) from exc

        layers = _marker_names(item, PRIMARY_LAYERS)
        if not layers:
            item.add_marker(getattr(pytest.mark, meta["layer"]))
            layers = {meta["layer"]}
        if len(layers) != 1:
            raise pytest.UsageError(
                f"test item must have exactly one primary layer: {item.nodeid}; got {sorted(layers)}"
            )

        domains = _marker_names(item, DOMAIN_MARKERS)
        if not domains:
            for domain in meta["domains"]:
                item.add_marker(getattr(pytest.mark, domain))
            domains = set(meta["domains"])
        if not domains:
            raise pytest.UsageError(f"test item must have at least one domain: {item.nodeid}")

        if meta["slow"]:
            item.add_marker(pytest.mark.slow)
        if meta["serial"]:
            item.add_marker(pytest.mark.serial)
        if item.nodeid in SMOKE_NODEIDS:
            item.add_marker(pytest.mark.smoke)
