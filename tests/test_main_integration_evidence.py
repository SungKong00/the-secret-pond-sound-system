from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_COMMIT = "2828c54"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def assert_contains(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text


def test_main_contains_voice_source_stack_live_transition_implementation() -> None:
    assert git("branch", "--show-current") == "main"
    git("rev-parse", "--verify", f"{IMPLEMENTATION_COMMIT}^{{commit}}")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", IMPLEMENTATION_COMMIT, "HEAD"],
        cwd=ROOT,
        check=True,
    )

    expected_files = [
        "src/secret_pond/audio/voice_stack_naming.py",
        "src/secret_pond/services/voice_source_service.py",
        "src/secret_pond/services/voice_stack_service.py",
        "src/secret_pond/services/recording_workflow.py",
        "src/secret_pond/web/static/app.js",
        "tests/audio/test_layered_loop_player.py",
        "tests/services/test_recording_workflow.py",
    ]
    for relative_path in expected_files:
        assert (ROOT / relative_path).exists()

    assert_contains(
        "src/secret_pond/services/recording_workflow.py",
        "refresh_playback_after_recording",
        "start_voice_crossfade",
        "transition_warning",
    )
    assert_contains(
        "src/secret_pond/audio/player.py",
        "start_voice_crossfade",
        "active_voice_transition_target_id",
    )
    assert_contains("src/secret_pond/config.py", "transition_seconds", "live_ephemeral")
    assert_contains(
        "src/secret_pond/web/static/app.js",
        "voiceStackControlDefs",
        "transition_seconds",
        "transitionModeBadge",
        "Live transition",
    )
