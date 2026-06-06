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


def test_excluded_playback_surfaces_stay_idle_in_shared_feedback_helper() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
  excludedFeedbackSurfaceIds,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const {
  deriveCoveredSurfaceFeedbackState,
  excludedFeedbackSurfaceIds,
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
const draft = clone(activeSettings);
draft.playback.master_volume_db = -6;
draft.playback.apply_mode = "live";
draft.sources.low_path = "sources/low-new.wav";

const snapshot = {
  settings: {
    active: activeSettings,
    draft,
    change: {
      changed_sections: ["playback", "sources"],
      runtime_config_changed: false,
      runtime_config_fields: [],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: { apply_mode: "stable", output_running: true },
};

assert.deepStrictEqual(
  excludedFeedbackSurfaceIds,
  ["output", "playback_apply_mode", "source_library"],
);

for (const surfaceId of excludedFeedbackSurfaceIds) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({
      snapshot,
      draft,
      operationFlags: {
        applyInFlight: true,
        applyAndRestartInFlight: true,
        feedbackSurfaceId: surfaceId,
      },
      surfaceId,
      backendState: { visual_state: "pending", show_spinner: true },
    }),
    { visual_state: "idle", show_spinner: false },
    `${surfaceId} should not receive covered yellow feedback`,
  );
}
""",
    )


def test_live_covered_setting_changes_use_shared_helper_for_successful_yellow_feedback() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyCoveredFeedbackVisualState,
  deriveCoveredSurfaceFeedbackState,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const {
  applyCoveredFeedbackVisualState,
  deriveCoveredSurfaceFeedbackState,
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
const liveSnapshot = (active) => ({
  settings: {
    active,
    draft: clone(active),
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
      mute_applies_immediately: true,
      eq_applies_immediately: true,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
});
const changedDrafts = [
  ["layer:low", "layers.low.volume_db", (draft) => { draft.layers.low.volume_db = -1; }],
  ["layer:mid", "layers.mid.eq.low_gain_db", (draft) => { draft.layers.mid.eq.low_gain_db = 2; }],
  ["layer:voice", "layers.voice.enabled", (draft) => { draft.layers.voice.enabled = false; }],
  [
    "voice_stack",
    "voice_stack.transition_seconds",
    (draft) => { draft.voice_stack.transition_seconds = 7; },
  ],
  ["recording", "recording.reverb_mix", (draft) => { draft.recording.reverb_mix = 0.4; }],
];

for (const [surfaceId, feedbackControlId, mutate] of changedDrafts) {
  const draft = clone(activeSettings);
  mutate(draft);
  const pendingState = deriveCoveredSurfaceFeedbackState({
    snapshot: liveSnapshot(activeSettings),
    draft,
    operationFlags: { draftSaveInFlight: true, feedbackControlId },
    surfaceId,
  });
  assert.deepStrictEqual(pendingState, { visual_state: "pending", show_spinner: true });

  const card = {
    className: "",
    innerHTML: '<span class="feedback-spinner" aria-hidden="true" hidden></span>',
    querySelector() { return null; },
  };
  applyCoveredFeedbackVisualState(card, "layer-card", pendingState);
  assert.match(card.className, /\\bfeedback-pending\\b/);

  const confirmedActiveSettings = clone(activeSettings);
  mutate(confirmedActiveSettings);
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({
      snapshot: liveSnapshot(confirmedActiveSettings),
      draft: clone(confirmedActiveSettings),
      operationFlags: {},
      surfaceId,
    }),
    { visual_state: "idle", show_spinner: false },
  );
}
""",
    )


def test_stable_covered_setting_changes_enter_pending_feedback_state_in_shared_helper() -> None:
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
const stableSnapshot = {
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
  playback: { apply_mode: "stable", output_running: true },
};
const changedDrafts = [
  ["layer:low", (draft) => { draft.layers.low.volume_db = -1; }],
  ["layer:mid", (draft) => { draft.layers.mid.eq.low_gain_db = 2; }],
  ["layer:voice", (draft) => { draft.layers.voice.enabled = false; }],
  ["voice_stack", (draft) => { draft.voice_stack.transition_seconds = 7; }],
  ["recording", (draft) => { draft.recording.reverb_mix = 0.4; }],
];

for (const [surfaceId, mutate] of changedDrafts) {
  const draft = clone(activeSettings);
  mutate(draft);

  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({
      snapshot: stableSnapshot,
      draft,
      operationFlags: {},
      surfaceId,
    }),
    { visual_state: "pending", show_spinner: false },
    `${surfaceId} should show a Stable pending highlight before Apply and Restart`,
  );
}
""",
    )


def test_stable_covered_changes_enter_apply_spinner_state_in_shared_helper() -> None:
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
const stableSnapshot = {
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: false,
      changed_sections: [],
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
  playback: { apply_mode: "stable", output_running: true },
};
const changedDrafts = [
  ["layer:low", (draft) => { draft.layers.low.volume_db = -1; }],
  ["layer:mid", (draft) => { draft.layers.mid.eq.low_gain_db = 2; }],
  ["layer:voice", (draft) => { draft.layers.voice.enabled = false; }],
  ["voice_stack", (draft) => { draft.voice_stack.transition_seconds = 7; }],
  ["recording", (draft) => { draft.recording.reverb_mix = 0.4; }],
];

for (const [surfaceId, mutate] of changedDrafts) {
  const draft = clone(activeSettings);
  mutate(draft);

  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({
      snapshot: stableSnapshot,
      draft,
      operationFlags: { applyInFlight: true, applyAndRestartInFlight: true },
      surfaceId,
    }),
    { visual_state: "restart_pending", show_spinner: true },
    `${surfaceId} should show a Stable Apply and Restart spinner while in flight`,
  );
}
""",
    )


def test_live_covered_feedback_helper_uses_rollback_control_ids_as_operation_targets() -> None:
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
      runtime_config_fields: [],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: {
    apply_mode: "live",
    output_running: true,
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: true,
      eq_applies_immediately: true,
    },
  },
};

const draftBeforeRollback = clone(activeSettings);
draftBeforeRollback.layers.low.volume_db = -1;
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft: draftBeforeRollback,
    operationFlags: {
      draftSaveInFlight: true,
      coveredFeedbackControlIds: ["layers.low.volume_db"],
    },
    surfaceId: "layer:low",
  }),
  { visual_state: "pending", show_spinner: true },
);

const draftAfterRollback = clone(activeSettings);
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft: draftAfterRollback,
    operationFlags: {
      draftSaveInFlight: true,
      coveredFeedbackControlIds: ["layers.low.volume_db"],
    },
    surfaceId: "layer:low",
  }),
  { visual_state: "idle", show_spinner: false },
);

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft: draftBeforeRollback,
    operationFlags: {
      draftSaveInFlight: true,
      coveredFeedbackControlIds: ["layers.low.volume_db"],
    },
    surfaceId: "layer:mid",
  }),
  { visual_state: "idle", show_spinner: false },
);
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
    assert "feedbackSpinnerMarkup" in app_script
    assert app_script.count('class="feedback-spinner" aria-hidden="true"') == 3


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


def test_stable_restart_pending_card_spinner_excludes_playback_mode() -> None:
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


def test_stable_apply_shows_spinner_only_for_restart_pending_changed_surface() -> None:
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
  { visual_state: "restart_pending", show_spinner: true },
);
assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot,
    draft,
    operationFlags: { applyInFlight: true, applyAndRestartInFlight: true },
    surfaceId: "recording",
  }),
  { visual_state: "restart_pending", show_spinner: true },
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


def test_stable_apply_capture_records_covered_surface_diffs_before_request() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  captureStableCoveredFeedbackSurfaceDiffs,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { captureStableCoveredFeedbackSurfaceDiffs } = globalThis.__secretPond;

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
draft.voice_stack.transition_seconds = 7;
draft.recording.reverb_mix = 0.4;
draft.playback.master_volume_db = -6;
draft.audio.sample_rate = 44100;
draft.devices.input_device_id = "mic-2";
const snapshot = {
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      runtime_config_changed: true,
      changed_sections: ["audio", "devices", "layers", "playback", "recording", "voice_stack"],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: { output_running: true, apply_mode: "stable" },
};

const captured = captureStableCoveredFeedbackSurfaceDiffs({ snapshot, draft });
draft.layers.mid.volume_db = -2;
draft.recording.gain_db = 9;

assert.deepStrictEqual(captured, ["layer:low", "voice_stack", "recording"]);
""",
    )


def test_stable_apply_captures_covered_surface_diffs_after_draft_save() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
  serverStateSignature,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
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
const clone = (value) => JSON.parse(JSON.stringify(value));
const originalDraft = clone(activeSettings);
originalDraft.layers.low.volume_db = -1;
originalDraft.recording.reverb_mix = 0.4;
const savedDraft = clone(originalDraft);
savedDraft.layers.low.volume_db = activeSettings.layers.low.volume_db;

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
      changed_sections: [],
      requires_restart: false,
      runtime_config_changed: false,
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [],
    },
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
};
state.draft = clone(originalDraft);
state.appliedSourceSignature = "";

let capturedAtApply = null;
globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      json: async () => ({
        settings: {
          active: clone(activeSettings),
          draft: clone(savedDraft),
          change: {
            changed_sections: ["recording"],
            requires_restart: true,
            runtime_config_changed: false,
            runtime_config_fields: [
              "audio.sample_rate",
              "audio.channels",
              "devices.input_device_id",
              "devices.output_device_id",
            ],
            live_preview_reprocessable_field_names: [],
          },
        },
      }),
    };
  }
  if (path === "/api/settings/apply") {
    capturedAtApply = [...state.stableApplyCoveredFeedbackSurfaceIds];
    return {
      ok: true,
      json: async () => ({
        state: {
          ...clone(state.snapshot),
          settings: {
            active: clone(savedDraft),
            draft: clone(savedDraft),
            change: {
              changed_sections: [],
              requires_restart: false,
              runtime_config_changed: false,
            },
          },
        },
      }),
    };
  }
  if (path === "/api/state") {
    return { ok: true, json: async () => clone(state.snapshot) };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      json: async () => ({ sources: [], events: { recent: [] } }),
    };
  }
  if (path === "/api/sources") {
    return { ok: true, json: async () => ({ categories: [] }) };
  }
  throw new Error(`unexpected request: ${path}`);
};

applyAndRestart()
  .then(() => {
    assert.deepStrictEqual(capturedAtApply, ["recording"]);
    assert.deepStrictEqual(state.stableApplyCoveredFeedbackSurfaceIds, []);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_stable_apply_captures_pre_restart_covered_control_snapshot_after_draft_save() -> None:
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
        body="""
(async () => {
const { applyAndRestart, serverStateSignature, state } = globalThis.__secretPond;

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
const originalDraft = clone(activeSettings);
originalDraft.layers.low.volume_db = -1;
originalDraft.layers.low.eq.low_gain_db = 4;
originalDraft.recording.reverb_mix = 0.4;
originalDraft.playback.master_volume_db = -6;

const savedDraft = clone(originalDraft);
savedDraft.layers.low.volume_db = activeSettings.layers.low.volume_db;
savedDraft.playback.master_volume_db = -5;

const changeFor = (active, draft) => ({
  runtime_config_changed: false,
  changed_sections: Object.keys(draft).filter((section) => (
    JSON.stringify(active[section]) !== JSON.stringify(draft[section])
  )),
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
});
const snapshotFor = (active, draft) => ({
  armed: false,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(active),
    draft: clone(draft),
    change: changeFor(active, draft),
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
});

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(originalDraft);
state.appliedSourceSignature = "";
state.serverStateSignature = null;

let capturedAtRestart = null;
globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      json: async () => ({ settings: snapshotFor(activeSettings, savedDraft).settings }),
    };
  }
  if (path === "/api/settings/apply") {
    capturedAtRestart = clone(state.stableApplyCoveredFeedbackControlSnapshots);
    return {
      ok: false,
      status: 500,
      json: async () => ({ detail: "render failed" }),
    };
  }
  if (path === "/api/state") {
    return { ok: true, json: async () => snapshotFor(activeSettings, savedDraft) };
  }
  if (path === "/api/diagnostics") {
    return { ok: true, json: async () => ({ sources: [], events: { recent: [] } }) };
  }
  if (path === "/api/sources") {
    return { ok: true, json: async () => ({ categories: [] }) };
  }
  throw new Error(`unexpected request: ${path}`);
};

await applyAndRestart();

assert.deepStrictEqual(capturedAtRestart, [
  { controlId: "layers.low.eq.low_gain_db", activeValue: 0, draftValue: 4 },
  { controlId: "recording.reverb_mix", activeValue: 0.25, draftValue: 0.4 },
]);
assert.deepStrictEqual(state.stableApplyCoveredFeedbackControlSnapshots, []);
assert.strictEqual(state.draft.layers.low.volume_db, -3);
assert.strictEqual(state.draft.layers.low.eq.low_gain_db, 0);
assert.strictEqual(state.draft.recording.reverb_mix, 0.25);
assert.strictEqual(state.draft.playback.master_volume_db, -5);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_stable_restart_rollback_state_reset_clears_all_covered_apply_spinner_flags() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  clearStableRestartRollbackFeedbackState,
  deriveCoveredSurfaceFeedbackState,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const {
  clearStableRestartRollbackFeedbackState,
  deriveCoveredSurfaceFeedbackState,
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
const draftSettings = clone(activeSettings);
draftSettings.layers.low.volume_db = -1;
draftSettings.layers.mid.eq.mid_gain_db = 2;
draftSettings.layers.voice.enabled = false;
draftSettings.voice_stack.transition_seconds = 7;
draftSettings.recording.presence_gain_db = 1;

state.snapshot = {
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      changed_sections: ["layers", "voice_stack", "recording"],
      runtime_config_changed: false,
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
  playback: { apply_mode: "stable", output_running: true },
};
state.draft = clone(draftSettings);
state.applyInFlight = true;
state.applyAndRestartInFlight = true;
state.stableApplyCoveredFeedbackSurfaceIds = [
  "layer:low",
  "layer:mid",
  "layer:voice",
  "voice_stack",
  "recording",
];
state.stableApplyCoveredFeedbackControlSnapshots = [
  { controlId: "layers.low.volume_db", activeValue: -3, draftValue: -1 },
  { controlId: "layers.mid.eq.mid_gain_db", activeValue: 0, draftValue: 2 },
  { controlId: "layers.voice.enabled", activeValue: true, draftValue: false },
  { controlId: "voice_stack.transition_seconds", activeValue: 4, draftValue: 7 },
  { controlId: "recording.presence_gain_db", activeValue: -3, draftValue: 1 },
];
state.pendingCoveredFeedbackSurfaceId = "layer:low";
state.coveredFeedbackSurfaceId = "layer:mid";
state.pendingLiveFeedbackSurfaceId = "layer:voice";
state.liveFeedbackSurfaceId = "recording";
state.pendingCoveredFeedbackControlIds = ["layers.low.volume_db"];
state.coveredFeedbackControlIds = ["layers.mid.eq.mid_gain_db"];

for (const surfaceId of state.stableApplyCoveredFeedbackSurfaceIds) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({ surfaceId }),
    { visual_state: "restart_pending", show_spinner: true },
  );
}

clearStableRestartRollbackFeedbackState();

assert.strictEqual(state.applyInFlight, false);
assert.strictEqual(state.applyAndRestartInFlight, false);
assert.deepStrictEqual(state.stableApplyCoveredFeedbackSurfaceIds, []);
assert.deepStrictEqual(state.stableApplyCoveredFeedbackControlSnapshots, []);
assert.strictEqual(state.pendingCoveredFeedbackSurfaceId, undefined);
assert.strictEqual(state.coveredFeedbackSurfaceId, undefined);
assert.strictEqual(state.pendingLiveFeedbackSurfaceId, undefined);
assert.strictEqual(state.liveFeedbackSurfaceId, undefined);
assert.deepStrictEqual(state.pendingCoveredFeedbackControlIds, []);
assert.deepStrictEqual(state.coveredFeedbackControlIds, []);

for (const surfaceId of [
  "layer:low",
  "layer:mid",
  "layer:voice",
  "voice_stack",
  "recording",
]) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({ surfaceId }),
    { visual_state: "idle", show_spinner: false },
  );
}
""",
    )


def test_stable_covered_setting_failure_rollback_is_reflected_by_shared_feedback_helper() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  deriveCoveredSurfaceFeedbackState,
  rollbackDraftCoveredControlSnapshots,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const {
  deriveCoveredSurfaceFeedbackState,
  rollbackDraftCoveredControlSnapshots,
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
const failedDraft = clone(activeSettings);
failedDraft.layers.low.volume_db = -1;
failedDraft.voice_stack.transition_seconds = 7;
failedDraft.recording.gain_db = 3;

state.snapshot = {
  settings: {
    active: clone(activeSettings),
    draft: clone(failedDraft),
    change: {
      changed_sections: ["layers", "voice_stack", "recording"],
      runtime_config_changed: false,
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
  playback: { apply_mode: "stable", output_running: true },
};
state.draft = clone(failedDraft);
state.applyInFlight = true;
state.applyAndRestartInFlight = true;

for (const surfaceId of ["layer:low", "voice_stack", "recording"]) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({ surfaceId }),
    { visual_state: "restart_pending", show_spinner: true },
  );
}

const rolledBack = rollbackDraftCoveredControlSnapshots([
  { controlId: "layers.low.volume_db", activeValue: -3, draftValue: -1 },
  { controlId: "voice_stack.transition_seconds", activeValue: 4, draftValue: 7 },
  { controlId: "recording.gain_db", activeValue: 0, draftValue: 3 },
]);
state.applyInFlight = false;
state.applyAndRestartInFlight = false;

assert.strictEqual(rolledBack, true);
assert.strictEqual(state.draft.layers.low.volume_db, -3);
assert.strictEqual(state.draft.voice_stack.transition_seconds, 4);
assert.strictEqual(state.draft.recording.gain_db, 0);

for (const surfaceId of ["layer:low", "voice_stack", "recording"]) {
  assert.deepStrictEqual(
    deriveCoveredSurfaceFeedbackState({ surfaceId }),
    { visual_state: "idle", show_spinner: false },
  );
}
""",
    )


def test_stable_apply_rollback_snapshot_uses_last_confirmed_active_settings() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  captureStableCoveredFeedbackControlSnapshots,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { captureStableCoveredFeedbackControlSnapshots, state } = globalThis.__secretPond;

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
const lastConfirmedActive = clone(activeSettings);
lastConfirmedActive.layers.low.volume_db = -3;
lastConfirmedActive.recording.reverb_mix = 0.25;

const failedRequestValues = clone(activeSettings);
failedRequestValues.layers.low.volume_db = -9;
failedRequestValues.recording.reverb_mix = 0.55;

state.confirmedActiveSettingsSnapshot = clone(lastConfirmedActive);
state.snapshot = {
  armed: false,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(failedRequestValues),
    draft: clone(failedRequestValues),
    change: { changed_sections: ["layers", "recording"], runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
};
state.draft = clone(failedRequestValues);

const snapshots = captureStableCoveredFeedbackControlSnapshots();

assert.deepStrictEqual(snapshots, [
  { controlId: "layers.low.volume_db", activeValue: -3, draftValue: -9 },
  { controlId: "recording.reverb_mix", activeValue: 0.25, draftValue: 0.55 },
]);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_stable_successful_apply_response_renders_server_confirmed_control_value() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyState,
  renderVoiceStackControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applyState, renderVoiceStackControls, state } = globalThis.__secretPond;

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
  armed: false,
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
};
state.draft = clone(activeSettings);
state.draft.voice_stack.transition_seconds = 9;
state.snapshot.settings.draft = clone(state.draft);

const confirmedSettings = clone(activeSettings);
confirmedSettings.voice_stack.transition_seconds = 6;
const serverState = {
  ...clone(state.snapshot),
  settings: {
    active: clone(confirmedSettings),
    draft: clone(confirmedSettings),
    change: { changed_sections: [], requires_restart: false, runtime_config_changed: false },
  },
  playback: { output_running: true, frame_cursor: 1300, apply_mode: "stable" },
};

assert.strictEqual(applyState(serverState), true);
renderVoiceStackControls();

assert.strictEqual(state.draft.voice_stack.transition_seconds, 6);
const voiceStackControls = document.getElementById("voiceStackControls");
const renderedMarkup = voiceStackControls.children
  .map((child) => `${child.className} ${child.innerHTML} ${child.children
    .map((grandchild) => `${grandchild.className} ${grandchild.innerHTML} ${grandchild.children
      .map((row) => `${row.className} ${row.innerHTML}`)
      .join("\\n")}`)
    .join("\\n")}`)
  .join("\\n");

assert.match(renderedMarkup, /value="6"/);
assert.match(renderedMarkup, /현재값 6 s/);
assert.doesNotMatch(renderedMarkup, /변경값 9 s/);
assert.doesNotMatch(renderedMarkup, /현재 적용 4 s/);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_feedback_spinner_uses_apply_mode_semantics_for_same_in_flight_covered_change() -> None:
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
const draft = clone(activeSettings);
draft.layers.low.volume_db = -1;
const change = {
  changed_sections: ["layers"],
  requires_restart: false,
  runtime_config_changed: false,
  live_preview_reprocessable_field_names: [],
};
const liveSnapshot = {
  settings: { active: clone(activeSettings), draft: clone(activeSettings), change },
  playback: {
    output_running: true,
    apply_mode: "live",
    live: { enabled: true, volume_applies_immediately: true },
  },
};
const stableSnapshot = clone(liveSnapshot);
stableSnapshot.playback.apply_mode = "stable";
stableSnapshot.settings.active.playback.apply_mode = "stable";
stableSnapshot.settings.draft.playback.apply_mode = "stable";

const operationFlags = {
  applyInFlight: true,
  applyAndRestartInFlight: true,
  feedbackControlId: "layers.low.volume_db",
};

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot: liveSnapshot,
    draft,
    operationFlags,
    surfaceId: "layer:low",
  }),
  { visual_state: "pending", show_spinner: true },
);

assert.deepStrictEqual(
  deriveCoveredSurfaceFeedbackState({
    snapshot: stableSnapshot,
    draft,
    operationFlags,
    surfaceId: "layer:low",
  }),
  { visual_state: "restart_pending", show_spinner: true },
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


def test_live_successful_save_completion_clears_covered_surface_highlight() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  commitDraftChange,
  renderLayerControls,
  saveDraft,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const {
  commitDraftChange,
  renderLayerControls,
  saveDraft,
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
      changed_runtime_fields: [],
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

commitDraftChange(() => {
  state.draft.layers.low.volume_db = -1;
}, { feedbackControlId: "layers.low.volume_db", scheduleSave: false });

let draftRequestResolve;
globalThis.fetch = (path) => {
  assert.strictEqual(path, "/api/settings/draft");
  return new Promise((resolve) => {
    draftRequestResolve = resolve;
  });
};

const savePromise = saveDraft();
renderLayerControls();
const lowCardDuringSave = document.getElementById("layerControls").children[1];
assert.match(lowCardDuringSave.className, /\\bfeedback-pending\\b/);
assert.doesNotMatch(
  lowCardDuringSave.innerHTML,
  /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
);

const confirmedSettings = clone(activeSettings);
confirmedSettings.layers.low.volume_db = -1;
draftRequestResolve({
  ok: true,
  json: async () => ({
    settings: {
      active: clone(confirmedSettings),
      draft: clone(confirmedSettings),
      change: {
        runtime_config_changed: false,
        changed_sections: [],
        changed_runtime_fields: [],
        runtime_config_fields: [
          "audio.sample_rate",
          "audio.channels",
          "devices.input_device_id",
          "devices.output_device_id",
        ],
        live_preview_reprocessable_field_names: [],
      },
    },
  }),
});
await savePromise;

renderLayerControls();
const lowCardAfterSave = document.getElementById("layerControls").children[1];
assert.doesNotMatch(lowCardAfterSave.className, /\\bfeedback-pending\\b/);
assert.match(
  lowCardAfterSave.innerHTML,
  /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
);
assert.strictEqual(state.coveredFeedbackSurfaceId, undefined);
assert.strictEqual(state.pendingCoveredFeedbackSurfaceId, undefined);
assert.strictEqual(state.liveFeedbackSurfaceId, undefined);
assert.strictEqual(state.pendingLiveFeedbackSurfaceId, undefined);
})();
""",
    )


def test_live_successful_save_renders_server_confirmed_covered_control_value() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  commitDraftChange,
  renderLayerControls,
  saveDraft,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const {
  commitDraftChange,
  renderLayerControls,
  saveDraft,
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
      changed_runtime_fields: [],
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
      mute_applies_immediately: true,
      eq_applies_immediately: true,
      seek_applies_immediately: true,
      voice_stack_transition_applies_immediately: true,
      voice_raw_preview_treatment_applies_immediately: true,
    },
  },
};
state.draft = clone(activeSettings);

commitDraftChange(() => {
  state.draft.layers.low.volume_db = -1;
}, { feedbackControlId: "layers.low.volume_db", scheduleSave: false });

globalThis.fetch = async (path) => {
  assert.strictEqual(path, "/api/settings/draft");
  const confirmedSettings = clone(activeSettings);
  confirmedSettings.layers.low.volume_db = -2;
  const savedDraft = clone(activeSettings);
  savedDraft.layers.low.volume_db = -1;
  return {
    ok: true,
    json: async () => ({
      settings: {
        active: clone(confirmedSettings),
        draft: clone(savedDraft),
        change: {
          runtime_config_changed: false,
          changed_sections: [],
          changed_runtime_fields: [],
          runtime_config_fields: [
            "audio.sample_rate",
            "audio.channels",
            "devices.input_device_id",
            "devices.output_device_id",
          ],
          live_preview_reprocessable_field_names: [],
        },
      },
    }),
  };
};

await saveDraft();
renderLayerControls();

const lowCard = document.getElementById("layerControls").children[1];
assert.strictEqual(state.snapshot.settings.active.layers.low.volume_db, -2);
assert.strictEqual(state.draft.layers.low.volume_db, -2);
assert.doesNotMatch(lowCard.className, /\\bfeedback-pending\\b/);
assert.strictEqual(
  state.draft.layers.low.volume_db,
  state.snapshot.settings.active.layers.low.volume_db,
);
})();
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


def test_live_failure_rollback_clears_highlight_even_when_control_render_is_deferred() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  commitDraftChange,
  renderLayerControls,
  saveDraft,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const {
  commitDraftChange,
  renderLayerControls,
  saveDraft,
  state,
  trackInteractiveControl,
} = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2, loop_seconds: 60 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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
    low_path: null,
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  },
  layers: {
    low: {
      enabled: true,
      volume_db: 0,
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
const changePayload = {
  changed_sections: [],
  runtime_config_changed: false,
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_field_names: [],
};

state.snapshot = {
  playback: {
    apply_mode: "live",
    output_running: true,
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: true,
      eq_applies_immediately: true,
    },
  },
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: clone(changePayload),
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = clone(activeSettings);

commitDraftChange(() => {
  state.draft.layers.low.volume_db = -6;
}, { feedbackControlId: "layers.low.volume_db", scheduleSave: false });

let releaseFetch;
const fetchGate = new Promise((resolve) => { releaseFetch = resolve; });
globalThis.fetch = async () => {
  await fetchGate;
  return {
    ok: false,
    status: 500,
    json: async () => ({ detail: "backend hot swap failed" }),
  };
};

const savePromise = saveDraft();
const lowCard = document.getElementById("layerControls").children[1];
assert.match(lowCard.className, /\\bfeedback-pending\\b/);
assert.doesNotMatch(lowCard.innerHTML, /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/);

trackInteractiveControl(lowCard);
releaseFetch();

await assert.rejects(savePromise, /backend hot swap failed/);

assert.strictEqual(state.draft.layers.low.volume_db, 0);
assert.strictEqual(state.snapshot.settings.draft.layers.low.volume_db, 0);
assert.doesNotMatch(lowCard.className, /\\bfeedback-pending\\b/);
assert.match(lowCard.innerHTML, /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/);
})();
""",
    )


def test_live_failure_rollback_clears_spinner_when_same_surface_has_prior_live_diff() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  commitDraftChange,
  deriveCoveredSurfaceFeedbackState,
  renderLayerControls,
  saveDraft,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const {
  commitDraftChange,
  deriveCoveredSurfaceFeedbackState,
  renderLayerControls,
  saveDraft,
  state,
} = globalThis.__secretPond;

const activeSettings = {
  audio: { sample_rate: 48000, channels: 2, loop_seconds: 60 },
  devices: { input_device_id: "mic-1", output_device_id: "speaker-1" },
  playback: { auto_start: true, apply_mode: "live", master_volume_db: -9 },
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
    low_path: null,
    mid_path: null,
    voice_raw_path: null,
    voice_stack_path: null,
  },
  layers: {
    low: {
      enabled: true,
      volume_db: 0,
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
  playback: {
    apply_mode: "live",
    output_running: true,
    live: {
      enabled: true,
      volume_applies_immediately: true,
      mute_applies_immediately: true,
      eq_applies_immediately: true,
    },
  },
  settings: {
    active: clone(activeSettings),
    draft: clone(activeSettings),
    change: {
      changed_sections: [],
      runtime_config_changed: false,
      changed_runtime_fields: [],
      runtime_config_fields: [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
      ],
      live_preview_reprocessable_field_names: [],
    },
  },
  armed: false,
  is_recording: false,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  participant_count: 0,
};
state.draft = clone(activeSettings);

state.draft.layers.low.enabled = false;
state.snapshot.settings.draft.layers.low.enabled = false;

commitDraftChange(() => {
  state.draft.layers.low.volume_db = -6;
}, { feedbackControlId: "layers.low.volume_db", scheduleSave: false });

let releaseFetch;
const fetchGate = new Promise((resolve) => { releaseFetch = resolve; });
globalThis.fetch = async () => {
  await fetchGate;
  return {
    ok: false,
    status: 500,
    json: async () => ({ detail: "backend hot swap failed" }),
  };
};

renderLayerControls();
const savePromise = saveDraft();
const lowCardDuringSave = document.getElementById("layerControls").children[1];
assert.match(lowCardDuringSave.className, /\\bfeedback-pending\\b/);
assert.doesNotMatch(
  lowCardDuringSave.innerHTML,
  /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
);

releaseFetch();
await assert.rejects(savePromise, /backend hot swap failed/);

renderLayerControls();
const lowCardAfterFailure = document.getElementById("layerControls").children[1];
const feedbackStateAfterFailure = deriveCoveredSurfaceFeedbackState({ surfaceId: "layer:low" });

assert.strictEqual(state.draftSaveInFlight, false);
assert.strictEqual(state.coveredFeedbackSurfaceId, undefined);
assert.strictEqual(state.liveFeedbackSurfaceId, undefined);
assert.deepStrictEqual(feedbackStateAfterFailure, { visual_state: "idle", show_spinner: false });
assert.doesNotMatch(lowCardAfterFailure.className, /\\bfeedback-pending\\b/);
assert.match(
  lowCardAfterFailure.innerHTML,
  /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
);
assert.strictEqual(state.draft.layers.low.volume_db, 0);
assert.strictEqual(state.draft.layers.low.enabled, false);
})();
""",
    )


def test_stable_successful_apply_clears_covered_card_highlights() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
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
(async () => {
const {
  applyAndRestart,
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
const draftSettings = clone(activeSettings);
draftSettings.layers.low.volume_db = -1;
draftSettings.voice_stack.transition_seconds = 7;
draftSettings.recording.gain_db = 3;
const appliedSettings = clone(draftSettings);

const stablePlayback = {
  apply_mode: "stable",
  output_running: true,
  rendered_cache_ready: true,
  active_voice_transition_target_id: null,
  position_seconds: 0,
  duration_seconds: 60,
  progress: 0,
};
const changePayload = {
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
};
const snapshotFor = (active, draft, change = changePayload) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(active),
    draft: clone(draft),
    change: clone(change),
  },
  playback: clone(stablePlayback),
});
const renderCoveredSurfaces = () => {
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingControls();
};
const coveredSurfaces = () => ({
  low: document.getElementById("layerControls").children[1],
  voiceStack: document.getElementById("voiceStackControls"),
  recording: document.getElementById("recordingControls"),
});
const assertCoveredPending = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should be pending`);
  }
};
const assertCoveredIdle = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.doesNotMatch(surface.className, /\\bfeedback-pending\\b/, `${key} should be idle`);
    assert.match(
      surface.innerHTML,
      /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
      `${key} spinner should be hidden`,
    );
  }
};

state.snapshot = snapshotFor(activeSettings, activeSettings, {
  runtime_config_changed: false,
  changed_sections: [],
  changed_runtime_fields: [],
  runtime_config_fields: changePayload.runtime_config_fields,
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
});
state.draft = clone(draftSettings);
state.serverStateSignature = null;

renderCoveredSurfaces();
assertCoveredPending();

const requests = [];
globalThis.fetch = async (path) => {
  requests.push(path);
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, draftSettings).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          state: snapshotFor(appliedSettings, appliedSettings, {
            runtime_config_changed: false,
            changed_sections: [],
            changed_runtime_fields: [],
            runtime_config_fields: changePayload.runtime_config_fields,
            live_preview_reprocessable_fields: [],
            live_preview_reprocessable_field_names: [],
          }),
        };
      },
    };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

assert.deepStrictEqual(requests, [
  "/api/settings/draft",
  "/api/settings/apply",
  "/api/diagnostics",
  "/api/sources",
]);
assert.strictEqual(state.draft.layers.low.volume_db, -1);
assert.strictEqual(state.snapshot.settings.active.layers.low.volume_db, -1);
assert.strictEqual(state.snapshot.settings.draft.layers.low.volume_db, -1);
assert.strictEqual(state.snapshot.settings.active.voice_stack.transition_seconds, 7);
assert.strictEqual(state.snapshot.settings.draft.voice_stack.transition_seconds, 7);
assert.strictEqual(state.snapshot.settings.active.recording.gain_db, 3);
assert.strictEqual(state.snapshot.settings.draft.recording.gain_db, 3);
assertCoveredIdle();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_stable_successful_apply_clears_restart_spinners_before_refresh_requests() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
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
(async () => {
const {
  applyAndRestart,
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
const draftSettings = clone(activeSettings);
draftSettings.layers.low.volume_db = -1;
draftSettings.voice_stack.transition_seconds = 7;
draftSettings.recording.gain_db = 3;
const cleanChange = {
  runtime_config_changed: false,
  changed_sections: [],
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
};
const snapshotFor = (active, draft) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: { active: clone(active), draft: clone(draft), change: clone(cleanChange) },
  playback: {
    apply_mode: "stable",
    output_running: true,
    rendered_cache_ready: true,
    active_voice_transition_target_id: null,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
  },
});
const lowCard = () => document.getElementById("layerControls").children[1];
const coveredSurfaces = () => ({
  low: lowCard(),
  voiceStack: document.getElementById("voiceStackControls"),
  recording: document.getElementById("recordingControls"),
});
const renderCoveredSurfaces = () => {
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingControls();
};
const assertCoveredSpinnersVisible = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should be pending`);
    assert.doesNotMatch(
      surface.innerHTML,
      /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
      `${key} spinner should be visible`,
    );
  }
};
const assertCoveredSpinnersHidden = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.doesNotMatch(surface.className, /\\bfeedback-pending\\b/, `${key} should be idle`);
    assert.match(
      surface.innerHTML,
      /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
      `${key} spinner should be hidden`,
    );
  }
};

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(draftSettings);
state.serverStateSignature = null;

renderCoveredSurfaces();
for (const [key, surface] of Object.entries(coveredSurfaces())) {
  assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should start pending`);
}

globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, draftSettings).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    assertCoveredSpinnersVisible();
    return {
      ok: true,
      status: 200,
      async json() {
        return { state: snapshotFor(draftSettings, draftSettings) };
      },
    };
  }
  if (path === "/api/diagnostics") {
    assertCoveredSpinnersHidden();
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();
assertCoveredSpinnersHidden();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_stable_failure_rollback_hides_restart_spinners_before_refresh() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
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
(async () => {
const {
  applyAndRestart,
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
const failedDraft = clone(activeSettings);
failedDraft.layers.low.volume_db = -1;
failedDraft.layers.mid.eq.mid_gain_db = 2;
failedDraft.layers.voice.enabled = false;
failedDraft.voice_stack.transition_seconds = 7;
failedDraft.recording.presence_gain_db = 1;
const cleanChange = {
  runtime_config_changed: false,
  changed_sections: [],
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
};
const changeFor = (active, draft) => ({
  ...cleanChange,
  changed_sections: Object.keys(draft).filter((section) => (
    JSON.stringify(active[section]) !== JSON.stringify(draft[section])
  )),
});
const snapshotFor = (active, draft) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: { active: clone(active), draft: clone(draft), change: changeFor(active, draft) },
  playback: {
    apply_mode: "stable",
    output_running: true,
    rendered_cache_ready: true,
    active_voice_transition_target_id: null,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
  },
});
const renderCoveredSurfaces = () => {
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingControls();
};
const coveredSurfaces = () => ({
  low: document.getElementById("layerControls").children[1],
  mid: document.getElementById("layerControls").children[0],
  voice: document.getElementById("voiceLayerControls").children[0],
  voiceStack: document.getElementById("voiceStackControls"),
  recording: document.getElementById("recordingControls"),
});
const assertCoveredSpinnersVisible = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should be pending`);
    assert.doesNotMatch(
      surface.innerHTML,
      /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
      `${key} spinner should be visible`,
    );
  }
};
const assertRollbackSpinnersHidden = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.doesNotMatch(surface.className, /\\bfeedback-pending\\b/, `${key} should be idle`);
    assert.match(
      surface.innerHTML,
      /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
      `${key} spinner should be hidden after rollback`,
    );
  }
};

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(failedDraft);
state.serverStateSignature = null;

renderCoveredSurfaces();
for (const [key, surface] of Object.entries(coveredSurfaces())) {
  assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should start pending`);
}

globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, failedDraft).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    assertCoveredSpinnersVisible();
    return {
      ok: false,
      status: 500,
      async json() { return { detail: "render failed" }; },
    };
  }
  if (path === "/api/state") {
    return {
      ok: true,
      status: 200,
      async json() {
        return snapshotFor(activeSettings, failedDraft);
      },
    };
  }
  if (path === "/api/diagnostics") {
    assertRollbackSpinnersHidden();
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    assertRollbackSpinnersHidden();
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();
assertRollbackSpinnersHidden();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_stable_successful_apply_clears_highlights_when_response_draft_is_stale() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
  renderLayerControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const { applyAndRestart, renderLayerControls, state } = globalThis.__secretPond;

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
const draftSettings = clone(activeSettings);
draftSettings.layers.low.volume_db = -1;
const appliedSettings = clone(draftSettings);
const cleanChange = {
  runtime_config_changed: false,
  changed_sections: [],
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
};
const snapshotFor = (active, draft, change = cleanChange) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: { active: clone(active), draft: clone(draft), change: clone(change) },
  playback: {
    apply_mode: "stable",
    output_running: true,
    rendered_cache_ready: true,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
  },
});

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(draftSettings);
state.serverStateSignature = null;

renderLayerControls();
let lowCard = document.getElementById("layerControls").children[1];
assert.match(lowCard.className, /\\bfeedback-pending\\b/);

globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, draftSettings).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    return {
      ok: true,
      status: 200,
      async json() {
        return { state: snapshotFor(appliedSettings, activeSettings, cleanChange) };
      },
    };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

assert.strictEqual(state.snapshot.settings.active.layers.low.volume_db, -1);
assert.strictEqual(state.snapshot.settings.draft.layers.low.volume_db, -1);
assert.strictEqual(state.draft.layers.low.volume_db, -1);
lowCard = document.getElementById("layerControls").children[1];
assert.doesNotMatch(lowCard.className, /\\bfeedback-pending\\b/);
assert.match(lowCard.innerHTML, /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_stable_successful_apply_renders_latest_confirmed_control_values() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
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
(async () => {
const {
  applyAndRestart,
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
const draftSettings = clone(activeSettings);
draftSettings.layers.low.volume_db = -1;
draftSettings.voice_stack.transition_seconds = 7;
draftSettings.recording.gain_db = 3;
const appliedSettings = clone(draftSettings);
const cleanChange = {
  runtime_config_changed: false,
  changed_sections: [],
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
};
const snapshotFor = (active, draft, change = cleanChange) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: { active: clone(active), draft: clone(draft), change: clone(change) },
  playback: {
    apply_mode: "stable",
    output_running: true,
    rendered_cache_ready: true,
    position_seconds: 0,
    duration_seconds: 60,
    progress: 0,
  },
});
const renderedMarkupFor = (rootId) => {
  const root = document.getElementById(rootId);
  const serialize = (element) => [
    element.className,
    element.textContent,
    element.innerHTML,
    ...(element.children || []).map(serialize),
  ].join("\\n");
  return serialize(root);
};

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(draftSettings);
state.serverStateSignature = null;

renderLayerControls();
renderVoiceStackControls();
renderRecordingControls();
assert.match(renderedMarkupFor("voiceStackControls"), /value="7"/);
assert.match(renderedMarkupFor("recordingControls"), /value="3"/);

globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, draftSettings).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    return {
      ok: true,
      status: 200,
      async json() {
        return { state: snapshotFor(appliedSettings, activeSettings, cleanChange) };
      },
    };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

assert.strictEqual(state.snapshot.settings.active.layers.low.volume_db, -1);
assert.strictEqual(state.draft.layers.low.volume_db, -1);
assert.match(renderedMarkupFor("voiceStackControls"), /value="7"/);
assert.match(renderedMarkupFor("recordingControls"), /value="3"/);
assert.match(renderedMarkupFor("voiceStackControls"), /현재값 7 s/);
assert.match(renderedMarkupFor("recordingControls"), /현재값 3 dB/);
assert.doesNotMatch(renderedMarkupFor("voiceStackControls"), /현재 적용 4 s/);
assert.doesNotMatch(renderedMarkupFor("recordingControls"), /현재 적용 0 dB/);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
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


def test_stable_apply_failure_rolls_back_only_captured_differing_covered_controls() -> None:
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
const clone = (value) => JSON.parse(JSON.stringify(value));
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
const draftSettings = clone(activeSettings);
draftSettings.layers.low.volume_db = -1;
draftSettings.layers.low.eq.low_gain_db = 4;
draftSettings.voice_stack.transition_seconds = 7;
draftSettings.recording.gain_db = 3;
draftSettings.playback.master_volume_db = -6;

const changeFor = (active, draft) => ({
  runtime_config_changed: false,
  changed_sections: Object.keys(draft).filter((section) => (
    JSON.stringify(active[section]) !== JSON.stringify(draft[section])
  )),
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
});
const snapshotFor = (active, draft) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(active),
    draft: clone(draft),
    change: changeFor(active, draft),
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
});

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(draftSettings);
state.serverStateSignature = null;

const requests = [];
globalThis.fetch = async (path) => {
  requests.push(path);
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, draftSettings).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    return {
      ok: false,
      status: 500,
      async json() { return { detail: "render failed" }; },
    };
  }
  if (path === "/api/state") {
    return {
      ok: true,
      status: 200,
      async json() { return snapshotFor(activeSettings, draftSettings); },
    };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

assert.deepStrictEqual(requests, [
  "/api/settings/draft",
  "/api/settings/apply",
  "/api/state",
  "/api/diagnostics",
  "/api/sources",
]);
assert.strictEqual(state.draft.layers.low.volume_db, -3);
assert.strictEqual(state.draft.layers.low.eq.low_gain_db, 0);
assert.strictEqual(state.draft.layers.low.eq.mid_gain_db, 0);
assert.strictEqual(state.draft.voice_stack.transition_seconds, 4);
assert.strictEqual(state.draft.recording.gain_db, 0);
assert.strictEqual(state.draft.playback.master_volume_db, -6);
assert.strictEqual(state.snapshot.settings.draft.layers.low.volume_db, -3);
assert.strictEqual(state.snapshot.settings.draft.layers.low.eq.low_gain_db, 0);
assert.strictEqual(state.snapshot.settings.draft.voice_stack.transition_seconds, 4);
assert.strictEqual(state.snapshot.settings.draft.recording.gain_db, 0);
assert.strictEqual(state.snapshot.settings.draft.playback.master_volume_db, -6);
assert.strictEqual(state.snapshot.settings.active.playback.master_volume_db, -9);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_stable_apply_failure_rollbacks_clear_all_covered_surface_highlights() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
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
(async () => {
const {
  applyAndRestart,
  renderLayerControls,
  renderRecordingControls,
  renderVoiceStackControls,
  state,
} = globalThis.__secretPond;
const clone = (value) => JSON.parse(JSON.stringify(value));
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
const failedDraft = clone(activeSettings);
failedDraft.layers.low.volume_db = -1;
failedDraft.layers.mid.eq.mid_gain_db = 2;
failedDraft.layers.voice.enabled = false;
failedDraft.voice_stack.transition_seconds = 7;
failedDraft.recording.presence_gain_db = 1;

const changeFor = (active, draft) => ({
  runtime_config_changed: false,
  changed_sections: Object.keys(draft).filter((section) => (
    JSON.stringify(active[section]) !== JSON.stringify(draft[section])
  )),
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
});
const snapshotFor = (active, draft) => ({
  armed: true,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(active),
    draft: clone(draft),
    change: changeFor(active, draft),
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
});
const renderCoveredSurfaces = () => {
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingControls();
};
const coveredSurfaces = () => ({
  low: document.getElementById("layerControls").children[1],
  mid: document.getElementById("layerControls").children[0],
  voice: document.getElementById("voiceLayerControls").children[0],
  voiceStack: document.getElementById("voiceStackControls"),
  recording: document.getElementById("recordingControls"),
});
const assertCoveredPending = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.match(surface.className, /\\bfeedback-pending\\b/, `${key} should be pending`);
  }
};
const assertCoveredIdle = () => {
  for (const [key, surface] of Object.entries(coveredSurfaces())) {
    assert.doesNotMatch(surface.className, /\\bfeedback-pending\\b/, `${key} should be idle`);
    assert.match(
      surface.innerHTML,
      /class="feedback-spinner"[^>]*\\shidden(?=[\\s>])/,
      `${key} spinner should be hidden`,
    );
  }
};

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(failedDraft);
state.serverStateSignature = null;

renderCoveredSurfaces();
assertCoveredPending();

globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, failedDraft).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    assertCoveredPending();
    return {
      ok: false,
      status: 500,
      async json() { return { detail: "render failed" }; },
    };
  }
  if (path === "/api/state") {
    return {
      ok: true,
      status: 200,
      async json() { return snapshotFor(activeSettings, failedDraft); },
    };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

assert.strictEqual(state.draft.layers.low.volume_db, -3);
assert.strictEqual(state.draft.layers.mid.eq.mid_gain_db, 0);
assert.strictEqual(state.draft.layers.voice.enabled, true);
assert.strictEqual(state.draft.voice_stack.transition_seconds, 4);
assert.strictEqual(state.draft.recording.presence_gain_db, -3);
assertCoveredIdle();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )


def test_stable_apply_failure_does_not_rollback_new_post_restart_diffs() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applyAndRestart,
  serverStateSignature,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
        body="""
(async () => {
const { applyAndRestart, serverStateSignature, state } = globalThis.__secretPond;
const clone = (value) => JSON.parse(JSON.stringify(value));
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
const restartDraft = clone(activeSettings);
restartDraft.layers.low.volume_db = -1;
restartDraft.recording.gain_db = 3;

const postFailureDraft = clone(restartDraft);
postFailureDraft.layers.mid.volume_db = -8;
postFailureDraft.voice_stack.transition_seconds = 9;

const changeFor = (active, draft) => ({
  runtime_config_changed: false,
  changed_sections: Object.keys(draft).filter((section) => (
    JSON.stringify(active[section]) !== JSON.stringify(draft[section])
  )),
  changed_runtime_fields: [],
  runtime_config_fields: [
    "audio.sample_rate",
    "audio.channels",
    "devices.input_device_id",
    "devices.output_device_id",
  ],
  live_preview_reprocessable_fields: [],
  live_preview_reprocessable_field_names: [],
});
const snapshotFor = (active, draft) => ({
  armed: false,
  is_recording: false,
  participant_count: 0,
  recording_elapsed_seconds: 0,
  recording_remaining_seconds: 120,
  settings: {
    active: clone(active),
    draft: clone(draft),
    change: changeFor(active, draft),
  },
  playback: { output_running: true, frame_cursor: 1200, apply_mode: "stable" },
});

state.snapshot = snapshotFor(activeSettings, activeSettings);
state.draft = clone(restartDraft);
state.serverStateSignature = null;

let capturedAtRestart = null;
globalThis.fetch = async (path) => {
  if (path === "/api/settings/draft") {
    return {
      ok: true,
      status: 200,
      async json() { return { settings: snapshotFor(activeSettings, restartDraft).settings }; },
    };
  }
  if (path === "/api/settings/apply") {
    capturedAtRestart = clone(state.stableApplyCoveredFeedbackControlSnapshots);
    state.draft = clone(postFailureDraft);
    state.snapshot.settings.draft = clone(postFailureDraft);
    return {
      ok: false,
      status: 500,
      async json() { return { detail: "render failed" }; },
    };
  }
  if (path === "/api/state") {
    return {
      ok: true,
      status: 200,
      async json() { return snapshotFor(activeSettings, postFailureDraft); },
    };
  }
  if (path === "/api/diagnostics") {
    return {
      ok: true,
      status: 200,
      async json() { return { sources: [], events: { recent: [] } }; },
    };
  }
  if (path === "/api/sources") {
    return { ok: true, status: 200, async json() { return { categories: [] }; } };
  }
  throw new Error(`unexpected ${path}`);
};

await applyAndRestart();

assert.deepStrictEqual(capturedAtRestart, [
  { controlId: "layers.low.volume_db", activeValue: -3, draftValue: -1 },
  { controlId: "recording.gain_db", activeValue: 0, draftValue: 3 },
]);
assert.strictEqual(state.draft.layers.low.volume_db, -3);
assert.strictEqual(state.draft.recording.gain_db, 0);
assert.strictEqual(state.draft.layers.mid.volume_db, -8);
assert.strictEqual(state.draft.voice_stack.transition_seconds, 9);
assert.strictEqual(state.snapshot.settings.draft.layers.low.volume_db, -3);
assert.strictEqual(state.snapshot.settings.draft.recording.gain_db, 0);
assert.strictEqual(state.snapshot.settings.draft.layers.mid.volume_db, -8);
assert.strictEqual(state.snapshot.settings.draft.voice_stack.transition_seconds, 9);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
""",
    )
