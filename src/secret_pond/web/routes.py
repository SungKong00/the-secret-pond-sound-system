from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from secret_pond.services.controller import RecordingOutcome
from secret_pond.services.runtime import SecretPondRuntime

router = APIRouter(prefix="/api")


@router.get("/state")
def get_state(request: Request) -> dict[str, Any]:
    return _state_payload(_runtime(request))


@router.post("/input/arm")
def arm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    runtime.controller.arm_input()
    return {"state": _state_payload(runtime)}


@router.post("/input/disarm")
def disarm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    outcome = _run_control(runtime.controller.disarm_input)
    return {
        "outcome": _outcome_payload(outcome),
        "state": _state_payload(runtime),
    }


@router.post("/recording/start")
def start_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    _run_control(runtime.controller.start_recording)
    return {"state": _state_payload(runtime)}


@router.post("/recording/stop")
def stop_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    outcome = _run_control(runtime.controller.stop_recording)
    return {
        "outcome": _outcome_payload(outcome),
        "state": _state_payload(runtime),
    }


@router.post("/recording/poll-auto-stop")
def poll_auto_stop(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    outcome = _run_control(runtime.controller.poll_auto_stop)
    return {
        "outcome": _outcome_payload(outcome),
        "state": _state_payload(runtime),
    }


def _runtime(request: Request) -> SecretPondRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="runtime is not ready")
    return runtime


def _run_control(fn):
    try:
        return fn()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _state_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    settings_state = runtime.settings_store.load()
    return {
        "armed": runtime.controller.armed,
        "is_recording": runtime.controller.is_recording,
        "recording_elapsed_seconds": runtime.controller.recording_elapsed_seconds,
        "recording_remaining_seconds": runtime.controller.recording_remaining_seconds,
        "last_error": runtime.controller.last_error,
        "participant_count": runtime.participants.get_count(),
        "playback": {
            "frame_cursor": runtime.player.frame_cursor,
            "is_playing": runtime.player.is_playing,
        },
        "settings": {
            "active": settings_state.active.model_dump(mode="json"),
            "draft": settings_state.draft.model_dump(mode="json"),
        },
    }


def _outcome_payload(outcome: RecordingOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
        "accepted": outcome.accepted,
        "duration_seconds": outcome.duration_seconds,
        "reason": outcome.reason,
        "participant_count": outcome.participant_count,
    }
