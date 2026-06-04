from __future__ import annotations

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.recorder import FakeRecorder, SoundDeviceRecorder


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


class FakeInputStream:
    def __init__(self, callback, fail_start: bool = False) -> None:
        self.callback = callback
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        if self.fail_start:
            raise OSError("stream start failed")
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def push(self, samples: np.ndarray, status=None) -> None:
        self.callback(samples, samples.shape[0], None, status)


class CapturingStreamFactory:
    def __init__(self, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.calls: list[dict] = []
        self.streams: list[FakeInputStream] = []

    def __call__(self, **kwargs) -> FakeInputStream:
        self.calls.append(kwargs)
        stream = FakeInputStream(kwargs["callback"], fail_start=self.fail_start)
        self.streams.append(stream)
        return stream


def test_sounddevice_recorder_records_callback_blocks() -> None:
    factory = CapturingStreamFactory()
    recorder = SoundDeviceRecorder(
        sample_rate=48_000,
        channels=2,
        stream_factory=factory,
    )

    recorder.start()
    factory.streams[0].push(np.ones((2, 2), dtype=np.float32) * 0.1)
    factory.streams[0].push(np.ones((3, 2), dtype=np.float32) * 0.2)
    recorded = recorder.stop()

    assert factory.streams[0].started is True
    assert factory.streams[0].stopped is True
    assert factory.streams[0].closed is True
    assert recorder.is_recording is False
    assert recorded.sample_rate == 48_000
    np.testing.assert_allclose(recorded.samples[:2], 0.1)
    np.testing.assert_allclose(recorded.samples[2:], 0.2)


def test_sounddevice_recorder_passes_stream_configuration_and_normalizes_device_id() -> None:
    factory = CapturingStreamFactory()
    recorder = SoundDeviceRecorder(
        sample_rate=48_000,
        channels=1,
        device_id="3",
        stream_factory=factory,
    )

    recorder.start()

    assert factory.calls[0]["samplerate"] == 48_000
    assert factory.calls[0]["channels"] == 1
    assert factory.calls[0]["device"] == 3
    assert factory.calls[0]["dtype"] == "float32"


def test_sounddevice_recorder_maps_stream_factory_failures_to_runtime_error() -> None:
    def fail_factory(**_kwargs):
        raise OSError("invalid number of channels")

    recorder = SoundDeviceRecorder(
        sample_rate=48_000,
        channels=2,
        stream_factory=fail_factory,
    )

    with pytest.raises(RuntimeError, match="input stream unavailable"):
        recorder.start()

    assert recorder.is_recording is False


def test_sounddevice_recorder_returns_empty_buffer_when_no_chunks() -> None:
    factory = CapturingStreamFactory()
    recorder = SoundDeviceRecorder(
        sample_rate=48_000,
        channels=2,
        stream_factory=factory,
    )

    recorder.start()
    recorded = recorder.stop()

    assert recorded.sample_rate == 48_000
    assert recorded.samples.shape == (0, 2)


def test_sounddevice_recorder_rejects_double_start_and_stop_before_start() -> None:
    recorder = SoundDeviceRecorder(
        sample_rate=48_000,
        channels=2,
        stream_factory=CapturingStreamFactory(),
    )

    with pytest.raises(RuntimeError, match="not recording"):
        recorder.stop()

    recorder.start()
    with pytest.raises(RuntimeError, match="already recording"):
        recorder.start()


def test_sounddevice_recorder_stores_callback_statuses() -> None:
    factory = CapturingStreamFactory()
    recorder = SoundDeviceRecorder(sample_rate=48_000, channels=2, stream_factory=factory)

    recorder.start()
    factory.streams[0].push(np.ones((1, 2), dtype=np.float32), status="overflow")
    recorder.stop()

    assert recorder.latest_status == "overflow"
    assert recorder.statuses == ["overflow"]


def test_sounddevice_recorder_closes_stream_when_start_fails() -> None:
    factory = CapturingStreamFactory(fail_start=True)
    recorder = SoundDeviceRecorder(sample_rate=48_000, channels=2, stream_factory=factory)

    with pytest.raises(OSError, match="start failed"):
        recorder.start()

    assert factory.streams[0].closed is True
    assert recorder.is_recording is False
