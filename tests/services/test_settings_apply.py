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


class ApplyRestartPlayerSpy:
    def __init__(self) -> None:
        self.reload_paths = []
        self.voice_hot_swap_calls = 0
        self.enabled_updates = []
        self.realtime_trim_updates = []
        self.peak_ceiling_updates = []

    @property
    def frame_cursor(self) -> int:
        return 0

    def snapshot(self):
        return {"reload_paths": list(self.reload_paths)}

    def reload_and_restart(self, paths) -> None:
        self.reload_paths.append(paths)

    def load_rendered_layers(self, paths) -> None:
        raise AssertionError("Apply and Restart must reload the rendered cache")

    def restart(self) -> None:
        raise AssertionError("Apply and Restart must reload the rendered cache")

    def restore(self, snapshot) -> None:
        self.reload_paths = list(snapshot["reload_paths"])

    def start_voice_crossfade(self, *args, **kwargs) -> None:
        self.voice_hot_swap_calls += 1
        raise AssertionError("Apply and Restart must not use live voice hot-swap")

    def set_enabled(self, layer_id: str, enabled: bool) -> None:
        self.enabled_updates.append((layer_id, enabled))

    def set_realtime_trim(self, layer_id: str, realtime_trim_db: float) -> None:
        self.realtime_trim_updates.append((layer_id, realtime_trim_db))

    def set_peak_ceiling(self, peak_ceiling: float) -> None:
        self.peak_ceiling_updates.append(peak_ceiling)


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


def test_apply_draft_settings_reloads_rendered_cache_without_live_voice_hot_swap(
    tmp_path,
) -> None:
    settings = service_settings().model_copy(
        update={"voice_stack": VoiceStackSettings(mode="live_ephemeral", loop_seconds=1)},
        deep=True,
    )
    runtime = build_service_runtime(tmp_path, settings)
    write_required_sources(ProjectPaths(tmp_path), settings)
    player = ApplyRestartPlayerSpy()
    runtime.player = player
    runtime.output.start()
    layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(update={"volume_db": -9.0}),
    }
    draft = settings.model_copy(update={"layers": layers}, deep=True)
    runtime.settings_store.set_draft(draft)

    result = apply_draft_settings(runtime)

    assert result.was_output_running is True
    assert result.output_running is True
    assert player.voice_hot_swap_calls == 0
    assert len(player.reload_paths) == 1
    reload_paths = player.reload_paths[0]
    assert reload_paths["low"] == runtime.paths.low_playback
    assert reload_paths["mid"] == runtime.paths.mid_playback
    assert reload_paths["voice"] == runtime.paths.voice_playback
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
