from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_store import SettingsState, SettingsStore
from secret_pond.services.source_library_mutations import (
    SourceLibraryMutationError,
    delete_source_file_from_library,
    select_source_file_and_update_draft,
    upload_source_file_and_maybe_select,
)


class FailingPatchDraftStore:
    def __init__(self) -> None:
        settings = AppSettings()
        self.state = SettingsState(active=settings, draft=settings)

    def load(self) -> SettingsState:
        return self.state

    def patch_draft(self, patch):
        raise OSError("settings save failed")


def test_select_source_file_persists_draft_selection_and_updates_runtime_state(
    tmp_path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    source = AudioBuffer(
        samples=np.ones((8_000, 2), dtype=np.float32) * 0.05,
        sample_rate=8_000,
    )
    write_wav_atomic(paths.mid_sources_dir / "library-mid.wav", source)
    selected_path = "data/sources/mid/library-mid.wav"
    settings = AppSettings()
    store = SettingsStore(paths)
    initial_state = store.save(SettingsState(active=settings, draft=settings))
    runtime = SimpleNamespace(
        paths=paths,
        settings_store=store,
        settings_state=initial_state,
    )

    state = select_source_file_and_update_draft(
        runtime,
        "mid",
        selected_path,
    )

    assert state.draft.sources.mid_path == selected_path
    assert store.load().draft.sources.mid_path == selected_path
    assert runtime.settings_state is state


def test_delete_source_file_from_library_removes_inactive_file_without_settings_mutation(
    tmp_path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    source = AudioBuffer(
        samples=np.ones((8_000, 2), dtype=np.float32) * 0.05,
        sample_rate=8_000,
    )
    active_path = paths.low_sources_dir / "active-low.wav"
    inactive_path = paths.low_sources_dir / "inactive-low.wav"
    write_wav_atomic(active_path, source)
    write_wav_atomic(inactive_path, source)
    settings = AppSettings()
    store = SettingsStore(paths)
    settings_state = store.save(SettingsState(active=settings, draft=settings))
    runtime = SimpleNamespace(
        paths=paths,
        settings_store=store,
        settings_state=settings_state,
    )

    state = delete_source_file_from_library(
        runtime,
        "low",
        "data/sources/low/inactive-low.wav",
        settings_state=settings_state,
    )

    assert state is settings_state
    assert active_path.exists()
    assert not inactive_path.exists()
    assert store.load() == settings_state
    assert runtime.settings_state is settings_state


def test_upload_and_select_rolls_back_uploaded_file_when_draft_save_fails(
    tmp_path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    source = AudioBuffer(
        samples=np.ones((8_000, 2), dtype=np.float32) * 0.05,
        sample_rate=8_000,
    )
    source_path = tmp_path / "source.wav"
    write_wav_atomic(source_path, source)
    runtime = SimpleNamespace(
        paths=paths,
        settings_store=FailingPatchDraftStore(),
        settings_state=None,
    )

    with pytest.raises(SourceLibraryMutationError, match="settings save failed"):
        upload_source_file_and_maybe_select(
            runtime,
            "low",
            filename="uploaded-low.wav",
            content=source_path.read_bytes(),
            select_after_upload=True,
        )

    assert not (paths.low_sources_dir / "uploaded-low.wav").exists()
