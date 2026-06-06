from __future__ import annotations

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

    assert (
        '<section id="playbackPanel" class="operation-card playback-panel" '
        'aria-labelledby="playbackPanelTitle">'
    ) in index_html
    assert 'id="playbackPanel" class="operation-card playback-panel feedback-pending"' not in (
        index_html
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
    operationFlags: { draftSaveInFlight: true },
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
    operationFlags: { draftSaveInFlight: true },
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
