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


def test_playback_timeline_renders_loop_duration_based_progress() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, state } = globalThis.__secretPond;

const activeSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 5 },
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
  audio: { sample_rate: 48000, channels: 2, loop_seconds: 60 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  sources: {
    low_path: null,
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  },
  layers: {
    low: { enabled: true, volume_db: 0, eq: {} },
    mid: { enabled: true, volume_db: 0, eq: {} },
    voice: { enabled: true, volume_db: 0, eq: {} },
  },
};
const cloneSettings = (settings) => JSON.parse(JSON.stringify(settings));
state.draft = cloneSettings(activeSettings);

applyState({
  settings: {
    active: cloneSettings(activeSettings),
    draft: cloneSettings(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: {
    output_running: true,
    frame_cursor: 1440000,
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

assert.strictEqual(document.getElementById("playbackPositionTime").textContent, "30.0s");
assert.strictEqual(document.getElementById("playbackDurationTime").textContent, "60.0s");
assert.strictEqual(document.getElementById("playbackProgressBar").style.width, "50%");
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_legacy_state_payload_without_live_fields_defaults_to_stable_mode() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, state } = globalThis.__secretPond;

const legacySettings = {
  voice_stack: { mode: "test_library", loop_seconds: 45, transition_seconds: 4 },
  input_control: {
    minimum_recording_seconds: 2,
    maximum_recording_seconds: 90,
  },
  recording: {
    gain_db: 1,
    normalize_peak: 0.4,
    highpass_hz: 120,
    lowpass_hz: 9000,
    presence_gain_db: -1,
    reverb_mix: 0.2,
    delay_mix: 0.05,
    fade_ms: 60,
  },
  audio: { sample_rate: 48000, channels: 2, loop_seconds: 45 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { auto_start: true, master_volume_db: -9 },
  sources: {
    low_path: "data/sources/low/legacy-low.wav",
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: "data/sources/voice/stack/VS0610_213112.wav",
  },
  layers: {
    low: { enabled: true, volume_db: -12, eq: {} },
    mid: { enabled: false, volume_db: -18, eq: {} },
    voice: { enabled: true, volume_db: -6, eq: {} },
  },
};
const cloneSettings = (settings) => JSON.parse(JSON.stringify(settings));

const applied = applyState({
  settings: {
    active: cloneSettings(legacySettings),
    draft: cloneSettings(legacySettings),
    change: { changed_sections: [], runtime_config_changed: false },
  },
  playback: {
    frame_cursor: 1200,
    is_playing: true,
    rendered_cache_ready: true,
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 90,
  participant_count: 3,
});

assert.strictEqual(applied, true);
assert.strictEqual(state.snapshot.playback.apply_mode, "stable");
assert.strictEqual(state.snapshot.playback.position_seconds, 0);
assert.strictEqual(state.snapshot.playback.duration_seconds, 0);
assert.strictEqual(state.snapshot.playback.progress, 0);
assert.strictEqual(state.snapshot.playback.active_voice_transition_target_id, null);
assert.strictEqual(state.snapshot.playback.playback_session_id, null);
assert.strictEqual(state.snapshot.playback.voice_raw_preview_path, null);
assert.strictEqual(state.snapshot.playback.transition_warning, null);
assert.strictEqual(state.snapshot.playback.output_running, false);
assert.strictEqual(state.snapshot.settings.active.playback.apply_mode, "stable");
assert.strictEqual(state.snapshot.settings.draft.playback.apply_mode, "stable");
assert.strictEqual(state.snapshot.settings.active.playback.auto_start, true);
assert.strictEqual(state.snapshot.settings.active.playback.master_volume_db, -9);
assert.strictEqual(state.snapshot.settings.active.audio.loop_seconds, 45);
assert.strictEqual(state.snapshot.settings.active.voice_stack.mode, "test_library");
assert.strictEqual(state.draft.playback.apply_mode, "stable");
assert.strictEqual(state.draft.playback.master_volume_db, -9);
assert.deepStrictEqual(
  state.snapshot.settings.change.runtime_config_fields,
  ["audio.sample_rate", "audio.channels", "devices.input_device_id", "devices.output_device_id"],
);
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
