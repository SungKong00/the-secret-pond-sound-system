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
    EqSettings,
    SourceSelectionSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.playback_apply_mode import apply_playback_apply_mode
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

    def load(self) -> SettingsState:
        return self.state

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
        self.transition_warning: str | None = None
        self.logger = LoggerSpy()

    def apply_settings_state(self, settings_state: SettingsState) -> None:
        self.controller.settings = settings_state.active
        self.settings_state = settings_state


class LoggerSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_type: str, payload: dict | None = None) -> None:
        self.events.append((event_type, payload or {}))


class PlayerSpy:
    def __init__(self) -> None:
        self.is_playing = True
        self.enabled_updates: list[tuple[str, bool]] = []
        self.realtime_trim_updates: list[tuple[str, float]] = []
        self.layer_buffer_updates: list[tuple[str, AudioBuffer]] = []
        self.live_eq_state_updates: list[tuple[str, float]] = []
        self._live_eq_states = {layer_id: EqSettings() for layer_id in ("low", "mid", "voice")}
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
        self._live_eq_states[layer_id] = eq.model_copy(deep=True)

    @property
    def live_eq_states(self):
        return {layer_id: eq.model_copy(deep=True) for layer_id, eq in self._live_eq_states.items()}

    def restart(self) -> None:
        self.restart_called = True

    def reload_and_restart(self, paths) -> None:
        self.reload_and_restart_called = True


class FailingLayerBufferPlayerSpy(PlayerSpy):
    def set_layer_buffer(self, layer_id: str, buffer: AudioBuffer) -> None:
        super().set_layer_buffer(layer_id, buffer)
        raise RuntimeError("hot swap failed")


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


def test_stable_update_draft_settings_stages_volume_and_mute_without_touching_playback() -> None:
    active = AppSettings()
    draft_layers = {
        **active.layers,
        "low": active.layers["low"].model_copy(update={"enabled": False, "volume_db": -24.0}),
        "mid": active.layers["mid"].model_copy(update={"enabled": False, "volume_db": -30.0}),
        "voice": active.layers["voice"].model_copy(update={"enabled": False, "volume_db": -36.0}),
    }
    draft = active.model_copy(update={"layers": draft_layers}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "stable"
    assert result.active.layers == active.layers
    assert runtime.settings_state.active.layers == active.layers
    assert runtime.controller.settings.layers == active.layers
    assert result.draft.layers["low"].enabled is False
    assert result.draft.layers["low"].volume_db == -24.0
    assert result.draft.layers["mid"].enabled is False
    assert result.draft.layers["mid"].volume_db == -30.0
    assert result.draft.layers["voice"].enabled is False
    assert result.draft.layers["voice"].volume_db == -36.0
    assert runtime.player.enabled_updates == []
    assert runtime.player.realtime_trim_updates == []
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


def test_stable_update_draft_settings_stages_eq_without_touching_active_playback() -> None:
    active = AppSettings()
    draft_layers = {
        **active.layers,
        "mid": active.layers["mid"].model_copy(
            update={
                "eq": active.layers["mid"].eq.model_copy(update={"mid_gain_db": 5.0}),
            },
        ),
        "voice": active.layers["voice"].model_copy(
            update={
                "eq": active.layers["voice"].eq.model_copy(update={"high_gain_db": -4.0}),
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
    runtime.playback_render_settings = active

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "stable"
    assert result.active.layers["mid"].eq == active.layers["mid"].eq
    assert result.active.layers["voice"].eq == active.layers["voice"].eq
    assert runtime.controller.settings.layers["mid"].eq == active.layers["mid"].eq
    assert runtime.settings_state.active.layers["voice"].eq == active.layers["voice"].eq
    assert result.draft.layers["mid"].eq.mid_gain_db == 5.0
    assert result.draft.layers["voice"].eq.high_gain_db == -4.0
    assert runtime.playback_render_settings is active
    assert runtime.renderer.layer_buffer_renders == []
    assert runtime.renderer.live_eq_buffer_renders == []
    assert runtime.player.layer_buffer_updates == []
    assert runtime.player.live_eq_state_updates == []
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


def test_stable_update_draft_settings_stages_graph_eq_points_without_touching_playback() -> None:
    active = AppSettings()
    draft_layers = {
        **active.layers,
        "mid": active.layers["mid"].model_copy(
            update={"eq": graph_eq_with_mid_gain(active.layers["mid"].eq, 5.0)},
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
    runtime.playback_render_settings = active

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "stable"
    assert result.active.layers["mid"].eq == active.layers["mid"].eq
    assert runtime.controller.settings.layers["mid"].eq == active.layers["mid"].eq
    assert result.draft.layers["mid"].eq.points[1].gain_db == 5.0
    assert runtime.playback_render_settings is active
    assert runtime.renderer.layer_buffer_renders == []
    assert runtime.renderer.live_eq_buffer_renders == []
    assert runtime.player.layer_buffer_updates == []
    assert runtime.player.live_eq_state_updates == []
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


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


def test_live_update_draft_settings_uses_active_state_for_layer_reenable() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
        },
        deep=True,
    )
    disabled_layers = {
        **active.layers,
        "low": active.layers["low"].model_copy(update={"enabled": False}),
    }
    disabled_active = active.model_copy(update={"layers": disabled_layers}, deep=True)
    draft_layers = {
        **disabled_active.layers,
        "low": disabled_active.layers["low"].model_copy(update={"enabled": True}),
    }
    draft = disabled_active.model_copy(update={"layers": draft_layers}, deep=True)
    state = SettingsState(active=disabled_active, draft=disabled_active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.playback_render_settings = active

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active.layers["low"].enabled is True
    assert result.draft.layers["low"].enabled is True
    assert runtime.controller.settings.layers["low"].enabled is True
    assert runtime.player.enabled_updates == [("low", True)]


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


def test_live_rapid_eq_updates_keep_output_playback_running(
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
                "mid": AppSettings().layers["mid"].model_copy(update={"volume_db": 0.0}),
                "voice": AppSettings().layers["voice"].model_copy(update={"volume_db": -60.0}),
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
    player.next_block(512)
    state = SettingsState(active=settings, draft=settings)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.paths = paths
    runtime.renderer = renderer
    runtime.player = player

    current = state
    block_size = 512
    for gain_db in (2.0, 6.0, -3.0, 9.0, 0.0):
        draft_layers = {
            **current.draft.layers,
            "mid": current.draft.layers["mid"].model_copy(
                update={
                    "eq": current.draft.layers["mid"].eq.model_copy(
                        update={"mid_gain_db": gain_db},
                    ),
                },
            ),
        }
        draft = current.draft.model_copy(update={"layers": draft_layers}, deep=True)
        cursor_before_update = player.frame_cursor

        current = update_draft_settings(runtime, draft, current=current)  # type: ignore[arg-type]
        block = player.next_block(block_size)

        assert current.active.layers["mid"].eq.mid_gain_db == gain_db
        assert player.is_playing is True
        assert cursor_before_update != 0
        assert block.next_frame_cursor == (cursor_before_update + block_size) % 8_000
        assert _rms(block.samples[:, 0]) > 0.01

    recovery_eq = current.draft.layers["mid"].eq.model_copy(update={"mid_gain_db": 4.0})
    recovery_draft_layers = {
        **current.draft.layers,
        "mid": current.draft.layers["mid"].model_copy(update={"eq": recovery_eq}),
    }
    recovery_draft = current.draft.model_copy(update={"layers": recovery_draft_layers}, deep=True)
    cursor_before_recovery = player.frame_cursor

    current = update_draft_settings(runtime, recovery_draft, current=current)  # type: ignore[arg-type]
    recovery_block = player.next_block(block_size)

    assert current.active.layers["mid"].eq.mid_gain_db == 4.0
    assert player.live_eq_states["mid"].mid_gain_db == 4.0
    assert player.is_playing is True
    assert recovery_block.next_frame_cursor == (cursor_before_recovery + block_size) % 8_000
    assert _rms(recovery_block.samples[:, 0]) > 0.01

    player.set_realtime_trim("mid", -6.0)
    trim_block = player.next_block(64)
    player.set_enabled("mid", False)
    mute_block = player.next_block(64)
    player.seek(4_000)
    seek_block = player.next_block(64)

    assert player.is_playing is True
    assert trim_block.next_frame_cursor == (recovery_block.next_frame_cursor + 64) % 8_000
    assert mute_block.next_frame_cursor == (trim_block.next_frame_cursor + 64) % 8_000
    assert seek_block.next_frame_cursor == 4_064


def test_live_rapid_eq_updates_keep_final_state_matching_last_submission() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                **AppSettings().layers,
                "mid": AppSettings().layers["mid"].model_copy(
                    update={"enabled": True, "volume_db": -6.0},
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    rendered_mid = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.1,
        sample_rate=48_000,
    )
    runtime.renderer = RendererSpy(rendered_mid)
    runtime.playback_render_settings = active

    current = state
    submitted_eqs = [
        EqSettings(highpass_hz=40.0, low_gain_db=2.0, mid_gain_db=1.0),
        EqSettings(highpass_hz=80.0, mid_gain_db=-3.0, high_gain_db=4.0),
        EqSettings(
            highpass_hz=120.0,
            lowpass_hz=12_000.0,
            low_gain_db=-2.0,
            mid_gain_db=6.0,
            high_gain_db=-1.5,
        ),
    ]
    for eq in submitted_eqs:
        draft_layers = {
            **current.draft.layers,
            "mid": current.draft.layers["mid"].model_copy(update={"eq": eq}),
        }
        draft = current.draft.model_copy(update={"layers": draft_layers}, deep=True)

        current = update_draft_settings(runtime, draft, current=current)  # type: ignore[arg-type]

    final_eq = submitted_eqs[-1]
    assert current.active.layers["mid"].eq == final_eq
    assert current.draft.layers["mid"].eq == final_eq
    assert runtime.controller.settings.layers["mid"].eq == final_eq
    assert runtime.settings_state.active.layers["mid"].eq == final_eq
    assert runtime.playback_render_settings.layers["mid"].eq == final_eq
    assert runtime.player.live_eq_states["mid"] == final_eq
    assert runtime.player.live_eq_state_updates[-1] == ("mid", final_eq.mid_gain_db)
    assert runtime.renderer.live_eq_buffer_renders[-1] == ("mid", current.active)
    assert len(runtime.renderer.live_eq_buffer_renders) == len(submitted_eqs)
    assert len(runtime.player.layer_buffer_updates) == len(submitted_eqs)
    assert runtime.player.is_playing is True
    assert current.active.layers["mid"].enabled is True
    assert current.active.layers["mid"].volume_db == -6.0
    assert runtime.player.enabled_updates == []
    assert runtime.player.realtime_trim_updates == []
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


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


def test_live_eq_hot_swap_failure_sets_nonfatal_korean_operator_caution() -> None:
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
    runtime.player = FailingLayerBufferPlayerSpy()
    rendered_mid = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.1,
        sample_rate=48_000,
    )
    runtime.renderer = RendererSpy(rendered_mid)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.draft.layers["mid"].eq.mid_gain_db == 5.0
    assert runtime.transition_warning == (
        "Live EQ 전환을 적용하지 못했습니다. 기존 재생 상태를 유지합니다."
    )
    assert runtime.logger.events[-1] == (
        "settings.live_eq_hot_swap_failed",
        {
            "layer_id": "mid",
            "error": "hot swap failed",
        },
    )
    assert runtime.player.live_eq_state_updates == []
    assert runtime.player.restart_called is False
    assert runtime.player.reload_and_restart_called is False


def test_live_eq_hot_swap_failure_restores_current_stream_state() -> None:
    active = AppSettings().model_copy(
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
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(
                samples=np.ones((8, 2), dtype=np.float32) * 0.1,
                sample_rate=8_000,
            ),
            "mid": AudioBuffer(
                samples=np.ones((8, 2), dtype=np.float32) * 0.2,
                sample_rate=8_000,
            ),
            "voice": AudioBuffer(
                samples=np.ones((8, 2), dtype=np.float32) * 0.3,
                sample_rate=8_000,
            ),
        },
    )
    player.start()
    player.next_block(3)
    cursor_before_update = player.frame_cursor

    def corrupt_current_stream_then_fail(_layer_id: str, _buffer: AudioBuffer) -> None:
        player.stop()
        raise RuntimeError("hot swap failed")

    player.set_layer_buffer = corrupt_current_stream_then_fail  # type: ignore[method-assign]
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
    runtime.player = player
    runtime.renderer = RendererSpy(
        AudioBuffer(samples=np.ones((8, 2), dtype=np.float32) * 0.4, sample_rate=8_000)
    )
    runtime.playback_render_settings = active

    update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    after_failure_snapshot = player.snapshot()
    next_block = player.next_block(2)
    assert runtime.transition_warning == (
        "Live EQ 전환을 적용하지 못했습니다. 기존 재생 상태를 유지합니다."
    )
    assert after_failure_snapshot.playing is True
    assert after_failure_snapshot.frame_cursor == cursor_before_update
    assert next_block.next_frame_cursor == cursor_before_update + 2
    np.testing.assert_allclose(
        next_block.samples,
        np.ones((2, 2), dtype=np.float32) * 0.6,
        atol=1e-6,
    )


def test_live_same_curve_eq_update_syncs_active_state_without_stacking() -> None:
    active = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                **AppSettings().layers,
                "mid": AppSettings().layers["mid"].model_copy(
                    update={
                        "eq": AppSettings().layers["mid"].eq.model_copy(
                            update={"mid_gain_db": 6.0},
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.renderer = RendererSpy(
        AudioBuffer(samples=np.ones((32, 2), dtype=np.float32), sample_rate=48_000)
    )

    result = update_draft_settings(runtime, active, current=state)  # type: ignore[arg-type]

    assert result.active.layers["mid"].eq.mid_gain_db == 6.0
    assert runtime.renderer.live_eq_buffer_renders == []
    assert runtime.player.layer_buffer_updates == []
    assert runtime.player.live_eq_state_updates == [("mid", 6.0)]


def test_stable_to_live_mode_marks_stable_eq_render_state_inactive() -> None:
    stable = AppSettings().model_copy(
        update={
            "layers": {
                **AppSettings().layers,
                "mid": AppSettings().layers["mid"].model_copy(
                    update={
                        "volume_db": 0.0,
                        "eq": AppSettings().layers["mid"].eq.model_copy(
                            update={"mid_gain_db": 6.0},
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=stable, draft=stable)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)
    runtime.playback_render_settings = stable
    rendered_mid = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.1,
        sample_rate=48_000,
    )
    runtime.renderer = RendererSpy(rendered_mid)

    live_state = apply_playback_apply_mode(runtime, "live")  # type: ignore[arg-type]
    draft_layers = {
        **live_state.draft.layers,
        "mid": live_state.draft.layers["mid"].model_copy(update={"volume_db": -3.0}),
    }
    draft = live_state.draft.model_copy(update={"layers": draft_layers}, deep=True)

    result = update_draft_settings(runtime, draft, current=live_state)  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "live"
    assert len(runtime.renderer.live_eq_buffer_renders) == 1
    rendered_layer_id, rendered_settings = runtime.renderer.live_eq_buffer_renders[0]
    assert rendered_layer_id == "mid"
    assert rendered_settings.layers["mid"].eq.mid_gain_db == 6.0
    assert runtime.player.layer_buffer_updates == [("mid", rendered_mid)]
    assert runtime.playback_render_settings.layers["mid"].eq.mid_gain_db == 6.0


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


def graph_eq_with_mid_gain(eq: EqSettings, gain_db: float) -> EqSettings:
    points = [point.model_dump() for point in eq.points]
    points[1]["gain_db"] = gain_db
    return EqSettings(points=points, highpass_hz=eq.highpass_hz, lowpass_hz=eq.lowpass_hz)


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
