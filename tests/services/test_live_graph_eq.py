from __future__ import annotations

from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.renderer import LiveEqSourceError
from secret_pond.config import AppSettings, EqSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.live_graph_eq import (
    LIVE_EQ_APPLY_DEBOUNCE_MS,
    LIVE_EQ_SLOW_APPLY_MS,
    LIVE_GRAPH_EQ_FAILURE_WARNING,
    apply_live_graph_eq_render_result,
    live_graph_eq_payload,
    live_graph_eq_state,
    mark_slow_live_graph_eq_requests,
    run_due_live_graph_eq_update,
    schedule_live_graph_eq_update,
)


class RendererSpy:
    def __init__(self) -> None:
        self.renders: list[tuple[str, AppSettings]] = []
        self.buffer = AudioBuffer(
            samples=np.ones((16, 2), dtype=np.float32) * 0.25,
            sample_rate=48_000,
        )

    def render_live_eq_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.renders.append((layer_id, settings))
        return self.buffer


class MissingSourceRendererSpy(RendererSpy):
    def render_live_eq_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.renders.append((layer_id, settings))
        raise LiveEqSourceError(layer_id, None, "EQ-free source is missing")


class MissingVoiceStackSourceRendererSpy(RendererSpy):
    def __init__(self, source_path: Path, fallback_path: Path) -> None:
        super().__init__()
        self.source_path = source_path
        self.fallback_path = fallback_path

    def render_live_eq_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        self.renders.append((layer_id, settings))
        raise LiveEqSourceError(
            "voice",
            self.source_path,
            "selected Voice Stack source is missing and fallback is unavailable",
            fallback_path=self.fallback_path,
            fallback_available=False,
        )


class PlayerSpy:
    def __init__(self) -> None:
        self.layer_buffer_updates: list[tuple[str, AudioBuffer]] = []
        self.live_eq_state_updates: list[tuple[str, EqSettings]] = []

    def set_layer_buffer(self, layer_id: str, buffer: AudioBuffer) -> None:
        self.layer_buffer_updates.append((layer_id, buffer))

    def set_live_eq_state(self, layer_id: str, eq: EqSettings) -> None:
        self.live_eq_state_updates.append((layer_id, eq.model_copy(deep=True)))


class SnapshotPlayerSpy(PlayerSpy):
    def snapshot(self):
        return (
            list(self.layer_buffer_updates),
            list(self.live_eq_state_updates),
        )

    def restore(self, snapshot) -> None:
        self.layer_buffer_updates = list(snapshot[0])
        self.live_eq_state_updates = list(snapshot[1])


class RuntimeHarness:
    def __init__(self) -> None:
        self.state_epoch = 42
        self.renderer = RendererSpy()
        self.player = PlayerSpy()
        self.logger = LoggerSpy()
        self.playback_render_settings = AppSettings()
        self.transition_warning: str | None = None


class LoggerSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_type: str, payload: dict | None = None) -> None:
        self.events.append((event_type, payload or {}))


class FailingSettingsStore:
    def __init__(self, state) -> None:
        self.state = state

    def load(self):
        return self.state

    def save(self, state):
        self.state = state
        raise RuntimeError("settings save failed")


def graph_eq_with_mid_gain(settings: AppSettings, gain_db: float) -> AppSettings:
    return graph_eq_with_layer_mid_gain(settings, "mid", gain_db)


def graph_eq_with_layer_mid_gain(
    settings: AppSettings,
    layer_id: str,
    gain_db: float,
) -> AppSettings:
    points = [point.model_dump() for point in settings.layers[layer_id].eq.points]
    points[1]["gain_db"] = gain_db
    eq = EqSettings(points=points)
    layers = {
        **settings.layers,
        layer_id: settings.layers[layer_id].model_copy(update={"eq": eq}),
    }
    return settings.model_copy(update={"layers": layers}, deep=True)


def test_schedule_live_graph_eq_update_is_latest_wins_after_debounce() -> None:
    runtime = RuntimeHarness()
    first_settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 3.0)
    second_settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 6.0)

    first_state = schedule_live_graph_eq_update(
        runtime,
        "mid",
        first_settings,
        now_ms=100,
    )
    first_request = first_state.pending_request
    second_state = schedule_live_graph_eq_update(
        runtime,
        "mid",
        second_settings,
        now_ms=200,
    )

    assert first_request is not None
    assert first_request.request_id == 1
    assert first_request.mode_epoch == 42
    assert first_request.due_at_ms == 100 + LIVE_EQ_APPLY_DEBOUNCE_MS
    assert second_state.pending_request is not None
    assert second_state.pending_request.request_id == 2
    assert runtime.renderer.renders == []

    assert run_due_live_graph_eq_update(runtime, now_ms=1199) is None
    applied = run_due_live_graph_eq_update(runtime, now_ms=1200)

    assert applied is not None
    assert applied.request_id == 2
    assert runtime.renderer.renders == [("mid", second_settings)]
    assert runtime.player.layer_buffer_updates == [("mid", runtime.renderer.buffer)]
    assert runtime.player.live_eq_state_updates[-1][0] == "mid"
    assert runtime.player.live_eq_state_updates[-1][1].points[1].gain_db == 6.0
    assert runtime.playback_render_settings.layers["mid"].eq.points[1].gain_db == 6.0
    assert live_graph_eq_state(runtime).pending_request is None


def test_live_graph_eq_preserves_distinct_layer_requests_after_debounce() -> None:
    runtime = RuntimeHarness()
    low_settings = graph_eq_with_layer_mid_gain(runtime.playback_render_settings, "low", 3.0)
    mid_settings = graph_eq_with_layer_mid_gain(runtime.playback_render_settings, "mid", 6.0)

    schedule_live_graph_eq_update(runtime, "low", low_settings, now_ms=100)
    schedule_live_graph_eq_update(runtime, "mid", mid_settings, now_ms=200)

    low_request = run_due_live_graph_eq_update(
        runtime,
        now_ms=100 + LIVE_EQ_APPLY_DEBOUNCE_MS,
    )
    mid_request = run_due_live_graph_eq_update(
        runtime,
        now_ms=200 + LIVE_EQ_APPLY_DEBOUNCE_MS,
    )

    assert low_request is not None
    assert low_request.layer_id == "low"
    assert mid_request is not None
    assert mid_request.layer_id == "mid"
    assert runtime.renderer.renders == [("low", low_settings), ("mid", mid_settings)]
    assert [layer_id for layer_id, _buffer in runtime.player.layer_buffer_updates] == [
        "low",
        "mid",
    ]
    assert runtime.playback_render_settings.layers["low"].eq.points[1].gain_db == 3.0
    assert runtime.playback_render_settings.layers["mid"].eq.points[1].gain_db == 6.0
    assert live_graph_eq_state(runtime).pending_request is None


def test_stale_live_graph_eq_render_result_is_discarded() -> None:
    runtime = RuntimeHarness()
    first_settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 3.0)
    second_settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 6.0)
    first_state = schedule_live_graph_eq_update(runtime, "mid", first_settings, now_ms=0)
    first_request = first_state.pending_request
    schedule_live_graph_eq_update(runtime, "mid", second_settings, now_ms=100)

    assert first_request is not None
    accepted = apply_live_graph_eq_render_result(
        runtime,
        request_id=first_request.request_id,
        mode_epoch=first_request.mode_epoch,
        layer_id="mid",
        buffer=runtime.renderer.buffer,
        rendered_settings=first_settings,
    )

    assert accepted is False
    assert runtime.player.layer_buffer_updates == []
    assert runtime.playback_render_settings.layers["mid"].eq.points[1].gain_db == 0.0


def test_slow_live_graph_eq_request_marks_caution_after_threshold() -> None:
    runtime = RuntimeHarness()
    settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 3.0)

    schedule_live_graph_eq_update(runtime, "mid", settings, now_ms=0)

    assert mark_slow_live_graph_eq_requests(
        runtime,
        now_ms=LIVE_EQ_APPLY_DEBOUNCE_MS + LIVE_EQ_SLOW_APPLY_MS - 1,
    ) is False
    assert live_graph_eq_state(runtime).slow_caution is False

    assert mark_slow_live_graph_eq_requests(
        runtime,
        now_ms=LIVE_EQ_APPLY_DEBOUNCE_MS + LIVE_EQ_SLOW_APPLY_MS,
    ) is True
    assert live_graph_eq_state(runtime).slow_caution is True


def test_missing_live_eq_source_keeps_current_playback_and_sets_warning() -> None:
    runtime = RuntimeHarness()
    runtime.renderer = MissingSourceRendererSpy()
    settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 6.0)

    schedule_live_graph_eq_update(runtime, "mid", settings, now_ms=0)
    result = run_due_live_graph_eq_update(
        runtime,
        now_ms=LIVE_EQ_APPLY_DEBOUNCE_MS,
    )

    live_state = live_graph_eq_state(runtime)
    assert result is None
    assert runtime.renderer.renders == [("mid", settings)]
    assert runtime.player.layer_buffer_updates == []
    assert runtime.playback_render_settings.layers["mid"].eq.points[1].gain_db == 0.0
    assert live_state.pending_request is None
    assert live_state.failure_warning == LIVE_GRAPH_EQ_FAILURE_WARNING
    assert runtime.transition_warning == LIVE_GRAPH_EQ_FAILURE_WARNING
    payload = live_graph_eq_payload(runtime)
    assert payload["status"] == "failed"
    assert payload["pending"] is False
    assert payload["layer_id"] == "mid"
    assert payload["request_id"] == 1


def test_live_graph_eq_persist_failure_rolls_back_hot_swap_and_reports_failure() -> None:
    runtime = RuntimeHarness()
    runtime.player = SnapshotPlayerSpy()
    previous_render_settings = runtime.playback_render_settings.model_copy(deep=True)
    next_settings = graph_eq_with_mid_gain(runtime.playback_render_settings, 6.0)

    from secret_pond.services.settings_store import SettingsState

    settings_state = SettingsState(
        active=runtime.playback_render_settings,
        draft=runtime.playback_render_settings,
    )
    runtime.settings_state = settings_state
    runtime.settings_store = FailingSettingsStore(settings_state)

    schedule_live_graph_eq_update(runtime, "mid", next_settings, now_ms=0)
    result = run_due_live_graph_eq_update(runtime, now_ms=LIVE_EQ_APPLY_DEBOUNCE_MS)

    live_state = live_graph_eq_state(runtime)
    assert result is None
    assert runtime.player.layer_buffer_updates == []
    assert runtime.player.live_eq_state_updates == []
    assert runtime.playback_render_settings == previous_render_settings
    assert live_state.pending_request is None
    assert live_state.failure_warning == LIVE_GRAPH_EQ_FAILURE_WARNING
    assert live_state.failure_detail is None
    assert live_state.last_failed_layer_id == "mid"


def test_missing_voice_stack_source_failure_payload_names_fallback(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    stale_source = paths.voice_stack_sources_dir / "VS0608_072702.wav"
    fallback_source = paths.voice_stack_raw
    runtime = RuntimeHarness()
    runtime.paths = paths
    runtime.renderer = MissingVoiceStackSourceRendererSpy(stale_source, fallback_source)

    schedule_live_graph_eq_update(runtime, "voice", runtime.playback_render_settings, now_ms=0)
    result = run_due_live_graph_eq_update(runtime, now_ms=LIVE_EQ_APPLY_DEBOUNCE_MS)

    expected_detail = (
        "Voice Stack source가 없습니다: data/sources/voice/stack/VS0608_072702.wav "
        "fallback 확인: data/voice/voice_stack_raw.wav "
        "fallback도 없어서 Live 적용을 중단했습니다."
    )
    live_state = live_graph_eq_state(runtime)
    payload = live_graph_eq_payload(runtime)
    assert result is None
    assert live_state.failure_warning == LIVE_GRAPH_EQ_FAILURE_WARNING
    assert live_state.failure_detail == expected_detail
    assert payload["failure_warning"] == LIVE_GRAPH_EQ_FAILURE_WARNING
    assert payload["failure_detail"] == expected_detail
    assert payload["status"] == "failed"
    assert payload["pending"] is False
    assert payload["layer_id"] == "voice"
    assert payload["request_id"] == 1
    assert runtime.logger.events[-1] == (
        "settings.live_graph_eq_failed",
        {
            "layer_id": "voice",
            "request_id": 1,
            "error": (
                f"Live Graph EQ source for voice is unavailable: {stale_source}. "
                "selected Voice Stack source is missing and fallback is unavailable."
                f" fallback={fallback_source} (unavailable)."
            ),
            "failure_detail": expected_detail,
        },
    )
