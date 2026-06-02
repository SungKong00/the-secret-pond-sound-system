from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic


def test_write_wav_atomic_round_trips_audio_buffer(tmp_path) -> None:
    path = tmp_path / "roundtrip.wav"
    samples = np.array([[0.0, 0.25], [-0.25, 0.5]], dtype=np.float32)
    buffer = AudioBuffer(samples=samples, sample_rate=48_000)

    write_wav_atomic(path, buffer)
    loaded = read_wav(path)

    assert loaded.sample_rate == 48_000
    assert loaded.samples.shape == (2, 2)
    np.testing.assert_allclose(loaded.samples, samples, atol=1e-4)
