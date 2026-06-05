from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_store import SettingsState
from secret_pond.services.source_library_mutations import (
    SourceLibraryMutationError,
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
