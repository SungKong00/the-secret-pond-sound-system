from __future__ import annotations

from types import SimpleNamespace

import pytest

from secret_pond.config import AppSettings, AudioFormatSettings, VoiceStackSettings
from secret_pond.services.playback_control import (
    PlaybackControlError,
    restart_playback,
    seek_playback,
    start_playback,
    stop_playback,
)


class FakePlayer:
    def __init__(self, operations: list[str] | None = None) -> None:
        self.operations = operations
        self.frame_cursor = 10
        self.restart_calls = 0
        self.restore_calls = 0
        self.seek_calls = []
        self.loaded_rendered_layers = None

    def snapshot(self):
        return {"frame_cursor": self.frame_cursor}

    def restore(self, snapshot) -> None:
        self.restore_calls += 1
        self.frame_cursor = snapshot["frame_cursor"]

    def restart(self) -> None:
        self.restart_calls += 1
        self.frame_cursor = 0

    def seek(self, frame_cursor: int) -> None:
        self.seek_calls.append(frame_cursor)
        self.frame_cursor = frame_cursor

    def load_rendered_layers(
        self,
        paths,
        *,
        loop_frames=None,
        loop_transition_frames=0,
    ) -> None:
        if self.operations is not None:
            self.operations.append("load_main")
        self.loaded_rendered_layers = paths
        self.loaded_loop_frames = loop_frames
        self.loaded_loop_transition_frames = loop_transition_frames

    def set_peak_ceiling(self, peak_ceiling: float) -> None:
        self.peak_ceiling = peak_ceiling

    def set_enabled(self, layer_id: str, enabled: bool) -> None:
        pass

    def set_realtime_trim(self, layer_id: str, trim_db: float) -> None:
        pass


class FakeOutput:
    def __init__(
        self,
        *,
        fail_start_on_call: int | None = None,
        operations: list[str] | None = None,
    ) -> None:
        self.operations = operations
        self.fail_start_on_call = fail_start_on_call
        self.is_running = True
        self.start_calls = 1
        self.stop_calls = 0

    def stop(self) -> None:
        if self.operations is not None:
            self.operations.append("stop_output")
        self.stop_calls += 1
        self.is_running = False

    def start(self) -> None:
        if self.operations is not None:
            self.operations.append("start_output")
        self.start_calls += 1
        if self.fail_start_on_call == self.start_calls:
            self.is_running = False
            raise OSError("restart failed")
        self.is_running = True


class EventLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class FakeVoiceStack:
    def __init__(self) -> None:
        self.begin_calls = 0
        self.end_calls = 0

    def begin_playback_session(self, settings: AppSettings) -> None:
        self.begin_calls += 1

    def end_playback_session(self) -> None:
        self.end_calls += 1


def test_start_playback_stops_voice_raw_preview_before_main_output_starts(tmp_path) -> None:
    operations: list[str] = []
    voice_stack = FakeVoiceStack()
    runtime = SimpleNamespace(
        player=FakePlayer(operations),
        output=FakeOutput(operations=operations),
        logger=EventLogger(),
        controller=SimpleNamespace(settings=AppSettings()),
        voice_stack=voice_stack,
        transition_warning="preview active",
        voice_raw_preview_path="data/sources/voice/raw/VR0610_213112.wav",
        voice_raw_preview_resume_main=False,
        voice_raw_preview_layers={"voice": object()},
        paths=SimpleNamespace(
            low_playback=tmp_path / "low.wav",
            mid_playback=tmp_path / "mid.wav",
            voice_playback=tmp_path / "voice.wav",
        ),
    )

    start_playback(runtime)

    assert operations == ["stop_output", "load_main", "start_output"]
    assert runtime.output.stop_calls == 1
    assert runtime.output.start_calls == 2
    assert runtime.output.is_running is True
    assert runtime.voice_raw_preview_path is None
    assert runtime.voice_raw_preview_resume_main is False
    assert runtime.voice_raw_preview_layers is None
    assert voice_stack.begin_calls == 1
    assert voice_stack.end_calls == 0


def test_restart_playback_restores_snapshot_and_running_output_after_start_failure() -> None:
    runtime = SimpleNamespace(
        player=FakePlayer(),
        output=FakeOutput(fail_start_on_call=2),
        logger=EventLogger(),
    )

    with pytest.raises(PlaybackControlError, match="restart failed"):
        restart_playback(runtime)

    assert runtime.player.frame_cursor == 10
    assert runtime.player.restore_calls == 1
    assert runtime.output.stop_calls == 1
    assert runtime.output.start_calls == 3
    assert runtime.output.is_running is True
    assert runtime.logger.events == [
        (
            "playback.restart_failed",
            {
                "error": "restart failed",
                "frame_cursor": 10,
                "output_running": True,
            },
        )
    ]


def test_stop_playback_restores_preview_without_starting_inactive_main_playback(
    tmp_path,
) -> None:
    runtime = SimpleNamespace(
        player=FakePlayer(),
        output=FakeOutput(),
        logger=EventLogger(),
        controller=SimpleNamespace(settings=AppSettings()),
        voice_stack=SimpleNamespace(end_playback_session=lambda: None),
        transition_warning="preview active",
        voice_raw_preview_path="data/sources/voice/raw/VR0610_213112.wav",
        voice_raw_preview_resume_main=False,
        voice_raw_preview_layers={"voice": object()},
        paths=SimpleNamespace(
            low_playback=tmp_path / "low.wav",
            mid_playback=tmp_path / "mid.wav",
            voice_playback=tmp_path / "voice.wav",
        ),
    )

    stop_playback(runtime)

    assert runtime.output.stop_calls == 1
    assert runtime.output.start_calls == 1
    assert runtime.output.is_running is False
    assert runtime.voice_raw_preview_path is None
    assert runtime.voice_raw_preview_resume_main is False
    assert runtime.voice_raw_preview_layers is None
    assert runtime.transition_warning is None


def test_seek_playback_maps_progress_to_visible_voice_loop_cycle() -> None:
    player = FakePlayer()
    runtime = SimpleNamespace(
        player=player,
        output=FakeOutput(),
        logger=EventLogger(),
        controller=SimpleNamespace(
            settings=AppSettings(
                audio=AudioFormatSettings(sample_rate=8_000, loop_seconds=60),
                voice_stack=VoiceStackSettings(loop_seconds=60, transition_seconds=5),
            ),
        ),
    )

    seek_playback(runtime, 0.5)

    assert player.seek_calls == [220_000]
    assert player.frame_cursor == 220_000


def test_seek_playback_uses_full_voice_loop_when_transition_is_disabled() -> None:
    player = FakePlayer()
    runtime = SimpleNamespace(
        player=player,
        output=FakeOutput(),
        logger=EventLogger(),
        controller=SimpleNamespace(
            settings=AppSettings(
                audio=AudioFormatSettings(sample_rate=8_000, loop_seconds=60),
                voice_stack=VoiceStackSettings(loop_seconds=60, transition_seconds=0),
            ),
        ),
    )

    seek_playback(runtime, 0.5)

    assert player.seek_calls == [240_000]
    assert player.frame_cursor == 240_000
