from __future__ import annotations

from contextlib import suppress
from typing import Any

from secret_pond.audio.device_readiness import RecordingInputFormat, resolve_recording_input_format
from secret_pond.config import AppSettings, DeviceSettings
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_store import SettingsState


class DeviceSelectionError(RuntimeError):
    """Raised when a runtime device change cannot be safely applied."""


def device_settings_from_payload(
    current: DeviceSettings,
    payload: dict[str, Any],
) -> DeviceSettings:
    allowed = {"input_device_id", "output_device_id"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown device setting: {unknown[0]}")
    updates: dict[str, str | None] = {}
    for key in allowed:
        if key not in payload:
            continue
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a string or null")
        updates[key] = value or None
    return current.model_copy(update=updates)


def validate_draft_device_settings(active: AppSettings, draft: AppSettings) -> None:
    if draft.devices == active.devices:
        return
    raise ValueError("device changes must be applied from the System panel")


def apply_runtime_devices(
    runtime: SecretPondRuntime,
    devices: DeviceSettings,
) -> SettingsState:
    current = runtime.settings_store.load()
    previous_devices = current.active.devices
    input_changed = previous_devices.input_device_id != devices.input_device_id
    output_changed = previous_devices.output_device_id != devices.output_device_id
    previous_input_format = _stream_format(runtime.recorder)

    if input_changed and runtime.controller.is_recording:
        raise DeviceSelectionError("cannot change input device while recording")

    if not input_changed and not output_changed:
        return current

    _validate_changed_devices(
        runtime,
        devices,
        input_changed=input_changed,
        output_changed=output_changed,
    )

    was_output_running = runtime.output.is_running
    save_succeeded = False
    try:
        if output_changed and was_output_running:
            runtime.output.stop()
        next_active = current.active.model_copy(update={"devices": devices}, deep=True)
        if input_changed:
            _apply_recorder_input(runtime, next_active)
        if output_changed:
            _set_device_id(runtime.output, devices.output_device_id)
        if output_changed and was_output_running:
            runtime.output.start()
        next_draft = current.draft.model_copy(update={"devices": devices}, deep=True)
        next_state = runtime.settings_store.save(
            SettingsState(active=next_active, draft=next_draft),
        )
        save_succeeded = True
        runtime.apply_settings_state(next_state)
        return next_state
    except Exception as exc:
        _rollback_runtime_devices(
            runtime,
            previous_devices=previous_devices,
            input_changed=input_changed,
            output_changed=output_changed,
            restore_output=output_changed and was_output_running,
            previous_input_format=previous_input_format,
        )
        if save_succeeded:
            with suppress(Exception):
                previous_state = runtime.settings_store.save(current)
                runtime.settings_state = previous_state
                runtime.controller.update_settings(previous_state.active)
        raise DeviceSelectionError(str(exc)) from exc


def _validate_changed_devices(
    runtime: SecretPondRuntime,
    devices: DeviceSettings,
    *,
    input_changed: bool,
    output_changed: bool,
) -> None:
    if input_changed and devices.input_device_id is not None:
        selected_input = runtime.device_registry.validate_input(devices.input_device_id)
        if selected_input is None:
            raise DeviceSelectionError(f"input device is unavailable: {devices.input_device_id}")
    if output_changed and devices.output_device_id is not None:
        selected_output = runtime.device_registry.validate_output(devices.output_device_id)
        if selected_output is None:
            raise DeviceSelectionError(
                f"output device is unavailable: {devices.output_device_id}"
            )


def _set_device_id(component: Any, device_id: str | None) -> None:
    setter = getattr(component, "set_device_id", None)
    if not callable(setter):
        name = component.__class__.__name__
        raise DeviceSelectionError(f"{name} cannot change device while the app is running")
    setter(device_id)


def _apply_recorder_input(runtime: SecretPondRuntime, settings: Any) -> None:
    selected_input = runtime.device_registry.validate_input(settings.devices.input_device_id)
    input_format = resolve_recording_input_format(settings, selected_input)
    _set_device_id(runtime.recorder, settings.devices.input_device_id)
    _set_stream_format(runtime.recorder, input_format)


def _set_stream_format(component: Any, stream_format: RecordingInputFormat) -> None:
    setter = getattr(component, "set_stream_format", None)
    if callable(setter):
        setter(sample_rate=stream_format.sample_rate, channels=stream_format.channels)


def _stream_format(component: Any) -> RecordingInputFormat | None:
    sample_rate = getattr(component, "stream_sample_rate", None)
    channels = getattr(component, "stream_channels", None)
    if isinstance(sample_rate, int) and isinstance(channels, int):
        return RecordingInputFormat(sample_rate=sample_rate, channels=channels)
    return None


def _rollback_runtime_devices(
    runtime: SecretPondRuntime,
    *,
    previous_devices: DeviceSettings,
    input_changed: bool,
    output_changed: bool,
    restore_output: bool,
    previous_input_format: RecordingInputFormat | None,
) -> None:
    if runtime.output.is_running:
        with suppress(Exception):
            runtime.output.stop()
    if input_changed:
        with suppress(Exception):
            _set_device_id(runtime.recorder, previous_devices.input_device_id)
        if previous_input_format is not None:
            with suppress(Exception):
                _set_stream_format(runtime.recorder, previous_input_format)
    if output_changed:
        with suppress(Exception):
            _set_device_id(runtime.output, previous_devices.output_device_id)
    if restore_output:
        with suppress(Exception):
            runtime.output.start()
