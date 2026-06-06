from __future__ import annotations

from dataclasses import dataclass

import pytest

from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.config import AppSettings, AudioFormatSettings, DeviceSettings
from secret_pond.services.device_switcher import (
    DeviceSelectionError,
    apply_runtime_devices,
    device_settings_from_payload,
    validate_draft_device_settings,
)
from secret_pond.services.settings_store import SettingsState


@dataclass
class FakeDeviceComponent:
    device_id: str | None = None

    def set_device_id(self, device_id: str | None) -> None:
        self.device_id = device_id


class FakeRecorderDevice(FakeDeviceComponent):
    def __init__(
        self,
        device_id: str | None = None,
        *,
        stream_sample_rate: int = 48_000,
        stream_channels: int = 2,
    ) -> None:
        super().__init__(device_id)
        self.stream_sample_rate = stream_sample_rate
        self.stream_channels = stream_channels

    def set_stream_format(self, *, sample_rate: int, channels: int) -> None:
        self.stream_sample_rate = sample_rate
        self.stream_channels = channels


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
    def __init__(
        self,
        state: SettingsState,
        settings_store,
        *,
        devices: list[AudioDeviceInfo] | None = None,
    ) -> None:
        self.settings_store = settings_store
        self.settings_state = state
        self.recorder = FakeRecorderDevice(state.active.devices.input_device_id)
        self.output = FakeOutputDevice(
            state.active.devices.output_device_id,
            is_running=True,
        )
        self.controller = FakeController(state.active)
        self.device_registry = FakeDeviceRegistry(
            devices
            or [
                AudioDeviceInfo(
                    id="mic-1",
                    name="Stereo Mic",
                    kind="input",
                    max_input_channels=2,
                    max_output_channels=0,
                    default_sample_rate=48_000,
                ),
                AudioDeviceInfo(
                    id="mic-2",
                    name="Headset Mic",
                    kind="input",
                    max_input_channels=1,
                    max_output_channels=0,
                    default_sample_rate=44_100,
                ),
                AudioDeviceInfo(
                    id="speaker-1",
                    name="Speakers",
                    kind="output",
                    max_input_channels=0,
                    max_output_channels=2,
                    default_sample_rate=48_000,
                ),
                AudioDeviceInfo(
                    id="speaker-2",
                    name="Headphones",
                    kind="output",
                    max_input_channels=0,
                    max_output_channels=2,
                    default_sample_rate=48_000,
                ),
            ]
        )

    def apply_settings_state(self, state: SettingsState) -> None:
        self.controller.update_settings(state.active)
        self.settings_state = state


class FailingApplyRuntimeHarness(RuntimeHarness):
    def apply_settings_state(self, state: SettingsState) -> None:
        self.settings_state = state
        raise RuntimeError("controller update failed")


def test_device_settings_from_payload_rejects_unknown_keys_and_normalizes_empty_values() -> None:
    current = DeviceSettings(input_device_id="mic-1", output_device_id="speaker-1")

    assert device_settings_from_payload(current, {"input_device_id": ""}) == DeviceSettings(
        input_device_id=None,
        output_device_id="speaker-1",
    )
    assert device_settings_from_payload(current, {"output_device_id": None}) == DeviceSettings(
        input_device_id="mic-1",
        output_device_id=None,
    )

    with pytest.raises(ValueError, match="unknown device setting: latency"):
        device_settings_from_payload(current, {"latency": 0.1})

    with pytest.raises(ValueError, match="input_device_id must be a string or null"):
        device_settings_from_payload(current, {"input_device_id": 123})


def test_validate_draft_device_settings_rejects_device_changes_outside_system_panel() -> None:
    active = AppSettings(devices=DeviceSettings(input_device_id="mic-1"))
    same_devices_draft = active.model_copy(update={"audio": AudioFormatSettings(channels=1)})
    changed_devices_draft = active.model_copy(
        update={"devices": DeviceSettings(input_device_id="mic-2")},
        deep=True,
    )

    validate_draft_device_settings(active, same_devices_draft)

    with pytest.raises(ValueError, match="device changes must be applied from the System panel"):
        validate_draft_device_settings(active, changed_devices_draft)


def test_apply_runtime_devices_rejects_unavailable_output_before_mutating_runtime() -> None:
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
    runtime = RuntimeHarness(state, store)

    with pytest.raises(DeviceSelectionError, match="output device is unavailable: missing-speaker"):
        apply_runtime_devices(  # type: ignore[arg-type]
            runtime,
            DeviceSettings(input_device_id="mic-1", output_device_id="missing-speaker"),
        )

    assert runtime.recorder.device_id == "mic-1"
    assert runtime.output.device_id == "speaker-1"
    assert runtime.output.is_running is True
    assert runtime.output.stop_calls == 0
    assert runtime.output.start_calls == 0
    assert store.saved_states == []
    assert runtime.settings_state == state


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


def test_apply_runtime_devices_updates_recorder_stream_format_for_new_input() -> None:
    active = AppSettings(
        audio=AudioFormatSettings(sample_rate=48_000, channels=2),
        devices=DeviceSettings(input_device_id="mic-1", output_device_id="speaker-1"),
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(state, store)

    next_state = apply_runtime_devices(  # type: ignore[arg-type]
        runtime,
        DeviceSettings(input_device_id="mic-2", output_device_id="speaker-1"),
    )

    assert next_state.active.devices.input_device_id == "mic-2"
    assert runtime.recorder.device_id == "mic-2"
    assert runtime.recorder.stream_sample_rate == 44_100
    assert runtime.recorder.stream_channels == 1


def test_apply_runtime_devices_saves_stable_ids_but_uses_portaudio_stream_indices() -> None:
    active = AppSettings(
        audio=AudioFormatSettings(sample_rate=48_000, channels=2),
        devices=DeviceSettings(input_device_id="input:old", output_device_id="output:old"),
    )
    state = SettingsState(active=active, draft=active)
    store = MemorySettingsStore(state)
    runtime = RuntimeHarness(
        state,
        store,
        devices=[
            AudioDeviceInfo(
                id="input:old",
                name="Old Mic",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
                portaudio_index=4,
            ),
            AudioDeviceInfo(
                id="input:usb-mic",
                name="USB Mic",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
                portaudio_index=7,
            ),
            AudioDeviceInfo(
                id="output:old",
                name="Old Speakers",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=48_000,
                portaudio_index=5,
            ),
            AudioDeviceInfo(
                id="output:usb-speakers",
                name="USB Speakers",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=48_000,
                portaudio_index=8,
            ),
        ],
    )

    next_state = apply_runtime_devices(  # type: ignore[arg-type]
        runtime,
        DeviceSettings(input_device_id="input:usb-mic", output_device_id="output:usb-speakers"),
    )

    assert next_state.active.devices.input_device_id == "input:usb-mic"
    assert next_state.active.devices.output_device_id == "output:usb-speakers"
    assert runtime.recorder.device_id == "7"
    assert runtime.output.device_id == "8"
