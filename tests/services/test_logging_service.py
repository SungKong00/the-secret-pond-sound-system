from __future__ import annotations

import json
from pathlib import Path

import pytest

from secret_pond.paths import ProjectPaths
from secret_pond.services.logging_service import EventLogger


def test_event_logger_appends_event_and_returns_written_payload(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    logger = EventLogger(paths)

    event = logger.log_event(
        "recording.start",
        {"armed": True},
        timestamp="2026-06-03T12:00:00+00:00",
    )

    assert event == {
        "timestamp": "2026-06-03T12:00:00+00:00",
        "event_type": "recording.start",
        "payload": {"armed": True},
    }
    assert json.loads(paths.event_log_file.read_text(encoding="utf-8")) == event


def test_event_logger_appends_multiple_events_in_order(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    logger = EventLogger(paths)

    first = logger.log_event("recording.start", timestamp="t1")
    second = logger.log_event("recording.stop", {"duration": 4.2}, timestamp="t2")

    assert logger.read_events() == [first, second]
    assert logger.read_events(limit=1) == [first]


def test_event_logger_copies_payload_by_json_round_trip(tmp_path: Path) -> None:
    logger = EventLogger(ProjectPaths(tmp_path))
    payload = {"nested": {"value": 1}}

    event = logger.log_event("recording.accepted", payload, timestamp="t1")
    payload["nested"]["value"] = 2

    assert event["payload"] == {"nested": {"value": 1}}
    assert logger.read_events()[0]["payload"] == {"nested": {"value": 1}}


def test_event_logger_rejects_invalid_payload_without_writing(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    logger = EventLogger(paths)

    with pytest.raises(TypeError):
        logger.log_event("recording.start", {"bad": object()}, timestamp="t1")

    assert paths.event_log_file.exists() is False


def test_event_logger_reads_missing_file_as_empty_list(tmp_path: Path) -> None:
    logger = EventLogger(ProjectPaths(tmp_path))

    assert logger.read_events() == []


def test_event_logger_rejects_invalid_jsonl(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    paths.event_log_file.write_text("not-json\n", encoding="utf-8")
    logger = EventLogger(paths)

    with pytest.raises(ValueError, match="event log"):
        logger.read_events()
