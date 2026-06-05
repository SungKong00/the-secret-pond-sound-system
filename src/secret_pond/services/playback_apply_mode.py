from __future__ import annotations

from typing import Literal

from secret_pond.audio.layers import LAYER_IDS
from secret_pond.config import AppSettings, EqSettings
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths
from secret_pond.services.settings_store import SettingsState

PlaybackApplyMode = Literal["stable", "live"]

PLAYBACK_APPLY_MODES: set[str] = {"stable", "live"}


def apply_playback_apply_mode(
    runtime: SecretPondRuntime,
    mode: PlaybackApplyMode,
) -> SettingsState:
    current = runtime.settings_store.load()
    active = _with_playback_apply_mode(current.active, mode)
    draft = _with_playback_apply_mode(current.draft, mode)
    state = runtime.settings_store.save(SettingsState(active=active, draft=draft))
    if current.active.playback.apply_mode == "stable" and mode == "live":
        runtime.playback_render_settings = _eq_free_render_marker(active)
        _replace_stable_eq_artifacts(runtime, active)
        runtime.playback_render_settings = active
    elif current.active.playback.apply_mode == "live" and mode == "stable":
        _restore_stable_eq_artifacts(runtime)
        runtime.playback_render_settings = active
    runtime.apply_settings_state(state)
    _log_event_best_effort(runtime, "settings.playback_apply_mode_applied", {"mode": mode})
    return state


def parse_playback_apply_mode(value: object) -> PlaybackApplyMode:
    if value not in PLAYBACK_APPLY_MODES:
        msg = "mode must be stable or live"
        raise ValueError(msg)
    return value  # type: ignore[return-value]


def _with_playback_apply_mode(settings: AppSettings, mode: PlaybackApplyMode) -> AppSettings:
    return settings.model_copy(
        update={"playback": settings.playback.model_copy(update={"apply_mode": mode})},
        deep=True,
    )


def _eq_free_render_marker(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "layers": {
                layer_id: layer.model_copy(update={"eq": EqSettings()})
                for layer_id, layer in settings.layers.items()
            },
        },
        deep=True,
    )


def _replace_stable_eq_artifacts(runtime: SecretPondRuntime, settings: AppSettings) -> None:
    render_live_eq_layer_buffer = getattr(runtime.renderer, "render_live_eq_layer_buffer", None)
    set_layer_buffer = getattr(runtime.player, "set_layer_buffer", None)
    set_live_eq_state = getattr(runtime.player, "set_live_eq_state", None)
    if not callable(render_live_eq_layer_buffer) or not callable(set_layer_buffer):
        return

    for layer_id in LAYER_IDS:
        eq = settings.layers[layer_id].eq
        if eq == EqSettings():
            continue
        set_layer_buffer(layer_id, render_live_eq_layer_buffer(layer_id, settings))
        if callable(set_live_eq_state):
            set_live_eq_state(layer_id, eq)


def _restore_stable_eq_artifacts(runtime: SecretPondRuntime) -> None:
    reload_and_restart = getattr(runtime.player, "reload_and_restart", None)
    paths = getattr(runtime, "paths", None)
    if not callable(reload_and_restart) or paths is None:
        return
    try:
        reload_and_restart(rendered_layer_paths(paths))
    except FileNotFoundError:
        return


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict[str, object],
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
