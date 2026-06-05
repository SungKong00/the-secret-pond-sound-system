from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from secret_pond.audio.file_io import read_wav
from secret_pond.services.player_settings import apply_player_layer_settings
from secret_pond.services.recording_transaction import run_recording_transaction
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths

_T = TypeVar("_T")


@dataclass(frozen=True)
class RecordingPlaybackGuard:
    playback_session_id: str | None
    current_stack_id: str


def run_recording_workflow(runtime: SecretPondRuntime, control: Callable[[], _T]) -> _T:
    guard = _capture_recording_playback_guard(runtime)
    outcome = run_recording_transaction(runtime, control)
    refresh_playback_after_recording(runtime, outcome, guard=guard)
    return outcome


def refresh_playback_after_recording(
    runtime: SecretPondRuntime,
    outcome: Any,
    *,
    guard: RecordingPlaybackGuard | None = None,
) -> None:
    if outcome is None or not getattr(outcome, "accepted", False):
        return

    settings = runtime.controller.settings
    if settings.voice_stack.mode != "live_ephemeral":
        return

    try:
        if runtime.output.is_running:
            if not _playback_guard_matches(runtime, settings, guard):
                runtime.transition_warning = (
                    "목소리 전환을 건너뛰었습니다. 재생 중 선택된 스택이 바뀌었습니다."
                )
                _log_event_best_effort(
                    runtime,
                    "recording.playback_refresh_skipped",
                    {
                        "reason": "playback_guard_mismatch",
                        "voice_stack_path": _voice_stack_path(outcome),
                    },
                )
                return
            voice = read_wav(runtime.paths.voice_playback)
            runtime.player.start_voice_crossfade(
                voice,
                duration_frames=int(
                    settings.voice_stack.transition_seconds * settings.audio.sample_rate
                ),
                transition_target_id=_voice_stack_path(outcome) or "voice-stack",
            )
            runtime.transition_warning = None
        else:
            runtime.player.load_rendered_layers(rendered_layer_paths(runtime.paths))
            runtime.transition_warning = None
        apply_player_layer_settings(runtime, settings)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        runtime.transition_warning = "목소리 전환을 적용하지 못했습니다."
        _log_event_best_effort(
            runtime,
            "recording.playback_refresh_failed",
            {
                "error": str(exc),
                "output_running": runtime.output.is_running,
            },
        )


def _capture_recording_playback_guard(runtime: SecretPondRuntime) -> RecordingPlaybackGuard | None:
    if not runtime.output.is_running:
        return None
    state = runtime.voice_stack.transition_guard_state(runtime.controller.settings)
    return RecordingPlaybackGuard(
        playback_session_id=state.playback_session_id,
        current_stack_id=state.current_stack_id,
    )


def _playback_guard_matches(
    runtime: SecretPondRuntime,
    settings: Any,
    guard: RecordingPlaybackGuard | None,
) -> bool:
    if guard is None:
        return True
    current = runtime.voice_stack.transition_guard_state(settings)
    return (
        current.playback_session_id == guard.playback_session_id
        and current.current_stack_id == guard.current_stack_id
    )


def _voice_stack_path(outcome: Any) -> str | None:
    stack_result = getattr(outcome, "stack_result", None)
    voice_stack_path = getattr(stack_result, "voice_stack_path", None)
    return voice_stack_path if isinstance(voice_stack_path, str) else None


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
