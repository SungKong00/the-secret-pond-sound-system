from __future__ import annotations

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.effects import apply_fade, apply_gain_db, apply_highpass, apply_lowpass


def sine_wave(frequency: float, sample_rate: int = 48_000, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return np.sin(2 * np.pi * frequency * t).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


def test_apply_gain_db_changes_amplitude_without_changing_shape() -> None:
    buffer = AudioBuffer(samples=np.array([0.1, -0.1], dtype=np.float32), sample_rate=48_000)

    gained = apply_gain_db(buffer, 6.0)

    assert gained.samples.shape == buffer.samples.shape
    assert gained.channels == 1
    np.testing.assert_allclose(gained.samples, buffer.samples * (10 ** (6.0 / 20.0)))


def test_apply_fade_softens_start_and_end() -> None:
    samples = np.ones(4_800, dtype=np.float32)
    buffer = AudioBuffer(samples=samples, sample_rate=48_000)

    faded = apply_fade(buffer, fade_in_ms=50, fade_out_ms=50)

    assert faded.samples.shape == samples.shape
    assert faded.samples[0] == pytest.approx(0.0)
    assert faded.samples[2_400] == pytest.approx(1.0)
    assert faded.samples[-1] < 0.01


def test_apply_fade_rejects_negative_durations() -> None:
    buffer = AudioBuffer(samples=np.ones(100, dtype=np.float32), sample_rate=48_000)

    with pytest.raises(ValueError, match="fade"):
        apply_fade(buffer, fade_in_ms=-1, fade_out_ms=0)

    with pytest.raises(ValueError, match="fade"):
        apply_fade(buffer, fade_in_ms=0, fade_out_ms=-1)


def test_highpass_reduces_low_frequency_more_than_high_frequency() -> None:
    low = sine_wave(60.0)
    high = sine_wave(4_000.0)
    samples = (low + high) * 0.25
    buffer = AudioBuffer(samples=samples, sample_rate=48_000)

    filtered_low = apply_highpass(AudioBuffer(samples=low * 0.25, sample_rate=48_000), 500.0)
    filtered_high = apply_highpass(AudioBuffer(samples=high * 0.25, sample_rate=48_000), 500.0)

    assert rms(filtered_low.samples[1_000:]) < rms((low * 0.25)[1_000:]) * 0.25
    assert rms(filtered_high.samples[1_000:]) > rms((high * 0.25)[1_000:]) * 0.70
    assert apply_highpass(buffer, 500.0).samples.shape == samples.shape


def test_lowpass_reduces_high_frequency_more_than_low_frequency() -> None:
    low = sine_wave(120.0)
    high = sine_wave(8_000.0)

    filtered_low = apply_lowpass(AudioBuffer(samples=low * 0.25, sample_rate=48_000), 1_000.0)
    filtered_high = apply_lowpass(AudioBuffer(samples=high * 0.25, sample_rate=48_000), 1_000.0)

    assert rms(filtered_low.samples[1_000:]) > rms((low * 0.25)[1_000:]) * 0.70
    assert rms(filtered_high.samples[1_000:]) < rms((high * 0.25)[1_000:]) * 0.25


def test_filters_reject_invalid_cutoff_values() -> None:
    buffer = AudioBuffer(samples=np.ones(100, dtype=np.float32), sample_rate=48_000)

    with pytest.raises(ValueError, match="cutoff"):
        apply_highpass(buffer, 0.0)

    with pytest.raises(ValueError, match="cutoff"):
        apply_lowpass(buffer, 24_000.0)


def test_filters_reject_nan_cutoff_values() -> None:
    buffer = AudioBuffer(samples=np.ones(100, dtype=np.float32), sample_rate=48_000)

    with pytest.raises(ValueError, match="cutoff"):
        apply_highpass(buffer, float("nan"))


def test_filters_preserve_stereo_shape_and_filter_over_time_axis() -> None:
    left = sine_wave(60.0) * 0.25
    right = sine_wave(4_000.0) * 0.25
    stereo = np.column_stack([left, right]).astype(np.float32)
    buffer = AudioBuffer(samples=stereo, sample_rate=48_000)

    filtered = apply_highpass(buffer, 500.0)

    assert filtered.samples.shape == stereo.shape
    assert rms(filtered.samples[1_000:, 0]) < rms(stereo[1_000:, 0]) * 0.25
    assert rms(filtered.samples[1_000:, 1]) > rms(stereo[1_000:, 1]) * 0.70
