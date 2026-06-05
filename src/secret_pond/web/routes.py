from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import ValidationError

from secret_pond.audio.device_readiness import build_device_warnings
from secret_pond.audio.devices import AudioDeviceInfo
from secret_pond.audio.source_library import (
    category_config,
    delete_source_file,
    select_source,
    selected_source_path,
    source_file_is_selected,
    source_library_payload,
    upload_source_file,
)
from secret_pond.config import AppSettings, DeviceSettings
from secret_pond.services.device_switcher import DeviceSelectionError, apply_runtime_devices
from secret_pond.services.recording_transaction import (
    RecordingControlError,
)
from secret_pond.services.recording_workflow import run_recording_workflow
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_apply import SettingsApplyError, apply_draft_settings
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
        outcome = _run_recording_control(runtime, runtime.controller.stop_recording)
        return {
            "outcome": outcome_payload(outcome),
            "state": state_payload(runtime),
        }


@router.post("/recording/poll-auto-stop")
def poll_auto_stop(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_recording_control(runtime, runtime.controller.poll_auto_stop)
        return {
            "outcome": outcome_payload(outcome),
            "state": state_payload(runtime),
        }


@router.get("/devices")
def get_devices(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        return _devices_payload(runtime, runtime.settings_store.load().active)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"audio devices unavailable: {exc}",
        ) from exc


@router.put("/devices")
def update_devices(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        current = runtime.settings_store.load()
        try:
            devices = _device_settings_from_payload(current.active.devices, payload)
            _validate_device_selection(runtime, current.active.devices, devices)
            apply_runtime_devices(runtime, devices)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DeviceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "settings": settings_payload(runtime),
            "state": state_payload(runtime),
            "devices": _devices_payload(runtime, runtime.settings_store.load().active),
        }


@router.get("/diagnostics")
def get_diagnostics(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return _diagnostics_payload(runtime)


@router.get("/sources")
def get_sources(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        settings = runtime.settings_store.load().draft
        return source_library_payload(runtime.paths, settings)


@router.put("/sources/{category}/select")
def select_source_file(
    request: Request,
    category: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        config = category_config(category)
        relative_path = payload.get("path")
        if relative_path is not None and not isinstance(relative_path, str):
            raise ValueError("path must be a string or null")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with runtime.operation_lock:
        try:
            state = runtime.settings_store.patch_draft(
                lambda draft: _select_source_draft(runtime, draft, config.id, relative_path),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        runtime.settings_state = state
        return {
            "settings": settings_payload(runtime),
            "sources": source_library_payload(runtime.paths, state.draft),
        }


@router.post("/sources/{category}/files", status_code=201)
def upload_source(
    request: Request,
    category: str,
    filename: str,
    select: bool = False,
    body: bytes = Body(...),
) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        config = category_config(category)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with runtime.operation_lock:
        try:
            file_payload = upload_source_file(
                runtime.paths,
                config.id,
                filename=filename,
                content=body,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if select:
            settings_state = runtime.settings_store.patch_draft(
                lambda draft: select_source(draft, config.id, file_payload["path"]),
            )
            runtime.settings_state = settings_state
        else:
            settings_state = runtime.settings_store.load()
        return {
            "file": file_payload,
            "settings": settings_payload(runtime),
            "sources": source_library_payload(runtime.paths, settings_state.draft),
        }


@router.delete("/sources/{category}/files")
def delete_source(
    request: Request,
    category: str,
    path: str,
) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        config = category_config(category)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with runtime.operation_lock:
        settings_state = runtime.settings_store.load()
        try:
            if source_file_is_selected(runtime.paths, settings_state.active, config.id, path):
                raise PermissionError("cannot delete the active source file")
            if source_file_is_selected(runtime.paths, settings_state.draft, config.id, path):
                raise PermissionError("cannot delete the draft source file")
            delete_source_file(runtime.paths, settings_state.active, config.id, path)
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "sources": source_library_payload(runtime.paths, settings_state.draft),
        }


@router.post("/playback/start")
def start_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            runtime.output.start()
        except (RuntimeError, ValueError, OSError) as exc:
            _log_playback_event(runtime, "playback.start_failed", error=str(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _log_playback_event(runtime, "playback.started")
        return {"state": state_payload(runtime)}


@router.post("/playback/stop")
def stop_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            runtime.output.stop()
        except (RuntimeError, ValueError, OSError) as exc:
            _log_playback_event(runtime, "playback.stop_failed", error=str(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _log_playback_event(runtime, "playback.stopped")
        return {"state": state_payload(runtime)}


@router.post("/playback/restart")
def restart_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        if not runtime.output.is_running:
            detail = "output must be running before restart"
            _log_playback_event(runtime, "playback.restart_failed", error=detail)
            raise HTTPException(status_code=409, detail=detail)

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
            raise HTTPException(status_code=409, detail=detail) from exc
        _log_playback_event(runtime, "playback.restarted")
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


@router.post("/settings/reset-draft")
@router.post("/settings/reset")
def reset_draft_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with _maintenance_operation(runtime):
        if runtime.controller.is_recording:
            raise HTTPException(
                status_code=409,
                detail="cannot reset draft settings while recording",
            )
        state = runtime.settings_store.reset_draft()
        runtime.settings_state = state
        return {"settings": settings_payload(runtime)}


@router.post("/participants/reset")
def reset_participant_count(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with _maintenance_operation(runtime):
        if runtime.controller.is_recording:
            raise HTTPException(
                status_code=409,
                detail="cannot reset participant count while recording",
            )
        previous_count = runtime.participants.get_count()
        participant_count = runtime.participants.reset()
        _log_event_best_effort(
            runtime,
            "participants.reset",
            {"previous_count": previous_count, "count": participant_count},
        )
        return {"state": state_payload(runtime)}


@router.post("/settings/apply")
@router.post("/settings/apply-and-restart")
def apply_and_restart(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            apply_draft_settings(runtime)
        except SettingsApplyError as exc:
            raise HTTPException(status_code=409, detail=exc.detail) from exc
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
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _run_recording_control(runtime: SecretPondRuntime, fn):
    try:
        return run_recording_workflow(runtime, fn)
    except RecordingControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@contextmanager
def _maintenance_operation(runtime: SecretPondRuntime) -> Iterator[None]:
    acquired = runtime.operation_lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="maintenance actions are unavailable while another operation is running",
        )
    try:
        yield
    finally:
        runtime.operation_lock.release()


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return


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


def _devices_payload(runtime: SecretPondRuntime, settings: AppSettings) -> dict[str, Any]:
    input_devices = runtime.device_registry.list_input_devices()
    output_devices = runtime.device_registry.list_output_devices()
    selected_input = runtime.device_registry.validate_input(settings.devices.input_device_id)
    selected_output = runtime.device_registry.validate_output(settings.devices.output_device_id)
    return {
        "input_devices": [_device_payload(device) for device in input_devices],
        "output_devices": [_device_payload(device) for device in output_devices],
        "selected_input_device": _device_payload(selected_input),
        "selected_output_device": _device_payload(selected_output),
        "warnings": _device_warnings(selected_input, selected_output, settings),
    }


def _device_settings_from_payload(
    current: DeviceSettings,
    payload: dict[str, Any],
) -> DeviceSettings:
    allowed = {"input_device_id", "output_device_id"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown device setting: {unknown[0]}")
    updates: dict[str, str | None] = {}
    for key in allowed:
        if key not in payload:
            continue
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a string or null")
        updates[key] = value or None
    return current.model_copy(update=updates)


def _select_source_draft(
    runtime: SecretPondRuntime,
    draft: AppSettings,
    category: str,
    relative_path: str | None,
) -> AppSettings:
    next_draft = select_source(draft, category, relative_path)
    if relative_path is not None:
        selected = selected_source_path(runtime.paths, next_draft, category)
        if selected is None or not selected.exists():
            raise FileNotFoundError(f"source file does not exist: {relative_path}")
    return next_draft


def _validate_device_selection(
    runtime: SecretPondRuntime,
    current: DeviceSettings,
    devices: DeviceSettings,
) -> None:
    if (
        devices.input_device_id != current.input_device_id
        and devices.input_device_id is not None
    ):
        selected_input = runtime.device_registry.validate_input(devices.input_device_id)
        if selected_input is None:
            raise ValueError(f"input device is unavailable: {devices.input_device_id}")
    if (
        devices.output_device_id != current.output_device_id
        and devices.output_device_id is not None
    ):
        selected_output = runtime.device_registry.validate_output(devices.output_device_id)
        if selected_output is None:
            raise ValueError(f"output device is unavailable: {devices.output_device_id}")


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
        "host_api_name": device.host_api_name,
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
    warnings.extend(build_device_warnings(input_device, output_device, settings))
    return warnings


def _diagnostics_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    paths = runtime.paths
    settings = runtime.settings_store.load().active
    low_source = selected_source_path(paths, settings, "low") or paths.low_source
    mid_source = selected_source_path(paths, settings, "mid") or paths.mid_source
    voice_source = selected_source_path(paths, settings, "voice_stack") or paths.voice_stack_raw
    return {
        "sources": [
            _file_status_payload(paths.root, "low", "Low Source", low_source),
            _file_status_payload(paths.root, "mid", "Mid Source", mid_source),
            _file_status_payload(paths.root, "voice", "Voice Stack", voice_source),
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
