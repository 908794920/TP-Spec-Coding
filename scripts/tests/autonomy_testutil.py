from __future__ import annotations

import contextlib
import io
import subprocess
from pathlib import Path

from scripts.tests.cli_testutil import invoke_main


def run(argv, *, refresh_card: bool = False):
    """Run the Base CLI with the SystemExit semantics used by autonomy tests."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = invoke_main(argv, refresh_card=refresh_card)
        except SystemExit as exc:
            rc = int(exc.code or 0)
    return rc, out.getvalue(), err.getvalue()


def git_repo(path: Path):
    """Create the canonical one-commit Git fixture shared by autonomy tests."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "x@y.z"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "x"], check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
