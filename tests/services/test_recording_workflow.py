from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.config import AppSettings, AudioFormatSettings, VoiceStackSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.recording_workflow import (
    RecordingPlaybackGuard,
    refresh_playback_after_recording,
)


class WorkflowPlayerSpy:
    def __init__(self) -> None:
        self.crossfade_calls = []
        self.reload_paths = []
        self.load_paths = []

    def start_voice_crossfade(self, next_voice, *, duration_frames, transition_target_id):
        self.crossfade_calls.append(
            {
                "next_voice": next_voice,
                "duration_frames": duration_frames,
                "transition_target_id": transition_target_id,
            }
        )
        return None

    def reload_and_restart(self, paths):
        self.reload_paths.append(paths)

    def load_rendered_layers(self, paths):
        self.load_paths.append(paths)

    def set_enabled(self, _layer_id, _enabled):
        return None

    def set_realtime_trim(self, _layer_id, _realtime_trim_db):
        return None

    def set_peak_ceiling(self, _peak_ceiling):
        return None


class WorkflowOutput:
    def __init__(self, *, running: bool) -> None:
        self.is_running = running


class WorkflowLogger:
    def __init__(self) -> None:
        self.events = []

    def log_event(self, event_type, payload=None):
        self.events.append({"event_type": event_type, "payload": payload or {}})


class WorkflowVoiceStack:
    def transition_guard_state(self, _settings):
        return SimpleNamespace(
            playback_session_id="session-1",
            current_stack_id="data/voice/voice_stack_raw.wav",
        )


def workflow_settings() -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        voice_stack=VoiceStackSettings(
            mode="live_ephemeral",
            loop_seconds=1,
            transition_seconds=4,
        ),
    )


def write_rendered_layers(paths: ProjectPaths, value: float = 0.1) -> None:
    paths.ensure_directories()
    samples = np.ones((8_000, 2), dtype=np.float32) * value
    buffer = AudioBuffer(samples=samples, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, buffer)
    write_wav_atomic(paths.mid_playback, buffer)
    write_wav_atomic(paths.voice_playback, buffer)


def workflow_runtime(tmp_path, *, output_running: bool):
    paths = ProjectPaths(tmp_path)
    write_rendered_layers(paths)
    settings = workflow_settings()
    settings.sources.voice_stack_path = "data/sources/voice/stack/VS0610_213112.wav"
    return SimpleNamespace(
        paths=paths,
        controller=SimpleNamespace(settings=settings),
        player=WorkflowPlayerSpy(),
        output=WorkflowOutput(running=output_running),
        logger=WorkflowLogger(),
        voice_stack=WorkflowVoiceStack(),
    )


def accepted_outcome():
    return SimpleNamespace(
        accepted=True,
        stack_result=SimpleNamespace(
            voice_stack_path="data/sources/voice/stack/VS0610_213112.wav",
        ),
    )


def test_refresh_playback_uses_voice_crossfade_when_output_running_and_guard_matches(
    tmp_path,
) -> None:
    runtime = workflow_runtime(tmp_path, output_running=True)
    guard = RecordingPlaybackGuard(
        playback_session_id="session-1",
        current_stack_id="data/voice/voice_stack_raw.wav",
    )

    refresh_playback_after_recording(runtime, accepted_outcome(), guard=guard)

    assert runtime.player.reload_paths == []
    assert runtime.player.load_paths == []
    assert len(runtime.player.crossfade_calls) == 1
    call = runtime.player.crossfade_calls[0]
    assert call["duration_frames"] == 32_000
    assert call["transition_target_id"] == "data/sources/voice/stack/VS0610_213112.wav"
    assert call["next_voice"].frames == 8_000
    assert runtime.logger.events == [
        {
            "event_type": "recording.voice_transition_started",
            "payload": {
                "status": "applying",
                "source_layer_id": "voice",
                "target_layer_id": "voice",
                "transition_source_id": "data/voice/voice_stack_raw.wav",
                "transition_target_id": "data/sources/voice/stack/VS0610_213112.wav",
                "transition_seconds": 4,
                "duration_frames": 32_000,
                "crossfade_scheduled": True,
                "reason": "output_running_guard_matched_next_voice_ready",
                "previous_transition_target_id": None,
                "output_running": True,
                "guard_matched": True,
                "playback_session_id": "session-1",
                "guard_current_stack_id": "data/voice/voice_stack_raw.wav",
                "next_voice_frames": 8_000,
            },
        }
    ]


def test_refresh_playback_crossfades_from_current_voice_when_next_voice_becomes_ready(
    tmp_path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = workflow_settings()
    settings.sources.voice_stack_path = "data/sources/voice/stack/VS0610_213112.wav"
    old_low = AudioBuffer(samples=np.ones((8, 2), dtype=np.float32) * 0.1, sample_rate=8_000)
    old_mid = AudioBuffer(samples=np.ones((8, 2), dtype=np.float32) * 0.2, sample_rate=8_000)
    old_voice = AudioBuffer(samples=np.ones((8, 2), dtype=np.float32) * 0.3, sample_rate=8_000)
    next_voice = AudioBuffer(samples=np.ones((8, 2), dtype=np.float32) * 0.7, sample_rate=8_000)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers({"low": old_low, "mid": old_mid, "voice": old_voice})
    player.start()
    player.next_block(3)
    runtime = SimpleNamespace(
        paths=paths,
        controller=SimpleNamespace(settings=settings),
        player=player,
        output=WorkflowOutput(running=True),
        logger=WorkflowLogger(),
        voice_stack=WorkflowVoiceStack(),
    )
    guard = RecordingPlaybackGuard(
        playback_session_id="session-1",
        current_stack_id="data/voice/voice_stack_raw.wav",
    )

    before_ready = player.snapshot()
    write_wav_atomic(paths.voice_playback, next_voice)
    refresh_playback_after_recording(runtime, accepted_outcome(), guard=guard)

    after_ready = player.snapshot()
    assert before_ready.voice_transition is None
    assert after_ready.voice_transition is not None
    assert after_ready.voice_transition.transition_target_id == (
        "data/sources/voice/stack/VS0610_213112.wav"
    )
    assert after_ready.voice_transition.duration_frames == 32_000
    assert player.frame_cursor == 3
    assert player.is_playing is True
    np.testing.assert_allclose(
        after_ready.voice_transition.from_buffer.samples,
        old_voice.samples,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        after_ready.voice_transition.to_buffer.samples,
        next_voice.samples,
        atol=1e-4,
    )
    np.testing.assert_allclose(after_ready.layers["low"].samples, old_low.samples, atol=1e-6)
    np.testing.assert_allclose(after_ready.layers["mid"].samples, old_mid.samples, atol=1e-6)
    assert runtime.logger.events[-1]["event_type"] == "recording.voice_transition_started"
    assert runtime.logger.events[-1]["payload"]["transition_target_id"] == (
        "data/sources/voice/stack/VS0610_213112.wav"
    )


def test_live_ephemeral_ready_diagnostic_captures_audible_voice_layer(tmp_path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = workflow_settings()
    settings.sources.voice_stack_path = "data/sources/voice/stack/VS0610_213112.wav"
    current_voice_samples = np.linspace(0.1, 0.8, num=16, dtype=np.float32).reshape(8, 2)
    current_voice = AudioBuffer(samples=current_voice_samples, sample_rate=8_000)
    next_voice = AudioBuffer(
        samples=np.ones((8, 2), dtype=np.float32) * 0.9,
        sample_rate=8_000,
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=np.zeros((8, 2), dtype=np.float32), sample_rate=8_000),
            "mid": AudioBuffer(samples=np.zeros((8, 2), dtype=np.float32), sample_rate=8_000),
            "voice": current_voice,
        }
    )
    player.start()
    player.next_block(5)
    runtime = SimpleNamespace(
        paths=paths,
        controller=SimpleNamespace(settings=settings),
        player=player,
        output=WorkflowOutput(running=True),
        logger=WorkflowLogger(),
        voice_stack=WorkflowVoiceStack(),
    )
    guard = RecordingPlaybackGuard(
        playback_session_id="session-1",
        current_stack_id="data/voice/voice_stack_raw.wav",
    )

    ready_moment_snapshot = player.snapshot()
    assert ready_moment_snapshot.layers is not None
    ready_moment_voice = ready_moment_snapshot.layers["voice"]
    ready_moment_cursor = ready_moment_snapshot.frame_cursor
    write_wav_atomic(paths.voice_playback, next_voice)
    refresh_playback_after_recording(runtime, accepted_outcome(), guard=guard)

    transition = player.snapshot().voice_transition
    assert transition is not None
    assert ready_moment_cursor == 5
    assert player.frame_cursor == ready_moment_cursor
    np.testing.assert_allclose(
        transition.from_buffer.samples,
        ready_moment_voice.samples,
        atol=1e-6,
    )
    np.testing.assert_allclose(transition.to_buffer.samples, next_voice.samples, atol=1e-4)


def test_live_ephemeral_transition_log_emits_exact_crossfade_runtime_evidence(tmp_path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = workflow_settings()
    settings.sources.voice_stack_path = "data/sources/voice/stack/VS0610_213112.wav"
    current_voice = AudioBuffer(
        samples=np.ones((8, 2), dtype=np.float32) * 0.25,
        sample_rate=8_000,
    )
    next_voice = AudioBuffer(
        samples=np.ones((8, 2), dtype=np.float32) * 0.75,
        sample_rate=8_000,
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=np.zeros((8, 2), dtype=np.float32), sample_rate=8_000),
            "mid": AudioBuffer(samples=np.zeros((8, 2), dtype=np.float32), sample_rate=8_000),
            "voice": current_voice,
        }
    )
    player.start()
    player.next_block(6)
    runtime = SimpleNamespace(
        paths=paths,
        controller=SimpleNamespace(settings=settings),
        player=player,
        output=WorkflowOutput(running=True),
        logger=WorkflowLogger(),
        voice_stack=WorkflowVoiceStack(),
    )
    guard = RecordingPlaybackGuard(
        playback_session_id="session-1",
        current_stack_id="data/voice/voice_stack_raw.wav",
    )

    write_wav_atomic(paths.voice_playback, next_voice)
    refresh_playback_after_recording(runtime, accepted_outcome(), guard=guard)

    assert runtime.logger.events[-1] == {
        "event_type": "recording.voice_transition_started",
        "payload": {
            "status": "applying",
            "source_layer_id": "voice",
            "target_layer_id": "voice",
            "transition_source_id": "data/voice/voice_stack_raw.wav",
            "transition_target_id": "data/sources/voice/stack/VS0610_213112.wav",
            "transition_seconds": 4,
            "duration_frames": 32_000,
            "crossfade_scheduled": True,
            "reason": "output_running_guard_matched_next_voice_ready",
            "output_running": True,
            "guard_matched": True,
            "playback_session_id": "session-1",
            "guard_current_stack_id": "data/voice/voice_stack_raw.wav",
            "frame_cursor_at_ready": 6,
            "player_was_playing": True,
            "previous_transition_target_id": None,
            "current_voice_frames": 8,
            "next_voice_frames": 8,
        },
    }


@pytest.mark.parametrize(
    ("guard", "expected"),
    [
        (
            RecordingPlaybackGuard(
                playback_session_id="session-1",
                current_stack_id="data/voice/voice_stack_raw.wav",
            ),
            {"crossfade_scheduled": True, "skip_logged": False},
        ),
        (
            RecordingPlaybackGuard(
                playback_session_id="session-1",
                current_stack_id="data/voice/stale_stack_raw.wav",
            ),
            {"crossfade_scheduled": False, "skip_logged": True},
        ),
    ],
)
def test_live_ephemeral_ready_diagnostic_records_crossfade_schedule_or_skip(
    tmp_path,
    guard,
    expected,
) -> None:
    runtime = workflow_runtime(tmp_path, output_running=True)

    refresh_playback_after_recording(runtime, accepted_outcome(), guard=guard)

    diagnostic = {
        "crossfade_scheduled": bool(runtime.player.crossfade_calls),
        "skip_logged": any(
            event["event_type"] == "recording.playback_refresh_skipped"
            for event in runtime.logger.events
        ),
    }
    assert diagnostic == expected
    if not expected["crossfade_scheduled"]:
        assert runtime.transition_warning == (
            "목소리 전환을 건너뛰었습니다. 재생 중 선택된 스택이 바뀌었습니다. "
            "기존 목소리를 유지합니다."
        )


def test_refresh_playback_loads_rendered_layers_without_crossfade_when_output_stopped(
    tmp_path,
) -> None:
    runtime = workflow_runtime(tmp_path, output_running=False)

    refresh_playback_after_recording(runtime, accepted_outcome())

    assert runtime.player.crossfade_calls == []
    assert runtime.player.reload_paths == []
    assert len(runtime.player.load_paths) == 1


def test_refresh_playback_keeps_running_output_on_crossfade_failure(tmp_path) -> None:
    runtime = workflow_runtime(tmp_path, output_running=True)

    def fail_crossfade(*_args, **_kwargs):
        raise RuntimeError("crossfade failed")

    runtime.player.start_voice_crossfade = fail_crossfade

    refresh_playback_after_recording(runtime, accepted_outcome())

    assert runtime.output.is_running is True
    assert runtime.transition_warning == (
        "목소리 전환을 적용하지 못했습니다. 기존 목소리를 유지합니다."
    )
    assert runtime.player.reload_paths == []
    assert runtime.logger.events[-1]["event_type"] == "recording.playback_refresh_failed"
