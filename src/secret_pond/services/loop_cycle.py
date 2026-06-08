from __future__ import annotations

from typing import Any


def playback_loop_seconds(settings: Any) -> float:
    return float(settings.voice_stack.loop_seconds)


def playback_loop_frames(settings: Any) -> int:
    return int(round(settings.audio.sample_rate * playback_loop_seconds(settings)))


def normalized_loop_seconds(settings: Any) -> float:
    return playback_loop_seconds(settings)


def visible_loop_seconds(settings: Any) -> float:
    return playback_loop_seconds(settings)


def visible_loop_frames(settings: Any) -> int:
    return playback_loop_frames(settings)
