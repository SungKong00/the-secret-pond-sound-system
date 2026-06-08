from __future__ import annotations

from typing import Any


def playback_loop_seconds(settings: Any) -> float:
    return float(settings.voice_stack.loop_seconds)


def playback_loop_frames(settings: Any) -> int:
    return int(round(settings.audio.sample_rate * playback_loop_seconds(settings)))


def normalized_loop_seconds(settings: Any) -> float:
    return playback_loop_seconds(settings)


def visible_loop_seconds(settings: Any) -> float:
    loop_seconds = playback_loop_seconds(settings)
    transition_seconds = float(settings.voice_stack.transition_seconds)
    if transition_seconds > 0.0 and transition_seconds < loop_seconds:
        return loop_seconds - transition_seconds
    return loop_seconds


def visible_loop_frames(settings: Any) -> int:
    return int(round(settings.audio.sample_rate * visible_loop_seconds(settings)))


def loop_transition_frames(settings: Any) -> int:
    loop_frames = playback_loop_frames(settings)
    transition_frames = int(
        round(settings.audio.sample_rate * settings.voice_stack.transition_seconds)
    )
    if transition_frames <= 0 or transition_frames >= loop_frames:
        return 0
    return transition_frames
