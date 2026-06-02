from __future__ import annotations

from pathlib import Path

from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.cli import build_doctor_report, check_native_dependencies, check_write_access
from secret_pond.config import AppSettings, AudioFormatSettings
from secret_pond.paths import ProjectPaths


def test_check_write_access_creates_and_removes_probe_file(tmp_path: Path) -> None:
    assert check_write_access(tmp_path) is True
    assert not any(tmp_path.iterdir())


def test_check_native_dependencies_reports_required_audio_packages() -> None:
    result = check_native_dependencies()

    assert result["numpy"] is True
    assert result["sounddevice"] is True
    assert result["soundfile"] is True
    assert result["scipy"] is True
    assert result["pedalboard"] is True


def test_doctor_report_flags_output_device_channel_mismatch(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    registry = FakeDeviceRegistry(
        devices=[
            AudioDeviceInfo(
                id="speaker-1",
                name="Mono Speaker",
                kind="output",
                max_input_channels=0,
                max_output_channels=1,
                default_sample_rate=48_000,
            )
        ]
    )
    settings = AppSettings(audio=AudioFormatSettings(sample_rate=48_000, channels=2))

    report = build_doctor_report(paths, registry, settings)

    assert report.data_writable is True
    assert report.output_device is not None
    assert "Selected output supports 1 channels, but settings request 2." in report.warnings


def test_doctor_report_flags_sample_rate_mismatch(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    registry = FakeDeviceRegistry(
        devices=[
            AudioDeviceInfo(
                id="speaker-1",
                name="44.1k Speaker",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=44_100,
            )
        ]
    )
    settings = AppSettings(audio=AudioFormatSettings(sample_rate=48_000, channels=2))

    report = build_doctor_report(paths, registry, settings)

    assert (
        "Selected output default sample rate is 44100, but settings request 48000."
        in report.warnings
    )
