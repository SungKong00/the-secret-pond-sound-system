from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from secret_pond.audio.buffers import AudioBuffer

DEFAULT_NOISE_FLOOR = 0.001
SILENT_PEAK_THRESHOLD = 0.0005
SILENT_RMS_THRESHOLD = 0.00005


@dataclass(frozen=True)
class AudioLevelMetrics:
    frames: int
    sample_rate: int
    channels: int
    peak: float
    rms: float
    nonzero_ratio: float
    above_noise_floor_ratio: float


def analyze_audio_levels(
    buffer: AudioBuffer,
    *,
    noise_floor: float = DEFAULT_NOISE_FLOOR,
) -> AudioLevelMetrics:
    samples = buffer.samples
    sample_count = int(samples.size)
    if sample_count == 0:
        return AudioLevelMetrics(
            frames=buffer.frames,
            sample_rate=buffer.sample_rate,
            channels=buffer.channels,
            peak=0.0,
            rms=0.0,
            nonzero_ratio=0.0,
            above_noise_floor_ratio=0.0,
        )

    absolute = np.abs(samples)
    return AudioLevelMetrics(
        frames=buffer.frames,
        sample_rate=buffer.sample_rate,
        channels=buffer.channels,
        peak=float(np.max(absolute)),
        rms=float(np.sqrt(np.mean(samples**2))),
        nonzero_ratio=float(np.count_nonzero(samples)) / float(sample_count),
        above_noise_floor_ratio=float(np.count_nonzero(absolute > noise_floor))
        / float(sample_count),
    )


def is_effectively_silent(
    levels: AudioLevelMetrics,
    *,
    peak_threshold: float = SILENT_PEAK_THRESHOLD,
    rms_threshold: float = SILENT_RMS_THRESHOLD,
) -> bool:
    if levels.frames == 0:
        return True
    if levels.peak == 0.0 and levels.rms == 0.0 and levels.nonzero_ratio == 0.0:
        return True
    return (
        levels.peak < peak_threshold
        and levels.rms < rms_threshold
        and levels.above_noise_floor_ratio == 0.0
    )


def audio_level_payload(levels: AudioLevelMetrics) -> dict[str, int | float]:
    return {
        "frames": levels.frames,
        "sample_rate": levels.sample_rate,
        "channels": levels.channels,
        "peak": levels.peak,
        "rms": levels.rms,
        "nonzero_ratio": levels.nonzero_ratio,
        "above_noise_floor_ratio": levels.above_noise_floor_ratio,
    }
