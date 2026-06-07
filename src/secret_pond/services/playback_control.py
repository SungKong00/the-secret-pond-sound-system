from __future__ import annotations

import math
from typing import Any

from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.voice_raw_preview import restore_main_playback_after_voice_raw_preview


class PlaybackControlError(RuntimeError):
    """Raised when a playback control action cannot be completed safely."""


def start_playback(runtime: SecretPondRuntime) -> None:
    try:
        if runtime.voice_raw_preview_path is not None:
            if runtime.output.is_running:
                runtime.output.stop()
            restore_main_playback_after_voice_raw_preview(runtime, runtime.controller.settings)
        runtime.output.start()
        _ensure_player_started(runtime)
    except (RuntimeError, ValueError, OSError) as exc:
        _log_playback_event(runtime, "playback.start_failed", error=str(exc))
        raise PlaybackControlError(str(exc)) from exc
    runtime.voice_stack.begin_playback_session(runtime.controller.settings)
    runtime.transition_warning = None
    _log_playback_event(runtime, "playback.started")


def stop_playback(runtime: SecretPondRuntime) -> None:
    preview_should_resume_main = bool(
        runtime.voice_raw_preview_path is not None and runtime.voice_raw_preview_resume_main,
    )
    try:
        runtime.output.stop()
        if runtime.voice_raw_preview_path is not None:
            restore_main_playback_after_voice_raw_preview(runtime, runtime.controller.settings)
            if preview_should_resume_main:
                runtime.output.start()
    except (RuntimeError, ValueError, OSError) as exc:
        _log_playback_event(runtime, "playback.stop_failed", error=str(exc))
        raise PlaybackControlError(str(exc)) from exc
    if not preview_should_resume_main:
        runtime.voice_stack.end_playback_session()
    runtime.transition_warning = None
    _log_playback_event(runtime, "playback.stopped")


def restart_playback(runtime: SecretPondRuntime) -> None:
    if not runtime.output.is_running:
        detail = "output must be running before restart"
        _log_playback_event(runtime, "playback.restart_failed", error=detail)
        raise PlaybackControlError(detail)

    player_snapshot = runtime.player.snapshot()
    try:
        runtime.output.stop()
        runtime.player.restart()
        runtime.output.start()
    except (OSError, RuntimeError, ValueError) as exc:
        runtime.player.restore(player_snapshot)
        detail = str(exc)
        try:
            if not runtime.output.is_running:
                runtime.output.start()
        except Exception as resume_exc:
            runtime.player.restore(player_snapshot)
            detail = f"{detail}; rollback resume failed: {resume_exc}"
        _log_playback_event(runtime, "playback.restart_failed", error=detail)
        raise PlaybackControlError(detail) from exc
    runtime.voice_stack.begin_playback_session(runtime.controller.settings)
    runtime.transition_warning = None
    _log_playback_event(runtime, "playback.restarted")


def seek_playback(runtime: SecretPondRuntime, progress: float) -> None:
    if not math.isfinite(progress) or progress < 0.0 or progress > 1.0:
        detail = "progress must be a finite number between 0 and 1"
        _log_playback_event(runtime, "playback.seek_failed", error=detail)
        raise PlaybackControlError(detail)

    settings = runtime.controller.settings
    loop_frames = settings.audio.sample_rate * settings.voice_stack.loop_seconds
    if loop_frames <= 0:
        detail = "audio loop length must be greater than 0"
        _log_playback_event(runtime, "playback.seek_failed", error=detail)
        raise PlaybackControlError(detail)

    frame_cursor = int(round(progress * loop_frames)) % loop_frames
    try:
        runtime.player.seek(frame_cursor)
    except ValueError as exc:
        detail = str(exc)
        _log_playback_event(runtime, "playback.seek_failed", error=detail)
        raise PlaybackControlError(detail) from exc
    _log_playback_event(runtime, "playback.seeked")


def _log_playback_event(
    runtime: SecretPondRuntime,
    event_type: str,
    *,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "frame_cursor": runtime.player.frame_cursor,
        "output_running": runtime.output.is_running,
    }
    if error is not None:
        payload["error"] = error
    _log_event_best_effort(runtime, event_type, payload)


def _ensure_player_started(runtime: SecretPondRuntime) -> None:
    if getattr(runtime.player, "is_playing", False):
        return
    player_start = getattr(runtime.player, "start", None)
    if not callable(player_start):
        return
    try:
        player_start()
    except (RuntimeError, ValueError, OSError):
        try:
            if runtime.output.is_running:
                runtime.output.stop()
        except Exception:
            pass
        raise


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
