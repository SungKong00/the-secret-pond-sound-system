from __future__ import annotations

from collections.abc import Callable

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.config import AppSettings, EqSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.playback_apply_mode import apply_playback_apply_mode
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


class LoggerSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object] | None]] = []

    def log_event(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        self.events.append((event_type, payload))


class PlayerSpy:
    def __init__(self) -> None:
        self.layer_buffer_updates: list[tuple[str, AudioBuffer]] = []
        self.live_eq_state_updates: list[tuple[str, EqSettings]] = []
        self.reload_paths: list[dict[str, object]] = []
        self.load_paths: list[dict[str, object]] = []

    def set_layer_buffer(self, layer_id: str, buffer: AudioBuffer) -> None:
        self.layer_buffer_updates.append((layer_id, buffer))

    def set_live_eq_state(self, layer_id: str, eq: EqSettings) -> None:
        self.live_eq_state_updates.append((layer_id, eq.model_copy(deep=True)))

    def reload_and_restart(self, paths, *, loop_frames=None, loop_transition_frames=0) -> None:
        self.reload_paths.append(
            {
                "paths": dict(paths),
                "loop_frames": loop_frames,
                "loop_transition_frames": loop_transition_frames,
            }
        )

    def load_rendered_layers(self, paths, *, loop_frames=None, loop_transition_frames=0) -> None:
        self.load_paths.append(
            {
                "paths": dict(paths),
                "loop_frames": loop_frames,
                "loop_transition_frames": loop_transition_frames,
            }
        )


class RendererSpy:
    def __init__(
        self,
        buffer: AudioBuffer,
        *,
        marker_reader: Callable[[], AppSettings] | None = None,
    ) -> None:
        self.buffer = buffer
        self.marker_reader = marker_reader
        self.render_markers: list[AppSettings] = []
        self.live_eq_buffer_renders: list[tuple[str, AppSettings]] = []
        self.stable_render_calls: list[tuple[str, AppSettings]] = []

    def render_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.stable_render_calls.append((layer_id, settings))
        return self.buffer

    def render_live_eq_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        if self.marker_reader is not None:
            self.render_markers.append(self.marker_reader().model_copy(deep=True))
        self.live_eq_buffer_renders.append((layer_id, settings))
        return self.buffer


class OutputSpy:
    def __init__(self, *, running: bool) -> None:
        self.is_running = running


class RuntimeHarness:
    def __init__(
        self,
        state: SettingsState,
        live_raw_buffer: AudioBuffer,
        paths: ProjectPaths | None = None,
        output_running: bool | None = None,
    ) -> None:
        self.settings_state = state
        self.settings_store = MemorySettingsStore(state)
        self.controller = type("Controller", (), {"settings": state.active})()
        self.player = PlayerSpy()
        self.renderer = RendererSpy(live_raw_buffer)
        self.logger = LoggerSpy()
        self.playback_render_settings = state.active
        if output_running is not None:
            self.output = OutputSpy(running=output_running)
        if paths is not None:
            self.paths = paths

    def apply_settings_state(self, settings_state: SettingsState) -> None:
        self.controller.settings = settings_state.active
        self.settings_state = settings_state


def test_stable_to_live_mode_uses_live_eq_buffer_not_stable_rendered_artifact() -> None:
    stable = AppSettings().model_copy(
        update={
            "layers": {
                **AppSettings().layers,
                "voice": AppSettings().layers["voice"].model_copy(
                    update={
                        "eq": AppSettings().layers["voice"].eq.model_copy(
                            update={"mid_gain_db": 6.0},
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=stable, draft=stable)
    stable_rendered_artifact = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.9,
        sample_rate=48_000,
    )
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    runtime = RuntimeHarness(state, live_raw_buffer)
    runtime.player.layer_buffer_updates = [("voice", stable_rendered_artifact)]

    result = apply_playback_apply_mode(runtime, "live")  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "live"
    assert runtime.renderer.stable_render_calls == []
    assert runtime.renderer.live_eq_buffer_renders == [("voice", result.active)]
    assert runtime.player.layer_buffer_updates[-1] == ("voice", live_raw_buffer)
    assert runtime.player.layer_buffer_updates[-1][1] is not stable_rendered_artifact
    assert runtime.player.live_eq_state_updates == [("voice", result.active.layers["voice"].eq)]
    assert runtime.playback_render_settings == result.active


def test_stable_to_live_mode_marks_graph_eq_render_baseline_eq_free() -> None:
    stable = AppSettings().model_copy(
        update={
            "layers": {
                **AppSettings().layers,
                "mid": AppSettings().layers["mid"].model_copy(
                    update={
                        "eq": graph_eq_with_mid_gain(
                            AppSettings().layers["mid"].eq,
                            6.0,
                            highpass_hz=90.0,
                            lowpass_hz=9_000.0,
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=stable, draft=stable)
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    runtime = RuntimeHarness(state, live_raw_buffer)
    runtime.renderer = RendererSpy(
        live_raw_buffer,
        marker_reader=lambda: runtime.playback_render_settings,
    )

    result = apply_playback_apply_mode(runtime, "live")  # type: ignore[arg-type]

    assert runtime.renderer.live_eq_buffer_renders == [("mid", result.active)]
    assert len(runtime.renderer.render_markers) == 1
    marker_eq = runtime.renderer.render_markers[0].layers["mid"].eq
    assert marker_eq == EqSettings()
    assert marker_eq.highpass_hz == 20.0
    assert marker_eq.lowpass_hz == 20_000.0
    assert [point.gain_db for point in marker_eq.points] == [0.0, 0.0, 0.0]
    assert runtime.playback_render_settings == result.active


def test_live_to_stable_mode_restores_rendered_cache_paths_without_live_eq_render(
    tmp_path,
) -> None:
    live = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                **AppSettings().layers,
                "voice": AppSettings().layers["voice"].model_copy(
                    update={
                        "eq": AppSettings().layers["voice"].eq.model_copy(
                            update={"mid_gain_db": 6.0},
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=live, draft=live)
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    paths = ProjectPaths(tmp_path)
    runtime = RuntimeHarness(state, live_raw_buffer, paths=paths)
    runtime.player.layer_buffer_updates = [("voice", live_raw_buffer)]

    result = apply_playback_apply_mode(runtime, "stable")  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "stable"
    assert runtime.renderer.live_eq_buffer_renders == []
    assert runtime.renderer.stable_render_calls == []
    assert runtime.player.layer_buffer_updates == [("voice", live_raw_buffer)]
    assert runtime.player.reload_paths == [
        {
            "paths": {
                "low": paths.low_playback,
                "mid": paths.mid_playback,
                "voice": paths.voice_playback,
            },
            "loop_frames": live.audio.sample_rate * live.voice_stack.loop_seconds,
            "loop_transition_frames": live.audio.sample_rate
            * live.voice_stack.transition_seconds,
        }
    ]
    assert runtime.playback_render_settings == result.active


def graph_eq_with_mid_gain(
    eq: EqSettings,
    gain_db: float,
    *,
    highpass_hz: float = 20.0,
    lowpass_hz: float = 20_000.0,
) -> EqSettings:
    points = [point.model_dump() for point in eq.points]
    points[1]["gain_db"] = gain_db
    return EqSettings(points=points, highpass_hz=highpass_hz, lowpass_hz=lowpass_hz)


def test_live_to_stable_mode_loads_cache_without_starting_player_when_output_is_stopped(
    tmp_path,
) -> None:
    live = AppSettings().model_copy(
        update={
            "playback": AppSettings().playback.model_copy(update={"apply_mode": "live"}),
            "layers": {
                **AppSettings().layers,
                "voice": AppSettings().layers["voice"].model_copy(
                    update={
                        "eq": AppSettings().layers["voice"].eq.model_copy(
                            update={"mid_gain_db": 6.0},
                        ),
                    },
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=live, draft=live)
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    paths = ProjectPaths(tmp_path)
    runtime = RuntimeHarness(
        state,
        live_raw_buffer,
        paths=paths,
        output_running=False,
    )

    result = apply_playback_apply_mode(runtime, "stable")  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "stable"
    assert runtime.player.reload_paths == []
    assert runtime.player.load_paths == [
        {
            "paths": {
                "low": paths.low_playback,
                "mid": paths.mid_playback,
                "voice": paths.voice_playback,
            },
            "loop_frames": live.audio.sample_rate * live.voice_stack.loop_seconds,
            "loop_transition_frames": live.audio.sample_rate
            * live.voice_stack.transition_seconds,
        }
    ]
    assert runtime.playback_render_settings == result.active
