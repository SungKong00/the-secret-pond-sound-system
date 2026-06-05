from __future__ import annotations

import json
import shutil
import subprocess

import pytest

STATIC_APP_BOOTSTRAP = (
    "\nbindEvents();\nrenderWorkspaceTabs();\ndrawCanvas();\n"
    "connectStateSocket();\nrefreshAll();\n"
)

STATIC_APP_NULL_DOM_SETUP = """
globalThis.document = {
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return {}; },
  addEventListener() {},
};
globalThis.window = {
  addEventListener() {},
  location: { protocol: "http:", host: "127.0.0.1:8000", search: "" },
};
globalThis.requestAnimationFrame = () => {};
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
"""

STATIC_APP_RENDER_DOM_SETUP = """
const elements = {};
const makeElement = () => {
  const element = {
    children: [],
    innerHTML: "",
    textContent: "",
    className: "",
    hidden: false,
    disabled: false,
    title: "",
    value: "",
    attributes: {},
    _classes: new Set(),
    classList: {
      toggle(name, force) {
        if (force) element._classes.add(name);
        else element._classes.delete(name);
      },
      contains(name) {
        return element._classes.has(name);
      },
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    getAttribute(name) {
      return this.attributes[name] || null;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    append(...children) {
      this.children.push(...children);
    },
    addEventListener() {},
    querySelector() {
      return makeElement();
    },
    querySelectorAll() {
      return [];
    },
  };
  return element;
};
const createElement = () => makeElement();
const recordCore = createElement();
const recordOutcome = createElement();
recordOutcome.className = "record-outcome ready";
elements.recordOutcomeStatus = createElement();
elements.recordOutcomeStatus.parentElement = recordOutcome;
elements.recordOutcomeDetail = createElement();
elements.recordOutcomeDetail.parentElement = recordOutcome;
globalThis.document = {
  getElementById(id) {
    if (!elements[id]) elements[id] = createElement();
    return elements[id];
  },
  createElement() {
    return createElement();
  },
  querySelector(selector) {
    return selector === ".record-core" ? recordCore : createElement();
  },
  querySelectorAll() {
    return [];
  },
  addEventListener() {},
};
globalThis.window = {
  addEventListener() {},
  location: { protocol: "http:", host: "127.0.0.1:8000", search: "" },
};
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
globalThis.requestAnimationFrame = () => {};
"""


def run_node_harness(
    script: str,
    *,
    body: str,
    dom_setup: str = STATIC_APP_NULL_DOM_SETUP,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for static app behavior smoke test")

    body = body.replace("{{", "{").replace("}}", "}")
    harness = f"""
const assert = require("assert");
const vm = require("vm");
{dom_setup}
vm.runInThisContext({json.dumps(script)}, {{ filename: "app.js" }});

{body}
"""
    subprocess.run([node, "-e", harness], check=True, text=True)
