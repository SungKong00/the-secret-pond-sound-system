from __future__ import annotations

from dataclasses import dataclass

import pytest

from secret_pond.config import AppSettings, DeviceSettings
from secret_pond.services.device_switcher import DeviceSelectionError, apply_runtime_devices
from secret_pond.services.settings_store import SettingsState


@dataclass
class FakeDeviceComponent:
    device_id: str | None = None

    def set_device_id(self, device_id: str | None) -> None:
        self.device_id = device_id


class FakeOutputDevice(FakeDeviceComponent):
    def __init__(self, device_id: str | None = None, *, is_running: bool = False) -> None:
        super().__init__(device_id)
        self.is_running = is_running
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self.is_running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_running = False


class FakeController:
    def __init__(self, settings: AppSettings, *, is_recording: bool = False) -> None:
        self.settings = settings
        self.is_recording = is_recording

    def update_settings(self, settings: AppSettings) -> None:
        self.settings = settings


class FailingSaveSettingsStore:
    def __init__(self, state: SettingsState, error: Exception) -> None:
        self.state = state
        self.error = error
        self.saved_states: list[SettingsState] = []

    def load(self) -> SettingsState:
        return self.state

    def save(self, state: SettingsState) -> SettingsState:
        self.saved_states.append(state)
        raise self.error


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


class RuntimeHarness:
    def __init__(self, state: SettingsState, settings_store) -> None:
        self.settings_store = settings_store
        self.settings_state = state
        self.recorder = FakeDeviceComponent(state.active.devices.input_device_id)
        self.output = FakeOutputDevice(
            state.active.devices.output_device_id,
            is_running=True,
        )
        self.controller = FakeController(state.active)

    def apply_settings_state(self, state: SettingsState) -> None:
        self.controller.update_settings(state.active)
        self.settings_state = state


class FailingApplyRuntimeHarness(RuntimeHarness):
    def apply_settings_state(self, state: SettingsState) -> None:
        self.settings_state = state
        raise RuntimeError("controller update failed")


def test_apply_runtime_devices_rolls_back_runtime_devices_when_save_fails() -> None:
    active = AppSettings().model_copy(
        update={
            "devices": DeviceSettings(
                input_device_id="mic-1",
                output_device_id="speaker-1",
            )
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    runtime = RuntimeHarness(
        state,
        FailingSaveSettingsStore(state, OSError("settings save failed")),
    )

    with pytest.raises(DeviceSelectionError, match="settings save failed"):
        apply_runtime_devices(
            runtime,  # type: ignore[arg-type]
            DeviceSettings(input_device_id="mic-2", output_device_id="speaker-2"),
        )

    assert runtime.recorder.device_id == "mic-1"
    assert runtime.output.device_id == "speaker-1"
    assert runtime.output.is_running is True
    assert runtime.output.stop_calls == 2
    assert runtime.output.start_calls == 2
    assert runtime.controller.settings.devices.input_device_id == "mic-1"
    assert runtime.settings_state == state


def test_apply_runtime_devices_restores_saved_settings_when_runtime_apply_fails() -> None:
    active = AppSettings().model_copy(
        update={
            "devices": DeviceSettings(
                input_device_id="mic-1",
                output_device_id="speaker-1",
            )
        },
        deep=True,
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = FailingApplyRuntimeHarness(state, store)

    with pytest.raises(DeviceSelectionError, match="controller update failed"):
        apply_runtime_devices(
            runtime,  # type: ignore[arg-type]
            DeviceSettings(input_device_id="mic-2", output_device_id="speaker-2"),
        )

    assert runtime.recorder.device_id == "mic-1"
    assert runtime.output.device_id == "speaker-1"
    assert runtime.output.is_running is True
    assert store.state == state
    assert store.saved_states[-1] == state
    assert runtime.settings_state == state
    assert runtime.controller.settings.devices.input_device_id == "mic-1"
