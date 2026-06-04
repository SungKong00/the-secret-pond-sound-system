from __future__ import annotations

import platform
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from secret_pond.audio.devices import AudioDeviceInfo, AudioDeviceRegistry, SoundDeviceRegistry
from secret_pond.audio.layers import LayerId
from secret_pond.audio.output import SoundDeviceOutput
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.audio.recorder import Recorder, SoundDeviceRecorder
from secret_pond.audio.renderer import LayerRenderer
from secret_pond.audio.voice_stack import VoiceStackStore
from secret_pond.paths import ProjectPaths
from secret_pond.services.controller import RecordingController
from secret_pond.services.logging_service import EventLogger
from secret_pond.services.participants import ParticipantCounter
from secret_pond.services.settings_store import SettingsState, SettingsStore


class PlaybackOutput(Protocol):
    @property
    def is_running(self) -> bool: ...

    @property
    def latest_status(self) -> Any | None: ...

    @property
    def statuses(self) -> list[Any]: ...

    @property
    def latest_error(self) -> str | None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class StartupLogger(Protocol):
    def log_event(self, event_type: str, payload: dict[str, Any] | None = None) -> Any: ...


@dataclass
class SecretPondRuntime:
    paths: ProjectPaths
    settings_store: SettingsStore
    settings_state: SettingsState
    recorder: Recorder
    voice_stack: VoiceStackStore
    renderer: LayerRenderer
    participants: ParticipantCounter
    logger: EventLogger
    device_registry: AudioDeviceRegistry
    controller: RecordingController
    player: LayeredLoopPlayer
    output: PlaybackOutput
    operation_lock: Any = field(default_factory=threading.RLock)

    def apply_settings_state(self, settings_state: SettingsState) -> None:
        self.controller.update_settings(settings_state.active)
        self.settings_state = settings_state


def build_runtime(
    root: Path,
    *,
    recorder: Recorder | None = None,
    player: LayeredLoopPlayer | None = None,
    output: PlaybackOutput | None = None,
    device_registry: AudioDeviceRegistry | None = None,
    startup_logger: StartupLogger | None = None,
) -> SecretPondRuntime:
    paths = ProjectPaths(root)
    paths.ensure_directories()

    settings_store = SettingsStore(paths)
    settings_state = settings_store.load_for_startup()
    active_settings = settings_state.active

    voice_stack = VoiceStackStore(paths)
    voice_stack.ensure_initialized(active_settings)

    resolved_recorder = recorder or SoundDeviceRecorder(
        sample_rate=active_settings.audio.sample_rate,
        channels=active_settings.audio.channels,
        device_id=active_settings.devices.input_device_id,
    )
    resolved_player = player or LayeredLoopPlayer(peak_ceiling=active_settings.audio.peak_ceiling)
    resolved_output = output or SoundDeviceOutput(
        sample_rate=active_settings.audio.sample_rate,
        channels=active_settings.audio.channels,
        device_id=active_settings.devices.output_device_id,
        player=resolved_player,
    )
    renderer = LayerRenderer(paths)
    participants = ParticipantCounter(paths)
    logger = EventLogger(paths)
    resolved_device_registry = device_registry or SoundDeviceRegistry()
    _log_startup_diagnostics_best_effort(
        paths=paths,
        settings=active_settings,
        logger=startup_logger or logger,
        device_registry=resolved_device_registry,
    )
    controller = RecordingController(
        settings=active_settings,
        recorder=resolved_recorder,
        voice_stack=voice_stack,
        renderer=renderer,
        participants=participants,
        logger=logger,
    )

    return SecretPondRuntime(
        paths=paths,
        settings_store=settings_store,
        settings_state=settings_state,
        recorder=resolved_recorder,
        voice_stack=voice_stack,
        renderer=renderer,
        participants=participants,
        logger=logger,
        device_registry=resolved_device_registry,
        controller=controller,
        player=resolved_player,
        output=resolved_output,
    )


def rendered_layer_paths(paths: ProjectPaths) -> dict[LayerId, Path]:
    return {
        "low": paths.low_playback,
        "mid": paths.mid_playback,
        "voice": paths.voice_playback,
    }


def _log_startup_diagnostics_best_effort(
    *,
    paths: ProjectPaths,
    settings: Any,
    logger: StartupLogger,
    device_registry: AudioDeviceRegistry,
) -> None:
    device_error = None
    selected_input = None
    selected_output = None
    try:
        selected_input = device_registry.validate_input(settings.devices.input_device_id)
        selected_output = device_registry.validate_output(settings.devices.output_device_id)
    except Exception as exc:
        device_error = str(exc)

    payload = {
        "os_name": platform.platform(),
        "python_version": sys.version.split()[0],
        "data_dir": str(paths.data_dir),
        "requested_sample_rate": settings.audio.sample_rate,
        "requested_channels": settings.audio.channels,
        "configured_input_device_id": settings.devices.input_device_id,
        "configured_output_device_id": settings.devices.output_device_id,
        "selected_input_device": _device_payload(selected_input),
        "selected_output_device": _device_payload(selected_output),
        "actual_input_sample_rate": None,
        "actual_input_channels": None,
        "actual_output_sample_rate": None,
        "actual_output_channels": None,
        "device_error": device_error,
    }
    try:
        logger.log_event("system.startup", payload)
    except Exception:
        return


def _device_payload(device: AudioDeviceInfo | None) -> dict[str, Any] | None:
    if device is None:
        return None
    return {
        "id": device.id,
        "name": device.name,
        "kind": device.kind,
        "max_input_channels": device.max_input_channels,
        "max_output_channels": device.max_output_channels,
        "default_sample_rate": device.default_sample_rate,
    }
