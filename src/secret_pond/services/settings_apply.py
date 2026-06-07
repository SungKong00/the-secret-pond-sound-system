from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from secret_pond.services.device_switcher import DEVICE_CHANGES_SYSTEM_PANEL_DETAIL
from secret_pond.services.file_snapshots import (
    FileSnapshot,
    capture_file_snapshot,
    restore_file_snapshot,
)
from secret_pond.services.player_settings import apply_player_layer_settings
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths
from secret_pond.services.settings_changes import SettingsChangePlan, classify_settings_change
from secret_pond.services.settings_store import SettingsState
from secret_pond.services.voice_raw_preview import prepare_voice_raw_preview


@dataclass(frozen=True)
class SettingsApplyResult:
    settings_state: SettingsState
    change_plan: SettingsChangePlan
    was_output_running: bool
    output_running: bool


class SettingsApplyError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        change_plan: SettingsChangePlan,
        was_output_running: bool,
        output_running: bool,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.change_plan = change_plan
        self.was_output_running = was_output_running
        self.output_running = output_running


def apply_draft_settings(runtime: SecretPondRuntime) -> SettingsApplyResult:
    if runtime.controller.is_recording:
        current = runtime.settings_store.load()
        change_plan = classify_settings_change(current.active, current.draft)
        raise SettingsApplyError(
            "cannot apply settings while recording",
            change_plan=change_plan,
            was_output_running=runtime.output.is_running,
            output_running=runtime.output.is_running,
        )

    current = runtime.settings_store.load()
    draft = current.draft
    change_plan = classify_settings_change(current.active, draft)
    was_running = runtime.output.is_running
    voice_raw_preview_path = runtime.voice_raw_preview_path
    if change_plan.runtime_config_changed:
        detail = (
            "audio output format changes require an app restart; " +
            DEVICE_CHANGES_SYSTEM_PANEL_DETAIL
        )
        _log_event_best_effort(
            runtime,
            "settings.apply_rejected",
            {
                "reason": detail,
                "runtime_config_changed": True,
                "changed_runtime_fields": change_plan.changed_runtime_fields,
                "was_output_running": was_running,
                "output_running": runtime.output.is_running,
            },
        )
        raise SettingsApplyError(
            detail,
            change_plan=change_plan,
            was_output_running=was_running,
            output_running=runtime.output.is_running,
        )

    player_snapshot = runtime.player.snapshot()
    staged = None
    raw_snapshot: FileSnapshot | None = None
    try:
        if was_running:
            runtime.output.stop()
        if current.active.voice_stack.loop_seconds != draft.voice_stack.loop_seconds:
            raw_snapshot = capture_file_snapshot(runtime.paths.voice_stack_raw)
            runtime.voice_stack.ensure_initialized(draft)
        staged = runtime.renderer.stage_all(draft)
        staged.commit()
        if voice_raw_preview_path is None:
            if was_running:
                runtime.player.reload_and_restart(rendered_layer_paths(runtime.paths))
            else:
                runtime.player.load_rendered_layers(rendered_layer_paths(runtime.paths))
            apply_player_layer_settings(runtime, draft, reset_realtime_trims=True)
        else:
            prepare_voice_raw_preview(runtime, voice_raw_preview_path, draft)
        if was_running:
            runtime.output.start()

        state = runtime.settings_store.save(SettingsState(active=draft, draft=draft))
        runtime.playback_render_settings = draft
        runtime.apply_settings_state(state)
    except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
        detail = _rollback_apply_failure(
            runtime,
            staged=staged,
            player_snapshot=player_snapshot,
            restore_output=was_running,
            cause=exc,
        )
        if raw_snapshot is not None:
            restore_file_snapshot(runtime.paths.voice_stack_raw, raw_snapshot)
        _log_event_best_effort(
            runtime,
            "settings.apply_failed",
            {
                "error": detail,
                "runtime_config_changed": change_plan.runtime_config_changed,
                "changed_sections": change_plan.changed_sections,
                "was_output_running": was_running,
                "output_running": runtime.output.is_running,
                "output_restore_attempted": was_running,
            },
        )
        raise SettingsApplyError(
            detail,
            change_plan=change_plan,
            was_output_running=was_running,
            output_running=runtime.output.is_running,
        ) from exc
    if staged is not None:
        staged.cleanup()

    _log_event_best_effort(
        runtime,
        "settings.applied",
        {
            "changed_sections": change_plan.changed_sections,
            "runtime_config_changed": change_plan.runtime_config_changed,
            "was_output_running": was_running,
            "output_running": runtime.output.is_running,
        },
    )
    return SettingsApplyResult(
        settings_state=state,
        change_plan=change_plan,
        was_output_running=was_running,
        output_running=runtime.output.is_running,
    )


def _rollback_apply_failure(
    runtime: SecretPondRuntime,
    *,
    staged: Any,
    player_snapshot: Any,
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


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
