from __future__ import annotations

import platform
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from secret_pond.audio.devices import AudioDeviceInfo, AudioDeviceRegistry, SoundDeviceRegistry
from secret_pond.audio.file_io import read_wav
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
    voice_stack_snapshot = voice_stack.ensure_initialized(active_settings)

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
    _prepare_startup_playback_best_effort(
        paths=paths,
        settings=active_settings,
        renderer=renderer,
        player=resolved_player,
        output=resolved_output,
        logger=startup_logger or logger,
        voice_stack_source_normalized=voice_stack_snapshot.raw_normalized,
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


def _prepare_startup_playback_best_effort(
    *,
    paths: ProjectPaths,
    settings: Any,
    renderer: LayerRenderer,
    player: LayeredLoopPlayer,
    output: PlaybackOutput,
    logger: StartupLogger,
    voice_stack_source_normalized: bool = False,
) -> None:
    layer_paths = rendered_layer_paths(paths)
    missing_layers: list[LayerId] = []
    prepared_from = "cache"
    try:
        missing_layers = [layer_id for layer_id, path in layer_paths.items() if not path.exists()]
        if (
            missing_layers
            or voice_stack_source_normalized
            or not _rendered_layers_match_settings(layer_paths, settings)
        ):
            renderer.render_all(settings)
            prepared_from = "render"
        player.load_rendered_layers(layer_paths)
        _apply_startup_player_settings(player, settings)
    except Exception as exc:
        _log_startup_event_best_effort(
            logger,
            "system.startup_playback_unavailable",
            {
                "error": str(exc),
                "missing_layers": missing_layers,
                "prepared_from": prepared_from,
                "auto_start_requested": settings.playback.auto_start,
                "voice_stack_source_normalized": voice_stack_source_normalized,
            },
        )
        return

    if not settings.playback.auto_start:
        return

    try:
        output.start()
    except Exception as exc:
        _log_startup_event_best_effort(
            logger,
            "system.startup_playback_autostart_failed",
            {
                "error": str(exc),
                "prepared_from": prepared_from,
            },
        )


def _apply_startup_player_settings(player: LayeredLoopPlayer, settings: Any) -> None:
    for layer_id, layer_settings in settings.layers.items():
        player.set_enabled(layer_id, layer_settings.enabled)
    player.set_peak_ceiling(settings.audio.peak_ceiling)


def _rendered_layers_match_settings(layer_paths: dict[LayerId, Path], settings: Any) -> bool:
    target_frames = settings.audio.sample_rate * settings.audio.loop_seconds
    for path in layer_paths.values():
        try:
            buffer = read_wav(path)
        except Exception:
            return False
        if (
            buffer.sample_rate != settings.audio.sample_rate
            or buffer.channels != settings.audio.channels
            or buffer.frames != target_frames
        ):
            return False
    return True


def _log_startup_event_best_effort(
    logger: StartupLogger,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        logger.log_event(event_type, payload)
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
