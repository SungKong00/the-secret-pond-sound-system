from __future__ import annotations

from typing import Any

from secret_pond.config import AppSettings
from secret_pond.services.controller import RecordingOutcome
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_changes import (
    SettingsChangePlan,
    classify_settings_change,
    live_preview_reprocessable_field_names,
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
    active_settings = runtime.controller.settings
    playback_timeline = _playback_timeline_payload(
        frame_cursor=runtime.player.frame_cursor,
        sample_rate=active_settings.audio.sample_rate,
        loop_seconds=active_settings.voice_stack.loop_seconds,
    )
    transition_guard = runtime.voice_stack.transition_guard_state(runtime.controller.settings)
    return {
        **state_version_payload(runtime),
        "armed": runtime.controller.armed,
        "is_recording": runtime.controller.is_recording,
        "recording_elapsed_seconds": runtime.controller.recording_elapsed_seconds,
        "recording_remaining_seconds": runtime.controller.recording_remaining_seconds,
        "last_error": runtime.controller.last_error,
        "operator_notices": _operator_notices_payload(runtime),
        "participant_count": participant_count,
        "playback": {
            "frame_cursor": runtime.player.frame_cursor,
            "apply_mode": active_settings.playback.apply_mode,
            **playback_timeline,
            "is_playing": runtime.player.is_playing,
            "rendered_cache_ready": runtime.player.rendered_cache_ready,
            "active_voice_transition_target_id": runtime.player.active_voice_transition_target_id,
            "pending_voice_transition_target_id": runtime.pending_voice_transition_target_id,
            "playback_session_id": transition_guard.playback_session_id,
            "voice_raw_preview_path": runtime.voice_raw_preview_path,
            "transition_warning": runtime.transition_warning,
            "output_running": runtime.output.is_running,
            "output_latest_status": runtime.output.latest_status,
            "output_latest_error": runtime.output.latest_error,
            "live": _playback_live_payload(active_settings),
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


def _operator_notices_payload(runtime: SecretPondRuntime) -> list[dict[str, str]]:
    notices: list[dict[str, str]] = []
    try:
        events = runtime.logger.read_events()
    except (OSError, ValueError):
        return notices

    for event in reversed(events):
        event_type = event.get("event_type")
        if event_type in {
            "system.startup",
            "settings.applied",
            "playback.started",
            "playback.restarted",
        }:
            break
        if event_type != "system.startup_playback_unavailable":
            continue
        error = str(event.get("payload", {}).get("error") or "").strip()
        notices.append(
            {
                "code": "startup_playback_unavailable",
                "severity": "caution",
                "summary": "시작 재생 준비 실패",
                "detail": (
                    "시작 시 재생 캐시를 준비하지 못했습니다. 출력은 꺼진 상태로 유지되며 "
                    "Source Library와 System 패널을 확인한 뒤 적용하세요."
                ),
                "technical": _relative_operator_message(runtime, error),
            }
        )
        break
    return notices


LIVE_EXCLUDED_APPLY_FLOW_FIELDS = [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
    "voice_stack.loop_seconds",
    "sources.low_path",
    "sources.mid_path",
    "sources.voice_raw_path",
    "sources.voice_stack_path",
]

LIVE_EQ_SOURCE_CONTRACT = "Live EQ uses source buffers without playback EQ applied twice."


def _playback_live_payload(settings: AppSettings) -> dict[str, Any]:
    enabled = settings.playback.apply_mode == "live"
    return {
        "enabled": enabled,
        "volume_applies_immediately": enabled,
        "mute_applies_immediately": enabled,
        "seek_applies_immediately": enabled,
        "voice_stack_transition_applies_immediately": enabled,
        "voice_raw_preview_treatment_applies_immediately": enabled,
        "eq_applies_immediately": enabled,
        "excluded_apply_flow": LIVE_EXCLUDED_APPLY_FLOW_FIELDS,
        "eq_source_contract": LIVE_EQ_SOURCE_CONTRACT,
    }


def _relative_operator_message(runtime: SecretPondRuntime, message: str) -> str:
    if not message:
        return message
    root = runtime.paths.root.as_posix()
    return message.replace(f"{root}/", "")


def state_version_payload(runtime: SecretPondRuntime) -> dict[str, int]:
    return {
        "state_epoch": runtime.state_epoch,
        "state_revision": runtime.state_revision,
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


def _playback_timeline_payload(
    *,
    frame_cursor: int,
    sample_rate: int,
    loop_seconds: int,
) -> dict[str, float]:
    duration_seconds = float(loop_seconds)
    position_seconds = 0.0 if sample_rate <= 0 else frame_cursor / sample_rate
    if duration_seconds > 0:
        position_seconds %= duration_seconds
        progress = position_seconds / duration_seconds
    else:
        progress = 0.0
    return {
        "position_seconds": position_seconds,
        "duration_seconds": duration_seconds,
        "progress": progress,
    }


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
        "live_preview_reprocessable_fields": change.live_preview_reprocessable_fields,
        "changed_sections": change.changed_sections,
        "runtime_config_fields": runtime_config_field_names(),
        "live_preview_reprocessable_field_names": live_preview_reprocessable_field_names(),
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
