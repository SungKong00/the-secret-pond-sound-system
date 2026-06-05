from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.level_analysis import analyze_audio_levels, is_effectively_silent


def test_analyze_audio_levels_reports_digital_silence() -> None:
    buffer = AudioBuffer(samples=np.zeros((128, 2), dtype=np.float32), sample_rate=48_000)

    levels = analyze_audio_levels(buffer)

    assert levels.frames == 128
    assert levels.channels == 2
    assert levels.peak == 0.0
    assert levels.rms == 0.0
    assert levels.nonzero_ratio == 0.0
    assert levels.above_noise_floor_ratio == 0.0
    assert is_effectively_silent(levels) is True


def test_effective_silence_policy_keeps_low_but_real_input() -> None:
    samples = np.ones((128, 1), dtype=np.float32) * 0.0015
    buffer = AudioBuffer(samples=samples, sample_rate=48_000)

    levels = analyze_audio_levels(buffer)

    assert levels.peak > 0.0
    assert levels.rms > 0.0
    assert levels.nonzero_ratio == 1.0
    assert is_effectively_silent(levels) is False
