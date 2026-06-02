# LazyWeb UI Notes

LazyWeb was used during project setup to inspect desktop dashboard and audio-control patterns.

Useful patterns found:

- DAW-style dark mixer layouts work well for dense audio controls.
- Persistent status bars are important for operational dashboards.
- Mixer rows should expose layer enable, volume, and detailed controls without hiding system state.
- Diagnostic dashboards should make device/browser/system checks visible before operation.

MVP UI direction:

- First screen is the operator dashboard, not a landing page.
- Use a dark, utilitarian layout with restrained contrast.
- Place `Arm / Disarm`, recording status, participant count, device health, and last error in the persistent top bar.
- Represent `Low`, `Mid`, and `Voice Stack` as mixer rows.
- Treat EQ sliders as staged controls until `Apply and Restart`.
