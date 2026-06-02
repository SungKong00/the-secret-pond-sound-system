from __future__ import annotations

from dataclasses import dataclass, field
from math import gcd

import numpy as np
from scipy.signal import resample_poly


@dataclass(frozen=True)
class AudioBuffer:
    samples: np.ndarray
    sample_rate: int
    channels: int = field(init=False)

    def __post_init__(self) -> None:
        samples = np.asarray(self.samples)
        if samples.ndim not in (1, 2):
            msg = "AudioBuffer samples must be a 1D mono or 2D channel array"
            raise ValueError(msg)
        normalized = self._to_float32(samples)
        object.__setattr__(self, "samples", normalized)
        object.__setattr__(self, "channels", self._count_channels(normalized))

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    def to_canonical(self, sample_rate: int, channels: int) -> AudioBuffer:
        converted = self._with_channels(channels)
        if converted.sample_rate == sample_rate:
            return converted

        divisor = gcd(converted.sample_rate, sample_rate)
        up = sample_rate // divisor
        down = converted.sample_rate // divisor
        resampled = resample_poly(converted.samples, up, down, axis=0).astype(np.float32)
        return AudioBuffer(samples=resampled, sample_rate=sample_rate)

    def to_frame_count(self, frames: int) -> AudioBuffer:
        if frames < 0:
            msg = "frames must be non-negative"
            raise ValueError(msg)

        samples = self._as_2d(self.samples)
        if frames == samples.shape[0]:
            return AudioBuffer(samples=samples.copy(), sample_rate=self.sample_rate)
        if frames < samples.shape[0]:
            return AudioBuffer(samples=samples[:frames].copy(), sample_rate=self.sample_rate)
        if samples.shape[0] == 0:
            return AudioBuffer(
                samples=np.zeros((frames, samples.shape[1]), dtype=np.float32),
                sample_rate=self.sample_rate,
            )

        repeats = int(np.ceil(frames / samples.shape[0]))
        tiled = np.tile(samples, (repeats, 1))[:frames]
        return AudioBuffer(samples=tiled.astype(np.float32), sample_rate=self.sample_rate)

    def clipped(self, peak: float = 1.0) -> AudioBuffer:
        samples = np.clip(self.samples, -peak, peak).astype(np.float32)
        return AudioBuffer(samples=samples, sample_rate=self.sample_rate)

    def _with_channels(self, channels: int) -> AudioBuffer:
        if channels < 1:
            msg = "channels must be at least 1"
            raise ValueError(msg)

        samples = self._as_2d(self.samples)
        current = samples.shape[1]
        if current == channels:
            return AudioBuffer(samples=samples.copy(), sample_rate=self.sample_rate)
        if channels == 1:
            return AudioBuffer(
                samples=samples.mean(axis=1, keepdims=True),
                sample_rate=self.sample_rate,
            )
        if current == 1:
            return AudioBuffer(
                samples=np.repeat(samples, channels, axis=1),
                sample_rate=self.sample_rate,
            )
        if current > channels:
            return AudioBuffer(samples=samples[:, :channels], sample_rate=self.sample_rate)

        repeats = int(np.ceil(channels / current))
        expanded = np.tile(samples, (1, repeats))[:, :channels]
        return AudioBuffer(samples=expanded, sample_rate=self.sample_rate)

    @staticmethod
    def _as_2d(samples: np.ndarray) -> np.ndarray:
        if samples.ndim == 1:
            return samples.reshape(-1, 1)
        return samples

    @staticmethod
    def _count_channels(samples: np.ndarray) -> int:
        return 1 if samples.ndim == 1 else int(samples.shape[1])

    @staticmethod
    def _to_float32(samples: np.ndarray) -> np.ndarray:
        if np.issubdtype(samples.dtype, np.integer):
            info = np.iinfo(samples.dtype)
            scale = max(abs(info.min), info.max)
            return (samples.astype(np.float32) / float(scale)).astype(np.float32)
        return np.clip(samples.astype(np.float32), -1.0, 1.0)
