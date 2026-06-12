# Secret Pond Graph EQ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Seed-defined Graph EQ v1 for The Secret Pond without starting implementation until the user explicitly approves execution.

**Architecture:** Replace the current fixed three-band `EqSettings` workflow with a per-layer Graph EQ point model, keep Stable mode on the existing Apply and Restart path, and move Live mode Graph EQ into a debounced latest-wins render/swap service. The dashboard gets one Graph EQ workspace surface with Low/Mid/Voice layer tabs, selected point controls, and Filter Range, while backend tests protect EQ-free source usage and Live/Stable mode boundaries.

**Tech Stack:** Python 3, Pydantic, NumPy, SciPy/pedalboard, FastAPI services, static HTML/CSS/vanilla JS, pytest, ruff, rendered dashboard verification.

---

## Source Seed

Use this Seed as the authority for scope and acceptance criteria:

- `docs/ouroboros/seed_secret_pond_graph_eq_live_stable_20260612.yaml`

Current known dirty files before planning:

- `pyproject.toml`
- `uv.lock`

Do not edit, format, stage, or commit those dirty files unless the user explicitly expands the scope.

## File Structure

Create:

- `src/secret_pond/audio/graph_eq.py`
  - Owns Graph EQ DSP helpers, point ordering, frequency/gain/Q validation helpers that are not Pydantic-specific, and response-curve sampling for tests/UI approximation if useful.
- `src/secret_pond/services/live_graph_eq.py`
  - Owns Live Graph EQ request ids, mode epochs, debounce scheduling contract, latest-wins discard behavior, rollback state, and buffer replacement orchestration.

Modify:

- `src/secret_pond/config.py`
  - Add `EqPointSettings`, `GraphEqSettings`, point-type literals, defaults, validation, and compatibility defaults for missing fields.
- `src/secret_pond/audio/renderer.py`
  - Replace `_apply_three_band_eq` with Graph EQ rendering while preserving Filter Range and gain order.
  - Make the EQ-free source contract explicit for Live renders.
- `src/secret_pond/audio/player.py`
  - Add or verify buffer replacement keeps frame cursor and uses no more than 50 ms de-click protection.
- `src/secret_pond/services/settings_draft.py`
  - Route Graph EQ draft updates into Stable staged behavior or Live Graph EQ service.
- `src/secret_pond/services/settings_apply.py`
  - Ensure Stable Apply and Restart renders Graph EQ through the existing stable cache path.
- `src/secret_pond/services/playback_apply_mode.py`
  - Harden Live/Stable transitions, pending request invalidation, Stable-to-Live staged-change gate, and EQ-free marker behavior.
- `src/secret_pond/services/settings_changes.py`
  - Classify Graph EQ changes as Live-reprocessable only when playback apply mode is Live.
- `src/secret_pond/web/static/index.html`
  - Add the Graph EQ workspace tab and panel skeleton.
- `src/secret_pond/web/static/app.js`
  - Add Graph EQ state, graph coordinate transforms, point edit actions, Live debounce UI hooks, and mode boundary prompts.
- `src/secret_pond/web/static/styles.css`
  - Add dashboard-native Graph EQ layout, graph editor, point controls, and feedback styling.
- `docs/operator-guide.md`
  - Document operator behavior for Stable/Live Graph EQ and fallback.
- `docs/audio-setup-checklist.md`
  - Add verification and caution notes for Live Graph EQ.

Test:

- `tests/test_config.py`
- `tests/audio/test_graph_eq.py`
- `tests/audio/test_layered_loop_player.py`
- `tests/services/test_settings_draft.py`
- `tests/services/test_settings_apply.py`
- `tests/services/test_playback_apply_mode.py`
- `tests/web/test_routes.py`

## Core Contracts

The implementation should converge on this settings shape unless current-code discovery reveals a safer local variant:

```python
EqPointType = Literal["bell", "low_shelf", "high_shelf"]

class EqPointSettings(BaseModel):
    id: str
    type: EqPointType
    frequency_hz: float = Field(ge=20.0, le=20_000.0)
    gain_db: float = Field(ge=-18.0, le=18.0)
    q: float = Field(default=1.0, ge=0.1, le=18.0)

class EqSettings(BaseModel):
    points: list[EqPointSettings] = Field(default_factory=default_graph_eq_points)
    highpass_hz: float = Field(default=20.0, ge=20.0, le=1_000.0)
    lowpass_hz: float = Field(default=20_000.0, ge=1_000.0, le=20_000.0)
```

Use these constants or close equivalents in one shared place:

```python
GRAPH_EQ_MIN_HZ = 20.0
GRAPH_EQ_MAX_HZ = 20_000.0
GRAPH_EQ_MIN_GAIN_DB = -18.0
GRAPH_EQ_MAX_GAIN_DB = 18.0
GRAPH_EQ_MAX_POINTS = 6
LIVE_EQ_APPLY_DEBOUNCE_MS = 1000
LIVE_EQ_DECLICK_MS = 50
LIVE_EQ_SLOW_APPLY_MS = 3000
```

Default points:

```python
[
    {"id": "low", "type": "low_shelf", "frequency_hz": 120.0, "gain_db": 0.0, "q": 0.7},
    {"id": "mid", "type": "bell", "frequency_hz": 1000.0, "gain_db": 0.0, "q": 1.0},
    {"id": "high", "type": "high_shelf", "frequency_hz": 8000.0, "gain_db": 0.0, "q": 0.7},
]
```

## Task 0: Baseline And Test Harness Audit

**Files:**

- Inspect: `docs/ouroboros/seed_secret_pond_graph_eq_live_stable_20260612.yaml`
- Inspect: `src/secret_pond/config.py`
- Inspect: `src/secret_pond/audio/renderer.py`
- Inspect: `src/secret_pond/services/settings_draft.py`
- Inspect: `src/secret_pond/services/playback_apply_mode.py`
- Inspect: `src/secret_pond/web/static/app.js`
- Inspect: `tests/services/test_settings_draft.py`
- Inspect: `tests/services/test_playback_apply_mode.py`
- Inspect: `tests/web/test_routes.py`

- [ ] **Step 1: Re-check worktree before any implementation**

Run:

```bash
git status --short
```

Expected: `pyproject.toml` and `uv.lock` may already be modified; leave them untouched. The Seed and this plan may be untracked or modified depending on whether they have been committed.

- [ ] **Step 2: Read the Seed and current EQ code**

Run:

```bash
sed -n '1,260p' docs/ouroboros/seed_secret_pond_graph_eq_live_stable_20260612.yaml
sed -n '1,180p' src/secret_pond/config.py
sed -n '1,260p' src/secret_pond/audio/renderer.py
sed -n '1,220p' src/secret_pond/services/settings_draft.py
sed -n '1,180p' src/secret_pond/services/playback_apply_mode.py
```

Expected: confirm the implementation still matches the inspected contracts in this plan.

- [ ] **Step 3: Run current focused tests before edits**

Run:

```bash
uv run pytest tests/test_config.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py tests/web/test_routes.py -q
```

Expected: existing tests pass or any failure is recorded before Graph EQ edits start.

## Task 1: Graph EQ Model

**Files:**

- Modify: `src/secret_pond/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add failing model tests**

Add tests that assert:

```python
def test_graph_eq_defaults_define_three_flat_points() -> None:
    eq = EqSettings()
    assert [(p.type, p.frequency_hz, p.gain_db) for p in eq.points] == [
        ("low_shelf", 120.0, 0.0),
        ("bell", 1000.0, 0.0),
        ("high_shelf", 8000.0, 0.0),
    ]
    assert eq.highpass_hz == 20.0
    assert eq.lowpass_hz == 20_000.0


def test_graph_eq_rejects_more_than_six_points() -> None:
    point = EqSettings().points[1]
    with pytest.raises(ValidationError):
        EqSettings(points=[point.model_copy(update={"id": str(index)}) for index in range(7)])


def test_graph_eq_validates_frequency_gain_and_q() -> None:
    point = EqSettings().points[1]
    with pytest.raises(ValidationError):
        EqSettings(points=[point.model_copy(update={"frequency_hz": 10.0})])
    with pytest.raises(ValidationError):
        EqSettings(points=[point.model_copy(update={"gain_db": 24.0})])
    with pytest.raises(ValidationError):
        EqSettings(points=[point.model_copy(update={"q": 0.0})])
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/test_config.py -q
```

Expected: tests fail because `EqSettings.points` and `EqPointSettings` do not exist yet.

- [ ] **Step 3: Implement Pydantic models**

Modify `src/secret_pond/config.py` to add `EqPointSettings`, `default_graph_eq_points()`, and the new `EqSettings.points` field. Keep `highpass_hz` and `lowpass_hz`.

Migration note: no saved user data migration is required, but missing fields must default safely through Pydantic defaults.

- [ ] **Step 4: Keep compatibility only if required by existing tests**

If old tests or code still read `low_gain_db`, `mid_gain_db`, or `high_gain_db`, update them to Graph EQ semantics in this slice instead of adding long-term duplicate controls. Temporary computed compatibility helpers are acceptable only if they are private and removed by Task 3.

- [ ] **Step 5: Verify model tests**

Run:

```bash
uv run pytest tests/test_config.py -q
```

Expected: PASS.

## Task 2: Graph EQ Render Core

**Files:**

- Create: `src/secret_pond/audio/graph_eq.py`
- Modify: `src/secret_pond/audio/renderer.py`
- Create: `tests/audio/test_graph_eq.py`
- Test: `tests/audio/test_graph_eq.py`

- [ ] **Step 1: Add focused DSP tests**

Create tests for:

- Flat default EQ returns samples close to the input after Filter Range is open.
- Positive Bell / Peak near 1000 Hz increases a 1000 Hz sine more than a 100 Hz sine.
- Low Shelf boosts 100 Hz more than 5000 Hz.
- High Shelf boosts 8000 Hz more than 200 Hz.
- Filter Range still rejects invalid lowpass <= highpass through `EqSettings`.

- [ ] **Step 2: Run failing render tests**

Run:

```bash
uv run pytest tests/audio/test_graph_eq.py -q
```

Expected: FAIL because `secret_pond.audio.graph_eq` does not exist.

- [ ] **Step 3: Implement graph EQ DSP helper**

Create `src/secret_pond/audio/graph_eq.py` with functions:

```python
def apply_graph_eq(samples: np.ndarray, sample_rate: int, eq: EqSettings) -> np.ndarray:
    ...

def graph_eq_response_points(eq: EqSettings, *, width: int = 256) -> list[tuple[float, float]]:
    ...
```

Implementation guidance:

- Apply Filter Range separately in `renderer.py` so Low Cut / High Cut remain visually separate.
- Use `scipy.signal` biquad helpers or `pedalboard` filters where practical.
- Keep processing deterministic and float32.
- Return a copy for neutral EQ so downstream mutation cannot alias source buffers.

- [ ] **Step 4: Wire renderer to Graph EQ**

Modify `src/secret_pond/audio/renderer.py`:

- Replace `_apply_three_band_eq(...)` calls with `apply_graph_eq(...)`.
- Keep order as source canonicalization -> Filter Range -> Graph EQ points -> volume gain -> peak guard.
- Remove `_LOW_BAND_HZ`, `_HIGH_BAND_HZ`, and fixed three-band split when no longer used.

- [ ] **Step 5: Verify render tests**

Run:

```bash
uv run pytest tests/audio/test_graph_eq.py tests/test_config.py -q
```

Expected: PASS.

## Task 3: Stable Integration

**Files:**

- Modify: `src/secret_pond/services/settings_apply.py`
- Modify: `src/secret_pond/services/settings_changes.py`
- Modify: `src/secret_pond/services/playback_apply_mode.py`
- Modify: `tests/services/test_settings_apply.py`
- Modify: `tests/services/test_settings_draft.py`
- Modify: `tests/services/test_playback_apply_mode.py`

- [ ] **Step 1: Add Stable behavior tests**

Add or update tests that assert:

- In Stable mode, changing `layers.mid.eq.points[1].gain_db` changes draft only.
- `runtime.playback_render_settings` and player buffers do not change before Apply and Restart.
- Stable Apply renders the Graph EQ version into playback cache through the existing stable path.
- Runtime-config guards still reject sample-rate/channel/device changes through the existing rules.

- [ ] **Step 2: Run focused Stable tests**

Run:

```bash
uv run pytest tests/services/test_settings_apply.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py -q
```

Expected: Graph EQ-specific tests fail before service wiring is updated.

- [ ] **Step 3: Update settings-change classification**

Modify `src/secret_pond/services/settings_changes.py` so Graph EQ point changes are recognized as layer EQ changes. Keep sample rate, channel count, loop length, device selection, and source selection outside Live Graph EQ scope.

- [ ] **Step 4: Update Stable apply path**

Modify `src/secret_pond/services/settings_apply.py` and existing render calls so Stable Apply and Restart uses the new `EqSettings.points` model with no special Live shortcut.

- [ ] **Step 5: Update playback apply mode EQ-free marker**

Modify `src/secret_pond/services/playback_apply_mode.py` so `_eq_free_render_marker(...)` resets Graph EQ to default flat points and open Filter Range.

- [ ] **Step 6: Verify Stable integration**

Run:

```bash
uv run pytest tests/services/test_settings_apply.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py -q
```

Expected: PASS for Stable Graph EQ tests and existing Stable/Live tests adjusted to the new model.

## Task 4: Graph EQ Dashboard UI

**Files:**

- Modify: `src/secret_pond/web/static/index.html`
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `src/secret_pond/web/static/styles.css`
- Modify: `tests/web/test_routes.py`

- [ ] **Step 1: Add static UI tests for structure**

Update `tests/web/test_routes.py` to assert:

- `workspaceTabNames` includes `"graph-eq"` or the chosen tab id.
- Markup includes `workspaceTabGraphEq`, `workspacePaneGraphEq`, `graphEqLayerTabs`, `graphEqEditor`, `graphEqPointControls`, and `graphEqFilterRange`.
- Old fixed paths `eq.low_gain_db`, `eq.mid_gain_db`, and `eq.high_gain_db` are no longer primary layer controls.
- Copy includes `Graph EQ`, `Bell / Peak`, `Low Shelf`, `High Shelf`, `Freq`, `Gain`, `Q`, `Low Cut`, `High Cut`, and `점을 선택하세요`.

- [ ] **Step 2: Run failing UI tests**

Run:

```bash
uv run pytest tests/web/test_routes.py -q
```

Expected: new Graph EQ UI tests fail before static files are updated.

- [ ] **Step 3: Add Graph EQ workspace markup**

Modify `src/secret_pond/web/static/index.html`:

- Add Graph EQ tab beside Treatment / Voice Stack / Loop Mixer.
- Add one Graph EQ panel with Low/Mid/Voice layer tabs.
- Add graph surface, selected point controls, + Point, Delete, selected reset, all reset, and Filter Range section.

- [ ] **Step 4: Add Graph EQ UI state and coordinate helpers**

Modify `src/secret_pond/web/static/app.js`:

- Add log-frequency mapping helpers for 20 Hz to 20 kHz.
- Add gain mapping helpers for -18 dB to +18 dB.
- Add selected point state per layer.
- Implement drag draft update during pointer movement.
- Persist/schedule only on pointer up, Enter, or blur.
- Show `점을 선택하세요` when no point is selected.

- [ ] **Step 5: Remove duplicated old EQ controls**

Retire fixed `Tone EQ` controls from `layerControlGroups` so the operator does not see two conflicting EQ models. Keep Level and Filter Range only where still appropriate, with Filter Range moved or reused in the Graph EQ panel.

- [ ] **Step 6: Add CSS in existing dashboard style**

Modify `src/secret_pond/web/static/styles.css`:

- Use existing dark panel, compact control, status-pill, feedback-surface patterns.
- Keep stable dimensions for graph, handles, tabs, and numeric controls.
- Avoid mobile-specific editing work; allow horizontal overflow if needed.

- [ ] **Step 7: Verify UI tests**

Run:

```bash
uv run pytest tests/web/test_routes.py -q
```

Expected: PASS.

## Task 5: Live Debounce, Render, And Buffer Swap

**Files:**

- Create: `src/secret_pond/services/live_graph_eq.py`
- Modify: `src/secret_pond/services/settings_draft.py`
- Modify: `src/secret_pond/audio/player.py`
- Modify: `tests/services/test_settings_draft.py`
- Modify: `tests/audio/test_layered_loop_player.py`

- [ ] **Step 1: Add Live debounce service tests**

Add service tests that assert:

- First edit creates pending request id 1 with mode epoch N.
- A second edit before debounce replaces request id 1 with request id 2.
- Only request id 2 may call `render_live_eq_layer_buffer`.
- A slow request marks a caution state after `LIVE_EQ_SLOW_APPLY_MS`.
- A stale finished request is discarded if request id or mode epoch no longer matches.

- [ ] **Step 2: Add player buffer continuity test**

In `tests/audio/test_layered_loop_player.py`, assert that replacing a layer buffer preserves `frame_cursor` and next block advances from the same cursor. If a de-click ramp is implemented in `player.py`, assert it is bounded by `LIVE_EQ_DECLICK_MS`.

- [ ] **Step 3: Run failing Live tests**

Run:

```bash
uv run pytest tests/services/test_settings_draft.py tests/audio/test_layered_loop_player.py -q
```

Expected: new Live debounce/latest-wins tests fail before service implementation.

- [ ] **Step 4: Implement Live Graph EQ service**

Create `src/secret_pond/services/live_graph_eq.py` with a small explicit API:

```python
def schedule_live_graph_eq_update(runtime: SecretPondRuntime, layer_id: str, next_settings: AppSettings) -> LiveGraphEqState:
    ...

def invalidate_live_graph_eq_requests(runtime: SecretPondRuntime, reason: str) -> None:
    ...

def confirmed_live_graph_eq(runtime: SecretPondRuntime, layer_id: str) -> EqSettings:
    ...
```

Use request id + mode epoch. Do rendering outside the audio callback. Keep rollback state as the last confirmed audible `EqSettings`.

- [ ] **Step 5: Route Live draft EQ through the service**

Modify `src/secret_pond/services/settings_draft.py`:

- In Live mode, Graph EQ edits should save draft state, mark Live feedback pending, and schedule the service.
- Do not call `render_live_eq_layer_buffer` synchronously for every keystroke or pointer movement.
- Keep Live volume/mute behavior unchanged unless a test shows it must be adapted to the new model.

- [ ] **Step 6: Verify Live debounce and swap**

Run:

```bash
uv run pytest tests/services/test_settings_draft.py tests/audio/test_layered_loop_player.py -q
```

Expected: PASS.

## Task 6: Live/Stable Boundary And Rollback

**Files:**

- Modify: `src/secret_pond/services/playback_apply_mode.py`
- Modify: `src/secret_pond/services/live_graph_eq.py`
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `tests/services/test_playback_apply_mode.py`
- Modify: `tests/services/test_settings_draft.py`
- Modify: `tests/web/test_routes.py`

- [ ] **Step 1: Add mode boundary tests**

Add tests that assert:

- Live -> Stable invalidates pending Live Graph EQ requests.
- A late Live render result after Live -> Stable is discarded.
- The Graph EQ edit remains a Stable staged draft after Live -> Stable.
- Stable -> Live with staged Graph EQ changes exposes apply, discard, and cancel choices.

- [ ] **Step 2: Add failure rollback tests**

Add tests that assert:

- Failed render keeps current playback alive.
- Failed swap restores player snapshot.
- UI draft rolls back to the last confirmed audible EQ state.
- Korean warning mentions Stable Apply and Restart fallback.

- [ ] **Step 3: Run failing boundary tests**

Run:

```bash
uv run pytest tests/services/test_playback_apply_mode.py tests/services/test_settings_draft.py tests/web/test_routes.py -q
```

Expected: new boundary and rollback tests fail before implementation.

- [ ] **Step 4: Implement mode epoch invalidation**

Modify `src/secret_pond/services/playback_apply_mode.py`:

- On Live -> Stable, call `invalidate_live_graph_eq_requests(...)`.
- Restore stable rendered artifacts through the existing path.
- Preserve the graph edit in `draft`.

- [ ] **Step 5: Implement Stable -> Live staged-change gate**

Modify `src/secret_pond/web/static/app.js` and route/service handling:

- Prompt the operator when staged Graph EQ changes exist.
- Apply choice schedules Live Graph EQ.
- Discard choice syncs draft Graph EQ from active.
- Cancel choice leaves mode unchanged.

- [ ] **Step 6: Implement rollback feedback**

Wire service failure state into existing `liveApplyFeedbackStates` or a Graph EQ-specific extension:

- `pending`
- `applying`
- `applied`
- `failed`
- `stale`
- slow caution message `적용이 오래 걸리는 중`

- [ ] **Step 7: Verify boundary and rollback**

Run:

```bash
uv run pytest tests/services/test_playback_apply_mode.py tests/services/test_settings_draft.py tests/web/test_routes.py -q
```

Expected: PASS.

## Task 7: EQ-Free Source Contract

**Files:**

- Modify: `src/secret_pond/audio/renderer.py`
- Modify: `src/secret_pond/services/live_graph_eq.py`
- Modify: `src/secret_pond/services/playback_apply_mode.py`
- Modify: `tests/audio/test_graph_eq.py`
- Modify: `tests/services/test_settings_draft.py`
- Modify: `tests/services/test_playback_apply_mode.py`

- [ ] **Step 1: Add no-double-EQ tests**

Add tests that assert:

- Live low/mid Graph EQ render reads selected source material, not `low_playback.wav` or `mid_playback.wav`.
- Live voice Graph EQ render reads EQ-free `voice_stack_raw` or selected voice stack material, not `voice_playback.wav`.
- If an EQ-free source is missing, the operation fails safely and keeps current playback.

- [ ] **Step 2: Run failing source tests**

Run:

```bash
uv run pytest tests/audio/test_graph_eq.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py -q
```

Expected: no-double-EQ tests fail if current paths are ambiguous.

- [ ] **Step 3: Make source contract explicit**

Modify `src/secret_pond/audio/renderer.py`:

- Keep `render_layer(...)` for Stable playback cache generation.
- Add or clarify `render_live_eq_layer_buffer(...)` so it documents and enforces EQ-free source selection.
- Raise a specific exception if the EQ-free source cannot be resolved.

- [ ] **Step 4: Wire source failures to rollback**

Modify `src/secret_pond/services/live_graph_eq.py` and `playback_apply_mode.py` so missing/unsafe source resolution triggers the same nonfatal Korean rollback path as render/swap failure.

- [ ] **Step 5: Verify source contract**

Run:

```bash
uv run pytest tests/audio/test_graph_eq.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py -q
```

Expected: PASS.

## Task 8: Docs And Rendered Dashboard Verification

**Files:**

- Modify: `docs/operator-guide.md`
- Modify: `docs/audio-setup-checklist.md`
- Verify: static dashboard in browser

- [ ] **Step 1: Update operator docs**

Document in Korean-first language:

- Stable mode: point edits are staged until Apply and Restart.
- Live mode: point edits apply after roughly 1 second debounce and should be audible within the 3 second target.
- Failure: playback continues, graph rolls back to confirmed audible state, and Stable Apply and Restart remains available.
- Source safety: Live Graph EQ must not be applied on already-EQ-rendered playback caches.

- [ ] **Step 2: Update audio checklist**

Add a checklist section for:

- Confirm default flat Graph EQ is neutral.
- Confirm Low/Mid/Voice each update independently.
- Confirm Live failure fallback.
- Confirm local hardware timing for typical source files.

- [ ] **Step 3: Run full automated verification**

Run:

```bash
uv run pytest
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 4: Run rendered dashboard verification**

Start the existing local app command used in this repo. If no command is already documented, inspect `README.md` or `pyproject.toml` scripts first.

Then verify in browser:

- Graph EQ tab appears in the workspace tabs.
- Low/Mid/Voice tabs switch without layout shift.
- Selected point controls do not overlap the graph.
- Long Korean status messages do not push header/status rows into incoherent overlap.
- Narrow desktop width may scroll horizontally but controls remain reachable.

- [ ] **Step 5: Record final implementation report**

Final report should include:

- Tests run and outcome.
- Rendered dashboard verification outcome.
- Manual audio checks still needed on physical hardware.
- Any measured Live apply timing if available.

## Commit Strategy

Commit only after a slice is passing its targeted tests. Keep `pyproject.toml` and `uv.lock` out of every commit unless the user explicitly approves dependency changes.

Recommended commit sequence:

```bash
git add src/secret_pond/config.py tests/test_config.py
git commit -m "feat: Graph EQ 설정 모델 추가"

git add src/secret_pond/audio/graph_eq.py src/secret_pond/audio/renderer.py tests/audio/test_graph_eq.py
git commit -m "feat: Graph EQ 렌더링 추가"

git add src/secret_pond/services/settings_apply.py src/secret_pond/services/settings_changes.py src/secret_pond/services/playback_apply_mode.py tests/services/test_settings_apply.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py
git commit -m "feat: Stable Graph EQ 적용 경로 추가"

git add src/secret_pond/web/static/index.html src/secret_pond/web/static/app.js src/secret_pond/web/static/styles.css tests/web/test_routes.py
git commit -m "feat: Graph EQ 대시보드 추가"

git add src/secret_pond/services/live_graph_eq.py src/secret_pond/services/settings_draft.py src/secret_pond/audio/player.py tests/services/test_settings_draft.py tests/audio/test_layered_loop_player.py
git commit -m "feat: Live Graph EQ 적용 흐름 추가"

git add src/secret_pond/services/playback_apply_mode.py src/secret_pond/services/live_graph_eq.py src/secret_pond/web/static/app.js tests/services/test_playback_apply_mode.py tests/services/test_settings_draft.py tests/web/test_routes.py
git commit -m "feat: Graph EQ 모드 전환 보호 추가"

git add src/secret_pond/audio/renderer.py src/secret_pond/services/live_graph_eq.py src/secret_pond/services/playback_apply_mode.py tests/audio/test_graph_eq.py tests/services/test_settings_draft.py tests/services/test_playback_apply_mode.py
git commit -m "fix: Live Graph EQ 중복 적용 방지"

git add docs/operator-guide.md docs/audio-setup-checklist.md
git commit -m "docs: Graph EQ 운영 안내 추가"
```

## Risk Controls

- Double EQ risk: block Live render from playback cache paths unless the cache is explicitly EQ-free.
- Mode ambiguity risk: keep Live request state keyed by request id and mode epoch.
- UI ambiguity risk: show Live feedback states near Graph EQ and keep Stable Apply and Restart messaging only where it is actually required.
- Performance risk: measure debounce + render + swap and show nonfatal caution after 3 seconds.
- Scope risk: do not add analyzer, presets, undo/redo, keyboard shortcuts, or mobile-first editing behavior in v1.

## Self-Review

- Spec coverage: each Seed slice maps to a task above.
- Placeholder scan: this plan avoids open-ended placeholders and defines expected tests, files, commands, and contracts.
- Type consistency: `EqPointSettings`, `EqSettings.points`, `live_graph_eq`, request id, mode epoch, and EQ-free source language are used consistently across tasks.
