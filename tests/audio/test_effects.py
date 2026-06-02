from __future__ import annotations

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.effects import (
    apply_fade,
    apply_gain_db,
    apply_highpass,
    apply_lowpass,
    apply_presence_tone,
    apply_recording_processing,
    normalize_peak,
)
from secret_pond.config import RecordingProcessingSettings


def sine_wave(frequency: float, sample_rate: int = 48_000, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return np.sin(2 * np.pi * frequency * t).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


def harmonic_ratio(samples: np.ndarray, sample_rate: int, fundamental_hz: float) -> float:
    spectrum = np.abs(np.fft.rfft(samples))
    fundamental_bin = int(round(fundamental_hz * len(samples) / sample_rate))
    fundamental = spectrum[fundamental_bin]
    harmonic_power = 0.0
    for multiple in (3, 5, 7):
        harmonic_bin = fundamental_bin * multiple
        if harmonic_bin < len(spectrum):
            harmonic_power += float(spectrum[harmonic_bin] ** 2)
    return float(np.sqrt(harmonic_power) / fundamental)


def test_apply_gain_db_changes_amplitude_without_changing_shape() -> None:
    buffer = AudioBuffer(samples=np.array([0.1, -0.1], dtype=np.float32), sample_rate=48_000)

    gained = apply_gain_db(buffer, 6.0)

    assert gained.samples.shape == buffer.samples.shape
    assert gained.channels == 1
    np.testing.assert_allclose(gained.samples, buffer.samples * (10 ** (6.0 / 20.0)))


def test_normalize_peak_boosts_quiet_audio_up_to_gain_cap() -> None:
    buffer = AudioBuffer(samples=np.array([0.01, -0.01], dtype=np.float32), sample_rate=48_000)

    normalized = normalize_peak(buffer, target_peak=0.20, max_gain_db=6.0)

    assert float(np.max(np.abs(normalized.samples))) == pytest.approx(
        0.01 * (10 ** (6.0 / 20.0)),
        rel=1e-5,
    )


def test_normalize_peak_boosts_quiet_audio_to_target_when_cap_allows() -> None:
    buffer = AudioBuffer(samples=np.array([0.05, -0.05], dtype=np.float32), sample_rate=48_000)

    normalized = normalize_peak(buffer, target_peak=0.20, max_gain_db=20.0)

    assert float(np.max(np.abs(normalized.samples))) == pytest.approx(0.20, rel=1e-5)


def test_normalize_peak_leaves_silence_and_loud_audio_stable() -> None:
    silence = AudioBuffer(samples=np.zeros(16, dtype=np.float32), sample_rate=48_000)
    loud = AudioBuffer(samples=np.array([0.8, -0.8], dtype=np.float32), sample_rate=48_000)

    normalized_silence = normalize_peak(silence, target_peak=0.35)
    normalized_loud = normalize_peak(loud, target_peak=0.35)

    np.testing.assert_allclose(normalized_silence.samples, silence.samples)
    np.testing.assert_allclose(normalized_loud.samples, loud.samples)


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


def test_presence_tone_changes_high_band_more_than_low_band() -> None:
    low = sine_wave(200.0) * 0.20
    high = sine_wave(4_000.0) * 0.20

    toned_low = apply_presence_tone(AudioBuffer(samples=low, sample_rate=48_000), 6.0)
    toned_high = apply_presence_tone(AudioBuffer(samples=high, sample_rate=48_000), 6.0)

    low_ratio = rms(toned_low.samples[1_000:]) / rms(low[1_000:])
    high_ratio = rms(toned_high.samples[1_000:]) / rms(high[1_000:])
    assert high_ratio > low_ratio * 1.5


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


def test_recording_processing_chain_filters_fades_and_preserves_shape() -> None:
    low = sine_wave(80.0) * 0.20
    high = sine_wave(3_000.0) * 0.20
    stereo = np.column_stack([low + high, high]).astype(np.float32)
    buffer = AudioBuffer(samples=stereo, sample_rate=48_000)
    settings = RecordingProcessingSettings(
        gain_db=0.0,
        normalize_peak=0.8,
        highpass_hz=500.0,
        lowpass_hz=6_000.0,
        presence_gain_db=3.0,
        reverb_mix=0.25,
        delay_mix=0.5,
        fade_ms=20,
    )

    processed = apply_recording_processing(buffer, settings)
    processed_low_only = apply_recording_processing(
        AudioBuffer(samples=low, sample_rate=48_000),
        settings.model_copy(update={"presence_gain_db": 0.0, "fade_ms": 0}),
    )

    assert processed.samples.shape == stereo.shape
    assert processed.sample_rate == 48_000
    assert processed.channels == 2
    assert processed.samples[0, 0] == pytest.approx(0.0)
    assert abs(float(processed.samples[-1, 0])) < 0.01
    assert float(np.max(np.abs(processed.samples))) <= 1.0
    assert rms(processed_low_only.samples[1_000:]) < rms(low[1_000:]) * 0.35


def test_recording_processing_limits_peak_without_flat_top_clipping() -> None:
    source = sine_wave(1_000.0) * 0.40
    settings = RecordingProcessingSettings(
        gain_db=12.0,
        normalize_peak=0.35,
        highpass_hz=20.0,
        lowpass_hz=20_000.0,
        presence_gain_db=0.0,
        reverb_mix=0.0,
        delay_mix=0.0,
        fade_ms=0,
    )

    processed = apply_recording_processing(
        AudioBuffer(samples=source, sample_rate=48_000),
        settings,
    )
    steady_state = processed.samples[4_800:]

    assert float(np.max(np.abs(processed.samples))) <= 1.0
    assert harmonic_ratio(steady_state, sample_rate=48_000, fundamental_hz=1_000.0) < 0.03


def test_recording_processing_defers_reverb_and_delay_for_now() -> None:
    source = sine_wave(500.0) * 0.20
    base_settings = RecordingProcessingSettings(
        gain_db=0.0,
        normalize_peak=0.35,
        highpass_hz=90.0,
        lowpass_hz=8_000.0,
        presence_gain_db=-3.0,
        reverb_mix=0.0,
        delay_mix=0.0,
        fade_ms=0,
    )
    ambience_settings = base_settings.model_copy(update={"reverb_mix": 1.0, "delay_mix": 1.0})

    dry = apply_recording_processing(AudioBuffer(samples=source, sample_rate=48_000), base_settings)
    ambience_deferred = apply_recording_processing(
        AudioBuffer(samples=source, sample_rate=48_000),
        ambience_settings,
    )

    np.testing.assert_allclose(ambience_deferred.samples, dry.samples)
