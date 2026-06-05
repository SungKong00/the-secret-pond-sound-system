from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.source_library import delete_source_file, select_existing_source
from secret_pond.config import AppSettings, SourceSelectionSettings
from secret_pond.paths import ProjectPaths


def write_library_wav(path: Path) -> None:
    write_wav_atomic(
        path,
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.05, sample_rate=8_000),
    )


def settings_with_low_source(path: str) -> AppSettings:
    return AppSettings(sources=SourceSelectionSettings(low_path=path))


def test_delete_source_file_rejects_active_or_draft_selected_file(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    active_relative = "data/sources/low/active-low.wav"
    draft_relative = "data/sources/low/draft-low.wav"
    inactive_relative = "data/sources/low/inactive-low.wav"
    active_path = tmp_path / active_relative
    draft_path = tmp_path / draft_relative
    inactive_path = tmp_path / inactive_relative
    for source_path in (active_path, draft_path, inactive_path):
        write_library_wav(source_path)
    active_settings = settings_with_low_source(active_relative)
    draft_settings = settings_with_low_source(draft_relative)

    with pytest.raises(PermissionError, match="active source file"):
        delete_source_file(
            paths,
            "low",
            active_relative,
            active_settings=active_settings,
            draft_settings=draft_settings,
        )
    with pytest.raises(PermissionError, match="draft source file"):
        delete_source_file(
            paths,
            "low",
            draft_relative,
            active_settings=active_settings,
            draft_settings=draft_settings,
        )

    delete_source_file(
        paths,
        "low",
        inactive_relative,
        active_settings=active_settings,
        draft_settings=draft_settings,
    )

    assert active_path.exists()
    assert draft_path.exists()
    assert not inactive_path.exists()


def test_select_existing_source_requires_file_in_category_directory(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    source_relative = "data/sources/low/library-low.wav"
    write_library_wav(tmp_path / source_relative)
    settings = AppSettings()

    selected = select_existing_source(paths, settings, "low", source_relative)

    assert selected.sources.low_path == source_relative
    assert settings.sources.low_path is None
    with pytest.raises(FileNotFoundError, match="source file does not exist"):
        select_existing_source(paths, settings, "low", "data/sources/low/missing-low.wav")
