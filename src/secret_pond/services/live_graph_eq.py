from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.layers import LayerId
from secret_pond.audio.renderer import LiveEqSourceError
from secret_pond.config import AppSettings, EqSettings
from secret_pond.services.settings_store import SettingsState

LIVE_EQ_APPLY_DEBOUNCE_MS = 1_000
LIVE_EQ_DECLICK_MS = 50
LIVE_EQ_SLOW_APPLY_MS = 3_000
LIVE_GRAPH_EQ_FAILURE_WARNING = (
    "Live Graph EQ 적용을 완료하지 못했습니다. 기존 재생 상태를 유지합니다. "
    "필요하면 Stable Apply and Restart로 적용하세요."
)


@dataclass(frozen=True)
class LiveGraphEqRequest:
    request_id: int
    mode_epoch: int
    layer_id: LayerId
    settings: AppSettings
    requested_at_ms: int
    due_at_ms: int


@dataclass
class LiveGraphEqState:
    next_request_id: int = 0
    pending_requests: dict[LayerId, LiveGraphEqRequest] = field(default_factory=dict)
    confirmed_eq: dict[LayerId, EqSettings] = field(default_factory=dict)
    failed_layers: dict[LayerId, tuple[int, str, str | None]] = field(default_factory=dict)
    applied_layers: dict[LayerId, int] = field(default_factory=dict)
    slow_caution: bool = False
    failure_warning: str | None = None
    failure_detail: str | None = None
    invalidation_reason: str | None = None
    last_applied_request_id: int | None = None
    last_applied_layer_id: LayerId | None = None
    last_failed_request_id: int | None = None
    last_failed_layer_id: LayerId | None = None

    @property
    def pending_request(self) -> LiveGraphEqRequest | None:
        if not self.pending_requests:
            return None
        return min(
            self.pending_requests.values(),
            key=lambda request: (request.due_at_ms, request.request_id),
        )

    @pending_request.setter
    def pending_request(self, request: LiveGraphEqRequest | None) -> None:
        self.pending_requests.clear()
        if request is not None:
            self.pending_requests[request.layer_id] = request


def live_graph_eq_state(runtime: Any) -> LiveGraphEqState:
    state = getattr(runtime, "_live_graph_eq_state", None)
    if isinstance(state, LiveGraphEqState):
        return state
    state = LiveGraphEqState()
    runtime._live_graph_eq_state = state
    return state


def schedule_live_graph_eq_update(
    runtime: Any,
    layer_id: str,
    next_settings: AppSettings,
    *,
    now_ms: int | None = None,
) -> LiveGraphEqState:
    state = live_graph_eq_state(runtime)
    request_id = state.next_request_id + 1
    requested_at_ms = _now_ms() if now_ms is None else int(now_ms)
    normalized_layer_id = _validate_layer_id(layer_id)
    state.next_request_id = request_id
    state.pending_requests[normalized_layer_id] = LiveGraphEqRequest(
        request_id=request_id,
        mode_epoch=_mode_epoch(runtime),
        layer_id=normalized_layer_id,
        settings=next_settings.model_copy(deep=True),
        requested_at_ms=requested_at_ms,
        due_at_ms=requested_at_ms + LIVE_EQ_APPLY_DEBOUNCE_MS,
    )
    state.slow_caution = False
    state.invalidation_reason = None
    state.failed_layers.pop(normalized_layer_id, None)
    state.applied_layers.pop(normalized_layer_id, None)
    if state.failed_layers:
        latest_failed_layer_id, latest_failure = _latest_failed_layer(state)
        state.failure_warning = latest_failure[1]
        state.failure_detail = latest_failure[2]
        state.last_failed_request_id = latest_failure[0]
        state.last_failed_layer_id = latest_failed_layer_id
    else:
        state.failure_warning = None
        state.failure_detail = None
        state.last_failed_request_id = None
        state.last_failed_layer_id = None
    return state


def mark_slow_live_graph_eq_requests(runtime: Any, *, now_ms: int | None = None) -> bool:
    state = live_graph_eq_state(runtime)
    if not state.pending_requests:
        state.slow_caution = False
        return False
    current_ms = _now_ms() if now_ms is None else int(now_ms)
    slow = any(
        current_ms >= request.due_at_ms + LIVE_EQ_SLOW_APPLY_MS
        for request in state.pending_requests.values()
    )
    state.slow_caution = slow
    return slow


def run_due_live_graph_eq_update(
    runtime: Any,
    *,
    now_ms: int | None = None,
) -> LiveGraphEqRequest | None:
    state = live_graph_eq_state(runtime)
    request = state.pending_request
    if request is None:
        return None
    current_ms = _now_ms() if now_ms is None else int(now_ms)
    if current_ms < request.due_at_ms:
        return None
    if request.mode_epoch != _mode_epoch(runtime):
        state.pending_requests.clear()
        state.invalidation_reason = "mode_epoch_changed"
        return None
    try:
        buffer = runtime.renderer.render_live_eq_layer_buffer(request.layer_id, request.settings)
    except (OSError, RuntimeError, ValueError) as exc:
        _record_failure(runtime, state, request, exc)
        return None
    if not apply_live_graph_eq_render_result(
        runtime,
        request_id=request.request_id,
        mode_epoch=request.mode_epoch,
        layer_id=request.layer_id,
        buffer=buffer,
        rendered_settings=request.settings,
    ):
        return None
    return request


def apply_live_graph_eq_render_result(
    runtime: Any,
    *,
    request_id: int,
    mode_epoch: int,
    layer_id: str,
    buffer: AudioBuffer,
    rendered_settings: AppSettings,
) -> bool:
    state = live_graph_eq_state(runtime)
    normalized_layer_id = _validate_layer_id(layer_id)
    request = state.pending_requests.get(normalized_layer_id)
    if (
        request is None
        or request.request_id != int(request_id)
        or request.mode_epoch != int(mode_epoch)
        or request.layer_id != normalized_layer_id
        or request.mode_epoch != _mode_epoch(runtime)
    ):
        state.invalidation_reason = "stale_result"
        return False

    player_snapshot = _capture_player_snapshot(runtime)
    previous_render_settings = getattr(runtime, "playback_render_settings", None)
    if previous_render_settings is not None:
        previous_render_settings = previous_render_settings.model_copy(deep=True)
    previous_confirmed_eq = state.confirmed_eq.get(normalized_layer_id)
    if previous_confirmed_eq is not None:
        previous_confirmed_eq = previous_confirmed_eq.model_copy(deep=True)
    try:
        runtime.player.set_layer_buffer(normalized_layer_id, buffer)
    except (OSError, RuntimeError, ValueError) as exc:
        _restore_player_snapshot(runtime, player_snapshot)
        _record_failure(runtime, state, request, exc)
        return False

    eq = rendered_settings.layers[normalized_layer_id].eq
    set_live_eq_state = getattr(runtime.player, "set_live_eq_state", None)
    if callable(set_live_eq_state):
        set_live_eq_state(normalized_layer_id, eq)
    current_render_settings = (
        getattr(runtime, "playback_render_settings", None) or rendered_settings
    )
    current_layer = current_render_settings.layers[normalized_layer_id]
    render_layers = {
        **current_render_settings.layers,
        normalized_layer_id: current_layer.model_copy(update={"eq": eq}),
    }
    runtime.playback_render_settings = current_render_settings.model_copy(
        update={"layers": render_layers},
        deep=True,
    )
    state.confirmed_eq[normalized_layer_id] = eq.model_copy(deep=True)
    state.pending_requests.pop(normalized_layer_id, None)
    state.slow_caution = False
    state.failed_layers.pop(normalized_layer_id, None)
    if state.failed_layers:
        latest_failed_layer_id, latest_failure = _latest_failed_layer(state)
        state.failure_warning = latest_failure[1]
        state.failure_detail = latest_failure[2]
        state.last_failed_request_id = latest_failure[0]
        state.last_failed_layer_id = latest_failed_layer_id
    else:
        state.failure_warning = None
        state.failure_detail = None
        state.last_failed_request_id = None
        state.last_failed_layer_id = None
    state.invalidation_reason = None
    state.last_applied_request_id = request.request_id
    state.last_applied_layer_id = normalized_layer_id
    state.applied_layers[normalized_layer_id] = request.request_id
    try:
        _persist_confirmed_eq_if_available(runtime, normalized_layer_id, eq)
    except (OSError, RuntimeError, ValueError) as exc:
        _restore_player_snapshot(runtime, player_snapshot)
        if previous_render_settings is not None:
            runtime.playback_render_settings = previous_render_settings
        if previous_confirmed_eq is None:
            state.confirmed_eq.pop(normalized_layer_id, None)
        else:
            state.confirmed_eq[normalized_layer_id] = previous_confirmed_eq
        _record_failure(runtime, state, request, exc)
        return False
    return True


def invalidate_live_graph_eq_requests(runtime: Any, reason: str) -> None:
    state = live_graph_eq_state(runtime)
    state.pending_requests.clear()
    state.failed_layers.clear()
    state.applied_layers.clear()
    state.slow_caution = False
    state.failure_warning = None
    state.failure_detail = None
    state.invalidation_reason = reason
    state.last_applied_request_id = None
    state.last_applied_layer_id = None
    state.last_failed_request_id = None
    state.last_failed_layer_id = None


def confirmed_live_graph_eq(runtime: Any, layer_id: str) -> EqSettings:
    normalized_layer_id = _validate_layer_id(layer_id)
    state = live_graph_eq_state(runtime)
    if normalized_layer_id in state.confirmed_eq:
        return state.confirmed_eq[normalized_layer_id].model_copy(deep=True)
    player_eq_states = getattr(runtime.player, "live_eq_states", None)
    if isinstance(player_eq_states, dict) and normalized_layer_id in player_eq_states:
        return player_eq_states[normalized_layer_id].model_copy(deep=True)
    settings = getattr(runtime, "playback_render_settings", None)
    if settings is not None:
        return settings.layers[normalized_layer_id].eq.model_copy(deep=True)
    return EqSettings()


def live_graph_eq_payload(runtime: Any) -> dict[str, Any]:
    state = live_graph_eq_state(runtime)
    request = state.pending_request
    status = "idle"
    if request is not None:
        status = "slow" if state.slow_caution else "pending"
    elif state.failed_layers or state.failure_warning:
        status = "failed"
    elif state.last_applied_request_id is not None:
        status = "applied"
    return {
        "status": status,
        "pending": request is not None,
        "pending_count": len(state.pending_requests),
        "pending_layers": sorted(state.pending_requests),
        "layer_id": (
            request.layer_id
            if request is not None
            else state.last_failed_layer_id
            if status == "failed"
            else state.last_applied_layer_id
        ),
        "request_id": (
            request.request_id
            if request is not None
            else state.last_failed_request_id
            if status == "failed"
            else state.last_applied_request_id
        ),
        "due_at_ms": request.due_at_ms if request is not None else None,
        "apply_delay_ms": LIVE_EQ_APPLY_DEBOUNCE_MS,
        "slow_caution": state.slow_caution,
        "failure_warning": state.failure_warning,
        "failure_detail": state.failure_detail,
        "failed_layers": sorted(state.failed_layers),
        "applied_layers": sorted(state.applied_layers),
        "invalidation_reason": state.invalidation_reason,
    }


def _persist_confirmed_eq_if_available(runtime: Any, layer_id: LayerId, eq: EqSettings) -> None:
    current = getattr(runtime, "settings_state", None)
    if current is None:
        settings_store = getattr(runtime, "settings_store", None)
        if settings_store is not None and callable(getattr(settings_store, "load", None)):
            current = settings_store.load()
    if current is None:
        return
    active_layers = {
        **current.active.layers,
        layer_id: current.active.layers[layer_id].model_copy(update={"eq": eq}),
    }
    active = current.active.model_copy(update={"layers": active_layers}, deep=True)
    state = SettingsState(active=active, draft=current.draft)
    settings_store = getattr(runtime, "settings_store", None)
    if settings_store is not None and callable(getattr(settings_store, "save", None)):
        state = settings_store.save(state)
    apply_settings_state = getattr(runtime, "apply_settings_state", None)
    if callable(apply_settings_state):
        apply_settings_state(state)
    else:
        runtime.settings_state = state
    mark_state_changed = getattr(runtime, "mark_state_changed", None)
    if callable(mark_state_changed):
        mark_state_changed()


def _record_failure(
    runtime: Any,
    state: LiveGraphEqState,
    request: LiveGraphEqRequest,
    exc: Exception,
) -> None:
    state.pending_requests.pop(request.layer_id, None)
    failure_detail = _failure_detail(runtime, request, exc)
    state.failed_layers[request.layer_id] = (
        request.request_id,
        LIVE_GRAPH_EQ_FAILURE_WARNING,
        failure_detail,
    )
    state.applied_layers.pop(request.layer_id, None)
    state.failure_warning = LIVE_GRAPH_EQ_FAILURE_WARNING
    state.failure_detail = failure_detail
    state.slow_caution = False
    state.last_failed_request_id = request.request_id
    state.last_failed_layer_id = request.layer_id
    runtime.transition_warning = LIVE_GRAPH_EQ_FAILURE_WARNING
    logger = getattr(runtime, "logger", None)
    log_event = getattr(logger, "log_event", None)
    if callable(log_event):
        payload = {
            "layer_id": request.layer_id,
            "request_id": request.request_id,
            "error": str(exc),
        }
        if state.failure_detail:
            payload["failure_detail"] = state.failure_detail
        log_event("settings.live_graph_eq_failed", payload)


def _latest_failed_layer(state: LiveGraphEqState) -> tuple[LayerId, tuple[int, str, str | None]]:
    return max(
        state.failed_layers.items(),
        key=lambda item: item[1][0],
    )


def _failure_detail(runtime: Any, request: LiveGraphEqRequest, exc: Exception) -> str | None:
    if not isinstance(exc, LiveEqSourceError):
        return None
    source_label = _source_label(request.layer_id)
    parts = []
    if exc.source_path is not None:
        parts.append(f"{source_label}가 없습니다: {_relative_path(runtime, exc.source_path)}")
    else:
        parts.append(f"{source_label}가 없습니다.")
    if exc.fallback_path is not None:
        fallback_path = _relative_path(runtime, exc.fallback_path)
        parts.append(f"fallback 확인: {fallback_path}")
        if exc.fallback_available:
            parts.append(f"fallback 사용됨: {fallback_path}")
        else:
            parts.append("fallback도 없어서 Live 적용을 중단했습니다.")
    return " ".join(parts)


def _source_label(layer_id: LayerId) -> str:
    if layer_id == "voice":
        return "Voice Stack source"
    return f"{layer_id.capitalize()} source"


def _relative_path(runtime: Any, path: Any) -> str:
    path_as_string = getattr(path, "as_posix", lambda: str(path))()
    root = getattr(getattr(runtime, "paths", None), "root", None)
    if root is None:
        return path_as_string
    try:
        return path.relative_to(root).as_posix()
    except (AttributeError, ValueError):
        return path_as_string


def _capture_player_snapshot(runtime: Any) -> Any:
    snapshot = getattr(runtime.player, "snapshot", None)
    if not callable(snapshot):
        return None
    try:
        return snapshot()
    except Exception:
        return None


def _restore_player_snapshot(runtime: Any, snapshot: Any) -> None:
    if snapshot is None:
        return
    restore = getattr(runtime.player, "restore", None)
    if not callable(restore):
        return
    try:
        restore(snapshot)
    except Exception:
        return


def _mode_epoch(runtime: Any) -> int:
    return int(getattr(runtime, "state_epoch", 0) or 0)


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _validate_layer_id(layer_id: str) -> LayerId:
    if layer_id not in {"low", "mid", "voice"}:
        msg = f"unknown layer_id: {layer_id}"
        raise ValueError(msg)
    return layer_id  # type: ignore[return-value]
