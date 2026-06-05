from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceStatusEvidence:
    branch: str
    status_lines: list[str]
    stash_entries: list[str]
    is_dirty: bool
    redundant_merge_attempted: bool
    captured_at: str


def capture_workspace_status(root: Path, output_path: Path) -> WorkspaceStatusEvidence:
    """Persist the pre-edit git worktree status for brownfield safety accounting."""

    status_lines = _git(root, "status", "--short", "--branch").splitlines()
    stash_entries = _git(root, "stash", "list").splitlines()
    branch = _git(root, "branch", "--show-current")
    evidence = WorkspaceStatusEvidence(
        branch=branch,
        status_lines=status_lines,
        stash_entries=stash_entries,
        is_dirty=any(not line.startswith("## ") for line in status_lines),
        redundant_merge_attempted=False,
        captured_at=datetime.now(UTC).isoformat(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(evidence), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()
