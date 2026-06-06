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


def test_live_state_payload_optional_fields_are_parsed_without_changing_playback_fields() -> None:
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

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  audio: { sample_rate: 48000, channels: 2, loop_seconds: 60 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
  sources: {
    low_path: "data/sources/low/live-low.wav",
    mid_path: null,
    voice_raw_path: "data/sources/voice/raw/VR0610_213112.wav",
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
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: { changed_sections: [], runtime_config_changed: false },
  },
  playback: {
    apply_mode: "live",
    frame_cursor: 1440000,
    is_playing: true,
    rendered_cache_ready: true,
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    active_voice_transition_target_id: "data/sources/voice/stack/VS0610_213112.wav",
    playback_session_id: 7,
    voice_raw_preview_path: "data/sources/voice/raw/VR0610_213112.wav",
    transition_warning: "voice transition ready",
    output_running: true,
    output_latest_status: "running",
    output_latest_error: null,
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: true,
      seek_applies_immediately: true,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
      eq_applies_immediately: true,
      excluded_apply_flow: [
        "audio.loop_seconds",
        "audio.sample_rate",
        "devices.output_device_id",
        "sources",
      ],
      eq_source_contract: "eq_free",
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 90,
  participant_count: 3,
});

assert.strictEqual(applied, true);
assert.strictEqual(state.snapshot.playback.apply_mode, "live");
assert.strictEqual(state.snapshot.playback.position_seconds, 30);
assert.strictEqual(state.snapshot.playback.duration_seconds, 60);
assert.strictEqual(state.snapshot.playback.progress, 0.5);
assert.strictEqual(
  state.snapshot.playback.active_voice_transition_target_id,
  "data/sources/voice/stack/VS0610_213112.wav",
);
assert.strictEqual(state.snapshot.playback.playback_session_id, 7);
assert.strictEqual(
  state.snapshot.playback.voice_raw_preview_path,
  "data/sources/voice/raw/VR0610_213112.wav",
);
assert.strictEqual(state.snapshot.playback.transition_warning, "voice transition ready");
assert.strictEqual(state.snapshot.playback.output_running, true);
assert.strictEqual(state.snapshot.playback.output_latest_status, "running");
assert.deepStrictEqual(state.snapshot.playback.live, {
  enabled: true,
  volume_applies_immediately: true,
  mute_applies_immediately: true,
  seek_applies_immediately: true,
  voice_stack_transition_applies_immediately: true,
  voice_raw_preview_treatment_applies_immediately: true,
  eq_applies_immediately: true,
  excluded_apply_flow: [
    "audio.loop_seconds",
    "audio.sample_rate",
    "devices.output_device_id",
    "sources",
  ],
  eq_source_contract: "eq_free",
});
assert.strictEqual(state.snapshot.settings.active.playback.apply_mode, "live");
assert.strictEqual(state.draft.playback.apply_mode, "live");

const partialLivePayload = cloneSettings(liveSettings);
partialLivePayload.playback = { auto_start: true, apply_mode: "live", master_volume_db: -11 };
const partialApplied = applyState({
  state_revision: 1,
  settings: {
    active: cloneSettings(partialLivePayload),
    draft: cloneSettings(partialLivePayload),
    change: { changed_sections: [], runtime_config_changed: false },
  },
  playback: {
    apply_mode: "live",
    frame_cursor: 0,
    is_playing: false,
    rendered_cache_ready: true,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
    output_running: false,
    live: {
      enabled: true,
      seek_applies_immediately: true,
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 90,
  participant_count: 3,
});

assert.strictEqual(partialApplied, true);
assert.strictEqual(state.snapshot.playback.apply_mode, "live");
assert.strictEqual(state.snapshot.playback.output_running, false);
assert.deepStrictEqual(state.snapshot.playback.live, {
  enabled: true,
  volume_applies_immediately: false,
  mute_applies_immediately: false,
  seek_applies_immediately: true,
  voice_stack_transition_applies_immediately: false,
  voice_raw_preview_treatment_applies_immediately: false,
  eq_applies_immediately: false,
  excluded_apply_flow: [],
  eq_source_contract: null,
});
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


def test_playback_apply_mode_control_switches_live_and_survives_state_refresh() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderControls,
  setPlaybackApplyMode,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
(async () => {
const {
  applyState,
  renderControls,
  setPlaybackApplyMode,
  state,
  trackInteractiveControl,
} = globalThis.__secretPond;
const requests = [];
globalThis.fetch = async (path, options = {}) => {
  requests.push({ path, options });
  assert.strictEqual(path, "/api/playback/apply-mode");
  assert.strictEqual(options.method, "PUT");
  assert.deepStrictEqual(JSON.parse(options.body), { mode: "live" });
  const nextSettings = cloneSettings(state.snapshot.settings.active);
  nextSettings.playback = {
    ...nextSettings.playback,
    apply_mode: "live",
  };
  return {
    ok: true,
    json: async () => ({
      state: {
        ...state.snapshot,
        settings: {
          active: cloneSettings(nextSettings),
          draft: cloneSettings(nextSettings),
          change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
        },
        playback: {
          ...state.snapshot.playback,
          apply_mode: "live",
          live: { enabled: true, volume_applies_immediately: true },
        },
      },
    }),
  };
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
  audio: { sample_rate: 48000, channels: 2, loop_seconds: 60 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { auto_start: true, apply_mode: "stable", master_volume_db: -9 },
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
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

const panel = document.getElementById("playbackApplyModePanel");
const liveButton = document.getElementById("playbackApplyModeLiveButton");
const stableButton = document.getElementById("playbackApplyModeStableButton");
panel.append(liveButton, stableButton);
assert.strictEqual(panel.getAttribute("aria-label"), "재생 적용 모드");
assert.strictEqual(
  document.getElementById("playbackApplyModeSummary").textContent,
  "Stable · 활성 · 변경사항 적용 후 재생",
);
assert.strictEqual(stableButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(liveButton.getAttribute("aria-pressed"), "false");
assert.strictEqual(liveButton.disabled, false);

await setPlaybackApplyMode("live");

assert.strictEqual(requests.length, 1);
assert.strictEqual(state.snapshot.playback.apply_mode, "live");
assert.strictEqual(state.snapshot.settings.active.playback.apply_mode, "live");
assert.strictEqual(
  document.getElementById("playbackApplyModeSummary").textContent,
  "Live · 활성 · 즉시 반영 중",
);
assert.strictEqual(stableButton.getAttribute("aria-pressed"), "false");
assert.strictEqual(liveButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(liveButton.classList.contains("active"), true);

document.activeElement = liveButton;
trackInteractiveControl(liveButton);
renderControls();

assert.strictEqual(state.activeInteractiveControl, liveButton);
assert.strictEqual(
  state.deferredInteractiveRenders["settings-controls"].name,
  "renderControls",
);
assert.strictEqual(document.getElementById("playbackApplyModeLiveButton"), liveButton);
assert.strictEqual(liveButton.getAttribute("aria-pressed"), "true");
})();
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_playback_apply_mode_segment_labels_use_korean_facing_wording() -> None:
    index_html = Path("src/secret_pond/web/static/index.html").read_text(encoding="utf-8")

    assert '<span>Live <small lang="ko">라이브</small></span>' in index_html
    assert '<span>Stable <small lang="ko">안정</small></span>' in index_html


def test_live_playback_apply_panel_reuses_storage_mode_panel_pattern() -> None:
    index_html = Path("src/secret_pond/web/static/index.html").read_text(encoding="utf-8")
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")

    expected_panel_class = (
        'id="playbackApplyModePanel"\n'
        '                class="storage-mode-panel playback-apply-mode-panel"'
    )
    assert (
        expected_panel_class in index_html
    )
    assert (
        "panel.className = `storage-mode-panel playback-apply-mode-panel ${details.className}${"
        in app_script
    )


def test_live_status_text_uses_korean_facing_wording() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")

    assert "Live mode ·" not in app_script
    assert "Live transition ·" not in app_script
    assert "Live 모드 · 샘플레이트 변경은 Apply and Restart 후 반영됩니다." in app_script
    assert (
        "Live 모드 · 출력 장치 변경은 System 패널 적용 후 Apply and Restart 후 반영됩니다."
        in app_script
    )
    assert "Live 모드 · 루프 길이 변경은 Apply and Restart 후 반영됩니다." in app_script
    assert "Live 모드 · 소스 파일 선택은 Apply and Restart 후 반영됩니다." in app_script
    assert "Live 전환 · 새 녹음은 준비되면 목소리 레이어만 부드럽게 전환됩니다." in app_script


def test_live_volume_and_mute_drafts_do_not_show_apply_restart_required_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: {
    output_running: true,
    frame_cursor: 1200,
    apply_mode: "live",
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: true,
      seek_applies_immediately: true,
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.draft.layers.low.volume_db = -12;
state.draft.layers.voice.enabled = false;
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, true);
assert.strictEqual(document.getElementById("applyButton").disabled, true);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), false);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "적용할 변경사항이 없습니다.",
);
assert.strictEqual(
  document.getElementById("outputControlSummary").textContent,
  "Live 전환 · 새 녹음은 준비되면 목소리 레이어만 부드럽게 전환됩니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_voice_stack_transition_draft_does_not_show_apply_restart_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: {
    output_running: true,
    frame_cursor: 1200,
    apply_mode: "live",
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    live: {
      enabled: true,
      voice_stack_transition_applies_immediately: true,
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.draft.voice_stack.transition_seconds = 8;
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, true);
assert.strictEqual(document.getElementById("applyButton").disabled, true);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), false);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "적용할 변경사항이 없습니다.",
);

state.draft.voice_stack.loop_seconds = 75;
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, false);
assert.strictEqual(document.getElementById("applyButton").disabled, false);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), true);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "Live 모드에서도 루프 길이는 Apply and Restart 후 반영됩니다.",
);
assert.strictEqual(
  document.getElementById("outputControlSummary").textContent,
  "Live 모드 · 루프 길이 변경은 Apply and Restart 후 반영됩니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_sample_rate_draft_shows_apply_required_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: {
      changed_sections: [],
      requires_restart: false,
      runtime_config_changed: false,
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
    },
  },
  playback: {
    output_running: true,
    frame_cursor: 1200,
    apply_mode: "live",
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    live: {
      enabled: true,
      excluded_apply_flow: [
        "audio.loop_seconds",
        "audio.sample_rate",
        "devices.output_device_id",
        "sources",
      ],
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.draft.audio.sample_rate = 44100;
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, false);
assert.strictEqual(document.getElementById("applyButton").disabled, true);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), false);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "Live 모드에서도 샘플레이트 변경은 Apply and Restart 후 반영됩니다.",
);
assert.strictEqual(
  document.getElementById("outputControlSummary").textContent,
  "Live 모드 · 샘플레이트 변경은 Apply and Restart 후 반영됩니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_output_device_change_shows_apply_required_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: {
      changed_sections: [],
      requires_restart: false,
      runtime_config_changed: false,
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
    },
  },
  playback: {
    output_running: true,
    frame_cursor: 1200,
    apply_mode: "live",
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    live: {
      enabled: true,
      excluded_apply_flow: [
        "audio.loop_seconds",
        "audio.sample_rate",
        "devices.output_device_id",
        "sources",
      ],
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.draft.devices.output_device_id = "speaker-2";
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, false);
assert.strictEqual(document.getElementById("applyButton").disabled, true);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), false);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "Live 모드에서도 출력 장치 변경은 System 패널에서 적용한 뒤 Apply and Restart 후 반영됩니다.",
);
assert.strictEqual(
  document.getElementById("outputControlSummary").textContent,
  "Live 모드 · 출력 장치 변경은 System 패널 적용 후 Apply and Restart 후 반영됩니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_source_file_selection_change_shows_apply_required_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
  sources: {
    low_path: "data/sources/low/current.wav",
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

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: {
    output_running: true,
    frame_cursor: 1200,
    apply_mode: "live",
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    live: {
      enabled: true,
      excluded_apply_flow: [
        "audio.loop_seconds",
        "audio.sample_rate",
        "devices.output_device_id",
        "sources",
      ],
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.sources = {
  categories: [{
    id: "low",
    settings_field: "low_path",
    legacy_path: null,
    files: [
      {
        name: "current.wav",
        path: "data/sources/low/current.wav",
        size_bytes: 128,
        modified_at: "2026-06-06T10:00:00+09:00",
      },
      {
        name: "next.wav",
        path: "data/sources/low/next.wav",
        size_bytes: 256,
        modified_at: "2026-06-06T10:10:00+09:00",
      },
    ],
  }],
};
state.appliedSourceSignature = "low:data/sources/low/current.wav:128:2026-06-06T10:00:00+09:00";
state.draft.sources.low_path = "data/sources/low/next.wav";
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, false);
assert.strictEqual(document.getElementById("applyButton").disabled, false);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), true);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "Live 모드에서도 소스 파일 선택은 Apply and Restart 후 반영됩니다.",
);
assert.strictEqual(
  document.getElementById("outputControlSummary").textContent,
  "Live 모드 · 소스 파일 선택은 Apply and Restart 후 반영됩니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_eq_drafts_do_not_show_apply_restart_required_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: {
    output_running: true,
    frame_cursor: 1200,
    apply_mode: "live",
    position_seconds: 30,
    duration_seconds: 60,
    progress: 0.5,
    live: {
      enabled: true,
      eq_applies_immediately: true,
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.draft.layers.low.eq.low_gain_db = 3;
state.draft.layers.mid.eq.highpass_hz = 80;
state.draft.layers.voice.eq.lowpass_hz = 12000;
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, true);
assert.strictEqual(document.getElementById("applyButton").disabled, true);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), false);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "적용할 변경사항이 없습니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_voice_raw_preview_treatment_drafts_do_not_show_apply_message() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderState, state } = globalThis.__secretPond;

const liveSettings = {
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
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
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
  sources: {
    low_path: null,
    mid_path: null,
    voice_raw_path: "data/sources/voice/raw/VR0610_213112.wav",
    voice_stack_path: null,
  },
  layers: {
    low: { enabled: true, volume_db: 0, eq: {} },
    mid: { enabled: true, volume_db: 0, eq: {} },
    voice: { enabled: true, volume_db: 0, eq: {} },
  },
};
const cloneSettings = (settings) => JSON.parse(JSON.stringify(settings));

applyState({
  settings: {
    active: cloneSettings(liveSettings),
    draft: cloneSettings(liveSettings),
    change: {
      changed_sections: [],
      requires_restart: false,
      runtime_config_changed: false,
      live_preview_reprocessable_fields: [],
      live_preview_reprocessable_field_names: [
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
  playback: {
    output_running: false,
    frame_cursor: 1200,
    apply_mode: "live",
    voice_raw_preview_path: "data/sources/voice/raw/VR0610_213112.wav",
    live: {
      enabled: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
});

state.draft.recording.gain_db = 4;
state.draft.recording.reverb_mix = 0.45;
renderState();

assert.strictEqual(document.getElementById("pendingBadge").hidden, true);
assert.strictEqual(document.getElementById("applyButton").disabled, true);
assert.strictEqual(document.getElementById("applyButton").classList.contains("attention"), false);
assert.strictEqual(
  document.getElementById("applyButton").title,
  "적용할 변경사항이 없습니다.",
);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )
