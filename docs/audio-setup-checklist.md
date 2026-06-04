# Audio Setup Checklist

Use this checklist before rehearsal and before show operation.

## Preflight

- [ ] `secret-pond doctor` lists devices and data write access.
- [ ] `secret-pond doctor --json` produces parseable readiness JSON for logs.
- [ ] After prepared source files are in place, `secret-pond doctor --strict` exits successfully.
- [ ] App starts without source files and shows a clear missing-source warning.
- [ ] App starts with valid low/mid files at `data/sources/low.wav` and `data/sources/mid.wav`.
- [ ] Startup loads compatible rendered playback caches, or renders fresh caches when prepared sources are available.
- [ ] System panel shows source health, selected devices, and recent events.
- [ ] The browser opens at `http://127.0.0.1:8000`.

## Playback

- [ ] `Apply and Restart` renders new audio.
- [ ] Playback starts with `Start Output` after startup preload or `Apply and Restart`.
- [ ] `Restart Output` restarts the loaded playback without changing settings.
- [ ] `Stop Output` stops the output stream.
- [ ] A failed render keeps the previous good playback layer where possible.
- [ ] Low layer can be disabled after Apply and Restart.
- [ ] Mid layer can be disabled after Apply and Restart.
- [ ] Voice layer can be disabled after Apply and Restart.
- [ ] EQ slider movement shows dirty state with `Unsaved audio changes`.

## Recording

- [ ] Spacebar does nothing while Disarmed.
- [ ] Arm enables spacebar capture.
- [ ] Spacebar starts and stops recording while Armed.
- [ ] Holding Space does not scroll the page, reactivate a focused button, or send repeat start requests outside text inputs.
- [ ] Browser blur or hidden tab stops an active recording.
- [ ] Closing the UI connection does not leave recording stuck.
- [ ] A recording shorter than 3 seconds is discarded.
- [ ] A valid recording increments participant count.
- [ ] A valid recording updates `data/rendered/layers/voice_playback.wav`; use `Apply and Restart` if the running output needs to reload that rendered layer.

## Voice Stack Modes

- [ ] A valid recording in test_library mode creates accepted chunks and manifest entries.
- [ ] A valid recording in live_ephemeral mode leaves no individual accepted voice WAV.
- [ ] `secret-pond rebuild-test-library --root .` rebuilds voice_stack_raw.wav and voice_playback.wav from accepted chunks and manifest in test_library mode.
- [ ] live_ephemeral mode can start from an existing voice_stack_raw.wav.
- [ ] Restarting the app preserves participant count and settings.

## Device Recovery

- [ ] Unplugging or renaming an input/output device is visible in `secret-pond doctor` or the dashboard warnings.
- [ ] A new input/output draft can be selected.
- [ ] Restarting the app promotes startup device/audio-format drafts, rejects stale rendered caches, and then `secret-pond doctor` plus dashboard warnings are checked.
- [ ] Device, sample-rate, and channel changes are not expected to apply through Apply and Restart in the MVP.

## macOS

- [ ] Microphone permission is granted to the terminal app.
- [ ] CoreAudio input and output devices are listed.
- [ ] Default CoreAudio input and output can be selected.
- [ ] Closing and reopening the browser does not leave recording stuck.

## Windows

- [ ] Windows PowerShell install commands work.
- [ ] WASAPI/MME devices are listed.
- [ ] Re-rendering replaces WAV files without file-locking errors.
- [ ] Browser spacebar does not scroll the page while armed.
