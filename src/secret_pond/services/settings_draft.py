from __future__ import annotations

from secret_pond.config import AppSettings
from secret_pond.services.device_switcher import validate_draft_device_settings
from secret_pond.services.player_settings import apply_live_player_layer_controls
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_changes import classify_settings_change
from secret_pond.services.settings_store import SettingsState
from secret_pond.services.voice_raw_preview import prepare_voice_raw_preview


class SettingsDraftUpdateError(RuntimeError):
    """Raised when a draft settings update cannot be persisted."""


class SettingsDraftValidationError(ValueError):
    """Raised when a draft settings update violates the web draft contract."""


def update_draft_settings(
    runtime: SecretPondRuntime,
    draft: AppSettings,
    *,
    current: SettingsState,
) -> SettingsState:
    try:
        validate_draft_device_settings(current.active, draft)
    except ValueError as exc:
        raise SettingsDraftValidationError(str(exc)) from exc
    live_preview_reprocess_needed = _live_preview_reprocess_needed(runtime, current, draft)
    active_snapshot = _active_settings_for_draft_update(current.active, draft)
    try:
        saved_state = runtime.settings_store.save(
            SettingsState(active=_settings_copy(active_snapshot), draft=_settings_copy(draft))
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SettingsDraftUpdateError(str(exc)) from exc
    state = SettingsState(active=_settings_copy(active_snapshot), draft=saved_state.draft)
    if current.active.playback.apply_mode == "live":
        render_settings = _playback_render_settings(runtime, current)
        apply_live_player_layer_controls(
            runtime.player,
            previous=render_settings,
            current=state.active,
        )
        runtime.apply_settings_state(state)
        if live_preview_reprocess_needed:
            prepare_voice_raw_preview(runtime, runtime.voice_raw_preview_path, state.draft)
    else:
        runtime.settings_state = state
    return state


def _settings_copy(settings: AppSettings) -> AppSettings:
    return settings.model_copy(deep=True)


def _playback_render_settings(
    runtime: SecretPondRuntime,
    current: SettingsState,
) -> AppSettings:
    render_settings = getattr(runtime, "playback_render_settings", None)
    if render_settings is None:
        render_settings = _settings_copy(current.active)
        runtime.playback_render_settings = render_settings
    return render_settings


def _live_preview_reprocess_needed(
    runtime: SecretPondRuntime,
    current: SettingsState,
    draft: AppSettings,
) -> bool:
    if current.active.playback.apply_mode != "live":
        return False
    if getattr(runtime, "voice_raw_preview_path", None) is None:
        return False
    change = classify_settings_change(current.draft, draft)
    return bool(change.live_preview_reprocessable_fields)


def _active_settings_for_draft_update(active: AppSettings, draft: AppSettings) -> AppSettings:
    if active.playback.apply_mode != "live":
        return _settings_copy(active)

    live_layers = {}
    for layer_id, active_layer in active.layers.items():
        draft_layer = draft.layers[layer_id]
        live_layers[layer_id] = active_layer.model_copy(
            update={
                "enabled": draft_layer.enabled,
                "volume_db": draft_layer.volume_db,
            },
        )
    return active.model_copy(update={"layers": live_layers}, deep=True)
