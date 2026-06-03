from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from secret_pond.app import create_app
from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.recorder import FakeRecorder
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    DeviceSettings,
    InputControlSettings,
    VoiceStackSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.runtime import build_runtime
from secret_pond.services.settings_store import SettingsState, SettingsStore


def api_settings() -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        input_control=InputControlSettings(
            minimum_recording_seconds=0.0,
            maximum_recording_seconds=1.0,
        ),
        voice_stack=VoiceStackSettings(loop_seconds=1),
    )


def api_settings_with_devices() -> AppSettings:
    return api_settings().model_copy(
        update={"devices": DeviceSettings(input_device_id="mic-2", output_device_id="speaker-2")},
        deep=True,
    )


def recorder_take() -> AudioBuffer:
    samples = np.ones((2_000, 2), dtype=np.float32) * 0.05
    return AudioBuffer(samples=samples, sample_rate=48_000)


class FakeOutput:
    def __init__(
        self,
        *,
        fail_start: Exception | None = None,
        fail_start_on_call: int | None = None,
        fail_stop: Exception | None = None,
    ) -> None:
        self.fail_start = fail_start
        self.fail_start_on_call = fail_start_on_call
        self.fail_stop = fail_stop
        self.is_running = False
        self.latest_status = None
        self.statuses = []
        self.latest_error = None
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start is not None and (
            self.fail_start_on_call is None or self.start_calls == self.fail_start_on_call
        ):
            self.latest_error = str(self.fail_start)
            self.is_running = False
            raise self.fail_start
        self.is_running = True
        self.latest_error = None

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_running = False
        if self.fail_stop is not None:
            self.latest_error = str(self.fail_stop)
            raise self.fail_stop


class LockAwareRenderer:
    def __init__(self, delegate, lock) -> None:
        self.delegate = delegate
        self.lock = lock
        self.lock_owned_during_render = False

    def render_layer(self, layer_id, settings):
        return self.delegate.render_layer(layer_id, settings)

    def render_all(self, settings):
        self.lock_owned_during_render = self.lock._is_owned()
        return self.delegate.render_all(settings)

    def stage_all(self, settings):
        self.lock_owned_during_render = self.lock._is_owned()
        return self.delegate.stage_all(settings)


class FailingStageRenderer:
    def __init__(self, delegate, error: Exception) -> None:
        self.delegate = delegate
        self.error = error
        self.stage_calls = 0

    def render_layer(self, layer_id, settings):
        return self.delegate.render_layer(layer_id, settings)

    def render_all(self, settings):
        return self.delegate.render_all(settings)

    def stage_all(self, settings):
        self.stage_calls += 1
        raise self.error


class LockAwareSettingsStore:
    def __init__(self, delegate, lock) -> None:
        self.delegate = delegate
        self.lock = lock
        self.lock_owned_during_load = False

    def load(self):
        self.lock_owned_during_load = self.lock._is_owned()
        return self.delegate.load()

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class FailingSaveSettingsStore:
    def __init__(self, delegate, error: Exception) -> None:
        self.delegate = delegate
        self.error = error

    def save(self, state):
        if state.active == state.draft:
            raise self.error
        return self.delegate.save(state)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class FailingDeviceRegistry:
    def list_input_devices(self):
        raise OSError("device stack unavailable")

    def list_output_devices(self):
        raise OSError("device stack unavailable")

    def validate_input(self, device_id):
        raise OSError("device stack unavailable")

    def validate_output(self, device_id):
        raise OSError("device stack unavailable")


def create_test_client(
    tmp_path: Path,
    *,
    with_sources: bool = False,
    output: FakeOutput | None = None,
    settings: AppSettings | None = None,
    device_registry=None,
) -> TestClient:
    paths = ProjectPaths(tmp_path)
    resolved_settings = settings or api_settings()
    if with_sources:
        write_source_files(paths, resolved_settings)
    SettingsStore(paths).save(SettingsState(active=resolved_settings, draft=resolved_settings))
    runtime = build_runtime(
        tmp_path,
        recorder=FakeRecorder(recorder_take()),
        output=output,
        device_registry=device_registry,
    )
    return TestClient(create_app(runtime=runtime))


def write_source_files(paths: ProjectPaths, settings: AppSettings) -> None:
    paths.ensure_directories()
    frames = settings.audio.sample_rate * settings.audio.loop_seconds
    samples = np.ones((frames, settings.audio.channels), dtype=np.float32) * 0.05
    buffer = AudioBuffer(samples=samples, sample_rate=settings.audio.sample_rate)
    write_wav_atomic(paths.low_source, buffer)
    write_wav_atomic(paths.mid_source, buffer)


def draft_with_voice_volume(volume_db: float) -> dict:
    settings = api_settings()
    layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(update={"volume_db": volume_db}),
    }
    return settings.model_copy(update={"layers": layers}, deep=True).model_dump(mode="json")


def draft_with_low_layer_disabled() -> dict:
    settings = api_settings()
    layers = {
        **settings.layers,
        "low": settings.layers["low"].model_copy(update={"enabled": False}),
    }
    return settings.model_copy(update={"layers": layers}, deep=True).model_dump(mode="json")


def draft_with_sample_rate(sample_rate: int) -> dict:
    return api_settings().model_copy(
        update={"audio": api_settings().audio.model_copy(update={"sample_rate": sample_rate})},
        deep=True,
    ).model_dump(mode="json")


def draft_with_peak_ceiling(peak_ceiling: float) -> dict:
    return api_settings().model_copy(
        update={"audio": api_settings().audio.model_copy(update={"peak_ceiling": peak_ceiling})},
        deep=True,
    ).model_dump(mode="json")


def draft_with_devices(*, input_device_id: str | None, output_device_id: str | None) -> dict:
    return api_settings().model_copy(
        update={
            "devices": DeviceSettings(
                input_device_id=input_device_id,
                output_device_id=output_device_id,
            )
        },
        deep=True,
    ).model_dump(mode="json")


def fake_device_registry() -> FakeDeviceRegistry:
    return FakeDeviceRegistry(
        [
            AudioDeviceInfo(
                id="mic-1",
                name="Mic 1",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
            ),
            AudioDeviceInfo(
                id="mic-2",
                name="Mic 2",
                kind="input",
                max_input_channels=2,
                max_output_channels=0,
                default_sample_rate=48_000,
            ),
            AudioDeviceInfo(
                id="speaker-1",
                name="Speaker 1",
                kind="output",
                max_input_channels=0,
                max_output_channels=1,
                default_sample_rate=48_000,
            ),
            AudioDeviceInfo(
                id="speaker-2",
                name="Speaker 2",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=8_000,
            ),
        ]
    )


def wait_for_state(client: TestClient, predicate, *, timeout_seconds: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    state = client.get("/api/state").json()
    while not predicate(state) and time.monotonic() < deadline:
        time.sleep(0.01)
        state = client.get("/api/state").json()
    return state


def test_health_endpoint_still_reports_ok(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_root_serves_operator_dashboard(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="secret-pond-app"' in response.text
    assert 'href="/static/styles.css"' in response.text
    assert 'src="/static/app.js"' in response.text
    assert 'id="outputBadge"' in response.text
    assert 'id="startOutputButton"' in response.text
    assert 'id="stopOutputButton"' in response.text
    assert 'id="deviceStatus"' in response.text
    assert 'id="inputDeviceName"' in response.text
    assert 'id="outputDeviceName"' in response.text
    assert 'id="inputDeviceSelect"' in response.text
    assert 'id="outputDeviceSelect"' in response.text
    assert 'id="deviceRestartNotice"' in response.text


def test_static_ui_assets_are_served(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    styles = client.get("/static/styles.css")
    script = client.get("/static/app.js")

    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "state.devices = null" in script.text
    assert "new WebSocket" in script.text
    assert "syncDraft: false" in script.text
    assert "!state.websocketConnected && state.snapshot?.is_recording" in script.text
    assert "requestState({ syncDraft: false })" in script.text
    assert 'control("/api/recording/poll-auto-stop", { syncDraft: false })' in script.text
    assert "hasDraftRuntimeConfigChanges(snapshot)" in script.text
    assert '"applyButton").disabled = snapshot.is_recording || runtimeConfigChanges' in script.text
    assert "Will stop and restart output while applying staged audio settings." in script.text
    assert (
        "snapshot.settings.active.audio.sample_rate !== state.draft.audio.sample_rate"
        in script.text
    )
    assert "snapshot.settings.active.audio.channels !== state.draft.audio.channels" in script.text
    assert (
        "snapshot.settings.active.devices.input_device_id !== state.draft.devices.input_device_id"
        in script.text
    )
    assert (
        "snapshot.settings.active.devices.output_device_id !== state.draft.devices.output_device_id"
        in script.text
    )
    assert "await requestState({ syncDraft: false }).catch(() => {})" in script.text
    assert "showError(error.message)" in script.text


def test_api_state_reports_initial_runtime_state(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["armed"] is False
    assert payload["is_recording"] is False
    assert payload["participant_count"] == 0
    assert payload["playback"]["is_playing"] is False
    assert payload["playback"]["output_running"] is False
    assert payload["playback"]["output_latest_error"] is None
    assert payload["settings"]["active"]["voice_stack"]["loop_seconds"] == 1
    assert payload["settings"]["draft"]["voice_stack"]["loop_seconds"] == 1


def test_ws_state_sends_initial_runtime_state(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()

    assert payload["armed"] is False
    assert payload["is_recording"] is False
    assert payload["participant_count"] == 0
    assert payload["playback"]["output_running"] is False
    assert payload["settings"]["active"]["voice_stack"]["loop_seconds"] == 1


def test_ws_state_disconnect_stops_active_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    with client.websocket_connect("/ws/state") as websocket:
        assert websocket.receive_json()["is_recording"] is True

    state = wait_for_state(client, lambda payload: payload["is_recording"] is False)
    assert state["is_recording"] is False
    assert state["participant_count"] == 1


def test_ws_state_polls_recording_auto_stop_before_sending_state(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.post("/api/input/arm")
    client.post("/api/recording/start")
    client.app.state.runtime.controller._recording_started_at -= 2.0

    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()

    assert payload["is_recording"] is False
    assert payload["participant_count"] == 1


def test_api_devices_returns_device_lists_and_selected_devices(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path,
        settings=api_settings_with_devices(),
        device_registry=fake_device_registry(),
    )

    response = client.get("/api/devices")

    assert response.status_code == 200
    payload = response.json()
    assert [device["id"] for device in payload["input_devices"]] == ["mic-1", "mic-2"]
    assert [device["id"] for device in payload["output_devices"]] == ["speaker-1", "speaker-2"]
    assert payload["selected_input_device"]["id"] == "mic-2"
    assert payload["selected_output_device"]["id"] == "speaker-2"
    assert payload["warnings"] == []


def test_api_devices_maps_device_registry_failure_to_503(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, device_registry=FailingDeviceRegistry())

    response = client.get("/api/devices")

    assert response.status_code == 503
    assert "device stack unavailable" in response.json()["detail"]


def test_api_start_recording_rejects_disarmed_input(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.post("/api/recording/start")

    assert response.status_code == 409
    assert "armed" in response.json()["detail"]


def test_api_arm_start_and_stop_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    arm_response = client.post("/api/input/arm")
    start_response = client.post("/api/recording/start")
    stop_response = client.post("/api/recording/stop")

    assert arm_response.status_code == 200
    assert arm_response.json()["state"]["armed"] is True
    assert start_response.status_code == 200
    assert start_response.json()["state"]["is_recording"] is True
    assert stop_response.status_code == 200
    payload = stop_response.json()
    assert payload["outcome"]["accepted"] is True
    assert payload["outcome"]["reason"] is None
    assert payload["outcome"]["participant_count"] == 1
    assert "stack_result" not in payload["outcome"]
    assert payload["state"]["participant_count"] == 1
    assert payload["state"]["is_recording"] is False


def test_api_auto_stop_poll_returns_null_outcome_when_idle(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.post("/api/recording/poll-auto-stop")

    assert response.status_code == 200
    assert response.json()["outcome"] is None


def test_api_settings_draft_update_does_not_change_active(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["active"]["layers"]["voice"]["volume_db"] == -18.0
    assert settings["draft"]["layers"]["voice"]["volume_db"] == -9.0


def test_api_settings_draft_device_update_does_not_change_active(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.put(
        "/api/settings/draft",
        json=draft_with_devices(input_device_id="mic-2", output_device_id="speaker-2"),
    )

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["active"]["devices"]["input_device_id"] is None
    assert settings["active"]["devices"]["output_device_id"] is None
    assert settings["draft"]["devices"]["input_device_id"] == "mic-2"
    assert settings["draft"]["devices"]["output_device_id"] == "speaker-2"


def test_api_settings_reset_discards_draft_changes(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/reset")

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["active"]["layers"]["voice"]["volume_db"] == -18.0
    assert settings["draft"]["layers"]["voice"]["volume_db"] == -18.0


def test_api_state_loads_settings_inside_runtime_lock(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    runtime = client.app.state.runtime
    assert hasattr(runtime, "operation_lock")
    settings_store = LockAwareSettingsStore(runtime.settings_store, runtime.operation_lock)
    runtime.settings_store = settings_store

    response = client.get("/api/state")

    assert response.status_code == 200
    assert settings_store.lock_owned_during_load is True


def test_api_settings_apply_and_restart_renders_inside_runtime_lock(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    assert hasattr(runtime, "operation_lock")
    renderer = LockAwareRenderer(runtime.renderer, runtime.operation_lock)
    runtime.renderer = renderer
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    assert renderer.lock_owned_during_render is True


def test_api_settings_apply_and_restart_renders_layers_and_starts_player(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["active"]["layers"]["voice"]["volume_db"] == -9.0
    assert payload["settings"]["draft"]["layers"]["voice"]["volume_db"] == -9.0
    assert payload["state"]["playback"]["is_playing"] is True
    assert payload["state"]["playback"]["output_running"] is False
    paths = ProjectPaths(tmp_path)
    assert paths.low_playback.exists()
    assert paths.mid_playback.exists()
    assert paths.voice_playback.exists()


def test_api_settings_apply_and_restart_applies_layer_enabled_state(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_low_layer_disabled())

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    assert response.json()["state"]["playback"]["layers"]["low"]["enabled"] is False


def test_api_settings_apply_and_restart_is_blocked_while_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "recording" in response.json()["detail"]


def test_api_playback_start_before_layers_are_loaded_returns_conflict(tmp_path: Path) -> None:
    output = FakeOutput(fail_start=ValueError("rendered layers must be loaded before playback"))
    client = create_test_client(tmp_path, output=output)

    response = client.post("/api/playback/start")

    assert response.status_code == 409
    assert "loaded" in response.json()["detail"]


def test_api_playback_start_and_stop_controls_output_after_apply(tmp_path: Path) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")

    start_response = client.post("/api/playback/start")
    stop_response = client.post("/api/playback/stop")

    assert start_response.status_code == 200
    assert start_response.json()["state"]["playback"]["output_running"] is True
    assert output.start_calls == 1
    assert stop_response.status_code == 200
    assert stop_response.json()["state"]["playback"]["output_running"] is False
    assert output.stop_calls == 1


def test_api_settings_apply_and_restart_restarts_running_output(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    payload = response.json()
    assert output.stop_calls == 1
    assert output.start_calls == 2
    assert payload["settings"]["active"]["layers"]["voice"]["volume_db"] == -9.0
    assert payload["state"]["playback"]["output_running"] is True


def test_api_settings_apply_and_restart_applies_peak_ceiling_to_player(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    client.put("/api/settings/draft", json=draft_with_peak_ceiling(0.5))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    assert client.app.state.runtime.player.snapshot().peak_ceiling == 0.5


def test_api_settings_apply_and_restart_restores_output_after_stop_failure(
    tmp_path: Path,
) -> None:
    output = FakeOutput(fail_stop=OSError("stream stop failed"))
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "stream stop failed" in response.json()["detail"]
    assert output.stop_calls == 1
    assert output.start_calls == 2
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["layers"]["voice"]["volume_db"] == -18.0
    assert state["playback"]["output_running"] is True


def test_api_settings_apply_and_restart_rolls_back_render_failure_after_stop(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    runtime = client.app.state.runtime
    runtime.renderer = FailingStageRenderer(runtime.renderer, FileNotFoundError("low missing"))
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "low missing" in response.json()["detail"]
    assert output.stop_calls == 1
    assert output.start_calls == 2
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["layers"]["voice"]["volume_db"] == -18.0
    assert state["playback"]["output_running"] is True


def test_api_settings_apply_and_restart_rolls_back_failed_new_output_start(
    tmp_path: Path,
) -> None:
    output = FakeOutput(fail_start=OSError("restart failed"), fail_start_on_call=2)
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    client.put("/api/settings/draft", json=draft_with_peak_ceiling(0.5))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "restart failed" in response.json()["detail"]
    assert output.stop_calls == 1
    assert output.start_calls == 3
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["audio"]["peak_ceiling"] == 0.98
    assert state["playback"]["output_running"] is True
    assert client.app.state.runtime.player.snapshot().peak_ceiling == 0.98


def test_api_settings_apply_and_restart_rolls_back_save_failure_after_restart(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    runtime = client.app.state.runtime
    runtime.settings_store = FailingSaveSettingsStore(
        runtime.settings_store,
        OSError("settings save failed"),
    )
    client.put("/api/settings/draft", json=draft_with_peak_ceiling(0.5))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "settings save failed" in response.json()["detail"]
    assert output.stop_calls == 2
    assert output.start_calls == 3
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["audio"]["peak_ceiling"] == 0.98
    assert state["playback"]["output_running"] is True
    assert client.app.state.runtime.player.snapshot().peak_ceiling == 0.98


def test_api_settings_apply_rejects_runtime_config_changes_without_touching_running_output(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    output.is_running = True
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.put("/api/settings/draft", json=draft_with_sample_rate(16_000))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert output.stop_calls == 0
    assert output.start_calls == 0
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["audio"]["sample_rate"] == 8_000


def test_api_settings_apply_rejects_output_format_changes_without_changing_active(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_sample_rate(16_000))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "output" in response.json()["detail"]
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["audio"]["sample_rate"] == 8_000


def test_api_settings_apply_rejects_device_changes_without_changing_active(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put(
        "/api/settings/draft",
        json=draft_with_devices(input_device_id="mic-2", output_device_id="speaker-2"),
    )

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "device" in response.json()["detail"]
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["devices"]["input_device_id"] is None
    assert state["settings"]["active"]["devices"]["output_device_id"] is None


def test_api_settings_apply_rejects_input_device_changes_without_changing_active(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put(
        "/api/settings/draft",
        json=draft_with_devices(input_device_id="mic-2", output_device_id=None),
    )

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert "device" in response.json()["detail"]
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["devices"]["input_device_id"] is None
