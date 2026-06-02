from __future__ import annotations

import json
from pathlib import Path

import pytest

from secret_pond.paths import ProjectPaths
from secret_pond.services.participants import ParticipantCounter


def test_participant_counter_reads_missing_file_as_zero(tmp_path: Path) -> None:
    counter = ParticipantCounter(ProjectPaths(tmp_path))

    assert counter.get_count() == 0


def test_participant_counter_increment_persists_and_returns_new_count(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    counter = ParticipantCounter(paths)

    assert counter.increment() == 1
    assert counter.increment() == 2

    assert ParticipantCounter(paths).get_count() == 2
    assert json.loads(paths.participant_count_file.read_text(encoding="utf-8")) == {"count": 2}


def test_participant_counter_reset_persists_zero(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    counter = ParticipantCounter(paths)
    counter.increment()

    assert counter.reset() == 0
    assert ParticipantCounter(paths).get_count() == 0


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "{}",
        '{"count": -1}',
        '{"count": true}',
        '{"count": 1.5}',
    ],
)
def test_participant_counter_rejects_invalid_files(tmp_path: Path, payload: str) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    paths.participant_count_file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="participant"):
        ParticipantCounter(paths).get_count()

    with pytest.raises(ValueError, match="participant"):
        ParticipantCounter(paths).increment()

    with pytest.raises(ValueError, match="participant"):
        ParticipantCounter(paths).reset()


def test_participant_counter_atomic_write_cleans_temp_file(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    ParticipantCounter(paths).increment()

    assert list(paths.logs_dir.glob("*.tmp")) == []
