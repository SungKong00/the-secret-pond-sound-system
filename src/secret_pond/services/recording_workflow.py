from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from secret_pond.services.player_settings import apply_player_layer_settings
from secret_pond.services.recording_transaction import run_recording_transaction
from secret_pond.services.runtime import SecretPondRuntime, rendered_layer_paths

_T = TypeVar("_T")


def run_recording_workflow(runtime: SecretPondRuntime, control: Callable[[], _T]) -> _T:
    outcome = run_recording_transaction(runtime, control)
    refresh_playback_after_recording(runtime, outcome)
    return outcome


def refresh_playback_after_recording(runtime: SecretPondRuntime, outcome: Any) -> None:
    if outcome is None or not getattr(outcome, "accepted", False):
        return

    settings = runtime.controller.settings
    try:
        if runtime.output.is_running:
            runtime.player.reload_and_restart(rendered_layer_paths(runtime.paths))
        else:
            runtime.player.load_rendered_layers(rendered_layer_paths(runtime.paths))
        apply_player_layer_settings(runtime, settings)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        _log_event_best_effort(
            runtime,
            "recording.playback_refresh_failed",
            {
                "error": str(exc),
                "output_running": runtime.output.is_running,
            },
        )


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
