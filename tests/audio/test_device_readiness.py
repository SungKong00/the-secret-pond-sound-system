from __future__ import annotations

from secret_pond.audio.device_readiness import (
    build_device_warnings,
    resolve_recording_input_format,
)
from secret_pond.audio.devices import AudioDeviceInfo
from secret_pond.config import AppSettings, AudioFormatSettings


def mono_input_device(default_sample_rate: int = 44_100) -> AudioDeviceInfo:
    return AudioDeviceInfo(
        id="mic-1",
        name="Headset Microphone",
        kind="input",
        max_input_channels=1,
        max_output_channels=0,
        default_sample_rate=default_sample_rate,
    )


def stereo_output_device() -> AudioDeviceInfo:
    return AudioDeviceInfo(
        id="speaker-1",
        name="Speakers",
        kind="output",
        max_input_channels=0,
        max_output_channels=2,
        default_sample_rate=48_000,
    )


def test_recording_input_format_uses_mono_device_format_for_stereo_app_audio() -> None:
    settings = AppSettings(audio=AudioFormatSettings(sample_rate=48_000, channels=2))

    stream_format = resolve_recording_input_format(settings, mono_input_device())

    assert stream_format.sample_rate == 44_100
    assert stream_format.channels == 1


def test_device_warnings_do_not_flag_supported_mono_input_as_channel_mismatch() -> None:
    settings = AppSettings(audio=AudioFormatSettings(sample_rate=48_000, channels=2))

    warnings = build_device_warnings(
        input_device=mono_input_device(),
        output_device=stereo_output_device(),
        settings=settings,
    )

    assert warnings == []
