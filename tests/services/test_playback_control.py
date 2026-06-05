from __future__ import annotations

from types import SimpleNamespace

import pytest

from secret_pond.services.playback_control import PlaybackControlError, restart_playback


class FakePlayer:
    def __init__(self) -> None:
        self.frame_cursor = 10
        self.restart_calls = 0
        self.restore_calls = 0

    def snapshot(self):
        return {"frame_cursor": self.frame_cursor}

    def restore(self, snapshot) -> None:
        self.restore_calls += 1
        self.frame_cursor = snapshot["frame_cursor"]

    def restart(self) -> None:
        self.restart_calls += 1
        self.frame_cursor = 0


class FakeOutput:
    def __init__(self, *, fail_start_on_call: int | None = None) -> None:
        self.fail_start_on_call = fail_start_on_call
        self.is_running = True
        self.start_calls = 1
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_running = False

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start_on_call == self.start_calls:
            self.is_running = False
            raise OSError("restart failed")
        self.is_running = True


class EventLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


def test_restart_playback_restores_snapshot_and_running_output_after_start_failure() -> None:
    runtime = SimpleNamespace(
        player=FakePlayer(),
        output=FakeOutput(fail_start_on_call=2),
        logger=EventLogger(),
    )

    with pytest.raises(PlaybackControlError, match="restart failed"):
        restart_playback(runtime)

    assert runtime.player.frame_cursor == 10
    assert runtime.player.restore_calls == 1
    assert runtime.output.stop_calls == 1
    assert runtime.output.start_calls == 3
    assert runtime.output.is_running is True
    assert runtime.logger.events == [
        (
            "playback.restart_failed",
            {
                "error": "restart failed",
                "frame_cursor": 10,
                "output_running": True,
            },
        )
    ]
