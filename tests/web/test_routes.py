from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pytest
from fastapi.testclient import TestClient

from secret_pond.app import create_app
from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.output import SoundDeviceOutput
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.audio.recorder import FakeRecorder
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    DeviceSettings,
    InputControlSettings,
    RecordingProcessingSettings,
    SourceSelectionSettings,
    VoiceStackSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.runtime import PlaybackOutput, build_runtime
from secret_pond.services.settings_store import SettingsState, SettingsStore

RUNTIME_CONFIG_FIELDS = [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
]


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


def api_settings_for_sixty_second_voice_loop(
    *,
    mode: Literal["live_ephemeral", "test_library"] = "live_ephemeral",
) -> AppSettings:
    settings = AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=60),
        input_control=InputControlSettings(
            minimum_recording_seconds=0.0,
            maximum_recording_seconds=120.0,
        ),
        recording=RecordingProcessingSettings(
            gain_db=0.0,
            normalize_peak=0.2,
            highpass_hz=90.0,
            lowpass_hz=3_000.0,
            presence_gain_db=0.0,
            reverb_mix=0.0,
            delay_mix=0.0,
            fade_ms=0,
        ),
        voice_stack=VoiceStackSettings(
            mode=mode,
            loop_seconds=60,
            insert_gain_db=0.0,
        ),
    )
    layers = {
        **settings.layers,
        "low": settings.layers["low"].model_copy(update={"enabled": False}),
        "mid": settings.layers["mid"].model_copy(update={"enabled": False}),
        "voice": settings.layers["voice"].model_copy(
            update={"enabled": True, "volume_db": 0.0},
        ),
    }
    return settings.model_copy(update={"layers": layers}, deep=True)


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


def twenty_second_voice_take() -> AudioBuffer:
    sample_rate = 8_000
    frames = 20 * sample_rate
    t = np.arange(frames, dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * 500.0 * t).astype(np.float32) * 0.08
    return AudioBuffer(samples=np.column_stack([tone, tone]), sample_rate=sample_rate)


def assert_timestamped_voice_filename(path: str, suffix: str) -> None:
    name = Path(path).name
    assert name.endswith(suffix)
    timestamp = name.removesuffix(suffix)
    assert len(timestamp) == 22
    assert timestamp[8] == "T"
    assert timestamp[-1] == "Z"
    assert timestamp[:8].isdigit()
    assert timestamp[9:-1].isdigit()


def corrupt_settings_json(paths: ProjectPaths) -> None:
    paths.settings_file.write_text("{", encoding="utf-8")


def corrupt_participant_count_json(paths: ProjectPaths) -> None:
    paths.participant_count_file.parent.mkdir(parents=True, exist_ok=True)
    paths.participant_count_file.write_text("{", encoding="utf-8")


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
        self.device_id = None

    def set_device_id(self, device_id: str | None) -> None:
        if self.is_running:
            msg = "cannot change output device while running"
            raise RuntimeError(msg)
        self.device_id = device_id

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


class DeviceAwareFakeRecorder(FakeRecorder):
    def __init__(self, takes: AudioBuffer | list[AudioBuffer]) -> None:
        super().__init__(takes)
        self.device_id = None

    def set_device_id(self, device_id: str | None) -> None:
        if self.is_recording:
            msg = "cannot change input device while recording"
            raise RuntimeError(msg)
        self.device_id = device_id


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


class FailingLayerRenderer:
    def __init__(self, delegate, error: Exception) -> None:
        self.delegate = delegate
        self.error = error

    def render_layer(self, layer_id, settings):
        if layer_id == "voice":
            raise self.error
        return self.delegate.render_layer(layer_id, settings)

    def render_all(self, settings):
        return self.delegate.render_all(settings)

    def stage_all(self, settings):
        return self.delegate.stage_all(settings)


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
        self.patch_draft_owned_during_call = False

    def load(self):
        self.lock_owned_during_load = self.lock._is_owned()
        return self.delegate.load()

    def patch_draft(self, patch):
        self.patch_draft_owned_during_call = self.lock._is_owned()
        return self.delegate.patch_draft(patch)

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


class FailingEventLogger:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    def log_event(self, event_type, payload=None):
        raise OSError("event log unavailable")

    def read_events(self, limit=None):
        return self.delegate.read_events(limit)


def create_test_client(
    tmp_path: Path,
    *,
    with_sources: bool = False,
    recorder: Any | None = None,
    player: LayeredLoopPlayer | None = None,
    output: PlaybackOutput | None = None,
    settings: AppSettings | None = None,
    device_registry=None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    paths = ProjectPaths(tmp_path)
    resolved_settings = settings or api_settings()
    if with_sources:
        write_source_files(paths, resolved_settings)
    SettingsStore(paths).save(SettingsState(active=resolved_settings, draft=resolved_settings))
    resolved_device_registry = (
        device_registry if device_registry is not None else fake_device_registry()
    )
    runtime = build_runtime(
        tmp_path,
        recorder=recorder or FakeRecorder(recorder_take()),
        player=player,
        output=output,
        device_registry=resolved_device_registry,
    )
    return TestClient(
        create_app(runtime=runtime),
        raise_server_exceptions=raise_server_exceptions,
    )


STATIC_APP_BOOTSTRAP = (
    "\nbindEvents();\nrenderWorkspaceTabs();\ndrawCanvas();\n"
    "connectStateSocket();\nrefreshAll();\n"
)

STATIC_APP_NULL_DOM_SETUP = """
globalThis.document = {
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return {}; },
  addEventListener() {},
};
globalThis.window = {
  addEventListener() {},
  location: { protocol: "http:", host: "127.0.0.1:8000", search: "" },
};
globalThis.requestAnimationFrame = () => {};
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
"""

STATIC_APP_RENDER_DOM_SETUP = """
const elements = {};
const makeElement = () => {
  const element = {
    children: [],
    innerHTML: "",
    textContent: "",
    className: "",
    hidden: false,
    disabled: false,
    title: "",
    value: "",
    attributes: {},
    _classes: new Set(),
    classList: {
      toggle(name, force) {
        if (force) element._classes.add(name);
        else element._classes.delete(name);
      },
      contains(name) {
        return element._classes.has(name);
      },
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    getAttribute(name) {
      return this.attributes[name] || null;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    append(...children) {
      this.children.push(...children);
    },
    addEventListener() {},
    querySelector() {
      return makeElement();
    },
    querySelectorAll() {
      return [];
    },
  };
  return element;
};
const createElement = () => makeElement();
const recordCore = createElement();
const recordOutcome = createElement();
recordOutcome.className = "record-outcome ready";
elements.recordOutcomeStatus = createElement();
elements.recordOutcomeStatus.parentElement = recordOutcome;
elements.recordOutcomeDetail = createElement();
elements.recordOutcomeDetail.parentElement = recordOutcome;
globalThis.document = {
  getElementById(id) {
    if (!elements[id]) elements[id] = createElement();
    return elements[id];
  },
  createElement() {
    return createElement();
  },
  querySelector(selector) {
    return selector === ".record-core" ? recordCore : createElement();
  },
  querySelectorAll() {
    return [];
  },
  addEventListener() {},
};
globalThis.window = {
  addEventListener() {},
  location: { protocol: "http:", host: "127.0.0.1:8000", search: "" },
};
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
globalThis.requestAnimationFrame = () => {};
"""


def static_app_test_script(tmp_path: Path, exports: str) -> str:
    client = create_test_client(tmp_path)
    return client.get("/static/app.js").text.replace(
        STATIC_APP_BOOTSTRAP,
        f"\nglobalThis.__secretPondTest = {exports};\n",
    )


def run_static_app_harness(
    tmp_path: Path,
    *,
    exports: str,
    body: str,
    dom_setup: str = STATIC_APP_NULL_DOM_SETUP,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for static app behavior smoke test")

    script = static_app_test_script(tmp_path, exports)
    body = body.replace("{{", "{").replace("}}", "}")
    harness = f"""
const assert = require("assert");
const vm = require("vm");
{dom_setup}
vm.runInThisContext({json.dumps(script)}, {{ filename: "app.js" }});

{body}
"""
    subprocess.run([node, "-e", harness], check=True, text=True)


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


def api_settings_with_voice_only_layers() -> AppSettings:
    settings = api_settings()
    layers = {
        **settings.layers,
        "low": settings.layers["low"].model_copy(update={"enabled": False}),
        "mid": settings.layers["mid"].model_copy(update={"enabled": False}),
        "voice": settings.layers["voice"].model_copy(update={"enabled": True}),
    }
    return settings.model_copy(update={"layers": layers}, deep=True)


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


def draft_with_voice_stack_loop_seconds(loop_seconds: int) -> dict:
    return api_settings().model_copy(
        update={
            "voice_stack": api_settings().voice_stack.model_copy(
                update={"loop_seconds": loop_seconds}
            )
        },
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
                host_api_name="Core Audio",
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
                host_api_name="WASAPI",
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


def events_by_type(client: TestClient, event_type: str) -> list[dict]:
    return [
        event
        for event in client.app.state.runtime.logger.read_events()
        if event["event_type"] == event_type
    ]


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
    assert 'id="modeBadge"' not in response.text
    assert "녹음 보관 확인 중" not in response.text
    assert 'id="lastEventBadge"' in response.text
    assert 'id="errorBadge"' in response.text
    assert "오류 없음" in response.text
    assert 'class="error-banner notice-banner"' in response.text
    assert 'aria-live="polite"' in response.text
    assert 'id="deviceHealthBadge"' in response.text
    assert 'id="syncBadge"' in response.text
    assert '<details class="device-panel" open>' not in response.text
    assert "앱 재시작 적용" not in response.text
    assert "저장 안 된 변경 없음" not in response.text
    assert "No pending changes" not in response.text
    assert 'aria-label="녹음 제어"' in response.text
    assert 'aria-label="runtime controls"' not in response.text
    assert 'id="captureGateSwitch"' in response.text
    assert 'role="switch"' in response.text
    assert 'aria-checked="false"' in response.text
    assert 'aria-describedby="captureGateState"' in response.text
    top_actions = slice_between(
        response.text,
        '<section class="top-actions" aria-label="운영 콘솔">',
        "</section>",
    )
    assert "재생" not in top_actions
    assert "중지" not in top_actions
    assert "다시 재생" not in top_actions
    assert 'class="panel operation-panel"' in response.text
    assert 'class="operation-card playback-panel"' in response.text
    assert 'aria-labelledby="playbackPanelTitle"' in response.text
    operation_panel = slice_between(
        response.text,
        '<section class="panel operation-panel" aria-label="운영 콘솔">',
        '<section class="panel workspace-panel main-workspace-panel" aria-label="작업 영역">',
    )
    playback_panel = slice_between(
        operation_panel,
        '<section class="operation-card playback-panel"',
        '<section class="operation-card record-panel"',
    )
    record_panel = slice_between(
        operation_panel,
        '<section class="operation-card record-panel"',
        "</section>\n          </div>",
    )
    right_stack = slice_between(
        response.text,
        '<div class="right-stack-panel">',
        "\n        </div>\n      </section>",
    )
    system_panel = slice_between(
        right_stack,
        '<section class="panel system-panel"',
        "</section>",
    )
    assert operation_panel.index("Playback") < operation_panel.index("Voice Capture")
    assert 'id="playbackPanelTitle"' in playback_panel
    assert "Playback" in playback_panel
    assert '<small lang="ko">재생</small>' in playback_panel
    assert 'id="outputControlSummary"' in playback_panel
    playback_heading = slice_between(
        playback_panel,
        '<div class="panel-heading inline playback-heading">',
        "</div>\n              <div class=\"playback-status-stack\">",
    )
    assert 'id="pendingBadge"' in playback_heading
    assert 'class="status-pill hot"' in playback_heading
    assert 'role="status"' in playback_heading
    assert 'aria-live="polite"' in playback_heading
    assert "hidden" in playback_heading
    assert playback_heading.index("Playback") < playback_heading.index("pendingBadge")
    assert 'id="startOutputButton" class="button playback-button playback-start"' in playback_panel
    assert 'id="stopOutputButton" class="button playback-button playback-stop"' in playback_panel
    assert 'id="restartOutputButton"' in playback_panel
    assert (
        'id="restartOutputButton" class="button playback-button playback-restart" '
        'type="button" disabled'
    ) in playback_panel
    assert 'id="applyButton" class="button playback-apply-button"' in playback_panel
    assert "재생" in playback_panel
    assert "중지" in playback_panel
    assert "다시 재생" in playback_panel
    assert "변경사항 적용 후 재생" in playback_panel
    assert "출력 시작" not in playback_panel
    assert "출력 중지" not in playback_panel
    assert "출력 재시작" not in playback_panel
    assert "적용 후 재시작" not in playback_panel
    assert "Apply and Restart" not in playback_panel
    assert "녹음 준비" in record_panel
    assert 'id="storageModePanel"' in record_panel
    assert 'id="storageModeSummary"' in record_panel
    assert 'id="storageModeLiveButton"' in record_panel
    assert 'id="storageModeLibraryButton"' in record_panel
    assert "녹음 보관" in record_panel
    assert "전시" in record_panel
    assert "테스트 저장" in record_panel
    assert "개별 녹음 보관 안 함" not in record_panel
    assert "accepted clip 저장" not in record_panel
    assert record_panel.index("녹음 보관") < record_panel.index("녹음 준비")
    assert 'id="captureGate" class="capture-gate capture-gate-off"' in record_panel
    assert 'id="captureGateSwitch"' in record_panel
    assert 'role="switch"' in record_panel
    assert 'id="captureGateState"' in record_panel
    assert "녹음 준비 꺼짐" in record_panel
    assert 'id="armButton"' not in record_panel
    assert 'id="disarmButton"' not in record_panel
    assert "Arm" not in record_panel
    assert "Disarm" not in record_panel
    assert "Safe" not in record_panel
    assert "안전" not in record_panel
    assert 'id="startButton"' in record_panel
    assert 'id="stopButton"' in record_panel
    assert "테이크 시작" in record_panel
    take_console = slice_between(
        record_panel,
        '<div class="take-console">',
        "</div>\n              <div class=\"record-limits\"",
    )
    assert 'class="record-orbit"' in take_console
    assert 'id="startButton"' in take_console
    assert 'id="stopButton"' in take_console
    assert 'id="systemStatus"' in system_panel
    assert 'id="sourceHealthList"' in system_panel
    assert 'id="eventLogSummary"' in system_panel
    assert 'class="panel workspace-panel main-workspace-panel"' in response.text
    main_workspace = slice_between(
        response.text,
        '<section class="panel workspace-panel main-workspace-panel" aria-label="작업 영역">',
        '<div class="right-stack-panel">',
    )
    assert 'class="workspace-tabs"' in main_workspace
    assert 'role="tablist"' in main_workspace
    assert 'id="workspaceTabTreatment"' in main_workspace
    assert 'data-workspace-tab="treatment"' in main_workspace
    assert 'aria-controls="workspacePaneTreatment"' in main_workspace
    assert 'aria-selected="true"' in main_workspace
    assert 'id="workspaceTabStack"' in main_workspace
    assert 'data-workspace-tab="stack"' in main_workspace
    assert 'aria-controls="workspacePaneStack"' in main_workspace
    assert 'aria-selected="false"' in main_workspace
    assert 'id="workspaceTabMixer"' in main_workspace
    assert 'data-workspace-tab="mixer"' in main_workspace
    assert 'aria-controls="workspacePaneMixer"' in main_workspace
    assert 'class="settings-library"' in main_workspace
    assert 'id="settingsSnapshotSaveButton"' in main_workspace
    assert 'id="settingsSnapshotSelect"' in main_workspace
    assert "저장된 세팅 없음" in main_workspace
    assert 'id="settingsSnapshotApplyButton"' in main_workspace
    assert 'id="settingsSnapshotDeleteButton"' in main_workspace
    assert 'id="workspacePaneTreatment"' in main_workspace
    assert 'data-workspace-pane="treatment"' in main_workspace
    assert 'id="workspacePaneStack"' in main_workspace
    assert 'data-workspace-pane="stack"' in main_workspace
    assert 'id="workspacePaneMixer"' in main_workspace
    assert 'data-workspace-pane="mixer"' in main_workspace
    stack_pane_start = (
        'id="workspacePaneStack"\n'
        '            class="workspace-pane"\n'
        '            role="tabpanel"'
    )
    assert stack_pane_start in main_workspace
    assert 'data-workspace-pane="stack"\n            hidden' in main_workspace
    assert 'data-workspace-pane="mixer"\n            hidden' in main_workspace
    assert 'class="workspace-section voice-panel"' in response.text
    assert 'aria-labelledby="voiceStackPanelTitle"' in response.text
    settings_panel = slice_between(
        main_workspace,
        '<section class="workspace-section settings-panel"',
        '</div>\n\n          <div\n            id="workspacePaneStack"',
    )
    voice_panel = slice_between(
        main_workspace,
        '<section class="workspace-section voice-panel"',
        '</div>\n\n          <div\n            id="workspacePaneMixer"',
    )
    mixer_panel = slice_between(
        main_workspace,
        '<section class="workspace-section mixer-panel"',
        "\n          </div>\n        </section>",
    )
    assert main_workspace.index("Voice Treatment") < main_workspace.index("Voice Stack")
    assert main_workspace.index("Voice Stack") < main_workspace.index("Loop Mixer")
    assert "Voice Treatment" in settings_panel
    assert 'id="layerControls"' in mixer_panel
    assert 'id="voiceLayerControls"' not in mixer_panel
    assert 'id="voiceStackControls"' in voice_panel
    assert 'id="voiceLayerControls"' in voice_panel
    assert 'id="voiceStackPanelTitle"' in voice_panel
    assert 'id="storageModePanel"' not in voice_panel
    assert "Voice Stack" in voice_panel
    assert '<small lang="ko">목소리 스택</small>' in voice_panel
    assert 'id="deviceStatus"' not in response.text
    assert 'id="inputDeviceName"' not in response.text
    assert 'id="outputDeviceName"' not in response.text
    assert 'id="deviceRestartNotice"' not in response.text
    assert 'id="deviceApplyNotice"' not in system_panel
    assert "장치 변경은 선택 즉시 적용됩니다." not in system_panel
    assert "Input Device" not in system_panel
    assert "Output Device" not in system_panel
    assert "<span>입력</span>" in system_panel
    assert "<span>출력</span>" in system_panel
    assert 'id="inputDeviceSelect"' in system_panel
    assert 'id="outputDeviceSelect"' in system_panel
    assert 'id="inputDeviceSelect"' not in record_panel
    assert 'id="outputDeviceSelect"' not in record_panel
    assert 'id="recordOutcomeStatus"' in response.text
    assert 'id="recordOutcomeDetail"' in response.text
    assert 'class="record-limits"' in response.text
    assert 'id="minimumRecordingTime"' in response.text
    assert 'id="maximumRecordingTime"' in response.text
    assert 'id="recordingPresets"' in response.text
    assert 'role="group"' in response.text
    assert 'aria-label="녹음 처리 프리셋"' in response.text
    assert 'aria-pressed="false"' in response.text
    assert response.text.count('class="preset-button"') == 4
    assert "Soft" in response.text
    assert "Misty" in response.text
    assert "Dense" in response.text
    assert "Clearer Voice" in response.text
    assert '<small lang="ko">부드럽게</small>' in response.text
    assert '<small lang="ko">선명한 목소리</small>' in response.text
    assert 'class="right-stack-panel"' in response.text
    assert 'aria-label="시스템 진단"' in right_stack
    assert 'for="inputDeviceSelect"' in system_panel
    assert 'for="outputDeviceSelect"' in system_panel


def test_settings_reset_is_hidden_behind_maintenance_panel(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    operation_panel = slice_between(
        response.text,
        '<section class="panel operation-panel" aria-label="운영 콘솔">',
        '<section class="panel workspace-panel main-workspace-panel" aria-label="작업 영역">',
    )
    playback_panel = slice_between(
        operation_panel,
        '<section class="operation-card playback-panel"',
        '<section class="operation-card record-panel"',
    )
    main_workspace = slice_between(
        response.text,
        '<section class="panel workspace-panel main-workspace-panel" aria-label="작업 영역">',
        '<div class="right-stack-panel">',
    )
    settings_panel = slice_between(
        main_workspace,
        '<section class="workspace-section settings-panel"',
        '</div>\n\n          <div\n            id="workspacePaneStack"',
    )
    voice_panel = slice_between(
        main_workspace,
        '<section class="workspace-section voice-panel"',
        '</div>\n\n          <div\n            id="workspacePaneMixer"',
    )
    maintenance_panel = slice_between(
        settings_panel,
        '<details class="maintenance-panel">',
        "</details>",
    )
    assert "변경사항 적용 후 재생" in playback_panel
    assert "Apply and Restart" not in playback_panel
    assert "적용 후 재시작" not in settings_panel
    assert "적용 후 재시작" not in voice_panel
    assert "변경 취소" not in playback_panel
    assert "<summary>관리</summary>" in maintenance_panel
    assert "Maintenance" not in maintenance_panel
    assert 'id="resetButton"' in maintenance_panel
    assert 'id="resetParticipantsButton"' in maintenance_panel
    assert "변경 취소" in maintenance_panel
    assert "참여자 초기화" in maintenance_panel


def test_static_ui_assets_are_served(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    page = client.get("/")
    styles = client.get("/static/styles.css")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    normalized_styles = " ".join(styles.text.split())
    topbar_rule = slice_between(styles.text, ".topbar {", "}")
    status_strip_rule = slice_between(styles.text, ".status-strip {", "}")
    last_event_badge_rule = slice_between(styles.text, "#lastEventBadge {", "}")
    assert "grid-template-columns: minmax(210px, 0.72fr) minmax(0, 1fr) auto;" in (
        " ".join(topbar_rule.split())
    )
    assert "min-width: 0;" in status_strip_rule
    assert "min-width: 0;" in last_event_badge_rule
    assert "max-width: min(26ch, 100%);" in last_event_badge_rule
    assert "overflow: hidden;" in last_event_badge_rule
    assert "text-overflow: ellipsis;" in last_event_badge_rule
    assert "white-space: nowrap;" in last_event_badge_rule
    assert (
        "grid-template-columns: minmax(300px, 0.82fr) minmax(620px, 1.7fr) "
        "minmax(300px, 0.84fr);"
        in normalized_styles
    )
    assert (
        'grid-template-areas: "ops main side";'
        in normalized_styles
    )
    assert '"record playback mixer settings"' not in styles.text
    assert "align-items: start;" in styles.text
    assert "@media (max-width: 1120px)" in styles.text
    assert ".operation-panel" in styles.text
    assert ".operation-card" in styles.text
    assert ".capture-gate" in styles.text
    assert ".switch-control" in styles.text
    assert ".capture-gate-switch" in styles.text
    assert ".take-console" in styles.text
    assert ".playback-panel" in styles.text
    assert ".playback-actions" in styles.text
    assert ".playback-apply-strip" in styles.text
    assert ".main-workspace-panel" in styles.text
    assert ".workspace-panel" in styles.text
    assert ".workspace-tabs" in styles.text
    assert ".workspace-tab" in styles.text
    assert ".workspace-tab.active" in styles.text
    assert ".settings-library" in styles.text
    assert ".settings-library-controls" in styles.text
    assert ".workspace-pane[hidden]" in styles.text
    assert ".workspace-section" in styles.text
    assert ".right-stack-panel" in styles.text
    assert ".voice-panel" in styles.text
    assert ".device-panel" not in styles.text
    assert ".control-group" in styles.text
    assert ".eq-band-grid" in styles.text
    assert ".frequency-guide" in styles.text
    assert ".label-with-helper" in styles.text
    assert ".label-with-helper small" in styles.text
    assert ".operation-panel,\n.main-workspace-panel,\n.right-stack-panel" in styles.text
    assert "align-content: start;" in styles.text
    assert ".settings-panel .control-row" in styles.text
    assert '"voice voice"' in styles.text
    assert '"input space"' in styles.text
    assert ".input-safety-group" in styles.text
    assert ".voice-band-group" in styles.text
    assert ".space-tail-group" in styles.text
    assert ".settings-panel #recordingControls .voice-band-group .control-group-body" in styles.text
    assert (
        "grid-template-columns: minmax(96px, 0.82fr) minmax(130px, 1fr) "
        "minmax(112px, auto);"
        in normalized_styles
    )
    assert ".precision-control" in styles.text
    assert ".value-input" in styles.text
    assert ".nudge-button" in styles.text
    assert ".mini-button" in styles.text
    assert ".filter-status" in styles.text
    assert ".range-marks" in styles.text
    assert ".layer-preset-row" in styles.text
    assert ".layer-preset-button.active" in styles.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    normalized_script = " ".join(script.text.split())
    assert "state.devices = null" in script.text
    assert "state.diagnostics = null" in script.text
    assert "new WebSocket" in script.text
    assert 'api("/api/diagnostics")' in script.text
    assert "renderStorageModeControls()" in script.text
    assert '"live_ephemeral": "운영 모드"' in script.text
    assert '"test_library": "테스트 모드"' in script.text
    assert "renderLastEventBadge" in script.text
    assert "eventTypeLabels" in script.text
    assert "formatEventType" in script.text
    assert '"system.startup_playback_unavailable": "시작 재생 준비 실패"' in script.text
    assert '"recording.accepted": "녹음 추가"' in script.text
    assert '"playback.started": "출력 시작"' in script.text
    assert "`최근 ${formatEventType(lastEvent.event_type)}`" in script.text
    assert 'label.textContent = formatEventType(event.event_type)' in script.text
    assert "최근 이벤트 없음" in script.text
    assert "최근 이벤트 불러오기 실패" in script.text
    assert "state.diagnostics?.events?.recent?.[0]" in script.text
    assert "currentErrorMessages" in script.text
    assert "renderErrorBadge" in script.text
    assert "describeUiNotice" in script.text
    assert "renderNoticeBanner" in script.text
    assert "오류 있음" in script.text
    assert "오류 없음" in script.text
    assert "주의 있음" in script.text
    assert '"errorBadge").className = "status-pill hot"' in script.text
    assert '"errorBadge").className = "status-pill caution"' in script.text
    assert '"errorBadge").className = "status-pill muted"' in script.text
    assert "renderSyncBadge" in script.text
    assert "실시간 동기화" in script.text
    assert "동기화 연결 중" in script.text
    assert "동기화 확인" in script.text
    assert '"syncBadge").className = "status-pill safe"' in script.text
    assert '"syncBadge").className = "status-pill muted"' in script.text
    assert '!("WebSocket" in window)' in script.text
    assert "renderSyncBadge();\n  const snapshot = state.snapshot;" in script.text
    assert "outputControlSummary" in script.text
    assert "출력 스트림이 실행 중입니다." in script.text
    assert "저장 안 된 오디오 변경이 적용 후 재시작을 기다립니다." in script.text
    assert "syncAppliedSourceSignature" in script.text
    assert "hasSourceFileChanges" in script.text
    assert "sourceSignatureForSettings" in script.text
    assert "renderDeviceHealthBadge" in script.text
    assert "deviceOptionLabel" in script.text
    assert "host_api_name" in script.text
    assert '`${channelCount}ch`' in script.text
    assert "장치 확인 중" in script.text
    assert "장치 정상" in script.text
    assert "장치 주의" in script.text
    assert "장치 오프라인" in script.text
    assert "renderDeviceApplyNotice" not in script.text
    assert "const deriveDashboardControlState = ({" in script.text
    assert "const outputControlBusy = Boolean(applyInFlight || recordingStopBusy)" in script.text
    assert (
        "restartOutputDisabled: outputControlBusy || !outputRunning"
        in script.text
    )
    assert 'control("/api/playback/restart")' in script.text
    assert 'socket.addEventListener("message", async (event) => {' in script.text
    assert (
        "const shouldRefreshSources = activeSourcePathsChanged(state.snapshot, payload)"
        in script.text
    )
    assert (
        "await requestSources({ syncAppliedSourceSignature: true })"
        in script.text
    )
    assert "renderSystemStatus" in script.text
    assert "renderSystemDeviceSelect" in script.text
    assert "deriveSystemDeviceSelectState" in script.text
    assert (
        'renderSystemDeviceSelect( "inputDeviceSelect", devices.input_devices'
        in normalized_script
    )
    assert (
        'renderSystemDeviceSelect( "outputDeviceSelect", devices.output_devices'
        in normalized_script
    )
    assert "sourceHealthList" in script.text
    assert 'date.toLocaleString("ko-KR"' in script.text
    assert "sourceLibraryList" in page.text
    assert "Source Library" in page.text
    assert "파일 라이브러리" in page.text
    assert ".source-library-panel" in styles.text
    assert ".source-category-card" in styles.text
    assert ".source-file-row" in styles.text
    assert ".source-upload-row" in styles.text
    assert ".source-drop-zone" in styles.text
    assert ".source-upload-select" in styles.text
    assert "is-dragging" in styles.text
    assert "state.sources = null" in script.text
    assert 'api("/api/sources")' in script.text
    assert "requestSources" in script.text
    assert "renderSourceLibrary" in script.text
    assert "applySourceMutationPayload" in script.text
    assert "recoverSourceMutationError" in script.text
    assert "selectSourceFile" in script.text
    assert "uploadSourceFile" in script.text
    assert "selectedSourceUploadMode" in script.text
    assert "deriveSourceUploadActionState" in script.text
    assert "deriveSourceFileActionState" in script.text
    assert "handleSourceFileDrop" in script.text
    assert "deleteSourceFile" in script.text
    assert "source-file-select" in script.text
    assert "data-source-select" in script.text
    assert "data-source-delete" in script.text
    assert "data-source-upload" in script.text
    assert "data-source-upload-select" in script.text
    assert "data-source-drop" in script.text
    assert "업로드 후 바로 선택" in script.text
    assert "파일 선택 또는 드롭" in script.text
    assert "현재 선택된 파일은 삭제할 수 없습니다" in script.text
    assert "eventLogSummary" in script.text
    assert "syncDraft: false" in script.text
    assert "!state.websocketConnected && state.snapshot?.is_recording" in script.text
    assert "requestState({ syncDraft: false })" in script.text
    assert 'control("/api/recording/poll-auto-stop", { syncDraft: false })' in script.text
    assert "setRecordStatus(\"processing\", \"녹음 처리 중...\")" in script.text
    assert 'path !== "/api/recording/poll-auto-stop"' in script.text
    assert "recordingStopInFlight" in script.text
    assert (
        'path === "/api/recording/poll-auto-stop" && currentState.recordingStopInFlight'
        in script.text
    )
    assert 'path === "/api/recording/stop" && !snapshot?.is_recording' in script.text
    assert 'path.startsWith("/api/playback/")' in script.text
    assert "await requestState({ syncDraft: false }).catch(() => {})" in script.text
    assert (
        'path === "/api/input/disarm" && !snapshot?.is_recording && '
        "!snapshot?.armed"
        in script.text
    )
    assert "renderRecordingOutcome(payload.outcome)" in script.text
    assert "recordingPresetDefs" in script.text
    assert "applyRecordingPreset" in script.text
    assert "renderRecordingPresets" in script.text
    assert 'button.setAttribute("aria-pressed", active ? "true" : "false")' in script.text
    assert "reversiblePresetDraft(" in script.text
    assert "state.draft.recording = next.draft" in script.text
    assert "state.presetSelections.recording = next.selection" in script.text
    assert "state.snapshot.settings.draft = clone(state.draft)" in script.text
    assert "renderRecordingControls()" in script.text
    assert "renderVoiceStackControls()" in script.text
    assert "const renderVoiceStackControls = () => {" in script.text
    assert "storageModeDetails" in script.text
    assert "renderStorageModeControls" in script.text
    assert "deriveStorageModeControlState" in script.text
    assert "setStorageMode" in script.text
    assert "파일 안 남김" in script.text
    assert "파일 저장" in script.text
    assert "개별 녹음 파일을 남기지 않습니다." not in script.text
    assert "accepted clip을 파일로 저장합니다." not in script.text
    assert "재시작 시 적용" in script.text
    assert ".storage-mode-panel" in styles.text
    assert ".storage-mode-options" in styles.text
    assert ".storage-mode-button" in styles.text
    assert ".storage-mode-button.active" in styles.text
    assert ".storage-mode-badge" not in styles.text
    assert ".storage-mode-panel.pending" in styles.text
    assert ".storage-mode-panel.library" in styles.text
    assert ".record-panel .storage-mode-panel" in styles.text
    assert "const translateUiErrorMessage = (message)" in script.text
    assert "translateUiErrorMessage(error.message)" in script.text
    assert "translateUiErrorMessage(messages.join" not in script.text
    assert 'const workspaceTabNames = ["treatment", "stack", "mixer"]' in script.text
    assert "const workspaceTabFromUrl = () => {" in script.text
    assert "workspaceTab: workspaceTabFromUrl()" in script.text
    assert "const workspaceTabs = () =>" in script.text
    assert "const renderWorkspaceTabs = () => {" in script.text
    assert "const updateWorkspaceUrl = () => {" in script.text
    assert "const setWorkspaceTab = (tabName, options = {}) => {" in script.text
    assert 'url.searchParams.set("workspace", state.workspaceTab)' in script.text
    assert "window.history.replaceState" in script.text
    assert 'window.addEventListener("popstate"' in script.text
    assert '"ArrowRight"' in script.text
    assert '"ArrowLeft"' in script.text
    assert 'button.tabIndex = active ? 0 : -1' in script.text
    assert 'pane.hidden = pane.dataset.workspacePane !== state.workspaceTab' in script.text
    assert 'document.querySelectorAll("[data-workspace-pane]")' in script.text
    assert "renderWorkspaceTabs();" in script.text
    assert 'window.confirm("저장하지 않은 설정 변경을 취소할까요?")' in script.text
    assert 'window.confirm("참여자 녹음 스택을 초기화할까요? 이 작업은 되돌릴 수 없습니다.")' in (
        script.text
    )
    assert '"voiceStackControls"' in script.text
    assert "voiceStackControlDefs" in script.text
    assert 'label: { ko: "목소리 루프 길이", en: "Voice Loop" }' in script.text
    assert "1m center" in script.text
    assert "{ value: 60, label: \"1m\" }" in script.text
    assert "max: 105" in script.text
    assert 'lang="ko"' in script.text
    assert "return `<span class=\"label-with-helper\">${label.en}<small lang=\"ko\">" in (
        script.text
    )
    assert "scheduleDraftSave()" in script.text
    assert "presetLabels" in script.text
    assert 'Soft: { ko: "부드럽게", en: "Soft" }' in script.text
    assert '"Clearer Voice": { ko: "선명한 목소리", en: "Clearer Voice" }' in script.text
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
    assert "renderRecordReadiness" in script.text
    assert "스페이스바를 눌러 녹음" in script.text
    assert "녹음 준비 필요" in script.text
    assert "녹음 준비를 켠 뒤 스페이스바를 누르세요." in script.text
    assert ".record-outcome.armed-ready" in styles.text
    assert "overflow-wrap: anywhere" in styles.text
    assert "녹음 추가됨" in script.text
    assert "너무 짧음" in script.text
    assert "빈 녹음" in script.text
    assert "녹음 준비 꺼짐" in script.text
    assert "녹음 실패" in script.text
    assert "captureReady: armed && !isRecording && !recordingStopBusy" in script.text
    assert (
        'document.querySelector(".record-core").classList.toggle('
        '"armed", controlState.captureReady)'
        in script.text
    )
    assert (
        'document.querySelector(".record-core").classList.toggle("recording", '
        "snapshot.is_recording)"
        in script.text
    )
    assert ".record-core.armed" in styles.text
    assert ".record-core.recording" in styles.text
    assert "controlState.captureGateOn ? \"true\" : \"false\"" in script.text
    assert (
        'captureGateSwitch").classList.toggle("checked", controlState.captureGateOn)'
        in script.text
    )
    assert ".switch-control.checked" in styles.text
    assert '"captureGate").className = `capture-gate ${controlState.captureGateClass}`' in (
        script.text
    )
    assert ".capture-gate.capture-gate-off" in styles.text
    assert ".capture-gate.capture-gate-on" in styles.text
    assert ".capture-gate.capture-gate-recording" in styles.text
    assert ".playback-start" in styles.text
    assert ".playback-stop" in styles.text
    assert ".playback-restart" in styles.text
    assert ".playback-apply-button.attention" in styles.text
    assert "layerPendingBadge" not in script.text
    assert "updateLayerPendingBadge" not in script.text
    assert "layerDraftChangeSummary" not in script.text
    assert "Draft changes:" not in script.text
    assert "재시작 시 적용" in script.text
    assert "켜짐" in script.text
    assert "꺼짐" in script.text
    assert "다음 적용:" not in script.text
    assert "renderLayerCard" in script.text
    assert "layerPresetDefs" in script.text
    assert "applyLayerPreset" in script.text
    assert "Warm Bed" in script.text
    assert "Clear Pocket" in script.text
    assert "Distant Air" in script.text
    assert "renderLayerGroup(\"layerControls\", [\"mid\", \"low\"])" in script.text
    assert "renderLayerGroup(\"voiceLayerControls\", [\"voice\"])" in script.text
    assert "voiceLayerControls" in script.text
    assert "layerControlGroups" in script.text
    assert "reversiblePresetDraft" in script.text
    assert "presetSelectionMatches" in script.text
    assert "clearLayerPresetSelection" in script.text
    assert 'action: "reset-filter"' in script.text
    assert "filterStatus" in script.text
    assert "filter-reset-button" in script.text
    assert "resetLayerFilter" in script.text
    assert 'title: "Filter Range"' in script.text
    assert "필터가 통과시킬 대역을 정합니다." in script.text
    assert 'label: "Low Cut"' in script.text
    assert 'label: "High Cut"' in script.text
    assert "below cut" in script.text
    assert "above cut" in script.text
    assert "이 값보다 낮은 소리를 줄입니다." in script.text
    assert "이 값보다 높은 소리를 줄입니다." in script.text
    assert "아직 적용 안 됨" in script.text
    assert "필터 없음" in script.text
    assert "필터 적용됨" in script.text
    assert "전체 대역:" in script.text
    assert "통과 대역:" in script.text
    assert "변경 대역:" in script.text
    assert "필터 초기화" in script.text
    assert "No filter applied" not in script.text
    assert "Filter applied" not in script.text
    assert "Not applied yet" not in script.text
    assert "Full range:" not in script.text
    assert "Pass range:" not in script.text
    assert "Draft range:" not in script.text
    assert "Reset filter" not in script.text
    assert "수정 대역:" not in script.text
    group_actions_body = slice_between(
        script.text,
        "const groupActionsMarkup = (group, draftSource, activeSource = null) => {",
        "};\n\nconst controlGroup",
    )
    assert "필터 상태" in group_actions_body
    assert "필터 초기화" in group_actions_body
    assert "Bypassed" not in script.text
    assert "Active Filter" not in script.text
    assert "Clear <small" not in script.text
    assert "recordingControlGroups" in script.text
    assert "collapsible: true" in script.text
    assert "frequencyGuideMarkup" in script.text
    assert "20-250 Hz" in script.text
    assert "250 Hz-2 kHz" in script.text
    assert "2 kHz+" in script.text
    assert "renderDraftValue" in script.text
    assert "precisionControlMarkup" in script.text
    assert "snappedValue" in script.text
    assert "active-value" in styles.text
    render_draft_value_body = slice_between(
        script.text,
        "const renderDraftValue = (draftValue, activeValue, suffix) => {",
        "};\n\nconst decimalPlaces",
    )
    assert "변경값" in render_draft_value_body
    assert "수정값" not in render_draft_value_body
    assert "현재값" in render_draft_value_body
    assert "현재 적용" in render_draft_value_body
    assert "Pending" not in render_draft_value_body
    assert "Applied " not in render_draft_value_body
    assert "초안 " not in render_draft_value_body
    assert "적용값 " not in render_draft_value_body
    assert "Draft " not in render_draft_value_body
    assert "Active " not in render_draft_value_body
    assert "저장 안 된 오디오 변경" in script.text
    assert "저장 안 된 변경 없음" not in script.text
    assert "Pending changes" not in script.text
    assert "No pending changes" not in script.text
    assert "const deriveSettingsActionState = ({" in script.text
    assert "const derivePendingChangeState = (settingsPlan, sourceFilesChanged = false)" in (
        script.text
    )
    render_state_body = slice_between(
        script.text,
        "const renderState = () => {",
        "};\n\nconst renderLastEventBadge",
    )
    assert (
        "const pendingChangeState = derivePendingChangeState(" in render_state_body
    )
    assert "const controlState = deriveDashboardControlState({" in render_state_body
    assert (
        '"captureGateSwitch").disabled = controlState.captureGateSwitchDisabled'
        in render_state_body
    )
    assert (
        "controlState.captureGateOn ? \"true\" : \"false\""
        in render_state_body
    )
    assert (
        '"pendingBadge").hidden = !pendingChangeState.pendingChanges'
        in render_state_body
    )
    assert (
        '"applyButton").classList.toggle("attention", controlState.applyAttention)'
        in render_state_body
    )
    assert (
        '"captureGateState").textContent = snapshot.is_recording'
        in render_state_body
    )
    assert (
        '"startButton").disabled = controlState.startDisabled'
        in render_state_body
    )
    assert (
        '"stopButton").disabled = controlState.stopDisabled'
        in render_state_body
    )
    assert 'controlState.recordingStopBusy\n    ? "처리 중"' in render_state_body
    assert "applyInFlight: false" in script.text
    assert '"applyButton").disabled = controlState.applyDisabled' in render_state_body
    bilingual_apply_label = (
        'setLabelMarkup("applyButton", { ko: "적용 후 재시작", en: "Apply and Restart" })'
    )
    assert bilingual_apply_label not in script.text
    assert 'applyLabel: applyInFlight ? "적용 중…" : "변경사항 적용 후 재생"' in script.text
    assert "적용 중…" in script.text
    assert "적용할 변경사항이 없습니다." in script.text
    assert "녹음 처리가 끝날 때까지 기다리세요." in script.text
    assert "준비된 오디오 설정을 렌더링하고 다시 불러오는 중입니다." in script.text
    assert '"resetButton").disabled = controlState.resetDisabled' in script.text
    assert "저장하지 않은 설정 변경을 취소하기 전에 녹음을 중지하세요." in script.text
    assert "취소할 설정 변경사항이 없습니다." in script.text
    assert "const currentSettingsActionState = (snapshot = state.snapshot) => {" in script.text
    assert "if (currentSettingsActionState().applyDisabled) return" in script.text
    assert "if (currentSettingsActionState().resetDisabled) return" in script.text
    assert (
        '"resetParticipantsButton").disabled = controlState.resetParticipantsDisabled'
        in script.text
    )
    assert "참여자 수를 초기화하기 전에 녹음을 중지하세요." in script.text
    assert "준비된 오디오 설정을 적용하는 동안 출력을 멈췄다가 다시 시작합니다." in script.text
    assert "const canUseServerSettingsChangePlan = (snapshot, draft) => (" in script.text
    assert "snapshot?.settings?.change?.runtime_config_changed" in script.text
    assert "if (canUseServerSettingsChangePlan(snapshot, draft))" in script.text
    assert "const commitDraftChange = (mutator, options = {}) => {" in script.text
    assert "syncDraftSnapshot();" in script.text
    assert "scheduleDraftSave();" in script.text
    voice_stack_body = slice_between(
        script.text,
        "const renderVoiceStackControls = () => {",
        "};\n\nconst renderStorageModeControls",
    )
    assert "commitDraftChange(() => {" in voice_stack_body
    storage_mode_body = slice_between(
        script.text,
        "const setStorageMode = (mode) => {",
        "};\n\nconst renderLayerGroup",
    )
    assert "commitDraftChange(() => {" in storage_mode_body
    recording_controls_body = slice_between(
        script.text,
        "const renderRecordingControls = () => {",
        "};\n\nconst renderRecordingPresets",
    )
    assert "commitDraftChange(" in recording_controls_body
    assert "afterSync: renderRecordingPresets" in recording_controls_body
    render_layer_card_body = slice_between(
        script.text,
        "const renderLayerCard = (layerId) => {",
        "};\n\nconst layerPresetMarkup",
    )
    assert "commitDraftChange(" in render_layer_card_body
    assert "afterSync: () => {" in render_layer_card_body
    apply_layer_preset_body = slice_between(
        script.text,
        "const applyLayerPreset = (layerId, presetName) => {",
        "};\n\nconst resetLayerFilter",
    )
    assert "commitDraftChange(" in apply_layer_preset_body
    assert "afterSync: renderLayerControls" in apply_layer_preset_body
    reset_layer_filter_body = slice_between(
        script.text,
        "const resetLayerFilter = (layerId) => {",
        "};\n\nconst renderRecordingControls",
    )
    assert "commitDraftChange(" in reset_layer_filter_body
    assert "afterSync: renderLayerControls" in reset_layer_filter_body
    apply_recording_preset_body = slice_between(
        script.text,
        "const applyRecordingPreset = (name) => {",
        "};\n\nconst workspaceTabs",
    )
    assert "commitDraftChange(" in apply_recording_preset_body
    assert "renderRecordingPresets();" in apply_recording_preset_body
    assert "renderRecordingControls();" in apply_recording_preset_body
    assert "await requestState({ syncDraft: false }).catch(() => {})" in script.text
    refresh_all_body = slice_between(
        script.text,
        "const refreshAll = async () => {",
        "};\n\nconst applyState",
    )
    assert "await requestState({ syncDraft: false }).catch(" in refresh_all_body
    apply_body = slice_between(
        script.text,
        "const applyAndRestart = async () => {",
        "};\n\nconst resetDraft",
    )
    assert "if (currentSettingsActionState().applyDisabled) return" in apply_body
    assert "state.applyInFlight = true" in apply_body
    assert "state.applyInFlight = false" in apply_body
    assert "renderDevices();" in apply_body
    assert "let applyError = null" in apply_body
    assert "applyError = error" in apply_body
    assert "showError(applyError.message)" in apply_body
    assert '"/api/settings/apply"' in apply_body
    assert '"/api/settings/apply-and-restart"' not in apply_body
    assert "const resetDraft = async () => {" in script.text
    reset_draft_body = slice_between(
        script.text,
        "const resetDraft = async () => {",
        "};\n\nconst resetParticipants",
    )
    assert '"/api/settings/reset-draft"' in reset_draft_body
    assert '"/api/settings/reset"' not in reset_draft_body
    assert "if (currentSettingsActionState().resetDisabled) return" in reset_draft_body
    assert "await requestState({ syncDraft: false }).catch(() => {})" in reset_draft_body
    assert "const resetParticipants = async () => {" in script.text
    assert 'const payload = await api("/api/participants/reset"' in script.text
    reset_participants_body = slice_between(
        script.text,
        "const resetParticipants = async () => {",
        "};\n\nconst changeDevice",
    )
    assert "applyState(payload.state, { syncDraft: false })" in reset_participants_body
    assert "await requestState({ syncDraft: false }).catch(() => {})" in reset_participants_body
    assert "showError(error.message)" in script.text
    assert "const changeDevice = async (key, value) => {" in script.text
    change_device_body = slice_between(
        script.text,
        "const changeDevice = async (key, value) => {",
        "};\n\nconst shouldIgnoreSpace",
    )
    assert "if (state.deviceChangeInFlight || state.applyInFlight) return" in change_device_body
    assert '"/api/devices"' in change_device_body
    assert "state.devices = payload.devices" in change_device_body
    assert "await requestDevices().catch(() => {})" in change_device_body
    assert "await requestState({ syncDraft: false }).catch(() => {})" in change_device_body
    derive_control_body = slice_between(
        script.text,
        "const deriveControlRequestState = (path, options = {}, currentState = state) => {",
        "};\n\nconst control",
    )
    assert "const pollAutoStopRequest =" in derive_control_body
    assert 'path === "/api/recording/poll-auto-stop"' in derive_control_body
    assert (
        "Number(state.snapshot?.recording_remaining_seconds || 0) <= 0"
        not in derive_control_body
    )
    assert "pollAutoStopRequest" in slice_between(
        derive_control_body,
        "const startsStopRequest =",
        ";\n  const skip =",
    )
    control_body = slice_between(
        script.text,
        "const control = async (path, options = {}) => {",
        "};\n\nconst applyAndRestart",
    )
    assert "let controlError = null" in control_body
    assert "controlError = error" in control_body
    assert "const controlRequest = deriveControlRequestState(path, options)" in control_body
    assert "if (controlRequest.skip) return" in control_body
    assert "state.recordingStopInFlight = true;\n    renderState();" in control_body
    assert "state.recordingStopInFlight = false;\n      renderState();" in control_body
    assert "if (controlError) showError(controlError.message);" in control_body
    assert control_body.index("state.recordingStopInFlight = true") < control_body.index(
        "setRecordStatus(\"processing\", \"녹음 처리 중...\")",
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
    assert 'setRecordStatus("failed", "녹음 실패", translateUiErrorMessage(error.message))' in (
        recording_error_branch
    )
    assert "await requestState({ syncDraft: false }).catch(() => {})" in recording_error_branch
    assert "await requestDiagnostics().catch(() => {})" in recording_error_branch
    recording_branch_start = control_body.index(
        'if (path.startsWith("/api/recording/") || path === "/api/input/disarm") {',
    )
    recording_failed_status = control_body.index(
        'setRecordStatus("failed", "녹음 실패", translateUiErrorMessage(error.message))',
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
    assert "state.recordingStartInFlight" in start_from_space_body
    assert "state.recordingStopInFlight" in start_from_space_body
    assert "!state.snapshot?.armed" in start_from_space_body
    assert "state.snapshot?.is_recording" in start_from_space_body
    assert 'if (event.code !== "Space" || shouldIgnoreSpace()) return;' in start_from_space_body
    assert "if (event.repeat) return;" in start_from_space_body


def test_static_ui_filter_status_uses_latest_draft_after_saved_draft_refresh(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for static app behavior smoke test")

    script = static_app_test_script(
        tmp_path,
        "{ controlGroup, layerControlGroups, setPath, clone }",
    )
    harness = f"""
const assert = require("assert");
const vm = require("vm");
let lastActionsMarkup = "";

const makeElement = () => {{
  const element = {{
    children: [],
    innerHTML: "",
    value: "",
    textContent: "",
    className: "",
    parentElement: null,
    attributes: {{}},
    listeners: {{}},
    _queryElements: {{}},
    style: {{ setProperty() {{}} }},
    classList: {{
      toggle() {{}},
      contains() {{ return false; }},
    }},
    setAttribute(name, value) {{
      this.attributes[name] = value;
    }},
    appendChild(child) {{
      child.parentElement = this;
      this.children.push(child);
      return child;
    }},
    addEventListener(eventName, handler) {{
      this.listeners[eventName] = handler;
    }},
    dispatchEvent(event) {{
      this.listeners[event.type]?.(event);
    }},
    querySelector(selector) {{
      if (!this._queryElements[selector]) {{
        this._queryElements[selector] = makeElement();
      }}
      return this._queryElements[selector];
    }},
    replaceWith(nextElement) {{
      lastActionsMarkup = nextElement.innerHTML;
    }},
  }};
  return element;
}};

const makeTemplate = () => {{
  const template = {{ content: {{ firstElementChild: null }} }};
  Object.defineProperty(template, "innerHTML", {{
    set(value) {{
      const element = makeElement();
      element.innerHTML = value;
      template.content.firstElementChild = element;
    }},
  }});
  return template;
}};

globalThis.document = {{
  getElementById() {{ return makeElement(); }},
  querySelector() {{ return makeElement(); }},
  querySelectorAll() {{ return []; }},
  createElement(tagName) {{
    return tagName === "template" ? makeTemplate() : makeElement();
  }},
  addEventListener() {{}},
}};
globalThis.window = {{
  addEventListener() {{}},
  location: {{ protocol: "http:", host: "127.0.0.1:8000", search: "" }},
}};
globalThis.requestAnimationFrame = () => {{}};
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {{}};
globalThis.setInterval = () => 0;

vm.runInThisContext({json.dumps(script)}, {{ filename: "app.js" }});

const activeLayer = {{
  eq: {{ highpass_hz: 20, lowpass_hz: 20000 }},
}};
const current = {{
  draft: {{ eq: {{ highpass_hz: 20, lowpass_hz: 20000 }} }},
}};
const filterGroup = globalThis.__secretPondTest.layerControlGroups.find(
  (group) => group.action === "reset-filter",
);
const section = globalThis.__secretPondTest.controlGroup(
  filterGroup,
  current.draft,
  activeLayer,
  (control, value) => {{
    globalThis.__secretPondTest.setPath(current.draft, control.path, value);
  }},
);
const body = section.querySelector(".control-group-body");
const lowCutRow = body.children[0];
const lowCutInput = lowCutRow.querySelector("input");

lowCutInput.value = "80";
lowCutInput.dispatchEvent({{ type: "input" }});
assert.match(lastActionsMarkup, /filter-status pending/);

current.draft = globalThis.__secretPondTest.clone(current.draft);
lowCutInput.value = "20";
lowCutInput.dispatchEvent({{ type: "input" }});
assert.doesNotMatch(lastActionsMarkup, /filter-status pending/);
assert.match(lastActionsMarkup, /filter-status bypassed/);
assert.match(lastActionsMarkup, /필터 없음/);
"""
    subprocess.run([node, "-e", harness], check=True, text=True)


def test_static_ui_presets_are_stateful_and_reversible(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports=(
            "{ clone, layerPresetDefs, recordingPresetDefs, reversiblePresetDraft, "
            "presetSelectionMatches }"
        ),
        body="""
const helpers = globalThis.__secretPondTest;
const customLayer = {{
  enabled: true,
  volume_db: -9,
  eq: {{
    low_gain_db: 0,
    mid_gain_db: 0,
    high_gain_db: 0,
    highpass_hz: 55,
    lowpass_hz: 18000,
  }},
}};
const selectedLayer = helpers.reversiblePresetDraft(
  customLayer,
  helpers.layerPresetDefs,
  "Warm Bed",
  null,
);
assert.deepStrictEqual(selectedLayer.draft.eq, helpers.layerPresetDefs["Warm Bed"].eq);
assert.strictEqual(selectedLayer.selection.name, "Warm Bed");
assert.deepStrictEqual(selectedLayer.selection.previousDraft, customLayer);
assert.strictEqual(
  helpers.presetSelectionMatches(
    selectedLayer.draft,
    helpers.layerPresetDefs,
    selectedLayer.selection,
  ),
  true,
);

const editedLayer = helpers.clone(selectedLayer.draft);
editedLayer.eq.highpass_hz = 70;
assert.strictEqual(
  helpers.presetSelectionMatches(editedLayer, helpers.layerPresetDefs, selectedLayer.selection),
  false,
);

const revertedLayer = helpers.reversiblePresetDraft(
  selectedLayer.draft,
  helpers.layerPresetDefs,
  "Warm Bed",
  selectedLayer.selection,
);
assert.deepStrictEqual(revertedLayer.draft, customLayer);
assert.strictEqual(revertedLayer.selection, null);

const customRecording = {{
  gain_db: -8,
  normalize_peak: 0.2,
  highpass_hz: 70,
  lowpass_hz: 11000,
  presence_gain_db: -1,
  reverb_mix: 0.05,
  delay_mix: 0.02,
  fade_ms: 25,
}};
const selectedRecording = helpers.reversiblePresetDraft(
  customRecording,
  helpers.recordingPresetDefs,
  "Clearer Voice",
  null,
);
assert.deepStrictEqual(selectedRecording.draft, {{
  ...customRecording,
  ...helpers.recordingPresetDefs["Clearer Voice"],
}});
assert.strictEqual(selectedRecording.selection.name, "Clearer Voice");

const editedRecording = helpers.clone(selectedRecording.draft);
editedRecording.presence_gain_db = 2;
assert.strictEqual(
  helpers.presetSelectionMatches(
    editedRecording,
    helpers.recordingPresetDefs,
    selectedRecording.selection,
  ),
  false,
);

const revertedRecording = helpers.reversiblePresetDraft(
  selectedRecording.draft,
  helpers.recordingPresetDefs,
  "Clearer Voice",
  selectedRecording.selection,
);
assert.deepStrictEqual(revertedRecording.draft, customRecording);
assert.strictEqual(revertedRecording.selection, null);
""",
    )


def test_static_ui_dashboard_control_state_derives_buttons_without_dom(
    tmp_path: Path,
) -> None:
    run_static_app_harness(
        tmp_path,
        exports=(
            "{ deriveDashboardControlState, deriveSettingsActionState, derivePendingChangeState, "
            "deriveControlRequestState, deriveOperationLocks, deriveSystemDeviceSelectState, "
            "deriveStorageModeControlState }"
        ),
        body="""
const snapshot = {{
  armed: true,
  is_recording: false,
  playback: {{ output_running: false }},
}};
const derive = globalThis.__secretPondTest.deriveDashboardControlState;
const deriveSettingsActions = globalThis.__secretPondTest.deriveSettingsActionState;
const derivePending = globalThis.__secretPondTest.derivePendingChangeState;
const deriveControl = globalThis.__secretPondTest.deriveControlRequestState;
const deriveLocks = globalThis.__secretPondTest.deriveOperationLocks;
const deriveDeviceSelect = globalThis.__secretPondTest.deriveSystemDeviceSelectState;
const deriveStorageMode = globalThis.__secretPondTest.deriveStorageModeControlState;
const settings = {{
  active: {{ voice_stack: {{ mode: "live_ephemeral" }} }},
}};
const draft = {{ voice_stack: {{ mode: "live_ephemeral" }} }};

assert.deepStrictEqual(
  deriveLocks({{
    applyInFlight: true,
    resetDraftInFlight: true,
    sourceMutationInFlight: true,
    deviceChangeInFlight: true,
    devicesLoaded: true,
    forceDeviceDisabled: true,
  }}),
  {{
    draftLocked: true,
    sourceUiLocked: true,
    sourceCommandBlocked: true,
    sourceActionTitle: "설정 적용이 끝날 때까지 소스 파일을 바꿀 수 없습니다.",
    deviceLocked: true,
    deviceTitle: "설정 적용이 끝날 때까지 기다리세요.",
  }},
);

assert.deepStrictEqual(
  deriveLocks({{ devicesLoaded: false }}),
  {{
    draftLocked: false,
    sourceUiLocked: false,
    sourceCommandBlocked: false,
    sourceActionTitle: "",
    deviceLocked: true,
    deviceTitle: "장치 목록을 불러오는 중입니다.",
  }},
);

assert.deepStrictEqual(
  deriveDeviceSelect({{ devicesLoaded: false }}),
  {{
    disabled: true,
    title: "장치 목록을 불러오는 중입니다.",
  }},
);

assert.deepStrictEqual(
  deriveDeviceSelect({{ devicesLoaded: true, applyInFlight: true }}),
  {{
    disabled: true,
    title: "설정 적용이 끝날 때까지 기다리세요.",
  }},
);

assert.deepStrictEqual(
  deriveDeviceSelect({{ devicesLoaded: true, deviceChangeInFlight: true }}),
  {{
    disabled: true,
    title: "장치 변경을 적용하는 중입니다.",
  }},
);

assert.deepStrictEqual(
  deriveDeviceSelect({{ devicesLoaded: true, forceDisabled: true }}),
  {{
    disabled: true,
    title: "녹음 중에는 입력 장치를 바꿀 수 없습니다.",
  }},
);

assert.deepStrictEqual(
  deriveDeviceSelect({{ devicesLoaded: true }}),
  {{
    disabled: false,
    title: "",
  }},
);

assert.deepStrictEqual(
  deriveStorageMode({{ snapshot: {{ settings }}, draft, mode: "live_ephemeral" }}),
  {{
    active: true,
    ariaPressed: "true",
    pendingActive: false,
    disabled: false,
    title: "개별 accepted clip 파일을 남기지 않습니다.",
    canCommit: true,
  }},
);

const pendingDraft = {{ voice_stack: {{ mode: "test_library" }} }};
assert.deepStrictEqual(
  deriveStorageMode({{ snapshot: {{ settings }}, draft: pendingDraft, mode: "test_library" }}),
  {{
    active: true,
    ariaPressed: "true",
    pendingActive: true,
    disabled: false,
    title: "accepted clip을 data/processed/accepted에 저장합니다.",
    canCommit: true,
  }},
);

assert.deepStrictEqual(
  deriveStorageMode({{
    snapshot: {{ settings }},
    draft,
    mode: "live_ephemeral",
    applyInFlight: true,
  }}),
  {{
    active: true,
    ariaPressed: "true",
    pendingActive: false,
    disabled: true,
    title: "녹음 중이거나 적용 중일 때는 보관 모드를 바꿀 수 없습니다.",
    canCommit: false,
  }},
);

assert.deepStrictEqual(
  deriveStorageMode({{
    snapshot: {{ settings }},
    draft,
    mode: "live_ephemeral",
    resetDraftInFlight: true,
  }}),
  {{
    active: true,
    ariaPressed: "true",
    pendingActive: false,
    disabled: true,
    title: "설정 작업이 끝날 때까지 보관 모드를 바꿀 수 없습니다.",
    canCommit: false,
  }},
);

assert.strictEqual(
  deriveStorageMode({{
    snapshot: {{ settings, is_recording: true }},
    draft,
    mode: "live_ephemeral",
  }}).canCommit,
  false,
);
assert.strictEqual(
  deriveStorageMode({{ snapshot: {{ settings }}, draft, mode: "unknown" }}).canCommit,
  false,
);

assert.deepStrictEqual(
  deriveControl("/api/recording/start", {{}}, {{
    snapshot: {{ armed: true, is_recording: false }},
    recordingStartInFlight: false,
    recordingStopInFlight: false,
  }}),
  {{
    startsStartRequest: true,
    allowStaleRecordingStop: false,
    expectsRecordingOutcome: false,
    pollAutoStopRequest: false,
    startsStopRequest: false,
    skip: false,
  }},
);

assert.strictEqual(
  deriveControl("/api/recording/start", {{}}, {{
    snapshot: {{ armed: true, is_recording: false }},
    recordingStartInFlight: true,
    recordingStopInFlight: false,
  }}).skip,
  true,
);

assert.deepStrictEqual(
  deriveControl("/api/recording/stop", {{ allowStaleRecordingStop: true }}, {{
    snapshot: {{ armed: true, is_recording: false }},
    recordingStartInFlight: true,
    recordingStopInFlight: false,
  }}),
  {{
    startsStartRequest: false,
    allowStaleRecordingStop: true,
    expectsRecordingOutcome: true,
    pollAutoStopRequest: false,
    startsStopRequest: true,
    skip: false,
  }},
);

assert.deepStrictEqual(
  deriveControl("/api/recording/poll-auto-stop", {{}}, {{
    snapshot: {{ armed: true, is_recording: true }},
    recordingStartInFlight: false,
    recordingStopInFlight: true,
  }}),
  {{
    startsStartRequest: false,
    allowStaleRecordingStop: false,
    expectsRecordingOutcome: true,
    pollAutoStopRequest: true,
    startsStopRequest: true,
    skip: true,
  }},
);

assert.deepStrictEqual(
  derivePending({{
    runtimeConfigChanged: false,
    changedRuntimeFields: [],
    changedSections: [],
    runtimeConfigFields: ["audio.sample_rate"],
  }}, false),
  {{
    settingsChanged: false,
    sourceFilesChanged: false,
    pendingChanges: false,
    runtimeConfigChanged: false,
  }},
);

assert.deepStrictEqual(
  derivePending({{
    runtimeConfigChanged: false,
    changedRuntimeFields: [],
    changedSections: ["layers"],
    runtimeConfigFields: ["audio.sample_rate"],
  }}, false),
  {{
    settingsChanged: true,
    sourceFilesChanged: false,
    pendingChanges: true,
    runtimeConfigChanged: false,
  }},
);

assert.deepStrictEqual(
  derivePending({{
    runtimeConfigChanged: true,
    changedRuntimeFields: ["audio.sample_rate"],
    changedSections: ["audio"],
    runtimeConfigFields: ["audio.sample_rate"],
  }}, true),
  {{
    settingsChanged: true,
    sourceFilesChanged: true,
    pendingChanges: true,
    runtimeConfigChanged: true,
  }},
);

assert.deepStrictEqual(
  derive({{
    snapshot,
    applyInFlight: false,
    recordingStopInFlight: false,
    pendingChanges: true,
    runtimeConfigChanged: false,
  }}),
  {{
    recordingStopBusy: false,
    outputControlBusy: false,
    captureReady: true,
    captureGateOn: true,
    captureGateClass: "capture-gate-on",
    captureGateSwitchDisabled: false,
    startDisabled: false,
    stopDisabled: true,
    startOutputDisabled: false,
    stopOutputDisabled: true,
    restartOutputDisabled: true,
    applyDisabled: false,
    applyLabel: "변경사항 적용 후 재생",
    applyAttention: true,
    applyTitle: "",
    resetDisabled: false,
    resetTitle: "",
    resetParticipantsDisabled: false,
    resetParticipantsTitle: "",
  }},
);

const noPendingChanges = derive({{
  snapshot,
  applyInFlight: false,
  recordingStopInFlight: false,
  pendingChanges: false,
  runtimeConfigChanged: false,
}});
assert.strictEqual(noPendingChanges.applyDisabled, true);
assert.strictEqual(noPendingChanges.applyAttention, false);
assert.strictEqual(noPendingChanges.applyTitle, "적용할 변경사항이 없습니다.");
assert.strictEqual(noPendingChanges.resetDisabled, true);
assert.strictEqual(noPendingChanges.resetTitle, "취소할 설정 변경사항이 없습니다.");

assert.deepStrictEqual(
  deriveSettingsActions({{
    snapshot,
    applyInFlight: false,
    resetDraftInFlight: false,
    recordingStopInFlight: false,
    pendingChanges: true,
    runtimeConfigChanged: false,
  }}),
  {{
    applyDisabled: false,
    applyLabel: "변경사항 적용 후 재생",
    applyAttention: true,
    applyTitle: "",
    resetDisabled: false,
    resetTitle: "",
  }},
);

assert.deepStrictEqual(
  deriveSettingsActions({{
    snapshot,
    applyInFlight: false,
    resetDraftInFlight: true,
    recordingStopInFlight: false,
    pendingChanges: true,
    runtimeConfigChanged: false,
  }}),
  {{
    applyDisabled: true,
    applyLabel: "변경사항 적용 후 재생",
    applyAttention: true,
    applyTitle: "설정 변경 취소가 끝날 때까지 기다리세요.",
    resetDisabled: true,
    resetTitle: "설정 변경 취소가 끝날 때까지 기다리세요.",
  }},
);

const runtimeChange = derive({{
  snapshot,
  applyInFlight: false,
  recordingStopInFlight: false,
  pendingChanges: true,
  runtimeConfigChanged: true,
}});
assert.strictEqual(runtimeChange.applyDisabled, true);
assert.strictEqual(runtimeChange.applyAttention, false);
assert.strictEqual(
  runtimeChange.applyTitle,
  "샘플레이트, 채널 변경은 앱 재시작이 필요하고 장치 변경은 System 패널에서 적용해야 합니다.",
);

const recordingStopBusy = derive({{
  snapshot,
  applyInFlight: false,
  recordingStopInFlight: true,
  pendingChanges: true,
  runtimeConfigChanged: false,
}});
assert.strictEqual(recordingStopBusy.captureReady, false);
assert.strictEqual(recordingStopBusy.captureGateClass, "capture-gate-processing");
assert.strictEqual(recordingStopBusy.captureGateSwitchDisabled, true);
assert.strictEqual(recordingStopBusy.startDisabled, true);
assert.strictEqual(recordingStopBusy.applyDisabled, true);
assert.strictEqual(recordingStopBusy.applyTitle, "녹음 처리가 끝날 때까지 기다리세요.");
assert.strictEqual(recordingStopBusy.startOutputDisabled, true);

const activeRecording = derive({{
  snapshot: {{ ...snapshot, is_recording: true, playback: {{ output_running: true }} }},
  applyInFlight: false,
  recordingStopInFlight: false,
  pendingChanges: true,
  runtimeConfigChanged: false,
}});
assert.strictEqual(activeRecording.captureGateClass, "capture-gate-recording");
assert.strictEqual(activeRecording.stopDisabled, false);
assert.strictEqual(activeRecording.applyDisabled, true);
assert.strictEqual(activeRecording.resetDisabled, true);
assert.strictEqual(
  activeRecording.resetTitle,
  "저장하지 않은 설정 변경을 취소하기 전에 녹음을 중지하세요.",
);

const applyInFlight = derive({{
  snapshot: {{ ...snapshot, playback: {{ output_running: true }} }},
  applyInFlight: true,
  recordingStopInFlight: false,
  pendingChanges: true,
  runtimeConfigChanged: false,
}});
assert.strictEqual(applyInFlight.outputControlBusy, true);
assert.strictEqual(applyInFlight.applyDisabled, true);
assert.strictEqual(applyInFlight.applyLabel, "적용 중…");
assert.strictEqual(
  applyInFlight.applyTitle,
  "준비된 오디오 설정을 렌더링하고 다시 불러오는 중입니다.",
);
assert.strictEqual(applyInFlight.resetDisabled, true);

const outputRunning = derive({{
  snapshot: {{ ...snapshot, playback: {{ output_running: true }} }},
  applyInFlight: false,
  recordingStopInFlight: false,
  pendingChanges: true,
  runtimeConfigChanged: false,
}});
assert.strictEqual(outputRunning.startOutputDisabled, true);
assert.strictEqual(outputRunning.stopOutputDisabled, false);
assert.strictEqual(outputRunning.restartOutputDisabled, false);
assert.strictEqual(
  outputRunning.applyTitle,
  "준비된 오디오 설정을 적용하는 동안 출력을 멈췄다가 다시 시작합니다.",
);
""",
    )


def test_static_ui_settings_change_plan_uses_server_runtime_field_policy(
    tmp_path: Path,
) -> None:
    run_static_app_harness(
        tmp_path,
        exports=(
            "{ state, settingsChangePlan, canUseServerSettingsChangePlan, "
            "mergeSettingsPayloadDraft, localSettingsChangePlan, normalizeSettingsChangePlan, "
            "toServerSettingsChangePayload }"
        ),
        body="""
const helpers = globalThis.__secretPondTest;
const active = {{
  audio: {{ sample_rate: 48000, channels: 2 }},
  devices: {{ input_device_id: null, output_device_id: null }},
  sources: {{ low_path: "low-active.wav", mid_path: null }},
  layers: {{ voice: {{ volume_db: -18 }} }},
}};
const draft = JSON.parse(JSON.stringify(active));
draft.devices.input_device_id = "mic-2";

const plan = helpers.localSettingsChangePlan(active, draft, ["audio.sample_rate"]);
assert.deepStrictEqual(plan, {{
  runtimeConfigChanged: false,
  changedRuntimeFields: [],
  changedSections: ["devices"],
  runtimeConfigFields: ["audio.sample_rate"],
}});

const normalized = helpers.normalizeSettingsChangePlan({{
  runtime_config_changed: false,
  changed_runtime_fields: [],
  changed_sections: ["devices"],
  runtime_config_fields: ["audio.sample_rate"],
}});
assert.deepStrictEqual(normalized.runtimeConfigFields, ["audio.sample_rate"]);

assert.deepStrictEqual(helpers.toServerSettingsChangePayload(normalized), {{
  runtime_config_changed: false,
  changed_runtime_fields: [],
  changed_sections: ["devices"],
  runtime_config_fields: ["audio.sample_rate"],
}});

const serverDraft = JSON.parse(JSON.stringify(active));
const localDraft = JSON.parse(JSON.stringify(active));
localDraft.devices.input_device_id = "mic-3";
const staleSnapshot = {{
  settings: {{
    active,
    draft: serverDraft,
    change: {{
      runtime_config_changed: false,
      changed_runtime_fields: [],
      changed_sections: [],
      runtime_config_fields: ["audio.sample_rate"],
    }},
  }},
}};
helpers.state.draft = localDraft;
assert.strictEqual(
  helpers.canUseServerSettingsChangePlan(staleSnapshot, localDraft),
  false,
);
assert.deepStrictEqual(helpers.settingsChangePlan(staleSnapshot), {{
  runtimeConfigChanged: false,
  changedRuntimeFields: [],
  changedSections: ["devices"],
  runtimeConfigFields: ["audio.sample_rate"],
}});
assert.strictEqual(
  helpers.canUseServerSettingsChangePlan(staleSnapshot, serverDraft),
  true,
);

const reorderedActive = {{
  audio: {{ channels: 2, sample_rate: 48000 }},
  layers: {{ voice: {{ volume_db: -18, enabled: true }} }},
}};
const reorderedDraft = {{
  audio: {{ sample_rate: 48000, channels: 2 }},
  layers: {{ voice: {{ enabled: true, volume_db: -18 }} }},
}};
const reorderedSnapshot = {{
  settings: {{
    active: reorderedActive,
    draft: reorderedActive,
    change: {{
      runtime_config_changed: false,
      changed_runtime_fields: [],
      changed_sections: [],
      runtime_config_fields: ["audio.sample_rate", "audio.channels"],
    }},
  }},
}};
assert.strictEqual(
  helpers.canUseServerSettingsChangePlan(reorderedSnapshot, reorderedDraft),
  true,
);
assert.deepStrictEqual(
  helpers.localSettingsChangePlan(
    reorderedActive,
    reorderedDraft,
    ["audio.sample_rate", "audio.channels"],
  ).changedSections,
  [],
);

const incomingDraft = JSON.parse(JSON.stringify(active));
incomingDraft.sources.low_path = "low-server.wav";
incomingDraft.layers.voice.volume_db = -24;
const unsavedDraft = JSON.parse(JSON.stringify(active));
unsavedDraft.sources.low_path = "low-local.wav";
unsavedDraft.layers.voice.volume_db = -12;

const mergedDraft = helpers.mergeSettingsPayloadDraft(unsavedDraft, {{
  draft: incomingDraft,
}}, {{
  syncDraft: false,
  mergeDraftSections: ["sources"],
}});
assert.notStrictEqual(mergedDraft, unsavedDraft);
assert.notStrictEqual(mergedDraft.sources, unsavedDraft.sources);
assert.strictEqual(mergedDraft.sources.low_path, "low-server.wav");
assert.strictEqual(mergedDraft.layers.voice.volume_db, -12);
assert.strictEqual(unsavedDraft.sources.low_path, "low-local.wav");

const syncedDraft = helpers.mergeSettingsPayloadDraft(unsavedDraft, {{
  draft: incomingDraft,
}});
assert.strictEqual(syncedDraft.sources.low_path, "low-server.wav");
assert.strictEqual(syncedDraft.layers.voice.volume_db, -24);
""",
    )


def test_static_ui_ignores_stale_diagnostics_refresh_response(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ state, requestDiagnostics }",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
  const helpers = globalThis.__secretPondTest;
  const diagnosticsResponses = [];
  globalThis.fetch = (path) => {
    if (path !== "/api/diagnostics") {
      throw new Error(`unexpected fetch ${path}`);
    }
    return new Promise((resolve) => {
      diagnosticsResponses.push(resolve);
    });
  };

  const olderRefresh = helpers.requestDiagnostics();
  const newerRefresh = helpers.requestDiagnostics();
  assert.strictEqual(diagnosticsResponses.length, 2);

  diagnosticsResponses[1]({
    ok: true,
    json: async () => ({
      sources: [],
      events: {
        recent: [{ timestamp: "2026-06-05T01:32:00Z", event_type: "recording.accepted" }],
        error: null,
      },
    }),
  });
  await newerRefresh;
  assert.strictEqual(helpers.state.diagnostics.events.recent[0].event_type, "recording.accepted");
  assert.strictEqual(elements.lastEventBadge.textContent, "최근 녹음 추가");
  assert.strictEqual(elements.lastEventBadge.className, "status-pill");

  diagnosticsResponses[0]({
    ok: true,
    json: async () => ({
      sources: [],
      events: {
        recent: [{ timestamp: "2026-06-05T01:31:00Z", event_type: "playback.started" }],
        error: "event log unavailable",
      },
    }),
  });
  await olderRefresh;

  assert.strictEqual(helpers.state.diagnostics.events.recent[0].event_type, "recording.accepted");
  assert.strictEqual(helpers.state.diagnostics.events.error, null);
  assert.strictEqual(helpers.state.diagnosticsError, null);
  assert.strictEqual(elements.lastEventBadge.textContent, "최근 녹음 추가");
  assert.strictEqual(elements.lastEventBadge.className, "status-pill");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_static_ui_ignores_stale_state_refresh_response(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ state, applyState, requestState }",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
  const helpers = globalThis.__secretPondTest;
  const layerSettings = (volumeDb) => ({
    enabled: true,
    volume_db: volumeDb,
    eq: {
      low_gain_db: 0,
      mid_gain_db: 0,
      high_gain_db: 0,
      highpass_hz: 20,
      lowpass_hz: 20000,
    },
  });
  const settings = {
    voice_stack: { mode: "live_ephemeral", loop_seconds: 60 },
    input_control: {
      minimum_recording_seconds: 3,
      maximum_recording_seconds: 120,
    },
    recording: {
      gain_db: 0,
      normalize_peak: 0.35,
      highpass_hz: 90,
      lowpass_hz: 8000,
      presence_gain_db: -3,
      reverb_mix: 0.25,
      delay_mix: 0,
      fade_ms: 50,
    },
    audio: { sample_rate: 48000, channels: 2 },
    devices: { input_device_id: null, output_device_id: null },
    sources: {
      low_path: null,
      mid_path: null,
      voice_raw_path: null,
      voice_stack_path: null,
    },
    layers: {
      low: layerSettings(-12),
      mid: layerSettings(-12),
      voice: layerSettings(-18),
    },
  };
  const snapshot = (participantCount) => ({
    armed: true,
    is_recording: false,
    recording_elapsed_seconds: 0,
    recording_remaining_seconds: 120,
    participant_count: participantCount,
    last_error: null,
    playback: {
      output_running: false,
      output_latest_error: null,
      output_latest_status: null,
      layers: {},
    },
    settings: {
      active: settings,
      draft: settings,
      change: {
        runtime_config_changed: false,
        changed_runtime_fields: [],
        changed_sections: [],
        runtime_config_fields: ["audio.sample_rate", "audio.channels"],
      },
    },
  });
  helpers.state.draft = settings;
  const stateResponses = [];
  globalThis.fetch = (path) => {
    if (path !== "/api/state") {
      throw new Error(`unexpected fetch ${path}`);
    }
    return new Promise((resolve) => {
      stateResponses.push(resolve);
    });
  };

  const olderRefresh = helpers.requestState({ syncDraft: false });
  const newerRefresh = helpers.requestState({ syncDraft: false });
  assert.strictEqual(stateResponses.length, 2);

  stateResponses[1]({
    ok: true,
    json: async () => snapshot(2),
  });
  await newerRefresh;
  assert.strictEqual(helpers.state.snapshot.participant_count, 2);
  assert.strictEqual(elements.participantCount.textContent, 2);

  stateResponses[0]({
    ok: true,
    json: async () => snapshot(1),
  });
  await olderRefresh;

  assert.strictEqual(helpers.state.snapshot.participant_count, 2);
  assert.strictEqual(elements.participantCount.textContent, 2);

  const staleAfterPushedState = helpers.requestState({ syncDraft: false });
  assert.strictEqual(stateResponses.length, 3);
  helpers.applyState(snapshot(3), { syncDraft: false });
  assert.strictEqual(helpers.state.snapshot.participant_count, 3);

  stateResponses[2]({
    ok: true,
    json: async () => snapshot(2),
  });
  await staleAfterPushedState;

  assert.strictEqual(helpers.state.snapshot.participant_count, 3);
  assert.strictEqual(elements.participantCount.textContent, 3);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_static_ui_source_signature_uses_explicit_categories(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ sourceSignatureForSettings }",
        body="""
const settings = {{
  sources: {{
    low_path: "sources/low/selected.wav",
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  }},
}};
const categories = [
  {{
    id: "low",
    legacy_path: "sources/low/legacy.wav",
    legacy_size_bytes: 1,
    legacy_modified_at: "legacy-low",
    files: [
      {{
        path: "sources/low/selected.wav",
        size_bytes: 10,
        modified_at: "selected-low",
      }},
    ],
  }},
  {{
    id: "mid",
    legacy_path: "sources/mid/current.wav",
    legacy_size_bytes: 20,
    legacy_modified_at: "legacy-mid",
    files: [],
  }},
];

assert.strictEqual(
  globalThis.__secretPondTest.sourceSignatureForSettings(settings, categories),
  "low:sources/low/selected.wav:10:selected-low|mid:sources/mid/current.wav:20:legacy-mid",
);
assert.strictEqual(
  globalThis.__secretPondTest.sourceSignatureForSettings(settings, null),
  null,
);
""",
    )


def test_static_ui_source_file_action_states_are_derived(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ deriveSourceUploadActionState, deriveSourceFileActionState }",
        body="""
const helpers = globalThis.__secretPondTest;

assert.deepStrictEqual(
  helpers.deriveSourceUploadActionState({{ selectAfterUpload: true, file: null }}),
  {{
    selectAfterUpload: true,
    hasFile: false,
    hint: "WAV 파일을 이 폴더로 복사합니다.",
    uploadDisabled: true,
    uploadTitle: "추가할 WAV 파일을 먼저 선택하세요.",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceUploadActionState({{
    selectAfterUpload: false,
    file: {{ name: "picked-low.wav", size: 4096, lastModified: 1 }},
  }}, true),
  {{
    selectAfterUpload: false,
    hasFile: true,
    hint: "picked-low.wav · 4.0 KB 선택됨",
    uploadDisabled: true,
    uploadTitle: "소스 파일 작업이 끝날 때까지 기다리세요.",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceUploadActionState({{
    selectAfterUpload: false,
    file: {{ name: "picked-low.wav", size: 4096, lastModified: 1 }},
  }}, false, true),
  {{
    selectAfterUpload: false,
    hasFile: true,
    hint: "picked-low.wav · 4.0 KB 선택됨",
    uploadDisabled: true,
    uploadTitle: "설정 적용이 끝날 때까지 소스 파일을 바꿀 수 없습니다.",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceFileActionState({{ active: true }}),
  {{
    active: true,
    deleteDisabled: true,
    deleteTitle: "현재 선택된 파일은 삭제할 수 없습니다",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceFileActionState({{ active: false, applied: true }}),
  {{
    active: false,
    deleteDisabled: true,
    deleteTitle: "현재 적용된 파일은 삭제할 수 없습니다",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceFileActionState({{ active: false }}, true),
  {{
    active: false,
    deleteDisabled: true,
    deleteTitle: "소스 파일 작업이 끝날 때까지 기다리세요.",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceFileActionState({{ active: false }}, false, true),
  {{
    active: false,
    deleteDisabled: true,
    deleteTitle: "설정 적용이 끝날 때까지 소스 파일을 바꿀 수 없습니다.",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceFileActionState({{ active: false }}),
  {{
    active: false,
    deleteDisabled: false,
    deleteTitle: "",
  }},
);
""",
    )


def test_static_ui_source_library_status_ignores_optional_categories(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ deriveSourceLibraryStatusState }",
        body="""
const helpers = globalThis.__secretPondTest;

assert.deepStrictEqual(
  helpers.deriveSourceLibraryStatusState([
    {{ id: "low", required: true, active_exists: true }},
    {{ id: "mid", required: true, active_exists: true }},
    {{ id: "voice_raw", required: false, active_exists: false }},
    {{ id: "voice_stack", required: true, active_exists: true }},
  ]),
  {{
    missingCount: 0,
    text: "파일 준비됨",
    className: "status-pill safe",
  }},
);

assert.deepStrictEqual(
  helpers.deriveSourceLibraryStatusState([
    {{ id: "low", required: true, active_exists: false }},
    {{ id: "voice_raw", required: false, active_exists: false }},
  ]),
  {{
    missingCount: 1,
    text: "1개 선택 필요",
    className: "status-pill hot",
  }},
);
""",
    )


def test_static_ui_recording_stop_busy_state_disables_capture_controls(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for static app behavior smoke test")

    script = static_app_test_script(
        tmp_path,
        (
            "{ state, applyState, renderState, renderSyncBadge, "
            "renderRecordingControls, renderVoiceStackControls, renderWorkspaceTabs, "
            "setWorkspaceTab, setStorageMode, translateUiErrorMessage, describeUiNotice, "
            "renderEventLogSummary, draftEditLocked, "
            "connectStateSocket, showError, renderErrors, renderDevices, renderSourceLibrary, "
            "releaseInteractiveControl, refreshAll, requestDevices, requestSources, "
            "changeDevice, control, startFromSpace, stopFromSpace, stopIfRecording, "
            "renderLayerControls, syncAppliedSourceSignature, saveDraft, selectSourceFile, "
            "uploadSourceFile, applyAndRestart, resetDraft }"
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
  listeners: {{}},
  _queryElements: {{}},
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
  addEventListener(eventName, handler) {{
    this.listeners[eventName] = handler;
  }},
  dispatchEvent(event) {{
    this.listeners[event.type]?.(event);
  }},
  querySelector(selector) {{
    if (!this._queryElements[selector]) {{
      this._queryElements[selector] = makeTrackedElement();
    }}
    return this._queryElements[selector];
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

const recordOutcome = makeTrackedElement();
recordOutcome.className = "record-outcome ready";
elements.recordOutcomeStatus = makeTrackedElement();
elements.recordOutcomeStatus.textContent = "준비";
elements.recordOutcomeStatus.parentElement = recordOutcome;
elements.recordOutcomeDetail = makeTrackedElement();
elements.recordOutcomeDetail.textContent = "먼저 녹음을 준비한 뒤 스페이스바를 누르세요.";
elements.recordOutcomeDetail.parentElement = recordOutcome;

assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage("action failed"),
  "작업 중 오류가 발생했습니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage(
    "audio devices unavailable: host audio unavailable",
  ),
  "오디오 장치를 사용할 수 없습니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage(
    "device changes must be applied from the System panel",
  ),
  "입력/출력 장치는 System 패널에서 선택하세요.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage(
    "state is unavailable: settings file contains invalid JSON",
  ),
  "상태를 불러오지 못했습니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage("Request failed: 503"),
  "요청을 처리하지 못했습니다. HTTP 503 상태입니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage("not recording"),
  "녹음은 이미 중지되어 있습니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage(
    "Selected output default sample rate is 44100, but settings request 48000.",
  ),
  "출력 장치 기본 샘플레이트가 앱 설정과 다릅니다.",
);
const sampleRateNotice = globalThis.__secretPondTest.describeUiNotice(
  "Selected output default sample rate is 44100, but settings request 48000.",
  "caution",
);
assert.strictEqual(sampleRateNotice.severity, "caution");
assert.strictEqual(
  sampleRateNotice.detail,
  "선택한 출력 장치의 기본값은 44100 Hz이고 앱은 48000 Hz로 출력하도록 " +
    "설정되어 있습니다. 재생은 가능할 수 있지만 macOS 오디오 MIDI 설정이나 " +
    "앱 출력 장치를 확인하세요.",
);
assert.strictEqual(
  sampleRateNotice.technical,
  "Selected output default sample rate is 44100, but settings request 48000.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage(
    "Selected input supports 1 channels, but settings request 2.",
  ),
  "선택한 입력 장치의 채널 수가 현재 오디오 설정과 맞지 않습니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage(
    "low source file does not exist: /Users/nohsungbeen/dev/project/" +
      "The Secret Pond/data/sources/low.wav",
  ),
  "선택된 소스 파일을 찾지 못했습니다.",
);
assert.strictEqual(
  globalThis.__secretPondTest.translateUiErrorMessage("이미 한글 오류입니다."),
  "이미 한글 오류입니다.",
);

globalThis.__secretPondTest.showError("action failed");
assert.strictEqual(elements.errorBanner.hidden, false);
assert.strictEqual(elements.errorBanner.className, "error-banner notice-banner error");
assert.strictEqual(elements.errorBanner.getAttribute("role"), "alert");
assert.strictEqual(elements.errorBanner.children[0].children[0].textContent, "오류");
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "작업 중 오류가 발생했습니다.",
);
assert.strictEqual(
  elements.errorBanner.children[1].textContent,
  "문제가 반복되면 최근 이벤트와 시스템 진단을 확인하세요.",
);
assert.strictEqual(elements.errorBanner.children[2].children[0].textContent, "자세히");
assert.strictEqual(
  elements.errorBanner.children[2].children[1].textContent,
  "원문: action failed",
);
assert.strictEqual(elements.errorBadge.textContent, "오류 있음");
assert.strictEqual(elements.errorBadge.className, "status-pill hot");

globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, false);
assert.strictEqual(elements.errorBanner.className, "error-banner notice-banner error");
assert.strictEqual(elements.errorBadge.textContent, "오류 있음");

globalThis.__secretPondTest.state.deviceError = "devices failed";
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "오디오 장치 정보를 불러오지 못했습니다.",
);
globalThis.__secretPondTest.state.deviceError = null;
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, false);
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "작업 중 오류가 발생했습니다.",
);

globalThis.__secretPondTest.showError("");
assert.strictEqual(elements.errorBanner.hidden, true);
assert.strictEqual(elements.errorBanner.textContent, "");
assert.strictEqual(elements.errorBadge.textContent, "오류 없음");
assert.strictEqual(elements.errorBadge.className, "status-pill muted");

globalThis.__secretPondTest.state.snapshot = null;
globalThis.__secretPondTest.state.deviceError = "devices failed";
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "오디오 장치 정보를 불러오지 못했습니다.",
);
assert.strictEqual(elements.errorBadge.textContent, "오류 있음");

globalThis.__secretPondTest.state.deviceError = null;
globalThis.__secretPondTest.state.diagnosticsError = null;
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, true);
assert.strictEqual(elements.errorBadge.textContent, "오류 없음");

globalThis.__secretPondTest.state.devices = {{
  warnings: ["Selected output default sample rate is 44100, but settings request 48000."],
}};
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, false);
assert.strictEqual(elements.errorBanner.className, "error-banner notice-banner caution");
assert.strictEqual(elements.errorBanner.getAttribute("role"), "status");
assert.strictEqual(elements.errorBanner.children[0].children[0].textContent, "주의");
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "출력 장치 기본 샘플레이트가 앱 설정과 다릅니다.",
);
assert.strictEqual(
  elements.errorBanner.children[1].textContent,
  "선택한 출력 장치의 기본값은 44100 Hz이고 앱은 48000 Hz로 출력하도록 " +
    "설정되어 있습니다. 재생은 가능할 수 있지만 macOS 오디오 MIDI 설정이나 " +
    "앱 출력 장치를 확인하세요.",
);
assert.strictEqual(elements.errorBanner.children[2].children[0].textContent, "자세히");
assert.strictEqual(
  elements.errorBanner.children[2].children[1].textContent.includes("원문:"),
  true,
);
assert.strictEqual(elements.errorBadge.textContent, "주의 있음");
assert.strictEqual(elements.errorBadge.className, "status-pill caution");
elements.errorBanner.children[2].open = true;
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.children[2].open, true);

globalThis.__secretPondTest.renderDevices();
assert.strictEqual(elements.deviceHealthBadge.textContent, "장치 주의");
assert.strictEqual(elements.deviceHealthBadge.className, "status-pill caution");
assert.strictEqual(elements.deviceWarnings.children.length, 1);
assert.strictEqual(elements.deviceWarnings.children[0].className, "notice-list-item caution");
assert.strictEqual(
  elements.deviceWarnings.children[0].children[0].children[0].children[1].textContent,
  "출력 장치 기본 샘플레이트가 앱 설정과 다릅니다.",
);

globalThis.__secretPondTest.state.devices = {{ warnings: [] }};
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, true);
assert.strictEqual(elements.errorBadge.textContent, "오류 없음");

delete window.WebSocket;
delete globalThis.WebSocket;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "동기화 확인");
assert.strictEqual(elements.syncBadge.className, "status-pill muted");

window.WebSocket = function FakeWebSocket() {{}};
globalThis.__secretPondTest.state.stateSocket = {{}};
globalThis.__secretPondTest.state.websocketConnected = false;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "동기화 연결 중");
assert.strictEqual(elements.syncBadge.className, "status-pill muted");

globalThis.__secretPondTest.state.websocketConnected = true;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "실시간 동기화");
assert.strictEqual(elements.syncBadge.className, "status-pill safe");

globalThis.__secretPondTest.state.stateSocket = null;
globalThis.__secretPondTest.state.websocketConnected = false;
globalThis.__secretPondTest.renderSyncBadge();
assert.strictEqual(elements.syncBadge.textContent, "동기화 확인");

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
    return this.handlers[eventName]?.(payload);
  }}

  close() {{
    this.emit("close");
  }}
}}
window.WebSocket = FakeStateSocket;
globalThis.WebSocket = FakeStateSocket;
globalThis.__secretPondTest.state.snapshot = null;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.syncBadge.textContent, "동기화 확인");

globalThis.__secretPondTest.connectStateSocket();
const connectedSocket = FakeStateSocket.instances[0];
assert.strictEqual(connectedSocket.url, "ws://127.0.0.1:8000/ws/state");
assert.strictEqual(globalThis.__secretPondTest.state.stateSocket, connectedSocket);
assert.strictEqual(elements.syncBadge.textContent, "동기화 연결 중");

connectedSocket.emit("open");
assert.strictEqual(globalThis.__secretPondTest.state.websocketConnected, true);
assert.strictEqual(elements.syncBadge.textContent, "실시간 동기화");
assert.strictEqual(elements.syncBadge.className, "status-pill safe");

connectedSocket.emit("message", {{
  data: JSON.stringify({{
    error: {{
      code: "state_unavailable",
      message: "state is unavailable: settings file contains invalid JSON",
    }},
  }}),
}});
assert.strictEqual(globalThis.__secretPondTest.state.snapshot, null);
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "상태를 불러오지 못했습니다.",
);
assert.strictEqual(elements.errorBadge.textContent, "오류 있음");

connectedSocket.emit("close");
assert.strictEqual(globalThis.__secretPondTest.state.stateSocket, null);
assert.strictEqual(globalThis.__secretPondTest.state.websocketConnected, false);
assert.strictEqual(elements.syncBadge.textContent, "동기화 확인");
assert.strictEqual(scheduledReconnect.delay, 1500);
globalThis.__secretPondTest.showError("");

globalThis.__secretPondTest.renderEventLogSummary([], "stream start failed");
assert.strictEqual(elements.eventLogSummary.children.length, 1);
assert.strictEqual(elements.eventLogSummary.children[0].className, "notice-list-item error");
assert.strictEqual(
  elements.eventLogSummary.children[0].children[0].children[1].textContent,
  "오디오 출력 처리 중 오류가 발생했습니다.",
);
assert.strictEqual(
  elements.eventLogSummary.children[0].children[1].textContent,
  "출력 스트림, 렌더링 파일, 또는 믹서 상태에서 문제가 발생했습니다. " +
    "출력 장치와 최근 이벤트를 확인하세요.",
);
assert.strictEqual(
  elements.eventLogSummary.children[0].children[2].children[1].textContent,
  "원문: stream start failed",
);
elements.eventLogSummary.children = [];
globalThis.__secretPondTest.renderEventLogSummary([
  {{ timestamp: "2026-06-05T01:31:00Z", event_type: "system.startup_playback_unavailable" }},
  {{ timestamp: "2026-06-05T01:32:00Z", event_type: "recording.accepted" }},
  {{ timestamp: "2026-06-05T01:33:00Z", event_type: "unknown.internal_event" }},
]);
assert.strictEqual(elements.eventLogSummary.children.length, 3);
assert.strictEqual(
  elements.eventLogSummary.children[0].children[1].textContent,
  "시작 재생 준비 실패",
);
assert.strictEqual(elements.eventLogSummary.children[1].children[1].textContent, "녹음 추가");
assert.strictEqual(elements.eventLogSummary.children[2].children[1].textContent, "시스템 이벤트");

const layerSettings = (volumeDb) => ({{
  enabled: true,
  volume_db: volumeDb,
  eq: {{
    low_gain_db: 0,
    mid_gain_db: 0,
    high_gain_db: 0,
    highpass_hz: 20,
    lowpass_hz: 20000,
  }},
}});
const activeSettings = {{
  voice_stack: {{ mode: "live_ephemeral", loop_seconds: 60 }},
  input_control: {{
    minimum_recording_seconds: 3,
    maximum_recording_seconds: 120,
  }},
  recording: {{
    gain_db: 0,
    normalize_peak: 0.35,
    highpass_hz: 90,
    lowpass_hz: 8000,
    presence_gain_db: -3,
    reverb_mix: 0.25,
    delay_mix: 0,
    fade_ms: 50,
  }},
  audio: {{ sample_rate: 48000, channels: 2 }},
  devices: {{ input_device_id: null, output_device_id: null }},
  sources: {{
    low_path: "sources/low/current.wav",
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  }},
  layers: {{
    low: layerSettings(-12),
    mid: layerSettings(-12),
    voice: layerSettings(-18),
  }},
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
  settings: {{
    active: activeSettings,
    draft: activeSettings,
    change: {{
      runtime_config_changed: false,
      changed_runtime_fields: [],
      changed_sections: [],
    }},
  }},
}};

globalThis.__secretPondTest.state.snapshot = snapshot;
globalThis.__secretPondTest.state.draft = activeSettings;
globalThis.__secretPondTest.state.diagnosticsError = "diagnostics failed";
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(
  elements.errorBanner.textContent,
  "",
);
assert.strictEqual(
  elements.errorBanner.children[0].children[1].textContent,
  "시스템 진단 정보를 불러오지 못했습니다.",
);
assert.strictEqual(elements.errorBadge.textContent, "오류 있음");
assert.strictEqual(elements.errorBadge.className, "status-pill hot");
globalThis.__secretPondTest.state.diagnosticsError = null;
globalThis.__secretPondTest.renderErrors();
assert.strictEqual(elements.errorBanner.hidden, true);
assert.strictEqual(elements.errorBadge.textContent, "오류 없음");
globalThis.__secretPondTest.state.recordingStopInFlight = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.captureGateSwitch.disabled, true);
assert.strictEqual(elements.stopButton.disabled, false);
assert.strictEqual(elements.recordCoreStatus.textContent, "녹음 중");
assert.strictEqual(elements.recordOutcomeStatus.textContent, "녹음 중");
assert.strictEqual(elements.recordOutcomeDetail.textContent, "스페이스바를 떼면 중지합니다.");
assert.strictEqual(recordCore.classList.contains("recording"), true);
assert.strictEqual(recordCore.classList.contains("armed"), false);
assert.strictEqual(elements.captureGateSwitch.getAttribute("aria-checked"), "true");
assert.strictEqual(elements.captureGateSwitch.classList.contains("checked"), true);
assert.strictEqual(elements.captureGateState.textContent, "녹음 중");
assert.strictEqual(elements.captureGate.className, "capture-gate capture-gate-recording");

const cloneSettings = (value) => JSON.parse(JSON.stringify(value));
globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.is_recording = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(
  elements.storageModeSummary.textContent,
  "운영 모드 · 파일 안 남김",
);
assert.strictEqual(elements.storageModePanel.className, "storage-mode-panel safe");
assert.strictEqual(elements.storageModeLiveButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(elements.storageModeLibraryButton.getAttribute("aria-pressed"), "false");

globalThis.__secretPondTest.state.devices = {{
  selected_input_device: {{ id: "mic-1", name: "Built-in Mic" }},
  selected_output_device: {{ id: "speaker-1", name: "Built-in Output" }},
  input_devices: [{{ id: "mic-1", name: "Built-in Mic", default_sample_rate: 48000 }}],
  output_devices: [{{ id: "speaker-1", name: "Built-in Output", default_sample_rate: 48000 }}],
  warnings: [],
}};
globalThis.__secretPondTest.state.sources = {{
  categories: [
    {{
      id: "low",
      label: "Low",
      directory: "sources/low",
      active_exists: true,
      legacy_exists: true,
      selected_path: "sources/low/current.wav",
      files: [
        {{
          name: "current.wav",
          path: "sources/low/current.wav",
          size_bytes: 10,
          modified_at: "2026-06-05T00:00:00Z",
          active: true,
        }},
      ],
    }},
  ],
}};
globalThis.__secretPondTest.syncAppliedSourceSignature();
globalThis.__secretPondTest.renderSourceLibrary();
const latestSourceLibraryHtml = () =>
  elements.sourceLibraryList.children[elements.sourceLibraryList.children.length - 1].innerHTML;
const sourceUploadButtonHtml = () => {{
  const html = latestSourceLibraryHtml();
  const start = html.indexOf('data-source-upload="low"');
  const end = html.indexOf('data-source-upload-select="low"');
  return html.slice(start, end);
}};
assert.strictEqual(
  latestSourceLibraryHtml().includes(
    'data-source-upload-select="low" checked',
  ),
  true,
);
assert.strictEqual(
  sourceUploadButtonHtml().includes("disabled"),
  true,
);
assert.strictEqual(
  sourceUploadButtonHtml().includes('title="추가할 WAV 파일을 먼저 선택하세요."'),
  true,
);
globalThis.__secretPondTest.state.sourceUploads.low = {{
  selectAfterUpload: false,
  file: {{ name: "picked-low.wav", size: 4096, lastModified: 1 }},
}};
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(
  latestSourceLibraryHtml().includes(
    'data-source-upload-select="low" checked',
  ),
  false,
);
assert.strictEqual(
  latestSourceLibraryHtml().includes("picked-low.wav · 4.0 KB 선택됨"),
  true,
);
assert.strictEqual(
  sourceUploadButtonHtml().includes("disabled"),
  false,
);
globalThis.__secretPondTest.state.sourceMutationInFlight = true;
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(
  sourceUploadButtonHtml().includes("disabled"),
  true,
);
assert.strictEqual(
  latestSourceLibraryHtml().includes("소스 파일 작업이 끝날 때까지 기다리세요."),
  true,
);
globalThis.__secretPondTest.state.sourceMutationInFlight = false;
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(
  sourceUploadButtonHtml().includes("disabled"),
  false,
);
globalThis.__secretPondTest.state.applyInFlight = true;
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(
  sourceUploadButtonHtml().includes("disabled"),
  true,
);
assert.strictEqual(
  latestSourceLibraryHtml().includes("설정 적용이 끝날 때까지 소스 파일을 바꿀 수 없습니다."),
  true,
);
globalThis.__secretPondTest.state.applyInFlight = false;
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(
  sourceUploadButtonHtml().includes("disabled"),
  false,
);
elements.sourceLibraryList.children = [];
elements.sourceLibraryList.innerHTML = "";
globalThis.__secretPondTest.state.renderSignatures.sourceLibrary = null;
const runSourceSocketRefreshCheck = async () => {{
  globalThis.__secretPondTest.state.sources = {{
    categories: [
      {{
        id: "low",
        label: "Low",
        directory: "sources/low",
        active_exists: true,
        legacy_exists: true,
        selected_path: "sources/low/current.wav",
        files: [
          {{
            name: "current.wav",
            path: "sources/low/current.wav",
            size_bytes: 10,
            modified_at: "2026-06-05T00:00:00Z",
            active: true,
          }},
        ],
      }},
    ],
  }};
  globalThis.__secretPondTest.syncAppliedSourceSignature();
  const socketSourceSettings = cloneSettings(activeSettings);
  socketSourceSettings.sources.low_path = "sources/low/new.wav";
  const socketSourceState = {{
    ...snapshot,
    settings: {{
      active: socketSourceSettings,
      draft: socketSourceSettings,
      change: {{
        runtime_config_changed: false,
        changed_runtime_fields: [],
        changed_sections: [],
      }},
    }},
  }};
  const socketSourceResponses = [];
  globalThis.fetch = (path) => {{
    if (path === "/api/sources") {{
      socketSourceResponses.push(path);
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          categories: [
            {{
              id: "low",
              label: "Low",
              directory: "sources/low",
              active_exists: true,
              legacy_exists: true,
              selected_path: "sources/low/new.wav",
              files: [
                {{
                  name: "new.wav",
                  path: "sources/low/new.wav",
                  size_bytes: 20,
                  modified_at: "2026-06-05T00:02:00Z",
                  active: true,
                }},
              ],
            }},
          ],
        }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  globalThis.__secretPondTest.connectStateSocket();
  const sourceSocket = FakeStateSocket.instances[FakeStateSocket.instances.length - 1];
  await sourceSocket.emit("message", {{ data: JSON.stringify(socketSourceState) }});
  assert.strictEqual(socketSourceResponses.length, 1);
  assert.strictEqual(
    globalThis.__secretPondTest.state.sources.categories[0].selected_path,
    "sources/low/new.wav",
  );
  assert.strictEqual(
    globalThis.__secretPondTest.state.appliedSourceSignature.includes("sources/low/new.wav"),
    true,
  );
  elements.participantCount.textContent = "native dropdown still open";
  await sourceSocket.emit("message", {{ data: JSON.stringify(socketSourceState) }});
  assert.strictEqual(socketSourceResponses.length, 1);
  assert.strictEqual(elements.participantCount.textContent, "native dropdown still open");
}};
document.getElementById("inputDeviceSelect");
document.getElementById("sourceLibraryList");
globalThis.__secretPondTest.state.sources = null;
globalThis.__secretPondTest.state.sourcesError = "source file does not exist: data/sources/low.wav";
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(elements.sourceLibraryStatus.textContent, "목록 실패");
assert.strictEqual(
  elements.sourceLibraryList.children[0].className,
  "source-library-empty notice-list-item error",
);
assert.strictEqual(
  elements.sourceLibraryList.children[0].children[0].children[1].textContent,
  "선택된 소스 파일을 찾지 못했습니다.",
);
assert.strictEqual(
  elements.sourceLibraryList.children[0].children[1].textContent,
  "현재 설정이 가리키는 WAV 파일이 없습니다. Source Library에서 존재하는 파일을 다시 선택하세요.",
);
assert.strictEqual(
  elements.sourceLibraryList.children[0].children[2].children[1].textContent,
  "원문: source file does not exist: data/sources/low.wav",
);
globalThis.__secretPondTest.state.sourcesError = null;
globalThis.__secretPondTest.state.sources = {{
  categories: [
    {{
      id: "low",
      label: "Low",
      directory: "sources/low",
      active_exists: true,
      legacy_exists: true,
      selected_path: "sources/low/current.wav",
      files: [
        {{
          name: "current.wav",
          path: "sources/low/current.wav",
          size_bytes: 10,
          modified_at: "2026-06-05T00:00:00Z",
          active: true,
        }},
      ],
    }},
  ],
}};
globalThis.__secretPondTest.renderDevices();
elements.inputDeviceSelect.innerHTML = "native device dropdown still open";
globalThis.__secretPondTest.renderDevices();
assert.strictEqual(elements.inputDeviceSelect.innerHTML, "native device dropdown still open");
globalThis.__secretPondTest.renderSourceLibrary();
elements.sourceLibraryList.innerHTML = "native source dropdown still open";
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(elements.sourceLibraryList.innerHTML, "native source dropdown still open");
elements.inputDeviceSelect.innerHTML = "open device dropdown";
elements.sourceLibraryList.innerHTML = "open source dropdown";
globalThis.document.activeElement = elements.inputDeviceSelect;
globalThis.__secretPondTest.state.activeInteractiveControl = elements.inputDeviceSelect;
globalThis.__secretPondTest.applyState(snapshot, {{ syncDraft: false }});
assert.strictEqual(elements.inputDeviceSelect.innerHTML, "open device dropdown");
assert.strictEqual(elements.sourceLibraryList.innerHTML, "open source dropdown");
globalThis.__secretPondTest.renderDevices();
assert.strictEqual(elements.inputDeviceSelect.innerHTML, "open device dropdown");
globalThis.__secretPondTest.state.devices.input_devices[0].name = "Renamed Mic";
globalThis.__secretPondTest.releaseInteractiveControl(elements.inputDeviceSelect);
globalThis.__secretPondTest.renderDevices();
assert.strictEqual(elements.inputDeviceSelect.innerHTML, "");

const focusedSourceSelect = makeTrackedElement();
focusedSourceSelect.tagName = "SELECT";
elements.sourceLibraryList.innerHTML = "open source dropdown";
elements.sourceLibraryList.contains = (element) => element === focusedSourceSelect;
globalThis.document.activeElement = focusedSourceSelect;
globalThis.__secretPondTest.state.activeInteractiveControl = focusedSourceSelect;
globalThis.__secretPondTest.renderSourceLibrary();
assert.strictEqual(elements.sourceLibraryList.innerHTML, "open source dropdown");
globalThis.__secretPondTest.state.sources.categories[0].label = "Renamed Low";
globalThis.__secretPondTest.releaseInteractiveControl(focusedSourceSelect);
globalThis.__secretPondTest.renderSourceLibrary();
assert.notStrictEqual(elements.sourceLibraryList.innerHTML, "open source dropdown");
globalThis.document.activeElement = null;

globalThis.__secretPondTest.setStorageMode("test_library");
assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.mode, "test_library");
assert.strictEqual(
  elements.storageModeSummary.textContent,
  "운영 모드 · 재시작 시 적용: 테스트 저장",
);
assert.strictEqual(elements.storageModePanel.className, "storage-mode-panel library pending");
assert.strictEqual(elements.storageModeLiveButton.getAttribute("aria-pressed"), "false");
assert.strictEqual(elements.storageModeLibraryButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(elements.pendingBadge.hidden, false);
assert.strictEqual(elements.applyButton.classList.contains("attention"), true);
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.settings.active.voice_stack.mode = "test_library";
globalThis.__secretPondTest.state.snapshot.settings.draft.voice_stack.mode = "test_library";
globalThis.__secretPondTest.state.snapshot.settings.change = {{
  runtime_config_changed: false,
  changed_runtime_fields: [],
  changed_sections: [],
}};
globalThis.__secretPondTest.state.draft.voice_stack.mode = "test_library";
globalThis.__secretPondTest.renderState();
assert.strictEqual(
  elements.storageModeSummary.textContent,
  "테스트 모드 · 파일 저장",
);
assert.strictEqual(elements.storageModePanel.className, "storage-mode-panel library");
globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, true);
assert.strictEqual(elements.pendingBadge.textContent, "");
assert.strictEqual(elements.pendingBadge.className, "status-pill hot");
assert.strictEqual(elements.applyButton.classList.contains("attention"), false);
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "적용할 변경사항이 없습니다.");
assert.strictEqual(elements.resetButton.disabled, true);
assert.strictEqual(elements.resetButton.title, "취소할 설정 변경사항이 없습니다.");
globalThis.__secretPondTest.renderVoiceStackControls();
const voiceLoopRow = elements.voiceStackControls.children[0];
const voiceLoopInput = voiceLoopRow.querySelector("input");
voiceLoopInput.value = "120";
voiceLoopInput.dispatchEvent({{ type: "input" }});
assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 105);
assert.strictEqual(elements.pendingBadge.hidden, false);
assert.strictEqual(elements.pendingBadge.textContent, "저장 안 된 오디오 변경");
assert.strictEqual(elements.pendingBadge.className, "status-pill hot");
assert.strictEqual(elements.applyButton.classList.contains("attention"), true);
assert.strictEqual(elements.applyButton.disabled, false);
assert.strictEqual(elements.applyButton.title, "");
assert.strictEqual(elements.resetButton.disabled, false);
assert.strictEqual(elements.resetButton.title, "");
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, true);
assert.strictEqual(elements.applyButton.classList.contains("attention"), false);
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.resetButton.disabled, true);
globalThis.__secretPondTest.renderRecordingControls();
const inputGainGroupBody = elements.recordingControls.children[0].children[0];
const inputGainRow = inputGainGroupBody.children[0];
const inputGainInput = inputGainRow.querySelector("input");
inputGainInput.value = "3";
inputGainInput.dispatchEvent({{ type: "input" }});
assert.strictEqual(elements.pendingBadge.hidden, false);
assert.strictEqual(elements.pendingBadge.textContent, "저장 안 된 오디오 변경");
assert.strictEqual(elements.pendingBadge.className, "status-pill hot");
assert.strictEqual(elements.applyButton.disabled, false);
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, true);
assert.strictEqual(elements.applyButton.disabled, true);

globalThis.__secretPondTest.renderLayerControls();
const mixerLayerCard = elements.layerControls.children[0];
const mixerLayerToggle = mixerLayerCard.querySelector("input[type='checkbox']");
mixerLayerToggle.checked = false;
mixerLayerToggle.dispatchEvent({{ type: "change", target: mixerLayerToggle }});
assert.strictEqual(elements.pendingBadge.hidden, false);
assert.strictEqual(elements.pendingBadge.textContent, "저장 안 된 오디오 변경");
assert.strictEqual(elements.applyButton.disabled, false);
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, true);
assert.strictEqual(elements.applyButton.disabled, true);

globalThis.__secretPondTest.state.sources.categories[0].files[0].modified_at =
  "2026-06-05T00:30:00Z";
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, false);
assert.strictEqual(elements.pendingBadge.textContent, "저장 안 된 오디오 변경");
assert.strictEqual(elements.applyButton.disabled, false);
globalThis.__secretPondTest.syncAppliedSourceSignature();
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, true);
assert.strictEqual(elements.applyButton.disabled, true);

const deviceDraft = cloneSettings(activeSettings);
deviceDraft.devices.input_device_id = "mic-2";
deviceDraft.devices.output_device_id = "speaker-2";
globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(deviceDraft);
globalThis.__secretPondTest.state.snapshot.settings.change = {{
  runtime_config_changed: true,
  changed_runtime_fields: ["devices.input_device_id", "devices.output_device_id"],
  changed_sections: ["devices"],
}};
globalThis.__secretPondTest.state.draft = cloneSettings(deviceDraft);
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.pendingBadge.hidden, false);
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.classList.contains("attention"), false);
assert.strictEqual(elements.resetButton.disabled, false);
assert.strictEqual(
  elements.applyButton.title,
  "샘플레이트, 채널 변경은 앱 재시작이 필요하고 장치 변경은 System 패널에서 적용해야 합니다.",
);
globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(activeSettings);
globalThis.__secretPondTest.state.snapshot.settings.change = {{
  runtime_config_changed: false,
  changed_runtime_fields: [],
  changed_sections: [],
}};
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);

globalThis.__secretPondTest.state.recordingStopInFlight = true;
globalThis.__secretPondTest.state.snapshot.playback.output_running = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "녹음 처리가 끝날 때까지 기다리세요.");
assert.strictEqual(elements.startOutputButton.disabled, true);
globalThis.__secretPondTest.state.snapshot.playback.output_running = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.stopOutputButton.disabled, true);
assert.strictEqual(elements.restartOutputButton.disabled, true);

globalThis.__secretPondTest.state.recordingStopInFlight = false;
globalThis.__secretPondTest.state.snapshot.playback.output_running = false;
globalThis.__secretPondTest.state.snapshot.is_recording = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.recordCoreStatus.textContent, "준비 완료");
assert.strictEqual(elements.recordOutcomeStatus.textContent, "스페이스바를 눌러 녹음");
assert.strictEqual(
  elements.recordOutcomeDetail.textContent,
  "스페이스바를 떼면 녹음을 중지합니다.",
);
assert.strictEqual(recordOutcome.className, "record-outcome armed-ready");
assert.strictEqual(recordCore.classList.contains("recording"), false);
assert.strictEqual(recordCore.classList.contains("armed"), true);
assert.strictEqual(elements.captureGateSwitch.disabled, false);
assert.strictEqual(elements.captureGateSwitch.getAttribute("aria-checked"), "true");
assert.strictEqual(elements.captureGateSwitch.classList.contains("checked"), true);
assert.strictEqual(elements.captureGateState.textContent, "녹음 준비 켜짐");
assert.strictEqual(elements.captureGate.className, "capture-gate capture-gate-on");
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "적용할 변경사항이 없습니다.");
assert.strictEqual(elements.startOutputButton.disabled, false);

globalThis.__secretPondTest.state.recordingStopInFlight = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.captureGateSwitch.disabled, true);
assert.strictEqual(elements.startButton.disabled, true);
assert.strictEqual(elements.stopButton.disabled, true);
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "녹음 처리가 끝날 때까지 기다리세요.");
assert.strictEqual(elements.startOutputButton.disabled, true);
assert.strictEqual(elements.recordCoreStatus.textContent, "처리 중");
assert.strictEqual(elements.recordOutcomeStatus.textContent, "녹음 처리 중...");
assert.strictEqual(recordCore.classList.contains("armed"), false);

globalThis.__secretPondTest.state.recordingStopInFlight = false;
globalThis.__secretPondTest.state.applyInFlight = true;
globalThis.__secretPondTest.state.snapshot.playback.output_running = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(globalThis.__secretPondTest.draftEditLocked(), true);
assert.strictEqual(elements.startOutputButton.disabled, true);
globalThis.__secretPondTest.renderDevices();
assert.strictEqual(elements.inputDeviceSelect.disabled, true);
assert.strictEqual(elements.outputDeviceSelect.disabled, true);
assert.strictEqual(elements.inputDeviceSelect.title, "설정 적용이 끝날 때까지 기다리세요.");
assert.strictEqual(elements.outputDeviceSelect.title, "설정 적용이 끝날 때까지 기다리세요.");
globalThis.__secretPondTest.state.snapshot.playback.output_running = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.stopOutputButton.disabled, true);
assert.strictEqual(elements.restartOutputButton.disabled, true);
globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
const voiceStackControlCountBeforeLockRender = elements.voiceStackControls.children.length;
globalThis.__secretPondTest.renderVoiceStackControls();
const lockedVoiceLoopRow =
  elements.voiceStackControls.children[voiceStackControlCountBeforeLockRender];
const lockedVoiceLoopInput = lockedVoiceLoopRow.querySelector("input");
const lockedVoiceLoopValueInput = lockedVoiceLoopRow.querySelector(".value-input");
assert.strictEqual(lockedVoiceLoopInput.disabled, true);
assert.strictEqual(lockedVoiceLoopValueInput.disabled, true);
lockedVoiceLoopInput.value = "90";
lockedVoiceLoopInput.dispatchEvent({{ type: "input" }});
assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 60);
assert.strictEqual(lockedVoiceLoopInput.value, "60");

globalThis.__secretPondTest.state.applyInFlight = false;
assert.strictEqual(globalThis.__secretPondTest.draftEditLocked(), false);
globalThis.__secretPondTest.state.snapshot.playback.output_running = false;
globalThis.__secretPondTest.state.snapshot.armed = false;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.recordCoreStatus.textContent, "준비 전");
assert.strictEqual(elements.recordOutcomeStatus.textContent, "녹음 준비 필요");
assert.strictEqual(
  elements.recordOutcomeDetail.textContent,
  "녹음 준비를 켠 뒤 스페이스바를 누르세요.",
);
assert.strictEqual(recordCore.classList.contains("armed"), false);
assert.strictEqual(recordCore.classList.contains("recording"), false);
assert.strictEqual(elements.captureGateSwitch.getAttribute("aria-checked"), "false");
assert.strictEqual(elements.captureGateSwitch.classList.contains("checked"), false);
assert.strictEqual(elements.captureGateSwitch.disabled, false);
assert.strictEqual(elements.captureGateState.textContent, "녹음 준비 꺼짐");
assert.strictEqual(elements.captureGate.className, "capture-gate capture-gate-off");
assert.strictEqual(elements.applyButton.disabled, true);
assert.strictEqual(elements.applyButton.title, "적용할 변경사항이 없습니다.");

elements.recordOutcomeStatus.textContent = "녹음 추가됨";
elements.recordOutcomeDetail.textContent = "참여자 8 · 4.2s";
recordOutcome.className = "record-outcome added";
globalThis.__secretPondTest.state.snapshot.armed = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.recordOutcomeStatus.textContent, "녹음 추가됨");
assert.strictEqual(elements.recordOutcomeDetail.textContent, "참여자 8 · 4.2s");
assert.strictEqual(recordOutcome.className, "record-outcome added");

globalThis.__secretPondTest.state.snapshot.is_recording = true;
globalThis.__secretPondTest.renderState();
assert.strictEqual(elements.recordOutcomeStatus.textContent, "녹음 중");
assert.strictEqual(elements.recordOutcomeDetail.textContent, "스페이스바를 떼면 중지합니다.");
assert.strictEqual(recordOutcome.className, "record-outcome recording");
globalThis.__secretPondTest.state.snapshot.is_recording = false;

(async () => {{
  let applyDeviceChangePath = null;
  globalThis.__secretPondTest.state.applyInFlight = true;
  globalThis.fetch = (path) => {{
    applyDeviceChangePath = path;
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  await globalThis.__secretPondTest.changeDevice("output_device_id", "speaker-2");
  assert.strictEqual(applyDeviceChangePath, null);
  globalThis.__secretPondTest.state.applyInFlight = false;
  globalThis.__secretPondTest.renderDevices();
  assert.strictEqual(elements.outputDeviceSelect.disabled, false);
  assert.strictEqual(elements.outputDeviceSelect.title, "");

  const unsavedDeviceDraft = cloneSettings(activeSettings);
  unsavedDeviceDraft.voice_stack.loop_seconds = 91;
  const serverDeviceActive = cloneSettings(activeSettings);
  serverDeviceActive.devices.output_device_id = "speaker-2";
  const serverDeviceDraft = cloneSettings(activeSettings);
  serverDeviceDraft.devices.output_device_id = "speaker-2";
  globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.draft = cloneSettings(unsavedDeviceDraft);
  globalThis.fetch = (path) => {{
    if (path === "/api/devices") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          state: {{
            ...snapshot,
            is_recording: false,
            settings: {{
              active: cloneSettings(serverDeviceActive),
              draft: cloneSettings(serverDeviceDraft),
              change: {{
                runtime_config_changed: false,
                changed_runtime_fields: [],
                changed_sections: ["devices"],
              }},
            }},
          }},
          devices: {{
            input_devices: [],
            output_devices: [],
            selected_input_device: null,
            selected_output_device: {{ id: "speaker-2", name: "Speaker 2" }},
            warnings: [],
          }},
        }}),
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
  await globalThis.__secretPondTest.changeDevice("output_device_id", "speaker-2");
  assert.strictEqual(
    globalThis.__secretPondTest.state.draft.devices.output_device_id,
    "speaker-2",
  );
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 91);
  assert.strictEqual(
    globalThis.__secretPondTest.state.snapshot.settings.draft.voice_stack.loop_seconds,
    91,
  );

  const oldDeviceList = {{
    input_devices: [],
    output_devices: [{{ id: "speaker-1", name: "Speaker 1" }}],
    selected_input_device: null,
    selected_output_device: {{ id: "speaker-1", name: "Speaker 1" }},
    warnings: [],
  }};
  const newDeviceList = {{
    input_devices: [],
    output_devices: [{{ id: "speaker-2", name: "Speaker 2" }}],
    selected_input_device: null,
    selected_output_device: {{ id: "speaker-2", name: "Speaker 2" }},
    warnings: [],
  }};
  const slowDeviceRefreshResponses = [];
  globalThis.__secretPondTest.state.devices = oldDeviceList;
  globalThis.fetch = (path, options = {{}}) => {{
    if (path === "/api/devices" && options.method === "PUT") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          state: {{
            ...snapshot,
            is_recording: false,
            settings: {{
              active: cloneSettings(serverDeviceActive),
              draft: cloneSettings(serverDeviceDraft),
              change: {{
                runtime_config_changed: false,
                changed_runtime_fields: [],
                changed_sections: ["devices"],
              }},
            }},
          }},
          devices: newDeviceList,
        }}),
      }});
    }}
    if (path === "/api/devices") {{
      return new Promise((resolve) => {{
        slowDeviceRefreshResponses.push(resolve);
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
  const staleDeviceRefresh = globalThis.__secretPondTest.requestDevices();
  assert.strictEqual(slowDeviceRefreshResponses.length, 1);
  await globalThis.__secretPondTest.changeDevice("output_device_id", "speaker-2");
  assert.strictEqual(
    globalThis.__secretPondTest.state.devices.selected_output_device.id,
    "speaker-2",
  );
  slowDeviceRefreshResponses[0]({{
    ok: true,
    json: async () => oldDeviceList,
  }});
  await staleDeviceRefresh;
  assert.strictEqual(
    globalThis.__secretPondTest.state.devices.selected_output_device.id,
    "speaker-2",
  );

  globalThis.__secretPondTest.applyState({{
    ...snapshot,
    is_recording: false,
    settings: {{
      active: cloneSettings(activeSettings),
      draft: cloneSettings(activeSettings),
      change: {{
        runtime_config_changed: false,
        changed_runtime_fields: [],
        changed_sections: [],
      }},
    }},
  }});

  let cleanApplyFetchPath = null;
  globalThis.fetch = (path) => {{
    cleanApplyFetchPath = path;
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  await globalThis.__secretPondTest.applyAndRestart();
  assert.strictEqual(cleanApplyFetchPath, null);
  let cleanResetConfirmed = false;
  window.confirm = () => {{
    cleanResetConfirmed = true;
    return true;
  }};
  await globalThis.__secretPondTest.resetDraft();
  assert.strictEqual(cleanResetConfirmed, false);

  await runSourceSocketRefreshCheck();

  const unsavedDraft = cloneSettings(activeSettings);
  unsavedDraft.voice_stack.loop_seconds = 77;
  const serverDraft = cloneSettings(activeSettings);
  serverDraft.voice_stack.loop_seconds = 60;
  globalThis.__secretPondTest.showError("action failed");
  assert.strictEqual(globalThis.__secretPondTest.state.transientError, "action failed");
  globalThis.__secretPondTest.state.draft = cloneSettings(unsavedDraft);
  globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(serverDraft);
  globalThis.fetch = (path) => {{
    if (path === "/api/state") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          ...snapshot,
          settings: {{
            active: cloneSettings(activeSettings),
            draft: cloneSettings(serverDraft),
            change: {{
              runtime_config_changed: false,
              changed_runtime_fields: [],
              changed_sections: [],
            }},
          }},
        }}),
      }});
    }}
    if (path === "/api/devices") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          input_devices: [],
          output_devices: [],
          selected_input_device: null,
          selected_output_device: null,
          warnings: [],
        }}),
      }});
    }}
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    if (path === "/api/sources") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ categories: [] }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  await globalThis.__secretPondTest.refreshAll();
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 77);
  assert.strictEqual(
    globalThis.__secretPondTest.state.snapshot.settings.draft.voice_stack.loop_seconds,
    77,
  );
  assert.strictEqual(globalThis.__secretPondTest.state.transientError, null);
  assert.strictEqual(elements.errorBanner.hidden, true);

  globalThis.__secretPondTest.showError("");
  globalThis.fetch = (path) => {{
    if (path === "/api/state") {{
      throw new Error("state refresh failed");
    }}
    if (path === "/api/devices") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          input_devices: [],
          output_devices: [],
          selected_input_device: null,
          selected_output_device: null,
          warnings: [],
        }}),
      }});
    }}
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    if (path === "/api/sources") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ categories: [] }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  await globalThis.__secretPondTest.refreshAll();
  assert.strictEqual(globalThis.__secretPondTest.state.transientError, "state refresh failed");
  assert.strictEqual(elements.errorBanner.hidden, false);
  globalThis.__secretPondTest.showError("");

  const draftSaveResponses = [];
  globalThis.fetch = (path, options = {{}}) =>
    new Promise((resolve) => {{
      draftSaveResponses.push({{ path, options, resolve }});
    }});
  const olderDraft = cloneSettings(activeSettings);
  olderDraft.voice_stack.loop_seconds = 61;
  globalThis.__secretPondTest.state.draft = cloneSettings(olderDraft);
  const olderSave = globalThis.__secretPondTest.saveDraft();
  const newerDraft = cloneSettings(activeSettings);
  newerDraft.voice_stack.loop_seconds = 62;
  globalThis.__secretPondTest.state.draft = cloneSettings(newerDraft);
  const newerSave = globalThis.__secretPondTest.saveDraft();
  assert.strictEqual(draftSaveResponses.length, 2);
  draftSaveResponses[1].resolve({{
    ok: true,
    json: async () => ({{
      settings: {{
        active: cloneSettings(activeSettings),
        draft: cloneSettings(newerDraft),
      }},
    }}),
  }});
  await newerSave;
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 62);
  draftSaveResponses[0].resolve({{
    ok: true,
    json: async () => ({{
      settings: {{
        active: cloneSettings(activeSettings),
        draft: cloneSettings(olderDraft),
      }},
    }}),
  }});
  await olderSave;
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 62);

  const inFlightEditSaveRequests = [];
  const inFlightOlderDraft = cloneSettings(activeSettings);
  inFlightOlderDraft.voice_stack.loop_seconds = 63;
  globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(inFlightOlderDraft);
  globalThis.__secretPondTest.state.draft = cloneSettings(inFlightOlderDraft);
  globalThis.fetch = (path, options = {{}}) =>
    new Promise((resolve) => {{
      inFlightEditSaveRequests.push({{ path, options, resolve }});
    }});
  const saveBeforeNewEdit = globalThis.__secretPondTest.saveDraft();
  assert.strictEqual(inFlightEditSaveRequests.length, 1);
  globalThis.__secretPondTest.setStorageMode("test_library");
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.mode, "test_library");
  assert.strictEqual(inFlightEditSaveRequests.length, 1);
  inFlightEditSaveRequests[0].resolve({{
    ok: true,
    json: async () => ({{
      settings: {{
        active: cloneSettings(activeSettings),
        draft: cloneSettings(inFlightOlderDraft),
      }},
    }}),
  }});
  await saveBeforeNewEdit;
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.mode, "test_library");
  assert.strictEqual(
    globalThis.__secretPondTest.state.snapshot.settings.draft.voice_stack.mode,
    "test_library",
  );

  const resetRaceSaveRequests = [];
  const resetDraftValue = cloneSettings(activeSettings);
  const staleDraftValue = cloneSettings(activeSettings);
  staleDraftValue.voice_stack.loop_seconds = 89;
  globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(staleDraftValue);
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  globalThis.__secretPondTest.state.draft = cloneSettings(staleDraftValue);
  window.confirm = () => true;
  globalThis.fetch = (path, options = {{}}) => {{
    if (path === "/api/settings/draft") {{
      return new Promise((resolve) => {{
        resetRaceSaveRequests.push({{ path, options, resolve }});
      }});
    }}
    if (path === "/api/settings/reset-draft") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          settings: {{
            active: cloneSettings(activeSettings),
            draft: cloneSettings(resetDraftValue),
          }},
        }}),
      }});
    }}
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    if (path === "/api/sources") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ categories: [] }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  const staleSaveAfterReset = globalThis.__secretPondTest.saveDraft();
  assert.strictEqual(resetRaceSaveRequests.length, 1);
  await globalThis.__secretPondTest.resetDraft();
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 60);
  resetRaceSaveRequests[0].resolve({{
    ok: true,
    json: async () => ({{
      settings: {{
        active: cloneSettings(activeSettings),
        draft: cloneSettings(staleDraftValue),
      }},
    }}),
  }});
  await staleSaveAfterReset;
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 60);

  const resetInFlightRequests = [];
  globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  globalThis.__secretPondTest.state.draft = cloneSettings(activeSettings);
  globalThis.__secretPondTest.setStorageMode("test_library");
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.mode, "test_library");
  window.confirm = () => true;
  globalThis.fetch = (path) => {{
    if (path === "/api/settings/reset-draft") {{
      return new Promise((resolve) => {{
        resetInFlightRequests.push(resolve);
      }});
    }}
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    if (path === "/api/sources") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ categories: [] }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  const pendingReset = globalThis.__secretPondTest.resetDraft();
  assert.strictEqual(resetInFlightRequests.length, 1);
  assert.strictEqual(globalThis.__secretPondTest.state.resetDraftInFlight, true);
  assert.strictEqual(globalThis.__secretPondTest.draftEditLocked(), true);
  assert.strictEqual(elements.resetButton.disabled, true);
  assert.strictEqual(elements.resetButton.title, "설정 변경 취소가 끝날 때까지 기다리세요.");
  globalThis.__secretPondTest.setStorageMode("live_ephemeral");
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.mode, "test_library");
  resetInFlightRequests[0]({{
    ok: true,
    json: async () => ({{
      settings: {{
        active: cloneSettings(activeSettings),
        draft: cloneSettings(activeSettings),
      }},
    }}),
  }});
  await pendingReset;
  assert.strictEqual(globalThis.__secretPondTest.state.resetDraftInFlight, false);
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.mode, "live_ephemeral");

  const sourceSettingsFor = (lowPath) => {{
    const active = cloneSettings(activeSettings);
    active.sources.low_path = lowPath;
    const draft = cloneSettings(active);
    return {{ active, draft }};
  }};
  const sourcePayloadFor = (lowPath) => ({{
    settings: sourceSettingsFor(lowPath),
    sources: {{
      categories: [
        {{
          id: "low",
          label: "Low",
          directory: "sources/low",
          active_exists: true,
          legacy_exists: true,
          selected_path: lowPath,
          files: [
            {{
              name: "older.wav",
              path: "sources/low/older.wav",
              size_bytes: 10,
              modified_at: "2026-06-05T00:00:00Z",
              active: lowPath === "sources/low/older.wav",
            }},
            {{
              name: "newer.wav",
              path: "sources/low/newer.wav",
              size_bytes: 10,
              modified_at: "2026-06-05T00:01:00Z",
              active: lowPath === "sources/low/newer.wav",
            }},
          ],
        }},
      ],
    }},
  }});
  const uploadRequests = [];
  globalThis.__secretPondTest.state.sourceUploads.low = {{
    selectAfterUpload: false,
    file: {{ name: "stored-low.wav", size: 4096, lastModified: 2 }},
  }};
  globalThis.fetch = (path, options = {{}}) => {{
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    uploadRequests.push({{ path, options }});
    return Promise.resolve({{
      ok: true,
      json: async () => sourcePayloadFor("sources/low/current.wav"),
    }});
  }};
  await globalThis.__secretPondTest.uploadSourceFile("low");
  assert.strictEqual(uploadRequests.length, 1);
  assert.strictEqual(uploadRequests[0].path.includes("filename=stored-low.wav"), true);
  assert.strictEqual(uploadRequests[0].path.includes("select=false"), true);
  assert.strictEqual(uploadRequests[0].options.body.name, "stored-low.wav");
  assert.strictEqual(globalThis.__secretPondTest.state.sourceUploads.low.file, null);
  assert.strictEqual(globalThis.__secretPondTest.state.sourceMutationInFlight, false);

  const unsavedSourceDraft = cloneSettings(activeSettings);
  unsavedSourceDraft.voice_stack.loop_seconds = 88;
  globalThis.__secretPondTest.state.snapshot.settings.active = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.snapshot.settings.draft = cloneSettings(activeSettings);
  globalThis.__secretPondTest.state.draft = cloneSettings(unsavedSourceDraft);
  globalThis.fetch = (path) => {{
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    return Promise.resolve({{
      ok: true,
      json: async () => sourcePayloadFor("sources/low/newer.wav"),
    }});
  }};
  await globalThis.__secretPondTest.selectSourceFile("low", "sources/low/newer.wav");
  assert.strictEqual(
    globalThis.__secretPondTest.state.draft.sources.low_path,
    "sources/low/newer.wav",
  );
  assert.strictEqual(globalThis.__secretPondTest.state.draft.voice_stack.loop_seconds, 88);
  assert.strictEqual(
    globalThis.__secretPondTest.state.snapshot.settings.draft.voice_stack.loop_seconds,
    88,
  );

  const sourceSelectResponses = [];
  globalThis.fetch = (path, options = {{}}) => {{
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    return new Promise((resolve) => {{
      sourceSelectResponses.push({{ path, options, resolve }});
    }});
  }};
  const olderSelect = globalThis.__secretPondTest.selectSourceFile(
    "low",
    "sources/low/older.wav",
  );
  const newerSelect = globalThis.__secretPondTest.selectSourceFile(
    "low",
    "sources/low/newer.wav",
  );
  assert.strictEqual(sourceSelectResponses.length, 2);
  assert.strictEqual(globalThis.__secretPondTest.state.sourceMutationInFlight, true);
  sourceSelectResponses[1].resolve({{
    ok: true,
    json: async () => sourcePayloadFor("sources/low/newer.wav"),
  }});
  await newerSelect;
  assert.strictEqual(
    globalThis.__secretPondTest.state.draft.sources.low_path,
    "sources/low/newer.wav",
  );
  assert.strictEqual(globalThis.__secretPondTest.state.sourceMutationInFlight, false);
  sourceSelectResponses[0].resolve({{
    ok: true,
    json: async () => sourcePayloadFor("sources/low/older.wav"),
  }});
  await olderSelect;
  assert.strictEqual(
    globalThis.__secretPondTest.state.draft.sources.low_path,
    "sources/low/newer.wav",
  );
  assert.strictEqual(globalThis.__secretPondTest.state.sourceMutationInFlight, false);

  const sourceRefreshResponses = [];
  globalThis.__secretPondTest.state.sources = sourcePayloadFor("sources/low/current.wav").sources;
  globalThis.fetch = (path) => {{
    if (path === "/api/sources") {{
      return new Promise((resolve) => {{
        sourceRefreshResponses.push(resolve);
      }});
    }}
    if (path === "/api/sources/low/select") {{
      return Promise.resolve({{
        ok: true,
        json: async () => sourcePayloadFor("sources/low/newer.wav"),
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
  const staleSourceRefresh = globalThis.__secretPondTest.requestSources();
  assert.strictEqual(sourceRefreshResponses.length, 1);
  await globalThis.__secretPondTest.selectSourceFile("low", "sources/low/newer.wav");
  assert.strictEqual(
    globalThis.__secretPondTest.state.sources.categories[0].selected_path,
    "sources/low/newer.wav",
  );
  sourceRefreshResponses[0]({{
    ok: true,
    json: async () => sourcePayloadFor("sources/low/older.wav").sources,
  }});
  await staleSourceRefresh;
  assert.strictEqual(
    globalThis.__secretPondTest.state.sources.categories[0].selected_path,
    "sources/low/newer.wav",
  );

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

  let unexpectedStartPath = null;
  globalThis.fetch = (path) => {{
    unexpectedStartPath = path;
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  const repeatSpaceEvent = {{
    code: "Space",
    repeat: true,
    defaultPrevented: false,
    preventDefault() {{
      this.defaultPrevented = true;
    }},
  }};
  let repeatButtonBlurred = false;
  globalThis.document.activeElement = {{
    tagName: "BUTTON",
    blur() {{
      repeatButtonBlurred = true;
    }},
  }};
  globalThis.__secretPondTest.state.spaceRecording = false;
  globalThis.__secretPondTest.state.recordingStopInFlight = false;
  globalThis.__secretPondTest.state.snapshot.armed = true;
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  await globalThis.__secretPondTest.startFromSpace(repeatSpaceEvent);
  assert.strictEqual(repeatSpaceEvent.defaultPrevented, true);
  assert.strictEqual(repeatButtonBlurred, true);
  assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, false);
  assert.strictEqual(unexpectedStartPath, null);

  for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) {{
    const focusedControlSpaceEvent = {{
      code: "Space",
      repeat: true,
      defaultPrevented: false,
      preventDefault() {{
        this.defaultPrevented = true;
      }},
    }};
    globalThis.document.activeElement = {{ tagName }};
    await globalThis.__secretPondTest.startFromSpace(focusedControlSpaceEvent);
    assert.strictEqual(focusedControlSpaceEvent.defaultPrevented, false, tagName);
    assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, false, tagName);
    assert.strictEqual(unexpectedStartPath, null, tagName);
  }}
  globalThis.document.activeElement = null;

  let resolveStart = null;
  let stopSeenBeforeDiagnostics = null;
  const recordingPaths = [];
  globalThis.fetch = (path) => {{
    if (path.startsWith("/api/recording/")) recordingPaths.push(path);
    if (path === "/api/recording/start") {{
      return new Promise((resolve) => {{
        resolveStart = () => {{
          snapshot.is_recording = true;
          resolve({{
            ok: true,
            json: async () => ({{ state: snapshot }}),
          }});
        }};
      }});
    }}
    if (path === "/api/recording/stop") {{
      snapshot.is_recording = false;
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          state: snapshot,
          outcome: {{ accepted: false, reason: "too_short", duration_seconds: 0.2 }},
        }}),
      }});
    }}
    if (path === "/api/diagnostics") {{
      if (stopSeenBeforeDiagnostics === null) {{
        stopSeenBeforeDiagnostics = recordingPaths.includes("/api/recording/stop");
      }}
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  globalThis.__secretPondTest.state.spaceRecording = false;
  globalThis.__secretPondTest.state.recordingStopInFlight = false;
  globalThis.__secretPondTest.state.snapshot.armed = true;
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  const raceStartEvent = {{
    code: "Space",
    repeat: false,
    defaultPrevented: false,
    preventDefault() {{
      this.defaultPrevented = true;
    }},
  }};
  const raceStopEvent = {{
    code: "Space",
    defaultPrevented: false,
    preventDefault() {{
      this.defaultPrevented = true;
    }},
  }};
  const startPromise = globalThis.__secretPondTest.startFromSpace(raceStartEvent);
  assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, true);
  await globalThis.__secretPondTest.stopFromSpace(raceStopEvent);
  assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, false);
  assert.strictEqual(globalThis.__secretPondTest.state.recordingStopRequestedAfterStart, true);
  assert.deepStrictEqual(recordingPaths, ["/api/recording/start"]);
  resolveStart();
  await startPromise;
  assert.strictEqual(stopSeenBeforeDiagnostics, true);
  assert.deepStrictEqual(recordingPaths, ["/api/recording/start", "/api/recording/stop"]);
  assert.strictEqual(globalThis.__secretPondTest.state.snapshot.is_recording, false);

  let unexpectedSecondStartPath = null;
  globalThis.fetch = (path) => {{
    unexpectedSecondStartPath = path;
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  const secondStartWhilePendingEvent = {{
    code: "Space",
    repeat: false,
    defaultPrevented: false,
    preventDefault() {{
      this.defaultPrevented = true;
    }},
  }};
  globalThis.__secretPondTest.state.spaceRecording = false;
  globalThis.__secretPondTest.state.recordingStartInFlight = true;
  globalThis.__secretPondTest.state.recordingStopInFlight = false;
  globalThis.__secretPondTest.state.snapshot.armed = true;
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  await globalThis.__secretPondTest.startFromSpace(secondStartWhilePendingEvent);
  assert.strictEqual(secondStartWhilePendingEvent.defaultPrevented, true);
  assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, false);
  assert.strictEqual(unexpectedSecondStartPath, null);

  let resolveBlurStart = null;
  let blurStopSeenBeforeDiagnostics = null;
  const blurRacePaths = [];
  globalThis.fetch = (path) => {{
    if (path.startsWith("/api/recording/")) blurRacePaths.push(path);
    if (path === "/api/recording/start") {{
      return new Promise((resolve) => {{
        resolveBlurStart = () => {{
          snapshot.is_recording = true;
          resolve({{
            ok: true,
            json: async () => ({{ state: snapshot }}),
          }});
        }};
      }});
    }}
    if (path === "/api/recording/stop") {{
      snapshot.is_recording = false;
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          state: snapshot,
          outcome: {{ accepted: false, reason: "too_short", duration_seconds: 0.2 }},
        }}),
      }});
    }}
    if (path === "/api/diagnostics") {{
      if (blurStopSeenBeforeDiagnostics === null) {{
        blurStopSeenBeforeDiagnostics = blurRacePaths.includes("/api/recording/stop");
      }}
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  globalThis.__secretPondTest.state.spaceRecording = false;
  globalThis.__secretPondTest.state.recordingStartInFlight = false;
  globalThis.__secretPondTest.state.recordingStopInFlight = false;
  globalThis.__secretPondTest.state.snapshot.armed = true;
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  const blurStartEvent = {{
    code: "Space",
    repeat: false,
    defaultPrevented: false,
    preventDefault() {{
      this.defaultPrevented = true;
    }},
  }};
  const blurStartPromise = globalThis.__secretPondTest.startFromSpace(blurStartEvent);
  await globalThis.__secretPondTest.stopIfRecording();
  assert.strictEqual(globalThis.__secretPondTest.state.recordingStopRequestedAfterStart, true);
  assert.deepStrictEqual(blurRacePaths, ["/api/recording/start"]);
  resolveBlurStart();
  await blurStartPromise;
  assert.strictEqual(blurStopSeenBeforeDiagnostics, true);
  assert.deepStrictEqual(blurRacePaths, ["/api/recording/start", "/api/recording/stop"]);

  const blurStopPaths = [];
  globalThis.fetch = (path) => {{
    if (path.startsWith("/api/recording/")) blurStopPaths.push(path);
    if (path === "/api/recording/stop") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{
          state: snapshot,
          outcome: {{ accepted: false, reason: "too_short", duration_seconds: 0.1 }},
        }}),
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
  globalThis.__secretPondTest.state.spaceRecording = true;
  globalThis.__secretPondTest.state.snapshot.is_recording = false;
  globalThis.__secretPondTest.state.recordingStartInFlight = false;
  await globalThis.__secretPondTest.stopIfRecording();
  assert.deepStrictEqual(blurStopPaths, []);
  assert.strictEqual(globalThis.__secretPondTest.state.spaceRecording, false);

  const staleStopPaths = [];
  let staleStopStateRequested = false;
  globalThis.fetch = (path) => {{
    if (path.startsWith("/api/recording/")) staleStopPaths.push(path);
    if (path === "/api/recording/stop") {{
      snapshot.is_recording = false;
      return Promise.resolve({{
        ok: false,
        status: 409,
        json: async () => ({{ detail: "not recording" }}),
      }});
    }}
    if (path === "/api/state") {{
      staleStopStateRequested = true;
      return Promise.resolve({{
        ok: true,
        json: async () => snapshot,
      }});
    }}
    if (path === "/api/diagnostics") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ sources: [], events: {{ recent: [] }} }}),
      }});
    }}
    if (path === "/api/sources") {{
      return Promise.resolve({{
        ok: true,
        json: async () => ({{ categories: [] }}),
      }});
    }}
    throw new Error(`unexpected fetch ${{path}}`);
  }};
  elements.errorBanner.hidden = true;
  elements.errorBanner.textContent = "";
  elements.errorBadge.textContent = "오류 없음";
  globalThis.__secretPondTest.state.spaceRecording = false;
  globalThis.__secretPondTest.state.snapshot.is_recording = true;
  globalThis.__secretPondTest.state.recordingStartInFlight = false;
  await globalThis.__secretPondTest.stopIfRecording();
  assert.deepStrictEqual(staleStopPaths, ["/api/recording/stop"]);
  assert.strictEqual(staleStopStateRequested, true);
  assert.strictEqual(globalThis.__secretPondTest.state.recordingStopInFlight, false);
  assert.strictEqual(elements.errorBanner.hidden, true);
  assert.strictEqual(elements.errorBanner.textContent, "");
  assert.strictEqual(elements.errorBadge.textContent, "오류 없음");
  assert.notStrictEqual(elements.recordOutcomeStatus.textContent, "녹음 실패");

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


def test_api_diagnostics_reports_selected_library_sources(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    write_wav_atomic(
        paths.low_sources_dir / "library-low.wav",
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )
    settings = api_settings().model_copy(
        update={
            "sources": SourceSelectionSettings(
                low_path="data/sources/low/library-low.wav",
            )
        },
        deep=True,
    )
    client = create_test_client(tmp_path, settings=settings)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    sources = {source["id"]: source for source in response.json()["sources"]}
    assert sources["low"]["exists"] is True
    assert sources["low"]["path"] == "data/sources/low/library-low.wav"


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


def test_api_sources_lists_categories_and_selected_files(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    write_wav_atomic(
        paths.low_sources_dir / "library-low.wav",
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )
    settings = api_settings().model_copy(
        update={
            "sources": SourceSelectionSettings(
                low_path="data/sources/low/library-low.wav",
            )
        },
        deep=True,
    )
    client = create_test_client(tmp_path, settings=settings)

    response = client.get("/api/sources")

    assert response.status_code == 200
    categories = {category["id"]: category for category in response.json()["categories"]}
    assert set(categories) == {"low", "mid", "voice_raw", "voice_stack"}
    assert categories["low"]["selected_path"] == "data/sources/low/library-low.wav"
    assert categories["low"]["active_exists"] is True
    assert categories["low"]["legacy_size_bytes"] == 0
    assert categories["low"]["legacy_modified_at"] is None
    assert categories["low"]["required"] is True
    assert categories["voice_raw"]["required"] is False
    assert categories["low"]["files"][0]["path"] == "data/sources/low/library-low.wav"
    assert categories["low"]["files"][0]["active"] is True


def test_api_sources_marks_applied_files_when_draft_selection_differs(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    active_relative = "data/sources/low/applied-low.wav"
    draft_relative = "data/sources/low/draft-low.wav"
    for relative_path in (active_relative, draft_relative):
        write_wav_atomic(
            tmp_path / relative_path,
            AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
        )
    active_settings = api_settings().model_copy(
        update={"sources": SourceSelectionSettings(low_path=active_relative)},
        deep=True,
    )
    draft_settings = active_settings.model_copy(
        update={"sources": SourceSelectionSettings(low_path=draft_relative)},
        deep=True,
    )
    client = create_test_client(tmp_path, settings=active_settings)
    settings_state = SettingsState(active=active_settings, draft=draft_settings)
    SettingsStore(paths).save(settings_state)
    client.app.state.runtime.settings_state = settings_state

    response = client.get("/api/sources")

    assert response.status_code == 200
    categories = {category["id"]: category for category in response.json()["categories"]}
    files = {file["path"]: file for file in categories["low"]["files"]}
    assert files[active_relative]["active"] is False
    assert files[active_relative]["applied"] is True
    assert files[draft_relative]["active"] is True
    assert files[draft_relative]["applied"] is False


def test_api_sources_select_persists_draft_selection(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    write_wav_atomic(
        paths.mid_sources_dir / "library-mid.wav",
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )
    client = create_test_client(tmp_path)

    response = client.put(
        "/api/sources/mid/select",
        json={"path": "data/sources/mid/library-mid.wav"},
    )

    assert response.status_code == 200
    assert response.json()["settings"]["draft"]["sources"]["mid_path"] == (
        "data/sources/mid/library-mid.wav"
    )
    assert SettingsStore(paths).load().draft.sources.mid_path == (
        "data/sources/mid/library-mid.wav"
    )


def test_api_sources_select_patches_draft_inside_runtime_lock(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    write_wav_atomic(
        paths.mid_sources_dir / "library-mid.wav",
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )
    client = create_test_client(tmp_path)
    runtime = client.app.state.runtime
    settings_store = LockAwareSettingsStore(runtime.settings_store, runtime.operation_lock)
    runtime.settings_store = settings_store

    response = client.put(
        "/api/sources/mid/select",
        json={"path": "data/sources/mid/library-mid.wav"},
    )

    assert response.status_code == 200
    assert settings_store.patch_draft_owned_during_call is True
    assert response.json()["settings"]["draft"]["sources"]["mid_path"] == (
        "data/sources/mid/library-mid.wav"
    )


def test_api_sources_upload_writes_wav_to_category_directory(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    client = create_test_client(tmp_path)
    source = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000)
    source_path = tmp_path / "upload-source.wav"
    write_wav_atomic(source_path, source)

    response = client.post(
        "/api/sources/low/files",
        params={"filename": "uploaded-low.wav"},
        content=source_path.read_bytes(),
    )

    assert response.status_code == 201
    assert response.json()["file"]["path"] == "data/sources/low/uploaded-low.wav"
    assert (paths.low_sources_dir / "uploaded-low.wav").exists()


def test_api_sources_upload_can_persist_uploaded_file_as_draft_selection(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    client = create_test_client(tmp_path)
    source = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000)
    source_path = tmp_path / "upload-source.wav"
    write_wav_atomic(source_path, source)

    response = client.post(
        "/api/sources/low/files",
        params={"filename": "uploaded-low.wav", "select": "true"},
        content=source_path.read_bytes(),
    )

    assert response.status_code == 201
    assert response.json()["settings"]["draft"]["sources"]["low_path"] == (
        "data/sources/low/uploaded-low.wav"
    )
    assert response.json()["sources"]["categories"][0]["selected_path"] == (
        "data/sources/low/uploaded-low.wav"
    )
    assert SettingsStore(paths).load().draft.sources.low_path == (
        "data/sources/low/uploaded-low.wav"
    )


def test_api_sources_delete_rejects_active_file(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    active_path = paths.low_sources_dir / "active-low.wav"
    write_wav_atomic(
        active_path,
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )
    settings = api_settings().model_copy(
        update={
            "sources": SourceSelectionSettings(
                low_path="data/sources/low/active-low.wav",
            )
        },
        deep=True,
    )
    client = create_test_client(tmp_path, settings=settings)

    response = client.delete(
        "/api/sources/low/files",
        params={"path": "data/sources/low/active-low.wav"},
    )

    assert response.status_code == 409
    assert active_path.exists()


def test_api_sources_delete_removes_inactive_file(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    inactive_path = paths.low_sources_dir / "inactive-low.wav"
    write_wav_atomic(
        inactive_path,
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )
    client = create_test_client(tmp_path)

    response = client.delete(
        "/api/sources/low/files",
        params={"path": "data/sources/low/inactive-low.wav"},
    )

    assert response.status_code == 200
    assert inactive_path.exists() is False


def test_api_apply_and_restart_renders_selected_library_source(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    client = create_test_client(tmp_path, with_sources=True)
    paths.ensure_directories()
    selected_low = np.ones((8_000, 2), dtype=np.float32) * 0.4
    write_wav_atomic(
        paths.low_sources_dir / "selected-low.wav",
        AudioBuffer(samples=selected_low, sample_rate=8_000),
    )

    select_response = client.put(
        "/api/sources/low/select",
        json={"path": "data/sources/low/selected-low.wav"},
    )
    apply_response = client.post("/api/settings/apply-and-restart")

    assert select_response.status_code == 200
    assert apply_response.status_code == 200
    assert apply_response.json()["settings"]["active"]["sources"]["low_path"] == (
        "data/sources/low/selected-low.wav"
    )
    rendered = read_wav(paths.low_playback)
    assert float(np.max(np.abs(rendered.samples))) > 0.05


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
    assert payload["settings"]["change"] == {
        "runtime_config_changed": False,
        "changed_runtime_fields": [],
        "changed_sections": [],
        "runtime_config_fields": RUNTIME_CONFIG_FIELDS,
    }


@pytest.mark.parametrize(
    ("corrupt_durable_state", "reason"),
    [
        (corrupt_settings_json, "settings file contains invalid JSON"),
        (corrupt_participant_count_json, "participant count file is not valid JSON"),
    ],
)
def test_api_state_maps_unreadable_durable_state_to_503(
    tmp_path: Path,
    corrupt_durable_state,
    reason: str,
) -> None:
    paths = ProjectPaths(tmp_path)
    client = create_test_client(tmp_path, raise_server_exceptions=False)
    corrupt_durable_state(paths)

    response = client.get("/api/state")

    assert response.status_code == 503
    assert response.json()["detail"] == f"state is unavailable: {reason}"


@pytest.mark.parametrize(
    "path",
    [
        "/api/settings",
        "/api/sources",
        "/api/diagnostics",
        "/api/devices",
    ],
)
def test_api_settings_backed_reads_map_unreadable_settings_to_503(
    tmp_path: Path,
    path: str,
) -> None:
    paths = ProjectPaths(tmp_path)
    client = create_test_client(tmp_path, raise_server_exceptions=False)
    corrupt_settings_json(paths)

    response = client.get(path)

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "settings are unavailable: settings file contains invalid JSON"
    )


def test_api_settings_payload_reports_change_plan(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    assert response.status_code == 200
    assert response.json()["settings"]["change"] == {
        "runtime_config_changed": False,
        "changed_runtime_fields": [],
        "changed_sections": ["layers"],
        "runtime_config_fields": RUNTIME_CONFIG_FIELDS,
    }
    state = client.get("/api/state").json()
    assert state["settings"]["change"] == {
        "runtime_config_changed": False,
        "changed_runtime_fields": [],
        "changed_sections": ["layers"],
        "runtime_config_fields": RUNTIME_CONFIG_FIELDS,
    }


def test_api_settings_payload_reports_runtime_config_change_plan(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.put(
        "/api/settings/draft",
        json=draft_with_sample_rate(16_000),
    )

    assert response.status_code == 200
    assert response.json()["settings"]["change"] == {
        "runtime_config_changed": True,
        "changed_runtime_fields": ["audio.sample_rate"],
        "changed_sections": ["audio"],
        "runtime_config_fields": RUNTIME_CONFIG_FIELDS,
    }


def test_ws_state_sends_initial_runtime_state(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()

    assert payload["armed"] is False
    assert payload["is_recording"] is False
    assert payload["participant_count"] == 0
    assert payload["playback"]["output_running"] is False
    assert payload["settings"]["active"]["voice_stack"]["loop_seconds"] == 1


@pytest.mark.parametrize(
    ("corrupt_durable_state", "reason"),
    [
        (corrupt_settings_json, "settings file contains invalid JSON"),
        (corrupt_participant_count_json, "participant count file is not valid JSON"),
    ],
)
def test_ws_state_sends_state_unavailable_error_without_closing(
    tmp_path: Path,
    corrupt_durable_state,
    reason: str,
) -> None:
    paths = ProjectPaths(tmp_path)
    client = create_test_client(tmp_path)
    corrupt_durable_state(paths)

    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()

    assert payload == {
        "error": {
            "code": "state_unavailable",
            "message": f"state is unavailable: {reason}",
        },
    }


def test_ws_state_disconnect_stops_active_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    with client.websocket_connect("/ws/state") as websocket:
        assert websocket.receive_json()["is_recording"] is True

    state = wait_for_state(
        client,
        lambda payload: payload["is_recording"] is False,
        timeout_seconds=8.0,
    )
    assert state["is_recording"] is False
    assert state["participant_count"] == 1


def test_ws_state_disconnect_refreshes_running_voice_playback_layer(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        with_sources=True,
        output=output,
        settings=api_settings_with_voice_only_layers(),
    )
    runtime = client.app.state.runtime
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    before = runtime.player.next_block(8_000)

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    with client.websocket_connect("/ws/state") as websocket:
        assert websocket.receive_json()["is_recording"] is True

    after = runtime.player.next_block(8_000)

    assert output.is_running is True
    assert float(np.max(np.abs(before.samples))) == pytest.approx(0.0)
    assert float(np.max(np.abs(after.samples))) > 0.00001


def test_ws_state_polls_recording_auto_stop_before_sending_state(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.post("/api/input/arm")
    client.post("/api/recording/start")
    client.app.state.runtime.controller._recording_started_at -= 2.0

    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()

    assert payload["is_recording"] is False
    assert payload["participant_count"] == 1


def test_ws_state_auto_stop_refreshes_running_voice_playback_layer(tmp_path: Path) -> None:
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        with_sources=True,
        output=output,
        settings=api_settings_with_voice_only_layers(),
    )
    runtime = client.app.state.runtime
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    before = runtime.player.next_block(8_000)

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    runtime.controller._recording_started_at -= 2.0
    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()
    after = runtime.player.next_block(8_000)

    assert payload["is_recording"] is False
    assert output.is_running is True
    assert float(np.max(np.abs(before.samples))) == pytest.approx(0.0)
    assert float(np.max(np.abs(after.samples))) > 0.00001


def test_ws_state_auto_stop_rolls_back_voice_stack_when_voice_render_fails(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path)
    paths = ProjectPaths(tmp_path)
    runtime = client.app.state.runtime
    before_raw = paths.voice_stack_raw.read_bytes()
    before_manifest = json.loads(paths.voice_manifest.read_text(encoding="utf-8"))
    runtime.controller._renderer = FailingLayerRenderer(  # noqa: SLF001
        runtime.renderer,
        FileNotFoundError("voice missing"),
    )

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    runtime.controller._recording_started_at -= 2.0
    with client.websocket_connect("/ws/state") as websocket:
        payload = websocket.receive_json()

    assert payload["is_recording"] is False
    assert paths.voice_stack_raw.read_bytes() == before_raw
    assert json.loads(paths.voice_manifest.read_text(encoding="utf-8")) == before_manifest
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.voice_stack_sources_dir.glob("*.wav")) == []
    assert runtime.controller.settings.sources.voice_raw_path is None
    assert runtime.controller.settings.sources.voice_stack_path is None
    stored = SettingsStore(paths).load()
    assert stored.active.sources.voice_raw_path is None
    assert stored.active.sources.voice_stack_path is None


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
    assert payload["selected_input_device"]["host_api_name"] == "Core Audio"
    assert payload["selected_output_device"]["host_api_name"] == "WASAPI"
    assert payload["warnings"] == []


def test_api_devices_maps_device_registry_failure_to_503(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, device_registry=FailingDeviceRegistry())

    response = client.get("/api/devices")

    assert response.status_code == 503
    assert "device stack unavailable" in response.json()["detail"]


def test_api_devices_update_applies_devices_immediately(tmp_path: Path) -> None:
    recorder = DeviceAwareFakeRecorder(recorder_take())
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        recorder=recorder,
        output=output,
        device_registry=fake_device_registry(),
    )

    response = client.put(
        "/api/devices",
        json={"input_device_id": "mic-2", "output_device_id": "speaker-2"},
    )

    assert response.status_code == 200
    payload = response.json()
    settings = payload["state"]["settings"]
    assert settings["active"]["devices"]["input_device_id"] == "mic-2"
    assert settings["active"]["devices"]["output_device_id"] == "speaker-2"
    assert settings["draft"]["devices"]["input_device_id"] == "mic-2"
    assert settings["draft"]["devices"]["output_device_id"] == "speaker-2"
    assert payload["devices"]["selected_input_device"]["id"] == "mic-2"
    assert payload["devices"]["selected_output_device"]["id"] == "speaker-2"
    assert recorder.device_id == "mic-2"
    assert output.device_id == "speaker-2"
    runtime = client.app.state.runtime
    assert runtime.controller.settings.devices.input_device_id == "mic-2"
    stored = SettingsStore(ProjectPaths(tmp_path)).load()
    assert stored.active.devices.input_device_id == "mic-2"
    assert stored.draft.devices.output_device_id == "speaker-2"


def test_api_devices_update_validates_only_changed_device_fields(tmp_path: Path) -> None:
    settings = api_settings().model_copy(
        update={
            "devices": DeviceSettings(
                input_device_id="missing-mic",
                output_device_id=None,
            )
        },
        deep=True,
    )
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        settings=settings,
        output=output,
        device_registry=fake_device_registry(),
    )

    response = client.put("/api/devices", json={"output_device_id": "speaker-2"})

    assert response.status_code == 200
    devices = response.json()["state"]["settings"]["active"]["devices"]
    assert devices["input_device_id"] == "missing-mic"
    assert devices["output_device_id"] == "speaker-2"
    assert output.device_id == "speaker-2"


def test_api_devices_update_restarts_running_output_on_output_device_change(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        output=output,
        device_registry=fake_device_registry(),
    )
    start_response = client.post("/api/playback/start")

    response = client.put("/api/devices", json={"output_device_id": "speaker-2"})

    assert start_response.status_code == 200
    assert response.status_code == 200
    assert output.stop_calls == 1
    assert output.start_calls == 2
    assert output.is_running is True
    assert output.device_id == "speaker-2"
    assert response.json()["state"]["playback"]["output_running"] is True


def test_api_devices_update_rolls_back_runtime_devices_when_save_fails(
    tmp_path: Path,
) -> None:
    recorder = DeviceAwareFakeRecorder(recorder_take())
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        recorder=recorder,
        output=output,
        device_registry=fake_device_registry(),
        raise_server_exceptions=False,
    )
    runtime = client.app.state.runtime
    start_response = client.post("/api/playback/start")
    runtime.settings_store = FailingSaveSettingsStore(
        runtime.settings_store,
        OSError("settings save failed"),
    )

    response = client.put(
        "/api/devices",
        json={"input_device_id": "mic-2", "output_device_id": "speaker-2"},
    )

    assert start_response.status_code == 200
    assert response.status_code == 409
    assert "settings save failed" in response.json()["detail"]
    assert recorder.device_id is None
    assert output.device_id is None
    assert output.is_running is True
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["devices"]["input_device_id"] is None
    assert state["settings"]["active"]["devices"]["output_device_id"] is None
    stored = SettingsStore(ProjectPaths(tmp_path)).load()
    assert stored.active.devices.input_device_id is None
    assert stored.draft.devices.output_device_id is None


def test_api_devices_update_blocks_input_change_while_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, device_registry=fake_device_registry())
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    response = client.put("/api/devices", json={"input_device_id": "mic-2"})

    assert response.status_code == 409
    assert "recording" in response.json()["detail"]
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["devices"]["input_device_id"] is None


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


def test_api_recording_stop_maps_voice_render_failures_to_conflict(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, raise_server_exceptions=False)
    runtime = client.app.state.runtime
    runtime.controller._renderer = FailingLayerRenderer(  # noqa: SLF001
        runtime.renderer,
        FileNotFoundError("voice missing"),
    )

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    response = client.post("/api/recording/stop")

    assert response.status_code == 409
    assert "voice missing" in response.json()["detail"]
    state = client.get("/api/state").json()
    assert state["is_recording"] is False
    assert state["last_error"] == "voice missing"


def test_api_recording_stop_rolls_back_voice_stack_when_voice_render_fails(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, raise_server_exceptions=False)
    paths = ProjectPaths(tmp_path)
    runtime = client.app.state.runtime
    before_raw = paths.voice_stack_raw.read_bytes()
    before_manifest = json.loads(paths.voice_manifest.read_text(encoding="utf-8"))
    runtime.controller._renderer = FailingLayerRenderer(  # noqa: SLF001
        runtime.renderer,
        FileNotFoundError("voice missing"),
    )

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    response = client.post("/api/recording/stop")

    assert response.status_code == 409
    assert paths.voice_stack_raw.read_bytes() == before_raw
    assert json.loads(paths.voice_manifest.read_text(encoding="utf-8")) == before_manifest
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.voice_stack_sources_dir.glob("*.wav")) == []
    assert runtime.controller.settings.sources.voice_raw_path is None
    assert runtime.controller.settings.sources.voice_stack_path is None
    stored = SettingsStore(paths).load()
    assert stored.active.sources.voice_raw_path is None
    assert stored.active.sources.voice_stack_path is None


def test_api_recording_acceptance_refreshes_running_voice_playback_layer(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        with_sources=True,
        output=output,
        settings=api_settings_with_voice_only_layers(),
    )
    runtime = client.app.state.runtime
    client.post("/api/settings/apply-and-restart")
    start_response = client.post("/api/playback/start")
    before = runtime.player.next_block(8_000)

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    stop_response = client.post("/api/recording/stop")
    after = runtime.player.next_block(8_000)

    assert start_response.status_code == 200
    assert start_response.json()["state"]["playback"]["output_running"] is True
    assert float(np.max(np.abs(before.samples))) == pytest.approx(0.0)
    assert stop_response.status_code == 200
    assert stop_response.json()["outcome"]["accepted"] is True
    assert stop_response.json()["state"]["playback"]["output_running"] is True
    assert float(np.max(np.abs(after.samples))) > 0.00001


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


def test_api_settings_draft_rejects_device_updates(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.put(
        "/api/settings/draft",
        json=draft_with_devices(input_device_id="mic-2", output_device_id="speaker-2"),
    )

    assert response.status_code == 422
    assert "System panel" in response.json()["detail"]
    settings = client.get("/api/settings").json()["settings"]
    assert settings["active"]["devices"]["input_device_id"] is None
    assert settings["active"]["devices"]["output_device_id"] is None
    assert settings["draft"]["devices"]["input_device_id"] is None
    assert settings["draft"]["devices"]["output_device_id"] is None


def test_api_settings_reset_discards_draft_changes(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/reset")

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["active"]["layers"]["voice"]["volume_db"] == -18.0
    assert settings["draft"]["layers"]["voice"]["volume_db"] == -18.0


def test_api_settings_reset_draft_alias_discards_draft_changes(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/reset-draft")

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


def test_api_settings_reset_draft_alias_is_blocked_while_recording(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    response = client.post("/api/settings/reset-draft")

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


def test_api_settings_reset_draft_alias_is_blocked_during_apply_and_restart(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    renderer = BlockingStageRenderer(runtime.renderer)
    runtime.renderer = renderer
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        apply_future = executor.submit(client.post, "/api/settings/apply-and-restart")
        assert renderer.entered.wait(timeout=2)
        reset_future = executor.submit(client.post, "/api/settings/reset-draft")
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


def test_api_settings_apply_and_restart_prepares_voice_stack_loop_length(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_voice_stack_loop_seconds(2))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["active"]["voice_stack"]["loop_seconds"] == 2
    raw = read_wav(ProjectPaths(tmp_path).voice_stack_raw)
    assert raw.sample_rate == 8_000
    assert raw.frames == 16_000


def test_recording_acceptance_persists_timestamped_voice_stack_selection(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path)
    paths = ProjectPaths(tmp_path)

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    response = client.post("/api/recording/stop")

    assert response.status_code == 200
    stored = SettingsStore(paths).load()
    selected_raw = stored.active.sources.voice_raw_path
    selected_stack = stored.active.sources.voice_stack_path
    assert selected_raw is not None
    assert selected_raw.startswith("data/sources/voice/raw/")
    assert selected_raw.endswith(".wav")
    assert (tmp_path / selected_raw).exists()
    assert selected_stack is not None
    assert selected_stack.startswith("data/sources/voice/stack/")
    assert selected_stack.endswith(".wav")
    assert (tmp_path / selected_stack).exists()
    assert response.json()["state"]["settings"]["active"]["sources"]["voice_raw_path"] == (
        selected_raw
    )
    assert response.json()["state"]["settings"]["active"]["sources"]["voice_stack_path"] == (
        selected_stack
    )


def test_api_first_live_recording_creates_sixty_second_stack_and_refreshes_playback(
    tmp_path: Path,
) -> None:
    settings = api_settings_for_sixty_second_voice_loop(mode="live_ephemeral")
    output = FakeOutput()
    client = create_test_client(
        tmp_path,
        with_sources=True,
        recorder=FakeRecorder(twenty_second_voice_take()),
        output=output,
        settings=settings,
    )
    paths = ProjectPaths(tmp_path)
    runtime = client.app.state.runtime

    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.voice_stack_sources_dir.glob("*.wav")) == []
    apply_response = client.post("/api/settings/apply-and-restart")
    start_response = client.post("/api/playback/start")
    before = runtime.player.next_block(8_000)

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    response = client.post("/api/recording/stop")
    after = runtime.player.next_block(8_000)

    assert apply_response.status_code == 200
    assert start_response.status_code == 200
    assert start_response.json()["state"]["playback"]["output_running"] is True
    assert float(np.max(np.abs(before.samples))) == pytest.approx(0.0)
    assert response.status_code == 200
    assert response.json()["outcome"]["accepted"] is True
    assert response.json()["state"]["playback"]["output_running"] is True
    assert output.is_running is True
    stored = SettingsStore(paths).load()
    selected_raw = stored.active.sources.voice_raw_path
    selected_stack = stored.active.sources.voice_stack_path
    assert selected_raw is not None
    assert selected_stack is not None
    assert selected_raw.startswith("data/sources/voice/raw/")
    assert selected_stack.startswith("data/sources/voice/stack/")
    assert_timestamped_voice_filename(selected_raw, "-raw.wav")
    assert_timestamped_voice_filename(selected_stack, "-stack.wav")
    assert len(list(paths.voice_raw_sources_dir.glob("*.wav"))) == 1
    assert len(list(paths.voice_stack_sources_dir.glob("*.wav"))) == 1

    stack = read_wav(tmp_path / selected_stack)
    rendered = read_wav(paths.voice_playback)
    loaded_voice = runtime.player.snapshot().layers["voice"]
    assert stack.frames == 60 * 8_000
    assert rendered.frames == 60 * 8_000
    assert loaded_voice.frames == 60 * 8_000
    np.testing.assert_allclose(
        stack.samples[: 20 * 8_000],
        stack.samples[20 * 8_000 : 40 * 8_000],
        atol=1e-4,
    )
    np.testing.assert_allclose(
        stack.samples[: 20 * 8_000],
        stack.samples[40 * 8_000 :],
        atol=1e-4,
    )
    np.testing.assert_allclose(loaded_voice.samples, rendered.samples, atol=1e-4)
    assert float(np.max(np.abs(after.samples))) > 0.00001


def test_api_test_library_recording_persists_timestamped_raw_and_accepted_clip(
    tmp_path: Path,
) -> None:
    settings = api_settings_for_sixty_second_voice_loop(mode="test_library")
    client = create_test_client(
        tmp_path,
        with_sources=True,
        recorder=FakeRecorder(twenty_second_voice_take()),
        settings=settings,
    )
    paths = ProjectPaths(tmp_path)

    client.post("/api/input/arm")
    client.post("/api/recording/start")
    response = client.post("/api/recording/stop")

    assert response.status_code == 200
    stored = SettingsStore(paths).load()
    selected_raw = stored.active.sources.voice_raw_path
    selected_stack = stored.active.sources.voice_stack_path
    assert selected_raw is not None
    assert selected_stack is not None
    assert selected_raw.startswith("data/sources/voice/raw/")
    assert selected_stack.startswith("data/sources/voice/stack/")
    assert_timestamped_voice_filename(selected_raw, "-raw.wav")
    assert_timestamped_voice_filename(selected_stack, "-stack.wav")
    assert (tmp_path / selected_raw).exists()
    assert (tmp_path / selected_stack).exists()
    manifest = json.loads(paths.voice_manifest.read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 1
    entry = manifest["entries"][0]
    assert entry["source_mode"] == "test_library"
    assert entry["accepted_clip_path"].startswith("data/processed/accepted/")
    assert (tmp_path / entry["accepted_clip_path"]).exists()


def test_api_settings_apply_and_restart_restores_voice_stack_raw_after_render_failure(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=False)
    paths = ProjectPaths(tmp_path)
    before_raw = paths.voice_stack_raw.read_bytes()
    client.put("/api/settings/draft", json=draft_with_voice_stack_loop_seconds(2))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    assert paths.voice_stack_raw.read_bytes() == before_raw
    state = client.get("/api/state").json()
    assert state["settings"]["active"]["voice_stack"]["loop_seconds"] == 1


def test_api_settings_apply_and_restart_logs_success_event(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    events = events_by_type(client, "settings.applied")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["changed_sections"] == ["layers"]
    assert payload["runtime_config_changed"] is False
    assert payload["was_output_running"] is False
    assert payload["output_running"] is False


def test_api_settings_apply_alias_renders_layers_and_starts_player(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["active"]["layers"]["voice"]["volume_db"] == -9.0
    assert payload["settings"]["draft"]["layers"]["voice"]["volume_db"] == -9.0
    assert payload["state"]["playback"]["is_playing"] is True
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


def test_api_settings_apply_alias_is_blocked_while_recording(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))
    client.post("/api/input/arm")
    client.post("/api/recording/start")

    response = client.post("/api/settings/apply")

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


def test_api_playback_start_and_stop_log_events(tmp_path: Path) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")

    client.post("/api/playback/start")
    client.post("/api/playback/stop")

    started_events = events_by_type(client, "playback.started")
    stopped_events = events_by_type(client, "playback.stopped")
    assert len(started_events) == 1
    assert started_events[0]["payload"] == {
        "frame_cursor": 0,
        "output_running": True,
    }
    assert len(stopped_events) == 1
    assert stopped_events[0]["payload"] == {
        "frame_cursor": 0,
        "output_running": False,
    }


def test_api_playback_restart_requires_running_output(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.post("/api/settings/apply-and-restart")

    response = client.post("/api/playback/restart")

    assert response.status_code == 409
    assert "running" in response.json()["detail"]


def test_api_playback_restart_precondition_failure_logs_event(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    client.post("/api/settings/apply-and-restart")

    response = client.post("/api/playback/restart")

    assert response.status_code == 409
    events = events_by_type(client, "playback.restart_failed")
    assert len(events) == 1
    assert events[0]["payload"] == {
        "error": "output must be running before restart",
        "frame_cursor": 0,
        "output_running": False,
    }


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


def test_api_playback_restart_logs_success_event(tmp_path: Path) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    client.app.state.runtime.player.next_block(10)

    response = client.post("/api/playback/restart")

    assert response.status_code == 200
    events = events_by_type(client, "playback.restarted")
    assert len(events) == 1
    assert events[0]["payload"] == {
        "frame_cursor": 0,
        "output_running": True,
    }


def test_api_playback_start_failure_logs_event(tmp_path: Path) -> None:
    output = FakeOutput(fail_start=ValueError("rendered layers must be loaded before playback"))
    client = create_test_client(tmp_path, output=output)

    response = client.post("/api/playback/start")

    assert response.status_code == 409
    events = events_by_type(client, "playback.start_failed")
    assert len(events) == 1
    assert events[0]["payload"] == {
        "error": "rendered layers must be loaded before playback",
        "frame_cursor": 0,
        "output_running": False,
    }


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


def test_api_playback_restart_failure_logs_final_rollback_state(
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
    events = events_by_type(client, "playback.restart_failed")
    assert len(events) == 1
    assert events[0]["payload"] == {
        "error": "restart failed",
        "frame_cursor": 10,
        "output_running": True,
    }


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


def test_api_settings_apply_and_restart_logs_failure_event_after_rollback(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    applied_before_failure = len(events_by_type(client, "settings.applied"))
    runtime = client.app.state.runtime
    runtime.renderer = FailingStageRenderer(runtime.renderer, FileNotFoundError("low missing"))
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    events = events_by_type(client, "settings.apply_failed")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["error"] == "low missing"
    assert payload["was_output_running"] is True
    assert payload["output_running"] is True
    assert payload["output_restore_attempted"] is True
    assert len(events_by_type(client, "settings.applied")) == applied_before_failure


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
    events = events_by_type(client, "settings.apply_failed")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["error"] == "settings save failed"
    assert payload["was_output_running"] is True
    assert payload["output_running"] is True
    assert payload["output_restore_attempted"] is True


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


def test_api_settings_apply_logs_runtime_config_rejection(tmp_path: Path) -> None:
    output = FakeOutput()
    output.is_running = True
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.put("/api/settings/draft", json=draft_with_sample_rate(16_000))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 409
    events = events_by_type(client, "settings.apply_rejected")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["runtime_config_changed"] is True
    assert payload["changed_runtime_fields"] == ["audio.sample_rate"]
    assert "restart" in payload["reason"]
    assert payload["was_output_running"] is True
    assert payload["output_running"] is True


def test_api_settings_apply_event_log_failure_does_not_mask_success(
    tmp_path: Path,
) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    runtime.logger = FailingEventLogger(runtime.logger)
    client.put("/api/settings/draft", json=draft_with_voice_volume(-9.0))

    response = client.post("/api/settings/apply-and-restart")

    assert response.status_code == 200
    assert response.json()["settings"]["active"]["layers"]["voice"]["volume_db"] == -9.0


def test_api_settings_apply_alias_rejects_runtime_config_changes_without_touching_output(
    tmp_path: Path,
) -> None:
    output = FakeOutput()
    output.is_running = True
    client = create_test_client(tmp_path, with_sources=True, output=output)
    client.put("/api/settings/draft", json=draft_with_sample_rate(16_000))

    response = client.post("/api/settings/apply")

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
