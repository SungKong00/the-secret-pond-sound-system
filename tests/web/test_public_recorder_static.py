from __future__ import annotations

from pathlib import Path

from static_app_harness import run_node_harness

STATIC_DIR = Path("src/secret_pond/web/static")


def public_recorder_script() -> str:
    return (STATIC_DIR / "public_recorder.js").read_text(encoding="utf-8")


def test_public_recorder_html_links_assets_and_states_limits() -> None:
    html = (STATIC_DIR / "public_recorder.html").read_text(encoding="utf-8")

    assert "public_recorder.css" in html
    assert "public_recorder.js" in html
    assert "3초" in html
    assert "10분" in html
    assert "25MB" in html


def test_public_recorder_disables_stop_before_three_seconds() -> None:
    script = public_recorder_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_RECORDER_DOM_SETUP,
        body="""
        const api = window.SecretPondPublicRecorder._test;
        api.updateElapsedSeconds(2.9);
        assert.strictEqual(document.getElementById("stopButton").disabled, true);
        api.updateElapsedSeconds(3.0);
        assert.strictEqual(document.getElementById("stopButton").disabled, false);
        """,
    )


def test_public_recorder_blocks_large_blob_before_upload() -> None:
    script = public_recorder_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_RECORDER_DOM_SETUP,
        body="""
        let fetchCalled = false;
        globalThis.fetch = async () => {
          fetchCalled = true;
          return { ok: true, json: async () => ({}) };
        };
        const api = window.SecretPondPublicRecorder._test;
        api.setRecordedBlob({ size: 25 * 1024 * 1024 + 1 });
        api.submitRecording();
        assert.strictEqual(fetchCalled, false);
        assert.match(document.getElementById("statusMessage").textContent, /파일이 너무 큽니다/);
        """,
    )


PUBLIC_RECORDER_DOM_SETUP = """
const elements = {};
const makeElement = (id = "") => ({
  id,
  disabled: false,
  hidden: false,
  textContent: "",
  className: "",
  listeners: {},
  addEventListener(eventName, handler) {
    this.listeners[eventName] = handler;
  },
  setAttribute() {},
  removeAttribute() {},
});
globalThis.document = {
  getElementById(id) {
    if (!elements[id]) elements[id] = makeElement(id);
    return elements[id];
  },
  addEventListener(eventName, handler) {
    if (eventName === "DOMContentLoaded") handler();
  },
};
globalThis.window = {
  location: { pathname: "/r/record-token" },
  addEventListener() {},
};
globalThis.navigator = {
  mediaDevices: {
    getUserMedia: async () => ({ getTracks: () => [] }),
  },
};
globalThis.MediaRecorder = function MediaRecorder() {};
globalThis.FormData = function FormData() {
  this.append = () => {};
};
globalThis.setInterval = () => 1;
globalThis.clearInterval = () => {};
globalThis.setTimeout = (handler) => {
  handler();
  return 1;
};
"""
