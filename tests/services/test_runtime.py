from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.audio.recorder import FakeRecorder
from secret_pond.config import AppSettings, AudioFormatSettings, DeviceSettings, VoiceStackSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.runtime import build_runtime
from secret_pond.services.settings_store import SettingsState, SettingsStore


def small_settings() -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        voice_stack=VoiceStackSettings(loop_seconds=1),
    )


def fake_recorder() -> FakeRecorder:
    samples = np.ones((4, 2), dtype=np.float32) * 0.05
    return FakeRecorder(AudioBuffer(samples=samples, sample_rate=8_000))


class FakeOutput:
    is_running = False
    latest_status = None
    statuses: list = []
    latest_error = None

    def start(self) -> None:
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False


class FailingDeviceRegistry:
    def list_input_devices(self):
        raise RuntimeError("host audio unavailable")

    def list_output_devices(self):
        raise RuntimeError("host audio unavailable")

    def validate_input(self, device_id):
        raise RuntimeError("host audio unavailable")

    def validate_output(self, device_id):
        raise RuntimeError("host audio unavailable")


class FailingStartupLogger:
    def log_event(self, event_type, payload=None):
        raise OSError("log write failed")


def fake_device_registry() -> FakeDeviceRegistry:
    return FakeDeviceRegistry(
        [
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


def test_build_runtime_wires_services_with_injected_audio_boundaries(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    player = LayeredLoopPlayer()

    output = FakeOutput()

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        player=player,
        output=output,
        device_registry=fake_device_registry(),
    )

    assert runtime.paths == paths
    assert runtime.settings_state.active == settings
    assert runtime.controller.settings == settings
    assert runtime.player is player
    assert runtime.output is output
    assert runtime.participants.get_count() == 0


def test_build_runtime_logs_startup_diagnostics(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))

    build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
    )

    events = paths.event_log_file.read_text(encoding="utf-8").splitlines()
    assert len(events) == 1
    event = json.loads(events[0])
    assert event["event_type"] == "system.startup"
    payload = event["payload"]
    assert payload["data_dir"] == str(paths.data_dir)
    assert payload["requested_sample_rate"] == 8_000
    assert payload["requested_channels"] == 2
    assert payload["configured_input_device_id"] is None
    assert payload["configured_output_device_id"] is None
    assert payload["selected_input_device"]["name"] == "USB Mic"
    assert payload["selected_output_device"]["name"] == "USB Speaker"
    assert payload["actual_input_sample_rate"] is None
    assert payload["actual_input_channels"] is None
    assert payload["actual_output_sample_rate"] is None
    assert payload["actual_output_channels"] is None
    assert payload["device_error"] is None
    assert payload["os_name"]
    assert payload["python_version"]


def test_build_runtime_logs_startup_device_error_without_failing(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=FailingDeviceRegistry(),
    )

    assert runtime.paths == paths
    event = json.loads(paths.event_log_file.read_text(encoding="utf-8"))
    assert event["event_type"] == "system.startup"
    assert event["payload"]["selected_input_device"] is None
    assert event["payload"]["selected_output_device"] is None
    assert event["payload"]["device_error"] == "host audio unavailable"


def test_build_runtime_ignores_startup_log_write_failure(tmp_path: Path) -> None:
    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
        startup_logger=FailingStartupLogger(),
    )

    assert runtime.paths == ProjectPaths(tmp_path)


def test_build_runtime_initializes_voice_stack_from_active_settings(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))

    build_runtime(tmp_path, recorder=fake_recorder(), device_registry=fake_device_registry())

    assert paths.voice_stack_raw.exists()
    assert paths.voice_manifest.exists()


def test_build_runtime_creates_default_settings_file_when_missing(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        device_registry=fake_device_registry(),
    )

    assert paths.settings_file.exists()
    assert runtime.settings_state.active == AppSettings()
    assert runtime.settings_state.draft == AppSettings()


def test_build_runtime_promotes_restart_required_draft_settings_on_startup(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    active = small_settings()
    draft = active.model_copy(
        update={
            "devices": DeviceSettings(
                input_device_id="mic-2",
                output_device_id="speaker-2",
            )
        },
        deep=True,
    )
    SettingsStore(paths).save(SettingsState(active=active, draft=draft))

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
    )

    assert runtime.settings_state.active.devices.input_device_id == "mic-2"
    assert runtime.settings_state.active.devices.output_device_id == "speaker-2"
    assert runtime.controller.settings.devices.input_device_id == "mic-2"
    assert SettingsStore(paths).load().active.devices.output_device_id == "speaker-2"
