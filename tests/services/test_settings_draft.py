from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.audio.renderer import LayerRenderer
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    DeviceSettings,
    SourceSelectionSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_draft import (
    SettingsDraftUpdateError,
    SettingsDraftValidationError,
    update_draft_settings,
)
from secret_pond.services.settings_store import SettingsState


class MemorySettingsStore:
    def __init__(self, state: SettingsState) -> None:
        self.state = state
        self.saved_states: list[SettingsState] = []

    def save(self, state: SettingsState) -> SettingsState:
        self.saved_states.append(state)
        self.state = state
        return state


class FailingSaveSettingsStore:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.saved_states: list[SettingsState] = []

    def save(self, state: SettingsState) -> SettingsState:
        self.saved_states.append(state)
        raise self.error


class MutatingSaveSettingsStore:
    def __init__(self) -> None:
        self.saved_states: list[SettingsState] = []

    def save(self, state: SettingsState) -> SettingsState:
        state.active.layers["voice"].volume_db = -3.0
        state.draft.layers["voice"].volume_db = -9.0
        self.saved_states.append(state)
        return state


class RuntimeHarness:
    def __init__(self, state: SettingsState, settings_store) -> None:
        self.settings_state = state
        self.settings_store = settings_store
        self.controller = type("Controller", (), {"settings": state.active})()
        self.player = PlayerSpy()
        self.voice_raw_preview_path: str | None = None

    def apply_settings_state(self, settings_state: SettingsState) -> None:
        self.controller.settings = settings_state.active
        self.settings_state = settings_state


class PlayerSpy:
    def __init__(self) -> None:
        self.is_playing = True
        self.enabled_updates: list[tuple[str, bool]] = []
        self.realtime_trim_updates: list[tuple[str, float]] = []
        self.layer_buffer_updates: list[tuple[str, AudioBuffer]] = []
        self.live_eq_state_updates: list[tuple[str, float]] = []
        self.restart_called = False
        self.reload_and_restart_called = False

    def set_enabled(self, layer_id: str, enabled: bool) -> None:
        self.enabled_updates.append((layer_id, enabled))

    def set_realtime_trim(self, layer_id: str, realtime_trim_db: float) -> None:
        self.realtime_trim_updates.append((layer_id, realtime_trim_db))

    def set_layer_buffer(self, layer_id: str, buffer: AudioBuffer) -> None:
        self.layer_buffer_updates.append((layer_id, buffer))

    def set_live_eq_state(self, layer_id: str, eq) -> None:
        self.live_eq_state_updates.append((layer_id, eq.mid_gain_db))

    def restart(self) -> None:
        self.restart_called = True

    def reload_and_restart(self, paths) -> None:
        self.reload_and_restart_called = True


class RendererSpy:
    def __init__(self, buffer: AudioBuffer) -> None:
        self.buffer = buffer
        self.layer_buffer_renders: list[tuple[str, AppSettings]] = []
        self.live_eq_buffer_renders: list[tuple[str, AppSettings]] = []

    def render_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.layer_buffer_renders.append((layer_id, settings))
        return self.buffer

    def render_live_eq_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.live_eq_buffer_renders.append((layer_id, settings))
        return self.buffer


def test_update_draft_settings_saves_draft_without_changing_active() -> None:
    active = AppSettings()
    draft = active.model_copy(update={"audio": AudioFormatSettings(channels=1)}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active == active
    assert result.draft.audio.channels == 1
    assert store.saved_states == [result]
    assert runtime.settings_state == result


def test_stable_update_draft_settings_does_not_mutate_active_runtime_state() -> None:
    active = AppSettings()
    draft_layers = {
        **active.layers,
        "voice": active.layers["voice"].model_copy(update={"volume_db": -12.0}),
    }
    draft = active.model_copy(update={"layers": draft_layers}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MutatingSaveSettingsStore()
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert active.playback.apply_mode == "stable"
    assert active.layers["voice"].volume_db == -18.0
    assert runtime.controller.settings.layers["voice"].volume_db == -18.0
    assert state.active.layers["voice"].volume_db == -18.0
    assert result.active.layers["voice"].volume_db == -18.0
    assert result.draft.layers["voice"].volume_db == -9.0
    assert runtime.player.realtime_trim_updates == []


def test_live_update_draft_settings_applies_low_volume_delta_to_active_playback_gain() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft_layers = {
        **active.layers,
        "low": active.layers["low"].model_copy(update={"volume_db": -24.0}),
    }
    draft = active.model_copy(update={"layers": draft_layers}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.layers["low"].volume_db == -24.0
    assert result.draft.layers["low"].volume_db == -24.0
    assert runtime.controller.settings.layers["low"].volume_db == -24.0
    assert runtime.player.realtime_trim_updates == [("low", -12.0)]


def test_live_update_draft_settings_applies_low_eq_to_active_playback_without_restart(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = AppSettings().model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                "low": AppSettings().layers["low"].model_copy(update={"volume_db": 0.0}),
                "mid": AppSettings().layers["mid"].model_copy(update={"volume_db": 0.0}),
                "voice": AppSettings().layers["voice"].model_copy(update={"volume_db": 0.0}),
            },
        },
        deep=True,
    )
    t = np.arange(8_000, dtype=np.float32) / 8_000
    low_tone = (np.sin(2 * np.pi * 100.0 * t) * 0.05).astype(np.float32)
    low_samples = np.column_stack([low_tone, low_tone])
    silence = np.zeros((8_000, 2), dtype=np.float32)
    write_wav_atomic(paths.low_source, AudioBuffer(low_samples, sample_rate=8_000))
    write_wav_atomic(paths.mid_source, AudioBuffer(silence, sample_rate=8_000))
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(silence, sample_rate=8_000))
    renderer = LayerRenderer(paths)
    renderer.render_all(settings)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(
        {"low": paths.low_playback, "mid": paths.mid_playback, "voice": paths.voice_playback}
    )
    player.start()
    state = SettingsState(active=settings, draft=settings)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.paths = paths
    runtime.renderer = renderer
    runtime.player = player

    before = _rms(player.next_block(2_048).samples[:, 0])
    draft_layers = {
        **settings.layers,
        "low": settings.layers["low"].model_copy(
            update={
                "eq": settings.layers["low"].eq.model_copy(update={"low_gain_db": 6.0}),
            },
        ),
    }
    draft = settings.model_copy(update={"layers": draft_layers}, deep=True)
    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]
    after = _rms(player.next_block(2_048).samples[:, 0])

    assert result.active.layers["low"].eq.low_gain_db == 6.0
    assert after > before * 1.5


def test_live_update_draft_settings_applies_mid_eq_to_current_playback_state(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = AppSettings().model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                "low": AppSettings().layers["low"].model_copy(update={"volume_db": 0.0}),
                "mid": AppSettings().layers["mid"].model_copy(update={"volume_db": 0.0}),
                "voice": AppSettings().layers["voice"].model_copy(update={"volume_db": 0.0}),
            },
        },
        deep=True,
    )
    t = np.arange(8_000, dtype=np.float32) / 8_000
    mid_tone = (np.sin(2 * np.pi * 1_000.0 * t) * 0.05).astype(np.float32)
    mid_samples = np.column_stack([mid_tone, mid_tone])
    silence = np.zeros((8_000, 2), dtype=np.float32)
    write_wav_atomic(paths.low_source, AudioBuffer(silence, sample_rate=8_000))
    write_wav_atomic(paths.mid_source, AudioBuffer(mid_samples, sample_rate=8_000))
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(silence, sample_rate=8_000))
    renderer = LayerRenderer(paths)
    renderer.render_all(settings)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(
        {"low": paths.low_playback, "mid": paths.mid_playback, "voice": paths.voice_playback}
    )
    player.start()
    state = SettingsState(active=settings, draft=settings)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.paths = paths
    runtime.renderer = renderer
    runtime.player = player

    before = _rms(player.next_block(2_048).samples[:, 0])
    draft_layers = {
        **settings.layers,
        "mid": settings.layers["mid"].model_copy(
            update={
                "eq": settings.layers["mid"].eq.model_copy(update={"mid_gain_db": 6.0}),
            },
        ),
    }
    draft = settings.model_copy(update={"layers": draft_layers}, deep=True)
    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]
    after = _rms(player.next_block(2_048).samples[:, 0])

    assert result.active.layers["mid"].eq.mid_gain_db == 6.0
    assert player.live_eq_states["mid"].mid_gain_db == 6.0
    assert after > before * 1.5
    assert player.is_playing is True


def test_live_update_draft_settings_routes_mid_eq_to_active_playback_without_restart() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft_layers = {
        **active.layers,
        "mid": active.layers["mid"].model_copy(
            update={
                "eq": active.layers["mid"].eq.model_copy(update={"mid_gain_db": 5.0}),
            },
        ),
    }
    draft = active.model_copy(update={"layers": draft_layers}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    rendered_mid = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.1,
        sample_rate=48_000,
    )
    runtime.renderer = RendererSpy(rendered_mid)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.layers["mid"].eq.mid_gain_db == 5.0
    assert result.draft.layers["mid"].eq.mid_gain_db == 5.0
    assert runtime.controller.settings.layers["mid"].eq.mid_gain_db == 5.0
    assert runtime.renderer.layer_buffer_renders == []
    assert runtime.renderer.live_eq_buffer_renders == [("mid", result.active)]
    assert runtime.player.layer_buffer_updates == [("mid", rendered_mid)]
    assert runtime.player.live_eq_state_updates == [("mid", 5.0)]
    assert runtime.playback_render_settings.layers["mid"].eq.mid_gain_db == 5.0
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


def test_live_update_draft_settings_routes_voice_eq_to_active_playback_without_restart() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft_layers = {
        **active.layers,
        "voice": active.layers["voice"].model_copy(
            update={
                "eq": active.layers["voice"].eq.model_copy(update={"mid_gain_db": 6.0}),
            },
        ),
    }
    draft = active.model_copy(update={"layers": draft_layers}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    rendered_voice = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    runtime.renderer = RendererSpy(rendered_voice)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.layers["voice"].eq.mid_gain_db == 6.0
    assert runtime.controller.settings.layers["voice"].eq.mid_gain_db == 6.0
    assert runtime.renderer.layer_buffer_renders == []
    assert runtime.renderer.live_eq_buffer_renders == [("voice", result.active)]
    assert runtime.player.layer_buffer_updates == [("voice", rendered_voice)]
    assert runtime.player.live_eq_state_updates == [("voice", 6.0)]
    assert runtime.playback_render_settings.layers["voice"].eq.mid_gain_db == 6.0
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


def test_live_voice_eq_rerenders_from_raw_voice_stack_not_existing_playback_cache(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = AppSettings().model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                "low": AppSettings().layers["low"].model_copy(update={"volume_db": -60.0}),
                "mid": AppSettings().layers["mid"].model_copy(update={"volume_db": -60.0}),
                "voice": AppSettings().layers["voice"].model_copy(
                    update={
                        "volume_db": 0.0,
                        "eq": AppSettings().layers["voice"].eq.model_copy(
                            update={"mid_gain_db": 6.0},
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    t = np.arange(8_000, dtype=np.float32) / 8_000
    voice_tone = (np.sin(2 * np.pi * 1_000.0 * t) * 0.05).astype(np.float32)
    raw_voice = np.column_stack([voice_tone, voice_tone])
    already_eq_rendered_voice = raw_voice * 2.0
    silence = np.zeros((8_000, 2), dtype=np.float32)
    write_wav_atomic(paths.low_source, AudioBuffer(silence, sample_rate=8_000))
    write_wav_atomic(paths.mid_source, AudioBuffer(silence, sample_rate=8_000))
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(raw_voice, sample_rate=8_000))
    write_wav_atomic(
        paths.voice_playback,
        AudioBuffer(already_eq_rendered_voice, sample_rate=8_000),
    )
    renderer = LayerRenderer(paths)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(silence, sample_rate=8_000),
            "mid": AudioBuffer(silence, sample_rate=8_000),
            "voice": AudioBuffer(already_eq_rendered_voice, sample_rate=8_000),
        }
    )
    player.start()
    state = SettingsState(active=settings, draft=settings)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.paths = paths
    runtime.renderer = renderer
    runtime.player = player
    draft_layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(
            update={
                "eq": settings.layers["voice"].eq.model_copy(update={"mid_gain_db": 12.0}),
            },
        ),
    }
    draft = settings.model_copy(update={"layers": draft_layers}, deep=True)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]
    expected_raw_based = renderer.render_layer_buffer("voice", result.active).samples
    if np.allclose(expected_raw_based, already_eq_rendered_voice, atol=1e-4):
        raise AssertionError("test setup must distinguish raw source from playback cache")
    block = player.next_block(8_000).samples

    assert result.active.layers["voice"].eq.mid_gain_db == 12.0
    np.testing.assert_allclose(block, expected_raw_based, atol=2e-4)


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


def test_live_update_draft_settings_reprocesses_running_voice_raw_preview_treatment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft = active.model_copy(
        update={
            "recording": active.recording.model_copy(
                update={
                    "gain_db": active.recording.gain_db + 3.0,
                    "reverb_mix": 0.7,
                }
            ),
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.voice_raw_preview_path = "data/sources/voice/raw/VR0610_213112.wav"
    calls = []

    def fake_prepare_voice_raw_preview(runtime_arg, relative_path, settings) -> None:
        calls.append((runtime_arg, relative_path, settings))

    monkeypatch.setattr(
        "secret_pond.services.settings_draft.prepare_voice_raw_preview",
        fake_prepare_voice_raw_preview,
    )

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert calls == [
        (
            runtime,
            "data/sources/voice/raw/VR0610_213112.wav",
            result.draft,
        )
    ]


def test_live_update_draft_settings_skips_voice_raw_preview_reprocess_when_not_playing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft = active.model_copy(
        update={
            "recording": active.recording.model_copy(
                update={
                    "gain_db": active.recording.gain_db + 3.0,
                    "reverb_mix": 0.7,
                }
            ),
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.voice_raw_preview_path = "data/sources/voice/raw/VR0610_213112.wav"
    runtime.player.is_playing = False
    calls = []

    def fake_prepare_voice_raw_preview(runtime_arg, relative_path, settings) -> None:
        calls.append((runtime_arg, relative_path, settings))

    monkeypatch.setattr(
        "secret_pond.services.settings_draft.prepare_voice_raw_preview",
        fake_prepare_voice_raw_preview,
    )

    update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert calls == []


def test_live_update_draft_settings_keeps_voice_gain_relative_to_rendered_volume() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    first_layers = {
        **active.layers,
        "voice": active.layers["voice"].model_copy(update={"volume_db": -12.0}),
    }
    second_layers = {
        **active.layers,
        "voice": active.layers["voice"].model_copy(update={"volume_db": -9.0}),
    }
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    first = update_draft_settings(
        runtime,
        active.model_copy(update={"layers": first_layers}, deep=True),
        current=state,
    )  # type: ignore[arg-type]
    result = update_draft_settings(
        runtime,
        active.model_copy(update={"layers": second_layers}, deep=True),
        current=first,
    )  # type: ignore[arg-type]

    assert result.active.layers["voice"].volume_db == -9.0
    assert result.draft.layers["voice"].volume_db == -9.0
    assert runtime.controller.settings.layers["voice"].volume_db == -9.0
    assert runtime.player.realtime_trim_updates == [("voice", 6.0), ("voice", 9.0)]


def test_live_update_draft_settings_keeps_audio_loop_seconds_on_apply_flow() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft = active.model_copy(
        update={
            "audio": active.audio.model_copy(update={"loop_seconds": 120}),
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.audio.loop_seconds == 300
    assert result.draft.audio.loop_seconds == 120
    assert runtime.controller.settings.audio.loop_seconds == 300
    assert runtime.player.realtime_trim_updates == []


def test_live_update_draft_settings_keeps_sample_rate_on_apply_flow() -> None:
    active = AppSettings().model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=48_000, channels=2),
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft = active.model_copy(
        update={
            "audio": active.audio.model_copy(update={"sample_rate": 44_100}),
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.audio.sample_rate == 48_000
    assert result.draft.audio.sample_rate == 44_100
    assert store.saved_states[0].active.audio.sample_rate == 48_000
    assert store.saved_states[0].draft.audio.sample_rate == 44_100
    assert runtime.controller.settings.audio.sample_rate == 48_000
    assert runtime.player.realtime_trim_updates == []


def test_live_update_draft_settings_keeps_source_selection_on_apply_flow() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "sources": SourceSelectionSettings(
                low_path="data/sources/low/applied-low.wav",
                mid_path="data/sources/mid/applied-mid.wav",
            ),
        },
        deep=True,
    )
    draft = active.model_copy(
        update={
            "sources": SourceSelectionSettings(
                low_path="data/sources/low/draft-low.wav",
                mid_path="data/sources/mid/applied-mid.wav",
            ),
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.sources.low_path == "data/sources/low/applied-low.wav"
    assert result.draft.sources.low_path == "data/sources/low/draft-low.wav"
    assert store.saved_states[0].active.sources.low_path == "data/sources/low/applied-low.wav"
    assert store.saved_states[0].draft.sources.low_path == "data/sources/low/draft-low.wav"
    assert runtime.controller.settings.sources.low_path == "data/sources/low/applied-low.wav"
    assert runtime.player.realtime_trim_updates == []


def test_live_update_draft_settings_rejects_output_device_changes() -> None:
    active = AppSettings().model_copy(
        update={
            "devices": DeviceSettings(output_device_id="speaker-1"),
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    draft = active.model_copy(
        update={"devices": DeviceSettings(output_device_id="speaker-2")},
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    with pytest.raises(SettingsDraftValidationError, match="System panel"):
        update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert store.saved_states == []
    assert runtime.settings_state == state
    assert runtime.controller.settings.devices.output_device_id == "speaker-1"
    assert runtime.player.realtime_trim_updates == []


def test_update_draft_settings_raises_validation_error_for_device_changes() -> None:
    active = AppSettings()
    draft = active.model_copy(
        update={"devices": DeviceSettings(input_device_id="mic-2")},
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    with pytest.raises(SettingsDraftValidationError, match="System panel"):
        update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert store.saved_states == []
    assert runtime.settings_state == state


def test_update_draft_settings_keeps_save_failures_as_update_errors() -> None:
    active = AppSettings()
    draft = active.model_copy(update={"audio": AudioFormatSettings(channels=1)}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = FailingSaveSettingsStore(OSError("settings save failed"))
    runtime = RuntimeHarness(state, store)

    with pytest.raises(SettingsDraftUpdateError, match="settings save failed"):
        update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert len(store.saved_states) == 1
    assert runtime.settings_state == state
