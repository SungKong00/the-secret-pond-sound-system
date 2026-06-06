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
const selectorMatches = (element, selector) => {
  if (!element) return false;
  if (selector === "select,input,textarea,button") {
    return ["SELECT", "INPUT", "TEXTAREA", "BUTTON"].includes(element.tagName);
  }
  if (selector === "select,input,textarea,button,summary") {
    return ["SELECT", "INPUT", "TEXTAREA", "BUTTON", "SUMMARY"].includes(element.tagName);
  }
  const dataSelector = selector.match(/^\\[([^=\\]]+)(?:="([^"]+)")?\\]$/);
  if (dataSelector) {
    const attribute = dataSelector[1];
    const expected = dataSelector[2];
    const actual = element.getAttribute(attribute);
    return expected === undefined ? actual !== null : actual === expected;
  }
  return false;
};
const makeElement = (tagName = "div") => {
    const style = {
      setProperty(name, value) {
        this[name] = String(value);
      },
    };
    const element = {
    tagName: String(tagName).toUpperCase(),
    children: [],
    textContent: "",
    className: "",
    hidden: false,
    open: false,
    disabled: false,
    title: "",
    value: "",
    style,
    attributes: {},
    dataset: {},
    listeners: {},
    parentElement: null,
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
      const stringValue = String(value);
      this.attributes[name] = stringValue;
      if (name.startsWith("data-")) {
        const key = name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
        this.dataset[key] = stringValue;
      }
    },
    getAttribute(name) {
      return this.attributes[name] ?? null;
    },
    appendChild(child) {
      child.parentElement = this;
      this.children.push(child);
      return child;
    },
    append(...children) {
      children.forEach((child) => {
        child.parentElement = this;
        this.children.push(child);
      });
    },
    addEventListener(eventName, handler) {
      this.listeners[eventName] = handler;
    },
    dispatchEvent(event) {
      this.listeners[event.type]?.(event);
    },
    contains(target) {
      if (target === this) return true;
      return this.children.some((child) => child?.contains?.(target));
    },
    closest(selector) {
      let current = this;
      while (current) {
        if (selectorMatches(current, selector)) return current;
        current = current.parentElement;
      }
      return null;
    },
    querySelector() {
      return makeElement();
    },
    querySelectorAll() {
      return [];
    },
  };
  Object.defineProperty(element, "innerHTML", {
    get() {
      return this._innerHTML || "";
    },
    set(value) {
      this._innerHTML = String(value);
      this.children = [];
    },
  });
  return element;
};
const createElement = (tagName = "div") => makeElement(tagName);
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
  createElement(tagName) {
    return createElement(tagName);
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
