from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from secret_pond.audio.buffers import AudioBuffer


def apply_gain_db(buffer: AudioBuffer, gain_db: float) -> AudioBuffer:
    gain = 10 ** (gain_db / 20.0)
    return AudioBuffer(samples=buffer.samples * gain, sample_rate=buffer.sample_rate)


def apply_fade(buffer: AudioBuffer, fade_in_ms: float, fade_out_ms: float) -> AudioBuffer:
    if fade_in_ms < 0 or fade_out_ms < 0:
        msg = "fade durations must be non-negative"
        raise ValueError(msg)

    samples = buffer.samples.copy()
    if samples.shape[0] == 0:
        return AudioBuffer(samples=samples, sample_rate=buffer.sample_rate)

    envelope = np.ones(samples.shape[0], dtype=np.float32)
    fade_in_frames = _ms_to_frames(fade_in_ms, buffer.sample_rate, samples.shape[0])
    fade_out_frames = _ms_to_frames(fade_out_ms, buffer.sample_rate, samples.shape[0])

    if fade_in_frames > 0:
        envelope[:fade_in_frames] *= np.linspace(0.0, 1.0, fade_in_frames, dtype=np.float32)
    if fade_out_frames > 0:
        envelope[-fade_out_frames:] *= np.linspace(1.0, 0.0, fade_out_frames, dtype=np.float32)

    if samples.ndim == 1:
        faded = samples * envelope
    else:
        faded = samples * envelope[:, np.newaxis]
    return AudioBuffer(samples=faded, sample_rate=buffer.sample_rate)


def apply_highpass(buffer: AudioBuffer, cutoff_hz: float, order: int = 4) -> AudioBuffer:
    return _apply_filter(buffer, cutoff_hz, "highpass", order)


def apply_lowpass(buffer: AudioBuffer, cutoff_hz: float, order: int = 4) -> AudioBuffer:
    return _apply_filter(buffer, cutoff_hz, "lowpass", order)


def _apply_filter(
    buffer: AudioBuffer,
    cutoff_hz: float,
    btype: str,
    order: int,
) -> AudioBuffer:
    _validate_cutoff(cutoff_hz, buffer.sample_rate)
    sos = butter(order, cutoff_hz, btype=btype, fs=buffer.sample_rate, output="sos")
    filtered = sosfilt(sos, buffer.samples, axis=0).astype(np.float32)
    return AudioBuffer(samples=filtered, sample_rate=buffer.sample_rate)


def _validate_cutoff(cutoff_hz: float, sample_rate: int) -> None:
    nyquist = sample_rate / 2
    if not np.isfinite(cutoff_hz) or cutoff_hz <= 0 or cutoff_hz >= nyquist:
        msg = f"cutoff_hz must be greater than 0 and less than Nyquist ({nyquist})"
        raise ValueError(msg)


def _ms_to_frames(milliseconds: float, sample_rate: int, max_frames: int) -> int:
    frames = int(round(sample_rate * (milliseconds / 1000.0)))
    return min(frames, max_frames)
