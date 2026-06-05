from __future__ import annotations

from typing import Literal

from secret_pond.config import AppSettings, EqSettings
from secret_pond.services.runtime import SecretPondRuntime
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


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict[str, object],
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
