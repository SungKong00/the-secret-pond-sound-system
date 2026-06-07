from __future__ import annotations

from typing import Any


def normalized_loop_seconds(settings: Any) -> float:
    return float(settings.audio.loop_seconds)


def visible_loop_seconds(settings: Any) -> float:
    loop_seconds = normalized_loop_seconds(settings)
    transition_seconds = float(settings.voice_stack.transition_seconds)
    if transition_seconds > 0.0 and transition_seconds < loop_seconds:
        return loop_seconds - transition_seconds
    return loop_seconds


def visible_loop_frames(settings: Any) -> int:
    return int(round(settings.audio.sample_rate * visible_loop_seconds(settings)))
