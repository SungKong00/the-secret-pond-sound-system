from __future__ import annotations

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.config import AppSettings, AudioFormatSettings, VoiceStackSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.runtime import build_runtime
from secret_pond.services.settings_apply import SettingsApplyError, apply_draft_settings
from secret_pond.services.settings_store import SettingsState, SettingsStore


class MemoryOutput:
    def __init__(self) -> None:
        self._running = False
        self.statuses = []
        self.latest_status = None
        self.latest_error = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False


def service_settings() -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        voice_stack=VoiceStackSettings(loop_seconds=1),
    )


def write_required_sources(paths: ProjectPaths, settings: AppSettings) -> None:
    paths.ensure_directories()
    frames = settings.audio.sample_rate * settings.audio.loop_seconds
    samples = np.ones((frames, settings.audio.channels), dtype=np.float32) * 0.05
    buffer = AudioBuffer(samples=samples, sample_rate=settings.audio.sample_rate)
    write_wav_atomic(paths.low_source, buffer)
    write_wav_atomic(paths.mid_source, buffer)


def build_service_runtime(tmp_path, settings: AppSettings):
    SettingsStore(ProjectPaths(tmp_path)).save(SettingsState(active=settings, draft=settings))
    return build_runtime(tmp_path, output=MemoryOutput())


def test_apply_draft_settings_service_applies_render_only_change(tmp_path) -> None:
    settings = service_settings()
    runtime = build_service_runtime(tmp_path, settings)
    write_required_sources(ProjectPaths(tmp_path), settings)
    layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(update={"volume_db": -9.0}),
    }
    draft = settings.model_copy(update={"layers": layers}, deep=True)
    runtime.settings_store.set_draft(draft)

    result = apply_draft_settings(runtime)

    assert result.change_plan.changed_sections == ["layers"]
    assert result.change_plan.runtime_config_changed is False
    assert result.was_output_running is False
    assert result.output_running is False
    assert runtime.settings_store.load().active.layers["voice"].volume_db == -9.0
    assert runtime.controller.settings.layers["voice"].volume_db == -9.0
    assert runtime.paths.low_playback.exists()
    assert runtime.paths.mid_playback.exists()
    assert runtime.paths.voice_playback.exists()


def test_apply_draft_settings_service_rejects_runtime_config_change(tmp_path) -> None:
    settings = service_settings()
    runtime = build_service_runtime(tmp_path, settings)
    draft = settings.model_copy(
        update={"audio": settings.audio.model_copy(update={"sample_rate": 44_100})},
        deep=True,
    )
    runtime.settings_store.set_draft(draft)

    with pytest.raises(SettingsApplyError) as exc_info:
        apply_draft_settings(runtime)

    assert "app restart" in str(exc_info.value)
    assert exc_info.value.change_plan.runtime_config_changed is True
    assert exc_info.value.change_plan.changed_runtime_fields == ["audio.sample_rate"]
    assert runtime.settings_store.load().active.audio.sample_rate == 8_000
