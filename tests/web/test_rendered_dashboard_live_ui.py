from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "src" / "secret_pond" / "web" / "static"
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def test_live_playback_dashboard_renders_in_desktop_viewport() -> None:
    chrome = _chrome_binary()
    if chrome is None:
        pytest.skip("Google Chrome or Chromium is required for rendered dashboard verification")

    with tempfile.TemporaryDirectory(prefix="secret-pond-rendered-ui-") as temp_dir:
        dashboard_path = _write_rendered_dashboard(Path(temp_dir))
        with tempfile.TemporaryDirectory(prefix="secret-pond-chrome-") as profile_dir:
            remote_debugging_port = _free_port()
            process = subprocess.Popen(
                [
                    chrome,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={profile_dir}",
                    f"--remote-debugging-port={remote_debugging_port}",
                    "--window-size=1440,1000",
                    dashboard_path.as_uri(),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            try:
                page = _connect_to_first_page(remote_debugging_port)
                page.send("Runtime.enable")
                rendered = _record_desktop_behavior_notes(page.wait_for_live_dashboard())
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    assert rendered["viewportWidth"] == 1440
    assert rendered["bodyWidth"] <= rendered["viewportWidth"]
    assert rendered["applyModeSummary"].startswith("즉시 반영")
    assert rendered["livePressed"] == "true"
    assert rendered["stablePressed"] == "false"
    assert rendered["liveDetailsText"] == (
        "적용 범위 즉시 반영: 볼륨, 음소거, 위치 이동, EQ, Voice Raw 미리듣기 처리 "
        "Apply and Restart: 루프 길이, 샘플레이트, 출력 장치, 소스 파일 선택"
    )
    assert rendered["seekDisabled"] is False
    assert rendered["seekMax"] == "60"
    assert rendered["seekValue"] == "30"
    assert rendered["positionText"] == "30.0s"
    assert rendered["durationText"] == "60.0s"
    assert rendered["progressWidth"] == "50%"
    assert rendered["outputSummary"] == (
        "Live 전환 · 새 녹음은 준비되면 목소리 레이어만 부드럽게 전환됩니다."
    )
    assert rendered["transitionBadge"].startswith("Live Transition")
    assert rendered["timelineRect"]["width"] > 260
    assert rendered["seekRect"]["width"] > 260
    assert rendered["desktopBehaviorNotes"] == [
        "desktop viewport 1440px rendered without horizontal overflow",
        "Live mode segment is selected and the seek control is enabled",
        "timeline and seek controls remain wide enough for compact desktop operation",
        "loop progress renders at 50% for the 30.0s / 60.0s fixture",
    ]


def test_rendered_dashboard_verification_output_records_desktop_behavior_notes() -> None:
    output = _record_desktop_behavior_notes(
        {
            "viewportWidth": 1440,
            "bodyWidth": 1440,
            "timelineRect": {"width": 720},
            "seekRect": {"width": 710},
            "livePressed": "true",
            "seekDisabled": False,
            "progressWidth": "50%",
        }
    )

    assert output["desktopBehaviorNotes"] == [
        "desktop viewport 1440px rendered without horizontal overflow",
        "Live mode segment is selected and the seek control is enabled",
        "timeline and seek controls remain wide enough for compact desktop operation",
        "loop progress renders at 50% for the 30.0s / 60.0s fixture",
    ]


def _record_desktop_behavior_notes(output: dict[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    viewport_width = int(output.get("viewportWidth") or 0)
    body_width = int(output.get("bodyWidth") or 0)
    timeline_width = float((output.get("timelineRect") or {}).get("width") or 0)
    seek_width = float((output.get("seekRect") or {}).get("width") or 0)

    if viewport_width >= 1024 and body_width <= viewport_width:
        notes.append(f"desktop viewport {viewport_width}px rendered without horizontal overflow")
    if output.get("livePressed") == "true" and output.get("seekDisabled") is False:
        notes.append("Live mode segment is selected and the seek control is enabled")
    if timeline_width > 260 and seek_width > 260:
        notes.append("timeline and seek controls remain wide enough for compact desktop operation")
    if output.get("progressWidth") == "50%":
        notes.append("loop progress renders at 50% for the 30.0s / 60.0s fixture")

    return {**output, "desktopBehaviorNotes": notes}


def _chrome_binary() -> str | None:
    for command in ("google-chrome", "chromium", "chrome"):
        binary = shutil.which(command)
        if binary:
            return binary
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("socket bind permission is required for rendered dashboard verification")
        return int(sock.getsockname()[1])


def _write_rendered_dashboard(temp_dir: Path) -> Path:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")
    app_script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    bootstrap = f"""
<script>
const apiPayloads = {json.dumps(_api_payloads())};
window.WebSocket = class {{
  constructor() {{
    queueMicrotask(() => this.onerror?.(new Event("error")));
  }}
  addEventListener() {{}}
  close() {{}}
}};
window.fetch = async (url) => {{
  const path = new URL(url, window.location.href).pathname;
  if (!Object.hasOwn(apiPayloads, path)) {{
    return new Response(JSON.stringify({{ error: `Unhandled test API path: ${{path}}` }}), {{
      status: 404,
      headers: {{ "Content-Type": "application/json" }},
    }});
  }}
  return new Response(JSON.stringify(apiPayloads[path]), {{
    status: 200,
    headers: {{ "Content-Type": "application/json" }},
  }});
}};
</script>
"""
    rendered = html.replace(
        '<link rel="stylesheet" href="/static/styles.css" />',
        f"<style>\n{styles}\n</style>",
    )
    rendered = rendered.replace(
        '<script src="/static/app.js" defer></script>',
        f"{bootstrap}\n<script>\n{app_script}\n</script>",
    )
    path = temp_dir / "rendered-live-dashboard.html"
    path.write_text(rendered, encoding="utf-8")
    return path


def _api_payloads() -> dict[str, Any]:
    return {
        "/api/state": _live_state_payload(),
        "/api/devices": {
            "input_devices": [
                {
                    "id": "mic-1",
                    "name": "Mic 1",
                    "host_api_name": "CoreAudio",
                    "kind": "input",
                }
            ],
            "output_devices": [
                {
                    "id": "speaker-1",
                    "name": "Speaker 1",
                    "host_api_name": "CoreAudio",
                    "kind": "output",
                }
            ],
            "warnings": [],
        },
        "/api/diagnostics": {
            "sources": [
                {
                    "label": "Low",
                    "path": "data/sources/low/low.wav",
                    "exists": True,
                    "size_bytes": 4096,
                    "modified_at": "2026-06-06T00:00:00+09:00",
                }
            ],
            "events": {"recent": [], "error": None},
        },
        "/api/sources": {
            "categories": [
                {
                    "id": "voice_raw",
                    "active_path": "data/sources/voice/raw/VR0606_120000.wav",
                    "active_exists": True,
                    "required": False,
                    "files": [
                        {
                            "name": "VR0606_120000.wav",
                            "path": "data/sources/voice/raw/VR0606_120000.wav",
                            "size_bytes": 4096,
                            "modified_at": "2026-06-06T12:00:00+09:00",
                        }
                    ],
                }
            ]
        },
    }


def _live_state_payload() -> dict[str, Any]:
    settings = {
        "voice_stack": {"mode": "live_ephemeral", "loop_seconds": 60, "transition_seconds": 4},
        "input_control": {
            "minimum_recording_seconds": 3,
            "maximum_recording_seconds": 120,
        },
        "recording": {
            "gain_db": 0,
            "normalize_peak": 0.35,
            "highpass_hz": 90,
            "lowpass_hz": 8000,
            "presence_gain_db": -3,
            "reverb_mix": 0.25,
            "delay_mix": 0,
            "fade_ms": 50,
        },
        "audio": {"sample_rate": 48000, "channels": 2, "loop_seconds": 60},
        "devices": {"input_device_id": "mic-1", "output_device_id": "speaker-1"},
        "playback": {"auto_start": True, "apply_mode": "live", "master_volume_db": -9},
        "sources": {
            "low_path": "data/sources/low/low.wav",
            "mid_path": "data/sources/mid/mid.wav",
            "voice_raw_path": "data/sources/voice/raw/VR0606_120000.wav",
            "voice_stack_path": "data/sources/voice/stack/VS0606_120000.wav",
        },
        "layers": {
            "low": {"enabled": True, "volume_db": -12, "eq": _eq()},
            "mid": {"enabled": True, "volume_db": -15, "eq": _eq()},
            "voice": {"enabled": True, "volume_db": -6, "eq": _eq()},
        },
    }
    return {
        "state_revision": 1,
        "state_epoch": 1,
        "settings": {
            "active": settings,
            "draft": settings,
            "change": {
                "changed_sections": [],
                "requires_restart": False,
                "runtime_config_changed": False,
                "runtime_config_fields": [
                    "audio.sample_rate",
                    "audio.channels",
                    "devices.input_device_id",
                    "devices.output_device_id",
                ],
                "live_preview_reprocessable_fields": [],
                "live_preview_reprocessable_field_names": [
                    "recording.gain_db",
                    "recording.normalize_peak",
                    "recording.highpass_hz",
                    "recording.lowpass_hz",
                    "recording.presence_gain_db",
                    "recording.reverb_mix",
                    "recording.delay_mix",
                    "recording.fade_ms",
                ],
            },
        },
        "playback": {
            "apply_mode": "live",
            "output_running": True,
            "rendered_cache_ready": False,
            "frame_cursor": 1_440_000,
            "position_seconds": 30,
            "duration_seconds": 60,
            "progress": 0.5,
            "active_voice_transition_target_id": "data/sources/voice/stack/VS0606_120000.wav",
            "playback_session_id": 7,
            "voice_raw_preview_path": None,
            "transition_warning": None,
            "output_latest_status": "running",
            "output_latest_error": None,
            "live": {
                "enabled": True,
                "volume_applies_immediately": True,
                "mute_applies_immediately": True,
                "seek_applies_immediately": True,
                "voice_stack_transition_applies_immediately": True,
                "voice_raw_preview_treatment_applies_immediately": True,
                "eq_applies_immediately": True,
                "excluded_apply_flow": [
                    "audio.loop_seconds",
                    "audio.sample_rate",
                    "devices.output_device_id",
                    "sources",
                ],
                "eq_source_contract": "eq_free",
            },
        },
        "armed": False,
        "is_recording": False,
        "recording_elapsed_seconds": 0,
        "recording_remaining_seconds": 120,
        "participant_count": 0,
        "operator_notices": [],
    }


def _eq() -> dict[str, float]:
    return {
        "low_gain_db": 0,
        "mid_gain_db": 0,
        "high_gain_db": 0,
        "highpass_hz": 20,
        "lowpass_hz": 20000,
    }


def _connect_to_first_page(port: int) -> _CdpPage:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            devtools_url = f"http://127.0.0.1:{port}/json/list"
            with urllib.request.urlopen(devtools_url, timeout=0.5) as response:
                targets = json.loads(response.read().decode("utf-8"))
            page_target = next(target for target in targets if target.get("type") == "page")
            return _CdpPage(page_target["webSocketDebuggerUrl"])
        except Exception:
            time.sleep(0.05)
    raise AssertionError("Chrome DevTools page target was not available")


class _CdpPage:
    def __init__(self, websocket_url: str) -> None:
        self.socket = _WebSocket(websocket_url)
        self.next_id = 1

    def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        command_id = self.next_id
        self.next_id += 1
        self.socket.send_json({"id": command_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = self.socket.recv_json()
            if message.get("id") == command_id:
                if "error" in message:
                    raise AssertionError(message["error"])
                return message.get("result")
        raise AssertionError(f"Chrome DevTools command timed out: {method}")

    def wait_for_live_dashboard(self) -> dict[str, Any]:
        expression = """
(() => {
  const elementText = (id) => document.getElementById(id)?.textContent.trim() || "";
  const rect = (element) => {
    const bounds = element.getBoundingClientRect();
    return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height };
  };
  const seek = document.getElementById("playbackSeekSlider");
  const progress = document.getElementById("playbackProgressBar");
  const timeline = document.getElementById("playbackTimeline");
  const liveButton = document.getElementById("playbackApplyModeLiveButton");
  const stableButton = document.getElementById("playbackApplyModeStableButton");
  const details = document.getElementById("playbackLiveDetails");
  return {
    ready: elementText("playbackApplyModeSummary").startsWith("즉시 반영") &&
      seek &&
      seek.disabled === false &&
      elementText("playbackPositionTime") === "30.0s",
    viewportWidth: window.innerWidth,
    bodyWidth: document.body.scrollWidth,
    applyModeSummary: elementText("playbackApplyModeSummary"),
    livePressed: liveButton?.getAttribute("aria-pressed"),
    stablePressed: stableButton?.getAttribute("aria-pressed"),
    liveDetailsText: details?.textContent.trim().replace(/\\s+/g, " "),
    seekDisabled: seek?.disabled,
    seekMax: seek?.max,
    seekValue: seek?.value,
    positionText: elementText("playbackPositionTime"),
    durationText: elementText("playbackDurationTime"),
    progressWidth: progress?.style.width || "",
    outputSummary: elementText("outputControlSummary"),
    transitionBadge: elementText("transitionModeBadge"),
    timelineRect: timeline ? rect(timeline) : null,
    seekRect: seek ? rect(seek) : null,
  };
})()
"""
        deadline = time.monotonic() + 10
        last_value: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            result = self.send(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
            )
            last_value = result["result"].get("value")
            if last_value and last_value.get("ready"):
                return last_value
            time.sleep(0.1)
        raise AssertionError(f"Live dashboard did not render in time: {last_value!r}")


class _WebSocket:
    def __init__(self, websocket_url: str) -> None:
        if not websocket_url.startswith("ws://"):
            raise AssertionError(f"unsupported websocket URL: {websocket_url}")
        without_scheme = websocket_url.removeprefix("ws://")
        host_port, path = without_scheme.split("/", 1)
        host, port_text = host_port.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port_text)), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host_port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise AssertionError(f"websocket handshake failed: {response[:120]!r}")

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", len(data)))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", len(data)))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def recv_json(self) -> dict[str, Any]:
        while True:
            frame = self._recv_frame()
            if frame[0] == 1:
                return json.loads(frame[1].decode("utf-8"))
            if frame[0] == 8:
                raise AssertionError("Chrome closed the DevTools websocket")

    def _recv_frame(self) -> tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if second & 0x80:
            mask = self._recv_exact(4)
            payload = bytes(
                byte ^ mask[index % 4] for index, byte in enumerate(self._recv_exact(length))
            )
        else:
            payload = self._recv_exact(length)
        return opcode, payload

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise AssertionError("websocket closed while reading frame")
            chunks.extend(chunk)
        return bytes(chunks)
