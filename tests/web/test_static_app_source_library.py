from __future__ import annotations

from pathlib import Path

from static_app_harness import STATIC_APP_BOOTSTRAP, STATIC_APP_RENDER_DOM_SETUP, run_node_harness


def test_active_source_select_survives_source_library_refresh() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderSourceLibrary,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderSourceLibrary, state, trackInteractiveControl } = globalThis.__secretPond;
const sourceLibraryList = document.getElementById("sourceLibraryList");
const sourceLibraryStatus = document.getElementById("sourceLibraryStatus");
const activeSelect = document.createElement("select");
activeSelect.setAttribute("data-source-select", "low");
activeSelect.value = "data/sources/low/original.wav";
sourceLibraryList.appendChild(activeSelect);
sourceLibraryList.innerHTML = [
  "<select data-source-select=\\"low\\\">",
  "<option>original</option>",
  "</select>",
].join("");
sourceLibraryList.appendChild(activeSelect);
sourceLibraryStatus.textContent = "파일 준비됨";

trackInteractiveControl(activeSelect);
state.sources = {
  categories: [{
    id: "low",
    label: "Low",
    settings_field: "low_path",
    required: true,
    directory: "data/sources/low",
    active_exists: true,
    legacy_exists: false,
    selected_path: "data/sources/low/refreshed.wav",
    files: [{
      name: "refreshed.wav",
      path: "data/sources/low/refreshed.wav",
      size_bytes: 2048,
      modified_at: "2026-06-05T00:00:00Z",
      active: true,
      applied: true,
    }],
  }],
};

renderSourceLibrary();

assert.strictEqual(sourceLibraryList.children.length, 1);
assert.strictEqual(sourceLibraryList.children[0], activeSelect);
assert.strictEqual(activeSelect.value, "data/sources/low/original.wav");
assert.strictEqual(state.deferredInteractiveRenders["source-library"], renderSourceLibrary);
assert.strictEqual(sourceLibraryStatus.textContent, "파일 준비됨");
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_active_source_upload_mode_survives_playback_refresh_render() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderOperationLockSurfaces,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderOperationLockSurfaces, state, trackInteractiveControl } = globalThis.__secretPond;
const sourceLibraryList = document.getElementById("sourceLibraryList");
const sourceLibraryStatus = document.getElementById("sourceLibraryStatus");
const activeUploadMode = document.createElement("input");
activeUploadMode.setAttribute("data-source-upload-select", "low");
activeUploadMode.checked = false;
sourceLibraryList.appendChild(activeUploadMode);
sourceLibraryStatus.textContent = "파일 준비됨";

trackInteractiveControl(activeUploadMode);
state.playbackControlInFlight = true;
state.sources = {
  categories: [{
    id: "low",
    label: "Low",
    settings_field: "low_path",
    required: true,
    directory: "data/sources/low",
    active_exists: true,
    legacy_exists: false,
    selected_path: "data/sources/low/refreshed.wav",
    files: [{
      name: "refreshed.wav",
      path: "data/sources/low/refreshed.wav",
      size_bytes: 2048,
      modified_at: "2026-06-05T00:00:00Z",
      active: true,
      applied: true,
    }],
  }],
};

renderOperationLockSurfaces();

assert.strictEqual(sourceLibraryList.children.length, 1);
assert.strictEqual(sourceLibraryList.children[0], activeUploadMode);
assert.strictEqual(activeUploadMode.checked, false);
assert.strictEqual(state.deferredInteractiveRenders["source-library"].name, "renderSourceLibrary");
assert.strictEqual(sourceLibraryStatus.textContent, "파일 준비됨");
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_focused_source_dropdown_survives_playback_refresh_render() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderOperationLockSurfaces,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderOperationLockSurfaces, state } = globalThis.__secretPond;
const sourceLibraryList = document.getElementById("sourceLibraryList");
const sourceLibraryStatus = document.getElementById("sourceLibraryStatus");
const activeSelect = document.createElement("select");
activeSelect.setAttribute("data-source-select", "low");
activeSelect.value = "data/sources/low/open-menu.wav";
sourceLibraryList.appendChild(activeSelect);
sourceLibraryStatus.textContent = "파일 준비됨";
document.activeElement = activeSelect;
state.playbackControlInFlight = true;
state.sources = {
  categories: [{
    id: "low",
    label: "Low",
    settings_field: "low_path",
    required: true,
    directory: "data/sources/low",
    active_exists: true,
    legacy_exists: false,
    selected_path: "data/sources/low/refreshed.wav",
    files: [{
      name: "refreshed.wav",
      path: "data/sources/low/refreshed.wav",
      size_bytes: 2048,
      modified_at: "2026-06-05T00:00:00Z",
      active: true,
      applied: true,
    }],
  }],
};

renderOperationLockSurfaces();

assert.strictEqual(sourceLibraryList.children.length, 1);
assert.strictEqual(sourceLibraryList.children[0], activeSelect);
assert.strictEqual(activeSelect.value, "data/sources/low/open-menu.wav");
assert.strictEqual(state.activeInteractiveControl, activeSelect);
assert.strictEqual(state.deferredInteractiveRenders["source-library"].name, "renderSourceLibrary");
assert.strictEqual(sourceLibraryStatus.textContent, "파일 준비됨");
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_source_delete_response_rerenders_even_while_delete_button_is_active() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  applySourceMutationPayload,
  state,
  trackInteractiveControl,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { applySourceMutationPayload, state, trackInteractiveControl } = globalThis.__secretPond;
const sourceLibraryList = document.getElementById("sourceLibraryList");
const sourceLibraryStatus = document.getElementById("sourceLibraryStatus");
const staleDeleteButton = document.createElement("button");
staleDeleteButton.setAttribute("data-source-delete", "voice_raw");
staleDeleteButton.setAttribute("data-source-path", "data/sources/voice/raw/VR0610_213112.wav");
sourceLibraryList.appendChild(staleDeleteButton);
sourceLibraryStatus.textContent = "파일 준비됨";
state.sourceMutationInFlight = true;
trackInteractiveControl(staleDeleteButton);

const payload = {
  state_revision: 1,
  sources: {
    categories: [{
      id: "voice_raw",
      label: "Voice Raw",
      settings_field: "voice_raw_path",
      required: false,
      directory: "data/sources/voice/raw",
      active_exists: false,
      legacy_exists: false,
      selected_path: null,
      files: [],
    }],
  },
};

assert.strictEqual(applySourceMutationPayload(payload), true);

assert.strictEqual(sourceLibraryList.children.length, 1);
assert.notStrictEqual(sourceLibraryList.children[0], staleDeleteButton);
assert.strictEqual(state.deferredInteractiveRenders["source-library"], undefined);
assert.strictEqual(sourceLibraryStatus.textContent, "파일 준비됨");
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_expanded_recording_detail_row_survives_state_refresh_render() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderRecordingControls,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderRecordingControls, state } = globalThis.__secretPond;
const recordingControls = document.getElementById("recordingControls");
const recordingSettings = {
  highpass_hz: 80,
  lowpass_hz: 12000,
  presence_gain_db: 0,
  gain_db: 0,
  normalize_peak: 0.4,
  reverb_mix: 0.25,
  reverb_decay: 2.5,
  delay_mix: 0.1,
  delay_seconds: 0.25,
};
state.draft = { recording: { ...recordingSettings } };
state.snapshot = {
  settings: {
    active: { recording: { ...recordingSettings } },
  },
  playback: { output_running: true },
};

renderRecordingControls();
const inputSafetyDetails = recordingControls.children[1];
const spaceTailDetails = recordingControls.children[2];
assert.strictEqual(inputSafetyDetails.tagName, "DETAILS");
assert.strictEqual(spaceTailDetails.tagName, "DETAILS");
assert.strictEqual(inputSafetyDetails.open, true);
assert.strictEqual(spaceTailDetails.open, true);

inputSafetyDetails.open = false;
inputSafetyDetails.dispatchEvent({ type: "toggle" });
renderRecordingControls();

assert.strictEqual(recordingControls.children[1].tagName, "DETAILS");
assert.strictEqual(recordingControls.children[2].tagName, "DETAILS");
assert.strictEqual(recordingControls.children[1].open, false);
assert.strictEqual(recordingControls.children[2].open, true);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )


def test_open_technical_notice_panel_survives_playback_state_refresh() -> None:
    app_script = Path("src/secret_pond/web/static/app.js").read_text(encoding="utf-8")
    app_script = app_script.replace(STATIC_APP_BOOTSTRAP, "")
    app_script += """
globalThis.__secretPond = {
  renderErrors,
  state,
};
"""
    app_script = f"(() => {{\n{app_script}\n}})();"

    run_node_harness(
        script=app_script,
        body="""
const { renderErrors, state } = globalThis.__secretPond;
const errorBanner = document.getElementById("errorBanner");
state.devices = {
  warnings: ["Selected output default sample rate is 44100, but settings request 48000."],
};
state.snapshot = {
  playback: { output_running: true, frame_cursor: 1200 },
};

renderErrors();
const technicalDetails = errorBanner.children[2];
assert.strictEqual(technicalDetails.tagName, "DETAILS");
assert.strictEqual(technicalDetails.open, false);

technicalDetails.open = true;
state.snapshot = {
  playback: { output_running: true, frame_cursor: 2400 },
};
renderErrors();

assert.strictEqual(errorBanner.children[2].tagName, "DETAILS");
assert.strictEqual(errorBanner.children[2].open, true);
""",
        dom_setup=STATIC_APP_RENDER_DOM_SETUP,
    )
