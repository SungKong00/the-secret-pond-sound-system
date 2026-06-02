from __future__ import annotations

from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
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


def test_build_runtime_wires_services_without_sounddevice_when_recorder_is_injected(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    player = LayeredLoopPlayer()

    output = FakeOutput()

    runtime = build_runtime(tmp_path, recorder=fake_recorder(), player=player, output=output)

    assert runtime.paths == paths
    assert runtime.settings_state.active == settings
    assert runtime.controller.settings == settings
    assert runtime.player is player
    assert runtime.output is output
    assert runtime.participants.get_count() == 0


def test_build_runtime_initializes_voice_stack_from_active_settings(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = small_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))

    build_runtime(tmp_path, recorder=fake_recorder())

    assert paths.voice_stack_raw.exists()
    assert paths.voice_manifest.exists()


def test_build_runtime_creates_default_settings_file_when_missing(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    runtime = build_runtime(tmp_path, recorder=fake_recorder())

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

    runtime = build_runtime(tmp_path, recorder=fake_recorder(), output=FakeOutput())

    assert runtime.settings_state.active.devices.input_device_id == "mic-2"
    assert runtime.settings_state.active.devices.output_device_id == "speaker-2"
    assert runtime.controller.settings.devices.input_device_id == "mic-2"
    assert SettingsStore(paths).load().active.devices.output_device_id == "speaker-2"
