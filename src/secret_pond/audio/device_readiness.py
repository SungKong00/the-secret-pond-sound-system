from __future__ import annotations

from dataclasses import dataclass

from secret_pond.audio.devices import AudioDeviceInfo
from secret_pond.config import AppSettings

_PREFERRED_RECORDING_INPUT_CHANNELS = 1


@dataclass(frozen=True)
class RecordingInputFormat:
    sample_rate: int
    channels: int


def resolve_recording_input_format(
    settings: AppSettings,
    input_device: AudioDeviceInfo | None,
) -> RecordingInputFormat:
    """Choose the host input format before converting takes to app-canonical audio."""
    sample_rate = (
        input_device.default_sample_rate
        if input_device and input_device.default_sample_rate
        else settings.audio.sample_rate
    )
    channels = _recording_input_channels(input_device)
    return RecordingInputFormat(sample_rate=sample_rate, channels=channels)


def build_device_warnings(
    input_device: AudioDeviceInfo | None,
    output_device: AudioDeviceInfo | None,
    settings: AppSettings,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(build_input_device_failures(input_device))
    warnings.extend(build_output_device_failures(output_device, settings))
    return warnings


def build_input_device_failures(input_device: AudioDeviceInfo | None) -> list[str]:
    if input_device and input_device.max_input_channels < 1:
        return ["Selected input device does not expose an input channel."]
    return []


def build_output_device_failures(
    output_device: AudioDeviceInfo | None,
    settings: AppSettings,
) -> list[str]:
    failures: list[str] = []
    if output_device and output_device.max_output_channels < settings.audio.channels:
        failures.append(
            "Selected output supports "
            f"{output_device.max_output_channels} channels, "
            f"but settings request {settings.audio.channels}."
        )
    if output_device and output_device.default_sample_rate not in (
        None,
        settings.audio.sample_rate,
    ):
        failures.append(
            "Selected output default sample rate is "
            f"{output_device.default_sample_rate}, "
            f"but settings request {settings.audio.sample_rate}."
        )
    return failures


def _recording_input_channels(input_device: AudioDeviceInfo | None) -> int:
    if input_device is None:
        return _PREFERRED_RECORDING_INPUT_CHANNELS
    if input_device.max_input_channels < 1:
        return _PREFERRED_RECORDING_INPUT_CHANNELS
    return min(_PREFERRED_RECORDING_INPUT_CHANNELS, input_device.max_input_channels)
