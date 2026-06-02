from __future__ import annotations

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.player import LayerPlaybackState, mix_layer_blocks


def stereo(value: float, frames: int = 4, sample_rate: int = 8_000) -> AudioBuffer:
    return AudioBuffer(
        samples=np.ones((frames, 2), dtype=np.float32) * value,
        sample_rate=sample_rate,
    )


def test_mixer_sums_enabled_layers_without_reapplying_baked_volume() -> None:
    layers = {
        "low": stereo(0.1),
        "mid": stereo(0.2),
        "voice": stereo(0.3),
    }

    block = mix_layer_blocks(layers, {}, frame_cursor=0, block_size=4)

    np.testing.assert_allclose(block.samples, np.ones((4, 2), dtype=np.float32) * 0.6)
    assert block.next_frame_cursor == 0


def test_mixer_skips_disabled_layers() -> None:
    layers = {
        "low": stereo(0.1),
        "mid": stereo(0.2),
        "voice": stereo(0.3),
    }
    states = {"mid": LayerPlaybackState(enabled=False)}

    block = mix_layer_blocks(layers, states, frame_cursor=0, block_size=4)

    np.testing.assert_allclose(block.samples, np.ones((4, 2), dtype=np.float32) * 0.4)


def test_mixer_reads_wrapped_block_and_reports_next_cursor() -> None:
    samples = np.column_stack(
        [
            np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float32),
            np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float32),
        ],
    )
    layers = {
        "low": AudioBuffer(samples=samples, sample_rate=8_000),
        "mid": stereo(0.0),
        "voice": stereo(0.0),
    }

    block = mix_layer_blocks(layers, {}, frame_cursor=2, block_size=4)

    np.testing.assert_allclose(
        block.samples[:, 0],
        np.array([0.2, 0.3, 0.0, 0.1], dtype=np.float32),
        atol=1e-6,
    )
    assert block.next_frame_cursor == 2


def test_mixer_applies_realtime_trim_only_to_matching_layer() -> None:
    layers = {
        "low": stereo(0.2),
        "mid": stereo(0.2),
        "voice": stereo(0.2),
    }
    states = {"voice": LayerPlaybackState(realtime_trim_db=-6.0)}

    block = mix_layer_blocks(layers, states, frame_cursor=0, block_size=4)

    expected_voice = 0.2 * (10 ** (-6.0 / 20.0))
    np.testing.assert_allclose(block.samples, np.ones((4, 2)) * (0.4 + expected_voice), atol=1e-6)


def test_mixer_rejects_mismatched_layer_format() -> None:
    layers = {
        "low": stereo(0.1, sample_rate=8_000),
        "mid": stereo(0.2, sample_rate=16_000),
        "voice": stereo(0.3, sample_rate=8_000),
    }

    with pytest.raises(ValueError, match="sample rate"):
        mix_layer_blocks(layers, {}, frame_cursor=0, block_size=4)


def test_mixer_rejects_invalid_sizes_and_peak_ceiling() -> None:
    layers = {"low": stereo(0.1), "mid": stereo(0.2), "voice": stereo(0.3)}

    with pytest.raises(ValueError, match="block_size"):
        mix_layer_blocks(layers, {}, frame_cursor=0, block_size=0)

    with pytest.raises(ValueError, match="peak_ceiling"):
        mix_layer_blocks(layers, {}, frame_cursor=0, block_size=4, peak_ceiling=0.0)

    with pytest.raises(ValueError, match="peak_ceiling"):
        mix_layer_blocks(layers, {}, frame_cursor=0, block_size=4, peak_ceiling=1.1)

    with pytest.raises(ValueError, match="peak_ceiling"):
        mix_layer_blocks(layers, {}, frame_cursor=0, block_size=4, peak_ceiling=float("nan"))

    with pytest.raises(ValueError, match="frame_cursor"):
        mix_layer_blocks(layers, {}, frame_cursor=-1, block_size=4)


def test_mixer_peak_guard_scales_instead_of_clipping() -> None:
    low = AudioBuffer(
        samples=np.array([[0.8, 0.8], [0.4, 0.4], [0.8, 0.8], [0.4, 0.4]], dtype=np.float32),
        sample_rate=8_000,
    )
    mid = AudioBuffer(
        samples=np.array([[0.6, 0.6], [0.3, 0.3], [0.6, 0.6], [0.3, 0.3]], dtype=np.float32),
        sample_rate=8_000,
    )
    voice = AudioBuffer(
        samples=np.array([[0.2, 0.2], [0.1, 0.1], [0.2, 0.2], [0.1, 0.1]], dtype=np.float32),
        sample_rate=8_000,
    )
    layers = {
        "low": low,
        "mid": mid,
        "voice": voice,
    }

    block = mix_layer_blocks(layers, {}, frame_cursor=0, block_size=4, peak_ceiling=0.8)

    assert block.peak_before_guard == pytest.approx(1.6, rel=1e-6)
    assert block.peak_after_guard == pytest.approx(0.8, rel=1e-6)
    np.testing.assert_allclose(
        block.samples[:, 0],
        np.array([0.8, 0.4, 0.8, 0.4], dtype=np.float32),
    )
