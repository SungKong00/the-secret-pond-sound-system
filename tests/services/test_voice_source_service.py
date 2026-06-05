from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.config import AppSettings, AudioFormatSettings, RecordingProcessingSettings
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


def test_preview_layers_apply_current_recording_treatment_to_selected_vr(tmp_path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        recording=RecordingProcessingSettings(
            gain_db=0.0,
            normalize_peak=0.42,
            highpass_hz=20.0,
            lowpass_hz=3_000.0,
            presence_gain_db=0.0,
            reverb_mix=0.0,
            delay_mix=0.0,
            fade_ms=0,
        ),
    )
    raw_path = paths.voice_raw_sources_dir / "VR0610_213112.wav"
    t = np.arange(4_000, dtype=np.float32) / 8_000
    tone = np.sin(2 * np.pi * 500.0 * t).astype(np.float32) * 0.05
    source = AudioBuffer(samples=np.column_stack([tone, tone]), sample_rate=8_000)
    write_wav_atomic(raw_path, source)

    preview = VoiceSourceService(paths).preview_layers(
        "data/sources/voice/raw/VR0610_213112.wav",
        settings,
    )

    assert preview["voice"].frames == 8_000
    assert float(np.max(np.abs(preview["voice"].samples))) > 0.15
    assert float(np.max(np.abs(preview["low"].samples))) == 0.0
    assert float(np.max(np.abs(preview["mid"].samples))) == 0.0
