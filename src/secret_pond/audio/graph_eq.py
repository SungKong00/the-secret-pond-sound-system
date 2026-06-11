from __future__ import annotations

from typing import cast

import numpy as np
from pedalboard import HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard

from secret_pond.config import (
    GRAPH_EQ_MAX_HZ,
    GRAPH_EQ_MIN_HZ,
    EqPointSettings,
    EqSettings,
    default_graph_eq_points,
)

_LEGACY_LOW_SHELF_HZ = 250.0
_LEGACY_MID_BELL_HZ = 1_000.0
_LEGACY_HIGH_SHELF_HZ = 2_000.0


def apply_graph_eq(samples: np.ndarray, sample_rate: int, eq: EqSettings) -> np.ndarray:
    points = _active_points(eq)
    active_points = [point for point in points if point.gain_db != 0.0]
    if not active_points:
        return samples.astype(np.float32, copy=True)

    board = Pedalboard([_filter_for_point(point, sample_rate) for point in active_points])
    processed = board(samples.astype(np.float32, copy=False), sample_rate)
    return np.asarray(processed, dtype=np.float32)


def graph_eq_response_points(eq: EqSettings, *, width: int = 256) -> list[tuple[float, float]]:
    if width < 2:
        msg = "width must be at least 2"
        raise ValueError(msg)

    frequencies = np.geomspace(GRAPH_EQ_MIN_HZ, GRAPH_EQ_MAX_HZ, width, dtype=np.float64)
    gains = np.zeros_like(frequencies)
    for point in _active_points(eq):
        gains += _response_for_point(frequencies, point)
    return [
        (float(frequency_hz), float(gain_db))
        for frequency_hz, gain_db in zip(frequencies, gains, strict=True)
    ]


def _active_points(eq: EqSettings) -> list[EqPointSettings]:
    if _uses_legacy_three_band_fields(eq):
        return _legacy_points(eq)
    return sorted(eq.points, key=lambda point: point.frequency_hz)


def _uses_legacy_three_band_fields(eq: EqSettings) -> bool:
    if eq.points != default_graph_eq_points():
        return False
    return eq.low_gain_db != 0.0 or eq.mid_gain_db != 0.0 or eq.high_gain_db != 0.0


def _legacy_points(eq: EqSettings) -> list[EqPointSettings]:
    return [
        EqPointSettings(
            id="legacy-low",
            type="low_shelf",
            frequency_hz=_LEGACY_LOW_SHELF_HZ,
            gain_db=eq.low_gain_db,
            q=0.7,
        ),
        EqPointSettings(
            id="legacy-mid",
            type="bell",
            frequency_hz=_LEGACY_MID_BELL_HZ,
            gain_db=eq.mid_gain_db,
            q=1.0,
        ),
        EqPointSettings(
            id="legacy-high",
            type="high_shelf",
            frequency_hz=_LEGACY_HIGH_SHELF_HZ,
            gain_db=eq.high_gain_db,
            q=0.7,
        ),
    ]


def _filter_for_point(
    point: EqPointSettings,
    sample_rate: int,
) -> PeakFilter | LowShelfFilter | HighShelfFilter:
    cutoff_frequency_hz = _frequency_below_nyquist(point.frequency_hz, sample_rate)
    filter_kwargs = {
        "cutoff_frequency_hz": cutoff_frequency_hz,
        "gain_db": point.gain_db,
        "q": point.q,
    }
    if point.type == "bell":
        return PeakFilter(**filter_kwargs)
    if point.type == "low_shelf":
        return LowShelfFilter(**filter_kwargs)
    if point.type == "high_shelf":
        return HighShelfFilter(**filter_kwargs)
    msg = f"unsupported graph eq point type: {point.type}"
    raise ValueError(msg)


def _frequency_below_nyquist(frequency_hz: float, sample_rate: int) -> float:
    nyquist = sample_rate / 2
    if frequency_hz < nyquist:
        return frequency_hz
    return float(np.nextafter(nyquist, 0.0))


def _response_for_point(frequencies: np.ndarray, point: EqPointSettings) -> np.ndarray:
    center_hz = point.frequency_hz
    if point.type == "bell":
        octave_distance = np.log2(frequencies / center_hz)
        width = max(point.q, 0.1)
        return cast(np.ndarray, point.gain_db / (1.0 + np.square(octave_distance * width * 2.0)))
    if point.type == "low_shelf":
        slope = max(point.q, 0.1) * 2.0
        return cast(np.ndarray, point.gain_db / (1.0 + np.power(frequencies / center_hz, slope)))
    if point.type == "high_shelf":
        slope = max(point.q, 0.1) * 2.0
        return cast(np.ndarray, point.gain_db / (1.0 + np.power(center_hz / frequencies, slope)))
    msg = f"unsupported graph eq point type: {point.type}"
    raise ValueError(msg)
