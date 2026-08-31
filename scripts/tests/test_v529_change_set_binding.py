from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from cli.change_set import ChangeSetError, capture_change_set, current_content_digest, same_product_content


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return cp.stdout.strip()


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "app.txt").write_text("v1\n", encoding="utf-8")
    git(repo, "add", "app.txt")
    git(repo, "commit", "-qm", "init")
    return repo


def test_product_content_change_changes_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = current_content_digest([repo])
    (repo / "app.txt").write_text("v2\n", encoding="utf-8")
    after = current_content_digest([repo])
    assert before != after


def test_task_runtime_file_does_not_change_product_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = current_content_digest([repo])
    (repo / ".tp-spec" / "tasks" / "T1").mkdir(parents=True)
    (repo / ".tp-spec" / "tasks" / "T1" / "status.yaml").write_text("x: 1\n", encoding="utf-8")
    (repo / ".execution").mkdir()
    (repo / ".execution" / "scratch.txt").write_text("temp\n", encoding="utf-8")
    assert current_content_digest([repo]) == before


def test_project_card_artifact_does_not_change_product_change_set(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = capture_change_set([repo])

    artifact = repo / ".tp-spec" / "card" / "index.html"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("first render\n", encoding="utf-8")
    after_create = capture_change_set([repo])

    artifact.write_text("second render\n", encoding="utf-8")
    after_update = capture_change_set([repo])

    assert after_create["content_digest"] == before["content_digest"]
    assert after_update["content_digest"] == before["content_digest"]
    for snapshot in (after_create, after_update):
        assert all(
            not str(entry["path"]).replace("\\", "/").startswith(".tp-spec/card/")
            for repository in snapshot["repositories"]
            for entry in repository["entries"]
        )


def test_committed_runtime_file_does_not_change_product_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = current_content_digest([repo])
    (repo / ".tp-spec").mkdir()
    (repo / ".tp-spec" / "runtime.txt").write_text("runtime\n", encoding="utf-8")
    git(repo, "add", "-f", ".tp-spec/runtime.txt")
    git(repo, "commit", "-qm", "runtime only")
    assert current_content_digest([repo]) == before


def test_history_only_commit_keeps_content_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = capture_change_set([repo])
    git(repo, "commit", "--allow-empty", "-qm", "history only")
    after = capture_change_set([repo])
    assert before["content_digest"] == after["content_digest"]
    assert before["snapshot_digest"] != after["snapshot_digest"]


def test_untracked_product_file_changes_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = current_content_digest([repo])
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    assert current_content_digest([repo]) != before


def test_deleted_or_renamed_tracked_file_changes_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    before = current_content_digest([repo])
    (repo / "app.txt").rename(repo / "renamed.txt")
    assert current_content_digest([repo]) != before


def test_multiple_repo_roots_are_deduplicated_and_stably_ordered(tmp_path: Path):
    repo_a = make_repo(tmp_path, "a")
    repo_b = make_repo(tmp_path, "b")
    nested = repo_a / "nested"
    nested.mkdir()
    first = capture_change_set([repo_b, nested, repo_a])
    second = capture_change_set([repo_a, repo_b, nested])
    assert first["content_digest"] == second["content_digest"]
    assert [row["root_locator"] for row in first["repositories"]] == sorted(
        {str(repo_a.resolve()), str(repo_b.resolve())}
    )


def test_symlink_is_hashed_without_following_target(tmp_path: Path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unsupported")
    repo = make_repo(tmp_path)
    target = tmp_path / "outside.txt"
    target.write_text("one\n", encoding="utf-8")
    try:
        os.symlink(target, repo / "link.txt")
    except OSError:
        pytest.skip("symlink creation not permitted")
    before = current_content_digest([repo])
    target.write_text("two\n", encoding="utf-8")
    assert current_content_digest([repo]) == before


def test_git_failure_is_fail_closed(tmp_path: Path):
    not_repo = tmp_path / "not-repo"
    not_repo.mkdir()
    with pytest.raises(ChangeSetError):
        capture_change_set([not_repo])


def test_same_product_content_compares_content_digest(tmp_path: Path):
    repo = make_repo(tmp_path)
    current = capture_change_set([repo])
    assert same_product_content(current["content_digest"], current)
    assert not same_product_content("sha256:deadbeef", current)
