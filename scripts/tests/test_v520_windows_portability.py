# -*- coding: utf-8 -*-
"""V5.2.1 Windows portability and execution-boundary regression tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _make_runtime_db(db_path: Path, project_id: str, root_path: Path) -> None:
    from cli import db as dbmod

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(str(db_path))
    try:
        dbmod.init_schema(conn)
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                "INSERT OR REPLACE INTO project "
                "(project_id, project_name, root_path, base_version, schema_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, project_id, str(root_path), "5.2.1", dbmod.EXPECTED_SCHEMA_VERSION, now, now),
            )
    finally:
        conn.close()


def test_shared_path_identity_collapses_filesystem_alias(tmp_path: Path):
    """A symlink/junction-like alias and its physical target are one identity."""
    from cli.path_identity import canonical_path, path_identity_key, same_path

    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not allow directory symlinks")

    assert canonical_path(alias) == canonical_path(real)
    assert path_identity_key(alias) == path_identity_key(real)
    assert same_path(alias, real)


def test_project_bootstrap_accepts_equivalent_alias_root(tmp_path: Path):
    """An existing Runtime root alias must not produce a false REBIND_REQUIRED."""
    from cli import project_cmd

    real = tmp_path / "workspace"
    real.mkdir()
    alias = tmp_path / "workspace-alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not allow directory symlinks")

    project_id = "demo"
    db_path = real / ".tp-spec" / "db" / "demo.db"
    _make_runtime_db(db_path, project_id, alias)
    registry = tmp_path / "registry.local.json"
    registry.write_text(
        json.dumps({
            "projects": [{
                "project_id": project_id,
                "project_name": project_id,
                "db_path": str(db_path),
                "root_path": str(alias),
                "base_version": "5.2.1",
                "schema_version": 1,
            }]
        }),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        id=project_id,
        root=str(real),
        db=str(db_path),
        registry=str(registry),
        base_version="5.2.1",
        check_only=False,
    )
    assert project_cmd.cmd_project_bootstrap(args) == 0


def test_legacy_registry_migration_treats_alias_roots_as_same_identity(tmp_path: Path):
    """Two live aliases of one workspace must not be reported as duplicate projects."""
    from cli import db as dbmod

    real = tmp_path / "workspace"
    real.mkdir()
    alias = tmp_path / "workspace-alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not allow directory symlinks")

    db_path = real / "demo.db"
    db_path.touch()
    legacy = tmp_path / "legacy.json"
    current = tmp_path / "current.json"
    _write(
        legacy,
        json.dumps({"projects": [{
            "project_id": "demo", "project_name": "demo",
            "root_path": str(alias), "db_path": str(db_path),
            "base_version": "5.2.1", "schema_version": 1,
        }]}),
    )
    _write(
        current,
        json.dumps({"projects": [{
            "project_id": "demo", "project_name": "demo",
            "root_path": str(real), "db_path": str(db_path),
            "base_version": "5.2.1", "schema_version": 1,
        }]}),
    )

    result = dbmod.migrate_legacy_registry_to_user(
        apply=False,
        legacy_path=str(legacy),
        target_path=str(current),
    )
    assert result["status"] == "MIGRATION_AVAILABLE", result
    assert result["conflicts"] == []


def test_version_scanner_survives_cp1252_parent_stdio():
    """Standalone release scripts must establish their own UTF-8 output boundary."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    env.pop("PYTHONUTF8", None)
    proc = subprocess.run(
        [sys.executable, str(BASE / "scripts" / "check_version_consistency.py")],
        cwd=str(BASE),
        env=env,
        capture_output=True,
        text=False,
    )
    assert proc.returncode == 0, (proc.stdout + b"\n" + proc.stderr).decode("utf-8", errors="replace")
    assert "全仓版本纯净" in proc.stdout.decode("utf-8")


def test_windows_ci_declares_utf8_execution_boundary():
    workflow = (BASE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "PYTHONUTF8" in workflow
    assert "PYTHONIOENCODING" in workflow


def test_windows_byte_gate_validates_repo_policy_not_global_autocrlf_setting():
    gate = (BASE / "scripts" / "ci" / "Test-TpSpecBase.ps1").read_text(encoding="utf-8-sig")
    assert "* -text" in gate
    assert "expected 'false'" not in gate
    assert "core.autocrlf" in gate  # diagnostics remain visible


@pytest.mark.skipif(os.name != "nt", reason="Windows-only 8.3 alias regression")
def test_windows_8dot3_alias_matches_long_path_identity(tmp_path: Path):
    """Real Windows short-name aliases must compare equal to their long names."""
    import ctypes
    from ctypes import wintypes

    from cli.path_identity import same_path

    target = tmp_path / "directory-with-a-long-name"
    target.mkdir()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short = kernel32.GetShortPathNameW
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD

    size = get_short(str(target), None, 0)
    if not size:
        pytest.skip("8.3 short names are disabled on this Windows volume")
    buf = ctypes.create_unicode_buffer(size + 1)
    written = get_short(str(target), buf, len(buf))
    if not written:
        pytest.skip("Windows did not return an 8.3 short alias")
    short = Path(buf.value)
    if os.path.normcase(str(short)) == os.path.normcase(str(target)):
        pytest.skip("target has no distinct short alias")
    assert same_path(short, target)
