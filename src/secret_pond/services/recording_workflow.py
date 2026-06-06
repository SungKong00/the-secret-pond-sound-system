from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from secret_pond.audio.file_io import read_wav
from secret_pond.services.player_settings import apply_player_layer_settings
from secret_pond.services.recording_transaction import run_recording_transaction
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths

_T = TypeVar("_T")

READY_VOICE_STACK_CROSSFADE_OWNER = "LayeredLoopPlayer.start_voice_crossfade"


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

    rollback_snapshot = _player_snapshot_best_effort(runtime)
    preserved_layer_enabled = {
        layer_id: _player_layer_enabled_best_effort(runtime, layer_id)
        for layer_id in ("low", "mid")
    }
    crossfade_scheduled = False
    try:
        if runtime.output.is_running:
            if not _playback_guard_matches(runtime, settings, guard):
                runtime.transition_warning = (
                    "목소리 전환을 건너뛰었습니다. 재생 중 선택된 스택이 바뀌었습니다. "
                    "기존 목소리를 유지합니다."
                )
                _log_event_best_effort(
                    runtime,
                    "recording.playback_refresh_skipped",
                    _transition_skip_evidence(runtime, settings, outcome, guard),
                )
                return
            voice = read_wav(runtime.paths.voice_playback)
            duration_frames = int(
                settings.voice_stack.transition_seconds * settings.audio.sample_rate
            )
            transition_target_id = _voice_stack_path(outcome) or "voice-stack"
            ready_evidence = _transition_ready_evidence(runtime, voice, guard)
            superseded = start_ready_voice_stack_crossfade(
                runtime.player,
                voice,
                transition_seconds=settings.voice_stack.transition_seconds,
                sample_rate=settings.audio.sample_rate,
                transition_target_id=transition_target_id,
            )
            crossfade_scheduled = True
            _log_event_best_effort(
                runtime,
                "recording.voice_transition_started",
                {
                    "status": "applying",
                    "source_layer_id": "voice",
                    "target_layer_id": "voice",
                    "transition_source_id": _transition_source_id(runtime, settings, guard),
                    "transition_target_id": transition_target_id,
                    "transition_seconds": settings.voice_stack.transition_seconds,
                    "duration_frames": duration_frames,
                    "crossfade_scheduled": True,
                    "reason": "output_running_guard_matched_next_voice_ready",
                    "previous_transition_target_id": superseded,
                    **ready_evidence,
                },
            )
            runtime.transition_warning = None
        else:
            runtime.player.load_rendered_layers(rendered_layer_paths(runtime.paths))
            runtime.transition_warning = None
        apply_player_layer_settings(runtime, settings)
        if crossfade_scheduled:
            for layer_id, enabled in preserved_layer_enabled.items():
                _restore_player_layer_enabled_best_effort(runtime, layer_id, enabled)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        _restore_player_snapshot_best_effort(runtime, rollback_snapshot)
        runtime.transition_warning = (
            "목소리 전환을 적용하지 못했습니다. 기존 목소리를 유지합니다."
        )
        _log_event_best_effort(
            runtime,
            "recording.playback_refresh_failed",
            {
                "error": str(exc),
                "output_running": runtime.output.is_running,
            },
        )


def start_ready_voice_stack_crossfade(
    player: Any,
    next_voice: Any,
    *,
    transition_seconds: float,
    sample_rate: int,
    transition_target_id: str,
) -> str | None:
    duration_frames = int(transition_seconds * sample_rate)
    return player.start_voice_crossfade(
        next_voice,
        duration_frames=duration_frames,
        transition_target_id=transition_target_id,
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


def _transition_source_id(
    runtime: SecretPondRuntime,
    settings: Any,
    guard: RecordingPlaybackGuard | None,
) -> str:
    if guard is not None:
        return guard.current_stack_id
    return runtime.voice_stack.transition_guard_state(settings).current_stack_id


def _transition_ready_evidence(
    runtime: SecretPondRuntime,
    next_voice: Any,
    guard: RecordingPlaybackGuard | None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "output_running": runtime.output.is_running,
        "guard_matched": True,
        "playback_session_id": None if guard is None else guard.playback_session_id,
        "guard_current_stack_id": None if guard is None else guard.current_stack_id,
        "next_voice_frames": getattr(next_voice, "frames", None),
    }
    snapshot = _player_snapshot_best_effort(runtime)
    if snapshot is None:
        return evidence

    evidence["frame_cursor_at_ready"] = getattr(snapshot, "frame_cursor", None)
    evidence["player_was_playing"] = getattr(snapshot, "playing", None)
    layers = getattr(snapshot, "layers", None)
    if layers is not None and "voice" in layers:
        evidence["current_voice_frames"] = getattr(layers["voice"], "frames", None)
    return evidence


def _transition_skip_evidence(
    runtime: SecretPondRuntime,
    settings: Any,
    outcome: Any,
    guard: RecordingPlaybackGuard | None,
) -> dict[str, Any]:
    current = runtime.voice_stack.transition_guard_state(settings)
    return {
        "reason": "playback_guard_mismatch",
        "crossfade_scheduled": False,
        "output_running": runtime.output.is_running,
        "guard_matched": False,
        "voice_stack_path": _voice_stack_path(outcome),
        "guard_playback_session_id": None if guard is None else guard.playback_session_id,
        "current_playback_session_id": current.playback_session_id,
        "guard_current_stack_id": None if guard is None else guard.current_stack_id,
        "current_stack_id": current.current_stack_id,
    }


def _player_snapshot_best_effort(runtime: SecretPondRuntime) -> Any | None:
    try:
        snapshot = runtime.player.snapshot
    except AttributeError:
        return None
    try:
        return snapshot()
    except Exception:
        return None


def _restore_player_snapshot_best_effort(runtime: SecretPondRuntime, snapshot: Any | None) -> None:
    if snapshot is None:
        return
    try:
        restore = runtime.player.restore
    except AttributeError:
        return
    try:
        restore(snapshot)
    except Exception:
        return


def _player_layer_enabled_best_effort(runtime: SecretPondRuntime, layer_id: str) -> bool | None:
    try:
        states = runtime.player.layer_states
    except AttributeError:
        return None
    try:
        return bool(states[layer_id].enabled)
    except (KeyError, AttributeError, TypeError):
        return None


def _restore_player_layer_enabled_best_effort(
    runtime: SecretPondRuntime,
    layer_id: str,
    enabled: bool | None,
) -> None:
    if enabled is None:
        return
    try:
        set_enabled_immediate = runtime.player.set_enabled_immediate
    except AttributeError:
        try:
            runtime.player.set_enabled(layer_id, enabled)
        except Exception:
            return
        return
    try:
        set_enabled_immediate(layer_id, enabled)
    except Exception:
        return


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
