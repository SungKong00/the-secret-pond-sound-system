from __future__ import annotations

from typing import Any

from secret_pond.audio.device_readiness import build_device_warnings
from secret_pond.audio.devices import AudioDeviceInfo, AudioDeviceRegistry
from secret_pond.config import AppSettings


def device_inventory_payload(
    registry: AudioDeviceRegistry,
    settings: AppSettings,
) -> dict[str, Any]:
    input_devices = registry.list_input_devices()
    output_devices = registry.list_output_devices()
    selected_input = registry.validate_input(settings.devices.input_device_id)
    selected_output = registry.validate_output(settings.devices.output_device_id)
    return {
        "input_devices": [device_payload(device) for device in input_devices],
        "output_devices": [device_payload(device) for device in output_devices],
        "selected_input_device": device_payload(selected_input),
        "selected_output_device": device_payload(selected_output),
        "warnings": device_inventory_warnings(selected_input, selected_output, settings),
    }


def device_payload(device: AudioDeviceInfo | None) -> dict[str, Any] | None:
    if device is None:
        return None
    return {
        "id": device.id,
        "name": device.name,
        "kind": device.kind,
        "max_input_channels": device.max_input_channels,
        "max_output_channels": device.max_output_channels,
        "default_sample_rate": device.default_sample_rate,
        "host_api_name": device.host_api_name,
    }


def device_inventory_warnings(
    input_device: AudioDeviceInfo | None,
    output_device: AudioDeviceInfo | None,
    settings: AppSettings,
) -> list[str]:
    warnings: list[str] = []
    if settings.devices.input_device_id is not None and input_device is None:
        warnings.append("Configured input device is unavailable.")
    if settings.devices.output_device_id is not None and output_device is None:
        warnings.append("Configured output device is unavailable.")
    warnings.extend(build_device_warnings(input_device, output_device, settings))
    return warnings
