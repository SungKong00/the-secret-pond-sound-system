from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

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
