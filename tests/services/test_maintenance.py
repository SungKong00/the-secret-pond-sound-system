from __future__ import annotations

from types import SimpleNamespace

import pytest

from secret_pond.services.maintenance import (
    MaintenanceOperationError,
    reset_draft_settings,
    reset_participant_count,
)


class FakeMaintenanceLock:
    def __init__(self, *, acquire_result: bool = True) -> None:
        self.acquire_result = acquire_result
        self.acquire_calls: list[bool] = []
        self.release_calls = 0

    def acquire(self, blocking: bool = True) -> bool:
        self.acquire_calls.append(blocking)
        return self.acquire_result

    def release(self) -> None:
        self.release_calls += 1


class FakeSettingsStore:
    def __init__(self) -> None:
        self.state = SimpleNamespace(name="reset-state")
        self.reset_calls = 0

    def reset_draft(self):
        self.reset_calls += 1
        return self.state


class FakeParticipants:
    def __init__(self, count: int) -> None:
        self.count = count
        self.reset_calls = 0

    def get_count(self) -> int:
        return self.count

    def reset(self) -> int:
        self.reset_calls += 1
        self.count = 0
        return self.count


class FakeLogger:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_type: str, payload: dict) -> None:
        if self.fail:
            raise OSError("event log unavailable")
        self.events.append((event_type, payload))


def maintenance_runtime(*, recording: bool = False, lock_acquired: bool = True):
    return SimpleNamespace(
        controller=SimpleNamespace(is_recording=recording),
        logger=FakeLogger(),
        operation_lock=FakeMaintenanceLock(acquire_result=lock_acquired),
        participants=FakeParticipants(2),
        settings_state=SimpleNamespace(name="initial-state"),
        settings_store=FakeSettingsStore(),
    )


def test_reset_draft_settings_rejects_recording_without_mutating_draft() -> None:
    runtime = maintenance_runtime(recording=True)

    with pytest.raises(
        MaintenanceOperationError,
        match="cannot reset draft settings while recording",
    ):
        reset_draft_settings(runtime)

    assert runtime.settings_store.reset_calls == 0
    assert runtime.settings_state.name == "initial-state"
    assert runtime.operation_lock.acquire_calls == [False]
    assert runtime.operation_lock.release_calls == 1


def test_reset_draft_settings_rejects_concurrent_operation_without_mutating_draft() -> None:
    runtime = maintenance_runtime(lock_acquired=False)

    with pytest.raises(
        MaintenanceOperationError,
        match="maintenance actions are unavailable while another operation is running",
    ):
        reset_draft_settings(runtime)

    assert runtime.settings_store.reset_calls == 0
    assert runtime.settings_state.name == "initial-state"
    assert runtime.operation_lock.acquire_calls == [False]
    assert runtime.operation_lock.release_calls == 0


def test_reset_draft_settings_updates_runtime_settings_state() -> None:
    runtime = maintenance_runtime()

    state = reset_draft_settings(runtime)

    assert state is runtime.settings_store.state
    assert runtime.settings_store.reset_calls == 1
    assert runtime.settings_state is state
    assert runtime.operation_lock.release_calls == 1


def test_reset_draft_settings_can_build_result_before_lock_release() -> None:
    runtime = maintenance_runtime()

    def build_result(state):
        assert state is runtime.settings_store.state
        assert runtime.operation_lock.release_calls == 0
        return {"settings": state.name}

    result = reset_draft_settings(runtime, build_result=build_result)

    assert result == {"settings": "reset-state"}
    assert runtime.operation_lock.release_calls == 1


def test_reset_participant_count_logs_previous_and_new_count_best_effort() -> None:
    runtime = maintenance_runtime()

    count = reset_participant_count(runtime)

    assert count == 0
    assert runtime.participants.reset_calls == 1
    assert runtime.logger.events == [
        ("participants.reset", {"previous_count": 2, "count": 0})
    ]
    assert runtime.operation_lock.release_calls == 1


def test_reset_participant_count_can_build_result_before_lock_release() -> None:
    runtime = maintenance_runtime()

    def build_result(count: int):
        assert count == 0
        assert runtime.operation_lock.release_calls == 0
        return {"participant_count": count}

    result = reset_participant_count(runtime, build_result=build_result)

    assert result == {"participant_count": 0}
    assert runtime.operation_lock.release_calls == 1


def test_reset_participant_count_ignores_event_log_failure() -> None:
    runtime = maintenance_runtime()
    runtime.logger = FakeLogger(fail=True)

    count = reset_participant_count(runtime)

    assert count == 0
    assert runtime.participants.reset_calls == 1
    assert runtime.operation_lock.release_calls == 1
