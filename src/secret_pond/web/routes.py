from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from secret_pond.config import AppSettings
from secret_pond.services.controller import RecordingOutcome
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths
from secret_pond.services.settings_store import SettingsState

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


@router.post("/playback/start")
def start_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    _run_playback_control(runtime.output.start)
    return {"state": _state_payload(runtime)}


@router.post("/playback/stop")
def stop_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    _run_playback_control(runtime.output.stop)
    return {"state": _state_payload(runtime)}


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return {"settings": _settings_payload(_runtime(request))}


@router.put("/settings/draft")
def update_draft_settings(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        draft = AppSettings.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    state = runtime.settings_store.set_draft(draft)
    runtime.settings_state = state
    return {"settings": _settings_payload(runtime)}


@router.post("/settings/reset")
def reset_draft_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    state = runtime.settings_store.reset_draft()
    runtime.settings_state = state
    return {"settings": _settings_payload(runtime)}


@router.post("/settings/apply-and-restart")
def apply_and_restart(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    if runtime.controller.is_recording:
        raise HTTPException(status_code=409, detail="cannot apply settings while recording")
    if runtime.output.is_running:
        raise HTTPException(
            status_code=409,
            detail="cannot apply settings while playback is running",
        )

    current = runtime.settings_store.load()
    draft = current.draft
    if _output_configuration_changed(current.active, draft):
        raise HTTPException(
            status_code=409,
            detail=(
                "output sample rate, channel count, and device changes require "
                "a restart in this MVP"
            ),
        )

    try:
        runtime.renderer.render_all(draft)
        runtime.player.reload_and_restart(rendered_layer_paths(runtime.paths))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    state = runtime.settings_store.save(SettingsState(active=draft, draft=draft))
    runtime.apply_settings_state(state)
    _apply_player_layer_settings(runtime, state.active)
    return {
        "settings": _settings_payload(runtime),
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


def _run_playback_control(fn):
    try:
        return fn()
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _state_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
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
            "output_running": runtime.output.is_running,
            "output_latest_status": runtime.output.latest_status,
            "output_latest_error": runtime.output.latest_error,
            "layers": {
                layer_id: {
                    "enabled": layer_state.enabled,
                    "realtime_trim_db": layer_state.realtime_trim_db,
                }
                for layer_id, layer_state in runtime.player.layer_states.items()
            },
        },
        "settings": _settings_payload(runtime),
    }


def _settings_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    settings_state = runtime.settings_store.load()
    runtime.settings_state = settings_state
    return {
        "active": settings_state.active.model_dump(mode="json"),
        "draft": settings_state.draft.model_dump(mode="json"),
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


def _apply_player_layer_settings(runtime: SecretPondRuntime, settings: AppSettings) -> None:
    for layer_id, layer_settings in settings.layers.items():
        runtime.player.set_enabled(layer_id, layer_settings.enabled)


def _output_configuration_changed(active: AppSettings, draft: AppSettings) -> bool:
    return (
        active.audio.sample_rate != draft.audio.sample_rate
        or active.audio.channels != draft.audio.channels
        or active.devices.output_device_id != draft.devices.output_device_id
    )
