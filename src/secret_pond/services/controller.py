from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.recorder import Recorder
from secret_pond.config import AppSettings


class VoiceStack(Protocol):
    def add_processed_voice(
        self,
        buffer: AudioBuffer,
        settings: AppSettings,
        processing_settings_snapshot: Mapping[str, Any],
        offset_frames: int | None = None,
    ) -> Any: ...


class VoiceLayerRenderer(Protocol):
    def render_layer(self, layer_id: str, settings: AppSettings) -> Any: ...


class Participants(Protocol):
    def increment(self) -> int: ...


@dataclass(frozen=True)
class RecordingOutcome:
    accepted: bool
    duration_seconds: float
    reason: str | None = None
    participant_count: int | None = None
    stack_result: Any | None = None
    render_result: Any | None = None


class RecordingController:
    def __init__(
        self,
        *,
        settings: AppSettings,
        recorder: Recorder,
        voice_stack: VoiceStack,
        renderer: VoiceLayerRenderer,
        participants: Participants,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._recorder = recorder
        self._voice_stack = voice_stack
        self._renderer = renderer
        self._participants = participants
        self._clock = clock
        self._armed = False
        self._recording_started_at: float | None = None
        self._last_error: str | None = None

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def is_recording(self) -> bool:
        return self._recording_started_at is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def recording_elapsed_seconds(self) -> float:
        return self._elapsed_since(self._recording_started_at)

    @property
    def recording_remaining_seconds(self) -> float:
        maximum = self._settings.input_control.maximum_recording_seconds
        return max(0.0, maximum - self.recording_elapsed_seconds)

    def arm_input(self) -> None:
        self._armed = True
        self._last_error = None

    def disarm_input(self) -> RecordingOutcome | None:
        self._armed = False
        if not self.is_recording:
            return None

        started_at = self._recording_started_at
        try:
            self._recorder.stop()
        except Exception as exc:
            self._clear_recording_state(exc)
            raise

        duration_seconds = self._elapsed_since(started_at)
        self._clear_recording_state()
        return RecordingOutcome(
            accepted=False,
            duration_seconds=duration_seconds,
            reason="disarmed",
        )

    def start_recording(self) -> None:
        if not self._armed:
            msg = "input must be armed before recording"
            raise RuntimeError(msg)
        if self.is_recording:
            msg = "recording is already recording"
            raise RuntimeError(msg)

        started_at = self._clock()
        try:
            self._recorder.start()
        except Exception as exc:
            self._recording_started_at = None
            self._last_error = str(exc)
            raise

        self._recording_started_at = started_at
        self._last_error = None

    def stop_recording(self) -> RecordingOutcome:
        if not self.is_recording:
            msg = "controller is not recording"
            raise RuntimeError(msg)

        started_at = self._recording_started_at
        try:
            recorded = self._recorder.stop()
        except Exception as exc:
            self._clear_recording_state(exc)
            raise

        duration_seconds = self._elapsed_since(started_at)
        self._clear_recording_state()

        if duration_seconds < self._settings.input_control.minimum_recording_seconds:
            return RecordingOutcome(
                accepted=False,
                duration_seconds=duration_seconds,
                reason="too_short",
            )
        if recorded.frames == 0:
            return RecordingOutcome(
                accepted=False,
                duration_seconds=duration_seconds,
                reason="empty",
            )

        try:
            processed = apply_recording_processing(recorded, self._settings.recording)
            stack_result = self._voice_stack.add_processed_voice(
                processed,
                self._settings,
                processing_settings_snapshot=self._settings.recording.model_dump(mode="json"),
            )
            participant_count = self._increment_participants_best_effort()
            render_result = self._renderer.render_layer("voice", self._settings)
        except Exception as exc:
            self._last_error = str(exc)
            raise

        if participant_count is not None:
            self._last_error = None
        return RecordingOutcome(
            accepted=True,
            duration_seconds=duration_seconds,
            participant_count=participant_count,
            stack_result=stack_result,
            render_result=render_result,
        )

    def poll_auto_stop(self) -> RecordingOutcome | None:
        if not self.is_recording:
            return None
        if self.recording_elapsed_seconds < self._settings.input_control.maximum_recording_seconds:
            return None
        return self.stop_recording()

    def _elapsed_since(self, started_at: float | None) -> float:
        if started_at is None:
            return 0.0
        return max(0.0, self._clock() - started_at)

    def _clear_recording_state(self, error: Exception | None = None) -> None:
        self._recording_started_at = None
        self._last_error = None if error is None else str(error)

    def _increment_participants_best_effort(self) -> int | None:
        try:
            return self._participants.increment()
        except Exception as exc:
            self._last_error = str(exc)
            return None
