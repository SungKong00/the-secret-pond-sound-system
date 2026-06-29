from __future__ import annotations

from pathlib import Path

from static_app_harness import run_node_harness

STATIC_DIR = Path("src/secret_pond/web/static")


def public_admin_script() -> str:
    return (STATIC_DIR / "public_admin.js").read_text(encoding="utf-8")


def test_public_admin_html_links_assets_and_admin_shell() -> None:
    html = (STATIC_DIR / "public_admin.html").read_text(encoding="utf-8")

    assert "Voice Stack Admin" in html
    assert "public_admin.css" in html
    assert "public_admin.js" in html
    assert "versionsList" in html


def test_public_admin_renders_active_and_deleted_version_actions() -> None:
    script = public_admin_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_ADMIN_DOM_SETUP,
        body="""
        const api = window.SecretPondPublicAdmin._test;
        api.state.versions = [
          {
            id: "active-version",
            kind: "commit",
            created_at: "2026-06-29T12:00:00Z",
            duration_seconds: 13,
            file_size: 2048,
            added_chunks: 1,
            gain_reduction_db: 0,
            deleted_at: null,
          },
          {
            id: "deleted-version",
            kind: "seed",
            created_at: "2026-06-29T11:00:00Z",
            duration_seconds: 10,
            file_size: 1024,
            added_chunks: 0,
            gain_reduction_db: null,
            deleted_at: "2026-06-29T12:10:00Z",
          },
        ];
        api.renderVersions();

        const list = document.getElementById("versionsList");
        assert.strictEqual(list.children.length, 2);
        assert.match(document.getElementById("summaryText").textContent, /2 versions, 1 active/);
        assert.strictEqual(list.children[0].dataset.versionId, "active-version");
        assert.match(list.children[0].children[0].src, /active-version\\/preview/);
        assert.match(list.children[0].children[1].href, /active-version\\/download/);
        assert.strictEqual(list.children[0].children[2].disabled, false);
        assert.match(list.children[1].className, /deleted/);
        assert.strictEqual(list.children[1].children[0].getAttribute("aria-disabled"), "true");
        assert.strictEqual(list.children[1].children[1].disabled, true);
        """,
    )


def test_public_admin_confirms_before_delete() -> None:
    script = public_admin_script()

    run_node_harness(
        script,
        dom_setup=PUBLIC_ADMIN_DOM_SETUP,
        body="""
        (async () => {
          const api = window.SecretPondPublicAdmin._test;
          let fetchCalls = [];
          let confirmCalls = 0;
          window.confirm = () => {
            confirmCalls += 1;
            return false;
          };
          globalThis.fetch = async (url, options = {}) => {
            fetchCalls.push({ url, method: options.method || "GET" });
            return { ok: true, json: async () => ({ versions: [] }) };
          };
          await api.deleteVersion("version-a");
          assert.strictEqual(confirmCalls, 1);
          assert.strictEqual(fetchCalls.length, 0);

          window.confirm = () => true;
          await api.deleteVersion("version-a");
          assert.deepStrictEqual(fetchCalls[0], {
            url: "/admin/versions/version-a",
            method: "DELETE",
          });
        })().catch((error) => {
          console.error(error);
          process.exitCode = 1;
        });
        """,
    )


PUBLIC_ADMIN_DOM_SETUP = """
const elements = {};
function makeElement(tagName = "div", id = "") {
  const element = {
    tagName,
    id,
    disabled: false,
    textContent: "",
    className: "",
    href: "",
    src: "",
    preload: "",
    controls: false,
    children: [],
    dataset: {},
    attributes: {},
    listeners: {},
    _innerHTML: "",
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    addEventListener(eventName, handler) {
      this.listeners[eventName] = handler;
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return this.attributes[name];
    },
    querySelector(selector) {
      if (selector === ".version-actions") {
        if (!this._actions) {
          this._actions = makeElement("div");
          this.children = this._actions.children;
        }
        return this._actions;
      }
      return null;
    },
    set innerHTML(value) {
      this._innerHTML = value;
    },
    get innerHTML() {
      return this._innerHTML;
    },
  };
  return element;
}
globalThis.document = {
  getElementById(id) {
    if (!elements[id]) elements[id] = makeElement("div", id);
    return elements[id];
  },
  createElement(tagName) {
    return makeElement(tagName);
  },
  addEventListener(eventName, handler) {
    if (eventName === "DOMContentLoaded") handler();
  },
};
globalThis.window = {
  confirm: () => true,
  addEventListener() {},
};
globalThis.fetch = async () => ({ ok: true, json: async () => ({ versions: [] }) });
"""
