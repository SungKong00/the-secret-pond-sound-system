from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ValidationError

from secret_pond.audio.source_library import (
    SourceCategoryConfig,
    category_config,
    source_library_payload,
)
from secret_pond.config import AppSettings
from secret_pond.services import maintenance, playback_control
from secret_pond.services.device_inventory import device_inventory_payload
from secret_pond.services.device_switcher import (
    DeviceSelectionError,
    apply_runtime_devices,
    device_settings_from_payload,
)
from secret_pond.services.diagnostics import diagnostics_payload
from secret_pond.services.live_graph_eq import (
    live_graph_eq_state,
    mark_slow_live_graph_eq_requests,
    run_due_live_graph_eq_update,
)
from secret_pond.services.playback_apply_mode import (
    PlaybackApplyMode,
    StagedGraphEqChoice,
    apply_playback_apply_mode,
    parse_playback_apply_mode,
)
from secret_pond.services.recording_transaction import (
    RecordingControlError,
)
from secret_pond.services.recording_workflow import (
    apply_ready_voice_stack_transition,
    read_rendered_layer_buffers,
    run_recording_workflow,
)
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_apply import SettingsApplyError, apply_draft_settings
from secret_pond.services.settings_draft import (
    SettingsDraftUpdateError,
    SettingsDraftValidationError,
)
from secret_pond.services.settings_draft import (
    update_draft_settings as save_draft_settings,
)
from secret_pond.services.settings_presets import (
    PresetNotFoundError,
    PresetSourceMissingError,
    PresetStore,
)
from secret_pond.services.settings_store import SettingsState
from secret_pond.services.source_library_mutations import (
    SourceLibraryMutationError,
    delete_source_file_from_library,
    rename_source_file_in_library,
    select_source_file_and_update_draft,
    upload_source_file_and_maybe_select,
)
from secret_pond.services.storage_mode import (
    StorageModeChangeError,
    apply_voice_stack_mode,
    parse_voice_stack_mode,
)
from secret_pond.services.voice_raw_preview import start_voice_raw_preview
from secret_pond.web.state import (
    SettingsPayloadUnavailable,
    StatePayloadUnavailable,
    load_settings_state,
    outcome_payload,
    settings_payload,
    state_payload,
    state_version_payload,
)

router = APIRouter(prefix="/api")

SOURCE_MUTATION_ERRORS = (
    FileNotFoundError,
    FileExistsError,
    PermissionError,
    SourceLibraryMutationError,
    OSError,
    RuntimeError,
    ValueError,
)


class PlaybackApplyModeRequest(BaseModel):
    mode: PlaybackApplyMode
    staged_graph_eq: StagedGraphEqChoice = "discard"


class LiveGraphEqTickRequest(BaseModel):
    now_ms: int | None = None


class SettingsPresetCreateRequest(BaseModel):
    name: str


class SettingsPresetUpdateRequest(BaseModel):
    name: str | None = None


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
        runtime.mark_state_changed()
        return {"state": _state_payload(runtime)}


@router.post("/input/disarm")
def disarm_input(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_control(runtime, runtime.controller.disarm_input)
        runtime.mark_state_changed()
        return {
            "outcome": outcome_payload(outcome),
            "state": _state_payload(runtime),
        }


@router.post("/recording/start")
def start_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_control(runtime, runtime.controller.start_recording)
        runtime.mark_state_changed()
        return {"state": _state_payload(runtime)}


@router.post("/recording/stop")
def stop_recording(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_recording_control(runtime, runtime.controller.stop_recording)
        runtime.mark_state_changed()
        return {
            "outcome": outcome_payload(outcome),
            "state": _state_payload(runtime),
        }


@router.post("/recording/poll-auto-stop")
def poll_auto_stop(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        outcome = _run_recording_control(runtime, runtime.controller.poll_auto_stop)
        if outcome is not None:
            runtime.mark_state_changed()
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
        visible_state_before = _visible_runtime_state_fingerprint(runtime)
        current = _settings_state(runtime)
        try:
            devices = device_settings_from_payload(current.active.devices, payload)
            settings_state = apply_runtime_devices(runtime, devices)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DeviceSelectionError as exc:
            _mark_if_visible_runtime_state_changed(runtime, visible_state_before)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            _mark_if_visible_runtime_state_changed(runtime, visible_state_before)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if settings_state.active.devices != current.active.devices:
            runtime.mark_state_changed()
        return {
            "settings": _settings_payload(runtime, settings_state),
            "state": _state_payload(runtime, settings_state),
            "devices": _devices_payload(runtime, settings_state.active),
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
        return _sources_payload(runtime, _settings_state(runtime))


@router.put("/voice-stack/mode")
def update_voice_stack_mode(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        mode = parse_voice_stack_mode(payload.get("mode"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with runtime.operation_lock:
        try:
            settings_state = apply_voice_stack_mode(runtime, mode)
        except StorageModeChangeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        runtime.mark_state_changed()
        return {
            "settings": _settings_payload(runtime, settings_state),
            "state": _state_payload(runtime, settings_state),
        }


@router.put("/sources/{category}/select")
def select_source_file(
    request: Request,
    category: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    runtime = _runtime(request)
    config = _source_category_config(category)
    relative_path = _source_select_path(payload)

    with runtime.operation_lock:
        try:
            state = select_source_file_and_update_draft(
                runtime,
                config.id,
                relative_path,
            )
            _update_pending_voice_transition_after_source_select(
                runtime,
                config.id,
                relative_path,
                state,
            )
        except SOURCE_MUTATION_ERRORS as exc:
            raise _source_mutation_http_exception(exc) from exc
        runtime.mark_state_changed()
        return _source_settings_payload(runtime, state)


@router.post("/sources/{category}/files", status_code=201)
def upload_source(
    request: Request,
    category: str,
    filename: str,
    select: bool = False,
    body: bytes = Body(...),
) -> dict[str, Any]:
    runtime = _runtime(request)
    config = _source_category_config(category)

    with runtime.operation_lock:
        try:
            result = upload_source_file_and_maybe_select(
                runtime,
                config.id,
                filename=filename,
                content=body,
                select_after_upload=select,
            )
        except SOURCE_MUTATION_ERRORS as exc:
            raise _source_mutation_http_exception(exc) from exc
        runtime.mark_state_changed()
        return {
            "file": result.file,
            **_source_settings_payload(runtime, result.settings_state),
        }


@router.delete("/sources/{category}/files")
def delete_source(
    request: Request,
    category: str,
    path: str,
) -> dict[str, Any]:
    runtime = _runtime(request)
    config = _source_category_config(category)
    with runtime.operation_lock:
        settings_state = _settings_state(runtime)
        try:
            referencing_presets = PresetStore(runtime.paths).preset_names_referencing_source(path)
            if referencing_presets:
                names = ", ".join(referencing_presets)
                raise PermissionError(
                    f"source file is used by presets: {names}. "
                    "Delete or update those presets first."
                )
            delete_source_file_from_library(
                runtime,
                config.id,
                path,
                settings_state=settings_state,
            )
        except SOURCE_MUTATION_ERRORS as exc:
            raise _source_mutation_http_exception(exc) from exc
        runtime.mark_state_changed()
        return {
            **state_version_payload(runtime),
            "sources": _sources_payload(runtime, settings_state),
        }


@router.patch("/sources/{category}/files")
def rename_source(
    request: Request,
    category: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    runtime = _runtime(request)
    config = _source_category_config(category)
    relative_path, stem = _source_rename_payload(payload)

    with runtime.operation_lock:
        settings_state = _settings_state(runtime)
        try:
            result = rename_source_file_in_library(
                runtime,
                config.id,
                relative_path,
                stem,
                settings_state=settings_state,
            )
            PresetStore(runtime.paths).replace_source_path(relative_path, result.relative_path)
            settings_state = result.settings_state
        except SOURCE_MUTATION_ERRORS as exc:
            raise _source_mutation_http_exception(exc) from exc
        runtime.mark_state_changed()
        return {
            "settings": _settings_payload(runtime, settings_state),
            "state": _state_payload(runtime, settings_state),
            "sources": _sources_payload(runtime, settings_state),
        }


@router.post("/voice-stack/add-source")
def add_voice_raw_to_stack(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    relative_path = _voice_raw_path_from_payload(payload)

    with runtime.operation_lock:
        current = _settings_state(runtime)
        active = current.active.model_copy(deep=True)
        try:
            result = runtime.voice_stack_service.add_vr_to_stack(relative_path, active)
        except SOURCE_MUTATION_ERRORS as exc:
            raise _source_mutation_http_exception(exc) from exc
        draft = current.draft.model_copy(
            update={
                "sources": current.draft.sources.model_copy(
                    update={
                        "voice_raw_path": active.sources.voice_raw_path,
                        "voice_stack_path": active.sources.voice_stack_path,
                    },
                )
            },
            deep=True,
        )
        settings_state = runtime.settings_store.save(SettingsState(active=active, draft=draft))
        runtime.apply_settings_state(settings_state)
        _update_pending_voice_transition_after_source_select(
            runtime,
            "voice_stack",
            result.selected_voice_stack_path,
            settings_state,
        )
        runtime.mark_state_changed()
        return {
            "add_to_stack": {"voice_stack_path": result.selected_voice_stack_path},
            "settings": _settings_payload(runtime, settings_state),
            "state": _state_payload(runtime, settings_state),
            "sources": _sources_payload(runtime, settings_state),
        }


@router.post("/voice-raw/preview")
def preview_voice_raw(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)

    with runtime.operation_lock:
        settings_state = _settings_state(runtime)
        relative_path = _voice_raw_path_from_payload(
            payload,
            fallback=settings_state.active.sources.voice_raw_path,
        )
        try:
            start_voice_raw_preview(runtime, relative_path, settings_state.active)
        except SOURCE_MUTATION_ERRORS as exc:
            raise _source_mutation_http_exception(exc) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        runtime.mark_state_changed()
        return {
            "preview": {"voice_raw_path": relative_path, "playing": True},
            "state": _state_payload(runtime, settings_state),
        }


@router.post("/playback/start")
def start_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_playback_control(runtime, playback_control.start_playback)
        runtime.mark_state_changed()
        return {"state": _state_payload(runtime)}


@router.post("/playback/stop")
def stop_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_playback_control(runtime, playback_control.stop_playback)
        runtime.mark_state_changed()
        return {"state": _state_payload(runtime)}


@router.post("/playback/restart")
def restart_playback(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        _run_playback_control(runtime, playback_control.restart_playback)
        runtime.mark_state_changed()
        return {"state": _state_payload(runtime)}


@router.post("/playback/seek")
def seek_playback(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        progress = _seek_progress(payload)
        _run_playback_control(
            runtime,
            lambda active_runtime: playback_control.seek_playback(active_runtime, progress),
        )
        runtime.mark_state_changed()
        return {"state": _state_payload(runtime)}


@router.post("/playback/live-graph-eq/tick")
def tick_live_graph_eq(
    request: Request,
    payload: LiveGraphEqTickRequest | None = None,
) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        if runtime.controller.settings.playback.apply_mode != "live":
            return {"applied": False, "state": _state_payload(runtime)}
        applied_request = run_due_live_graph_eq_update(
            runtime,
            now_ms=payload.now_ms if payload is not None else None,
        )
        slow = mark_slow_live_graph_eq_requests(
            runtime,
            now_ms=payload.now_ms if payload is not None else None,
        )
        live_state = live_graph_eq_state(runtime)
        if applied_request is not None or slow or live_state.failure_warning:
            runtime.mark_state_changed()
        return {
            "applied": applied_request is not None,
            "state": _state_payload(runtime),
        }


@router.put("/playback/apply-mode")
def update_playback_apply_mode(
    request: Request,
    payload: PlaybackApplyModeRequest,
) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        mode = parse_playback_apply_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with runtime.operation_lock:
        try:
            settings_state = apply_playback_apply_mode(
                runtime,
                mode,
                staged_graph_eq=payload.staged_graph_eq,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        runtime.mark_state_changed()
        return {
            "settings": _settings_payload(runtime, settings_state),
            "state": _state_payload(runtime, settings_state),
        }


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return {"settings": _settings_payload(runtime)}


@router.get("/settings/presets")
def list_settings_presets(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        return _settings_presets_response(runtime)


@router.post("/settings/presets", status_code=201)
def create_settings_preset(
    request: Request,
    payload: SettingsPresetCreateRequest,
) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            preset = PresetStore(runtime.paths).create_from_draft(
                payload.name,
                _settings_state(runtime).draft,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "preset": preset.model_dump(mode="json"),
            **_settings_presets_response(runtime),
        }


@router.patch("/settings/presets/{preset_id}")
def update_settings_preset(
    request: Request,
    preset_id: str,
    payload: SettingsPresetUpdateRequest,
) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            preset = PresetStore(runtime.paths).update_from_draft(
                preset_id,
                payload.name,
                _settings_state(runtime).draft,
            )
        except PresetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "preset": preset.model_dump(mode="json"),
            **_settings_presets_response(runtime),
        }


@router.delete("/settings/presets/{preset_id}")
def delete_settings_preset(request: Request, preset_id: str) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        try:
            PresetStore(runtime.paths).delete(preset_id)
        except PresetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _settings_presets_response(runtime)


@router.post("/settings/presets/{preset_id}/load")
def load_settings_preset(request: Request, preset_id: str) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        current = _settings_state(runtime)
        if current.active.playback.apply_mode != "stable":
            raise HTTPException(
                status_code=409,
                detail="presets can be loaded only in Stable mode",
            )
        try:
            next_state = PresetStore(runtime.paths).load_to_draft(preset_id, current)
            saved_state = runtime.settings_store.save(next_state)
        except PresetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PresetSourceMissingError as exc:
            raise HTTPException(
                status_code=409,
                detail={"missing_sources": exc.missing_sources},
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        runtime.settings_state = saved_state
        runtime.mark_state_changed()
        return _source_settings_payload(runtime, saved_state)


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
            settings_state = save_draft_settings(runtime, draft, current=current)
        except SettingsDraftValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SettingsDraftUpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        runtime.mark_state_changed()
        return _settings_response_payload(runtime, settings_state)


@router.post("/settings/reset-draft")
@router.post("/settings/reset")
def reset_draft_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        return maintenance.reset_draft_settings(
            runtime,
            build_result=lambda settings_state: _changed_settings_response_payload(
                runtime,
                settings_state,
            ),
        )
    except maintenance.MaintenanceOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/participants/reset")
def reset_participant_count(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        return maintenance.reset_participant_count(
            runtime,
            build_result=lambda _: {"state": _changed_state_payload(runtime)},
        )
    except maintenance.MaintenanceOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/apply")
@router.post("/settings/apply-and-restart")
def apply_and_restart(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        visible_state_before = _visible_runtime_state_fingerprint(runtime)
        try:
            result = apply_draft_settings(runtime)
        except SettingsApplyError as exc:
            _mark_if_visible_runtime_state_changed(runtime, visible_state_before)
            raise HTTPException(status_code=409, detail=exc.detail) from exc
        runtime.mark_state_changed()
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


def _changed_state_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    runtime.mark_state_changed()
    return _state_payload(runtime, settings_state)


def _settings_response_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    return {
        **state_version_payload(runtime),
        "settings": _settings_payload(runtime, settings_state),
    }


def _settings_presets_response(runtime: SecretPondRuntime) -> dict[str, Any]:
    return {
        **state_version_payload(runtime),
        "presets": [
            preset.model_dump(mode="json")
            for preset in PresetStore(runtime.paths).list_presets()
        ],
    }


def _changed_settings_response_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState,
) -> dict[str, Any]:
    runtime.mark_state_changed()
    return _settings_response_payload(runtime, settings_state)


def _sources_payload(runtime: SecretPondRuntime, settings_state: SettingsState) -> dict[str, Any]:
    return source_library_payload(
        runtime.paths,
        settings_state.draft,
        active_settings=settings_state.active,
    )


def _source_category_config(category: str) -> SourceCategoryConfig:
    try:
        return category_config(category)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _source_select_path(payload: dict[str, Any]) -> str | None:
    relative_path = payload.get("path")
    if relative_path is not None and not isinstance(relative_path, str):
        raise HTTPException(status_code=422, detail="path must be a string or null")
    return relative_path


def _seek_progress(payload: dict[str, Any]) -> float:
    raw_progress = payload.get("progress")
    if isinstance(raw_progress, bool) or raw_progress is None:
        raise HTTPException(status_code=422, detail="progress must be a number")
    try:
        return float(raw_progress)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="progress must be a number") from exc


def _source_rename_payload(payload: dict[str, Any]) -> tuple[str, str]:
    relative_path = payload.get("path")
    stem = payload.get("stem")
    if not isinstance(relative_path, str) or not relative_path:
        raise HTTPException(status_code=422, detail="path must be a non-empty string")
    if not isinstance(stem, str) or not stem:
        raise HTTPException(status_code=422, detail="stem must be a non-empty string")
    return relative_path, stem


def _voice_raw_path_from_payload(payload: dict[str, Any], *, fallback: str | None = None) -> str:
    relative_path = payload.get("voice_raw_path")
    if relative_path is None and fallback:
        return fallback
    if not isinstance(relative_path, str) or not relative_path:
        raise HTTPException(status_code=422, detail="voice_raw_path must be a non-empty string")
    return relative_path


def _source_mutation_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        status_code = 404
    elif isinstance(exc, (FileExistsError, PermissionError, SourceLibraryMutationError)):
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail=str(exc))


def _source_settings_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState,
) -> dict[str, Any]:
    return {
        **state_version_payload(runtime),
        "settings": _settings_payload(runtime, settings_state),
        "state": _state_payload(runtime, settings_state),
        "sources": _sources_payload(runtime, settings_state),
    }


def _update_pending_voice_transition_after_source_select(
    runtime: SecretPondRuntime,
    category: str,
    relative_path: str | None,
    settings_state: SettingsState,
) -> None:
    if (
        category == "voice_stack"
        and relative_path is not None
        and runtime.controller.settings.playback.apply_mode == "live"
    ):
        runtime.renderer.render_layer("voice", settings_state.draft)
        if runtime.output.is_running:
            _start_ready_voice_stack_transition(runtime, relative_path)
            runtime.pending_voice_transition_target_id = None
            return
        runtime.pending_voice_transition_target_id = relative_path
        return
    runtime.pending_voice_transition_target_id = None


def _start_ready_voice_stack_transition(
    runtime: SecretPondRuntime,
    transition_target_id: str,
) -> None:
    settings = runtime.controller.settings
    next_layers = read_rendered_layer_buffers(runtime.paths)
    next_voice = next_layers["voice"]
    apply_ready_voice_stack_transition(
        runtime.player,
        next_voice,
        next_layers=next_layers,
        transition_seconds=settings.voice_stack.transition_seconds,
        sample_rate=settings.audio.sample_rate,
        transition_target_id=transition_target_id,
        disabled_policy="loop_boundary",
    )
    runtime.transition_warning = None


def _run_control(runtime: SecretPondRuntime, fn):
    visible_state_before = _visible_runtime_state_fingerprint(runtime)
    try:
        return fn()
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        _mark_if_visible_runtime_state_changed(runtime, visible_state_before)
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _run_recording_control(runtime: SecretPondRuntime, fn):
    visible_state_before = _visible_runtime_state_fingerprint(runtime)
    try:
        return run_recording_workflow(runtime, fn)
    except RecordingControlError as exc:
        _mark_if_visible_runtime_state_changed(runtime, visible_state_before)
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _run_playback_control(runtime: SecretPondRuntime, fn) -> None:
    visible_state_before = _visible_runtime_state_fingerprint(runtime)
    try:
        fn(runtime)
    except playback_control.PlaybackControlError as exc:
        _mark_if_visible_runtime_state_changed(runtime, visible_state_before)
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _devices_payload(runtime: SecretPondRuntime, settings: AppSettings) -> dict[str, Any]:
    return device_inventory_payload(runtime.device_registry, settings)


def _diagnostics_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    settings = _settings_state(runtime).active
    return diagnostics_payload(runtime.paths, settings, runtime.logger)


def _visible_runtime_state_fingerprint(runtime: SecretPondRuntime) -> tuple[Any, ...]:
    latest_status = runtime.output.latest_status
    layer_states = tuple(
        (
            layer_id,
            layer_state.enabled,
            layer_state.realtime_trim_db,
        )
        for layer_id, layer_state in sorted(runtime.player.layer_states.items())
    )
    return (
        runtime.controller.armed,
        runtime.controller.is_recording,
        runtime.controller.last_error,
        runtime.player.frame_cursor,
        runtime.player.is_playing,
        runtime.output.is_running,
        None if latest_status is None else str(latest_status),
        runtime.output.latest_error,
        layer_states,
    )


def _mark_if_visible_runtime_state_changed(
    runtime: SecretPondRuntime,
    before: tuple[Any, ...],
) -> None:
    if _visible_runtime_state_fingerprint(runtime) != before:
        runtime.mark_state_changed()
