from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav
from secret_pond.config import AppSettings, AudioFormatSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.voice_source_service import VoiceSourceService


def test_save_vr_source_stores_canonical_pre_treatment_source(tmp_path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = AppSettings(audio=AudioFormatSettings(sample_rate=8_000, channels=2))
    mono = AudioBuffer(samples=np.ones(400, dtype=np.float32) * 0.25, sample_rate=8_000)

    result = VoiceSourceService(paths).save_recording_source(mono, settings)

    assert result.relative_path.startswith("data/sources/voice/raw/VR")
    stored = read_wav(tmp_path / result.relative_path)
    assert stored.sample_rate == 8_000
    assert stored.channels == 2
    assert float(stored.samples.max()) == 0.25
