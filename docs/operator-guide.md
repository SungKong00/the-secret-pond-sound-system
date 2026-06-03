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
data/sources/low.wav
data/sources/mid.wav
```

The System panel also checks:

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

For machine-readable preflight logs, run:

```bash
secret-pond doctor --json
```

After `data/sources/low.wav` and `data/sources/mid.wav` are prepared, `secret-pond doctor --strict` can be used as a show-readiness gate. It exits with failure when data write access, native dependencies, selected device availability, source files, or basic device compatibility checks fail.

The doctor report does not prove microphone permission, actual stream startup, rendering, browser behavior, or Windows file replacement. Keep the manual checklist for those checks.

## Device Selection

Input and output devices can be selected in the dashboard as draft settings. Device names and IDs can differ across Mac and Windows, and can also change when an audio interface is unplugged, renamed, or reconnected.

Current MVP behavior:

- Device, sample-rate, and channel changes do not apply through `Apply and Restart`.
- Select the device draft, then restart the app.
- On startup, the app promotes startup device/audio-format drafts to active settings. After restart, verify `secret-pond doctor` and dashboard warnings because device compatibility still depends on the host audio stack.
- If a device disappears or is renamed, choose an available device again, restart the app, and rerun `secret-pond doctor`.

## Operation

On a fresh startup, press `Apply and Restart` once before `Start Output`; this renders and loads the playback layers. Use `Start Output` to begin playback after layers are loaded. Use `Stop Output` to stop the stream. Use `Restart Output` to restart the current loaded playback from the beginning without applying new settings.

Use `Arm` before recording. Spacebar recording only works while Armed.

- `Arm`: enables Spacebar capture.
- `Disarm`: disables capture and stops an active recording.
- `Spacebar`: hold to record, release to stop.
- Recording shorter than 3 seconds is discarded.
- Maximum recording duration is 120 seconds.
- The record panel shows elapsed time, remaining time, and min/max duration.
- A green/cyan ring means Spacebar capture is ready; magenta means active recording.

If browser blur happens, the tab becomes hidden, or the UI disconnects while recording, the app stops the active recording path. Browser blur and hidden-tab handling happen in the UI; WebSocket disconnect handling happens in the backend.

The header shows `Sync Live` when WebSocket state updates are active. If it shows `Sync Polling`, the dashboard is using HTTP fallback; recording controls still work, but check the status strip after the connection recovers.

The header shows `Error None` during normal operation and `Error Active` whenever the visible error banner has a current action, device, diagnostics, recording, or playback error.

## Settings

Sliders edit draft settings first. Draft changes are shown with `Unsaved audio changes`. Layer rows also show Active or Pending Draft values.

Use `Apply and Restart` to render the current draft audio settings and reload playback. While it is working, the button shows `Applying...` and Maintenance reset actions are locked. This applies layer volume/EQ/filter settings and recording treatment settings that affect later recordings. It does not apply device, sample-rate, or channel changes in the MVP.

The Voice Treatment panel has four non-technical presets:

- Soft
- Misty
- Dense
- Clearer Voice

Preset buttons update the recording-treatment draft. They still require the normal draft save/apply flow for persisted settings and for changes that affect rendered playback.

Use `Maintenance` > `Reset Draft` only when you want to discard unsaved draft settings. Stop recording before using Reset Draft. Reset Draft is also unavailable while Apply and Restart is running. Reset Draft does not render audio, apply settings, or change the currently active playback settings.

Use `Maintenance` > `Reset Participants` only when intentionally zeroing the show participant counter. Stop recording before using Reset Participants. Reset Participants is also unavailable while Apply and Restart is running. Reset Participants does not delete logs, voice-stack files, rendered audio, or settings.

## Error Recovery

- If prepared files are missing, add `data/sources/low.wav` and `data/sources/mid.wav`, then use `Apply and Restart`.
- If a selected device is unavailable, choose a new draft device, restart the app, and rerun `secret-pond doctor`.
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
```

Back up in `live_ephemeral` mode:

```text
data/voice/voice_stack_raw.wav
data/config/settings.json
data/logs
```

`test_library` keeps accepted individual clips so the stack can be rebuilt. `live_ephemeral` does not keep individual voice WAV files; the accumulated `voice_stack_raw.wav` is the important voice artifact.
