from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_store import SettingsState

T = TypeVar("T")


class MaintenanceOperationError(RuntimeError):
    """Raised when a maintenance action cannot run safely."""


def reset_draft_settings(
    runtime: SecretPondRuntime,
    *,
    build_result: Callable[[SettingsState], T] | None = None,
) -> SettingsState | T:
    with _maintenance_operation(runtime):
        if runtime.controller.is_recording:
            raise MaintenanceOperationError("cannot reset draft settings while recording")
        try:
            state = runtime.settings_store.reset_draft()
        except (OSError, RuntimeError, ValueError) as exc:
            raise MaintenanceOperationError(str(exc)) from exc
        runtime.settings_state = state
        if build_result is not None:
            return build_result(state)
        return state


def reset_participant_count(
    runtime: SecretPondRuntime,
    *,
    build_result: Callable[[int], T] | None = None,
) -> int | T:
    with _maintenance_operation(runtime):
        if runtime.controller.is_recording:
            raise MaintenanceOperationError("cannot reset participant count while recording")
        previous_count = runtime.participants.get_count()
        participant_count = runtime.participants.reset()
        _log_event_best_effort(
            runtime,
            "participants.reset",
            {"previous_count": previous_count, "count": participant_count},
        )
        if build_result is not None:
            return build_result(participant_count)
        return participant_count


@contextmanager
def _maintenance_operation(runtime: SecretPondRuntime) -> Iterator[None]:
    acquired = runtime.operation_lock.acquire(blocking=False)
    if not acquired:
        raise MaintenanceOperationError(
            "maintenance actions are unavailable while another operation is running"
        )
    try:
        yield
    finally:
        runtime.operation_lock.release()


def _log_event_best_effort(
    runtime: SecretPondRuntime,
    event_type: str,
    payload: dict,
) -> None:
    try:
        runtime.logger.log_event(event_type, payload)
    except Exception:
        return
