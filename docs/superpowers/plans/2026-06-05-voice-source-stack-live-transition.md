# Voice Source Stack Live Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement amended Seed `seed_58148696dd2f`: complete the VR/VS storage policy and add a bounded `live_ephemeral` post-recording voice-layer crossfade while preserving the Stable `Apply and Restart` fallback.

**Architecture:** Split storage, naming, recording workflow policy, and playback transition responsibilities before changing behavior. The live transition is not a full realtime engine replacement; it is a narrow voice-layer hot-swap path for accepted `live_ephemeral` recordings only. The UI must show the operator whether they are using the live transition path or the Stable rendered-cache fallback.

**Tech Stack:** Python 3.11/3.12, FastAPI, Pydantic, NumPy, sounddevice, browser dashboard JavaScript/CSS, `uv run pytest`, `uv run ruff check .`.

---

## Current Facts

- `src/secret_pond/services/recording_workflow.py` currently refreshes accepted recordings with `runtime.player.reload_and_restart(...)` while output is running.
- `src/secret_pond/audio/player.py` currently stores rendered `low`, `mid`, and `voice` buffers in one map and uses one shared cursor.
- `src/secret_pond/audio/voice_stack.py` currently owns stack mixing, timestamped raw/stack naming, manifest writes, and mirror writes.
- `src/secret_pond/audio/source_library.py` and `src/secret_pond/services/source_library_mutations.py` already expose source listing/upload/delete/select foundations.
- The UI already has Source Library, storage-mode controls, caution notices, operation locks, and stale-response guards.

## File Structure

Create:
- `src/secret_pond/audio/voice_stack_naming.py` - KST VR/VS filename generation and collision suffix policy.
- `src/secret_pond/services/voice_source_service.py` - canonical VR creation, VR selection metadata, and preview source preparation.
- `src/secret_pond/services/voice_stack_service.py` - Add to Stack orchestration and `voice_stack_raw.wav` mirror/update contract.
- `tests/audio/test_voice_stack_naming.py`
- `tests/services/test_voice_source_service.py`
- `tests/services/test_voice_stack_service.py`

Modify:
- `src/secret_pond/config.py` - add bounded voice transition setting.
- `src/secret_pond/audio/voice_stack.py` - delegate naming and expose stack creation primitives without always writing VR.
- `src/secret_pond/audio/player.py` - add voice-only equal-power transition API.
- `src/secret_pond/audio/renderer.py` - keep rendered-cache path stable and add a named helper for rendering only the voice layer into the current voice playback cache.
- `src/secret_pond/services/controller.py` - split recording behavior by `voice_stack.mode`.
- `src/secret_pond/services/recording_workflow.py` - apply post-recording transition policy and failure logging.
- `src/secret_pond/services/runtime.py` - track playback session identity and wire new services.
- `src/secret_pond/web/state.py` - expose playback transition state/warnings.
- `src/secret_pond/web/routes.py` - add VR preview/Add to Stack endpoints and return transition warnings in state.
- `src/secret_pond/web/static/app.js` - Source Library VR actions, Add to Stack action, live transition/Stable fallback UI states.
- `src/secret_pond/web/static/index.html` - transition status nodes and VR preview controls.
- `src/secret_pond/web/static/styles.css` - compact operational UI for transition mode, warnings, and VR action rows.
- `tests/audio/test_voice_stack.py`
- `tests/audio/test_layered_loop_player.py`
- `tests/audio/test_player_mixer.py`
- `tests/services/test_controller.py`
- `tests/services/test_recording_workflow.py`
- `tests/services/test_runtime.py`
- `tests/web/test_routes.py`
- `tests/test_config.py`
- `tests/test_docs.py`
- `docs/operator-guide.md`
- `docs/audio-setup-checklist.md`

## Task 1: KST VR/VS Naming Policy

**Files:**
- Create: `src/secret_pond/audio/voice_stack_naming.py`
- Create: `tests/audio/test_voice_stack_naming.py`
- Modify: `src/secret_pond/audio/voice_stack.py`
- Modify: `tests/audio/test_voice_stack.py`
- Modify: `tests/web/test_routes.py`

- [ ] **Step 1: Write failing naming tests**

Add tests that pin the exact Seed naming contract:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from secret_pond.audio.voice_stack_naming import next_voice_raw_path, next_voice_stack_path
from secret_pond.paths import ProjectPaths


def test_next_voice_raw_path_uses_kst_vr_name(tmp_path):
    paths = ProjectPaths(tmp_path)
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    path = next_voice_raw_path(paths, now=now)

    assert path == paths.voice_raw_sources_dir / "VR0610_213112.wav"


def test_next_voice_stack_path_uses_kst_vs_name(tmp_path):
    paths = ProjectPaths(tmp_path)
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    path = next_voice_stack_path(paths, now=now)

    assert path == paths.voice_stack_sources_dir / "VS0610_213112.wav"


def test_voice_name_collision_suffixes_start_at_two(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))
    (paths.voice_raw_sources_dir / "VR0610_213112.wav").write_bytes(b"one")
    (paths.voice_raw_sources_dir / "VR0610_213112_2.wav").write_bytes(b"two")

    path = next_voice_raw_path(paths, now=now)

    assert path == paths.voice_raw_sources_dir / "VR0610_213112_3.wav"
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
uv run pytest tests/audio/test_voice_stack_naming.py -q
```

Expected: FAIL because `secret_pond.audio.voice_stack_naming` does not exist.

- [ ] **Step 3: Implement the naming module**

Create `src/secret_pond/audio/voice_stack_naming.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from secret_pond.paths import ProjectPaths

KST = ZoneInfo("Asia/Seoul")


def next_voice_raw_path(paths: ProjectPaths, *, now: datetime | None = None) -> Path:
    paths.voice_raw_sources_dir.mkdir(parents=True, exist_ok=True)
    return _next_timestamped_path(paths.voice_raw_sources_dir, "VR", now=now)


def next_voice_stack_path(paths: ProjectPaths, *, now: datetime | None = None) -> Path:
    paths.voice_stack_sources_dir.mkdir(parents=True, exist_ok=True)
    return _next_timestamped_path(paths.voice_stack_sources_dir, "VS", now=now)


def _next_timestamped_path(directory: Path, prefix: str, *, now: datetime | None) -> Path:
    timestamp = _kst_timestamp(now)
    candidate = directory / f"{prefix}{timestamp}.wav"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{prefix}{timestamp}_{suffix}.wav"
        suffix += 1
    return candidate


def _kst_timestamp(now: datetime | None) -> str:
    value = now or datetime.now(tz=KST)
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    return value.astimezone(KST).strftime("%m%d_%H%M%S")
```

- [ ] **Step 4: Replace UTC timestamp helpers in `voice_stack.py`**

Change `_timestamped_raw_path` and `_timestamped_stack_path` to delegate:

```python
from secret_pond.audio.voice_stack_naming import next_voice_raw_path, next_voice_stack_path


def _timestamped_raw_path(paths: ProjectPaths) -> Path:
    return next_voice_raw_path(paths)


def _timestamped_stack_path(paths: ProjectPaths) -> Path:
    return next_voice_stack_path(paths)
```

- [ ] **Step 5: Update existing timestamp assertions**

Replace `assert_timestamped_voice_filename(..., "-raw.wav")` and `"-stack.wav"` helpers in `tests/web/test_routes.py` with VR/VS assertions:

```python
def assert_voice_source_filename(path: str, prefix: str) -> None:
    name = Path(path).name
    assert name.startswith(prefix)
    assert name.endswith(".wav")
    timestamp = name.removeprefix(prefix).removesuffix(".wav")
    base, *suffix = timestamp.split("_")
    assert len(base) == 4
    assert base.isdigit()
    assert len(suffix[0]) == 6
    assert suffix[0].isdigit()
```

- [ ] **Step 6: Run naming and affected storage tests**

Run:

```bash
uv run pytest tests/audio/test_voice_stack_naming.py tests/audio/test_voice_stack.py tests/web/test_routes.py::test_recording_acceptance_persists_timestamped_voice_stack_selection -q
```

Expected: PASS after adapting assertions to `VR...` and `VS...`.

- [ ] **Step 7: Commit**

```bash
git add src/secret_pond/audio/voice_stack_naming.py src/secret_pond/audio/voice_stack.py tests/audio/test_voice_stack_naming.py tests/audio/test_voice_stack.py tests/web/test_routes.py
git commit -m "feat: KST VR VS 파일명 정책 추가"
```

## Task 2: Storage Policy Services

**Files:**
- Create: `src/secret_pond/services/voice_source_service.py`
- Create: `src/secret_pond/services/voice_stack_service.py`
- Create: `tests/services/test_voice_source_service.py`
- Create: `tests/services/test_voice_stack_service.py`
- Modify: `src/secret_pond/audio/voice_stack.py`
- Modify: `src/secret_pond/services/controller.py`
- Modify: `tests/services/test_controller.py`

- [ ] **Step 1: Write tests for canonical pre-treatment VR**

Add `tests/services/test_voice_source_service.py`:

```python
from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav
from secret_pond.config import AppSettings, AudioFormatSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.voice_source_service import VoiceSourceService


def test_save_vr_source_stores_canonical_pre_treatment_source(tmp_path):
    paths = ProjectPaths(tmp_path)
    settings = AppSettings(audio=AudioFormatSettings(sample_rate=8_000, channels=2))
    mono = AudioBuffer(samples=np.ones(400, dtype=np.float32) * 0.25, sample_rate=4_000)

    result = VoiceSourceService(paths).save_recording_source(mono, settings)

    assert result.relative_path.startswith("data/sources/voice/raw/VR")
    stored = read_wav(tmp_path / result.relative_path)
    assert stored.sample_rate == 8_000
    assert stored.channels == 2
    assert float(stored.samples.max()) == 0.25
```

- [ ] **Step 2: Write tests for mode split in controller**

In `tests/services/test_controller.py`, add one test for `test_library` and one for `live_ephemeral`:

```python
def test_controller_test_library_saves_vr_without_adding_to_stack() -> None:
    controller, _, voice_stack, renderer, participants, _, clock = controller_fixture()
    controller.settings.voice_stack.mode = "test_library"

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert voice_stack.calls == []
    assert renderer.rendered_layers == []
    assert participants.count == 1


def test_controller_live_ephemeral_adds_to_stack_without_retaining_vr() -> None:
    controller, _, voice_stack, renderer, participants, _, clock = controller_fixture()
    controller.settings.voice_stack.mode = "live_ephemeral"

    controller.arm_input()
    controller.start_recording()
    clock.advance(1.2)
    outcome = controller.stop_recording()

    assert outcome.accepted is True
    assert len(voice_stack.calls) == 1
    assert renderer.rendered_layers == ["voice"]
    assert participants.count == 1
```

- [ ] **Step 3: Run failing service/controller tests**

Run:

```bash
uv run pytest tests/services/test_voice_source_service.py tests/services/test_controller.py::test_controller_test_library_saves_vr_without_adding_to_stack tests/services/test_controller.py::test_controller_live_ephemeral_adds_to_stack_without_retaining_vr -q
```

Expected: FAIL because the service does not exist and controller still always adds to stack.

- [ ] **Step 4: Implement `VoiceSourceService`**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.voice_stack_naming import next_voice_raw_path
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths


@dataclass(frozen=True)
class VoiceSourceSaveResult:
    relative_path: str


class VoiceSourceService:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def save_recording_source(
        self,
        recording: AudioBuffer,
        settings: AppSettings,
    ) -> VoiceSourceSaveResult:
        canonical = recording.to_canonical(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        path = next_voice_raw_path(self._paths)
        write_wav_atomic(path, canonical)
        return VoiceSourceSaveResult(relative_path=_relative_path(self._paths, path))


def _relative_path(paths: ProjectPaths, path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()
```

- [ ] **Step 5: Implement `VoiceStackService` orchestration shell**

Create `src/secret_pond/services/voice_stack_service.py` with an API that can be used by routes later:

```python
from __future__ import annotations

from dataclasses import dataclass

from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.file_io import read_wav
from secret_pond.audio.voice_stack import VoiceStackAddResult, VoiceStackStore
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths


@dataclass(frozen=True)
class AddVoiceSourceToStackResult:
    stack_result: VoiceStackAddResult
    selected_voice_stack_path: str | None


class VoiceStackService:
    def __init__(self, paths: ProjectPaths, store: VoiceStackStore) -> None:
        self._paths = paths
        self._store = store

    def add_vr_to_stack(
        self,
        vr_relative_path: str,
        settings: AppSettings,
    ) -> AddVoiceSourceToStackResult:
        source_path = (self._paths.root / vr_relative_path).resolve()
        source = read_wav(source_path).to_canonical(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        treated = apply_recording_processing(source, settings.recording)
        stack_result = self._store.add_processed_voice(
            treated,
            settings,
            processing_settings_snapshot=settings.recording.model_dump(mode="json"),
        )
        return AddVoiceSourceToStackResult(
            stack_result=stack_result,
            selected_voice_stack_path=stack_result.voice_stack_path,
        )
```

- [ ] **Step 6: Update controller mode split**

In `RecordingController.stop_recording`, keep canonicalization before treatment. Branch:

```python
canonical_recording = recorded.to_canonical(
    sample_rate=max(recorded.sample_rate, self._settings.audio.sample_rate),
    channels=self._settings.audio.channels,
)
if self._settings.voice_stack.mode == "test_library":
    source_result = self._voice_source.save_recording_source(canonical_recording, self._settings)
    self._settings.sources.voice_raw_path = source_result.relative_path
    render_result = None
    stack_result = None
else:
    processed = apply_recording_processing(canonical_recording, self._settings.recording)
    stack_result = self._voice_stack.add_processed_voice(...)
    render_result = self._renderer.render_layer("voice", self._settings)
```

If `RecordingController` constructor currently lacks `voice_source`, add a dependency with a small protocol/default in `runtime.build_runtime`.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/services/test_voice_source_service.py tests/services/test_voice_stack_service.py tests/services/test_controller.py -q
```

Expected: PASS after adapting fakes to include the new dependency.

- [ ] **Step 8: Commit**

```bash
git add src/secret_pond/services/voice_source_service.py src/secret_pond/services/voice_stack_service.py src/secret_pond/services/controller.py src/secret_pond/services/runtime.py tests/services/test_voice_source_service.py tests/services/test_voice_stack_service.py tests/services/test_controller.py
git commit -m "feat: VR VS 저장 정책 분리"
```

## Task 3: Source Library API for VR Preview and Add to Stack

**Files:**
- Modify: `src/secret_pond/web/routes.py`
- Modify: `src/secret_pond/web/state.py`
- Modify: `src/secret_pond/services/playback_control.py`
- Modify: `tests/web/test_routes.py`

- [ ] **Step 1: Add failing API tests**

Add route tests:

```python
def test_api_add_voice_raw_to_selected_stack_creates_new_vs_and_mirror(tmp_path: Path) -> None:
    settings = api_settings_for_sixty_second_voice_loop(mode="test_library")
    client = create_test_client(tmp_path, with_sources=True, settings=settings)
    paths = ProjectPaths(tmp_path)
    vr_path = paths.voice_raw_sources_dir / "VR0610_213112.wav"
    write_wav_atomic(vr_path, twenty_second_voice_take())

    response = client.post(
        "/api/voice-stack/add-source",
        json={"voice_raw_path": "data/sources/voice/raw/VR0610_213112.wav"},
    )

    assert response.status_code == 200
    selected = response.json()["settings"]["active"]["sources"]["voice_stack_path"]
    assert selected.startswith("data/sources/voice/stack/VS")
    assert (tmp_path / selected).exists()
    assert paths.voice_stack_raw.exists()


def test_api_voice_raw_preview_stops_main_playback_and_starts_preview(tmp_path: Path) -> None:
    output = FakeOutput()
    client = create_test_client(tmp_path, with_sources=True, output=output)
    paths = ProjectPaths(tmp_path)
    vr_path = paths.voice_raw_sources_dir / "VR0610_213112.wav"
    write_wav_atomic(vr_path, twenty_second_voice_take())

    client.post("/api/settings/apply-and-restart")
    client.post("/api/playback/start")
    response = client.post(
        "/api/voice-raw/preview",
        json={"voice_raw_path": "data/sources/voice/raw/VR0610_213112.wav"},
    )

    assert response.status_code == 200
    assert response.json()["preview"]["playing"] is True
    assert output.stop_calls == 1
    assert output.start_calls == 2
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
uv run pytest tests/web/test_routes.py::test_api_add_voice_raw_to_selected_stack_creates_new_vs_and_mirror tests/web/test_routes.py::test_api_voice_raw_preview_stops_main_playback_and_starts_preview -q
```

Expected: FAIL because endpoints do not exist.

- [ ] **Step 3: Add Add-to-Stack route**

Add endpoint:

```python
@router.post("/voice-stack/add-source")
def add_voice_raw_to_stack(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    relative_path = str(payload.get("voice_raw_path") or "")
    with runtime.operation_lock:
        settings = runtime.settings_state.active
        result = runtime.voice_stack_service.add_vr_to_stack(relative_path, settings)
        runtime.settings_store.save(
            SettingsState(active=settings, draft=settings.model_copy(deep=True)),
        )
        runtime.settings_state = runtime.settings_store.load()
        runtime.mark_state_changed()
        return {
            "add_to_stack": {"voice_stack_path": result.selected_voice_stack_path},
            "settings": _settings_payload(runtime),
            "state": _state_payload(runtime),
            "sources": _sources_payload(runtime, runtime.settings_state),
        }
```

Wire `voice_stack_service` into `SecretPondRuntime`.

- [ ] **Step 4: Add preview route with mutual exclusion**

Implement preview by stopping main playback, preparing the selected VR with current Voice Treatment, loading a voice-only preview layer set, and starting output:

```python
@router.post("/voice-raw/preview")
def preview_voice_raw(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(request)
    relative_path = str(payload.get("voice_raw_path") or "")
    with runtime.operation_lock:
        playback_control.stop_playback_if_running(runtime)
        preview_layers = runtime.voice_source_service.preview_layers(
            relative_path,
            runtime.settings_state.active,
        )
        if preview_layers is None:
            raise HTTPException(status_code=404, detail="voice raw source does not exist")
        runtime.player.load_rendered_buffers(preview_layers)
        runtime.output.start()
        runtime.mark_state_changed()
        return {"preview": {"voice_raw_path": relative_path, "playing": True}, "state": _state_payload(runtime)}
```

Add `VoiceSourceService.preview_layers(...)` so it returns silent low/mid buffers and a treated voice buffer matching the active audio format and loop length. Add `LayeredLoopPlayer.load_rendered_buffers(...)` as a buffer-based sibling to `load_rendered_layers(...)`.

- [ ] **Step 5: Run API tests**

Run:

```bash
uv run pytest tests/web/test_routes.py::test_api_add_voice_raw_to_selected_stack_creates_new_vs_and_mirror tests/web/test_routes.py::test_api_voice_raw_preview_stops_main_playback_and_starts_preview -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/secret_pond/web/routes.py src/secret_pond/web/state.py src/secret_pond/services/playback_control.py src/secret_pond/services/runtime.py tests/web/test_routes.py
git commit -m "feat: VR 미리듣기와 스택 추가 API 추가"
```

## Task 4: Voice-Only Equal-Power Crossfade in Player

**Files:**
- Modify: `src/secret_pond/audio/player.py`
- Modify: `tests/audio/test_layered_loop_player.py`
- Modify: `tests/audio/test_player_mixer.py`

- [ ] **Step 1: Add failing player tests**

Add tests:

```python
def test_player_crossfades_only_voice_layer_without_resetting_cursor(tmp_path: Path) -> None:
    paths = write_layers(tmp_path / "first", low=0.1, mid=0.2, voice=0.0, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(2)

    next_voice = stereo(0.4, frames=8)
    player.crossfade_voice_layer(next_voice, duration_frames=4, transition_target_id="vs-2")
    block = player.next_block(4)

    assert player.frame_cursor == 6
    assert player.active_voice_transition_target_id == "vs-2"
    assert np.all(block.samples[:, 0] >= 0.3)


def test_player_latest_voice_crossfade_target_wins(tmp_path: Path) -> None:
    paths = write_layers(tmp_path / "first", low=0.0, mid=0.0, voice=0.0, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()

    player.crossfade_voice_layer(stereo(0.2, frames=8), duration_frames=8, transition_target_id="old")
    player.next_block(2)
    player.crossfade_voice_layer(stereo(0.6, frames=8), duration_frames=4, transition_target_id="new")
    block = player.next_block(4)

    assert player.active_voice_transition_target_id == "new"
    assert float(block.samples[-1, 0]) > 0.45
```

- [ ] **Step 2: Run failing player tests**

Run:

```bash
uv run pytest tests/audio/test_layered_loop_player.py::test_player_crossfades_only_voice_layer_without_resetting_cursor tests/audio/test_layered_loop_player.py::test_player_latest_voice_crossfade_target_wins -q
```

Expected: FAIL because `crossfade_voice_layer` does not exist.

- [ ] **Step 3: Add transition state model**

In `player.py`, add:

```python
@dataclass(frozen=True)
class VoiceTransitionState:
    from_samples: np.ndarray
    to_buffer: AudioBuffer
    duration_frames: int
    elapsed_frames: int
    transition_target_id: str
```

- [ ] **Step 4: Add player API**

Add methods:

```python
@property
def active_voice_transition_target_id(self) -> str | None:
    return None if self._voice_transition is None else self._voice_transition.transition_target_id


def crossfade_voice_layer(
    self,
    next_voice: AudioBuffer,
    *,
    duration_frames: int,
    transition_target_id: str,
) -> None:
    layers = self._require_loaded()
    if duration_frames <= 0:
        msg = "duration_frames must be greater than 0"
        raise ValueError(msg)
    candidate = next_voice.to_canonical(
        sample_rate=layers["voice"].sample_rate,
        channels=layers["voice"].channels,
    ).to_frame_count(layers["voice"].frames)
    current_voice = _read_wrapped(layers["voice"].samples, self._frame_cursor, layers["voice"].frames)
    self._voice_transition = VoiceTransitionState(
        from_samples=current_voice,
        to_buffer=candidate,
        duration_frames=duration_frames,
        elapsed_frames=0,
        transition_target_id=transition_target_id,
    )
```

- [ ] **Step 5: Apply equal-power voice transition during mixing**

In `next_block`, read low/mid normally and use a transition block for voice. Equal-power gains:

```python
progress = np.clip((np.arange(block_size) + elapsed) / duration_frames, 0.0, 1.0)
from_gain = np.cos(progress * np.pi / 2.0)
to_gain = np.sin(progress * np.pi / 2.0)
voice = old_voice * from_gain[:, None] + new_voice * to_gain[:, None]
```

When `elapsed_frames + block_size >= duration_frames`, install `to_buffer` as `self._layers["voice"]` and clear `_voice_transition`.

- [ ] **Step 6: Run player tests**

Run:

```bash
uv run pytest tests/audio/test_layered_loop_player.py tests/audio/test_player_mixer.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/secret_pond/audio/player.py tests/audio/test_layered_loop_player.py tests/audio/test_player_mixer.py
git commit -m "feat: 목소리 레이어 크로스페이드 전환 추가"
```

## Task 5: Playback Session Guard and Post-Recording Transition Policy

**Files:**
- Modify: `src/secret_pond/config.py`
- Modify: `src/secret_pond/services/runtime.py`
- Modify: `src/secret_pond/services/recording_workflow.py`
- Modify: `src/secret_pond/web/state.py`
- Modify: `tests/test_config.py`
- Create or modify: `tests/services/test_recording_workflow.py`
- Modify: `tests/web/test_routes.py`

- [ ] **Step 1: Add config tests**

Add to `tests/test_config.py`:

```python
def test_voice_stack_transition_seconds_defaults_to_three() -> None:
    assert AppSettings().voice_stack.transition_seconds == 3


def test_voice_stack_transition_seconds_are_validated() -> None:
    with pytest.raises(ValueError):
        VoiceStackSettings(transition_seconds=0)
    with pytest.raises(ValueError):
        VoiceStackSettings(transition_seconds=11)
```

- [ ] **Step 2: Add transition workflow tests**

Create `tests/services/test_recording_workflow.py` with fake runtime/player:

```python
def test_refresh_playback_uses_voice_crossfade_when_output_running_and_guard_matches(tmp_path):
    runtime = runtime_with_running_output_and_matching_session(tmp_path)
    outcome = accepted_live_ephemeral_outcome("data/sources/voice/stack/VS0610_213112.wav")

    refresh_playback_after_recording(runtime, outcome)

    assert runtime.player.crossfade_calls == 1
    assert runtime.player.reload_calls == 0


def test_refresh_playback_does_not_crossfade_when_operator_moved_away(tmp_path):
    runtime = runtime_with_running_output_and_moved_session(tmp_path)
    outcome = accepted_live_ephemeral_outcome("data/sources/voice/stack/VS0610_213112.wav")

    refresh_playback_after_recording(runtime, outcome)

    assert runtime.player.crossfade_calls == 0
    assert event_types(runtime.logger) == ["recording.voice_transition_skipped"]


def test_refresh_playback_keeps_old_voice_on_crossfade_failure(tmp_path):
    runtime = runtime_with_failing_crossfade(tmp_path)
    outcome = accepted_live_ephemeral_outcome("data/sources/voice/stack/VS0610_213112.wav")

    refresh_playback_after_recording(runtime, outcome)

    assert runtime.output.is_running is True
    assert event_types(runtime.logger) == ["recording.voice_transition_failed"]
```

- [ ] **Step 3: Run failing workflow/config tests**

Run:

```bash
uv run pytest tests/test_config.py tests/services/test_recording_workflow.py -q
```

Expected: FAIL until config field and workflow policy exist.

- [ ] **Step 4: Add `transition_seconds` setting**

In `VoiceStackSettings`:

```python
transition_seconds: int = Field(default=3, ge=1, le=10)
```

- [ ] **Step 5: Add playback session tracking**

In `SecretPondRuntime`, add:

```python
playback_session_id: str = field(default_factory=lambda: uuid4().hex)
transition_warning: str | None = None
```

When `start_playback` starts a fresh output session or `restart_playback` restarts, update `playback_session_id`.

- [ ] **Step 6: Capture initiating stack/session on accepted recording**

In `recording_workflow`, capture before/after values under the existing runtime lock:

```python
initiating_session_id = runtime.playback_session_id
initiating_stack_id = runtime.settings_state.active.sources.voice_stack_path
```

Use those values to guard the transition when render is ready.

- [ ] **Step 7: Replace running reload with guarded voice-only transition**

In `refresh_playback_after_recording`:

```python
if runtime.output.is_running and settings.voice_stack.mode == "live_ephemeral":
    if not _same_transition_session(runtime, outcome):
        _log_event_best_effort(runtime, "recording.voice_transition_skipped", {...})
        return
    voice = read_wav(runtime.paths.voice_playback)
    runtime.player.crossfade_voice_layer(
        voice,
        duration_frames=settings.audio.sample_rate * settings.voice_stack.transition_seconds,
        transition_target_id=settings.sources.voice_stack_path or runtime.paths.voice_stack_raw.as_posix(),
    )
    _log_event_best_effort(runtime, "recording.voice_transition_started", {...})
    return
```

If output is stopped, keep the existing `load_rendered_layers(...)` branch.

- [ ] **Step 8: Expose transition warning in state**

In `web/state.py`, include:

```python
"playback": {
    ...,
    "playback_session_id": runtime.playback_session_id,
    "transition_warning": runtime.transition_warning,
}
```

- [ ] **Step 9: Run workflow and route tests**

Run:

```bash
uv run pytest tests/test_config.py tests/services/test_recording_workflow.py tests/web/test_routes.py -q
```

Expected: PASS after updating old tests that expected `reload_and_restart` and old raw persistence behavior.

- [ ] **Step 10: Commit**

```bash
git add src/secret_pond/config.py src/secret_pond/services/runtime.py src/secret_pond/services/playback_control.py src/secret_pond/services/recording_workflow.py src/secret_pond/web/state.py tests/test_config.py tests/services/test_recording_workflow.py tests/web/test_routes.py
git commit -m "feat: 전시 모드 목소리 전환 정책 추가"
```

## Task 6: Dashboard UI/UX for Storage, Live Transition, and Stable Fallback

**Files:**
- Modify: `src/secret_pond/web/static/index.html`
- Modify: `src/secret_pond/web/static/app.js`
- Modify: `src/secret_pond/web/static/styles.css`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/static_app_harness.py` if new DOM nodes are required.

- [ ] **Step 1: Add static asset assertions**

In `tests/web/test_routes.py::test_static_ui_assets_are_served`, assert these strings exist:

```python
assert "Live transition" in script.text
assert "Stable fallback" in script.text
assert "transition_warning" in script.text
assert "Add to Stack" in script.text
assert "Preview VR" in script.text
```

- [ ] **Step 2: Add UI state derivation tests**

Add a static harness test:

```python
def test_static_ui_shows_live_transition_and_stable_fallback_state(tmp_path: Path) -> None:
    run_static_app_harness(
        tmp_path,
        exports="{ renderState, state }",
        body=\"\"\"
state.snapshot = {
  playback: { output_running: true, transition_warning: null },
  settings: { active: { voice_stack: { mode: "live_ephemeral", transition_seconds: 3 } }, draft: {} },
  armed: false,
  is_recording: false,
};
renderState();
assertTextIncludes(elements.outputControlSummary, "Live transition");
\"\"\",
    )
```

- [ ] **Step 3: Run failing UI tests**

Run:

```bash
uv run pytest tests/web/test_routes.py::test_static_ui_assets_are_served tests/web/test_routes.py::test_static_ui_shows_live_transition_and_stable_fallback_state -q
```

Expected: FAIL until UI text and DOM wiring exist.

- [ ] **Step 4: Add UI copy and status mapping**

In `app.js`, add:

```javascript
const voiceTransitionModeLabel = (snapshot) => {
  const active = snapshot?.settings?.active;
  if (active?.voice_stack?.mode !== "live_ephemeral") return "Stable fallback";
  return "Live transition";
};
```

Update `outputControlSummary` so live exhibition mode says:

```javascript
`${voiceTransitionModeLabel(snapshot)} · 새 녹음은 준비되면 목소리 레이어만 부드럽게 전환됩니다.`
```

If `snapshot.playback.transition_warning` exists, show it through the existing caution banner path.

- [ ] **Step 5: Add VR action controls in Source Library**

For `voice_raw` file rows, add buttons:

```javascript
button("Preview VR", () => previewVoiceRaw(file.path));
button("Add to Stack", () => addVoiceRawToStack(file.path));
```

Both handlers should use tracked request IDs and set `sourceMutationInFlight` or a new `voiceActionInFlight` so dropdowns do not close from stale refresh churn.

- [ ] **Step 6: Add transition seconds control**

Add a compact `Voice Transition` slider in the Voice Stack control group:

```javascript
{
  path: "transition_seconds",
  label: { ko: "전환 시간", en: "Transition" },
  min: 1,
  max: 10,
  step: 1,
  suffix: " s",
  kind: "space",
  description: "전시 모드에서 새 목소리 스택으로 넘어가는 겹침 시간입니다.",
}
```

Make clear in helper text that this applies to live exhibition transition, not full realtime EQ.

- [ ] **Step 7: Run UI tests**

Run:

```bash
uv run pytest tests/web/test_routes.py tests/web/test_static_app_harness.py -q
```

Expected: PASS.

- [ ] **Step 8: Manual browser verification**

Run server:

```bash
uv run secret-pond serve
```

Verify in browser:
- Source Library rows for Voice Raw show `Preview VR` and `Add to Stack`.
- Playback panel distinguishes `Live transition` from `Stable fallback`.
- Transition seconds control fits on mobile and desktop.
- Non-fatal transition warnings use caution styling, not fatal error wording.

- [ ] **Step 9: Commit**

```bash
git add src/secret_pond/web/static/index.html src/secret_pond/web/static/app.js src/secret_pond/web/static/styles.css tests/web/test_routes.py tests/web/static_app_harness.py
git commit -m "feat: 목소리 전환 UI 추가"
```

## Task 7: End-to-End Regression and Docs

**Files:**
- Modify: `docs/operator-guide.md`
- Modify: `docs/audio-setup-checklist.md`
- Modify: `tests/test_docs.py`

- [ ] **Step 1: Add doc tests**

Update `tests/test_docs.py` to require:

```python
required = [
    "Live transition",
    "Stable fallback",
    "VR",
    "VS",
    "Apply and Restart",
    "전시 모드",
    "테스트 모드",
]
for phrase in required:
    assert phrase in guide
```

- [ ] **Step 2: Update operator guide**

Document:
- `live_ephemeral`: 녹음 완료 -> VR 없음 -> 새 VS 생성 -> 출력 중이면 voice-only crossfade.
- `test_library`: 녹음 완료 -> canonical VR 저장 -> 사용자가 Preview VR / Add to Stack.
- `Stable fallback`: 전환 실패나 설정 반영은 `Apply and Restart`.
- `transition_seconds`: 1-10초, 기본 3초.

- [ ] **Step 3: Update checklist**

Add manual checks:
- live recording while output is running changes only Voice Stack.
- low/mid remain continuous.
- transition failure is caution and does not stop output.
- test mode VR preview does not overlap with main playback.

- [ ] **Step 4: Run doc tests**

```bash
uv run pytest tests/test_docs.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

```bash
uv run pytest -q
uv run ruff check .
git diff --check
```

Expected:
- pytest passes.
- ruff passes.
- diff check has no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add docs/operator-guide.md docs/audio-setup-checklist.md tests/test_docs.py
git commit -m "docs: 목소리 저장과 전환 운영 방식 정리"
```

## Execution Strategy

Recommended parallelization:
- Agent A: Task 1 naming and voice stack storage tests.
- Agent B: Task 4 player crossfade tests/API.
- Agent C: Task 6 UI/UX controls and static tests, after API names are agreed.
- Main orchestrator: Task 2/3/5 integration, because these touch controller/runtime/routes and need conflict control.

Close each subagent immediately after its task report is reviewed and merged into the main working tree. Do not keep completed agents open.

## Risk Controls

- Do not remove `reload_and_restart`; it remains Stable fallback.
- Do not implement realtime EQ, seek, progress bar, general VS queue, manual VS transition, or test-library live transition.
- Do not let transition failure stop output.
- Do not let stale recording completions override an operator-changed stack/session.
- Do not write VR files for `live_ephemeral`.
- Do not add treatment into stored VR; treatment applies during preview/Add/live processing.

## Self-Review

Spec coverage:
- VR/VS KST names: Task 1.
- Mode split and canonical VR semantics: Task 2.
- Add to Stack and preview API: Task 3.
- Live voice-only crossfade: Task 4.
- Session guard, latest-wins, failure fallback: Task 5.
- UI/UX transition and Stable fallback visibility: Task 6.
- Docs and full verification: Task 7.

Red-flag scan:
- No forbidden planning phrases remain.

Type consistency:
- `transition_seconds` is a `VoiceStackSettings` field.
- `playback_session_id` belongs to `SecretPondRuntime` and state payload.
- `transition_target_id` is passed to `LayeredLoopPlayer.crossfade_voice_layer`.
