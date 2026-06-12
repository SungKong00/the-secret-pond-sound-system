from __future__ import annotations

from collections.abc import Callable

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.renderer import LayerRenderer, LiveEqSourceError
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    EqSettings,
    SourceSelectionSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.live_graph_eq import (
    LIVE_GRAPH_EQ_FAILURE_WARNING,
    apply_live_graph_eq_render_result,
    live_graph_eq_state,
    schedule_live_graph_eq_update,
)
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


class MissingLiveSourceRendererSpy(RendererSpy):
    def render_live_eq_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.live_eq_buffer_renders.append((layer_id, settings))
        raise LiveEqSourceError(layer_id, None, "EQ-free source is missing")


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
        self.transition_warning: str | None = None
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


def test_stable_to_live_mode_missing_live_source_rolls_back_to_stable_state() -> None:
    stable = AppSettings().model_copy(
        update={
            "layers": {
                **AppSettings().layers,
                "mid": AppSettings().layers["mid"].model_copy(
                    update={"eq": graph_eq_with_mid_gain(AppSettings().layers["mid"].eq, 6.0)},
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
    runtime.renderer = MissingLiveSourceRendererSpy(live_raw_buffer)

    result = apply_playback_apply_mode(runtime, "live")  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "stable"
    assert runtime.settings_store.state.active.playback.apply_mode == "stable"
    assert runtime.controller.settings.playback.apply_mode == "stable"
    assert runtime.playback_render_settings == stable
    assert runtime.player.layer_buffer_updates == []
    assert runtime.transition_warning == LIVE_GRAPH_EQ_FAILURE_WARNING


def test_stable_to_live_mode_uses_voice_stack_raw_when_selected_stack_is_stale(
    tmp_path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    stable = AppSettings().model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
            "sources": SourceSelectionSettings(
                voice_stack_path="data/sources/voice/stack/VS0608_072702.wav",
            ),
            "layers": {
                **AppSettings().layers,
                "voice": AppSettings().layers["voice"].model_copy(
                    update={"eq": graph_eq_with_mid_gain(AppSettings().layers["voice"].eq, 6.0)},
                ),
            },
        },
        deep=True,
    )
    write_wav_atomic(
        paths.voice_stack_raw,
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.2, sample_rate=8_000),
    )
    state = SettingsState(active=stable, draft=stable)
    runtime = RuntimeHarness(
        state,
        AudioBuffer(samples=np.zeros((8_000, 2), dtype=np.float32), sample_rate=8_000),
        paths=paths,
    )
    runtime.renderer = LayerRenderer(paths)

    result = apply_playback_apply_mode(runtime, "live")  # type: ignore[arg-type]

    assert result.active.playback.apply_mode == "live"
    assert runtime.transition_warning is None
    assert runtime.player.layer_buffer_updates
    assert runtime.player.layer_buffer_updates[-1][0] == "voice"
    assert [event_type for event_type, _payload in runtime.logger.events] == [
        "settings.playback_apply_mode_applied"
    ]


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


def test_live_to_stable_mode_invalidates_pending_live_graph_eq_request() -> None:
    live = AppSettings().model_copy(
        update={"playback": AppSettings().playback.model_copy(update={"apply_mode": "live"})},
        deep=True,
    )
    scheduled = live.model_copy(
        update={
            "layers": {
                **live.layers,
                "mid": live.layers["mid"].model_copy(
                    update={"eq": graph_eq_with_mid_gain(live.layers["mid"].eq, 6.0)},
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=live, draft=scheduled)
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    runtime = RuntimeHarness(state, live_raw_buffer)
    pending_state = schedule_live_graph_eq_update(runtime, "mid", scheduled, now_ms=0)
    pending_request = pending_state.pending_request

    result = apply_playback_apply_mode(runtime, "stable")  # type: ignore[arg-type]

    assert pending_request is not None
    assert result.active.playback.apply_mode == "stable"
    assert result.active.layers["mid"].eq == live.layers["mid"].eq
    assert result.draft.playback.apply_mode == "stable"
    assert result.draft.layers["mid"].eq == scheduled.layers["mid"].eq
    assert live_graph_eq_state(runtime).pending_request is None
    assert live_graph_eq_state(runtime).invalidation_reason == "playback_apply_mode:stable"

    accepted = apply_live_graph_eq_render_result(
        runtime,
        request_id=pending_request.request_id,
        mode_epoch=pending_request.mode_epoch,
        layer_id="mid",
        buffer=live_raw_buffer,
        rendered_settings=scheduled,
    )

    assert accepted is False
    assert runtime.player.layer_buffer_updates == []
    assert runtime.playback_render_settings == result.active


def test_stable_to_live_mode_apply_choice_preserves_staged_graph_eq_and_schedules() -> None:
    stable = AppSettings()
    staged = stable.model_copy(
        update={
            "layers": {
                **stable.layers,
                "mid": stable.layers["mid"].model_copy(
                    update={"eq": graph_eq_with_mid_gain(stable.layers["mid"].eq, 6.0)},
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=stable, draft=staged)
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    runtime = RuntimeHarness(state, live_raw_buffer)

    result = apply_playback_apply_mode(  # type: ignore[arg-type]
        runtime,
        "live",
        staged_graph_eq="apply",
    )

    live_state = live_graph_eq_state(runtime)
    assert result.active.playback.apply_mode == "live"
    assert result.active.layers["mid"].eq == stable.layers["mid"].eq
    assert result.draft.playback.apply_mode == "live"
    assert result.draft.layers["mid"].eq == staged.layers["mid"].eq
    assert live_state.pending_request is not None
    assert live_state.pending_request.layer_id == "mid"
    assert live_state.pending_request.settings.layers["mid"].eq == staged.layers["mid"].eq


def test_stable_to_live_mode_discard_choice_syncs_staged_graph_eq_from_active() -> None:
    stable = AppSettings()
    staged = stable.model_copy(
        update={
            "layers": {
                **stable.layers,
                "mid": stable.layers["mid"].model_copy(
                    update={"eq": graph_eq_with_mid_gain(stable.layers["mid"].eq, 6.0)},
                ),
            },
        },
        deep=True,
    )
    state = SettingsState(active=stable, draft=staged)
    live_raw_buffer = AudioBuffer(
        samples=np.ones((32, 2), dtype=np.float32) * 0.2,
        sample_rate=48_000,
    )
    runtime = RuntimeHarness(state, live_raw_buffer)

    result = apply_playback_apply_mode(  # type: ignore[arg-type]
        runtime,
        "live",
        staged_graph_eq="discard",
    )

    assert result.active.playback.apply_mode == "live"
    assert result.draft.playback.apply_mode == "live"
    assert result.draft.layers["mid"].eq == stable.layers["mid"].eq
    assert live_graph_eq_state(runtime).pending_request is None


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
