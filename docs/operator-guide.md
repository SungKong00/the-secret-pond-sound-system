# Operator Guide

This guide is for running The Secret Pond Sound System during rehearsal or exhibition.

## Install

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

Use Python 3.11 or 3.12. The project currently declares `>=3.11,<3.13`, so do not use Python 3.13 for show setup. The app is WAV-only for the MVP and does not require ffmpeg.

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

1. Run `secret-pond doctor`.
2. Confirm write access and that input/output devices are listed.
3. Run `secret-pond serve`.
4. Open `http://127.0.0.1:8000`.
5. Check the System panel before operation.
6. Use Source Library to select the Low, Mid, and Voice Stack WAV files. Upload new WAV files
   there when needed. Delete only inactive files; the active source is protected.

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

On startup, the app loads existing compatible playback caches. If caches are missing or stale and selected Source Library low/mid files are available, startup automatically renders and loads fresh playback layers. If no library selection exists, the app uses the legacy `data/sources/low.wav` plus `data/sources/mid.wav` paths. Use `Start Output` to begin playback after startup preparation succeeds. Use `Apply and Restart` after staged settings changes or when the System panel reports startup playback is unavailable. Use `Stop Output` to stop the stream. Use `Restart Output` to restart the current loaded playback from the beginning without applying new settings.

Use `Arm` before recording. Spacebar recording only works while Armed.

- `Arm`: enables Spacebar capture.
- Arm is unavailable while already armed or recording.
- `Disarm`: disables capture and stops an active recording.
- Disarm is unavailable when already disarmed.
- `Spacebar`: hold to record, release to stop.
- Holding Space suppresses key-repeat start requests and browser default Space actions outside text inputs.
- When Arm is active and no terminal recording outcome is displayed, the record panel shows `Hold Space to Record`.
- Recording shorter than 3 seconds is discarded.
- Maximum recording duration is 120 seconds.
- The record panel shows elapsed time, remaining time, and min/max duration.
- A green/cyan ring means Spacebar capture is ready; magenta means active recording.

If browser blur happens, the tab becomes hidden, or the UI disconnects while recording, the app stops the active recording path. Browser blur and hidden-tab handling happen in the UI; WebSocket disconnect handling happens in the backend.

The header shows `Sync Live` when WebSocket state updates are active. If it shows `Sync Polling`, the dashboard is using HTTP fallback; recording controls still work, but check the status strip after the connection recovers.

The header shows `Error None` during normal operation and `Error Active` whenever the visible error banner has a current action, device, diagnostics, recording, or playback error.

## Settings

Sliders edit pending settings first. The Playback panel shows `Unsaved audio changes`. Layer rows also show current values and changed values. The Loop Mixer panel contains the Low and Mid supporting layers; the Voice Stack panel contains the voice playback layer EQ/filter controls.

The Voice Stack panel also includes `Voice loop` for the voice stack loop length. This is not a real-time control. Changing Voice loop is staged as a pending setting like the layer sliders.

`Apply and Restart` normalizes the selected voice stack source to the selected voice stack loop length by trimming or repeating existing raw stack audio as needed, then rebuilds `data/rendered/layers/voice_playback.wav`. Accepted recordings also save a timestamped processed voice raw snapshot under `data/sources/voice/raw/`. New voice stack outputs are saved as timestamped files under `data/sources/voice/stack/`, while `data/voice/voice_stack_raw.wav` remains as a legacy compatibility mirror. If this apply fails, the app attempts to keep or restore the previous playback and raw stack state.

Use `Apply and Restart` to render the current pending audio settings and reload playback. While it is working, the button shows `Applying...` and Maintenance reset actions are locked. Apply and Restart is unavailable while recording and while recording stop processing finishes. This applies layer volume/EQ/filter settings and recording treatment settings that affect later recordings. It does not apply sample-rate or channel changes in the MVP; use the System panel dropdowns for device changes.

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
- If `Restart Output` fails, stop output, check the device, and restart the app if the device state is unclear.
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
