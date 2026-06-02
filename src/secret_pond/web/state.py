from __future__ import annotations

from typing import Any

from secret_pond.services.controller import RecordingOutcome
from secret_pond.services.runtime import SecretPondRuntime


def state_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
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
        "settings": settings_payload(runtime),
    }


def settings_payload(runtime: SecretPondRuntime) -> dict[str, Any]:
    settings_state = runtime.settings_store.load()
    runtime.settings_state = settings_state
    return {
        "active": settings_state.active.model_dump(mode="json"),
        "draft": settings_state.draft.model_dump(mode="json"),
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
