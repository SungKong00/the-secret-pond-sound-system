from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np

from secret_pond.audio.buffers import AudioBuffer


class Recorder(Protocol):
    @property
    def is_recording(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> AudioBuffer: ...


class FakeRecorder:
    def __init__(self, takes: AudioBuffer | Sequence[AudioBuffer]) -> None:
        if isinstance(takes, AudioBuffer):
            self._takes = [takes]
        else:
            self._takes = list(takes)
        self._is_recording = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start(self) -> None:
        if self._is_recording:
            msg = "recorder is already recording"
            raise RuntimeError(msg)
        self._is_recording = True

    def stop(self) -> AudioBuffer:
        if not self._is_recording:
            msg = "recorder is not recording"
            raise RuntimeError(msg)
        self._is_recording = False
        if not self._takes:
            msg = "fake recorder has no prepared takes"
            raise RuntimeError(msg)
        return self._takes.pop(0)


StreamFactory = Callable[..., Any]


class SoundDeviceRecorder:
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        device_id: str | None = None,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._device_id = device_id
        self._stream_factory = stream_factory or _default_stream_factory
        self._stream: Any | None = None
        self._chunks: list[np.ndarray] = []
        self._is_recording = False
        self._statuses: list[Any] = []

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def latest_status(self) -> Any | None:
        return self._statuses[-1] if self._statuses else None

    @property
    def statuses(self) -> list[Any]:
        return list(self._statuses)

    @property
    def stream_sample_rate(self) -> int:
        return self._sample_rate

    @property
    def stream_channels(self) -> int:
        return self._channels

    def set_device_id(self, device_id: str | None) -> None:
        if self._is_recording:
            msg = "cannot change input device while recording"
            raise RuntimeError(msg)
        self._device_id = device_id

    def set_stream_format(self, *, sample_rate: int, channels: int) -> None:
        if self._is_recording:
            msg = "cannot change input format while recording"
            raise RuntimeError(msg)
        if sample_rate < 1:
            msg = "sample_rate must be positive"
            raise ValueError(msg)
        if channels < 1:
            msg = "channels must be at least 1"
            raise ValueError(msg)
        self._sample_rate = sample_rate
        self._channels = channels

    def start(self) -> None:
        if self._is_recording:
            msg = "recorder is already recording"
            raise RuntimeError(msg)

        self._chunks = []
        self._statuses = []
        try:
            self._stream = self._stream_factory(
                samplerate=self._sample_rate,
                channels=self._channels,
                device=_normalize_device_id(self._device_id),
                dtype="float32",
                callback=self._callback,
            )
        except Exception as exc:
            self._stream = None
            msg = f"input stream unavailable: {exc}"
            raise RuntimeError(msg) from exc
        try:
            self._stream.start()
        except Exception:
            self._stream.close()
            self._stream = None
            raise
        else:
            self._is_recording = True

    def stop(self) -> AudioBuffer:
        if not self._is_recording:
            msg = "recorder is not recording"
            raise RuntimeError(msg)

        stream = self._stream
        self._stream = None
        self._is_recording = False
        try:
            if stream is not None:
                stream.stop()
        finally:
            if stream is not None:
                stream.close()

        if not self._chunks:
            samples = np.zeros((0, self._channels), dtype=np.float32)
        else:
            samples = np.concatenate(self._chunks, axis=0).astype(np.float32)
        return AudioBuffer(samples=samples, sample_rate=self._sample_rate)

    def _callback(self, indata, _frames, _time, status) -> None:
        if status:
            self._statuses.append(status)
        self._chunks.append(np.asarray(indata, dtype=np.float32).copy())


def _normalize_device_id(device_id: str | None) -> str | int | None:
    if device_id is None:
        return None
    if device_id.isdigit():
        return int(device_id)
    return device_id


def _default_stream_factory(**kwargs):
    import sounddevice as sd

    return sd.InputStream(**kwargs)
