from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import ValidationError

from secret_pond.audio.source_library import category_config, source_library_payload
from secret_pond.config import AppSettings
from secret_pond.services import maintenance, playback_control
from secret_pond.services.device_inventory import device_inventory_payload
from secret_pond.services.device_switcher import (
    DeviceSelectionError,
    apply_runtime_devices,
    device_settings_from_payload,
)
from secret_pond.services.diagnostics import diagnostics_payload
from secret_pond.services.recording_transaction import (
    RecordingControlError,
)
from secret_pond.services.recording_workflow import run_recording_workflow
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_apply import SettingsApplyError, apply_draft_settings
from secret_pond.services.settings_draft import (
    SettingsDraftUpdateError,
)
from secret_pond.services.settings_draft import (
    update_draft_settings as save_draft_settings,
)
from secret_pond.services.settings_store import SettingsState
from secret_pond.services.source_library_mutations import (
    SourceLibraryMutationError,
    delete_source_file_from_library,
    select_source_file_and_update_draft,
    upload_source_file_and_maybe_select,
)
from secret_pond.web.state import (
    SettingsPayloadUnavailable,
    StatePayloadUnavailable,
    load_settings_state,
    outcome_payload,
    settings_payload,
    state_payload,
)

router = APIRouter(prefix="/api")


@router.get("/state")
def get_state(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return _state_payload(runtime)


@router.post("/input/arm")
def arm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        runtime.controller.arm_input()
        return {"state": _state_payload(runtime)}


@router.post("/input/disarm")
def disarm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_control(runtime.controller.disarm_input)
        return {
            "outcome": outcome_payload(outcome),
            "state": _state_payload(runtime),
        }


@router.post("/recording/start")
def start_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_control(runtime.controller.start_recording)
        return {"state": _state_payload(runtime)}


@router.post("/recording/stop")
def stop_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_recording_control(runtime, runtime.controller.stop_recording)
        return {
            "outcome": outcome_payload(outcome),
            "state": _state_payload(runtime),
        }


@router.post("/recording/poll-auto-stop")
def poll_auto_stop(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_recording_control(runtime, runtime.controller.poll_auto_stop)
        return {
            "outcome": outcome_payload(outcome),
            "state": _state_payload(runtime),
        }


@router.get("/devices")
def get_devices(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        settings = _settings_state(runtime).active
        try:
            return _devices_payload(runtime, settings)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"audio devices unavailable: {exc}",
            ) from exc


@router.put("/devices")
def update_devices(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        current = _settings_state(runtime)
        try:
            devices = device_settings_from_payload(current.active.devices, payload)
            apply_runtime_devices(runtime, devices)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DeviceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "settings": _settings_payload(runtime),
            "state": _state_payload(runtime),
            "devices": _devices_payload(runtime, _settings_state(runtime).active),
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
        settings = _settings_state(runtime)
        return source_library_payload(
            runtime.paths,
            settings.draft,
            active_settings=settings.active,
        )


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
            state = select_source_file_and_update_draft(
                runtime,
                config.id,
                relative_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "settings": _settings_payload(runtime),
            "sources": source_library_payload(
                runtime.paths,
                state.draft,
                active_settings=state.active,
            ),
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
            result = upload_source_file_and_maybe_select(
                runtime,
                config.id,
                filename=filename,
                content=body,
                select_after_upload=select,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SourceLibraryMutationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "file": result.file,
            "settings": _settings_payload(runtime),
            "sources": source_library_payload(
                runtime.paths,
                result.settings_state.draft,
                active_settings=result.settings_state.active,
            ),
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
        settings_state = _settings_state(runtime)
        try:
            delete_source_file_from_library(
                runtime,
                config.id,
                path,
                settings_state=settings_state,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "sources": source_library_payload(
                runtime.paths,
                settings_state.draft,
                active_settings=settings_state.active,
            ),
        }


@router.post("/playback/start")
def start_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            playback_control.start_playback(runtime)
        except playback_control.PlaybackControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"state": _state_payload(runtime)}


@router.post("/playback/stop")
def stop_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            playback_control.stop_playback(runtime)
        except playback_control.PlaybackControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"state": _state_payload(runtime)}


@router.post("/playback/restart")
def restart_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            playback_control.restart_playback(runtime)
        except playback_control.PlaybackControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"state": _state_payload(runtime)}


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return {"settings": _settings_payload(runtime)}


@router.put("/settings/draft")
def update_draft_settings(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        draft = AppSettings.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    with runtime.operation_lock:
        current = _settings_state(runtime)
        try:
            save_draft_settings(runtime, draft, current=current)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SettingsDraftUpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"settings": _settings_payload(runtime)}


@router.post("/settings/reset-draft")
@router.post("/settings/reset")
def reset_draft_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        return maintenance.reset_draft_settings(
            runtime,
            build_result=lambda _: {"settings": _settings_payload(runtime)},
        )
    except maintenance.MaintenanceOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/participants/reset")
def reset_participant_count(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        return maintenance.reset_participant_count(
            runtime,
            build_result=lambda _: {"state": _state_payload(runtime)},
        )
    except maintenance.MaintenanceOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/apply")
@router.post("/settings/apply-and-restart")
def apply_and_restart(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            result = apply_draft_settings(runtime)
        except SettingsApplyError as exc:
            raise HTTPException(status_code=409, detail=exc.detail) from exc
        return {
            "settings": _settings_payload(runtime, result.settings_state),
            "state": _state_payload(runtime, result.settings_state),
        }


def _runtime(request: Request) -> SecretPondRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="runtime is not ready")
    return runtime


def _state_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    try:
        return state_payload(runtime, settings_state)
    except StatePayloadUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _settings_state(runtime: SecretPondRuntime) -> SettingsState:
    try:
        return load_settings_state(runtime)
    except SettingsPayloadUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _settings_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    try:
        return settings_payload(runtime, settings_state)
    except SettingsPayloadUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


def _devices_payload(runtime: SecretPondRuntime, settings: AppSettings) -> dict[str, Any]:
    return device_inventory_payload(runtime.device_registry, settings)


def _diagnostics_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    settings = _settings_state(runtime).active
    return diagnostics_payload(runtime.paths, settings, runtime.logger)
