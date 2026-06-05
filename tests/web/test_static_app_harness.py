from __future__ import annotations

from static_app_harness import STATIC_APP_NULL_DOM_SETUP, run_node_harness


def test_static_app_harness_runs_node_body() -> None:
    run_node_harness(
        script="globalThis.__secretPondTest = { answer: 41 + 1 };",
        body="assert.strictEqual(globalThis.__secretPondTest.answer, 42);",
        dom_setup=STATIC_APP_NULL_DOM_SETUP,
    )
