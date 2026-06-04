from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.recording_transaction import (
    RecordingControlError,
    run_recording_transaction,
)
from secret_pond.services.settings_store import SettingsState, SettingsStore


def test_recording_transaction_restores_files_settings_and_new_wavs(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    paths.voice_stack_raw.write_bytes(b"raw-before")
    paths.voice_manifest.write_text('{"entries": []}', encoding="utf-8")
    paths.voice_playback.write_bytes(b"playback-before")
    existing_raw = paths.voice_raw_sources_dir / "existing.wav"
    existing_raw.write_bytes(b"existing")

    settings_store = SettingsStore(paths)
    initial_settings = AppSettings()
    initial_state = settings_store.save(
        SettingsState(active=initial_settings, draft=initial_settings),
    )
    controller = SimpleNamespace(settings=initial_settings)
    runtime: Any = SimpleNamespace(
        paths=paths,
        settings_store=settings_store,
        settings_state=initial_state,
        controller=controller,
    )

    def failing_control() -> None:
        paths.voice_stack_raw.write_bytes(b"raw-after")
        paths.voice_manifest.write_text('{"entries": ["new"]}', encoding="utf-8")
        paths.voice_playback.write_bytes(b"playback-after")
        (paths.voice_raw_sources_dir / "new-raw.wav").write_bytes(b"new raw")
        (paths.voice_stack_sources_dir / "new-stack.wav").write_bytes(b"new stack")
        (paths.accepted_dir / "new-accepted.wav").write_bytes(b"accepted")

        next_settings = initial_settings.model_copy(
            update={
                "sources": initial_settings.sources.model_copy(
                    update={
                        "voice_raw_path": "data/sources/voice/raw/new-raw.wav",
                        "voice_stack_path": "data/sources/voice/stack/new-stack.wav",
                    },
                ),
            },
            deep=True,
        )
        controller.settings = next_settings
        runtime.settings_state = settings_store.save(
            SettingsState(active=next_settings, draft=next_settings),
        )
        raise RuntimeError("voice render failed")

    with pytest.raises(RecordingControlError, match="voice render failed"):
        run_recording_transaction(runtime, failing_control)

    assert paths.voice_stack_raw.read_bytes() == b"raw-before"
    assert paths.voice_manifest.read_text(encoding="utf-8") == '{"entries": []}'
    assert paths.voice_playback.read_bytes() == b"playback-before"
    assert existing_raw.exists()
    assert not (paths.voice_raw_sources_dir / "new-raw.wav").exists()
    assert not (paths.voice_stack_sources_dir / "new-stack.wav").exists()
    assert not (paths.accepted_dir / "new-accepted.wav").exists()
    assert controller.settings.sources.voice_raw_path is None
    assert controller.settings.sources.voice_stack_path is None
    assert settings_store.load().active.sources.voice_raw_path is None
    assert settings_store.load().active.sources.voice_stack_path is None
    assert runtime.settings_state.active.sources.voice_raw_path is None


def test_recording_transaction_returns_successful_control_result(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings_store = SettingsStore(paths)
    settings = AppSettings()
    state = settings_store.save(SettingsState(active=settings, draft=settings))
    runtime: Any = SimpleNamespace(
        paths=paths,
        settings_store=settings_store,
        settings_state=state,
        controller=SimpleNamespace(settings=settings),
    )

    assert run_recording_transaction(runtime, lambda: "ok") == "ok"
