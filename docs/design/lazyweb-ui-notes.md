# LazyWeb UI Notes

LazyWeb was used during project setup to inspect desktop dashboard and audio-control patterns.

Useful patterns found:

- DAW-style dark mixer layouts work well for dense audio controls.
- Persistent status bars are important for operational dashboards.
- Mixer rows should expose layer enable, volume, and detailed controls without hiding system state.
- Diagnostic dashboards should make device/browser/system checks visible before operation.
- Cyberpunk-style dark dashboards can support the artwork mood if status and safety controls remain clear.

MVP UI direction:

- First screen is the operator dashboard, not a landing page.
- Use a dark, dreamy cyberpunk layout: black/near-black base, cyan/magenta accent lines, restrained glow, and no decorative clutter that competes with controls.
- Place `Arm / Disarm`, recording status, participant count, device health, and last error in the persistent top bar.
- Represent `Low`, `Mid`, and `Voice Stack` as mixer rows.
- Treat EQ sliders as staged controls until `Apply and Restart`.
- Keep critical controls legible under exhibition pressure; visual mood must never hide whether recording is armed, recording, rendering, or failed.
