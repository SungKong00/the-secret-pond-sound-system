from __future__ import annotations

from typing import Literal

from secret_pond.config import AppSettings
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_store import SettingsState

VoiceStackMode = Literal["live_ephemeral", "test_library"]

VOICE_STACK_MODES: set[str] = {"live_ephemeral", "test_library"}


class StorageModeChangeError(RuntimeError):
    """Raised when the recording storage mode cannot be changed now."""


def apply_voice_stack_mode(
    runtime: SecretPondRuntime,
    mode: VoiceStackMode,
) -> SettingsState:
    if runtime.controller.is_recording:
        raise StorageModeChangeError("cannot change storage mode while recording")

    current = runtime.settings_store.load()
    active = _with_voice_stack_mode(current.active, mode)
    draft = _with_voice_stack_mode(current.draft, mode)
    state = runtime.settings_store.save(SettingsState(active=active, draft=draft))
    runtime.apply_settings_state(state)
    _log_event_best_effort(runtime, "settings.storage_mode_applied", {"mode": mode})
    return state


def parse_voice_stack_mode(value: object) -> VoiceStackMode:
    if value not in VOICE_STACK_MODES:
        msg = "mode must be live_ephemeral or test_library"
        raise ValueError(msg)
    return value  # type: ignore[return-value]


def _with_voice_stack_mode(settings: AppSettings, mode: VoiceStackMode) -> AppSettings:
    return settings.model_copy(
        update={"voice_stack": settings.voice_stack.model_copy(update={"mode": mode})},
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
