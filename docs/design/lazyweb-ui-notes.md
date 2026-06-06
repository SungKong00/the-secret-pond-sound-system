# LazyWeb UI Notes

LazyWeb was used during project setup to inspect desktop dashboard and audio-control patterns.
A fresh Phase 10 pass checked desktop service-status dashboards for compact diagnostics patterns.

Useful patterns found:

- DAW-style dark mixer layouts work well for dense audio controls.
- Persistent status bars are important for operational dashboards.
- Mixer rows should expose layer enable, volume, and detailed controls without hiding system state.
- A primary or featured audio channel can be separated from supporting mixer rows if it keeps the same compact controls and stays in the dashboard grid.
- Diagnostic dashboards should make device/browser/system checks visible before operation.
- Source and service health reads best as dense rows with severity status, not a separate landing page.
- Recent event summaries should stay short and newest-first so operators can scan the latest state.
- Cyberpunk-style dark dashboards can support the artwork mood if status and safety controls remain clear.

MVP UI direction:

- First screen is the operator dashboard, not a landing page.
- Use a dark, dreamy cyberpunk layout: black/near-black base, cyan/magenta accent lines, restrained glow, and no decorative clutter that competes with controls.
- Place `Arm / Disarm`, recording status, participant count, device health, and last error in the persistent top bar.
- Keep source-file health, selected devices, and recent event logs in a System panel on the first dashboard view.
- Represent `Low` and `Mid` as supporting mixer rows.
- Represent `Voice Stack` as a featured stack panel with the same compact playback EQ/filter controls.
- Group transport, `Apply and Restart`, and dirty-state feedback in a compact Playback panel.
- Treat EQ sliders as staged controls until `Apply and Restart`.
- Keep critical controls legible under exhibition pressure; visual mood must never hide whether recording is armed, recording, rendering, or failed.

## 2026-06-04 Phase 10 verification

Fresh LazyWeb searches checked desktop operational dashboards for dense status rows and
desktop audio tools for DAW-style mixer layouts. The useful reference direction stayed the same:
compact service-health badges for scanability, dense diagnostic rows instead of large narrative
cards, and DAW-style mixer controls for layer EQ and volume.

Rendered dashboard verification used bundled Playwright against the local app. Before the final
status-strip fix, the long `Last system.startup_playback_unavailable` badge pushed
`Participants` onto a second header row at 1440px. The dashboard now constrains that badge with
`text-overflow: ellipsis`; the same 1440px check measured the status badges on one row and showed
the long event badge actually truncating. Overflow checks were clean at desktop and mobile:
`bodyWidth=1440 viewportWidth=1440` and `bodyWidth=390 viewportWidth=390`.

## 2026-06-06 Live playback verification notes

All other Live playback acceptance checks are covered by automated tests. Remaining manual checks:

- physical audio output device routing and audible speaker output
- microphone permission prompt behavior on a fresh workstation
- exhibition speaker gain and room-level balance
