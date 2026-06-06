from __future__ import annotations

import re
from pathlib import Path

from static_app_harness import (
    STATIC_APP_BOOTSTRAP,
    STATIC_APP_RENDER_DOM_SETUP,
    run_node_harness,
)


def test_covered_live_control_identifiers_map_to_feedback_surfaces() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  feedbackSurfaceIdForControlId,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { feedbackSurfaceIdForControlId } = globalThis.__secretPond;

const layerControls = [
  "enabled",
  "volume_db",
  "eq.low_gain_db",
  "eq.mid_gain_db",
  "eq.high_gain_db",
  "eq.highpass_hz",
  "eq.lowpass_hz",
];
for (const layerId of ["low", "mid", "voice"]) {
  for (const controlPath of layerControls) {
    assert.strictEqual(
      feedbackSurfaceIdForControlId(`layers.${layerId}.${controlPath}`),
      `layer:${layerId}`,
    );
  }
}

assert.strictEqual(
  feedbackSurfaceIdForControlId("voice_stack.transition_seconds"),
  "voice_stack",
);

for (const controlPath of [
  "gain_db",
  "normalize_peak",
  "highpass_hz",
  "lowpass_hz",
  "presence_gain_db",
  "reverb_mix",
  "delay_mix",
  "fade_ms",
]) {
  assert.strictEqual(
    feedbackSurfaceIdForControlId(`recording.${controlPath}`),
    "recording",
  );
}

for (const excludedControlId of [
  "playback.master_volume_db",
  "playback.apply_mode",
  "audio.sample_rate",
  "audio.channels",
  "devices.input_device_id",
  "devices.output_device_id",
  "sources.low_path",
  "voice_stack.loop_seconds",
  "input_control.minimum_recording_seconds",
]) {
  assert.strictEqual(feedbackSurfaceIdForControlId(excludedControlId), null);
}
""",
    )


def test_output_playback_panel_does_not_receive_feedback_pending_card_class() -> None:
    index_html = Path("src/secret_pond/web/static/index.html").read_text(encoding="utf-8")

    playback_panel = re.search(
        r'<section(?=[^>]*\bid="playbackPanel")(?=[^>]*\bclass="([^"]+)")[^>]*>',
        index_html,
        re.DOTALL,
    )

    assert playback_panel is not None
    assert playback_panel.group(1) == "operation-card playback-panel"


def test_output_playback_panel_does_not_render_feedback_spinner() -> None:
    index_html = Path("src/secret_pond/web/static/index.html").read_text(encoding="utf-8")

    playback_panel = re.search(
        r'<section(?=[^>]*\bid="playbackPanel")[^>]*>(.*?)</section>',
        index_html,
        re.DOTALL,
    )

    assert playback_panel is not None
    assert "feedback-spinner" not in playback_panel.group(1)


def test_feedback_spinner_is_decorative_top_right_translucent_overlay() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    styles = Path("src/secret_pond/web/static/styles.css").read_text(encoding="utf-8")

    spinner_rule = re.search(r"\.feedback-spinner\s*\{(?P<body>.*?)\}", styles, re.DOTALL)
    hidden_rule = re.search(r"\.feedback-spinner\[hidden\]\s*\{(?P<body>.*?)\}", styles, re.DOTALL)

    assert spinner_rule is not None
    assert hidden_rule is not None

    spinner_body = spinner_rule.group("body")
    assert re.search(r"position:\s*absolute;", spinner_body)
    assert re.search(r"top:\s*10px;", spinner_body)
    assert re.search(r"right:\s*10px;", spinner_body)
    assert re.search(r"opacity:\s*0\.[0-9]+;", spinner_body)
    assert re.search(r"pointer-events:\s*none;", spinner_body)
    assert re.search(r"z-index:\s*[1-9][0-9]*;", spinner_body)
    assert re.search(r"display:\s*none;", hidden_rule.group("body"))
    assert app_script.count('class="feedback-spinner" aria-hidden="true"') == 2


def test_playback_apply_mode_panel_does_not_receive_feedback_pending_class() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderLayerControls,
  renderPlaybackApplyModeControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderLayerControls, renderPlaybackApplyModeControls, state } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
state.snapshot = {
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = clone(activeSettings);
state.draft.layers.low.volume_db = -1;

renderPlaybackApplyModeControls();
renderLayerControls();

const playbackApplyModePanel = document.getElementById("playbackApplyModePanel");
const lowCard = document.getElementById("layerControls").children[1];

assert.match(lowCard.className, /\\bfeedback-pending\\b/);
assert.doesNotMatch(playbackApplyModePanel.className, /\\bfeedback-pending\\b/);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_playback_apply_mode_panel_does_not_show_spinner_during_covered_apply() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderLayerControls,
  renderPlaybackApplyModeControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderLayerControls, renderPlaybackApplyModeControls, state } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
state.snapshot = {
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = clone(activeSettings);
state.draft.layers.low.volume_db = -1;
state.applyInFlight = true;
state.applyAndRestartInFlight = true;
state.playbackApplyModeInFlight = false;

renderPlaybackApplyModeControls();
renderLayerControls();

const playbackApplyModePanel = document.getElementById("playbackApplyModePanel");
const lowCard = document.getElementById("layerControls").children[1];

assert.match(lowCard.innerHTML, /class="feedback-spinner"[^>]*>/);
assert.doesNotMatch(lowCard.innerHTML, /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/);
assert.doesNotMatch(playbackApplyModePanel.className, /\\bfeedback-pending\\b/);
assert.doesNotMatch(playbackApplyModePanel.className, /\\bpending\\b/);
assert.doesNotMatch(playbackApplyModePanel.innerHTML, /feedback-spinner/);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_source_library_does_not_receive_feedback_card_class_or_spinner() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderLayerControls,
  renderSourceLibrary,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderLayerControls, renderSourceLibrary, state } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low/current.wav",
    mid_path: "sources/mid/current.wav",
    voice_raw_path: "sources/voice/raw.wav",
    voice_stack_path: "sources/voice/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
state.snapshot = {
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = clone(activeSettings);
state.draft.layers.low.volume_db = -1;
state.applyInFlight = true;
state.applyAndRestartInFlight = true;
state.coveredFeedbackSurfaceId = "layer:low";
state.sources = {
  categories: [
    {
      id: "low",
      label: "Low",
      settings_field: "low_path",
      required: true,
      directory: "data/sources/low",
      active_exists: true,
      selected_path: "sources/low/current.wav",
      files: [
        {
          name: "current.wav",
          path: "sources/low/current.wav",
          size_bytes: 1024,
          modified_at: "2026-06-06T10:00:00Z",
          active: true,
          applied: true,
        },
      ],
    },
  ],
};

renderLayerControls();
renderSourceLibrary();

const lowCard = document.getElementById("layerControls").children[1];
assert.match(lowCard.innerHTML, /feedback-spinner/);

const sourceLibraryList = document.getElementById("sourceLibraryList");
const sourceLibraryMarkup = sourceLibraryList.children
  .map((child) => `${child.className} ${child.innerHTML}`)
  .join("\\n");
assert.doesNotMatch(sourceLibraryMarkup, /\\bfeedback-pending\\b/);
assert.doesNotMatch(sourceLibraryMarkup, /feedback-spinner/);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_live_feedback_highlight_requires_covered_and_live_applicable_change() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { deriveCoveredSurfaceFeedbackState } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "live", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const snapshot = {
  settings: {
    active: activeSettings,
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [
        "recording.gain_db",
        "recording.reverb_mix",
      ],
    },
  },
  playback: {
    apply_mode: "live",
    output_running: true,
    voice_raw_preview_path: "sources/voice.wav",
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: false,
      eq_applies_immediately: false,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
};

const volumeDraft = clone(activeSettings);
volumeDraft.layers.low.volume_db = -1;
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft: volumeDraft,
    operationFlags: { draftSaveInFlight: true, liveFeedbackSurfaceId: "layer:low" },
    surfaceId: "layer.low",
  }),
  { visual_state: "pending", show_spinner: true },
);

const eqDraft = clone(activeSettings);
eqDraft.layers.low.eq.low_gain_db = 3;
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft: eqDraft,
    operationFlags: { draftSaveInFlight: true, liveFeedbackSurfaceId: "layer:low" },
    surfaceId: "layer.low",
  }),
  { visual_state: "idle", show_spinner: false },
);

const outputDraft = clone(activeSettings);
outputDraft.playback.master_volume_db = -6;
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft: outputDraft,
    operationFlags: { draftSaveInFlight: true },
    surfaceId: "output",
  }),
  { visual_state: "idle", show_spinner: false },
);
""",
    )


def test_live_input_and_output_device_changes_remain_runtime_gated_outside_feedback_path() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
  deriveSettingsUiState,
  localSettingsChangePlan,
  outputControlSummaryText,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const {
  deriveCoveredSurfaceFeedbackState,
  deriveSettingsUiState,
  localSettingsChangePlan,
  outputControlSummaryText,
} = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "live", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const runtimeConfigFields = [
  "audio.sample_rate",
  "audio.channels",
  "devices.input_device_id",
  "devices.output_device_id",
];
const clone = (value) => JSON.parse(JSON.stringify(value));

for (const [fieldName, nextDeviceId, expectedSummary] of [
  [
    "input_device_id",
    "mic-2",
    "Live 모드 · 입력 장치 변경은 System 패널 적용 후 Apply and Restart 후 반영됩니다.",
  ],
  [
    "output_device_id",
    "speaker-2",
    "Live 모드 · 출력 장치 변경은 System 패널 적용 후 Apply and Restart 후 반영됩니다.",
  ],
]) {
  const draft = clone(activeSettings);
  draft.devices[fieldName] = nextDeviceId;
  const snapshot = {
    settings: {
      active: activeSettings,
      draft,
      change: {
        runtime_config_changed: false,
        changed_sections: [],
        runtime_config_fields: runtimeConfigFields,
        live_preview_reprocessable_field_names: [],
      },
    },
    playback: {
      apply_mode: "live",
      output_running: true,
      live: { enabled: true, volume_applies_immediately: true },
    },
  };
  const plan = localSettingsChangePlan(activeSettings, draft, runtimeConfigFields);
  const uiState = deriveSettingsUiState({ snapshot, settingsPlan: plan });

  assert.strictEqual(plan.runtimeConfigChanged, true);
  assert.deepStrictEqual(plan.changedRuntimeFields, [`devices.${fieldName}`]);
  assert.strictEqual(uiState.pendingChangeState.runtimeConfigChanged, true);
  assert.strictEqual(uiState.controlState.applyDisabled, true);
  assert.strictEqual(
    outputControlSummaryText(snapshot, uiState.pendingChangeState),
    expectedSummary,
  );

  for (const surfaceId of ["layer:low", "layer:mid", "layer:voice", "voice_stack", "recording"]) {
    assert.deepStrictEqual(
      deriveCoveredSurfaceFeedbackState({
        snapshot,
        draft,
        operationFlags: {
          draftSaveInFlight: true,
          feedbackControlId: `devices.${fieldName}`,
        },
        surfaceId,
      }),
      { visual_state: "idle", show_spinner: false },
    );
  }
}
""",
    )


def test_stable_runtime_gated_fields_do_not_highlight_covered_surfaces() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { deriveCoveredSurfaceFeedbackState } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const draft = clone(activeSettings);
draft.audio.sample_rate = 44100;
draft.audio.channels = 1;
draft.devices.input_device_id = "mic-2";
draft.devices.output_device_id = "speaker-2";
draft.input_control.minimum_recording_seconds = 5;

const snapshot = {
  settings: {
    active: activeSettings,
    draft,
    change: {
      runtime_config_changed: true,
      changed_sections: ["audio", "devices", "input_control"],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: { apply_mode: "stable", output_running: true },
};

for (const surfaceId of ["layer:low", "layer:mid", "layer:voice", "voice_stack", "recording"]) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({
      snapshot,
      draft,
      operationFlags: { applyInFlight: true },
      surfaceId,
    }),
    { visual_state: "idle", show_spinner: false },
  );
}
""",
    )


def test_stable_apply_spinner_requires_changed_surface_and_apply_restart_operation() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { deriveCoveredSurfaceFeedbackState } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const draft = clone(activeSettings);
draft.layers.low.volume_db = -1;
draft.recording.gain_db = 3;
const snapshot = {
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, apply_mode: "stable" },
};

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { applyInFlight: false, applyAndRestartInFlight: false },
    surfaceId: "layer:low",
  }),
  { visual_state: "pending", show_spinner: false },
);

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { applyInFlight: true, applyAndRestartInFlight: false },
    surfaceId: "layer:low",
  }),
  { visual_state: "pending", show_spinner: false },
);

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { applyInFlight: true, applyAndRestartInFlight: true },
    surfaceId: "layer:low",
  }),
  { visual_state: "pending", show_spinner: true },
);
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { applyInFlight: true, applyAndRestartInFlight: true },
    surfaceId: "recording",
  }),
  { visual_state: "pending", show_spinner: true },
);
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { applyInFlight: true, applyAndRestartInFlight: true },
    surfaceId: "layer:mid",
  }),
  { visual_state: "idle", show_spinner: false },
);
""",
    )


def test_uncovered_live_draft_save_does_not_highlight_preexisting_covered_change() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { deriveCoveredSurfaceFeedbackState } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "live", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const snapshot = {
  settings: {
    active: activeSettings,
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: ["recording.gain_db"],
    },
  },
  playback: {
    apply_mode: "live",
    output_running: true,
    voice_raw_preview_path: "sources/voice.wav",
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: false,
      eq_applies_immediately: false,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
};
const draft = clone(activeSettings);
draft.layers.low.volume_db = -1;
draft.playback.master_volume_db = -6;

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: {
      draftSaveInFlight: true,
      liveFeedbackSurfaceId: null,
    },
    surfaceId: "layer:low",
  }),
  { visual_state: "idle", show_spinner: false },
);
""",
    )


def test_live_feedback_only_highlights_touched_covered_surface() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { deriveCoveredSurfaceFeedbackState } = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "live", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const snapshot = {
  settings: {
    active: activeSettings,
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: ["recording.gain_db"],
    },
  },
  playback: {
    apply_mode: "live",
    output_running: true,
    voice_raw_preview_path: "sources/voice.wav",
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: false,
      eq_applies_immediately: false,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
};
const draft = clone(activeSettings);
draft.layers.low.volume_db = -1;
draft.layers.mid.volume_db = -2;
draft.voice_stack.transition_seconds = 7;
draft.recording.gain_db = 3;

const operationFlags = {
  draftSaveInFlight: true,
  liveFeedbackSurfaceId: "layer:low",
};

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({ snapshot, draft, operationFlags, surfaceId: "layer:low" }),
  { visual_state: "pending", show_spinner: true },
);
for (const surfaceId of ["layer:mid", "layer:voice", "voice_stack", "recording"]) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({ snapshot, draft, operationFlags, surfaceId }),
    { visual_state: "idle", show_spinner: false },
  );
}
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { draftSaveInFlight: true },
    surfaceId: "layer:low",
  }),
  { visual_state: "idle", show_spinner: false },
);
""",
    )


def test_live_draft_save_render_targets_latest_covered_surface_only() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  commitDraftChange,
  renderLayerControls,
  renderRecordingControls,
  renderVoiceStackControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
const {
  commitDraftChange,
  renderLayerControls,
  renderRecordingControls,
  renderVoiceStackControls,
  state,
} = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "live", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
state.snapshot = {
  armed: false,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: ["recording.gain_db"],
    },
  },
  playback: {
    apply_mode: "live",
    output_running: true,
    voice_raw_preview_path: "sources/voice.wav",
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: false,
      eq_applies_immediately: false,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
};
state.draft = clone(activeSettings);

const renderCoveredSurfaces = () => {
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingControls();
};
const coveredSurfaceState = () => {
  renderCoveredSurfaces();
  const layerControls = document.getElementById("layerControls");
  return {
    mid: layerControls.children[0],
    low: layerControls.children[1],
    voiceStack: document.getElementById("voiceStackControls"),
    recording: document.getElementById("recordingControls"),
  };
};
const assertPendingSurface = (surfaces, pendingKey) => {
  for (const [key, surface] of Object.entries(surfaces)) {
    if (key === pendingKey) {
      assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should be pending`);
      assert.match(surface.innerHTML, /class="feedback-spinner"[^>]*>/, `${key} should spin`);
      assert.doesNotMatch(
        surface.innerHTML,
        /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
        `${key} should spin`,
      );
    } else {
      assert.doesNotMatch(surface.className, /\\bfeedback-pending\\b/, `${key} should stay idle`);
      assert.match(
        surface.innerHTML,
        /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
        `${key} should not spin`,
      );
    }
  }
};

commitDraftChange(() => {
  state.draft.layers.low.volume_db = -1;
}, { feedbackControlId: "layers.low.volume_db" });
commitDraftChange(() => {
  state.draft.playback.master_volume_db = -6;
});
assert.strictEqual(state.pendingCoveredFeedbackSurfaceId, undefined);
assert.strictEqual(state.pendingLiveFeedbackSurfaceId, undefined);
state.coveredFeedbackSurfaceId = state.pendingCoveredFeedbackSurfaceId;
state.liveFeedbackSurfaceId = state.pendingLiveFeedbackSurfaceId;
state.draftSaveInFlight = true;
assertPendingSurface(coveredSurfaceState(), null);

state.draftSaveInFlight = false;
commitDraftChange(() => {
  state.draft.voice_stack.transition_seconds = 7;
}, { feedbackControlId: "voice_stack.transition_seconds" });
state.coveredFeedbackSurfaceId = state.pendingCoveredFeedbackSurfaceId;
state.liveFeedbackSurfaceId = state.pendingLiveFeedbackSurfaceId;
state.draftSaveInFlight = true;
assertPendingSurface(coveredSurfaceState(), "voiceStack");
""",
    )


def test_frontend_state_drives_per_card_feedback_without_backend_metadata() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  currentOperationFlags,
  deriveCoveredSurfaceFeedbackState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const {
  currentOperationFlags,
  deriveCoveredSurfaceFeedbackState,
  state,
} = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "live", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
state.snapshot = {
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: {
    apply_mode: "live",
    output_running: true,
    voice_raw_preview_path: "sources/voice.wav",
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: false,
      eq_applies_immediately: false,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
};
state.draft = clone(activeSettings);
state.draft.layers.low.volume_db = -1;
state.draft.layers.mid.volume_db = -2;

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot: state.snapshot,
    draft: state.draft,
    operationFlags: currentOperationFlags(),
    surfaceId: "layer:low",
  }),
  { visual_state: "idle", show_spinner: false },
);

state.coveredFeedbackSurfaceId = "layer:low";
state.draftSaveInFlight = true;
const flags = currentOperationFlags();
assert.strictEqual(flags.coveredSurfaceId, "layer:low");

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot: state.snapshot,
    draft: state.draft,
    operationFlags: flags,
    surfaceId: "layer:low",
  }),
  { visual_state: "pending", show_spinner: true },
);
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot: state.snapshot,
    draft: state.draft,
    operationFlags: flags,
    surfaceId: "layer:mid",
  }),
  { visual_state: "idle", show_spinner: false },
);

state.draftSaveInFlight = false;
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot: state.snapshot,
    draft: state.draft,
    operationFlags: currentOperationFlags(),
    surfaceId: "layer:low",
  }),
  { visual_state: "idle", show_spinner: false },
);
""",
    )


def test_dashboard_render_consumes_backend_snapshot_without_per_card_operation_state() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderLayerControls,
  renderRecordingControls,
  renderVoiceStackControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
const {
  renderLayerControls,
  renderRecordingControls,
  renderVoiceStackControls,
  state,
} = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const backendSnapshot = {
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: ["layers", "voice_stack", "recording"],
      changed_runtime_fields: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_fields: [],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: {
    apply_mode: "stable",
    output_running: true,
    rendered_cache_ready: true,
    active_voice_transition_target_id: null,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
  },
};
state.snapshot = backendSnapshot;
state.draft = clone(backendSnapshot.settings.draft);
state.draft.layers.low.volume_db = -1;
state.draft.voice_stack.transition_seconds = 7;
state.draft.recording.gain_db = 3;
state.applyInFlight = true;
state.applyAndRestartInFlight = true;

assert.strictEqual(JSON.stringify(backendSnapshot).includes("operation_state"), false);
assert.strictEqual(JSON.stringify(backendSnapshot).includes("visual_state"), false);
assert.strictEqual(JSON.stringify(backendSnapshot).includes("show_spinner"), false);
assert.deepStrictEqual(
  Object.keys(backendSnapshot.settings.change).sort(),
  [
    "changed_runtime_fields",
    "changed_sections",
    "live_preview_reprocessable_field_names",
    "live_preview_reprocessable_fields",
    "runtime_config_changed",
    "runtime_config_fields",
  ].sort(),
);

renderLayerControls();
renderVoiceStackControls();
renderRecordingControls();

const lowCard = document.getElementById("layerControls").children[1];
const voiceStackControls = document.getElementById("voiceStackControls");
const recordingControls = document.getElementById("recordingControls");

assert.match(lowCard.innerHTML, /feedback-spinner/);
assert.match(voiceStackControls.className, /\\bfeedback-pending\\b/);
assert.match(voiceStackControls.innerHTML, /feedback-spinner/);
assert.match(recordingControls.className, /\\bfeedback-pending\\b/);
assert.match(recordingControls.innerHTML, /feedback-spinner/);
""",
    )


def test_stable_apply_failure_shows_single_global_korean_caution_banner() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const { applyAndRestart, state } = globalThis.__secretPond;
const activeSettings = {
  audio: { sample_rate: 48000, channels: 2 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { apply_mode: "stable", master_volume_db: -9 },
  voice_stack: { mode: "live_ephemeral", loop_seconds: 60, transition_seconds: 4 },
  input_control: { minimum_recording_seconds: 3, maximum_recording_seconds: 120 },
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
  sources: {
    low_path: "sources/low.wav",
    mid_path: "sources/mid.wav",
    voice_raw_path: "sources/voice.wav",
    voice_stack_path: "sources/stack.wav",
  },
  layers: {
    low: {
      enabled: true,
      volume_db: -3,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    mid: {
      enabled: true,
      volume_db: -4,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
    voice: {
      enabled: true,
      volume_db: -5,
      eq: { low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0, highpass_hz: 20, lowpass_hz: 20000 },
    },
  },
};
state.snapshot = {
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: activeSettings,
    draft: activeSettings,
    change: {
      runtime_config_changed: false,
      changed_sections: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: {
    apply_mode: "stable",
    output_running: true,
    rendered_cache_ready: true,
    active_voice_transition_target_id: null,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
  },
};
state.draft = null;

const requests = [];
globalThis.fetch = async (path) => {
  requests.push(path);
  if (path === "/api/settings/apply") {
    return {
      ok: false,
      status: 500,
      async json() { return { detail: "render failed" }; },
    };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

const banner = document.getElementById("errorBanner");
assert.deepStrictEqual(requests, [
  "/api/settings/apply",
  "/api/state",
  "/api/diagnostics",
  "/api/sources",
]);
assert.strictEqual(banner.hidden, false);
assert.strictEqual(banner.className, "error-banner notice-banner caution");
assert.strictEqual(banner.children.length, 3);
assert.strictEqual(banner.children[0].children[0].textContent, "주의");
assert.strictEqual(
  banner.children[0].children[1].textContent,
  "변경사항을 적용하지 못했습니다. 이전 설정이 계속 사용됩니다.",
);
assert.strictEqual(document.getElementById("errorBadge").textContent, "주의 있음");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )
