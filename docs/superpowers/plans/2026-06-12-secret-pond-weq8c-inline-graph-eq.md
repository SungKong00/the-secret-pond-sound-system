# Secret Pond WEQ8C Inline Graph EQ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate fourth Graph EQ workspace with a WEQ8C-based Graph EQ editor embedded inline inside each existing layer card.

**Architecture:** Keep Python audio/render behavior authoritative and treat WEQ8C as a browser-side EQ state editor. Move the Graph EQ interaction surface from a global workspace into per-layer card components, but continue writing changes through the existing `layers.<layer>.eq` draft state and `commitDraftChange` path so Live/Stable behavior remains unchanged. Preserve current card ownership: `mid` and `low` render under Loop Mixer, and `voice` renders under Voice Stack; all three layer cards get the same inline Graph EQ contract.

**Tech Stack:** Python/FastAPI static dashboard, vanilla JS/CSS, WEQ8C Web Component, esbuild, npm lockfile, pytest, Node static harness tests, Chrome Playwright/browser verification.

---

## Source Seed

- Seed: `docs/ouroboros/seed_secret_pond_graph_eq_weq8c_inline_20260612.yaml`
- Do not implement beyond this seed without a new user decision.
- Do not edit, format, stage, or commit `pyproject.toml` or `uv.lock`.
- Existing dirty files may already include Graph EQ work. Read diffs before editing and preserve unrelated user changes.

## File Map

**Create**
- `package.json`: npm scripts and frontend dependencies for WEQ8C/esbuild.
- `package-lock.json`: reproducible frontend dependency lockfile.
- `src/secret_pond/web/frontend/graph_eq_inline.js`: browser bundle entry that imports/registers WEQ8C and exposes the small adapter/controller API used by `app.js`.
- `src/secret_pond/web/static/graph_eq_inline.bundle.js`: committed esbuild output served by FastAPI.
- `tests/web/test_graph_eq_weq8c_adapter.py`: adapter/static-contract tests using the existing static app harness style.
- `tests/web/graph_eq_inline.spec.js`: Chrome Playwright checks for inline editor behavior where local Chrome is available.

**Modify**
- `src/secret_pond/web/static/index.html`: remove the fourth Graph EQ workspace tab/pane; include the committed WEQ8C bundle.
- `src/secret_pond/web/static/app.js`: replace global Graph EQ workspace state/rendering with layer-card inline state and WEQ8C adapter calls.
- `src/secret_pond/web/static/styles.css`: add inline layer-card Graph EQ layout, mini preview, expanded editor, and WEQ8C host-safe sizing.
- `tests/web/test_routes.py`: update static DOM/script assertions from global Graph EQ workspace to inline layer-card editor.
- `tests/web/test_static_app_dashboard_feedback.py`: assert inline Graph EQ edits use `commitDraftChange` and layer feedback surfaces.
- `tests/web/test_rendered_dashboard_live_ui.py`: update rendered dashboard expectations and Live/Stable status checks.

**Do Not Touch**
- `pyproject.toml`
- `uv.lock`

## Slice 0: Baseline Audit And Build Contract

**Purpose:** Freeze what exists before replacing it, and add failing tests for the new no-fourth-tab and inline-card expectations.

**Files**
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_rendered_dashboard_live_ui.py`
- Inspect only: `src/secret_pond/web/static/index.html`
- Inspect only: `src/secret_pond/web/static/app.js`
- Inspect only: `src/secret_pond/web/static/styles.css`

- [ ] **Step 0.1: Capture current git state**

Run:

```bash
git status --short --branch
git diff --name-only
```

Expected:
- Existing dirty files may appear.
- `pyproject.toml` and `uv.lock` may already be dirty; do not stage or edit them in this slice.

- [ ] **Step 0.2: Write failing route test for removing the fourth tab**

In `tests/web/test_routes.py`, update or replace the current `test_graph_eq_workspace_static_structure` with a new expectation:

```python
def test_graph_eq_is_inline_in_existing_layer_cards(tmp_path: Path) -> None:
    client = create_test_client(tmp_path)

    response = client.get("/")
    script = client.get("/static/app.js")
    styles = client.get("/static/styles.css")

    assert response.status_code == 200
    assert script.status_code == 200
    assert styles.status_code == 200

    assert 'data-workspace-tab="graph-eq"' not in response.text
    assert 'id="workspaceTabGraphEq"' not in response.text
    assert 'id="workspacePaneGraphEq"' not in response.text
    assert 'id="graphEqLayerTabs"' not in response.text

    assert "Graph EQ" in response.text
    assert "Loop Mixer" in response.text
    assert "Voice Treatment" in response.text
    assert "Voice Stack" in response.text

    assert "graph-eq-layer-card-section" in script.text
    assert "renderLayerGraphEqSection" in script.text
    assert "toggleExpandedGraphEqLayer" in script.text
    assert ".graph-eq-inline-editor" in styles.text
    assert ".graph-eq-mini-preview" in styles.text
```

- [ ] **Step 0.3: Write failing rendered UI expectation**

In `tests/web/test_rendered_dashboard_live_ui.py`, update the rendered Graph EQ check so it expects no global graph pane and expects inline layer-card sections:

```python
assert rendered["graphEqWorkspaceVisible"] is False
assert rendered["inlineGraphEqSections"] == 3
assert rendered["expandedGraphEqEditors"] in {0, 1}
```

Use the existing JavaScript evaluation style in that file. The evaluated DOM query should count:

```javascript
document.querySelectorAll(".graph-eq-layer-card-section").length
document.querySelectorAll(".graph-eq-inline-editor.expanded").length
Boolean(document.querySelector('[data-workspace-tab="graph-eq"]'))
```

- [ ] **Step 0.4: Run focused tests and confirm they fail**

Run:

```bash
uv run pytest tests/web/test_routes.py::test_graph_eq_is_inline_in_existing_layer_cards -q
uv run pytest tests/web/test_rendered_dashboard_live_ui.py -q
```

Expected:
- `test_graph_eq_is_inline_in_existing_layer_cards` fails because the fourth Graph EQ tab still exists.
- Rendered UI test fails because inline sections are not implemented yet.

- [ ] **Step 0.5: Commit only tests if the project convention for this run requires test-first commits**

If committing each slice:

```bash
git add tests/web/test_routes.py tests/web/test_rendered_dashboard_live_ui.py
git commit -m "test: 인라인 Graph EQ 기대 동작 추가"
```

Do not stage `pyproject.toml` or `uv.lock`.

## Slice 1: WEQ8C Bundle And Adapter

**Purpose:** Add a reproducible frontend bundle that registers WEQ8C and maps between WEQ8C filters and Secret Pond `EqPointSettings`.

**Files**
- Create: `package.json`
- Create: `package-lock.json`
- Create: `src/secret_pond/web/frontend/graph_eq_inline.js`
- Create: `src/secret_pond/web/static/graph_eq_inline.bundle.js`
- Create: `tests/web/test_graph_eq_weq8c_adapter.py`
- Modify: `src/secret_pond/web/static/index.html`
- Modify: `tests/web/test_routes.py`

- [ ] **Step 1.1: Write failing adapter export tests**

Create `tests/web/test_graph_eq_weq8c_adapter.py` with tests that assert the bundle source exposes the agreed adapter names before implementation:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ENTRY = ROOT / "src/secret_pond/web/frontend/graph_eq_inline.js"
STATIC_BUNDLE = ROOT / "src/secret_pond/web/static/graph_eq_inline.bundle.js"


def test_weq8c_frontend_entry_declares_adapter_contract() -> None:
    source = FRONTEND_ENTRY.read_text(encoding="utf-8")

    assert "weq8c" in source
    assert "secretPondGraphEq" in source
    assert "toSecretPondEqPoints" in source
    assert "fromSecretPondEqPoints" in source
    assert "MAX_SECRET_POND_EQ_POINTS" in source
    assert "SUPPORTED_SECRET_POND_TYPES" in source


def test_committed_weq8c_bundle_exists_for_fastapi_runtime() -> None:
    bundle = STATIC_BUNDLE.read_text(encoding="utf-8")

    assert "customElements" in bundle
    assert "secretPondGraphEq" in bundle
    assert "toSecretPondEqPoints" in bundle
    assert "fromSecretPondEqPoints" in bundle
```

- [ ] **Step 1.2: Run adapter tests and confirm they fail**

Run:

```bash
uv run pytest tests/web/test_graph_eq_weq8c_adapter.py -q
```

Expected:
- FAIL because frontend entry and bundle do not exist.

- [ ] **Step 1.3: Add npm build contract**

Create `package.json`:

```json
{
  "private": true,
  "scripts": {
    "build:graph-eq": "esbuild src/secret_pond/web/frontend/graph_eq_inline.js --bundle --format=iife --global-name=SecretPondGraphEqBundle --outfile=src/secret_pond/web/static/graph_eq_inline.bundle.js",
    "test:e2e": "playwright test tests/web/graph_eq_inline.spec.js --project=chromium"
  },
  "dependencies": {
    "weq8c": "0.3.5"
  },
  "devDependencies": {
    "@playwright/test": "^1.54.0",
    "esbuild": "^0.25.0"
  }
}
```

Then run:

```bash
npm install --package-lock-only
npm install
```

Expected:
- `package-lock.json` exists.
- `node_modules/` appears locally but must not be committed.

- [ ] **Step 1.4: Implement frontend adapter entry**

Create `src/secret_pond/web/frontend/graph_eq_inline.js` with these public contracts:

```javascript
import "weq8c";

const MAX_SECRET_POND_EQ_POINTS = 6;
const SUPPORTED_SECRET_POND_TYPES = Object.freeze({
  low_shelf: "lowshelf",
  bell: "peaking",
  high_shelf: "highshelf",
});
const WEQ8C_TO_SECRET_POND_TYPES = Object.freeze({
  lowshelf: "low_shelf",
  peaking: "bell",
  highshelf: "high_shelf",
});

const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value)));

const normalizeSecretPondPoint = (point, index = 0) => ({
  id: String(point?.id || `point-${index + 1}`),
  type: WEQ8C_TO_SECRET_POND_TYPES[point?.type] || point?.type || "bell",
  frequency_hz: Math.round(clamp(point?.frequency_hz ?? point?.frequency ?? 1000, 20, 20000)),
  gain_db: Number(clamp(point?.gain_db ?? point?.gain ?? 0, -18, 18).toFixed(1)),
  q: Number(clamp(point?.q ?? point?.Q ?? 1, 0.1, 18).toFixed(2)),
});

const toSecretPondEqPoints = (filters = []) => filters
  .map((filter, index) => normalizeSecretPondPoint(filter, index))
  .filter((point) => Object.hasOwn(SUPPORTED_SECRET_POND_TYPES, point.type))
  .slice(0, MAX_SECRET_POND_EQ_POINTS);

const fromSecretPondEqPoints = (points = []) => points
  .map((point, index) => normalizeSecretPondPoint(point, index))
  .filter((point) => Object.hasOwn(SUPPORTED_SECRET_POND_TYPES, point.type))
  .slice(0, MAX_SECRET_POND_EQ_POINTS)
  .map((point) => ({
    id: point.id,
    type: SUPPORTED_SECRET_POND_TYPES[point.type],
    frequency: point.frequency_hz,
    gain: point.gain_db,
    q: point.q,
  }));

window.secretPondGraphEq = Object.freeze({
  MAX_SECRET_POND_EQ_POINTS,
  SUPPORTED_SECRET_POND_TYPES,
  toSecretPondEqPoints,
  fromSecretPondEqPoints,
});
```

During implementation, verify exact WEQ8C property names against the installed package before relying on this mapping. Keep the public `window.secretPondGraphEq` names stable for `app.js` and tests.

- [ ] **Step 1.5: Build and include committed bundle**

Run:

```bash
npm run build:graph-eq
```

Modify `src/secret_pond/web/static/index.html` to include the bundle after the existing dashboard script dependencies and before `app.js` if `app.js` needs `window.secretPondGraphEq` during initialization:

```html
<script src="/static/graph_eq_inline.bundle.js"></script>
```

- [ ] **Step 1.6: Run focused bundle tests**

Run:

```bash
uv run pytest tests/web/test_graph_eq_weq8c_adapter.py tests/web/test_routes.py -q
```

Expected:
- PASS for adapter file/bundle existence.
- Route tests may still fail until Slice 2 removes the old global Graph EQ workspace.

- [ ] **Step 1.7: Commit Slice 1**

```bash
git add package.json package-lock.json \
  src/secret_pond/web/frontend/graph_eq_inline.js \
  src/secret_pond/web/static/graph_eq_inline.bundle.js \
  src/secret_pond/web/static/index.html \
  tests/web/test_graph_eq_weq8c_adapter.py tests/web/test_routes.py
git diff --cached --name-only
git commit -m "feat: WEQ8C 그래프 EQ 번들 추가"
```

Confirm `pyproject.toml` and `uv.lock` are not staged.

## Slice 2: Inline Layer Card Graph EQ UI

**Purpose:** Remove the separate Graph EQ workspace UI and render collapsed/expanded Graph EQ sections inside layer cards.

**Files**
- Modify: `src/secret_pond/web/static/index.html`
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `src/secret_pond/web/static/styles.css`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_rendered_dashboard_live_ui.py`

- [ ] **Step 2.1: Write failing static harness test for one expanded editor**

Add a test in `tests/web/test_routes.py` using the existing static harness exports:

```python
def test_static_inline_graph_eq_tracks_one_expanded_layer(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ toggleExpandedGraphEqLayer, expandedGraphEqLayerId }",
        body="""
const helpers = globalThis.__secretPondTest;
assert.strictEqual(helpers.expandedGraphEqLayerId(), null);
helpers.toggleExpandedGraphEqLayer("low");
assert.strictEqual(helpers.expandedGraphEqLayerId(), "low");
helpers.toggleExpandedGraphEqLayer("mid");
assert.strictEqual(helpers.expandedGraphEqLayerId(), "mid");
helpers.toggleExpandedGraphEqLayer("mid");
assert.strictEqual(helpers.expandedGraphEqLayerId(), null);
""",
    )
```

- [ ] **Step 2.2: Run the new static harness test and confirm it fails**

Run:

```bash
uv run pytest tests/web/test_routes.py::test_static_inline_graph_eq_tracks_one_expanded_layer -q
```

Expected:
- FAIL because `toggleExpandedGraphEqLayer` and `expandedGraphEqLayerId` do not exist.

- [ ] **Step 2.3: Remove global workspace markup**

In `src/secret_pond/web/static/index.html`:
- Remove the `workspaceTabGraphEq` button.
- Remove `workspacePaneGraphEq`.
- Keep `Graph EQ`, `Bell / Peak`, `Low Shelf`, `High Shelf`, `Freq`, `Gain`, `Q` labels available through JS-rendered inline controls, not a global pane.

In `src/secret_pond/web/static/app.js`, change:

```javascript
const workspaceTabNames = ["treatment", "stack", "mixer", "graph-eq"];
```

to:

```javascript
const workspaceTabNames = ["treatment", "stack", "mixer"];
```

- [ ] **Step 2.4: Add inline expansion state**

In the `state` object in `app.js`, replace the global layer selector:

```javascript
graphEqLayer: "low",
```

with:

```javascript
expandedGraphEqLayer: null,
```

Add helpers near the Graph EQ helper section:

```javascript
const expandedGraphEqLayerId = () => (
  layerIds.includes(state.expandedGraphEqLayer) ? state.expandedGraphEqLayer : null
);

const toggleExpandedGraphEqLayer = (layerId) => {
  if (!layerIds.includes(layerId)) return;
  state.expandedGraphEqLayer = expandedGraphEqLayerId() === layerId ? null : layerId;
  renderLayerControls();
};
```

Keep the existing ownership boundary: `renderLayerControls()` continues to render `mid` and `low` into `#layerControls`, and the existing voice rendering path continues to render `voice` into `#voiceLayerControls`. The inline Graph EQ section is added by `renderLayerCard(layerId)`, so all three layer cards receive it without moving `voice` into the Loop Mixer panel.

- [ ] **Step 2.5: Render collapsed and expanded sections from each layer card**

Add:

```javascript
const renderGraphEqMiniPreviewSvg = (eq) => {
  const path = graphEqPathD(graphEqVisualResponsePoints(eq, 32));
  return `
    <svg class="graph-eq-mini-preview" viewBox="0 0 1000 360" aria-hidden="true" preserveAspectRatio="none">
      <path class="graph-eq-mini-curve" d="${path}"></path>
    </svg>
  `;
};

const renderLayerGraphEqSection = (layerId) => {
  const eq = graphEqForLayer(state.draft, layerId);
  const expanded = expandedGraphEqLayerId() === layerId;
  return `
    <section class="graph-eq-layer-card-section ${expanded ? "expanded" : "collapsed"}" data-graph-eq-layer-card="${layerId}">
      <div class="graph-eq-layer-card-head">
        <div>
          <h4>Graph EQ <small lang="ko">곡선 EQ</small></h4>
          <p class="graph-eq-layer-card-status">${expanded ? "편집 중" : "현재 곡선"}</p>
        </div>
        <button class="button graph-eq-edit-button" type="button" data-graph-eq-toggle="${layerId}">
          ${expanded ? "Close" : "Edit"}
        </button>
      </div>
      ${expanded ? renderExpandedGraphEqEditorShell(layerId, eq) : renderGraphEqMiniPreviewSvg(eq)}
    </section>
  `;
};
```

Then call it inside `renderLayerCard` after Level and before Filter Range. Do not leave Filter Range in a separate global Graph EQ panel.

- [ ] **Step 2.6: Split Filter Range rendering back into layer card flow**

Currently `renderLayerCard` filters out `group.action === "reset-filter"`. Change that flow so:
- Level group renders first.
- `renderLayerGraphEqSection(layerId)` renders next.
- Filter Range group renders after Graph EQ.

Use the existing `graphEqFilterGroup` and `resetLayerFilter(layerId)` behavior. Do not duplicate Filter Range state.

- [ ] **Step 2.7: Add CSS for inline layout**

In `styles.css`, add styles with stable desktop dimensions:

```css
.graph-eq-layer-card-section {
  border: 1px solid rgba(223, 213, 191, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  padding: 10px;
  min-width: 0;
}

.graph-eq-layer-card-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.graph-eq-mini-preview {
  display: block;
  width: 100%;
  height: 72px;
  margin-top: 8px;
}

.graph-eq-inline-editor {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(190px, 240px);
  gap: 12px;
  min-height: 360px;
}

.graph-eq-inline-editor weq8-ui {
  width: 100%;
  min-height: 340px;
}
```

Do not add `weq8-ui { display: block; }`.

- [ ] **Step 2.8: Bind toggle buttons after render**

In `renderLayerCard`, after setting `innerHTML`, add:

```javascript
card.querySelector("[data-graph-eq-toggle]")?.addEventListener("click", (event) => {
  toggleExpandedGraphEqLayer(event.currentTarget.dataset.graphEqToggle);
});
```

- [ ] **Step 2.9: Run focused UI structure tests**

Run:

```bash
uv run pytest tests/web/test_routes.py::test_graph_eq_is_inline_in_existing_layer_cards \
  tests/web/test_routes.py::test_static_inline_graph_eq_tracks_one_expanded_layer \
  tests/web/test_rendered_dashboard_live_ui.py -q
```

Expected:
- PASS for no fourth tab and one-expanded-state checks.
- Rendered UI may still fail on WEQ8C internals until Slice 3 initializes the component.

- [ ] **Step 2.10: Commit Slice 2**

```bash
git add src/secret_pond/web/static/index.html \
  src/secret_pond/web/static/app.js \
  src/secret_pond/web/static/styles.css \
  tests/web/test_routes.py tests/web/test_rendered_dashboard_live_ui.py
git diff --cached --name-only
git commit -m "feat: Graph EQ를 레이어 카드에 통합"
```

Do not stage `pyproject.toml` or `uv.lock`.

## Slice 3: State And Apply Integration

**Purpose:** Connect WEQ8C graph edits and selected point controls to existing `layers.<layer>.eq` draft state, preserving Live/Stable behavior.

**Files**
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `src/secret_pond/web/static/styles.css`
- Modify: `tests/web/test_static_app_dashboard_feedback.py`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_rendered_dashboard_live_ui.py`

- [ ] **Step 3.1: Write failing commitDraftChange integration test**

In `tests/web/test_static_app_dashboard_feedback.py`, add a test that uses existing harness patterns:

```python
def test_inline_graph_eq_edit_marks_layer_feedback_surface(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ commitInlineGraphEqPoints, normalizeGraphEqSettings, state }",
        body="""
const helpers = globalThis.__secretPondTest;
helpers.state.draft = structuredClone(activeSettings);
helpers.state.snapshot = {
  settings: {
    active: structuredClone(activeSettings),
    draft: structuredClone(activeSettings),
  },
  playback: { apply_mode: "live", live_graph_eq: { status: "idle" } },
};

const baseEq = helpers.normalizeGraphEqSettings({});
const before = baseEq.points[1].gain_db;
helpers.commitInlineGraphEqPoints("mid", [
  { ...baseEq.points[1], gain_db: before + 3 },
]);

assert.strictEqual(helpers.state.draft.layers.mid.eq.points[0].gain_db, before + 3);
assert.strictEqual(helpers.state.pendingCoveredFeedbackSurfaceId, "layer:mid");
assert(helpers.state.pendingCoveredFeedbackControlIds.includes("layers.mid.eq.points"));
""",
    )
```

- [ ] **Step 3.2: Run the integration test and confirm it fails**

Run:

```bash
uv run pytest tests/web/test_static_app_dashboard_feedback.py::test_inline_graph_eq_edit_marks_layer_feedback_surface -q
```

Expected:
- FAIL because `commitInlineGraphEqPoints` does not exist.

- [ ] **Step 3.3: Add draft commit helper**

In `app.js`, add:

```javascript
const commitInlineGraphEqPoints = (layerId, points, selectedPointId = null) => {
  if (!layerIds.includes(layerId)) return false;
  const eq = graphEqForLayer(state.draft, layerId);
  const normalized = normalizeGraphEqSettings({ ...eq, points });
  const committed = commitDraftChange(
    () => {
      updateDraftGraphEq(layerId, normalized);
      if (selectedPointId !== undefined) {
        state.graphEqSelectedPointIds[layerId] = selectedPointId;
      }
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: graphEqControlIds(layerId, selectedPointId),
      afterSync: renderLayerControls,
    },
  );
  return committed;
};
```

This must be the only path WEQ8C uses to update the app state. It keeps Live/Stable behavior attached to `commitDraftChange`.

- [ ] **Step 3.4: Initialize expanded WEQ8C editor after render**

Add an initializer called after `renderLayerCard` returns or after `renderLayerControls` finishes:

```javascript
const initializeInlineGraphEqEditors = () => {
  document.querySelectorAll("[data-graph-eq-inline-editor]").forEach((container) => {
    const layerId = container.dataset.graphEqInlineEditor;
    const weq = container.querySelector("weq8-ui");
    if (!layerIds.includes(layerId) || !weq || weq.dataset.secretPondBound === "true") return;
    weq.dataset.secretPondBound = "true";
    const eq = graphEqForLayer(state.draft, layerId);
    const filters = window.secretPondGraphEq?.fromSecretPondEqPoints?.(eq.points) || [];
    if ("filters" in weq) weq.filters = filters;
    weq.addEventListener("change", () => {
      const nextFilters = weq.filters || [];
      const nextPoints = window.secretPondGraphEq.toSecretPondEqPoints(nextFilters);
      commitInlineGraphEqPoints(layerId, nextPoints, nextPoints[0]?.id || null);
    });
  });
};
```

Verify actual WEQ8C event/property names against the installed package before finalizing. If WEQ8C uses a different event than `change`, bind the documented event and update tests accordingly.

- [ ] **Step 3.5: Render selected point controls inside expanded editor**

Reuse existing control labels:
- `Type`
- `Freq`
- `Gain`
- `Q`

Keep technical terms English and state/action text Korean. The selected controls must call `commitGraphEqPointEdit(layerId, pointId, updates)` or the new `commitInlineGraphEqPoints` helper, not a local-only state object.

Use stable selectors for browser tests:

```html
<select data-graph-eq-point-type data-graph-eq-point-control="type"></select>
<input data-graph-eq-point-control="freq" type="number">
<input data-graph-eq-point-control="gain" type="number">
<input data-graph-eq-point-control="q" type="number">
<button data-graph-eq-action="add-point" type="button">+ Point</button>
<button data-graph-eq-action="delete-point" type="button">Delete</button>
```

- [ ] **Step 3.6: Remove old global Graph EQ binding path**

Remove or retire:
- `setGraphEqLayer`
- `renderGraphEqLayerTabs`
- `renderGraphEqWorkspace`
- `bindGraphEqControls` if it only targets global IDs
- DOM dependencies on `graphEqCanvas`, `graphEqSvg`, `graphEqPointOverlay`, `graphEqFilterControls` as global singleton IDs

Replace singleton IDs with per-layer `data-*` selectors. Avoid duplicate IDs inside multiple layer cards.

- [ ] **Step 3.7: Preserve Live/Stable behavior**

Add or update tests:

```python
def test_inline_graph_eq_live_edit_uses_existing_pending_feedback(tmp_path: Path) -> None:
    # edit via commitInlineGraphEqPoints in live mode
    # assert pending live feedback surface is layer:<id>
    # assert no browser-side render authority is created
```

```python
def test_inline_graph_eq_stable_edit_remains_staged_until_apply_restart(tmp_path: Path) -> None:
    # edit via commitInlineGraphEqPoints in stable mode
    # assert draft changes while active remains unchanged
    # assert Apply and Restart remains the apply path
```

Use existing fixtures in `tests/web/test_static_app_dashboard_feedback.py` and API mode tests in `tests/web/test_routes.py` instead of inventing a second runtime harness.

- [ ] **Step 3.8: Run focused state tests**

Run:

```bash
uv run pytest tests/web/test_static_app_dashboard_feedback.py \
  tests/web/test_routes.py::test_static_graph_eq_helpers_map_points_and_reset_actions \
  tests/web/test_routes.py::test_static_graph_eq_effective_points_reflect_legacy_gains \
  tests/web/test_routes.py::test_static_graph_eq_live_status_copy_describes_slow_and_failed_states -q
```

Expected:
- PASS.

- [ ] **Step 3.9: Commit Slice 3**

```bash
git add src/secret_pond/web/static/app.js src/secret_pond/web/static/styles.css \
  tests/web/test_static_app_dashboard_feedback.py tests/web/test_routes.py \
  tests/web/test_rendered_dashboard_live_ui.py
git diff --cached --name-only
git commit -m "feat: WEQ8C 변경을 레이어 draft에 연결"
```

Do not stage `pyproject.toml` or `uv.lock`.

## Slice 4: Browser And Persistence Verification

**Purpose:** Prove the implementation actually renders in the browser, supports WEQ8C editing, and survives reload.

**Files**
- Create: `tests/web/graph_eq_inline.spec.js`
- Modify: `package.json`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_rendered_dashboard_live_ui.py`

- [ ] **Step 4.1: Add Playwright spec for inline editor**

Create `tests/web/graph_eq_inline.spec.js`:

```javascript
const { test, expect } = require("@playwright/test");

test("Graph EQ is inline inside layer cards and no fourth tab exists", async ({ page }) => {
  await page.goto(process.env.SECRET_POND_E2E_URL || "http://127.0.0.1:8000/");

  await expect(page.locator('[data-workspace-tab="graph-eq"]')).toHaveCount(0);
  await expect(page.locator(".graph-eq-layer-card-section")).toHaveCount(3);

  const firstEdit = page.locator("[data-graph-eq-toggle]").first();
  await firstEdit.click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);

  const weqCanvas = page.locator(".graph-eq-inline-editor.expanded canvas").first();
  await expect(weqCanvas).toBeVisible();
  const box = await weqCanvas.boundingBox();
  expect(box.width).toBeGreaterThan(200);
  expect(box.height).toBeGreaterThan(160);
});
```

If WEQ8C does not render a raw `canvas` selector directly, update the selector to the verified internal element from the installed package.

- [ ] **Step 4.2: Add E2E for one-expanded-only**

Extend the spec:

```javascript
test("opening another layer collapses the previous Graph EQ editor", async ({ page }) => {
  await page.goto(process.env.SECRET_POND_E2E_URL || "http://127.0.0.1:8000/");

  const toggles = page.locator("[data-graph-eq-toggle]");
  await toggles.nth(0).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);

  await toggles.nth(1).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(page.locator('[data-graph-eq-layer-card].expanded')).toHaveCount(1);
});
```

- [ ] **Step 4.3: Add E2E for immediate draft update and reload persistence**

Use the existing dashboard API/state if available. The test should:
- Open Loop Mixer.
- Expand one layer Graph EQ.
- Drag or change a selected point.
- Read `/api/state` or dashboard state exposed in tests.
- Reload page.
- Assert the same layer EQ value remains.

Skeleton:

```javascript
test("WEQ8C edit updates layer EQ draft and persists after reload", async ({ page }) => {
  await page.goto(process.env.SECRET_POND_E2E_URL || "http://127.0.0.1:8000/");
  await page.locator("[data-graph-eq-toggle]").first().click();

  const gainInput = page.locator('[data-graph-eq-point-control="gain"]').first();
  await gainInput.fill("6");
  await gainInput.blur();

  const stateAfterEdit = await page.request.get("/api/state").then((res) => res.json());
  expect(JSON.stringify(stateAfterEdit.settings.draft.layers)).toContain("6");

  await page.reload();
  await page.locator("[data-graph-eq-toggle]").first().click();
  await expect(page.locator('[data-graph-eq-point-control="gain"]').first()).toHaveValue(/6(\\.0)?/);
});
```

The `/api/state` response used by existing tests exposes draft layer settings under `settings.draft.layers`; if the response shape changes before implementation, update this assertion and the API contract tests in the same slice.

- [ ] **Step 4.4: Add E2E for add/delete/type/max 6**

Add tests that use visible controls or WEQ8C native UI:

```javascript
test("Graph EQ add delete type and max six constraints are enforced", async ({ page }) => {
  await page.goto(process.env.SECRET_POND_E2E_URL || "http://127.0.0.1:8000/");
  await page.locator("[data-graph-eq-toggle]").first().click();

  for (let i = 0; i < 10; i += 1) {
    const add = page.locator('[data-graph-eq-action="add-point"]').first();
    if (await add.isDisabled()) break;
    await add.click();
  }

  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(6);

  await page.locator('[data-graph-eq-point-type]').first().selectOption("high_shelf");
  await expect(page.locator('[data-graph-eq-point-type]').first()).toHaveValue("high_shelf");

  await page.locator('[data-graph-eq-action="delete-point"]').first().click();
  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(5);
});
```

- [ ] **Step 4.5: Start local app and run browser tests**

Use the project startup method or test server. If using FastAPI directly:

```bash
uv run python -m secret_pond.app
```

In another shell:

```bash
SECRET_POND_E2E_URL=http://127.0.0.1:8000 npm run test:e2e
```

Expected:
- Browser opens served static assets.
- WEQ8C canvas is visible and nonblank.
- No fourth Graph EQ tab appears.
- Inline editor tests pass.

- [ ] **Step 4.6: Verify CSS host contract in browser**

Use Playwright or browser devtools to check:

```javascript
const dimensions = await page.locator(".graph-eq-inline-editor.expanded canvas").first()
  .evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  });
expect(dimensions.width).toBeGreaterThan(200);
expect(dimensions.height).toBeGreaterThan(160);
```

If the canvas height is 0 or near 0, inspect CSS for an accidental `weq8-ui { display: block; }` override.

- [ ] **Step 4.7: Run full project verification**

Run:

```bash
uv run pytest
uv run ruff check .
npm run build:graph-eq
npm run test:e2e
git status --short
```

Expected:
- Python tests pass.
- Ruff passes.
- Bundle rebuild is deterministic or produces only expected static bundle changes.
- E2E passes.
- `pyproject.toml` and `uv.lock` are not changed by this slice.

- [ ] **Step 4.8: Commit Slice 4**

```bash
git add package.json package-lock.json tests/web/graph_eq_inline.spec.js \
  src/secret_pond/web/static/graph_eq_inline.bundle.js \
  tests/web/test_routes.py tests/web/test_rendered_dashboard_live_ui.py
git diff --cached --name-only
git commit -m "test: 인라인 Graph EQ 브라우저 검증 추가"
```

Do not stage `pyproject.toml` or `uv.lock`.

## Live/Stable Risk Controls

- Live edits must call the same draft path as existing layer controls: `commitDraftChange`.
- Do not add browser-owned render authority. Browser edits only change draft state and let existing Live services handle debounce/render.
- Stable edits must remain staged until `Apply and Restart`; do not call Live Graph EQ tick/executor in Stable mode.
- If existing Live Graph EQ executor/source fallback bugs surface while testing this UI slice, do not silently expand scope. Either prove the UI slice requires the fix or split it into the existing completion seed/plan.
- Keep `feedbackSurfaceId` set to `layer:<layerId>` and `feedbackControlIds` under `layers.<layerId>.eq.*` so current pending/live/stable feedback visuals remain mode-aware.

## Browser/UI Verification Checklist

- No `Graph EQ` fourth workspace tab in the top tab row.
- `Loop Mixer` shows each layer with `Level`, `Graph EQ`, `Filter Range` in order.
- Collapsed `Graph EQ` section has mini curve preview and `Edit`.
- Opening `Edit` expands WEQ8C inside the same layer card.
- Opening another layer collapses the previous one.
- WEQ8C graph/canvas is visible, nonblank, and not collapsed.
- Selected point controls use English technical labels: `Type`, `Freq`, `Gain`, `Q`.
- State/action text remains Korean where it describes behavior or status.
- Text does not overlap at desktop operator viewport.
- No mobile-specific work is required.

## Self-Review

- Spec coverage: all Seed acceptance criteria map to Slice 0-4 tasks.
- Placeholder scan: no implementation step says "TBD" or "write tests" without a concrete target.
- Type consistency: plan consistently uses `expandedGraphEqLayer`, `expandedGraphEqLayerId`, `toggleExpandedGraphEqLayer`, `commitInlineGraphEqPoints`, and `window.secretPondGraphEq`.
- Scope guard: implementation avoids Live/Stable refactor, backend audio rewrite, preset libraries, mobile redesign, `pyproject.toml`, and `uv.lock`.

## Next Prompt

```text
방금 작성한 implementation plan을 기준으로 구현을 시작해줘.

조건:
- Plan 파일은 docs/superpowers/plans/2026-06-12-secret-pond-weq8c-inline-graph-eq.md 를 기준으로 해줘.
- 먼저 Slice 0~1까지만 진행해줘: baseline audit/build contract, WEQ8C bundle and adapter.
- 구현 전 각 slice는 테스트 먼저 작성하고 실패 확인 후 구현해줘.
- package.json, package-lock.json, built static bundle은 Slice 1에서 포함해도 되지만 pyproject.toml, uv.lock은 건드리지 마.
- 아직 inline layer card UI 전체 전환은 Slice 2부터 시작하므로, Slice 1 완료 후 내 확인을 받아줘.
- 작업 단위를 작게 나누고, 하나 끝나면 "feat: 내용" 또는 "test: 내용" 형식으로 커밋해줘.
```
