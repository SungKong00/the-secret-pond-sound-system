from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer


def test_audio_buffer_converts_mono_to_stereo_float32() -> None:
    samples = np.array([0.0, 0.5, -0.5], dtype=np.float64)

    buffer = AudioBuffer(samples=samples, sample_rate=48_000).to_canonical(
        sample_rate=48_000,
        channels=2,
    )

    assert buffer.samples.dtype == np.float32
    assert buffer.samples.shape == (3, 2)
    assert buffer.channels == 2
    np.testing.assert_allclose(buffer.samples[:, 0], samples.astype(np.float32))
    np.testing.assert_allclose(buffer.samples[:, 1], samples.astype(np.float32))


def test_audio_buffer_tiles_to_exact_frame_count() -> None:
    buffer = AudioBuffer(samples=np.ones((2, 2), dtype=np.float32), sample_rate=48_000)

    tiled = buffer.to_frame_count(5)

    assert tiled.samples.shape == (5, 2)
    np.testing.assert_allclose(tiled.samples, np.ones((5, 2), dtype=np.float32))


def test_audio_buffer_trims_to_exact_frame_count() -> None:
    buffer = AudioBuffer(samples=np.ones((10, 2), dtype=np.float32), sample_rate=48_000)

    trimmed = buffer.to_frame_count(4)

    assert trimmed.samples.shape == (4, 2)


def test_audio_buffer_normalizes_integer_pcm() -> None:
    buffer = AudioBuffer(samples=np.array([0, 32767], dtype=np.int16), sample_rate=48_000)

    assert buffer.samples.dtype == np.float32
    np.testing.assert_allclose(buffer.samples, np.array([0.0, 0.9999695], dtype=np.float32))


def test_audio_buffer_clips_float_input_to_safe_range() -> None:
    buffer = AudioBuffer(samples=np.array([-2.0, 0.5, 2.0], dtype=np.float32), sample_rate=48_000)

    np.testing.assert_allclose(buffer.samples, np.array([-1.0, 0.5, 1.0], dtype=np.float32))
