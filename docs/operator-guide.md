# Operator Guide

This guide is for running The Secret Pond Sound System during rehearsal or exhibition.

## Install

For prototype handoff, use the clickable launcher first:

macOS:

```text
Start Secret Pond.command
```

Windows:

```text
Start Secret Pond.bat
```

The launcher creates `.venv` if needed, installs the project package, starts the local server, and opens `http://127.0.0.1:8000`. Keep the launcher window open while the app is running. Close the window or press `Ctrl+C` to stop the server.

Use Python 3.11-3.14. The project currently declares `>=3.11,<3.15`. The app is WAV-only for the MVP and does not require ffmpeg.

Manual setup for development or troubleshooting:

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
secret-pond doctor
secret-pond serve
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
secret-pond doctor
secret-pond serve
```

## macOS Microphone Permission

If recording fails on macOS, open System Settings > Privacy & Security > Microphone and allow the terminal app used to run `secret-pond serve`. Restart the app after changing the permission.

## Audio Files

Prepare these files before playback:

```text
data/sources/low/*.wav
data/sources/mid/*.wav
```

The Source Library panel also manages:

```text
data/sources/voice/raw/*.wav
data/sources/voice/stack/*.wav
```

For compatibility, the app still falls back to:

```text
data/sources/low.wav
data/sources/mid.wav
data/voice/voice_stack_raw.wav
```

The System panel also checks the currently selected files. If no Source Library file is selected,
it checks the legacy fallback paths.

```text
data/voice/voice_stack_raw.wav
```

If `voice_stack_raw.wav` exists, the app can start from that accumulated voice stack. If it does not exist, the app creates a silent stack.

## Start And Open

1. For prototype handoff, run `Start Secret Pond.command` on macOS or `Start Secret Pond.bat` on Windows. For manual startup, run `secret-pond doctor`.
2. Confirm write access and that input/output devices are listed.
3. Run `secret-pond serve` when using manual startup.
4. Open `http://127.0.0.1:8000`.
5. Check the System panel before operation.
6. Use Source Library to select the Low, Mid, and Voice Stack WAV files. Upload new WAV files
   there when needed. Delete only inactive files that are not referenced by Settings Presets;
   active and preset-referenced sources are protected.

For machine-readable preflight logs, run:

```bash
secret-pond doctor --json
```

After low and mid files are selected in Source Library, or the legacy `data/sources/low.wav` and `data/sources/mid.wav` files are prepared, `secret-pond doctor --strict` can be used as a show-readiness gate. It exits with failure when data write access, native dependencies, selected device availability, source files, or basic device compatibility checks fail.

The doctor report does not prove microphone permission, actual stream startup, rendering, browser behavior, or Windows file replacement. Keep the manual checklist for those checks.

## Device Selection

Input and output devices are selected from the System panel dropdowns. Device names and IDs can differ across Mac and Windows, and can also change when an audio interface is unplugged, renamed, or reconnected.

Current MVP behavior:

- Input and output device changes apply as soon as you choose a dropdown option.
- If output is running and the output device changes, the app briefly stops the output stream and starts it again on the selected device.
- Input device changes are blocked while a recording is active.
- Sample-rate and channel changes still do not apply through `Apply and Restart`; restart the app after changing those startup audio-format settings.
- On startup, the app loads only rendered playback caches that match the active sample rate, channel count, and loop length. Stale or missing caches trigger an automatic render attempt. After restart, verify `secret-pond doctor` and dashboard warnings because device compatibility still depends on the host audio stack.
- If a device disappears or is renamed, choose an available device again and rerun `secret-pond doctor`.

## Operation

On startup, the app loads existing compatible playback caches. If caches are missing or stale and selected Source Library low/mid files are available, startup automatically renders and loads fresh playback layers. If no library selection exists, the app uses the legacy `data/sources/low.wav` plus `data/sources/mid.wav` paths. Use `재생` to begin playback after startup preparation succeeds. Use `Apply and Restart` after Stable staged settings changes or when the System panel reports startup playback is unavailable. Use `중지` to stop the stream. Use `다시 재생` to restart the current loaded playback from the beginning without applying new settings.

Turn on `녹음 준비` before recording. Spacebar recording only works while recording is ready.

- `녹음 준비`: enables Spacebar capture.
- `녹음 준비` is unavailable while already ready or recording.
- Turning `녹음 준비` off disables capture and stops an active recording.
- `Spacebar`: hold to record, release to stop.
- Holding Space suppresses key-repeat start requests. If focus is on a button, input, select, textarea, or summary, the focused control keeps its normal keyboard behavior.
- When `녹음 준비` is active and no terminal recording outcome is displayed, the record panel shows `스페이스바를 누르고 있는 동안 녹음`.
- Recording shorter than 3 seconds is discarded.
- Maximum recording duration is 120 seconds.
- The record panel shows elapsed time, remaining time, and min/max duration.
- A green/cyan ring means Spacebar capture is ready; magenta means active recording.

If browser blur happens, the tab becomes hidden, or the UI disconnects while recording, the app stops the active recording path. Browser blur and hidden-tab handling happen in the UI; WebSocket disconnect handling happens in the backend.

The header shows `실시간 동기화` when WebSocket state updates are active. If it shows `폴링 동기화`, the dashboard is using HTTP fallback; recording controls still work, but check the status strip after the connection recovers.

The header shows `오류 없음` during normal operation and `오류 있음` whenever the visible error banner has a current action, device, diagnostics, recording, or playback error.

## Settings

Sliders edit pending settings first. The Playback panel shows `Unsaved audio changes`. Layer rows also show current values and changed values. The Loop Mixer panel contains the Low and Mid supporting layers; the Voice Stack panel contains the voice playback layer EQ/filter controls.

Graph EQ는 Graph EQ workspace tab에서 Low, Mid, Voice layer별로 조절합니다. You can drag point handles, curve, or graph background to move the nearest editable point. 점을 움직이면 해당 layer의 `Bell / Peak`, `Low Shelf`, `High Shelf`, `Freq`, `Gain`, `Q`, `Filter Range` 설정이 pending settings로 저장됩니다.

- Stable mode에서는 Graph EQ 점 편집이 바로 들리지 않습니다. 변경한 곡선은 staged 상태로 남고, `Apply and Restart`를 눌렀을 때 rendered playback cache를 다시 만든 뒤 적용됩니다.
- Live mode에서는 Graph EQ 점 편집이 약 1초 debounce 뒤 server-owned executor에서 최신 변경만 렌더링됩니다. 일반적인 source file에서는 3초 안에 재생 중인 layer buffer가 빠르게 교체되는 것을 목표로 합니다. Live replacement is fast, not a musical crossfade.
- Live Graph EQ 적용에 실패하면 재생은 기존 audible state를 유지하고, dashboard warning에 실패 안내가 표시됩니다. 현재 들리는 EQ는 마지막 성공 상태이며, Stable `Apply and Restart`는 fallback으로 계속 사용할 수 있습니다.
- Voice가 `live_ephemeral`이고 selected timestamped stack source가 사라졌다면 Live Graph EQ는 `data/voice/voice_stack_raw.wav`를 EQ-free fallback source로 사용할 수 있습니다. 둘 다 없으면 missing source와 fallback 경로를 warning에 표시하고 기존 재생을 유지합니다.
- Live Graph EQ는 `low_playback.wav`, `mid_playback.wav`, `voice_playback.wav` 같은 이미 EQ가 baked 된 playback cache를 다시 EQ하지 않습니다. Low/Mid selected source, Voice Stack selected source 또는 `voice_stack_raw.wav` 같은 EQ-free source material에서만 새 buffer를 렌더링합니다.
- Source Library에서 Voice Stack 소스를 선택하면 Live 모드에서는 voice layer가 먼저 준비되고 준비가 끝나면 전환됩니다. Low/Mid 소스 선택은 계속 `Apply and Restart` 경로로 확정합니다.
- Voice Raw 파일은 행을 선택한 뒤 `미리듣기`로 현재 Voice Treatment가 적용된 소리를 확인하고, `스택에 추가`로 선택된 Voice Stack에 반영합니다. Voice Raw preview는 주 재생과 겹치지 않게 동작합니다.

The Voice Stack panel also includes `Voice loop` for the voice stack loop length. This is not a real-time control. Changing Voice loop is staged as a pending setting like the layer sliders.

`Apply and Restart` normalizes the selected voice stack source to the selected voice stack loop length by trimming or repeating existing raw stack audio as needed, then rebuilds `data/rendered/layers/voice_playback.wav`. Accepted recordings also save a timestamped processed voice raw snapshot under `data/sources/voice/raw/`. New voice stack outputs are saved as timestamped files under `data/sources/voice/stack/`, while `data/voice/voice_stack_raw.wav` remains as a legacy compatibility mirror. If this apply fails, the app attempts to keep or restore the previous playback and raw stack state.

Use `Apply and Restart` to render the current pending audio settings and reload playback. While it is working, the button shows `적용 중…` and Maintenance reset actions are locked. Apply and Restart is unavailable while recording and while recording stop processing finishes. In Stable mode this applies layer volume/EQ/filter settings and recording treatment settings that affect later recordings. Live mode applies volume, mute, seek, EQ, Filter Range, Voice Raw preview treatment, and Voice Stack source transition through immediate/live paths; use `Apply and Restart` as the Stable fallback or to confirm rendered cache state. It does not apply sample-rate or channel changes in the MVP; use the System panel dropdowns for device changes.

The Voice Treatment panel has four non-technical presets:

- Soft
- Misty
- Dense
- Clearer Voice

Preset buttons update the pending recording-treatment settings. They still require the normal save/apply flow for persisted settings and for changes that affect rendered playback.

Use `Maintenance` > `Cancel Changes` only when you want to discard unsaved settings changes. Stop recording before using Cancel Changes. Cancel Changes is also unavailable while Apply and Restart is running. Cancel Changes does not render audio, apply settings, or change the currently active playback settings.

Use `Maintenance` > `Reset Participants` only when intentionally zeroing the show participant counter. Stop recording before using Reset Participants. Reset Participants is also unavailable while Apply and Restart is running. Reset Participants does not delete logs, voice-stack files, rendered audio, or settings.

## Error Recovery

- If startup playback is unavailable, check the recent System event. If prepared files are missing, add or select low/mid WAV files in Source Library, or add `data/sources/low.wav` and `data/sources/mid.wav`, then use `Apply and Restart`.
- If a selected device is unavailable, choose a new device in the System panel and rerun `secret-pond doctor`.
- If `Apply and Restart` fails, the app tries to keep or restore the previous rendered playback state.
- If `다시 재생` fails, stop output, check the device, and restart the app if the device state is unclear.
- If the browser appears stale, refresh the page. Active backend state is preserved by the Python process.

## Files Between Rehearsals

Usually safe to delete when the app is stopped:

```text
data/rendered/layers/*.wav
data/recordings_temp/*
```

Delete generated voice-stack files only when intentionally resetting the installation.

Back up in `test_library` mode:

```text
data/processed/accepted
data/voice/voice_stack_manifest.json
data/sources/voice/stack
```

To rebuild the rehearsal stack from those accepted clips, stop the app and run:

```bash
secret-pond rebuild-test-library --root .
```

The command only runs when the active startup settings use `test_library` mode. It rewrites
`data/voice/voice_stack_raw.wav` from the manifest and renders
`data/rendered/layers/voice_playback.wav`.

Back up in `live_ephemeral` mode:

```text
data/voice/voice_stack_raw.wav
data/sources/voice/raw
data/sources/voice/stack
data/config/settings.json
data/logs
```

`test_library` keeps accepted individual clips so the stack can be rebuilt. `live_ephemeral` does not keep test-library accepted chunks, but accepted recordings now leave timestamped processed raw snapshots under `data/sources/voice/raw/`. The selected timestamped voice stack file under `data/sources/voice/stack/` is the important playback source artifact. The legacy `voice_stack_raw.wav` mirror is kept for compatibility.
