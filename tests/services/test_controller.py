from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.config import AppSettings, InputControlSettings
from secret_pond.services.controller import RecordingController


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ScriptedRecorder:
    def __init__(
        self,
        take: AudioBuffer | None = None,
        *,
        start_error: Exception | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        self.take = take or voice_take()
        self.start_error = start_error
        self.stop_error = stop_error
        self.is_recording = False
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error
        self.is_recording = True

    def stop(self) -> AudioBuffer:
        self.stop_calls += 1
        self.is_recording = False
        if self.stop_error is not None:
            raise self.stop_error
        return self.take


class SpyVoiceStack:
    def __init__(
        self,
        *,
        add_error: Exception | None = None,
        call_order: list[str] | None = None,
    ) -> None:
        self.add_error = add_error
        self.call_order = call_order
        self.calls: list[dict] = []

    def add_processed_voice(self, buffer, settings, processing_settings_snapshot):
        if self.call_order is not None:
            self.call_order.append("stack")
        self.calls.append(
            {
                "buffer": buffer,
                "settings": settings,
                "processing_settings_snapshot": processing_settings_snapshot,
            },
        )
        if self.add_error is not None:
            raise self.add_error
        settings.sources.voice_stack_path = "data/sources/voice/stack/generated-stack.wav"
        return SimpleNamespace(
            added_chunks=1,
            voice_stack_path="data/sources/voice/stack/generated-stack.wav",
        )


class SpyRenderer:
    def __init__(
        self,
        *,
        render_error: Exception | None = None,
        call_order: list[str] | None = None,
    ) -> None:
        self.render_error = render_error
        self.call_order = call_order
        self.rendered_layers: list[str] = []

    def render_layer(self, layer_id: str, settings):
        if self.call_order is not None:
            self.call_order.append("render")
        self.rendered_layers.append(layer_id)
        if self.render_error is not None:
            raise self.render_error
        return SimpleNamespace(layer_id=layer_id)


class FakeParticipants:
    def __init__(
        self,
        *,
        increment_error: Exception | None = None,
        call_order: list[str] | None = None,
    ) -> None:
        self.increment_error = increment_error
        self.call_order = call_order
        self.count = 0

    def increment(self) -> int:
        if self.call_order is not None:
            self.call_order.append("participants")
        if self.increment_error is not None:
            raise self.increment_error
        self.count += 1
        return self.count


class SpyLogger:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[dict] = []

    def log_event(self, event_type: str, payload=None):
        if self.fail:
            raise RuntimeError("log failed")
        event = {"event_type": event_type, "payload": payload or {}}
        self.events.append(event)
        return event


def voice_take(frames: int = 2_000) -> AudioBuffer:
    samples = np.ones((frames, 2), dtype=np.float32) * 0.05
    return AudioBuffer(samples=samples, sample_rate=48_000)


def empty_take() -> AudioBuffer:
    return AudioBuffer(samples=np.zeros((0, 2), dtype=np.float32), sample_rate=48_000)


def mono_device_take() -> AudioBuffer:
    samples = np.ones(4_410, dtype=np.float32) * 0.05
    return AudioBuffer(samples=samples, sample_rate=44_100)


def controller_fixture(
    *,
    recorder: ScriptedRecorder | None = None,
    voice_stack: SpyVoiceStack | None = None,
    renderer: SpyRenderer | None = None,
    participants: FakeParticipants | None = None,
    logger: SpyLogger | None = None,
    minimum_seconds: float = 1.0,
    maximum_seconds: float = 120.0,
) -> tuple[
    RecordingController,
    ScriptedRecorder,
    SpyVoiceStack,
    SpyRenderer,
    FakeParticipants,
    SpyLogger | None,
    FakeClock,
]:
    settings = AppSettings(
        input_control=InputControlSettings(
            minimum_recording_seconds=minimum_seconds,
            maximum_recording_seconds=maximum_seconds,
        ),
    )
    recorder = recorder or ScriptedRecorder()
    voice_stack = voice_stack or SpyVoiceStack()
    renderer = renderer or SpyRenderer()
    participants = participants or FakeParticipants()
    clock = FakeClock()
    controller = RecordingController(
        settings=settings,
        recorder=recorder,
        voice_stack=voice_stack,
        renderer=renderer,
        participants=participants,
        logger=logger,
        clock=clock,
    )
    return controller, recorder, voice_stack, renderer, participants, logger, clock


def test_controller_rejects_start_when_disarmed() -> None:
    controller, recorder, *_ = controller_fixture()

    with pytest.raises(RuntimeError, match="armed"):
        controller.start_recording()

    assert controller.is_recording is False
    assert recorder.start_calls == 0


def test_controller_discards_too_short_recording() -> None:
    controller, recorder, voice_stack, renderer, participants, _, clock = controller_fixture()

    controller.arm_input()
    controller.start_recording()
    clock.advance(0.25)
    outcome = controller.stop_recording()

    assert outcome.accepted is False
    assert outcome.reason == "too_short"
    assert controller.is_recording is False
    assert recorder.stop_calls == 1
    assert voice_stack.calls == []
    assert renderer.rendered_layers == []
    assert participants.count == 0


def test_controller_discards_empty_recording_even_when_duration_is_long_enough() -> None:
    recorder = ScriptedRecorder(empty_take())
    controller, _, voice_stack, renderer, participants, _, clock = controller_fixture(
        recorder=recorder,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(2.0)
    outcome = controller.stop_recording()

    assert outcome.accepted is False
    assert outcome.reason == "empty"
    assert voice_stack.calls == []
    assert renderer.rendered_layers == []
    assert participants.count == 0


def test_controller_processes_adds_renders_and_counts_accepted_recording() -> None:
    controller, _, voice_stack, renderer, participants, _, clock = controller_fixture()

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert outcome.reason is None
    assert outcome.duration_seconds == pytest.approx(1.2)
    assert outcome.participant_count == 1
    assert participants.count == 1
    assert len(voice_stack.calls) == 1
    assert voice_stack.calls[0]["buffer"].sample_rate == 48_000
    assert (
        voice_stack.calls[0]["processing_settings_snapshot"]
        == controller.settings.recording.model_dump(mode="json")
    )
    assert renderer.rendered_layers == ["voice"]
    assert controller.settings.sources.voice_stack_path == (
        "data/sources/voice/stack/generated-stack.wav"
    )


def test_controller_canonicalizes_mono_device_take_before_stack() -> None:
    recorder = ScriptedRecorder(mono_device_take())
    controller, _, voice_stack, _, _, _, clock = controller_fixture(recorder=recorder)

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    controller.stop_recording()

    processed = voice_stack.calls[0]["buffer"]
    assert processed.sample_rate == 48_000
    assert processed.channels == 2


def test_controller_counts_after_voice_render_succeeds() -> None:
    call_order: list[str] = []
    voice_stack = SpyVoiceStack(call_order=call_order)
    renderer = SpyRenderer(call_order=call_order)
    participants = FakeParticipants(call_order=call_order)
    controller, _, _, _, _, _, clock = controller_fixture(
        voice_stack=voice_stack,
        renderer=renderer,
        participants=participants,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert call_order == ["stack", "render", "participants"]


def test_controller_rejects_double_start_and_preserves_active_recording() -> None:
    controller, recorder, *_ = controller_fixture()

    controller.arm_input()
    controller.start_recording()

    with pytest.raises(RuntimeError, match="already recording"):
        controller.start_recording()

    assert controller.is_recording is True
    assert recorder.start_calls == 1


def test_controller_rejects_stop_when_not_recording() -> None:
    controller, *_ = controller_fixture()

    with pytest.raises(RuntimeError, match="not recording"):
        controller.stop_recording()


def test_controller_cancels_active_recording_when_disarmed() -> None:
    controller, recorder, voice_stack, renderer, participants, _, clock = controller_fixture()

    controller.arm_input()
    controller.start_recording()
    clock.advance(2.0)
    outcome = controller.disarm_input()

    assert controller.armed is False
    assert controller.is_recording is False
    assert outcome is not None
    assert outcome.accepted is False
    assert outcome.reason == "disarmed"
    assert recorder.stop_calls == 1
    assert voice_stack.calls == []
    assert renderer.rendered_layers == []
    assert participants.count == 0


def test_controller_clears_recording_state_when_recorder_start_fails() -> None:
    recorder = ScriptedRecorder(start_error=RuntimeError("stream unavailable"))
    controller, *_ = controller_fixture(recorder=recorder)

    controller.arm_input()

    with pytest.raises(RuntimeError, match="stream unavailable"):
        controller.start_recording()

    assert controller.is_recording is False
    assert controller.last_error == "stream unavailable"


def test_controller_clears_recording_state_when_recorder_stop_fails() -> None:
    recorder = ScriptedRecorder(stop_error=RuntimeError("stop failed"))
    controller, _, _, _, participants, _, clock = controller_fixture(recorder=recorder)

    controller.arm_input()
    controller.start_recording()
    clock.advance(2.0)

    with pytest.raises(RuntimeError, match="stop failed"):
        controller.stop_recording()

    assert controller.is_recording is False
    assert controller.last_error == "stop failed"
    assert participants.count == 0


def test_controller_does_not_increment_participants_when_stack_add_fails() -> None:
    voice_stack = SpyVoiceStack(add_error=RuntimeError("stack failed"))
    controller, _, _, renderer, participants, _, clock = controller_fixture(
        voice_stack=voice_stack,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(2.0)

    with pytest.raises(RuntimeError, match="stack failed"):
        controller.stop_recording()

    assert controller.is_recording is False
    assert controller.last_error == "stack failed"
    assert renderer.rendered_layers == []
    assert participants.count == 0


def test_controller_does_not_increment_participants_when_render_fails() -> None:
    renderer = SpyRenderer(render_error=RuntimeError("render failed"))
    controller, _, voice_stack, _, participants, _, clock = controller_fixture(renderer=renderer)

    controller.arm_input()
    controller.start_recording()
    clock.advance(2.0)

    with pytest.raises(RuntimeError, match="render failed"):
        controller.stop_recording()

    assert controller.is_recording is False
    assert controller.last_error == "render failed"
    assert len(voice_stack.calls) == 1
    assert renderer.rendered_layers == ["voice"]
    assert participants.count == 0


def test_controller_accepts_recording_when_participant_counter_fails() -> None:
    participants = FakeParticipants(increment_error=RuntimeError("count failed"))
    controller, _, voice_stack, renderer, _, _, clock = controller_fixture(
        participants=participants,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(2.0)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert outcome.participant_count is None
    assert controller.last_error == "count failed"
    assert len(voice_stack.calls) == 1
    assert renderer.rendered_layers == ["voice"]


def test_controller_reports_elapsed_and_remaining_recording_time() -> None:
    controller, *_rest, clock = controller_fixture(minimum_seconds=0.1, maximum_seconds=1.0)

    assert controller.recording_elapsed_seconds == 0.0
    assert controller.recording_remaining_seconds == 1.0

    controller.arm_input()
    controller.start_recording()
    clock.advance(0.4)

    assert controller.recording_elapsed_seconds == pytest.approx(0.4)
    assert controller.recording_remaining_seconds == pytest.approx(0.6)

    clock.advance(0.8)

    assert controller.recording_elapsed_seconds == pytest.approx(1.2)
    assert controller.recording_remaining_seconds == 0.0


def test_controller_auto_stop_poll_ignores_idle_controller() -> None:
    controller, recorder, *_ = controller_fixture(minimum_seconds=0.1, maximum_seconds=1.0)

    assert controller.poll_auto_stop() is None
    assert recorder.stop_calls == 0


def test_controller_auto_stop_poll_keeps_recording_before_maximum_duration() -> None:
    controller, recorder, *_rest, clock = controller_fixture(
        minimum_seconds=0.1,
        maximum_seconds=1.0,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(0.9)

    assert controller.poll_auto_stop() is None
    assert controller.is_recording is True
    assert recorder.stop_calls == 0


def test_controller_auto_stop_poll_stops_at_maximum_duration() -> None:
    controller, recorder, voice_stack, renderer, participants, _, clock = controller_fixture(
        minimum_seconds=0.1,
        maximum_seconds=1.0,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.0)
    outcome = controller.poll_auto_stop()

    assert outcome is not None
    assert outcome.accepted is True
    assert outcome.duration_seconds == pytest.approx(1.0)
    assert controller.is_recording is False
    assert recorder.stop_calls == 1
    assert len(voice_stack.calls) == 1
    assert renderer.rendered_layers == ["voice"]
    assert participants.count == 1


def test_controller_auto_stop_poll_discards_empty_recording() -> None:
    recorder = ScriptedRecorder(empty_take())
    controller, _, voice_stack, renderer, participants, _, clock = controller_fixture(
        recorder=recorder,
        minimum_seconds=0.1,
        maximum_seconds=1.0,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.poll_auto_stop()

    assert outcome is not None
    assert outcome.accepted is False
    assert outcome.reason == "empty"
    assert controller.is_recording is False
    assert voice_stack.calls == []
    assert renderer.rendered_layers == []
    assert participants.count == 0


def test_controller_auto_stop_poll_clears_state_when_stop_fails() -> None:
    recorder = ScriptedRecorder(stop_error=RuntimeError("stop failed"))
    controller, _, _, _, participants, _, clock = controller_fixture(
        recorder=recorder,
        minimum_seconds=0.1,
        maximum_seconds=1.0,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.1)

    with pytest.raises(RuntimeError, match="stop failed"):
        controller.poll_auto_stop()

    assert controller.is_recording is False
    assert controller.last_error == "stop failed"
    assert participants.count == 0


def test_controller_logs_accepted_recording_lifecycle() -> None:
    logger = SpyLogger()
    controller, _, _, _, _, _, clock = controller_fixture(logger=logger)

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    controller.stop_recording()

    assert [event["event_type"] for event in logger.events] == [
        "recording.start",
        "recording.stop",
        "participant.incremented",
        "recording.accepted",
    ]
    assert logger.events[1]["payload"]["duration_seconds"] == pytest.approx(1.2)
    assert logger.events[1]["payload"]["frames"] == 2_000
    assert logger.events[3]["payload"]["participant_count"] == 1
    assert logger.events[3]["payload"]["added_chunks"] == 1


def test_controller_logs_too_short_discard() -> None:
    logger = SpyLogger()
    controller, _, _, _, _, _, clock = controller_fixture(logger=logger)

    controller.arm_input()
    controller.start_recording()
    clock.advance(0.2)
    controller.stop_recording()

    assert [event["event_type"] for event in logger.events] == [
        "recording.start",
        "recording.stop",
        "recording.discarded",
    ]
    assert logger.events[2]["payload"]["reason"] == "too_short"


def test_controller_logs_start_failure_without_preserving_recording_state() -> None:
    logger = SpyLogger()
    recorder = ScriptedRecorder(start_error=RuntimeError("stream unavailable"))
    controller, *_ = controller_fixture(recorder=recorder, logger=logger)

    controller.arm_input()

    with pytest.raises(RuntimeError, match="stream unavailable"):
        controller.start_recording()

    assert controller.is_recording is False
    assert [event["event_type"] for event in logger.events] == ["recording.start_failed"]
    assert logger.events[0]["payload"]["error"] == "stream unavailable"


def test_controller_logs_render_failure_without_participant_increment() -> None:
    logger = SpyLogger()
    renderer = SpyRenderer(render_error=RuntimeError("render failed"))
    controller, _, _, _, participants, _, clock = controller_fixture(
        renderer=renderer,
        logger=logger,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)

    with pytest.raises(RuntimeError, match="render failed"):
        controller.stop_recording()

    assert participants.count == 0
    assert [event["event_type"] for event in logger.events] == [
        "recording.start",
        "recording.stop",
        "recording.render_failed",
    ]
    assert logger.events[2]["payload"]["error"] == "render failed"


def test_controller_logs_participant_failure_but_still_accepts_recording() -> None:
    logger = SpyLogger()
    participants = FakeParticipants(increment_error=RuntimeError("count failed"))
    controller, _, _, _, _, _, clock = controller_fixture(
        participants=participants,
        logger=logger,
    )

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert [event["event_type"] for event in logger.events] == [
        "recording.start",
        "recording.stop",
        "participant.increment_failed",
        "recording.accepted",
    ]
    assert logger.events[2]["payload"]["error"] == "count failed"
    assert logger.events[3]["payload"]["participant_count"] is None


def test_controller_ignores_logger_failure_without_overwriting_last_error() -> None:
    logger = SpyLogger(fail=True)
    controller, _, _, _, _, _, clock = controller_fixture(logger=logger)

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert controller.last_error is None
