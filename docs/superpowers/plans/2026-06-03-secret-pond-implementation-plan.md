# Secret Pond Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Mac/Windows-compatible Python app for "The Secret Pond" that records while the spacebar is held, processes each voice recording, accumulates it into a voice loop, and plays three controllable loop layers from a local browser UI.

**Architecture:** Use a Python backend as the single source of truth for audio state, file rendering, recording, playback, and logs. Serve a local web UI from FastAPI; the browser captures armed spacebar press/release and sends control commands to Python. A single sounddevice output stream owns the playback clock and mixes the three loop stems; FastAPI only talks to audio services through controller methods and thread-safe commands, never by touching playback buffers directly. The MVP uses staged EQ changes with an "Apply and Restart" action; the code boundaries keep a later real-time EQ engine possible without rewriting recording, rendering, or UI state.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, sounddevice, soundfile, NumPy, SciPy signal, Spotify Pedalboard, Pydantic, pytest, plain HTML/CSS/JavaScript.

---

## 1. Scope Decisions

### Included in MVP

- Local web UI opened at `http://127.0.0.1:8000`.
- Browser spacebar hold-to-record:
  - recording is disabled until the operator clicks `Arm`.
  - `keydown Space` starts recording.
  - `keyup Space` stops recording.
  - repeated keydown events are ignored.
  - browser blur, tab visibility loss, WebSocket disconnect, or disarm stops an active recording.
  - minimum duration is 3 seconds.
  - maximum duration is 120 seconds.
- Three loop layers:
  - `low`: prepared low-frequency droning source.
  - `mid`: prepared middle-frequency/directional source.
  - `voice`: accumulated voice-stack source.
- Each layer has:
  - enabled/disabled state.
  - volume in dB.
  - three-band EQ.
  - high-pass and low-pass filter controls.
- Recording pre-processing has:
  - input gain.
  - peak or RMS normalization target.
  - high-pass filter.
  - low-pass filter.
  - voice tone/presence control.
  - reverb amount.
  - optional delay amount.
  - fade in/out.
- Voice accumulation supports two modes:
  - `test_library` mode stores processed individual voice clips under `data/processed/accepted/*.wav` so tests and rehearsal imports can rebuild a voice stack from a folder.
  - `live_ephemeral` mode does not persist individual single-voice WAV files after they are mixed into the stack.
- Voice stack artifacts:
  - `data/voice/voice_stack_manifest.json`: placement, gain, duration, processing preset, source mode, and render revision metadata.
  - `data/voice/voice_stack_raw.wav`: current accumulated voice stack, also usable as a starting point when an exhibition begins with a prebuilt stack.
  - `data/rendered/layers/voice_playback.wav`: voice layer after current playback EQ/filter settings.
- EQ slider changes are staged first. They do not change audio until the operator clicks `Apply and Restart`.
- Participant count and operation logs are persisted.
- Automated tests avoid requiring real microphones or speakers.

### Explicitly Deferred

- Hardware button, touch sensor, Arduino, ESP32, and serial integration.
- Max/MSP integration.
- Complex multi-output routing per speaker.
- Per-speaker EQ.
- Immediate real-time EQ on slider movement.
- Cloud deployment or remote access.
- User account management.

### Optional Later

- Real-time volume and mute updates.
- Real-time EQ.
- Loop-end auto-apply instead of restart.
- Short crossfade between old and newly rendered playback layers.
- Hardware input through keyboard emulation or USB serial.

---

## 2. Core Conventions

### Audio Format

- Canonical sample rate: `48000`.
- Canonical channels: `2` stereo.
- Internal processing dtype: `float32`, range normally between `-1.0` and `1.0`.
- File output format: WAV, PCM 24-bit when supported; PCM 16-bit is acceptable fallback.
- All source files are converted on load to the canonical sample rate and channel count.
- Mono sources are duplicated to stereo.
- Longer source files are trimmed to the configured loop duration.
- Shorter source files are tiled to the configured loop duration with a short crossfade at boundaries.

### Loop Duration

- Prepared low/mid loop duration remains configurable.
- Voice stack default loop duration: 60 seconds.
- Voice stack loop duration is configurable through settings, as long as the implementation stays simple.
- `low`, `mid`, and `voice` rendered playback layers must have the same exact frame count.
- The player uses one shared frame cursor for all layers so the three layers stay phase-aligned.
- A source voice WAV longer than the voice stack duration is split into duration-sized chunks.
- Each chunk is mixed as a separate stack addition.
- A final short chunk is looped/tiled to fill the configured voice stack duration before it is mixed.

### Non-Destructive Rendering

- Never apply playback EQ repeatedly to `voice_stack_raw.wav`.
- Treat `data/rendered/layers/*.wav` as playback caches.
- In `test_library` mode, the authoritative record is `data/processed/accepted/*.wav` plus `data/voice/voice_stack_manifest.json`.
- In `test_library` mode, `voice_stack_raw.wav` is a rebuildable cache derived from accepted clips and the manifest.
- In `live_ephemeral` mode, `voice_stack_raw.wav` is the authoritative accumulated stack and individual voice WAV files are removed after mixing.
- The app must be able to start from an existing `voice_stack_raw.wav`.
- Render playback EQ/filter settings from raw/source files into `data/rendered/layers/*.wav`.
- Write rendered files atomically:
  - render to `*.tmp.wav`.
  - close the file handle.
  - replace the destination with `Path.replace`.
- The player loads rendered files into memory and closes file handles before playback. This avoids Windows file-locking problems during re-render.

### Audio Engine Boundary

- Use one output engine for all three layers, not one player per layer.
- The audio callback owns the output clock and frame cursor.
- FastAPI request handlers must not read or write active playback buffers.
- FastAPI routes call `AppController` methods.
- `AppController` sends playback changes through explicit player methods or a thread-safe command queue.
- The sounddevice callback must do only predictable lightweight work:
  - read layer sample blocks from memory.
  - apply enabled flags and optional realtime trim only.
  - sum layers.
  - apply final peak guard.
  - write output block.

### Device and Platform Boundary

- Create explicit abstractions:
  - `AudioInput`
  - `AudioOutput`
  - `AudioDeviceRegistry`
  - `Recorder`
  - `Player`
- Tests use fake implementations by default.
- Runtime uses sounddevice implementations.
- Device selection is stored by stable settings where possible, but device names can differ across Mac/Windows; startup must validate the configured device still exists.
- Keep the MVP WAV-only. Do not require ffmpeg.

### Gain Safety

- Each recording is normalized before insertion into the voice stack.
- Default inserted voice target: quiet enough to blend, not dominate.
- Use a peak guard after mixing:
  - if peak exceeds `0.98`, scale down to `0.98`.
  - final playback render should target at least 3 dB of headroom.
- Use a limiter on final playback renders if Pedalboard is available.
- Log whenever automatic gain reduction is applied.

### Settings

- Store settings as JSON at `data/config/settings.json`.
- Use Pydantic models for validation.
- UI sliders edit a draft settings object.
- Backend stores two settings states:
  - `active_settings`: currently applied to playback.
  - `draft_settings`: values currently shown in UI.
- `Apply and Restart` validates `draft_settings`, renders layer playback files, swaps them into the player, and restarts playback from frame zero.

### Logging

- Use Python `logging` with both human-readable and structured JSON-line event logs.
- Log startup diagnostics:
  - OS.
  - Python version.
  - selected input/output device.
  - requested sample rate and channels.
  - actual stream sample rate and channels.
  - data directory.
- Log every recording lifecycle event:
  - start.
  - stop.
  - too short discard.
  - accepted.
  - processing failure.
  - render failure.
  - participant count increment.
- Audio callback errors must be captured and surfaced in UI state.

### Operator Safety

- Recording is `Disarmed` by default.
- `Arm` enables browser spacebar capture.
- `Disarm` stops an active recording and prevents new recordings.
- Dangerous actions are blocked while recording or rendering:
  - Apply and Restart.
  - clear voice stack.
  - reset participant count.
  - restore previous render.
- Show a pending-changes badge whenever draft settings differ from active settings.
- UI copy must say that MVP EQ sliders are staged and apply only after `Apply and Restart`.

### Review Gates

- Before each small implementation slice, dispatch a subagent to review the local plan for contradictions and unnecessary complexity.
- Do not implement the slice until blocking review findings are resolved.
- After each slice implementation, dispatch a subagent for spec compliance and code-quality review.
- Do not commit with unresolved blocking or important review findings.
- Run tests and lint before every commit.
- Use `type;한글 설명` commit messages, for example `feat;오프라인 오디오 효과 추가`.

### Error Handling

- Audio rendering errors must not corrupt current playback.
- If a render fails, keep using the previous rendered layers.
- If recording fails, do not increment participant count.
- If a recording is too short, delete or quarantine the temp file and do not increment participant count.
- UI must show the latest error message and keep controls usable.

---

## 3. Project Structure

Create this structure:

```text
The Secret Pond/
  pyproject.toml
  README.md
  src/
    secret_pond/
      __init__.py
      app.py
      cli.py
      config.py
      paths.py
      state.py
      audio/
        __init__.py
        buffers.py
        devices.py
        effects.py
        file_io.py
        layers.py
        player.py
        recorder.py
        renderer.py
        voice_stack.py
      services/
        __init__.py
        controller.py
        logging_service.py
        participants.py
      web/
        __init__.py
        routes.py
        websocket.py
        static/
          index.html
          styles.css
          app.js
  tests/
    conftest.py
    audio/
      test_buffers.py
      test_devices.py
      test_effects.py
      test_player_mixer.py
      test_recorder.py
      test_renderer.py
      test_voice_stack.py
    services/
      test_controller.py
      test_participants.py
    web/
      test_routes.py
  data/
    sources/
      .gitkeep
    processed/
      accepted/
        .gitkeep
    voice/
      .gitkeep
    rendered/
      layers/
        .gitkeep
    recordings_temp/
      .gitkeep
    logs/
      .gitkeep
    config/
      .gitkeep
```

Responsibilities:

- `config.py`: Pydantic settings models and default values.
- `cli.py`: `serve` and `doctor` command entrypoint using `argparse`.
- `paths.py`: all filesystem paths, created relative to project root.
- `state.py`: runtime status enum and current UI-visible state.
- `audio/buffers.py`: `AudioBuffer` dataclass and channel/sample-rate normalization.
- `audio/devices.py`: sounddevice device discovery plus fake registry for tests.
- `audio/effects.py`: gain, fade, filters, EQ, reverb/delay wrappers.
- `audio/file_io.py`: WAV read/write, atomic write helpers.
- `audio/layers.py`: layer identifiers and layer settings.
- `audio/player.py`: layered loop playback engine.
- `audio/recorder.py`: recorder interface, fake recorder, sounddevice recorder.
- `audio/renderer.py`: render prepared sources and voice stack into playback layers.
- `audio/voice_stack.py`: build/update `voice_stack_raw.wav` from test-library files or live ephemeral recordings.
- `services/controller.py`: orchestration for record, stop, process, render, apply, playback.
- `services/logging_service.py`: rotating text logs and structured event logs.
- `services/participants.py`: participant count persistence.
- `web/routes.py`: HTTP API endpoints.
- `web/websocket.py`: status push to UI.
- `web/static/*`: operator dashboard.

---

## 4. Architecture Flow

### Startup

```text
secret-pond serve
→ create data directories
→ load settings JSON or defaults
→ run startup diagnostics
→ validate source files
→ render missing playback files
→ start FastAPI server
→ operator opens browser UI
```

### Recording

```text
operator clicks Arm
→ POST /api/input/arm
→ UI state becomes armed

browser Space keydown
→ POST /api/recording/start
→ Controller starts Recorder
→ UI state becomes recording

browser Space keyup or max-duration timeout
→ POST /api/recording/stop
→ Controller stops Recorder
→ if duration < 3 seconds, discard
→ process recording with recording pre-mix settings
→ split processed voice into voice-stack-duration chunks
→ in test_library mode, save processed chunks to the accepted folder
→ in live_ephemeral mode, keep processed chunks in memory/temp only
→ mix chunks into voice_stack_raw.wav
→ update voice_stack_manifest.json with source mode and placement metadata
→ render voice_playback.wav from raw stack and active voice layer settings
→ increment participant count
→ restart or continue playback according to operator setting
```

### Apply and Restart

```text
operator moves sliders
→ frontend updates draft settings
→ UI shows dirty state
→ operator clicks Apply and Restart
→ POST /api/settings/apply
→ backend validates draft settings
→ render low_playback.wav, mid_playback.wav, voice_playback.wav
→ player reloads layer buffers
→ playback restarts at frame zero
→ active settings become draft settings
```

### Playback

```text
LayeredLoopPlayer
→ loads low/mid/voice rendered WAV files into memory
→ sounddevice OutputStream requests blocks
→ player reads same frame range from each enabled layer
→ player sums layers with `LayerSettings.volume_db` already baked into rendered files
→ player applies final safety limiter/clip guard if needed
→ output block is sent to the selected audio device
```

FastAPI never performs this mixing itself. It only triggers controller actions that update player state safely outside the callback.

---

## 5. Implementation Phases

### Phase 0: Repository and Development Baseline

**Purpose:** Make the project installable, testable, and runnable on Mac/Windows before audio features are added.

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/secret_pond/__init__.py`
- Create: `src/secret_pond/cli.py`
- Create: `tests/conftest.py`

- [ ] Define Python package metadata and dependencies in `pyproject.toml`.

Use direct dependencies:

```toml
[project]
name = "secret-pond"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.8",
  "numpy>=1.26",
  "scipy>=1.13",
  "sounddevice>=0.4.7",
  "soundfile>=0.12",
  "pedalboard>=0.9",
  "platformdirs>=4.2",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "ruff>=0.6",
]

[project.scripts]
secret-pond = "secret_pond.cli:main"

[build-system]
requires = ["setuptools>=70", "wheel"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] Document local setup in `README.md`.

Required commands:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
secret-pond doctor
secret-pond serve
```

Windows equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
secret-pond doctor
secret-pond serve
```

- [ ] Implement `secret-pond doctor`.

Doctor checks:

```text
1. import native audio dependencies.
2. show OS and Python version.
3. list sounddevice input/output devices.
4. validate data directory write access.
5. validate configured sample rate/channels if devices are available.
6. report missing source files without failing the command.
```

### Phase 1: Settings, Paths, and State Models

**Purpose:** Define stable contracts before audio code and UI code depend on them.

**Files:**
- Create: `src/secret_pond/config.py`
- Create: `src/secret_pond/paths.py`
- Create: `src/secret_pond/state.py`
- Test: `tests/test_config.py`

- [ ] Define Pydantic models for:
  - `EqSettings`
  - `LayerSettings`
  - `RecordingProcessingSettings`
  - `VoiceStackSettings`
  - `PlaybackSettings`
  - `InputControlSettings`
  - `DeviceSettings`
  - `AppSettings`

Recommended control ranges:

```text
volume_db: -60.0 to +6.0
eq_low_gain_db: -18.0 to +12.0
eq_mid_gain_db: -18.0 to +12.0
eq_high_gain_db: -18.0 to +12.0
highpass_hz: 20.0 to 1000.0
lowpass_hz: 1000.0 to 20000.0
reverb_mix: 0.0 to 1.0
delay_mix: 0.0 to 1.0
fade_ms: 0 to 5000
loop_seconds: 30 to 600
```

- [ ] Define status values:

```text
idle
armed
recording
processing
rendering
playing
stopped
error
```

- [ ] Test defaults and validation:
  - invalid EQ gain is rejected.
  - low-pass must be greater than high-pass.
  - default settings include exactly three layers: `low`, `mid`, `voice`.
  - recording input is disarmed by default.

### Phase 1B: Audio Device Abstractions

**Purpose:** Keep Mac/Windows device differences out of core logic and make tests hardware-free.

**Files:**
- Create: `src/secret_pond/audio/devices.py`
- Test: `tests/audio/test_devices.py`

- [ ] Define `AudioDeviceInfo` with:
  - `id: str`
  - `name: str`
  - `kind: "input" | "output"`
  - `max_input_channels: int`
  - `max_output_channels: int`
  - `default_sample_rate: int | None`
- [ ] Define `AudioDeviceRegistry` protocol:
  - `list_input_devices() -> list[AudioDeviceInfo]`
  - `list_output_devices() -> list[AudioDeviceInfo]`
  - `validate_input(id: str | None) -> AudioDeviceInfo | None`
  - `validate_output(id: str | None) -> AudioDeviceInfo | None`
- [ ] Implement `SoundDeviceRegistry`.
- [ ] Implement `FakeDeviceRegistry`.
- [ ] Tests cover empty devices, selected device missing, and available fake devices.

### Phase 2: Audio Buffer and File IO

**Purpose:** Make audio data predictable across Mac/Windows and across different source files.

**Files:**
- Create: `src/secret_pond/audio/buffers.py`
- Create: `src/secret_pond/audio/file_io.py`
- Test: `tests/audio/test_buffers.py`

- [ ] Implement `AudioBuffer` with fields:
  - `samples: np.ndarray`
  - `sample_rate: int`
  - `channels: int`

- [ ] Implement conversion helpers:
  - mono to stereo.
  - int PCM to float32.
  - float clipping guard.
  - trim/tile to exact frame count.

- [ ] Implement `read_wav(path) -> AudioBuffer`.
- [ ] Implement `write_wav_atomic(path, buffer)`.
- [ ] Test with generated sine waves, not external files.

### Phase 3: Offline Audio Effects

**Purpose:** Build all non-real-time EQ, filters, gain, fade, and ambience processing in a testable layer.

**Files:**
- Create: `src/secret_pond/audio/effects.py`
- Test: `tests/audio/test_effects.py`

- [ ] Implement `apply_gain_db`.
- [ ] Implement `apply_fade`.
- [ ] Implement high-pass and low-pass filters using `scipy.signal.butter(..., output="sos")` and `scipy.signal.sosfilt`.
- [ ] Implement three-band EQ using stable biquad or SOS filters.
- [ ] Implement `apply_recording_processing`:
  - gain.
  - normalization.
  - filters.
  - EQ/tone.
  - fade.
  - reverb/delay through Pedalboard when enabled.
- [ ] Keep reverb/delay out of the playback callback for MVP.
- [ ] Tests should verify measurable changes:
  - gain changes peak amplitude.
  - high-pass reduces a low-frequency sine.
  - low-pass reduces a high-frequency sine.
  - fade starts and ends near zero.

### Phase 4: Voice Stack Accumulation

**Purpose:** Build and update the accumulated voice source while separating rehearsal/test persistence from live ephemeral operation.

**Files:**
- Create: `src/secret_pond/audio/voice_stack.py`
- Test: `tests/audio/test_voice_stack.py`

- [ ] Initialize an empty silent `voice_stack_raw.wav` when it does not exist.
- [ ] Load an existing `voice_stack_raw.wav` when present and normalize it to the configured voice stack duration.
- [ ] Add `VoiceStackMode` values:
  - `test_library`
  - `live_ephemeral`
- [ ] In `test_library` mode, save processed voice chunks under `data/processed/accepted`.
- [ ] In `live_ephemeral` mode, do not persist individual single-voice WAV files after they are mixed.
- [ ] Append one manifest entry to `data/voice/voice_stack_manifest.json` per stack addition.
- [ ] Manifest entry fields:
  - `id`
  - `source_mode`
  - `accepted_clip_path` when mode is `test_library`
  - `duration_seconds`
  - `offset_frames`
  - `gain_db`
  - `processing_settings_snapshot`
  - `created_at`
  - `source_sample_rate`
  - `source_channels`
- [ ] Split source WAVs longer than the configured voice stack duration into duration-sized chunks.
- [ ] Tile a final short chunk to the configured voice stack duration before mixing.
- [ ] Wrap chunk audio around the end of the loop if needed.
- [ ] Apply peak guard after rebuilding the stack.
- [ ] Return metadata:
  - recording duration.
  - insertion offset seconds.
  - peak before guard.
  - peak after guard.
  - gain reduction applied.
- [ ] Tests should verify:
  - `test_library` mode persists accepted chunks.
  - `live_ephemeral` mode leaves no individual accepted WAV file.
  - existing `voice_stack_raw.wav` can be used as the starting stack.
  - long WAVs split into multiple stack additions.
  - final short chunks tile to the configured stack duration.
  - inserted samples appear at expected offset.
  - wraparound works.
  - too-loud inserts are guarded.

### Phase 5: Layer Rendering

**Purpose:** Render the three playback layers from source/raw files and current settings.

**Files:**
- Create: `src/secret_pond/audio/layers.py`
- Create: `src/secret_pond/audio/renderer.py`
- Test: `tests/audio/test_renderer.py`

- [ ] Define layer IDs as string literals: `low`, `mid`, `voice`.
- [ ] Render `low` from `data/sources/low.wav`.
- [ ] Render `mid` from `data/sources/mid.wav`.
- [ ] Render `voice` from `data/voice/voice_stack_raw.wav`.
- [ ] Apply each layer's playback EQ/filter/volume to its rendered file.
  - Phase 5 treats `LayerSettings.volume_db` as baked base gain in the rendered playback cache.
  - Phase 6 must not apply the same `LayerSettings.volume_db` a second time; any later real-time trim must use a separate control defaulting to 0 dB.
- [ ] Render all layers to exact same frame count.
- [ ] Validate every rendered layer before replacing old files:
  - canonical sample rate.
  - stereo channel count.
  - exact loop frame count.
  - peak below configured ceiling.
- [ ] Write files atomically to:
  - `data/rendered/layers/low_playback.wav`
  - `data/rendered/layers/mid_playback.wav`
  - `data/rendered/layers/voice_playback.wav`
- [ ] Tests should verify that changing voice playback EQ does not modify `voice_stack_raw.wav`.
- [ ] Tests should verify failed render validation leaves previous rendered files in place.

### Phase 6: Layered Playback Engine

**Purpose:** Play the three rendered layers together while keeping the future real-time path open.

**Files:**
- Create: `src/secret_pond/audio/player.py`
- Test: `tests/audio/test_player_mixer.py`

- [ ] Implement a pure mixer function first:
  - input: rendered layer buffers, enabled flags, optional realtime trim values, frame cursor, block size.
  - output: mixed stereo block.
- [ ] Test pure mixer behavior without sounddevice:
  - disabled layers are silent.
  - three layers sum correctly.
  - cursor wraps at loop end.
  - output is guarded against clipping.
- [ ] Implement `LayeredLoopPlayer` using `sounddevice.OutputStream`.
- [ ] Implement a player command queue or locked control methods for:
  - start.
  - stop.
  - reload and restart.
  - set enabled flags.
  - set optional realtime trim. This must not reuse `LayerSettings.volume_db`, because that value is already baked during rendering.
  - report callback errors.
- [ ] Keep the sounddevice callback small:
  - no file IO.
  - no rendering.
  - no JSON parsing.
  - no heavy Pedalboard processing.
- [ ] Implement `reload_and_restart(rendered_layer_paths)`.
- [ ] Implement `stop()`.
- [ ] Implement selected output-device support after the pure mixer is stable.
- [ ] Tests should use the pure mixer and fake player; sounddevice stream tests are manual.

### Phase 7: Recording Engine

**Purpose:** Record only while requested, and test the workflow without a physical microphone.

**Files:**
- Create: `src/secret_pond/audio/recorder.py`
- Test: `tests/audio/test_recorder.py`

- [ ] Define a recorder protocol with:
  - `start()`
  - `stop() -> AudioBuffer`
  - `is_recording`
- [ ] Implement `FakeRecorder` for tests.
- [ ] Implement `SoundDeviceRecorder` for real use.
- [ ] Enforce minimum and maximum durations in the controller, not inside the low-level recorder.
- [ ] Implement max-duration auto-stop in the controller using a monotonic clock.
- [ ] Save accepted temp recordings to `data/recordings_temp`.
- [ ] Delete or quarantine rejected too-short recordings.
- [ ] Stop recording on explicit stop, disarm, browser disconnect, or timeout.

### Phase 8: Application Controller

**Purpose:** Centralize workflow rules so UI routes stay thin.

**Files:**
- Create: `src/secret_pond/services/controller.py`
- Create: `src/secret_pond/services/participants.py`
- Create: `src/secret_pond/services/logging_service.py`
- Test: `tests/services/test_controller.py`
- Test: `tests/services/test_participants.py`

- [ ] Implement `start_recording`.
- [ ] Implement `arm_input`.
- [ ] Implement `disarm_input`.
- [ ] Implement `stop_recording`.
- [ ] Implement too-short recording discard.
- [ ] Implement accepted recording processing:
  - process recording.
  - split the processed recording into configured voice-stack chunks.
  - pass chunks to `voice_stack.py` with the active stack mode.
  - persist individual chunks only in `test_library` mode.
  - keep no individual single-voice WAV after mixing in `live_ephemeral` mode.
  - append manifest entries with source mode and placement metadata.
  - update `voice_stack_raw.wav`.
  - render voice playback layer.
  - increment participant count.
  - log event.
- [ ] Implement `apply_settings_and_restart`.
- [ ] Implement `start_playback` and `stop_playback`.
- [ ] Ensure controller methods serialize render/mutation work with one render lock.
- [ ] Reject apply/restart while recording.
- [ ] Reject clear/reset/restore maintenance actions while recording or rendering.
- [ ] Tests should use `FakeRecorder`, fake renderer, and fake player.

### Phase 9: HTTP API and WebSocket State

**Purpose:** Expose a small stable API to the browser UI.

**Files:**
- Create: `src/secret_pond/app.py`
- Create: `src/secret_pond/web/routes.py`
- Create: `src/secret_pond/web/websocket.py`
- Test: `tests/web/test_routes.py`

HTTP endpoints:

```text
GET  /api/state
GET  /api/settings
PUT  /api/settings/draft
POST /api/settings/apply
POST /api/settings/reset-draft
POST /api/input/arm
POST /api/input/disarm
POST /api/playback/start
POST /api/playback/stop
POST /api/playback/restart
POST /api/recording/start
POST /api/recording/stop
GET  /api/devices
GET  /api/diagnostics
```

WebSocket:

```text
GET /ws/state
```

- [ ] API tests should verify route status codes and JSON shapes.
- [ ] API tests must not require real audio devices.
- [ ] Device listing can return an empty list in tests.
- [ ] Route handlers must delegate to `AppController`; route tests should use fake controller/audio services.

### Phase 10: Operator Web UI

**Purpose:** Give a non-technical operator a clear, safe dashboard.

**Files:**
- Create: `src/secret_pond/web/static/index.html`
- Create: `src/secret_pond/web/static/styles.css`
- Create: `src/secret_pond/web/static/app.js`

UI layout:

```text
Header:
  status, arm/disarm, participant count, current mode, last event/error, device health

Record panel:
  large hold-space recording area
  Ready / Hold Space to Record / Recording timer / Too Short / Processing / Added / Failed states
  min/max duration
  recording timer

Playback panel:
  play, stop, restart
  Apply and Restart
  dirty settings indicator

Layer panels:
  Low Layer
  Mid Layer
  Voice Stack Layer

Recording Processing panel:
  pre-mix voice controls

Voice Stack panel:
  stack playback EQ/filter controls

System panel:
  source file health
  selected input/output device
  log summary
```

Control conventions:

- The first screen is the Operator Dashboard, not a landing page.
- Recording is disarmed by default.
- Spacebar events are ignored while disarmed.
- `Arm` is visually prominent and must show that spacebar capture is active.
- `Disarm` stops an active recording.
- Sliders update draft settings only.
- Layer rows must distinguish active values from pending draft values.
- Show "Unsaved audio changes" when draft settings differ from active settings.
- `Apply and Restart` is the only MVP path that changes playback EQ.
- Disable `Apply and Restart` while recording or processing.
- Ignore spacebar events when focus is inside a text input.
- Ignore repeated `keydown` events from key repeat.
- Stop an active recording on browser blur, tab hidden, or WebSocket disconnect.
- Show a red recording state only during actual backend recording, not merely key press.
- Hide destructive maintenance actions behind a maintenance panel.
- Use preset names for non-technical tuning where possible:
  - Soft.
  - Misty.
  - Dense.
  - Clearer Voice.

### Phase 11: Documentation and Manual Verification

**Purpose:** Make the app runnable by a non-technical operator on both OSes.

**Files:**
- Modify: `README.md`
- Create: `docs/operator-guide.md`
- Create: `docs/audio-setup-checklist.md`

Docs must include:

- Mac install steps.
- Windows install steps.
- `secret-pond doctor` usage.
- How to grant microphone permission on macOS.
- How to choose input/output devices.
- How to recover when selected audio devices disappear or are renamed.
- Where to put prepared files:
  - `data/sources/low.wav`
  - `data/sources/mid.wav`
- How to start the app.
- How to open the UI.
- How to Arm and Disarm recording.
- How to use spacebar recording.
- What happens on browser blur, tab close, or UI disconnect.
- How to apply EQ settings.
- Difference between active settings and pending settings.
- How to recover from errors.
- What files can be deleted between rehearsals.
- What files should be backed up in `test_library` mode:
  - `data/processed/accepted`
  - `data/voice/voice_stack_manifest.json`
- What files should be backed up in `live_ephemeral` mode:
  - `data/voice/voice_stack_raw.wav`
  - `data/config/settings.json`
  - `data/logs`

Manual verification checklist:

```text
1. secret-pond doctor lists devices and write access.
2. App starts without source files and shows a clear missing-source warning.
3. App starts with valid low/mid files.
4. Playback starts.
5. Low layer can be disabled after Apply and Restart.
6. Mid layer can be disabled after Apply and Restart.
7. Voice layer can be disabled after Apply and Restart.
8. Spacebar does nothing while Disarmed.
9. Arm enables spacebar capture.
10. Spacebar starts and stops recording while Armed.
11. Browser blur or tab hidden stops an active recording.
12. A recording shorter than 3 seconds is discarded.
13. A valid recording increments participant count.
14. A valid recording in test_library mode creates accepted chunks and manifest entries.
15. A valid recording in live_ephemeral mode leaves no individual accepted voice WAV.
16. test_library mode can rebuild voice_stack_raw.wav from accepted chunks and manifest.
17. live_ephemeral mode can start from an existing voice_stack_raw.wav.
18. A valid recording changes the voice stack playback layer.
19. EQ slider movement shows dirty state.
20. Apply and Restart renders new audio and restarts playback.
21. A failed render keeps the previous good playback layer.
22. Restarting the app preserves participant count and settings.
```

Cross-platform manual checks:

```text
macOS:
1. microphone permission prompt appears or docs explain how to grant it.
2. default CoreAudio input and output can be selected.
3. closing/reopening the browser does not leave recording stuck.

Windows:
1. PowerShell install commands work.
2. default WASAPI/MME devices are listed.
3. re-rendering replaces WAV files without file-locking errors.
4. browser spacebar does not scroll the page while armed.
```

---

## 6. Later Real-Time EQ Extension

Do not implement this before the MVP is stable.

### Real-Time Phase A: Real-Time Volume and Mute

- Keep rendered layer buffers in memory.
- Let UI send volume/mute changes over WebSocket or HTTP.
- Store new values in a thread-safe player settings object.
- In the audio callback, apply only lightweight gain changes.
- Use short gain ramps to avoid click sounds.
- Keep `Apply and Restart` available as the fallback mode.

### Real-Time Phase B: Real-Time EQ

- Keep EQ out of the callback until volume/mute is proven stable.
- Precompute filter coefficients outside the callback.
- Swap coefficients at block boundaries.
- Maintain filter state per layer and channel.
- Avoid Pedalboard reverb/delay in the callback unless profiling proves it is safe.
- Add a UI mode switch:

```text
EQ Apply Mode:
  - Stable: Apply and Restart
  - Experimental: Live EQ
```

### Real-Time Exit Criteria

Only keep live EQ if all are true:

- No audible clicks while moving sliders.
- No dropouts during 30 minutes of playback.
- Works on the target Mac.
- Works on the target Windows machine.
- Operator can switch back to stable mode.
- `Apply and Restart` still works after disabling Live EQ.

---

## 7. Subagent Review Integration

This plan incorporates three independent critiques:

- Audio architecture review:
  - one output stream, one clock, three mixed stems.
  - stem/cache model instead of destructive loop replacement.
  - accepted clip manifest so the voice stack can be rebuilt.
  - strict canonical audio format and headroom rules.
- Operator UX review:
  - dashboard first, no landing page.
  - recording disarmed by default.
  - staged EQ changes are visually explicit.
  - recovery actions keep the previous good loop playing.
- Cross-platform review:
  - source install first, packaged installer later.
  - audio device abstraction and fake test backends.
  - no ffmpeg dependency for MVP.
  - `doctor` diagnostics before show operation.

During implementation, run a fresh pre-review before each small slice and a fresh post-review before committing. Phase 10 must include a fresh LazyWeb MCP pass for the final dashboard, not only the notes captured during planning.

---

## 8. Commit Strategy

Use small commits. Commit messages use a semicolon after the type and Korean description:

```text
feat;프로젝트 기본 세팅
feat;설정과 경로 모델 추가
feat;오디오 장치 진단 추가
feat;오디오 버퍼와 파일 입출력 추가
feat;오프라인 오디오 효과 추가
feat;목소리 스택 모드 추가
feat;레이어 렌더러 추가
feat;레이어 재생 엔진 추가
feat;녹음 엔진 추가
feat;애플리케이션 컨트롤러 추가
feat;로컬 웹 API 추가
feat;운영자 대시보드 추가
docs;운영자 안내 문서와 설정 체크리스트 추가
```

---

## 9. Current Recommendation

Build the MVP with staged EQ and `Apply and Restart`. Keep Max/MSP out. Keep hardware input out. Design the audio modules so real-time volume and EQ can be added later, but do not make real-time EQ a dependency for the first usable version.
