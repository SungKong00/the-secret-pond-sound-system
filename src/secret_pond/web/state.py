from __future__ import annotations

from typing import Any

from secret_pond.services.controller import RecordingOutcome
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_changes import (
    SettingsChangePlan,
    classify_settings_change,
    runtime_config_field_names,
)
from secret_pond.services.settings_store import SettingsState


class StatePayloadUnavailable(RuntimeError):
    code = "state_unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"state is unavailable: {reason}")


class SettingsPayloadUnavailable(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"settings are unavailable: {reason}")


def state_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    participant_count = _participant_count(runtime)
    settings = _settings_payload(runtime, settings_state)
    return {
        "state_epoch": runtime.state_epoch,
        "state_revision": runtime.state_revision,
        "armed": runtime.controller.armed,
        "is_recording": runtime.controller.is_recording,
        "recording_elapsed_seconds": runtime.controller.recording_elapsed_seconds,
        "recording_remaining_seconds": runtime.controller.recording_remaining_seconds,
        "last_error": runtime.controller.last_error,
        "participant_count": participant_count,
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
        "settings": settings,
    }


def settings_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    if settings_state is None:
        settings_state = load_settings_state(runtime)
    return {
        "active": settings_state.active.model_dump(mode="json"),
        "draft": settings_state.draft.model_dump(mode="json"),
        "change": settings_change_payload(
            classify_settings_change(settings_state.active, settings_state.draft),
        ),
    }


def load_settings_state(runtime: SecretPondRuntime) -> SettingsState:
    try:
        return runtime.settings_store.load()
    except (OSError, ValueError) as exc:
        raise SettingsPayloadUnavailable(str(exc)) from exc


def state_unavailable_payload(error: StatePayloadUnavailable) -> dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": str(error),
        },
    }


def _participant_count(runtime: SecretPondRuntime) -> int:
    try:
        return runtime.participants.get_count()
    except (OSError, ValueError) as exc:
        raise StatePayloadUnavailable(str(exc)) from exc


def _settings_payload(
    runtime: SecretPondRuntime,
    settings_state: SettingsState | None = None,
) -> dict[str, Any]:
    try:
        return settings_payload(runtime, settings_state)
    except SettingsPayloadUnavailable as exc:
        raise StatePayloadUnavailable(exc.reason) from exc
    except (OSError, ValueError) as exc:
        raise StatePayloadUnavailable(str(exc)) from exc


def settings_change_payload(change: SettingsChangePlan) -> dict[str, Any]:
    return {
        "runtime_config_changed": change.runtime_config_changed,
        "changed_runtime_fields": change.changed_runtime_fields,
        "changed_sections": change.changed_sections,
        "runtime_config_fields": runtime_config_field_names(),
    }


def outcome_payload(outcome: RecordingOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
        "accepted": outcome.accepted,
        "duration_seconds": outcome.duration_seconds,
        "reason": outcome.reason,
        "participant_count": outcome.participant_count,
    }
