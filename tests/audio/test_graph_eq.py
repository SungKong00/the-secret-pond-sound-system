from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from secret_pond.audio.graph_eq import apply_graph_eq, graph_eq_response_points
from secret_pond.config import EqSettings


def sine_tone(frequency_hz: float, *, sample_rate: int = 48_000) -> np.ndarray:
    seconds = 1.0
    frames = int(sample_rate * seconds)
    t = np.arange(frames, dtype=np.float32) / sample_rate
    mono = (np.sin(2 * np.pi * frequency_hz * t) * 0.1).astype(np.float32)
    return np.column_stack([mono, mono])


def steady_rms(samples: np.ndarray) -> float:
    trimmed = samples[2_000:-2_000]
    return float(np.sqrt(np.mean(np.square(trimmed))))


def eq_with_point(
    point_type: str,
    frequency_hz: float,
    gain_db: float,
    *,
    q: float = 1.0,
) -> EqSettings:
    return EqSettings(
        points=[
            {
                "id": "test",
                "type": point_type,
                "frequency_hz": frequency_hz,
                "gain_db": gain_db,
                "q": q,
            }
        ],
    )


def test_flat_graph_eq_returns_independent_copy_close_to_input() -> None:
    samples = sine_tone(1_000.0)

    processed = apply_graph_eq(samples, 48_000, EqSettings())

    assert processed is not samples
    assert processed.dtype == np.float32
    np.testing.assert_allclose(processed, samples, atol=1e-6)


def test_bell_peak_boost_targets_center_frequency_more_than_distant_frequency() -> None:
    eq = eq_with_point("bell", 1_000.0, 12.0, q=2.0)
    center = sine_tone(1_000.0)
    distant = sine_tone(100.0)

    center_gain = steady_rms(apply_graph_eq(center, 48_000, eq)) / steady_rms(center)
    distant_gain = steady_rms(apply_graph_eq(distant, 48_000, eq)) / steady_rms(distant)

    assert center_gain > 3.0
    assert distant_gain < 1.4


def test_low_shelf_boost_affects_low_frequency_more_than_high_frequency() -> None:
    eq = eq_with_point("low_shelf", 250.0, 12.0, q=0.7)
    low = sine_tone(100.0)
    high = sine_tone(5_000.0)

    low_gain = steady_rms(apply_graph_eq(low, 48_000, eq)) / steady_rms(low)
    high_gain = steady_rms(apply_graph_eq(high, 48_000, eq)) / steady_rms(high)

    assert low_gain > 3.0
    assert high_gain < 1.4


def test_high_shelf_boost_affects_high_frequency_more_than_low_frequency() -> None:
    eq = eq_with_point("high_shelf", 4_000.0, 12.0, q=0.7)
    low = sine_tone(200.0)
    high = sine_tone(8_000.0)

    low_gain = steady_rms(apply_graph_eq(low, 48_000, eq)) / steady_rms(low)
    high_gain = steady_rms(apply_graph_eq(high, 48_000, eq)) / steady_rms(high)

    assert high_gain > 3.0
    assert low_gain < 1.4


def test_graph_eq_response_points_cover_log_frequency_range() -> None:
    response = graph_eq_response_points(EqSettings(), width=5)

    assert len(response) == 5
    assert response[0][0] == pytest.approx(20.0)
    assert response[-1][0] == pytest.approx(20_000.0)
    assert [gain_db for _frequency_hz, gain_db in response] == pytest.approx([0.0] * 5)


def test_effective_graph_eq_points_reflect_legacy_gains_when_points_are_default() -> None:
    from secret_pond.audio.graph_eq import effective_graph_eq_points

    eq = EqSettings(low_gain_db=3.0, mid_gain_db=-2.0, high_gain_db=1.0)

    points = effective_graph_eq_points(eq)

    assert [(point.id, point.frequency_hz, point.gain_db) for point in points] == [
        ("legacy-low", 250.0, 3.0),
        ("legacy-mid", 1000.0, -2.0),
        ("legacy-high", 2000.0, 1.0),
    ]


def test_graph_eq_filter_range_still_rejects_invalid_order() -> None:
    with pytest.raises(ValidationError):
        EqSettings(highpass_hz=5_000.0, lowpass_hz=1_000.0)
