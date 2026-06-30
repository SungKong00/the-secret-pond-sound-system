from __future__ import annotations

from pathlib import Path

from static_app_harness import run_node_harness

STATIC_DIR = Path("src/secret_pond/web/static")


def public_recorder_script() -> str:
    return (STATIC_DIR / "public_recorder.js").read_text(encoding="utf-8")


def test_public_recorder_html_uses_confessional_copy_without_extra_notice_blocks() -> None:
    html = (STATIC_DIR / "public_recorder.html").read_text(encoding="utf-8")

    assert "public_recorder.css" in html
    assert "public_recorder.js" in html
    assert "비밀의 연못" in html
    assert "비밀 고해소" in html
    assert "누구에게도 전달되거나 들려지지 않습니다" in html
    assert "비밀의 연못에 고입니다" in html
    assert "정말로 말 못할 비밀이든, 후회하는 말이든, 끝내 전하지 못하는 진심이든," in html
    assert "혹은 누군가 알아줬으면 하지만 동시에 아무도 알지 않았으면 하는 속마음" in html
    assert "말하기" in html
    assert "그만두기" in html
    assert "다시하기" in html
    assert "두고가기" in html
    assert 'class="stack-line"' in html
    assert 'class="confession-line"' in html
    assert 'class="invitation-line"' in html
    assert "limit-grid" not in html
    assert "privacy-note" not in html
    assert "rollback-note" not in html
    assert "녹음 원본" not in html
    assert "두고 간 뒤" not in html


def test_public_recorder_css_is_dark_and_places_primary_actions_side_by_side() -> None:
    css = (STATIC_DIR / "public_recorder.css").read_text(encoding="utf-8")

    assert "color-scheme: dark" in css
    assert "background: #050706" in css
    assert ".actions" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css


def test_public_recorder_css_sets_typographic_hierarchy() -> None:
    css = (STATIC_DIR / "public_recorder.css").read_text(encoding="utf-8")

    assert ".intro-copy {" in css
    assert "font-size: 0.875rem;" in css
    assert ".intro-copy .assurance" in css
    assert "font-size: 1.05rem;" in css
    assert ".intro-copy .confession-line" in css
    assert "font-size: 0.94rem;" in css
    assert ".status {" in css
    assert "font-size: 0.875rem;" in css


def test_public_recorder_uses_confessional_status_copy() -> None:
    script = public_recorder_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_RECORDER_DOM_SETUP,
        body="""
        (async () => {
          const api = window.SecretPondPublicRecorder._test;
          globalThis.fetch = async () => ({
            ok: true,
            json: async () => ({ version_id: "stack-1" }),
          });
          api.setRecordedBlob({ size: 1024, type: "audio/webm" });
          const result = await api.submitRecording();

          assert.deepStrictEqual(result, { version_id: "stack-1" });
          assert.strictEqual(document.getElementById("recordState").textContent, "완료");
          assert.strictEqual(document.getElementById("statusMessage").textContent, "");
        })().catch((error) => {
          console.error(error);
          process.exitCode = 1;
        });
        """,
    )


def test_public_recorder_ready_state_keeps_start_and_stop_buttons_muted() -> None:
    script = public_recorder_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_RECORDER_DOM_SETUP,
        body="""
        const api = window.SecretPondPublicRecorder._test;
        api.setRecordedBlob({ size: 1024, type: "audio/webm" });

        assert.strictEqual(document.getElementById("startButton").disabled, true);
        assert.strictEqual(document.getElementById("stopButton").disabled, true);
        assert.strictEqual(document.getElementById("rerecordButton").hidden, false);
        assert.strictEqual(document.getElementById("addButton").hidden, false);
        """,
    )


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


def test_public_recorder_maps_duration_rejection_codes_to_specific_messages() -> None:
    script = public_recorder_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_RECORDER_DOM_SETUP,
        body="""
        (async () => {
          const api = window.SecretPondPublicRecorder._test;
          const responses = [
            { detail: "too_short", pattern: /녹음이 3초보다 짧습니다/ },
            { detail: "too_long", pattern: /녹음이 10분보다 깁니다/ },
          ];
          for (const responseBody of responses) {
            globalThis.fetch = async () => ({
              ok: false,
              json: async () => ({ detail: responseBody.detail }),
            });
            api.setRecordedBlob({ size: 1024, type: "audio/webm" });
            await api.submitRecording();
            assert.match(
              document.getElementById("statusMessage").textContent,
              responseBody.pattern,
            );
          }
        })().catch((error) => {
          console.error(error);
          process.exitCode = 1;
        });
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
