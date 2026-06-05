from __future__ import annotations

from secret_pond.config import AppSettings, SourceSelectionSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.diagnostics import diagnostics_payload
from secret_pond.services.logging_service import EventLogger


def test_diagnostics_payload_returns_recent_events_newest_first(tmp_path) -> None:
    paths = ProjectPaths(tmp_path)
    logger = EventLogger(paths)
    for index in range(7):
        logger.log_event(f"event.{index}", timestamp=f"t{index}")

    payload = diagnostics_payload(paths, AppSettings(), logger)

    assert [event["event_type"] for event in payload["events"]["recent"]] == [
        "event.6",
        "event.5",
        "event.4",
        "event.3",
        "event.2",
    ]
    assert payload["events"]["path"] == "data/logs/events.jsonl"
    assert payload["events"]["exists"] is True
    assert payload["events"]["error"] is None


def test_diagnostics_payload_reports_selected_library_sources(tmp_path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    selected_low = paths.low_sources_dir / "library-low.wav"
    selected_low.write_bytes(b"low")
    settings = AppSettings(
        sources=SourceSelectionSettings(low_path="data/sources/low/library-low.wav")
    )

    payload = diagnostics_payload(paths, settings, EventLogger(paths))

    sources = {source["id"]: source for source in payload["sources"]}
    assert sources["low"]["exists"] is True
    assert sources["low"]["path"] == "data/sources/low/library-low.wav"
    assert sources["low"]["size_bytes"] == 3
    assert sources["mid"]["exists"] is False
    assert sources["voice"]["path"] == "data/voice/voice_stack_raw.wav"
