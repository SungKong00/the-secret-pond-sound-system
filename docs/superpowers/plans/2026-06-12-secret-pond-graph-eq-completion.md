# Secret Pond Graph EQ Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the unfinished Graph EQ follow-up by making the graph directly draggable, fixing the verified Live Graph EQ voice-source failure, wiring the 1 second Live debounce executor, and preserving Stable as the safe Apply and Restart fallback.

**Architecture:** Keep the existing Graph EQ model/render core and finish the missing contracts around it. Backend/runtime remains the authority for Live render/swap; the browser can request or poll a server-owned executor but cannot apply audio buffers itself. UI changes stay inside the existing Secret Pond static dashboard, with technical EQ terms in English and operator state/action text in Korean.

**Tech Stack:** Python 3, FastAPI routes, Pydantic settings, NumPy/pedalboard render path, static HTML/CSS/vanilla JS dashboard, pytest, ruff, rendered desktop dashboard verification.

---

## Source Seed

Use this Seed as the scope authority:

- `docs/ouroboros/seed_secret_pond_graph_eq_completion_20260612.yaml`

This is a completion plan on top of the already-merged Graph EQ implementation. Do not restart the original Graph EQ v1 build from scratch.

## Hard Constraints

- Do not edit, format, stage, or commit `pyproject.toml` or `uv.lock`.
- Do not introduce React, Vite, or another frontend framework.
- Keep Stable mode as staged draft plus `Apply and Restart`.
- Keep Live mode as 1 second debounce plus fast buffer replacement.
- Keep render/swap work outside the audio callback.
- Never use `low_playback.wav`, `mid_playback.wav`, `voice_playback.wav`, or another playback cache as a Live Graph EQ source.
- In `live_ephemeral` voice mode, `data/voice/voice_stack_raw.wav` is a valid EQ-free source when selected `voice_stack_path` is stale or missing.
- Keep Filter Range as Low Cut / High Cut slider controls, not draggable graph points.
- Desktop/operator UI is the verification target. Mobile optimization is out of scope.

## Current Findings To Preserve

- `src/secret_pond/audio/graph_eq.py` and `src/secret_pond/audio/renderer.py` already provide Graph EQ render core.
- `src/secret_pond/services/live_graph_eq.py` already has request id, debounce constants, latest-wins checks, slow caution state, failure rollback, and `run_due_live_graph_eq_update(...)`.
- The verified Live warning is intentional rollback behavior, but the cause is a real source-contract bug: selected `voice_stack_path` points to a missing timestamped stack file while `data/voice/voice_stack_raw.wav` exists in `live_ephemeral` mode.
- No route, websocket loop, or frontend timer currently calls `run_due_live_graph_eq_update(...)` after the debounce.
- Graph EQ dragging starts only from SVG point circles. Curve/background pointerdown does not select and move the nearest editable point.
- Legacy fields `low_gain_db`, `mid_gain_db`, `high_gain_db` can still color backend audio while the UI may display default flat points.

## File Map

Backend:

- Modify `src/secret_pond/audio/renderer.py`: Live EQ source fallback and detailed `LiveEqSourceError`.
- Modify `src/secret_pond/audio/source_library.py`: add a narrow helper only if renderer source resolution should not duplicate category/path logic.
- Modify `src/secret_pond/audio/graph_eq.py`: expose effective Graph EQ points for legacy-field alignment.
- Modify `src/secret_pond/config.py`: only for legacy normalization helpers or validation tests if needed; do not redesign the model.
- Modify `src/secret_pond/services/live_graph_eq.py`: executor result payload helpers, source-specific warning details, slow status, and route-safe state serialization if needed.
- Modify `src/secret_pond/services/playback_apply_mode.py`: Stable-to-Live source fallback regression and rollback details.
- Modify `src/secret_pond/web/routes.py`: add a thin server-owned Live Graph EQ executor endpoint.
- Modify `src/secret_pond/web/state.py`: expose pending/applied/slow/failed Live Graph EQ state to `/api/state`.

Frontend:

- Modify `src/secret_pond/web/static/app.js`: graph surface dragging, nearest-point helper, Live executor polling/tick hook, confirmed EQ rollback display, legacy EQ visual alignment.
- Modify `src/secret_pond/web/static/styles.css`: graph hit surface, grab/grabbing affordance, hover/selected/drag-active states, desktop layout guard.
- Modify `src/secret_pond/web/static/index.html`: only if the graph needs an explicit status/hit target or warning slot not expressible from SVG render output.

Tests:

- Modify `tests/audio/test_renderer.py`
- Modify `tests/audio/test_graph_eq.py`
- Modify `tests/services/test_live_graph_eq.py`
- Modify `tests/services/test_playback_apply_mode.py`
- Modify `tests/services/test_settings_draft.py`
- Modify `tests/web/test_routes.py`
- Modify `tests/web/test_rendered_dashboard_live_ui.py` only for browser-rendered desktop verification coverage.
- Modify `tests/test_docs.py` only if docs assertions need to include the new operator guidance.

Docs:

- Modify `docs/operator-guide.md`
- Modify `docs/audio-setup-checklist.md`

## Slice Order

### slice_0: Reproduce And Lock Current Failures

**Purpose:** Add failing tests for the exact gaps before implementation: stale voice source fallback, missing executor route, graph surface drag, and legacy UI/audio mismatch.

**Files:**

- Inspect: `data/logs/events.jsonl`
- Inspect: `data/config/settings.json`
- Inspect: `data/voice/voice_stack_raw.wav`
- Modify: `tests/audio/test_renderer.py`
- Modify: `tests/services/test_playback_apply_mode.py`
- Modify: `tests/services/test_live_graph_eq.py`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/audio/test_graph_eq.py`

- [ ] **Step 1: Re-check worktree and protect unrelated dirty files**

Run:

```bash
git status --short --branch
```

Expected:

- `pyproject.toml` and `uv.lock` may appear as modified.
- Do not stage or edit those files in any slice.

- [ ] **Step 2: Add stale voice source fallback regression**

In `tests/audio/test_renderer.py`, add:

```python
def test_live_eq_render_uses_voice_stack_raw_when_selected_live_ephemeral_stack_is_stale(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    raw_frequency = 500.0
    stale_selected = paths.voice_stack_sources_dir / "VS0608_072702.wav"
    write_wav_atomic(
        paths.voice_stack_raw,
        AudioBuffer(samples=sine_wave(raw_frequency) * 0.25, sample_rate=8_000),
    )
    write_wav_atomic(
        paths.voice_playback,
        AudioBuffer(samples=sine_wave(2_500.0) * 0.25, sample_rate=8_000),
    )
    settings.sources = SourceSelectionSettings(
        voice_stack_path=stale_selected.relative_to(paths.root).as_posix(),
    )

    rendered = LayerRenderer(paths).render_live_eq_layer_buffer("voice", settings)

    assert tone_magnitude(rendered.samples, 8_000, raw_frequency) > (
        tone_magnitude(rendered.samples, 8_000, 2_500.0) * 4.0
    )
```

Expected before slice_1: FAIL with `Live Graph EQ source for voice is unavailable`.

- [ ] **Step 3: Add Stable-to-Live regression for the same source bug**

In `tests/services/test_playback_apply_mode.py`, add a test that:

- creates `AppSettings(playback.apply_mode="stable", voice_stack.mode="live_ephemeral")`;
- sets `sources.voice_stack_path` to `data/sources/voice/stack/VS0608_072702.wav`;
- writes `paths.voice_stack_raw`;
- stages a Voice Graph EQ change;
- switches to Live with `staged_graph_eq="apply"`;
- runs the pending Live request due time;
- asserts no `settings.live_graph_eq_failed` event and Voice buffer update happened.

Use the existing `schedule_live_graph_eq_update(...)` and `_run_due_live_eq(...)` test helpers where available instead of adding a second harness.

Expected before slice_1: FAIL because the pending Live render still tries the stale selected stack path.

- [ ] **Step 4: Add executor-route regression**

In `tests/web/test_routes.py`, add:

```python
def test_api_live_graph_eq_tick_runs_due_request_under_runtime_lock(tmp_path: Path) -> None:
    client = create_test_client(tmp_path, with_sources=True)
    runtime = client.app.state.runtime
    active = runtime.settings_store.load().active.model_copy(
        update={"playback": PlaybackSettings(apply_mode="live")},
        deep=True,
    )
    draft_points = [point.model_dump() for point in active.layers["mid"].eq.points]
    draft_points[1]["gain_db"] = 6.0
    draft = active.model_copy(
        update={
            "layers": {
                **active.layers,
                "mid": active.layers["mid"].model_copy(
                    update={"eq": EqSettings(points=draft_points)},
                ),
            },
        },
        deep=True,
    )
    runtime.settings_store.save(SettingsState(active=active, draft=active))

    draft_response = client.put("/api/settings/draft", json=draft.model_dump(mode="json"))
    tick_response = client.post("/api/playback/live-graph-eq/tick")

    assert draft_response.status_code == 200
    assert tick_response.status_code == 200
    assert tick_response.json()["state"]["playback"]["live_graph_eq"]["status"] in {
        "pending",
        "applied",
    }
```

During final implementation, this test should simulate time by either injecting `now_ms` through the route body in tests or using a helper that advances to `pending_request.due_at_ms`. Do not make production behavior depend on a test-only clock.

Expected before slice_2: FAIL with 404 because `/api/playback/live-graph-eq/tick` does not exist.

- [ ] **Step 5: Add graph surface direct-manipulation static tests**

In `tests/web/test_routes.py`, extend the existing static JS helper export around Graph EQ helpers to include:

```javascript
{
  defaultGraphEqPoints,
  normalizeGraphEqSettings,
  graphEqNearestPointId,
  graphEqPointFromPointerRatio,
  graphEqControlIds
}
```

Add assertions:

```javascript
const eq = {
  points: [
    { id: "low", type: "low_shelf", frequency_hz: 120, gain_db: -3, q: 0.7 },
    { id: "mid", type: "bell", frequency_hz: 1000, gain_db: 8, q: 1 },
    { id: "high", type: "high_shelf", frequency_hz: 8000, gain_db: 2, q: 0.7 },
  ],
  highpass_hz: 20,
  lowpass_hz: 20000,
};
assert.strictEqual(helpers.graphEqNearestPointId(eq, { x: 0.56, y: 0.28 }), "mid");
assert.strictEqual(helpers.graphEqNearestPointId(eq, { x: 0.90, y: 0.44 }), "high");
```

Also add static markup/CSS assertions:

- `data-graph-eq-hit-surface` exists in rendered SVG output.
- `data-graph-eq-curve` exists on the curve path.
- `.graph-eq-svg.drag-active`, `.graph-eq-hit-surface`, `.graph-eq-curve:hover`, and `cursor: grabbing` exist in CSS.

Expected before slice_3: FAIL because nearest-point helper and hit surface do not exist.

- [ ] **Step 6: Add legacy EQ mismatch regression**

In `tests/audio/test_graph_eq.py`, add:

```python
def test_effective_graph_eq_points_reflect_legacy_gains_when_points_are_default() -> None:
    eq = EqSettings(low_gain_db=3.0, mid_gain_db=-2.0, high_gain_db=1.0)

    points = effective_graph_eq_points(eq)

    assert [(point.id, point.frequency_hz, point.gain_db) for point in points] == [
        ("legacy-low", 250.0, 3.0),
        ("legacy-mid", 1000.0, -2.0),
        ("legacy-high", 2000.0, 1.0),
    ]
```

In `tests/web/test_routes.py`, add a matching static JS test for `graphEqEffectivePoints(...)` so the browser-drawn curve cannot remain flat when backend audio uses legacy gains.

Expected before slice_4: FAIL because the effective helper is private in Python and absent in JS.

- [ ] **Step 7: Run only the new focused failures**

Run:

```bash
uv run pytest tests/audio/test_renderer.py::test_live_eq_render_uses_voice_stack_raw_when_selected_live_ephemeral_stack_is_stale tests/services/test_playback_apply_mode.py tests/services/test_live_graph_eq.py tests/web/test_routes.py tests/audio/test_graph_eq.py -q
```

Expected: the new tests fail for the reasons recorded above. Existing unrelated failures should be investigated before implementation continues.

- [ ] **Step 8: Commit test lock**

Stage only the test files from this slice:

```bash
git add tests/audio/test_renderer.py tests/services/test_playback_apply_mode.py tests/services/test_live_graph_eq.py tests/web/test_routes.py tests/audio/test_graph_eq.py
git diff --cached --name-only
git commit -m "test: Graph EQ 완료 리그레션 고정"
```

Expected staged names do not include `pyproject.toml` or `uv.lock`.

**Live/Stable Risk Handling:** This slice changes only tests, so it cannot change playback behavior. It locks the exact mode-boundary and source-contract regressions before code changes begin.

### slice_1: Live Voice Source Fallback

**Purpose:** Fix the verified Live failure by using `voice_stack_raw.wav` as EQ-free source for Voice in `live_ephemeral` mode when the selected timestamped stack file is stale or missing.

**Files:**

- Modify: `src/secret_pond/audio/renderer.py`
- Modify: `src/secret_pond/audio/source_library.py` only if a shared helper reduces duplication
- Modify: `tests/audio/test_renderer.py`
- Modify: `tests/services/test_playback_apply_mode.py`

- [ ] **Step 1: Keep existing selected source priority**

Preserve this current behavior:

- If selected `voice_stack_path` exists, use it.
- If selected `voice_stack_path` is missing and `voice_stack.mode == "live_ephemeral"` and `paths.voice_stack_raw.exists()`, use `paths.voice_stack_raw`.
- If selected `voice_stack_path` is missing and `voice_stack_raw.wav` is also missing, fail safely with `LiveEqSourceError`.
- If the candidate source is a playback cache path, reject it even if it exists.

- [ ] **Step 2: Implement narrow renderer helper**

In `src/secret_pond/audio/renderer.py`, add a helper shaped like:

```python
def _voice_live_eq_source_path(self, settings: AppSettings, selected_path: Path) -> Path:
    if selected_path.exists():
        return selected_path
    if settings.voice_stack.mode == "live_ephemeral" and self._paths.voice_stack_raw.exists():
        return self._paths.voice_stack_raw
    raise LiveEqSourceError(
        "voice",
        selected_path,
        f"selected Voice Stack source is missing and fallback is unavailable: {self._paths.voice_stack_raw}",
    )
```

Then route `_live_eq_source_path("voice", settings)` through it after playback-cache rejection. Keep low/mid behavior unchanged.

- [ ] **Step 3: Make error detail operator-useful**

Update `LiveEqSourceError` so `str(exc)` includes:

- `layer_id`
- stale selected path when present
- fallback path when checked
- whether the fallback existed

Use relative paths only in UI text later; logger payload can keep the full technical string for now.

- [ ] **Step 4: Run fallback tests**

Run:

```bash
uv run pytest tests/audio/test_renderer.py::test_live_eq_render_uses_voice_stack_raw_when_selected_live_ephemeral_stack_is_stale tests/audio/test_renderer.py::test_live_eq_render_uses_voice_stack_source_not_voice_playback_cache tests/audio/test_renderer.py::test_live_eq_render_reports_missing_eq_free_source_explicitly -q
```

Expected: PASS.

- [ ] **Step 5: Run Stable-to-Live source tests**

Run:

```bash
uv run pytest tests/services/test_playback_apply_mode.py tests/services/test_settings_draft.py -q
```

Expected: PASS. Stable-to-Live with a valid `voice_stack_raw.wav` no longer records `settings.live_graph_eq_failed`.

- [ ] **Step 6: Commit**

```bash
git add src/secret_pond/audio/renderer.py src/secret_pond/audio/source_library.py tests/audio/test_renderer.py tests/services/test_playback_apply_mode.py
git diff --cached --name-only
git commit -m "fix: Live Graph EQ 음성 소스 fallback 추가"
```

Expected staged names do not include `pyproject.toml` or `uv.lock`.

**Live/Stable Risk Handling:** This slice must not hide rollback. It only changes source selection before render. If no EQ-free source exists, Live still fails safely, keeps current playback, logs the failure, and leaves Stable `Apply and Restart` available.

### slice_2: Live Debounce Executor

**Purpose:** Make scheduled Live Graph EQ requests actually run after the 1 second debounce through a server-owned executor path.

**Files:**

- Modify: `src/secret_pond/services/live_graph_eq.py`
- Modify: `src/secret_pond/web/routes.py`
- Modify: `src/secret_pond/web/state.py`
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `tests/services/test_live_graph_eq.py`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/services/test_settings_draft.py`

- [ ] **Step 1: Add state serialization helper**

In `src/secret_pond/services/live_graph_eq.py`, add a pure helper:

```python
def live_graph_eq_payload(runtime: Any) -> dict[str, Any]:
    state = live_graph_eq_state(runtime)
    request = state.pending_request
    status = "idle"
    if request is not None:
        status = "slow" if state.slow_caution else "pending"
    elif state.failure_warning:
        status = "failed"
    return {
        "status": status,
        "pending": request is not None,
        "layer_id": request.layer_id if request is not None else None,
        "request_id": request.request_id if request is not None else None,
        "due_at_ms": request.due_at_ms if request is not None else None,
        "slow_caution": state.slow_caution,
        "failure_warning": state.failure_warning,
        "invalidation_reason": state.invalidation_reason,
    }
```

If `applied` needs to be visible immediately after a tick, return `"applied"` from the route response when `run_due_live_graph_eq_update(...)` returns a request. Do not keep permanent applied status in global state unless tests prove the UI needs it.

- [ ] **Step 2: Expose state in `/api/state`**

In `src/secret_pond/web/state.py`, add under `playback`:

```python
"live_graph_eq": live_graph_eq_payload(runtime),
```

Import the helper from `secret_pond.services.live_graph_eq`.

- [ ] **Step 3: Add explicit executor route**

In `src/secret_pond/web/routes.py`, add:

```python
@router.post("/playback/live-graph-eq/tick")
def tick_live_graph_eq(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    with runtime.operation_lock:
        settings = runtime.controller.settings
        if settings.playback.apply_mode != "live":
            return {
                "applied": False,
                "state": _state_payload(runtime),
            }
        applied = run_due_live_graph_eq_update(runtime) is not None
        mark_slow_live_graph_eq_requests(runtime)
        if applied:
            runtime.mark_state_changed()
        return {
            "applied": applied,
            "state": _state_payload(runtime),
        }
```

For deterministic route tests, allow an optional test-only body field:

```python
class LiveGraphEqTickRequest(BaseModel):
    now_ms: int | None = None
```

Production callers omit it. Tests pass `{"now_ms": pending_request.due_at_ms}`.

- [ ] **Step 4: Add frontend polling/tick hook**

In `src/secret_pond/web/static/app.js`, add a small timer function:

```javascript
let liveGraphEqTickTimer = null;

const scheduleLiveGraphEqTick = (liveGraphEq) => {
  if (liveGraphEqTickTimer) window.clearTimeout(liveGraphEqTickTimer);
  if (currentPlaybackApplyMode() !== "live" || !liveGraphEq?.pending) return;
  const delayMs = Math.max(100, Number(liveGraphEq.due_at_ms || 0) - performance.now());
  liveGraphEqTickTimer = window.setTimeout(async () => {
    liveGraphEqTickTimer = null;
    await control("/api/playback/live-graph-eq/tick", { syncDraft: false }).catch(() => {});
  }, delayMs);
};
```

Call it from `applyState(...)` after `state.snapshot` is refreshed:

```javascript
scheduleLiveGraphEqTick(state.snapshot?.playback?.live_graph_eq);
```

If the backend uses monotonic milliseconds that cannot be compared to `performance.now()`, use a fixed delay of `1000` ms after seeing `pending=true`. Do not make the browser compute audio authority; it only triggers the route.

- [ ] **Step 5: Test latest-wins and Stable exclusion at route level**

Add route tests:

- two rapid draft EQ updates schedule requests 1 and 2;
- POST tick with request 1 due time does not apply request 1 after request 2 supersedes it;
- POST tick with request 2 due time applies request 2;
- switching to Stable before tick invalidates or ignores pending Live Graph EQ and does not call render.

- [ ] **Step 6: Run executor tests**

Run:

```bash
uv run pytest tests/services/test_live_graph_eq.py tests/services/test_settings_draft.py tests/web/test_routes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/secret_pond/services/live_graph_eq.py src/secret_pond/web/routes.py src/secret_pond/web/state.py src/secret_pond/web/static/app.js tests/services/test_live_graph_eq.py tests/services/test_settings_draft.py tests/web/test_routes.py
git diff --cached --name-only
git commit -m "feat: Live Graph EQ debounce 실행 경로 추가"
```

Expected staged names do not include `pyproject.toml` or `uv.lock`.

**Live/Stable Risk Handling:** The route must check `playback.apply_mode == "live"` before rendering. The route runs under `runtime.operation_lock`, keeps request id and `mode_epoch` as latest-wins authority, and leaves Stable edits staged. GET `/api/state` should report state but should not perform render/swap side effects.

### slice_3: Direct-Manipulation Graph EQ UI

**Purpose:** Make the Graph EQ graph behave like a professional curve editor: drag point handles, curve, or graph background to move the nearest editable point.

**Files:**

- Modify: `src/secret_pond/web/static/app.js`
- Modify: `src/secret_pond/web/static/styles.css`
- Modify: `src/secret_pond/web/static/index.html` only if a static container change is needed
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_rendered_dashboard_live_ui.py` if a rendered fixture is added

- [ ] **Step 1: Add nearest-point helpers**

In `app.js`, add:

```javascript
const graphEqNearestPointId = (eq, pointer) => {
  const normalized = normalizeGraphEqSettings(eq);
  if (!normalized.points.length) return null;
  return normalized.points
    .map((point) => {
      const dx = graphEqFrequencyToX(point.frequency_hz) - pointer.x;
      const dy = graphEqGainToY(point.gain_db) - pointer.y;
      return { id: point.id, distance: Math.hypot(dx * 1.25, dy) };
    })
    .sort((a, b) => a.distance - b.distance)[0].id;
};

const graphEqPointFromPointerRatio = (pointer) => ({
  frequency_hz: Math.round(graphEqXToFrequency(pointer.x)),
  gain_db: Number(graphEqYToGain(pointer.y).toFixed(1)),
});
```

Use these helpers from `graphEqPointFromPointerEvent(...)` so static tests can cover coordinate behavior without DOM geometry.

- [ ] **Step 2: Render hit surface and curve target**

In `renderGraphEqEditor(...)`, render this before the zero line and curve:

```javascript
<rect
  class="graph-eq-hit-surface"
  data-graph-eq-hit-surface="true"
  x="0"
  y="0"
  width="1000"
  height="360"
></rect>
```

Render the curve as:

```javascript
<path class="graph-eq-curve" data-graph-eq-curve="true" d="${responsePath}" />
```

Keep point circles after the curve so handles remain visually on top.

- [ ] **Step 3: Start drag from any graph target**

Add `startGraphEqDrag(layerId, pointId, event)`:

```javascript
const startGraphEqDrag = (layerId, pointId, event) => {
  if (!pointId || draftEditLocked()) return;
  event.preventDefault();
  setSelectedGraphEqPoint(layerId, pointId);
  state.graphEqDrag = { layerId, pointId, pointerId: event.pointerId };
  $("graphEqSvg")?.classList.add("drag-active");
  $("graphEqSvg")?.setPointerCapture?.(event.pointerId);
};
```

For point circle pointerdown, use its own id. For SVG pointerdown on `[data-graph-eq-hit-surface]` or `[data-graph-eq-curve]`, compute pointer ratio, choose `graphEqNearestPointId(eq, pointer)`, and start drag.

- [ ] **Step 4: Commit once on pointerup**

During pointermove:

- update local draft point for visual feedback;
- call `syncDraftSnapshot()` and `renderGraphEqWorkspace()`;
- do not call `commitDraftChange(...)` on every pointermove.

On pointerup:

- clear `state.graphEqDrag`;
- remove `drag-active`;
- call one `commitDraftChange(() => {}, { feedbackSurfaceId, feedbackControlIds, afterSync })`.

This keeps Live mode from scheduling dozens of renders while the operator drags.

- [ ] **Step 5: Add CSS affordance**

In `styles.css`, add or adjust:

```css
.graph-eq-hit-surface {
  fill: transparent;
  cursor: grab;
  pointer-events: all;
}

.graph-eq-curve {
  cursor: grab;
  pointer-events: stroke;
}

.graph-eq-svg.drag-active,
.graph-eq-svg.drag-active .graph-eq-hit-surface,
.graph-eq-svg.drag-active .graph-eq-curve,
.graph-eq-svg.drag-active .graph-eq-point {
  cursor: grabbing;
}

.graph-eq-point {
  r: 9px;
}

.graph-eq-point-hit {
  fill: transparent;
  pointer-events: all;
}
```

If SVG `r` cannot be controlled cleanly from CSS across browsers, keep visible point radius in JS and add an invisible `<circle class="graph-eq-point-hit" r="16">` per point. The acceptance target is a desktop hit area of at least 16 CSS px or equivalent SVG units.

- [ ] **Step 6: Run UI static tests**

Run:

```bash
uv run pytest tests/web/test_routes.py -q
```

Expected: PASS for Graph EQ helper, markup, and CSS assertions.

- [ ] **Step 7: Rendered desktop verification**

Run the existing rendered dashboard test if extended:

```bash
uv run pytest tests/web/test_rendered_dashboard_live_ui.py -q
```

Manual/browser check during implementation:

```bash
uv run secret-pond serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/?workspace=graph-eq` at a desktop viewport around `1440x1000` and verify:

- Graph EQ tab is the workspace, not a landing page.
- The graph, Low/Mid/Voice tabs, point controls, and Filter Range fit without incoherent overlap.
- Cursor is `grab` over point handles, curve, and graph background.
- Dragging curve/background selects and moves the nearest point.
- Point controls update after drag.

- [ ] **Step 8: Commit**

```bash
git add src/secret_pond/web/static/app.js src/secret_pond/web/static/styles.css src/secret_pond/web/static/index.html tests/web/test_routes.py tests/web/test_rendered_dashboard_live_ui.py
git diff --cached --name-only
git commit -m "feat: Graph EQ 곡선 드래그 조작 추가"
```

Expected staged names do not include `pyproject.toml` or `uv.lock`.

**Live/Stable Risk Handling:** This slice changes how the draft curve is edited, not audio authority. Stable remains staged. Live render scheduling occurs through the normal draft update path after pointerup, so the debounce executor from slice_2 remains the only Live apply path.

### slice_4: Legacy EQ State Alignment

**Purpose:** Prevent backend audio from using legacy gain fields while the dashboard displays a flat Graph EQ curve.

**Files:**

- Modify: `src/secret_pond/audio/graph_eq.py`
- Modify: `src/secret_pond/config.py` only if model defaults need a narrow compatibility helper
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `tests/audio/test_graph_eq.py`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/test_config.py` if model behavior changes

- [ ] **Step 1: Export effective point helper in Python**

Rename private `_active_points(eq)` to public `effective_graph_eq_points(eq)` or wrap it:

```python
def effective_graph_eq_points(eq: EqSettings) -> list[EqPointSettings]:
    if _uses_legacy_three_band_fields(eq):
        return _legacy_points(eq)
    return sorted(eq.points, key=lambda point: point.frequency_hz)
```

Update `apply_graph_eq(...)` and `graph_eq_response_points(...)` to call `effective_graph_eq_points(eq)`.

- [ ] **Step 2: Add frontend equivalent**

In `app.js`, add:

```javascript
const graphEqUsesLegacyFields = (eq = {}) => {
  const normalized = normalizeGraphEqSettings(eq);
  const defaults = defaultGraphEqPoints();
  const defaultPoints = normalized.points.length === defaults.length &&
    normalized.points.every((point, index) => (
      point.id === defaults[index].id &&
      point.type === defaults[index].type &&
      Number(point.frequency_hz) === Number(defaults[index].frequency_hz) &&
      Number(point.gain_db) === Number(defaults[index].gain_db) &&
      Number(point.q) === Number(defaults[index].q)
    ));
  return defaultPoints && (
    Number(eq.low_gain_db || 0) !== 0 ||
    Number(eq.mid_gain_db || 0) !== 0 ||
    Number(eq.high_gain_db || 0) !== 0
  );
};

const graphEqEffectivePoints = (eq = {}) => {
  if (!graphEqUsesLegacyFields(eq)) return normalizeGraphEqSettings(eq).points;
  return [
    { id: "legacy-low", type: "low_shelf", frequency_hz: 250, gain_db: Number(eq.low_gain_db || 0), q: 0.7 },
    { id: "legacy-mid", type: "bell", frequency_hz: 1000, gain_db: Number(eq.mid_gain_db || 0), q: 1 },
    { id: "legacy-high", type: "high_shelf", frequency_hz: 2000, gain_db: Number(eq.high_gain_db || 0), q: 0.7 },
  ].map(normalizeGraphEqPoint);
};
```

Update `graphEqVisualResponsePoints(...)` and `renderGraphEqEditor(...)` to use effective points for display.

- [ ] **Step 3: Clear legacy fields on new Graph EQ edits**

In `updateDraftGraphEq(layerId, nextEq)`, make new UI-written EQ explicit:

```javascript
layer.eq = {
  ...normalizeGraphEqSettings(nextEq),
  low_gain_db: 0,
  mid_gain_db: 0,
  high_gain_db: 0,
};
```

This keeps future UI edits point-based and stops old fields from invisibly continuing to color audio.

- [ ] **Step 4: Run legacy alignment tests**

Run:

```bash
uv run pytest tests/audio/test_graph_eq.py tests/web/test_routes.py tests/test_config.py -q
```

Expected: PASS. The backend effective points and frontend visual points agree for default points plus legacy gains.

- [ ] **Step 5: Commit**

```bash
git add src/secret_pond/audio/graph_eq.py src/secret_pond/config.py src/secret_pond/web/static/app.js tests/audio/test_graph_eq.py tests/web/test_routes.py tests/test_config.py
git diff --cached --name-only
git commit -m "fix: Graph EQ legacy gain 표시 불일치 정리"
```

Expected staged names do not include `pyproject.toml` or `uv.lock`.

**Live/Stable Risk Handling:** This slice does not remove compatibility input abruptly. It makes backend and UI agree, and makes new edits point-owned. Stable/Live apply semantics remain unchanged.

### slice_5: Operator Feedback, Docs, And Full Verification

**Purpose:** Make operator-facing status clear, document the final behavior, and run the full verification gate.

**Files:**

- Modify: `src/secret_pond/services/live_graph_eq.py`
- Modify: `src/secret_pond/web/state.py`
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `src/secret_pond/web/static/styles.css`
- Modify: `docs/operator-guide.md`
- Modify: `docs/audio-setup-checklist.md`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/test_docs.py` if docs assertions are extended

- [ ] **Step 1: Add source-specific Korean failure detail**

Keep the existing headline:

```text
Live Graph EQ 적용을 완료하지 못했습니다. 기존 재생 상태를 유지합니다. 필요하면 Stable Apply and Restart로 적용하세요.
```

Add detail when available:

- `Voice Stack source가 없습니다: data/sources/voice/stack/VS0608_072702.wav`
- `fallback 확인: data/voice/voice_stack_raw.wav`
- `fallback 사용됨: data/voice/voice_stack_raw.wav`
- `fallback도 없어서 Live 적용을 중단했습니다.`

Do not show a long absolute path in the main UI message. Use relative paths in dashboard text and keep full details in event payload.

- [ ] **Step 2: Show slow pending status without rollback**

When `playback.live_graph_eq.status == "slow"` or `slow_caution == true`, show a nonfatal Korean caution near the Graph EQ status:

```text
Live Graph EQ 적용이 지연되고 있습니다. 재생은 이전 상태로 계속됩니다.
```

This is not a failure and must not clear the pending request by itself.

- [ ] **Step 3: Reflect confirmed audible EQ after failure**

When a Live request fails:

- keep `state.draft` as the operator's staged curve;
- show that audible playback stayed on the last confirmed EQ;
- avoid rendering a success state for the failed curve.

If the existing UI cannot show both draft and confirmed states without adding complexity, use a concise warning:

```text
현재 들리는 EQ는 마지막 성공 상태입니다.
```

- [ ] **Step 4: Update docs**

In `docs/operator-guide.md`, include:

- Drag point handles, curve, or graph background to move the nearest point.
- `Freq`, `Gain`, and `Q` remain English technical controls.
- Live mode applies Graph EQ after roughly 1 second debounce through a server-owned executor.
- Live replacement is fast and not a musical crossfade.
- Voice in `live_ephemeral` can use `data/voice/voice_stack_raw.wav` when selected timestamped stack source is stale.
- Stable `Apply and Restart` remains the recovery path.
- Playback cache files are never EQ-free sources for Live Graph EQ.

In `docs/audio-setup-checklist.md`, include checkboxes for:

- curve/background drag works;
- stale selected Voice Stack path plus existing `voice_stack_raw.wav` does not fail Live mode;
- missing selected and missing fallback shows a specific warning and preserves playback;
- Stable mode does not run the Live executor.

- [ ] **Step 5: Run focused verification**

Run:

```bash
uv run pytest tests/audio/test_renderer.py tests/audio/test_graph_eq.py tests/services/test_live_graph_eq.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py tests/web/test_routes.py tests/test_docs.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full verification**

Run:

```bash
uv run pytest
uv run ruff check .
```

Expected:

- `uv run pytest` passes.
- `uv run ruff check .` reports all checks passed.

- [ ] **Step 7: Rendered desktop dashboard verification**

Run the existing rendered dashboard tests:

```bash
uv run pytest tests/web/test_rendered_dashboard_live_ui.py -q
```

Then run the local server for manual browser verification:

```bash
uv run secret-pond serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/?workspace=graph-eq` and verify:

- desktop width around 1440 px has no incoherent overlap;
- Graph EQ point controls do not overflow their panel;
- Filter Range remains slider-based and visually separate from point controls;
- Live mode pending, slow, failure, and applied status messages are Korean-first;
- technical terms remain English: `Graph EQ`, `Bell / Peak`, `Low Shelf`, `High Shelf`, `Freq`, `Gain`, `Q`, `Low Cut`, `High Cut`, `Live`, `Stable`, `Apply and Restart`.

- [ ] **Step 8: Commit**

```bash
git add src/secret_pond/services/live_graph_eq.py src/secret_pond/web/state.py src/secret_pond/web/static/app.js src/secret_pond/web/static/styles.css docs/operator-guide.md docs/audio-setup-checklist.md tests/web/test_routes.py tests/test_docs.py
git diff --cached --name-only
git commit -m "docs: Graph EQ 완료 동작 안내 추가"
```

Expected staged names do not include `pyproject.toml` or `uv.lock`.

**Live/Stable Risk Handling:** This slice must not add new apply behavior. It makes existing success/failure/slow states visible, preserves rollback wording, and documents Stable as the operator recovery path.

## Final Acceptance Checklist

- [ ] Curve/background drag moves the nearest editable point.
- [ ] Point handles have at least 16 px effective desktop hit target.
- [ ] Live mode schedules a request on Graph EQ draft change and server-owned tick applies it after 1 second debounce.
- [ ] Stable mode does not execute Live Graph EQ requests.
- [ ] Rapid Live edits apply only the latest request.
- [ ] Stale selected Voice Stack path in `live_ephemeral` falls back to `data/voice/voice_stack_raw.wav` when it exists.
- [ ] Missing selected Voice Stack path and missing fallback preserves playback and logs a specific source failure.
- [ ] Playback cache files remain rejected as Live Graph EQ sources.
- [ ] Legacy gain fields and visible Graph EQ curve agree.
- [ ] New Graph EQ UI edits clear legacy gain fields.
- [ ] Operator messages are Korean-first while EQ terms stay English.
- [ ] `uv run pytest` passes.
- [ ] `uv run ruff check .` passes.
- [ ] Rendered desktop dashboard verification passes.

## Implementation Notes

- Keep commits slice-scoped.
- Before every commit, run `git diff --cached --name-only` and confirm `pyproject.toml` and `uv.lock` are absent.
- If a source contract ambiguity appears, stop before using playback cache as fallback.
- If the Live executor route creates measurable latency or lock contention, keep Stable intact and report the exact timing and lock path before expanding scope.
