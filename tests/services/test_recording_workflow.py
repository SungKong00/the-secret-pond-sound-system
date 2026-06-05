from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
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
        voice_stack=VoiceStackSettings(mode="live_ephemeral", loop_seconds=1),
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
    assert call["duration_frames"] == 24_000
    assert call["transition_target_id"] == "data/sources/voice/stack/VS0610_213112.wav"
    assert call["next_voice"].frames == 8_000


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
    assert runtime.player.reload_paths == []
    assert runtime.logger.events[-1]["event_type"] == "recording.playback_refresh_failed"
