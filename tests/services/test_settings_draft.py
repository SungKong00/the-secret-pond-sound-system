from __future__ import annotations

import pytest

from secret_pond.config import AppSettings, AudioFormatSettings, DeviceSettings
from secret_pond.services.settings_draft import (
    SettingsDraftUpdateError,
    SettingsDraftValidationError,
    update_draft_settings,
)
from secret_pond.services.settings_store import SettingsState


class MemorySettingsStore:
    def __init__(self, state: SettingsState) -> None:
        self.state = state
        self.saved_states: list[SettingsState] = []

    def save(self, state: SettingsState) -> SettingsState:
        self.saved_states.append(state)
        self.state = state
        return state


class FailingSaveSettingsStore:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.saved_states: list[SettingsState] = []

    def save(self, state: SettingsState) -> SettingsState:
        self.saved_states.append(state)
        raise self.error


class RuntimeHarness:
    def __init__(self, state: SettingsState, settings_store) -> None:
        self.settings_state = state
        self.settings_store = settings_store


def test_update_draft_settings_saves_draft_without_changing_active() -> None:
    active = AppSettings()
    draft = active.model_copy(update={"audio": AudioFormatSettings(channels=1)}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    result = update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert result.active == active
    assert result.draft.audio.channels == 1
    assert store.saved_states == [result]
    assert runtime.settings_state == result


def test_update_draft_settings_raises_validation_error_for_device_changes() -> None:
    active = AppSettings()
    draft = active.model_copy(
        update={"devices": DeviceSettings(input_device_id="mic-2")},
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    with pytest.raises(SettingsDraftValidationError, match="System panel"):
        update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert store.saved_states == []
    assert runtime.settings_state == state


def test_update_draft_settings_keeps_save_failures_as_update_errors() -> None:
    active = AppSettings()
    draft = active.model_copy(update={"audio": AudioFormatSettings(channels=1)}, deep=True)
    state = SettingsState(active=active, draft=active)
    store = FailingSaveSettingsStore(OSError("settings save failed"))
    runtime = RuntimeHarness(state, store)

    with pytest.raises(SettingsDraftUpdateError, match="settings save failed"):
        update_draft_settings(runtime, draft, current=state)  # type: ignore[arg-type]

    assert len(store.saved_states) == 1
    assert runtime.settings_state == state
