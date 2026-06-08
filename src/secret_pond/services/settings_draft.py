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


LIVE_EQ_HOT_SWAP_WARNING = "Live EQ 전환을 적용하지 못했습니다. 기존 재생 상태를 유지합니다."


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
        render_settings = _apply_live_eq_buffers(runtime, render_settings, state.active)
        apply_live_player_layer_controls(
            runtime.player,
            previous=current.active,
            current=state.active,
            rendered_baseline=render_settings,
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
    if not getattr(runtime.player, "is_playing", False):
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
                "eq": draft_layer.eq,
            },
        )
    return active.model_copy(update={"layers": live_layers}, deep=True)


def _apply_live_eq_buffers(
    runtime: SecretPondRuntime,
    render_settings: AppSettings,
    active: AppSettings,
) -> AppSettings:
    next_render_layers = {}
    eq_changed = False
    for layer_id, render_layer in render_settings.layers.items():
        active_layer = active.layers[layer_id]
        if active_layer.eq == render_layer.eq:
            next_render_layers[layer_id] = render_layer
            continue
        eq_changed = True
        next_render_layers[layer_id] = render_layer.model_copy(update={"eq": active_layer.eq})

    if not eq_changed:
        _sync_live_eq_states(runtime, active)
        return render_settings

    next_render_settings = render_settings.model_copy(
        update={"layers": next_render_layers},
        deep=True,
    )
    player_snapshot = _capture_player_snapshot(runtime)
    for layer_id, render_layer in next_render_layers.items():
        if render_settings.layers[layer_id].eq == render_layer.eq:
            continue
        try:
            runtime.player.set_layer_buffer(
                layer_id,
                runtime.renderer.render_live_eq_layer_buffer(layer_id, next_render_settings),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            _restore_player_snapshot(runtime, player_snapshot)
            runtime.transition_warning = LIVE_EQ_HOT_SWAP_WARNING
            _log_event_best_effort(
                runtime,
                "settings.live_eq_hot_swap_failed",
                {
                    "layer_id": layer_id,
                    "error": str(exc),
                },
            )
            return render_settings
    _sync_live_eq_states(runtime, next_render_settings)
    runtime.playback_render_settings = next_render_settings
    return next_render_settings


def _capture_player_snapshot(runtime: SecretPondRuntime):
    snapshot = getattr(runtime.player, "snapshot", None)
    if not callable(snapshot):
        return None
    try:
        return snapshot()
    except Exception:
        return None


def _restore_player_snapshot(runtime: SecretPondRuntime, snapshot) -> None:
    if snapshot is None:
        return
    restore = getattr(runtime.player, "restore", None)
    if not callable(restore):
        return
    try:
        restore(snapshot)
    except Exception:
        return


def _log_event_best_effort(runtime: SecretPondRuntime, event_type: str, payload: dict) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return


def _sync_live_eq_states(runtime: SecretPondRuntime, settings: AppSettings) -> None:
    set_live_eq_state = getattr(runtime.player, "set_live_eq_state", None)
    player_eq_states = getattr(runtime.player, "live_eq_states", None)
    if not callable(set_live_eq_state) or not isinstance(player_eq_states, dict):
        return

    for layer_id, layer in settings.layers.items():
        if player_eq_states.get(layer_id) == layer.eq:
            continue
        set_live_eq_state(layer_id, layer.eq)
