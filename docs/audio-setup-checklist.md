# Audio Setup Checklist

Use this checklist before rehearsal and before show operation.

## Preflight

- [ ] `secret-pond doctor` lists devices and data write access.
- [ ] `secret-pond doctor --json` produces parseable readiness JSON for logs.
- [ ] After prepared source files are in place, `secret-pond doctor --strict` exits successfully.
- [ ] App starts without source files and shows a clear missing-source warning.
- [ ] App starts with valid low/mid files selected in Source Library or with legacy files at `data/sources/low.wav` and `data/sources/mid.wav`.
- [ ] Source Library lists `data/sources/low/*.wav`, `data/sources/mid/*.wav`, `data/sources/voice/raw/*.wav`, and `data/sources/voice/stack/*.wav`.
- [ ] Source Library selection survives app restart through settings.
- [ ] Source Library upload writes a WAV into the matching directory.
- [ ] Source Library delete removes inactive files and blocks the currently active file.
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
- [ ] Changing `Voice loop` shows `Unsaved audio changes`, then `Apply and Restart` rebuilds voice_stack_raw.wav and voice_playback.wav to the selected length.
- [ ] Changing source selections shows `Unsaved audio changes`, then `Apply and Restart` renders from the selected files.

## Graph EQ

- [ ] Default flat Graph EQ points do not audibly color Low, Mid, or Voice when `Filter Range` is open.
- [ ] Low, Mid, and Voice Graph EQ layer tabs each update their own layer without changing the other layers.
- [ ] Graph EQ curve/background drag moves the nearest point and point handles remain easy to grab.
- [ ] Stable mode Graph EQ edits stay staged until `Apply and Restart`.
- [ ] Stable mode does not run the Live executor.
- [ ] Live mode Graph EQ edits apply after roughly 1 second debounce and are audible within the 3 second target on typical local source files.
- [ ] Live Graph EQ failure shows a dashboard warning and keeps the previously audible playback state.
- [ ] A stale selected Voice Stack path plus existing `voice_stack_raw.wav` does not fail Live mode.
- [ ] A missing selected and missing fallback source shows a specific warning and keeps playback running.
- [ ] Live Graph EQ renders from selected source material or `voice_stack_raw.wav`, not from already rendered `*_playback.wav` cache files.
- [ ] Local hardware timing is checked with the actual exhibition source files and output device.

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
- [ ] A valid recording creates timestamped voice raw and stack files under `data/sources/voice/raw/` and `data/sources/voice/stack/`.

## Voice Stack Modes

- [ ] A valid recording in test_library mode creates accepted chunks and manifest entries.
- [ ] A valid recording in live_ephemeral mode leaves no individual accepted voice WAV.
- [ ] `secret-pond rebuild-test-library --root .` rebuilds voice_stack_raw.wav and voice_playback.wav from accepted chunks and manifest in test_library mode.
- [ ] Rebuilt voice stack output is also available as a timestamped Source Library stack file.
- [ ] live_ephemeral mode can start from an existing voice_stack_raw.wav.
- [ ] Restarting the app preserves participant count and settings.

## Device Recovery

- [ ] Unplugging or renaming an input/output device is visible in `secret-pond doctor` or the dashboard warnings.
- [ ] A new input/output device can be selected from the System panel dropdowns.
- [ ] Changing the output device while output is running briefly restarts output on the selected device.
- [ ] Changing the input device while recording is blocked.
- [ ] Sample-rate and channel changes are not expected to apply through Apply and Restart in the MVP.

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
