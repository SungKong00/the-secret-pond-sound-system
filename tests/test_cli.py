from __future__ import annotations

import json
from pathlib import Path

import pytest

from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.cli import (
    build_doctor_report,
    check_native_dependencies,
    check_write_access,
    doctor_readiness_failures,
    doctor_report_to_payload,
    run_doctor,
)
from secret_pond.config import AppSettings, AudioFormatSettings, DeviceSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_store import SettingsState, SettingsStore


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
                id="mic-1",
                name="48k Mic",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
            ),
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
    assert doctor_readiness_failures(report) == [
        f"Missing source: {paths.low_source}",
        f"Missing source: {paths.mid_source}",
    ]


def test_doctor_report_payload_is_json_ready(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    registry = FakeDeviceRegistry(
        devices=[
            AudioDeviceInfo(
                id="mic-1",
                name="USB Mic",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
            ),
            AudioDeviceInfo(
                id="speaker-1",
                name="USB Speaker",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=48_000,
            ),
        ]
    )
    paths.ensure_directories()
    paths.low_source.write_bytes(b"low")
    paths.mid_source.write_bytes(b"mid")

    report = build_doctor_report(paths, registry, AppSettings())
    payload = doctor_report_to_payload(report)

    assert payload["schema_version"] == 1
    assert payload["ready"] is True
    assert payload["root"] == str(tmp_path)
    assert payload["settings"]["sample_rate"] == 48_000
    assert payload["settings"]["channels"] == 2
    assert payload["input_devices"][0]["id"] == "mic-1"
    assert payload["selected_input_device"]["name"] == "USB Mic"
    assert payload["selected_output_device"]["name"] == "USB Speaker"
    assert payload["missing_sources"] == []
    assert payload["warnings"] == []
    assert json.loads(json.dumps(payload)) == payload


def test_doctor_readiness_failures_include_missing_sources_and_devices(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    report = build_doctor_report(paths, FakeDeviceRegistry(devices=[]), AppSettings())

    failures = doctor_readiness_failures(report)

    assert "No input device is available." in failures
    assert "No output device is available." in failures
    assert f"Missing source: {paths.low_source}" in failures
    assert f"Missing source: {paths.mid_source}" in failures


def test_run_doctor_strict_returns_failure_for_not_ready_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run_doctor(tmp_path, strict=True, registry=FakeDeviceRegistry(devices=[]))

    assert result == 1
    assert "Readiness failure: No input device is available." in capsys.readouterr().out


def test_run_doctor_json_outputs_parseable_failure_payload_when_registry_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class BrokenRegistry(FakeDeviceRegistry):
        def list_input_devices(self) -> list[AudioDeviceInfo]:
            raise RuntimeError("host audio unavailable")

    result = run_doctor(tmp_path, output_json=True, registry=BrokenRegistry(devices=[]))

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["schema_version"] == 1
    assert payload["input_devices"] == []
    assert payload["output_devices"] == []
    assert payload["warnings"] == []
    assert payload["readiness_failures"] == [
        "Audio devices: unavailable (host audio unavailable)"
    ]
    assert payload["errors"] == ["Audio devices: unavailable (host audio unavailable)"]
    assert payload["settings"]["sample_rate"] == 48_000


def test_run_doctor_json_reports_normal_readiness_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run_doctor(tmp_path, output_json=True, registry=FakeDeviceRegistry(devices=[]))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["errors"] == []
    assert "No input device is available." in payload["readiness_failures"]
    assert "No output device is available." in payload["readiness_failures"]
    assert payload["settings"]["voice_stack_loop_seconds"] == 60


def test_run_doctor_json_strict_returns_failure_for_not_ready_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run_doctor(
        tmp_path,
        output_json=True,
        strict=True,
        registry=FakeDeviceRegistry(devices=[]),
    )

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["errors"] == []
    assert "No input device is available." in payload["readiness_failures"]


def test_run_doctor_json_classifies_settings_load_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    paths.settings_file.write_text("{not-json", encoding="utf-8")

    result = run_doctor(tmp_path, output_json=True, registry=FakeDeviceRegistry(devices=[]))

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["settings"] is None
    assert payload["errors"] == [
        "Settings: unavailable (settings file contains invalid JSON)"
    ]
    assert payload["readiness_failures"] == [
        "Settings: unavailable (settings file contains invalid JSON)"
    ]


def test_run_doctor_uses_startup_effective_saved_settings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    paths.low_source.write_bytes(b"low")
    paths.mid_source.write_bytes(b"mid")
    active = AppSettings(audio=AudioFormatSettings(sample_rate=48_000, channels=2))
    draft = active.model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=44_100, channels=1),
            "devices": DeviceSettings(input_device_id="mic-2", output_device_id="speaker-2"),
        },
        deep=True,
    )
    SettingsStore(paths).save(SettingsState(active=active, draft=draft))
    registry = FakeDeviceRegistry(
        devices=[
            AudioDeviceInfo(
                id="mic-2",
                name="Configured Mic",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=44_100,
            ),
            AudioDeviceInfo(
                id="speaker-2",
                name="Configured Speaker",
                kind="output",
                max_input_channels=0,
                max_output_channels=1,
                default_sample_rate=44_100,
            ),
        ]
    )

    result = run_doctor(tmp_path, output_json=True, registry=registry)

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["settings"]["sample_rate"] == 44_100
    assert payload["settings"]["channels"] == 1
    assert payload["settings"]["input_device_id"] == "mic-2"
    assert payload["selected_input_device"]["name"] == "Configured Mic"
    assert payload["selected_output_device"]["name"] == "Configured Speaker"
