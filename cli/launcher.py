# -*- coding: utf-8 -*-
"""Install and validate the stable machine-local tp-spec launcher."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict

from cli.path_identity import canonical_path, same_path


def launcher_bin_root(state_root: "str | Path") -> Path:
    return canonical_path(state_root) / "bin"


def _path_entries(value: str) -> list[str]:
    return [p for p in (value or "").split(os.pathsep) if p]


def _path_contains(value: str, target: Path) -> bool:
    for raw in _path_entries(value):
        try:
            if same_path(raw, target):
                return True
        except Exception:
            continue
    return False


def _persist_windows_user_path(bin_root: Path) -> Dict[str, Any]:
    if os.name != "nt":
        return {"supported": False, "changed": False, "reason": "non-Windows: persistent shell PATH is user-shell specific"}
    import winreg
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment")
    try:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, value_type = "", winreg.REG_EXPAND_SZ
        current = str(current or "")
        if _path_contains(current, bin_root):
            changed = False
        else:
            sep = ";" if current and not current.endswith(";") else ""
            updated = current + sep + str(bin_root)
            winreg.SetValueEx(key, "Path", 0, value_type, updated)
            changed = True
    finally:
        winreg.CloseKey(key)
    if not _path_contains(os.environ.get("PATH", ""), bin_root):
        os.environ["PATH"] = os.environ.get("PATH", "") + (os.pathsep if os.environ.get("PATH") else "") + str(bin_root)
    if changed:
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF; WM_SETTINGCHANGE = 0x001A; SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None)
        except Exception:
            pass
    return {"supported": True, "changed": changed}


def precheck_launchers(*, base_root: "str | Path", state_root: "str | Path") -> Dict[str, Any]:
    """Report launcher conflicts that are visible before anything is written.

    Only states the installer could not have produced itself: the bin path occupied by a
    non-directory, a launcher target that is not a regular file, or a Base launcher source
    that is missing. Every issue names the exact path. Callers write the installation config
    only when this passes; a failure here leaves configuration and launchers untouched.
    """
    base = canonical_path(base_root); bin_root = launcher_bin_root(canonical_path(state_root))
    names = ("tp-spec.ps1", "tp-spec.cmd", "tp-spec")
    issues: list[str] = []
    conflicts: list[str] = []
    if (bin_root.exists() or bin_root.is_symlink()) and not bin_root.is_dir():
        issues.append(f"launcher bin path is not a directory: {bin_root}")
        conflicts.append(str(bin_root))
    for name in names:
        target = bin_root / name
        if (target.exists() or target.is_symlink()) and not target.is_file():
            issues.append(f"launcher target is not a regular file: {target}")
            conflicts.append(str(target))
    missing = [str(base / "scripts" / name) for name in names if not (base / "scripts" / name).is_file()]
    if missing:
        issues.append("launcher source missing: " + ", ".join(missing))
        conflicts.extend(missing)
    return {"status": "PASS" if not issues else "FAIL", "bin_root": str(bin_root),
            "conflicts": conflicts, "issues": issues}


def install_launchers(*, base_root: "str | Path", state_root: "str | Path", persist_path: bool) -> Dict[str, Any]:
    base = canonical_path(base_root); state = canonical_path(state_root); bin_root = launcher_bin_root(state)
    precheck = precheck_launchers(base_root=base, state_root=state)
    if precheck["status"] != "PASS":
        return {"status": "FAIL", "bin_root": str(bin_root), "conflicts": precheck["conflicts"],
                "issues": precheck["issues"]}
    bin_root.mkdir(parents=True, exist_ok=True)
    sources = {
        "tp-spec.ps1": base / "scripts" / "tp-spec.ps1",
        "tp-spec.cmd": base / "scripts" / "tp-spec.cmd",
        "tp-spec": base / "scripts" / "tp-spec",
    }
    changed = []
    for name, source in sources.items():
        target = bin_root / name
        data = source.read_bytes()
        if not target.is_file() or target.read_bytes() != data:
            # A write that fails part way stays a real I/O failure: report the path and the
            # targets already replaced, and let the caller retry the same command.
            try:
                target.write_bytes(data)
            except OSError as exc:
                return {"status": "FAIL", "bin_root": str(bin_root), "changed": changed,
                        "conflicts": [str(target)], "issues": [f"launcher write failed: {target}: {exc}"]}
            changed.append(str(target))
        if name == "tp-spec":
            try: target.chmod(target.stat().st_mode | 0o111)
            except OSError: pass
    path_result = _persist_windows_user_path(bin_root) if persist_path else {"supported": True, "changed": False, "skipped": True}
    return {"status": "PASS", "bin_root": str(bin_root), "changed": changed, "path": path_result}


def _persistent_path_contains(bin_root: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        finally:
            winreg.CloseKey(key)
        return _path_contains(str(current or ""), bin_root)
    except (OSError, FileNotFoundError):
        return False


def launcher_health(*, base_root: "str | Path | None", state_root: "str | Path", require_path: bool) -> Dict[str, Any]:
    bin_root = launcher_bin_root(state_root)
    required = [bin_root / "tp-spec.ps1", bin_root / "tp-spec.cmd", bin_root / "tp-spec"]
    missing = [str(p) for p in required if not p.is_file()]
    path_visible = _path_contains(os.environ.get("PATH", ""), bin_root) or _persistent_path_contains(bin_root)
    issues = []
    if missing: issues.append("launcher files missing")
    if require_path and not path_visible: issues.append("tp-spec launcher bin is not visible on PATH")
    if base_root is None: issues.append("Base root unresolved for launcher")
    return {"status": "PASS" if not issues else "FAIL", "bin_root": str(bin_root),
            "files": [str(p) for p in required], "missing": missing,
            "path_visible": path_visible, "issues": issues}
