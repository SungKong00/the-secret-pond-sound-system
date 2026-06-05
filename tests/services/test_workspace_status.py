from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from secret_pond.services.workspace_status import capture_workspace_status


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test User", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_capture_workspace_status_persists_clean_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    output_path = repo / ".evidence" / "pre_edit_git_status.json"

    evidence = capture_workspace_status(repo, output_path)

    assert evidence.is_dirty is False
    assert evidence.branch == "main"
    assert evidence.status_lines == ["## main"]
    assert evidence.stash_entries == []
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["is_dirty"] is False
    assert payload["status_lines"] == ["## main"]
    assert payload["stash_entries"] == []


def test_capture_workspace_status_persists_dirty_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
    output_path = repo / ".evidence" / "pre_edit_git_status.json"

    evidence = capture_workspace_status(repo, output_path)

    assert evidence.is_dirty is True
    assert evidence.branch == "main"
    assert evidence.status_lines == ["## main", " M tracked.txt", "?? untracked.txt"]
    assert evidence.stash_entries == []
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["is_dirty"] is True
    assert payload["status_lines"] == ["## main", " M tracked.txt", "?? untracked.txt"]
    assert payload["stash_entries"] == []


def test_capture_workspace_status_reports_existing_stash_entries(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "tracked.txt").write_text("stashed\n", encoding="utf-8")
    git(repo, "stash", "push", "-m", "pre-edit preservation")
    output_path = repo / ".evidence" / "pre_edit_git_status.json"

    evidence = capture_workspace_status(repo, output_path)

    assert evidence.is_dirty is False
    assert evidence.branch == "main"
    assert evidence.status_lines == ["## main"]
    assert evidence.stash_entries == ["stash@{0}: On main: pre-edit preservation"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["stash_entries"] == ["stash@{0}: On main: pre-edit preservation"]


def test_capture_workspace_status_skips_redundant_merge_attempt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path
    output_path = repo / ".evidence" / "pre_edit_git_status.json"
    git_commands: list[tuple[str, ...]] = []

    def fake_run(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        git_commands.append(tuple(command))
        assert command[:1] == ["git"]
        git_args = tuple(command[1:])
        stdout_by_args = {
            ("status", "--short", "--branch"): "## main\n",
            ("stash", "list"): "stash@{0}: On main: pre-edit preservation\n",
            ("branch", "--show-current"): "main\n",
        }
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=0,
            stdout=stdout_by_args[git_args],
            stderr="",
        )

    monkeypatch.setattr("secret_pond.services.workspace_status.subprocess.run", fake_run)

    evidence = capture_workspace_status(repo, output_path)

    assert evidence.redundant_merge_attempted is False
    assert all(command[1:2] != ("merge",) for command in git_commands)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["redundant_merge_attempted"] is False
