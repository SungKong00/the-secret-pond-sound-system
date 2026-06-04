from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.audio.recorder import FakeRecorder
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    DeviceSettings,
    PlaybackSettings,
    VoiceStackSettings,
)
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


def write_layer_file(path: Path, value: float, settings: AppSettings) -> None:
    frames = settings.audio.sample_rate * settings.audio.loop_seconds
    samples = np.ones((frames, settings.audio.channels), dtype=np.float32) * value
    write_wav_atomic(path, AudioBuffer(samples=samples, sample_rate=settings.audio.sample_rate))


def write_rendered_layers(paths: ProjectPaths, settings: AppSettings) -> None:
    write_layer_file(paths.low_playback, 0.4, settings)
    write_layer_file(paths.mid_playback, 0.4, settings)
    write_layer_file(paths.voice_playback, 0.4, settings)


def write_source_layers(paths: ProjectPaths, settings: AppSettings) -> None:
    write_layer_file(paths.low_source, 0.05, settings)
    write_layer_file(paths.mid_source, 0.05, settings)


def read_events(paths: ProjectPaths) -> list[dict]:
    return [
        json.loads(line)
        for line in paths.event_log_file.read_text(encoding="utf-8").splitlines()
    ]


def playback_ready_settings(*, auto_start: bool = False) -> AppSettings:
    settings = small_settings()
    layers = {
        **settings.layers,
        "mid": settings.layers["mid"].model_copy(update={"enabled": False}),
    }
    return settings.model_copy(
        update={
            "audio": settings.audio.model_copy(update={"peak_ceiling": 0.5}),
            "layers": layers,
            "playback": PlaybackSettings(auto_start=auto_start),
        },
        deep=True,
    )


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

    startup_events = [
        event for event in read_events(paths) if event["event_type"] == "system.startup"
    ]
    assert len(startup_events) == 1
    event = startup_events[0]
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
    startup_events = [
        event for event in read_events(paths) if event["event_type"] == "system.startup"
    ]
    assert len(startup_events) == 1
    event = startup_events[0]
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


def test_build_runtime_loads_existing_rendered_layers_on_startup(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = playback_ready_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    write_rendered_layers(paths, settings)

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
    )
    runtime.player.start()
    block = runtime.player.next_block(4)

    assert runtime.player.layer_states["mid"].enabled is False
    assert runtime.player.snapshot().peak_ceiling == 0.5
    np.testing.assert_allclose(block.samples, np.ones((4, 2), dtype=np.float32) * 0.5)


def test_build_runtime_renders_missing_playback_layers_when_sources_exist(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    write_source_layers(paths, settings)

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
    )
    runtime.player.start()
    block = runtime.player.next_block(4)

    assert paths.low_playback.exists()
    assert paths.mid_playback.exists()
    assert paths.voice_playback.exists()
    assert block.samples.shape == (4, 2)


def test_build_runtime_rerenders_stale_playback_layers_when_audio_format_changes(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    stale_settings = AppSettings(
        audio=AudioFormatSettings(sample_rate=16_000, channels=2, loop_seconds=1),
        voice_stack=VoiceStackSettings(loop_seconds=1),
    )
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    write_source_layers(paths, settings)
    write_rendered_layers(paths, stale_settings)

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
    )
    runtime.player.start()
    block = runtime.player.next_block(4)

    assert runtime.player.snapshot().layers["low"].sample_rate == 8_000
    assert runtime.player.snapshot().layers["low"].frames == 8_000
    assert block.samples.shape == (4, 2)


def test_build_runtime_keeps_startup_alive_when_playback_prepare_fails(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=FakeOutput(),
        device_registry=fake_device_registry(),
    )

    unavailable_events = [
        event
        for event in read_events(paths)
        if event["event_type"] == "system.startup_playback_unavailable"
    ]
    assert runtime.paths == paths
    assert unavailable_events
    assert "low source file" in unavailable_events[0]["payload"]["error"]


def test_build_runtime_autostarts_output_after_playback_prepare(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = playback_ready_settings(auto_start=True)
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    write_rendered_layers(paths, settings)
    output = FakeOutput()

    runtime = build_runtime(
        tmp_path,
        recorder=fake_recorder(),
        output=output,
        device_registry=fake_device_registry(),
    )

    assert runtime.output.is_running is True


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
