from __future__ import annotations

from enum import StrEnum


class RuntimeStatus(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    RECORDING = "recording"
    PROCESSING = "processing"
    RENDERING = "rendering"
    PLAYING = "playing"
    STOPPED = "stopped"
    ERROR = "error"
