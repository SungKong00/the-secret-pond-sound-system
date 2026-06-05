from __future__ import annotations

from secret_pond.config import AppSettings
from secret_pond.services.device_switcher import validate_draft_device_settings
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_store import SettingsState


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
    active_snapshot = _settings_copy(current.active)
    try:
        saved_state = runtime.settings_store.save(
            SettingsState(active=active_snapshot, draft=_settings_copy(draft))
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SettingsDraftUpdateError(str(exc)) from exc
    state = SettingsState(active=_settings_copy(current.active), draft=saved_state.draft)
    runtime.settings_state = state
    return state


def _settings_copy(settings: AppSettings) -> AppSettings:
    return settings.model_copy(deep=True)
