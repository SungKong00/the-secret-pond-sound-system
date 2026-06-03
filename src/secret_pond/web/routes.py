from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from secret_pond.audio.devices import AudioDeviceInfo
from secret_pond.config import AppSettings
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths
from secret_pond.services.settings_store import SettingsState
from secret_pond.web.state import outcome_payload, settings_payload, state_payload

router = APIRouter(prefix="/api")


@router.get("/state")
def get_state(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return state_payload(runtime)


@router.post("/input/arm")
def arm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        runtime.controller.arm_input()
        return {"state": state_payload(runtime)}


@router.post("/input/disarm")
def disarm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_control(runtime.controller.disarm_input)
        return {
            "outcome": outcome_payload(outcome),
            "state": state_payload(runtime),
        }


@router.post("/recording/start")
def start_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_control(runtime.controller.start_recording)
        return {"state": state_payload(runtime)}


@router.post("/recording/stop")
def stop_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_control(runtime.controller.stop_recording)
        return {
            "outcome": outcome_payload(outcome),
            "state": state_payload(runtime),
        }


@router.post("/recording/poll-auto-stop")
def poll_auto_stop(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_control(runtime.controller.poll_auto_stop)
        return {
            "outcome": outcome_payload(outcome),
            "state": state_payload(runtime),
        }


@router.get("/devices")
def get_devices(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        settings = runtime.settings_store.load().active
        input_devices = runtime.device_registry.list_input_devices()
        output_devices = runtime.device_registry.list_output_devices()
        selected_input = runtime.device_registry.validate_input(settings.devices.input_device_id)
        selected_output = runtime.device_registry.validate_output(settings.devices.output_device_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"audio devices unavailable: {exc}",
        ) from exc

    return {
        "input_devices": [_device_payload(device) for device in input_devices],
        "output_devices": [_device_payload(device) for device in output_devices],
        "selected_input_device": _device_payload(selected_input),
        "selected_output_device": _device_payload(selected_output),
        "warnings": _device_warnings(selected_input, selected_output, settings),
    }


@router.get("/diagnostics")
def get_diagnostics(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return _diagnostics_payload(runtime)


@router.post("/playback/start")
def start_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_playback_control(runtime.output.start)
        return {"state": state_payload(runtime)}


@router.post("/playback/stop")
def stop_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_playback_control(runtime.output.stop)
        return {"state": state_payload(runtime)}


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return {"settings": settings_payload(runtime)}


@router.put("/settings/draft")
def update_draft_settings(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        draft = AppSettings.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    with runtime.operation_lock:
        state = runtime.settings_store.set_draft(draft)
        runtime.settings_state = state
        return {"settings": settings_payload(runtime)}


@router.post("/settings/reset")
def reset_draft_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        state = runtime.settings_store.reset_draft()
        runtime.settings_state = state
        return {"settings": settings_payload(runtime)}


@router.post("/settings/apply-and-restart")
def apply_and_restart(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        if runtime.controller.is_recording:
            raise HTTPException(status_code=409, detail="cannot apply settings while recording")

        current = runtime.settings_store.load()
        draft = current.draft
        if _runtime_configuration_changed(current.active, draft):
            raise HTTPException(
                status_code=409,
                detail=(
                    "audio output format and device changes require an app restart in this MVP"
                ),
            )

        was_running = runtime.output.is_running
        player_snapshot = runtime.player.snapshot()
        staged = None
        try:
            if was_running:
                runtime.output.stop()
            staged = runtime.renderer.stage_all(draft)
            staged.commit()
            runtime.player.reload_and_restart(rendered_layer_paths(runtime.paths))
            _apply_player_layer_settings(runtime, draft)
            runtime.player.set_peak_ceiling(draft.audio.peak_ceiling)
            if was_running:
                runtime.output.start()

            state = runtime.settings_store.save(SettingsState(active=draft, draft=draft))
            runtime.apply_settings_state(state)
        except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
            detail = _rollback_apply_failure(
                runtime,
                staged=staged,
                player_snapshot=player_snapshot,
                restore_output=was_running,
                cause=exc,
            )
            raise HTTPException(status_code=409, detail=detail) from exc
        if staged is not None:
            staged.cleanup()
        return {
            "settings": settings_payload(runtime),
            "state": state_payload(runtime),
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


def _apply_player_layer_settings(runtime: SecretPondRuntime, settings: AppSettings) -> None:
    for layer_id, layer_settings in settings.layers.items():
        runtime.player.set_enabled(layer_id, layer_settings.enabled)


def _rollback_apply_failure(
    runtime: SecretPondRuntime,
    *,
    staged,
    player_snapshot,
    restore_output: bool,
    cause: Exception,
) -> str:
    rollback_errors: list[str] = []
    if runtime.output.is_running:
        try:
            runtime.output.stop()
        except Exception as exc:
            rollback_errors.append(f"output stop during rollback failed: {exc}")
    if staged is not None:
        try:
            staged.rollback()
        except Exception as exc:
            rollback_errors.append(f"render rollback failed: {exc}")
    try:
        runtime.player.restore(player_snapshot)
    except Exception as exc:
        rollback_errors.append(f"player rollback failed: {exc}")
    if restore_output:
        try:
            runtime.output.start()
        except Exception as exc:
            rollback_errors.append(f"output restore failed: {exc}")
    if staged is not None:
        try:
            staged.cleanup()
        except Exception as exc:
            rollback_errors.append(f"render cleanup failed: {exc}")

    detail = str(cause)
    if rollback_errors:
        detail = f"{detail}; rollback issues: {'; '.join(rollback_errors)}"
    return detail


def _device_payload(device: AudioDeviceInfo | None) -> dict[str, Any] | None:
    if device is None:
        return None
    return {
        "id": device.id,
        "name": device.name,
        "kind": device.kind,
        "max_input_channels": device.max_input_channels,
        "max_output_channels": device.max_output_channels,
        "default_sample_rate": device.default_sample_rate,
    }


def _device_warnings(
    input_device: AudioDeviceInfo | None,
    output_device: AudioDeviceInfo | None,
    settings: AppSettings,
) -> list[str]:
    warnings: list[str] = []
    if settings.devices.input_device_id is not None and input_device is None:
        warnings.append("Configured input device is unavailable.")
    if settings.devices.output_device_id is not None and output_device is None:
        warnings.append("Configured output device is unavailable.")
    if output_device and output_device.max_output_channels < settings.audio.channels:
        warnings.append(
            "Selected output supports "
            f"{output_device.max_output_channels} channels, "
            f"but settings request {settings.audio.channels}."
        )
    if output_device and output_device.default_sample_rate not in (
        None,
        settings.audio.sample_rate,
    ):
        warnings.append(
            "Selected output default sample rate is "
            f"{output_device.default_sample_rate}, "
            f"but settings request {settings.audio.sample_rate}."
        )
    return warnings


def _diagnostics_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    paths = runtime.paths
    return {
        "sources": [
            _file_status_payload(paths.root, "low", "Low Source", paths.low_source),
            _file_status_payload(paths.root, "mid", "Mid Source", paths.mid_source),
            _file_status_payload(paths.root, "voice", "Voice Stack", paths.voice_stack_raw),
        ],
        "events": _event_log_payload(runtime),
    }


def _file_status_payload(root: Path, file_id: str, label: str, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "id": file_id,
            "label": label,
            "path": _relative_path(root, path),
            "exists": False,
            "size_bytes": 0,
            "modified_at": None,
        }

    stat = path.stat()
    return {
        "id": file_id,
        "label": label,
        "path": _relative_path(root, path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def _event_log_payload(runtime: SecretPondRuntime, limit: int = 5) -> dict[str, Any]:
    path = runtime.paths.event_log_file
    try:
        events = runtime.logger.read_events()
    except ValueError as exc:
        return {
            "path": _relative_path(runtime.paths.root, path),
            "exists": path.exists(),
            "recent": [],
            "error": str(exc),
        }

    return {
        "path": _relative_path(runtime.paths.root, path),
        "exists": path.exists(),
        "recent": list(reversed(events[-limit:])),
        "error": None,
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _runtime_configuration_changed(active: AppSettings, draft: AppSettings) -> bool:
    return (
        active.audio.sample_rate != draft.audio.sample_rate
        or active.audio.channels != draft.audio.channels
        or active.devices.input_device_id != draft.devices.input_device_id
        or active.devices.output_device_id != draft.devices.output_device_id
    )
