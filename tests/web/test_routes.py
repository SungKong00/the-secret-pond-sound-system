from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from secret_pond.app import create_app
from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.output import SoundDeviceOutput
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.audio.recorder import FakeRecorder
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    DeviceSettings,
    InputControlSettings,
    RecordingProcessingSettings,
    VoiceStackSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.runtime import PlaybackOutput, build_runtime
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


RECORDING_PRESETS = {
    "Soft": {
        "gain_db": -3.0,
        "normalize_peak": 0.3,
        "highpass_hz": 80.0,
        "lowpass_hz": 9000.0,
        "presence_gain_db": -4.0,
        "reverb_mix": 0.18,
        "delay_mix": 0.0,
        "fade_ms": 80,
    },
    "Misty": {
        "gain_db": -1.0,
        "normalize_peak": 0.32,
        "highpass_hz": 90.0,
        "lowpass_hz": 7000.0,
        "presence_gain_db": -5.0,
        "reverb_mix": 0.45,
        "delay_mix": 0.12,
        "fade_ms": 120,
    },
    "Dense": {
        "gain_db": 1.5,
        "normalize_peak": 0.45,
        "highpass_hz": 120.0,
        "lowpass_hz": 6500.0,
        "presence_gain_db": -2.0,
        "reverb_mix": 0.3,
        "delay_mix": 0.08,
        "fade_ms": 60,
    },
    "Clearer Voice": {
        "gain_db": 0.0,
        "normalize_peak": 0.4,
        "highpass_hz": 140.0,
        "lowpass_hz": 10000.0,
        "presence_gain_db": 3.0,
        "reverb_mix": 0.12,
        "delay_mix": 0.0,
        "fade_ms": 40,
    },
}


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


class RestartFailureStream:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        if self.fail_start:
            raise OSError("stream start failed")
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class RestartFailureStreamFactory:
    def __init__(self, fail_start_on_calls: set[int]) -> None:
        self.fail_start_on_calls = fail_start_on_calls
        self.calls = 0

    def __call__(self, **_kwargs) -> RestartFailureStream:
        self.calls += 1
        return RestartFailureStream(fail_start=self.calls in self.fail_start_on_calls)


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


class BlockingStageRenderer:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.entered = threading.Event()
        self.release = threading.Event()

    def render_layer(self, layer_id, settings):
        return self.delegate.render_layer(layer_id, settings)

    def render_all(self, settings):
        return self.delegate.render_all(settings)

    def stage_all(self, settings):
        self.entered.set()
        if not self.release.wait(timeout=5):
            msg = "timed out waiting to release blocked render"
            raise AssertionError(msg)
        return self.delegate.stage_all(settings)


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
    player: LayeredLoopPlayer | None = None,
    output: PlaybackOutput | None = None,
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
        player=player,
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


def slice_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def wait_for_state(client: TestClient, predicate, *, timeout_seconds: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    state = client.get("/api/state").json()
    while not predicate(state) and time.monotonic() < deadline:
        time.sleep(0.01)
        state = client.get("/api/state").json()
    return state


def wait_for_future_response(future) -> Any:
    try:
        return future.result(timeout=1.0)
    except concurrent.futures.TimeoutError as exc:
        msg = "reset request waited for Apply and Restart instead of returning 409"
        raise AssertionError(msg) from exc


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
    assert 'id="modeBadge"' in response.text
    assert 'id="lastEventBadge"' in response.text
    assert 'id="errorBadge"' in response.text
    assert "Error None" in response.text
    assert 'id="deviceHealthBadge"' in response.text
    assert 'id="syncBadge"' in response.text
    assert "No unsaved changes" in response.text
    assert "No pending changes" not in response.text
    assert 'id="startOutputButton"' in response.text
    assert 'id="stopOutputButton"' in response.text
    assert 'id="restartOutputButton"' in response.text
    assert 'id="restartOutputButton" class="button" type="button" disabled' in response.text
    assert 'aria-label="runtime controls"' in response.text
    assert 'aria-label="spacebar capture mode"' in response.text
    assert (
        'id="armButton" class="button primary" type="button" aria-pressed="false"'
        in response.text
    )
    assert (
        'id="disarmButton" class="button" type="button" aria-pressed="true"'
        in response.text
    )
    assert 'id="deviceStatus"' in response.text
    assert 'id="inputDeviceName"' in response.text
    assert 'id="outputDeviceName"' in response.text
    assert 'id="inputDeviceSelect"' in response.text
    assert 'id="outputDeviceSelect"' in response.text
    assert 'id="deviceRestartNotice"' in response.text
    assert 'id="recordOutcomeStatus"' in response.text
    assert 'id="recordOutcomeDetail"' in response.text
    assert 'class="record-limits"' in response.text
    assert 'id="minimumRecordingTime"' in response.text
    assert 'id="maximumRecordingTime"' in response.text
    assert 'id="recordingPresets"' in response.text
    assert 'role="group"' in response.text
    assert 'aria-label="recording treatment presets"' in response.text
    assert 'aria-pressed="false"' in response.text
    assert response.text.count('class="preset-button"') == 4
    assert "Soft" in response.text
    assert "Misty" in response.text
    assert "Dense" in response.text
    assert "Clearer Voice" in response.text
    assert 'aria-label="system diagnostics"' in response.text
    assert 'id="systemStatus"' in response.text
    assert 'id="sourceHealthList"' in response.text
    assert 'id="eventLogSummary"' in response.text
    assert 'id="systemInputDeviceName"' in response.text
    assert 'id="systemOutputDeviceName"' in response.text


def test_settings_reset_is_hidden_behind_maintenance_panel(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    settings_panel = slice_between(
        response.text,
        '<section class="panel settings-panel"',
        '<section class="panel system-panel"',
    )
    primary_actions = slice_between(
        settings_panel,
        '<div class="button-row settings-primary-actions">',
        "</div>",
    )
    maintenance_panel = slice_between(
        settings_panel,
        '<details class="maintenance-panel">',
        "</details>",
    )
    assert "Apply and Restart" in primary_actions
    assert "Reset Draft" not in primary_actions
    assert "<summary>Maintenance</summary>" in maintenance_panel
    assert 'id="resetButton"' in maintenance_panel
    assert 'id="resetParticipantsButton"' in maintenance_panel
    assert "Reset Draft" in maintenance_panel
    assert "Reset Participants" in maintenance_panel


def test_static_ui_assets_are_served(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    styles = client.get("/static/styles.css")
    script = client.get("/static/app.js")

    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    normalized_styles = " ".join(styles.text.split())
    assert (
        "grid-template-columns: minmax(240px, 0.72fr) minmax(340px, 1.2fr) "
        "minmax(280px, 0.86fr) minmax(260px, 0.78fr);"
        in normalized_styles
    )
    assert "@media (max-width: 1240px)" in styles.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    normalized_script = " ".join(script.text.split())
    assert "state.devices = null" in script.text
    assert "state.diagnostics = null" in script.text
    assert "new WebSocket" in script.text
    assert 'api("/api/diagnostics")' in script.text
    assert "renderModeBadge(snapshot.settings.active.voice_stack.mode)" in script.text
    assert '"live_ephemeral": "Mode Live"' in script.text
    assert '"test_library": "Mode Test"' in script.text
    assert "renderLastEventBadge" in script.text
    assert "Last Event None" in script.text
    assert "Last Event Unavailable" in script.text
    assert "state.diagnostics?.events?.recent?.[0]" in script.text
    assert "currentErrorMessages" in script.text
    assert "renderErrorBadge" in script.text
    assert "Error Active" in script.text
    assert "Error None" in script.text
    assert '"errorBadge").className = "status-pill hot"' in script.text
    assert '"errorBadge").className = "status-pill muted"' in script.text
    assert "renderSyncBadge" in script.text
    assert "Sync Live" in script.text
    assert "Sync Connecting" in script.text
    assert "Sync Polling" in script.text
    assert '"syncBadge").className = "status-pill safe"' in script.text
    assert '"syncBadge").className = "status-pill muted"' in script.text
    assert '!("WebSocket" in window)' in script.text
    assert "renderSyncBadge();\n  const snapshot = state.snapshot;" in script.text
    assert "renderDeviceHealthBadge" in script.text
    assert "Devices Checking" in script.text
    assert "Devices OK" in script.text
    assert "Device Warning" in script.text
    assert "Devices Offline" in script.text
    assert '"restartOutputButton").disabled = !snapshot.playback.output_running' in script.text
    assert 'control("/api/playback/restart")' in script.text
    assert 'socket.addEventListener("message", (event) => {' in script.text
    assert (
        'socket.addEventListener("message", (event) => {\n    try {\n      applyState'
        in script.text
    )
    assert "renderSystemStatus" in script.text
    assert "const systemDeviceName" in script.text
    assert 'systemDeviceName( "selected_input_device", "No input device", )' in normalized_script
    assert 'systemDeviceName( "selected_output_device", "No output device", )' in normalized_script
    assert "sourceHealthList" in script.text
    assert "eventLogSummary" in script.text
    assert "syncDraft: false" in script.text
    assert "!state.websocketConnected && state.snapshot?.is_recording" in script.text
    assert "requestState({ syncDraft: false })" in script.text
    assert 'control("/api/recording/poll-auto-stop", { syncDraft: false })' in script.text
    assert "setRecordStatus(\"processing\", \"Processing recording...\")" in script.text
    assert 'path !== "/api/recording/poll-auto-stop"' in script.text
    assert "recordingStopInFlight" in script.text
    assert 'path === "/api/recording/poll-auto-stop" && state.recordingStopInFlight' in script.text
    assert 'path === "/api/recording/stop" && !state.snapshot?.is_recording' in script.text
    assert 'path.startsWith("/api/playback/")' in script.text
    assert "await requestState({ syncDraft: false }).catch(() => {})" in script.text
    assert (
        'path === "/api/input/disarm" && !state.snapshot?.is_recording && '
        "!state.snapshot?.armed"
        in script.text
    )
    assert "renderRecordingOutcome(payload.outcome)" in script.text
    assert "recordingPresetDefs" in script.text
    assert "applyRecordingPreset" in script.text
    assert "renderRecordingPresets" in script.text
    assert 'button.setAttribute("aria-pressed", active ? "true" : "false")' in script.text
    assert "state.draft.recording = { ...state.draft.recording, ...settings }" in script.text
    assert "state.snapshot.settings.draft = clone(state.draft)" in script.text
    assert "renderRecordingControls()" in script.text
    assert "scheduleDraftSave()" in script.text
    assert "Soft" in script.text
    assert "Misty" in script.text
    assert "Dense" in script.text
    assert "Clearer Voice" in script.text
    for preset in RECORDING_PRESETS.values():
        for key, value in preset.items():
            assert key in script.text
            assert str(value) in script.text
    assert ".preset-row" in styles.text
    assert ".maintenance-panel" in styles.text
    assert ".maintenance-panel summary:focus-visible" in styles.text
    assert (
        "formatSeconds( snapshot.settings.active.input_control.minimum_recording_seconds, )"
        in normalized_script
    )
    assert (
        "formatSeconds( snapshot.settings.active.input_control.maximum_recording_seconds, )"
        in normalized_script
    )
    assert "minimumRecordingTime" in script.text
    assert "maximumRecordingTime" in script.text
    assert ".record-limits" in styles.text
    assert "Recording Added" in script.text
    assert "Too Short" in script.text
    assert "Empty Recording" in script.text
    assert "Recording Disarmed" in script.text
    assert "Recording Failed" in script.text
    assert (
        "const captureReady = snapshot.armed && !snapshot.is_recording && !recordingStopBusy"
        in script.text
    )
    assert (
        'document.querySelector(".record-core").classList.toggle("armed", captureReady)'
        in script.text
    )
    assert (
        'document.querySelector(".record-core").classList.toggle("recording", '
        "snapshot.is_recording)"
        in script.text
    )
    assert (
        '"armButton").setAttribute("aria-pressed", snapshot.armed ? "true" : "false")'
        in script.text
    )
    assert (
        '"disarmButton").setAttribute("aria-pressed", snapshot.armed ? "false" : "true")'
        in script.text
    )
    assert ".record-core.armed" in styles.text
    assert ".record-core.recording" in styles.text
    assert ".capture-mode-actions" in styles.text
    assert "layerPendingBadge" in script.text
    assert "updateLayerPendingBadge" in script.text
    assert "Pending Draft" in script.text
    assert "Active" in script.text
    assert "renderDraftValue" in script.text
    assert "active-value" in styles.text
    assert "Draft " in script.text
    assert "Unsaved audio changes" in script.text
    assert "No unsaved changes" in script.text
    assert "Pending changes" not in script.text
    assert "No pending changes" not in script.text
    assert "hasDraftRuntimeConfigChanges(snapshot)" in script.text
    render_state_body = slice_between(
        script.text,
        "const renderState = () => {",
        "};\n\nconst renderModeBadge",
    )
    assert "const recordingStopBusy = state.recordingStopInFlight" in render_state_body
    assert '"armButton").disabled = recordingStopBusy' in render_state_body
    assert '"disarmButton").disabled = recordingStopBusy' in render_state_body
    assert (
        '"startButton").disabled = recordingStopBusy || !snapshot.armed || '
        "snapshot.is_recording"
        in render_state_body
    )
    assert (
        '"stopButton").disabled = recordingStopBusy || !snapshot.is_recording'
        in render_state_body
    )
    assert 'recordingStopBusy\n    ? "Processing"' in render_state_body
    assert "applyInFlight: false" in script.text
    assert (
        '"applyButton").disabled =\n    state.applyInFlight || recordingStopBusy || '
        "snapshot.is_recording || runtimeConfigChanges"
        in render_state_body
    )
    assert '"applyButton").textContent = state.applyInFlight' in script.text
    assert "Applying..." in script.text
    assert "Wait for recording processing to finish." in script.text
    assert "Rendering and reloading staged audio settings." in script.text
    assert '"resetButton").disabled = state.applyInFlight || snapshot.is_recording' in script.text
    assert "Stop recording before resetting draft settings." in script.text
    assert (
        '"resetParticipantsButton").disabled = state.applyInFlight || snapshot.is_recording'
        in script.text
    )
    assert "Stop recording before resetting participant count." in script.text
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
    apply_body = slice_between(
        script.text,
        "const applyAndRestart = async () => {",
        "};\n\nconst resetDraft",
    )
    assert "if (state.applyInFlight) return" in apply_body
    assert "state.applyInFlight = true" in apply_body
    assert "state.applyInFlight = false" in apply_body
    assert "let applyError = null" in apply_body
    assert "applyError = error" in apply_body
    assert "showError(applyError.message)" in apply_body
    assert "const resetDraft = async () => {" in script.text
    assert 'const payload = await api("/api/settings/reset"' in script.text
    reset_draft_body = slice_between(
        script.text,
        "const resetDraft = async () => {",
        "};\n\nconst changeDraftDevice",
    )
    assert "await requestState({ syncDraft: false }).catch(() => {})" in reset_draft_body
    assert "const resetParticipants = async () => {" in script.text
    assert 'const payload = await api("/api/participants/reset"' in script.text
    reset_participants_body = slice_between(
        script.text,
        "const resetParticipants = async () => {",
        "};\n\nconst changeDraftDevice",
    )
    assert "applyState(payload.state, { syncDraft: false })" in reset_participants_body
    assert "await requestState({ syncDraft: false }).catch(() => {})" in reset_participants_body
    assert "showError(error.message)" in script.text
    control_body = slice_between(
        script.text,
        "const control = async (path, options = {}) => {",
        "};\n\nconst applyAndRestart",
    )
    assert "let controlError = null" in control_body
    assert "controlError = error" in control_body
    assert "const pollAutoStopRequest =" in control_body
    assert 'path === "/api/recording/poll-auto-stop"' in control_body
    assert "Number(state.snapshot?.recording_remaining_seconds || 0) <= 0" not in control_body
    assert "pollAutoStopRequest" in slice_between(
        control_body,
        "const startsStopRequest =",
        ";\n  if (path === \"/api/recording/poll-auto-stop\"",
    )
    assert "state.recordingStopInFlight = true;\n    renderState();" in control_body
    assert "state.recordingStopInFlight = false;\n      renderState();" in control_body
    assert "if (controlError) showError(controlError.message);" in control_body
    assert control_body.index("state.recordingStopInFlight = true") < control_body.index(
        "setRecordStatus(\"processing\", \"Processing recording...\")",
    )
    final_recording_stop_reset = control_body.rindex("state.recordingStopInFlight = false")
    final_render = control_body.index("renderState();", final_recording_stop_reset)
    final_error = control_body.index("if (controlError) showError(controlError.message);")
    assert final_recording_stop_reset < final_render < final_error
    recording_error_branch = slice_between(
        control_body,
        'if (path.startsWith("/api/recording/") || path === "/api/input/disarm") {',
        "}\n    if (path.startsWith(\"/api/playback/\"))",
    )
    assert 'setRecordStatus("failed", "Recording Failed", error.message)' in recording_error_branch
    assert "await requestState({ syncDraft: false }).catch(() => {})" in recording_error_branch
    assert "await requestDiagnostics().catch(() => {})" in recording_error_branch
    recording_branch_start = control_body.index(
        'if (path.startsWith("/api/recording/") || path === "/api/input/disarm") {',
    )
    recording_failed_status = control_body.index(
        'setRecordStatus("failed", "Recording Failed", error.message)',
        recording_branch_start,
    )
    recording_state_refresh = control_body.index(
        "await requestState({ syncDraft: false }).catch(() => {})",
        recording_branch_start,
    )
    recording_diagnostics_refresh = control_body.index(
        "await requestDiagnostics().catch(() => {})",
        recording_branch_start,
    )
    show_error = control_body.index("showError(controlError.message)")
    assert recording_branch_start < recording_failed_status < recording_state_refresh
    assert recording_state_refresh < recording_diagnostics_refresh
    assert recording_diagnostics_refresh < show_error
    start_from_space_body = slice_between(
        script.text,
        "const startFromSpace = async (event) => {",
        "};\n\nconst stopFromSpace",
    )
    assert (
        "state.recordingStopInFlight || !state.snapshot?.armed || state.snapshot?.is_recording"
        in start_from_space_body
    )


def test_static_ui_recording_stop_busy_state_disables_capture_controls(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for static app behavior smoke test")

    client = create_test_client(tmp_path)
    script = client.get("/static/app.js").text.replace(
        "\nbindEvents();\ndrawCanvas();\nconnectStateSocket();\nrefreshAll();\n",
        (
            "\nglobalThis.__secretPondTest = "
            "{ state, renderState, renderSyncBadge, "
            "connectStateSocket, showError, renderErrors, control, startFromSpace };\n"
        ),
    )
    harness = f"""
const assert = require("assert");
const vm = require("vm");
const elements = {{}};
const makeElement = () => ({{
  children: [],
  innerHTML: "",
  value: "",
  textContent: "",
  className: "",
  hidden: false,
  disabled: false,
  title: "",
  attributes: {{}},
  _classes: new Set(),
  classList: {{
    toggle(name, force) {{
      if (force) this.owner._classes.add(name);
      else this.owner._classes.delete(name);
    }},
    contains(name) {{
      return this.owner._classes.has(name);
    }},
  }},
  setAttribute(name, value) {{
    this.attributes[name] = value;
  }},
  getAttribute(name) {{
    return this.attributes[name] || null;
  }},
  appendChild(child) {{
    this.children.push(child);
  }},
  append(...children) {{
    this.children.push(...children);
  }},
  addEventListener() {{}},
  querySelector() {{
    return makeElement();
  }},
}});
const makeTrackedElement = () => {{
  const element = makeElement();
  element.classList.owner = element;
  return element;
}};
const recordCore = makeElement();
recordCore.classList.owner = recordCore;
globalThis.document = {{
  getElementById(id) {{
    if (!elements[id]) elements[id] = makeTrackedElement();
    return elements[id];
  }},
  querySelector(selector) {{
    return selector === ".record-core" ? recordCore : makeTrackedElement();
  }},
  querySelectorAll() {{
    return [];
  }},
  createElement() {{
    return makeTrackedElement();
  }},
  addEventListener() {{}},
}};
globalThis.window = {{
  addEventListener() {{}},
  location: {{ protocol: "http:", host: "127.0.0.1:8000" }},
}};
globalThis.requestAnimationFrame = () => {{}};
let scheduledReconnect = null;
globalThis.setTimeout = (callback, delay) => {{
  scheduledReconnect = {{ callback, delay }};
  return scheduledReconnect;
}};
globalThis.clearTimeout = () => {{}};
vm.runInThisContext({json.dumps(script)}, {{ filename: "app.js" }});

globalThis.__secretPondTest.showError("action failed");
assert.strictEqual(elements.errorBanner.hidden, false);
assert.strictEqual(elements.errorBanner.textContent, "action failed");
assert.strictEqual(elements.errorBadge.textContent, "Error Active");
assert.strictEqual(elements.errorBadge.className, "status-pill hot");

globalThis.__secretPondTest.showError("");
assert.strictEqual(elements.errorBanner.hidden, true);
assert.strictEqual(elements.errorBanner.textContent, "");
assert.strictEqual(elements.errorBadge.textContent, "Error None");
assert.strictEqual(elements.errorBadge.className, "status-pill muted");

globalThis.__secretPondTest.state.snapshot = null;
globalThis.__secretPondTest.state.deviceError = "devices failed";
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.textContent, "devices failed");
assert.strictEqual(elements.errorBadge.textContent, "Error Active");

globalThis.__secretPondTest.state.deviceError = null;
globalThis.__secretPondTest.state.diagnosticsError = null;
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, true);
assert.strictEqual(elements.errorBadge.textContent, "Error None");

delete window.WebSocket;
delete globalThis.WebSocket;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "Sync Polling");
assert.strictEqual(elements.syncBadge.className, "status-pill muted");

window.WebSocket = function FakeWebSocket() {{}};
globalThis.__secretPondTest.state.stateSocket = {{}};
globalThis.__secretPondTest.state.websocketConnected = false;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "Sync Connecting");
assert.strictEqual(elements.syncBadge.className, "status-pill muted");

globalThis.__secretPondTest.state.websocketConnected = true;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "Sync Live");
assert.strictEqual(elements.syncBadge.className, "status-pill safe");

globalThis.__secretPondTest.state.stateSocket = null;
globalThis.__secretPondTest.state.websocketConnected = false;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "Sync Polling");

class FakeStateSocket {{
  static instances = [];

  constructor(url) {{
    this.url = url;
    this.handlers = {{}};
    FakeStateSocket.instances.push(this);
  }}

  addEventListener(eventName, handler) {{
    this.handlers[eventName] = handler;
  }}

  emit(eventName, payload = {{}}) {{
    this.handlers[eventName]?.(payload);
  }}

  close() {{
    this.emit("close");
  }}
}}
window.WebSocket = FakeStateSocket;
globalThis.WebSocket = FakeStateSocket;
globalThis.__secretPondTest.state.snapshot = null;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.syncBadge.textContent, "Sync Polling");

globalThis.__secretPondTest.connectStateSocket();
const connectedSocket = FakeStateSocket.instances[0];
assert.strictEqual(connectedSocket.url, "ws://127.0.0.1:8000/ws/state");
assert.strictEqual(globalThis.__secretPondTest.state.stateSocket, connectedSocket);
assert.strictEqual(elements.syncBadge.textContent, "Sync Connecting");

connectedSocket.emit("open");
assert.strictEqual(globalThis.__secretPondTest.state.websocketConnected, true);
assert.strictEqual(elements.syncBadge.textContent, "Sync Live");
assert.strictEqual(elements.syncBadge.className, "status-pill safe");

connectedSocket.emit("close");
assert.strictEqual(globalThis.__secretPondTest.state.stateSocket, null);
assert.strictEqual(globalThis.__secretPondTest.state.websocketConnected, false);
assert.strictEqual(elements.syncBadge.textContent, "Sync Polling");
assert.strictEqual(scheduledReconnect.delay, 1500);

const activeSettings = {{
  voice_stack: {{ mode: "live_ephemeral" }},
  input_control: {{
    minimum_recording_seconds: 3,
    maximum_recording_seconds: 120,
  }},
  audio: {{ sample_rate: 48000, channels: 2 }},
  devices: {{ input_device_id: null, output_device_id: null }},
  layers: {{}},
}};
const snapshot = {{
  armed: true,
  is_recording: true,
  recording_elapsed_seconds: 4.2,
  recording_remaining_seconds: 115.8,
  participant_count: 7,
  last_error: "stack failed",
  playback: {{
    output_running: false,
    output_latest_error: "stream failed",
    layers: {{}},
  }},
  settings: {{ active: activeSettings, draft: activeSettings }},
}};

globalThis.__secretPondTest.state.snapshot = snapshot;
globalThis.__secretPondTest.state.draft = activeSettings;
globalThis.__secretPondTest.state.diagnosticsError = "diagnostics failed";
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(
  elements.errorBanner.textContent,
  "stack failed · stream failed · diagnostics failed",
);
assert.strictEqual(elements.errorBadge.textContent, "Error Active");
assert.strictEqual(elements.errorBadge.className, "status-pill hot");
globalThis.__secretPondTest.state.snapshot.last_error = null;
globalThis.__secretPondTest.state.snapshot.playback.output_latest_error = null;
globalThis.__secretPondTest.state.diagnosticsError = null;
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBadge.textContent, "Error None");
globalThis.__secretPondTest.state.recordingStopInFlight = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.stopButton.disabled, false);
assert.strictEqual(elements.recordCoreStatus.textContent, "Capturing");
assert.strictEqual(recordCore.classList.contains("recording"), true);
assert.strictEqual(recordCore.classList.contains("armed"), false);
assert.strictEqual(elements.armButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(elements.disarmButton.getAttribute("aria-pressed"), "false");

globalThis.__secretPondTest.state.recordingStopInFlight = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "Wait for recording processing to finish.");

globalThis.__secretPondTest.state.recordingStopInFlight = false;
globalThis.__secretPondTest.state.snapshot.is_recording = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.recordCoreStatus.textContent, "Armed");
assert.strictEqual(recordCore.classList.contains("recording"), false);
assert.strictEqual(recordCore.classList.contains("armed"), true);
assert.strictEqual(elements.applyButton.disabled, false);
assert.strictEqual(elements.applyButton.title, "");

globalThis.__secretPondTest.state.recordingStopInFlight = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.armButton.disabled, true);
assert.strictEqual(elements.disarmButton.disabled, true);
assert.strictEqual(elements.startButton.disabled, true);
assert.strictEqual(elements.stopButton.disabled, true);
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "Wait for recording processing to finish.");
assert.strictEqual(elements.recordCoreStatus.textContent, "Processing");
assert.strictEqual(recordCore.classList.contains("armed"), false);

globalThis.__secretPondTest.state.recordingStopInFlight = false;
globalThis.__secretPondTest.state.snapshot.armed = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.recordCoreStatus.textContent, "Safe");
assert.strictEqual(recordCore.classList.contains("armed"), false);
assert.strictEqual(recordCore.classList.contains("recording"), false);
assert.strictEqual(elements.armButton.getAttribute("aria-pressed"), "false");
assert.strictEqual(elements.disarmButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(elements.applyButton.disabled, false);
assert.strictEqual(elements.applyButton.title, "");

(async () => {{
  const busySpaceEvent = {{
    code: "Space",
    repeat: false,
    defaultPrevented: false,
    preventDefault() {{
      this.defaultPrevented = true;
    }},
  }};
  globalThis.__secretPondTest.state.spaceRecording = false;
  globalThis.__secretPondTest.state.recordingStopInFlight = true;
  globalThis.__secretPondTest.state.snapshot.armed = true;
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  await globalThis.__secretPondTest.startFromSpace(busySpaceEvent);
  assert.strictEqual(busySpaceEvent.defaultPrevented, true);
  assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, false);

  let resolvePoll = null;
  globalThis.fetch = (path) => {{
    if (path === "/api/recording/poll-auto-stop") {{
      return new Promise((resolve) => {{
        resolvePoll = () =>
          resolve({{
            ok: true,
            json: async () => ({{ outcome: null, state: snapshot }}),
          }});
      }});
    }}
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  globalThis.__secretPondTest.state.snapshot.is_recording = true;
  globalThis.__secretPondTest.state.snapshot.recording_remaining_seconds = 12.3;
  globalThis.__secretPondTest.state.recordingStopInFlight = false;
  const pollPromise = globalThis.__secretPondTest.control("/api/recording/poll-auto-stop", {{
    syncDraft: false,
  }});
  assert.strictEqual(globalThis.__secretPondTest.state.recordingStopInFlight, true);
  assert.strictEqual(elements.stopButton.disabled, true);
  resolvePoll();
  await pollPromise;
  assert.strictEqual(globalThis.__secretPondTest.state.recordingStopInFlight, false);
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    subprocess.run([node, "-e", harness], check=True, text=True)


def test_recording_presets_match_processing_bounds() -> None:
    for preset in RECORDING_PRESETS.values():
        RecordingProcessingSettings.model_validate(preset)


def test_api_diagnostics_reports_source_health_and_recent_events(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    runtime.logger.log_event(
        "recording.accepted",
        {"participant_count": 1},
        timestamp="2026-06-03T10:00:00+00:00",
    )
    runtime.logger.log_event(
        "settings.applied",
        {"changed": ["voice.volume_db"]},
        timestamp="2026-06-03T10:01:00+00:00",
    )

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    sources = {source["id"]: source for source in payload["sources"]}
    assert sources["low"]["exists"] is True
    assert sources["low"]["path"] == "data/sources/low.wav"
    assert sources["low"]["size_bytes"] > 0
    assert sources["low"]["modified_at"] is not None
    assert sources["mid"]["exists"] is True
    assert sources["voice"]["exists"] is True
    assert sources["voice"]["path"] == "data/voice/voice_stack_raw.wav"
    assert payload["events"]["path"] == "data/logs/events.jsonl"
    assert payload["events"]["exists"] is True
    assert payload["events"]["recent"][0]["event_type"] == "settings.applied"
    assert payload["events"]["recent"][1]["event_type"] == "recording.accepted"


def test_api_diagnostics_marks_missing_prepared_sources(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    sources = {source["id"]: source for source in response.json()["sources"]}
    assert sources["low"]["exists"] is False
    assert sources["low"]["size_bytes"] == 0
    assert sources["low"]["modified_at"] is None
    assert sources["mid"]["exists"] is False
    assert sources["voice"]["exists"] is True


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


def test_api_settings_reset_is_blocked_while_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    response = client.post("/api/settings/reset")

    assert response.status_code == 409
    assert response.json()["detail"] == "cannot reset draft settings while recording"
    state = client.get("/api/state").json()
    assert state["is_recording"] is True
    assert state["settings"]["active"]["layers"]["voice"]["volume_db"] == -18.0
    assert state["settings"]["draft"]["layers"]["voice"]["volume_db"] == -9.0


def test_api_participants_reset_zeroes_count(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    runtime = client.app.state.runtime
    runtime.participants.increment()
    runtime.participants.increment()

    response = client.post("/api/participants/reset")

    assert response.status_code == 200
    state = response.json()["state"]
    assert state["participant_count"] == 0
    assert state["settings"]["draft"]["layers"]["voice"]["volume_db"] == -18.0
    assert runtime.participants.get_count() == 0


def test_api_participants_reset_is_blocked_while_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    runtime = client.app.state.runtime
    runtime.participants.increment()
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    response = client.post("/api/participants/reset")

    assert response.status_code == 409
    assert response.json()["detail"] == "cannot reset participant count while recording"
    state = client.get("/api/state").json()
    assert state["is_recording"] is True
    assert state["participant_count"] == 1
    assert runtime.participants.get_count() == 1


def test_api_settings_reset_is_blocked_during_apply_and_restart(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    renderer = BlockingStageRenderer(runtime.renderer)
    runtime.renderer = renderer
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        apply_future = executor.submit(client.post, "/api/settings/apply-and-restart")
        assert renderer.entered.wait(timeout=2)
        reset_future = executor.submit(client.post, "/api/settings/reset")
        try:
            response = wait_for_future_response(reset_future)
            assert response.status_code == 409
            assert response.json()["detail"] == (
                "maintenance actions are unavailable while another operation is running"
            )
            assert runtime.settings_state.draft.layers["voice"].volume_db == -9.0
        finally:
            renderer.release.set()

        apply_response = apply_future.result(timeout=2)

    assert apply_response.status_code == 200


def test_api_participants_reset_is_blocked_during_apply_and_restart(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    renderer = BlockingStageRenderer(runtime.renderer)
    runtime.renderer = renderer
    runtime.participants.increment()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        apply_future = executor.submit(client.post, "/api/settings/apply-and-restart")
        assert renderer.entered.wait(timeout=2)
        reset_future = executor.submit(client.post, "/api/participants/reset")
        try:
            response = wait_for_future_response(reset_future)
            assert response.status_code == 409
            assert response.json()["detail"] == (
                "maintenance actions are unavailable while another operation is running"
            )
            assert runtime.participants.get_count() == 1
        finally:
            renderer.release.set()

        apply_response = apply_future.result(timeout=2)

    assert apply_response.status_code == 200
    assert runtime.participants.get_count() == 1


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


def test_api_playback_restart_requires_running_output(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.post("/api/settings/apply-and-restart")

    response = client.post("/api/playback/restart")

    assert response.status_code == 409
    assert "running" in response.json()["detail"]


def test_api_playback_restart_resets_frame_cursor(tmp_path: Path) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    client.app.state.runtime.player.next_block(10)

    response = client.post("/api/playback/restart")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"]["playback"]["frame_cursor"] == 0
    assert payload["state"]["playback"]["is_playing"] is True
    assert payload["state"]["playback"]["output_running"] is True
    assert output.stop_calls == 1
    assert output.start_calls == 2


def test_api_playback_restart_restores_running_output_after_start_failure(
    tmp_path: Path,
) -> None:
    output = FakeOutput(fail_start=OSError("restart failed"), fail_start_on_call=2)
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    runtime = client.app.state.runtime
    runtime.player.next_block(10)

    response = client.post("/api/playback/restart")

    assert response.status_code == 409
    assert "restart failed" in response.json()["detail"]
    assert output.stop_calls == 1
    assert output.start_calls == 3
    state = client.get("/api/state").json()
    assert state["playback"]["frame_cursor"] == 10
    assert state["playback"]["is_playing"] is True
    assert state["playback"]["output_running"] is True


def test_api_playback_restart_restores_player_snapshot_when_resume_fails(
    tmp_path: Path,
) -> None:
    player = LayeredLoopPlayer()
    stream_factory = RestartFailureStreamFactory(fail_start_on_calls={2, 3})
    output = SoundDeviceOutput(
        sample_rate=api_settings().audio.sample_rate,
        channels=api_settings().audio.channels,
        player=player,
        stream_factory=stream_factory,
    )
    client = create_test_client(tmp_path, with_sources=True, player=player, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    runtime = client.app.state.runtime
    runtime.player.next_block(10)

    response = client.post("/api/playback/restart")

    assert response.status_code == 409
    assert "stream start failed" in response.json()["detail"]
    assert "rollback resume failed" in response.json()["detail"]
    state = client.get("/api/state").json()
    assert state["playback"]["frame_cursor"] == 10
    assert state["playback"]["is_playing"] is True
    assert state["playback"]["output_running"] is False


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
