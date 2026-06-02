from __future__ import annotations

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.recorder import FakeRecorder


def take(value: float = 0.25) -> AudioBuffer:
    return AudioBuffer(samples=np.ones((4, 2), dtype=np.float32) * value, sample_rate=48_000)


def test_fake_recorder_start_stop_returns_configured_take() -> None:
    recorder = FakeRecorder(take())

    recorder.start()
    recorded = recorder.stop()

    assert recorder.is_recording is False
    assert recorded.sample_rate == 48_000
    np.testing.assert_allclose(recorded.samples, take().samples)


def test_fake_recorder_is_recording_toggles() -> None:
    recorder = FakeRecorder(take())

    assert recorder.is_recording is False
    recorder.start()
    assert recorder.is_recording is True
    recorder.stop()
    assert recorder.is_recording is False


def test_fake_recorder_rejects_double_start() -> None:
    recorder = FakeRecorder(take())

    recorder.start()

    with pytest.raises(RuntimeError, match="already recording"):
        recorder.start()

    assert recorder.is_recording is True


def test_fake_recorder_rejects_stop_before_start() -> None:
    recorder = FakeRecorder(take())

    with pytest.raises(RuntimeError, match="not recording"):
        recorder.stop()


def test_fake_recorder_rejects_stop_without_prepared_take_and_clears_recording() -> None:
    recorder = FakeRecorder([])

    recorder.start()

    with pytest.raises(RuntimeError, match="prepared"):
        recorder.stop()

    assert recorder.is_recording is False


def test_fake_recorder_returns_queued_takes_in_order() -> None:
    recorder = FakeRecorder([take(0.1), take(0.2)])

    recorder.start()
    first = recorder.stop()
    recorder.start()
    second = recorder.stop()

    np.testing.assert_allclose(first.samples, take(0.1).samples)
    np.testing.assert_allclose(second.samples, take(0.2).samples)
