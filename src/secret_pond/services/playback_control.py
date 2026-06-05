from __future__ import annotations

from typing import Any

from secret_pond.services.runtime import SecretPondRuntime


class PlaybackControlError(RuntimeError):
    """Raised when a playback control action cannot be completed safely."""


def start_playback(runtime: SecretPondRuntime) -> None:
    try:
        runtime.output.start()
    except (RuntimeError, ValueError, OSError) as exc:
        _log_playback_event(runtime, "playback.start_failed", error=str(exc))
        raise PlaybackControlError(str(exc)) from exc
    runtime.voice_stack.begin_playback_session(runtime.controller.settings)
    runtime.transition_warning = None
    _log_playback_event(runtime, "playback.started")


def stop_playback(runtime: SecretPondRuntime) -> None:
    try:
        runtime.output.stop()
    except (RuntimeError, ValueError, OSError) as exc:
        _log_playback_event(runtime, "playback.stop_failed", error=str(exc))
        raise PlaybackControlError(str(exc)) from exc
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


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
