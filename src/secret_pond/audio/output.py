from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import numpy as np


class LoopPlayer(Protocol):
    @property
    def is_playing(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def next_block(self, block_size: int) -> Any: ...


StreamFactory = Callable[..., Any]


class SoundDeviceOutput:
    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        player: LoopPlayer,
        device_id: str | None = None,
        block_size: int = 1024,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        if block_size <= 0:
            msg = "block_size must be greater than 0"
            raise ValueError(msg)
        self._sample_rate = sample_rate
        self._channels = channels
        self._player = player
        self._device_id = device_id
        self._block_size = block_size
        self._stream_factory = stream_factory or _default_stream_factory
        self._stream: Any | None = None
        self._is_running = False
        self._statuses: list[Any] = []
        self._latest_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def latest_status(self) -> Any | None:
        return self._statuses[-1] if self._statuses else None

    @property
    def statuses(self) -> list[Any]:
        return list(self._statuses)

    @property
    def latest_error(self) -> str | None:
        return self._latest_error

    def start(self) -> None:
        if self._is_running:
            msg = "output is already running"
            raise RuntimeError(msg)

        self._statuses = []
        self._latest_error = None
        stream = self._stream_factory(
            samplerate=self._sample_rate,
            channels=self._channels,
            device=_normalize_device_id(self._device_id),
            dtype="float32",
            blocksize=self._block_size,
            callback=self._callback,
        )
        self._stream = stream
        player_started = False
        try:
            self._player.start()
            player_started = True
            stream.start()
        except Exception as exc:
            self._latest_error = str(exc)
            if player_started:
                self._player.stop()
            stream.close()
            self._stream = None
            self._is_running = False
            raise

        self._is_running = True

    def stop(self) -> None:
        if not self._is_running:
            msg = "output is not running"
            raise RuntimeError(msg)

        stream = self._stream
        self._stream = None
        self._is_running = False
        try:
            self._player.stop()
            if stream is not None:
                stream.stop()
        except Exception as exc:
            self._latest_error = str(exc)
            raise
        finally:
            if stream is not None:
                stream.close()

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            self._statuses.append(status)
        try:
            block = self._player.next_block(frames)
            outdata[:] = np.asarray(block.samples, dtype=np.float32)
        except Exception as exc:
            self._latest_error = str(exc)
            outdata.fill(0.0)


def _normalize_device_id(device_id: str | None) -> str | int | None:
    if device_id is None:
        return None
    if device_id.isdigit():
        return int(device_id)
    return device_id


def _default_stream_factory(**kwargs):
    import sounddevice as sd

    return sd.OutputStream(**kwargs)
