from __future__ import annotations

from pathlib import Path

from static_app_harness import STATIC_APP_BOOTSTRAP, STATIC_APP_RENDER_DOM_SETUP, run_node_harness


def test_active_device_select_survives_playback_websocket_state_refresh() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, state, trackInteractiveControl } = globalThis.__secretPond;
const inputSelect = document.getElementById("inputDeviceSelect");
const outputSelect = document.getElementById("outputDeviceSelect");
inputSelect.value = "mic-open";
outputSelect.value = "speaker-1";
document.activeElement = inputSelect;
trackInteractiveControl(inputSelect);
state.devices = {
  input_devices: [{ id: "mic-1", name: "Mic 1", host_api_name: "CoreAudio", kind: "input" }],
  output_devices: [{
    id: "speaker-1",
    name: "Speaker 1",
    host_api_name: "CoreAudio",
    kind: "output",
  }],
  warnings: [],
};

const activeSettings = {
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
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  sources: {
    low_path: null,
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  },
  layers: {
    low: {
      enabled: true,
      volume_db: 0,
      eq: {
        low_gain_db: 0,
        mid_gain_db: 0,
        high_gain_db: 0,
        highpass_hz: 20,
        lowpass_hz: 20000,
      },
    },
    mid: {
      enabled: true,
      volume_db: 0,
      eq: {
        low_gain_db: 0,
        mid_gain_db: 0,
        high_gain_db: 0,
        highpass_hz: 20,
        lowpass_hz: 20000,
      },
    },
    voice: {
      enabled: true,
      volume_db: 0,
      eq: {
        low_gain_db: 0,
        mid_gain_db: 0,
        high_gain_db: 0,
        highpass_hz: 20,
        lowpass_hz: 20000,
      },
    },
  },
};
const cloneSettings = (settings) => JSON.parse(JSON.stringify(settings));
state.snapshot = {
  settings: {
    active: cloneSettings(activeSettings),
    draft: cloneSettings(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1200 },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = cloneSettings(activeSettings);
state.draftEditRevision = 1;

applyState({
  settings: {
    active: cloneSettings(activeSettings),
    draft: cloneSettings(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 2400 },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
}, { syncDraft: false });

assert.strictEqual(document.getElementById("inputDeviceSelect"), inputSelect);
assert.strictEqual(inputSelect.value, "mic-open");
assert.strictEqual(state.activeInteractiveControl, inputSelect);
assert.strictEqual(
  state.deferredInteractiveRenders["device-inputDeviceSelect"].name,
  "renderDevices",
);
assert.strictEqual(outputSelect.value, "speaker-1");
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_active_capture_gate_toggle_survives_playback_websocket_state_refresh() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, state, trackInteractiveControl } = globalThis.__secretPond;
const captureGateSwitch = document.getElementById("captureGateSwitch");
captureGateSwitch.tagName = "BUTTON";
document.activeElement = captureGateSwitch;
trackInteractiveControl(captureGateSwitch);

const activeSettings = {
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
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  sources: {
    low_path: null,
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  },
  layers: {
    low: {
      enabled: true,
      volume_db: 0,
      eq: {
        low_gain_db: 0,
        mid_gain_db: 0,
        high_gain_db: 0,
        highpass_hz: 20,
        lowpass_hz: 20000,
      },
    },
    mid: {
      enabled: true,
      volume_db: 0,
      eq: {
        low_gain_db: 0,
        mid_gain_db: 0,
        high_gain_db: 0,
        highpass_hz: 20,
        lowpass_hz: 20000,
      },
    },
    voice: {
      enabled: true,
      volume_db: 0,
      eq: {
        low_gain_db: 0,
        mid_gain_db: 0,
        high_gain_db: 0,
        highpass_hz: 20,
        lowpass_hz: 20000,
      },
    },
  },
};
const cloneSettings = (settings) => JSON.parse(JSON.stringify(settings));
state.snapshot = {
  settings: {
    active: cloneSettings(activeSettings),
    draft: cloneSettings(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1200 },
  armed: true,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = cloneSettings(activeSettings);
state.draftEditRevision = 1;

applyState({
  settings: {
    active: cloneSettings(activeSettings),
    draft: cloneSettings(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 2400 },
  armed: true,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
}, { syncDraft: false });

assert.strictEqual(document.getElementById("captureGateSwitch"), captureGateSwitch);
assert.strictEqual(state.activeInteractiveControl, captureGateSwitch);
assert.strictEqual(captureGateSwitch.getAttribute("aria-checked"), "true");
assert.strictEqual(captureGateSwitch.classList.contains("checked"), true);
assert.strictEqual(captureGateSwitch.disabled, false);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )
