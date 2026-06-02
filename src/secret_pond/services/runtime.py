from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
    controller: RecordingController
    player: LayeredLoopPlayer
    output: PlaybackOutput

    def apply_settings_state(self, settings_state: SettingsState) -> None:
        self.controller.update_settings(settings_state.active)
        self.settings_state = settings_state


def build_runtime(
    root: Path,
    *,
    recorder: Recorder | None = None,
    player: LayeredLoopPlayer | None = None,
    output: PlaybackOutput | None = None,
) -> SecretPondRuntime:
    paths = ProjectPaths(root)
    paths.ensure_directories()

    settings_store = SettingsStore(paths)
    settings_state = settings_store.load()
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
