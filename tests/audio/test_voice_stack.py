from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.voice_stack import VoiceStackStore
from secret_pond.config import AppSettings, AudioFormatSettings, VoiceStackSettings
from secret_pond.paths import ProjectPaths


def voice_stack_settings(sample_rate: int = 8_000, channels: int = 2) -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=sample_rate, channels=channels),
        voice_stack=VoiceStackSettings(loop_seconds=1),
    )


def test_voice_stack_initializes_missing_raw_and_manifest(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    store = VoiceStackStore(paths)

    snapshot = store.ensure_initialized(voice_stack_settings())
    loaded = read_wav(paths.voice_stack_raw)

    assert snapshot.raw_created is True
    assert snapshot.manifest_created is True
    assert snapshot.buffer.sample_rate == 8_000
    assert snapshot.buffer.samples.shape == (8_000, 2)
    np.testing.assert_allclose(snapshot.buffer.samples, 0.0)
    assert loaded.sample_rate == 8_000
    assert loaded.samples.shape == (8_000, 2)
    np.testing.assert_allclose(loaded.samples, 0.0)
    assert json.loads(paths.voice_manifest.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "revision": 0,
        "entries": [],
    }


def test_voice_stack_preserves_existing_manifest(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    existing_manifest = {
        "schema_version": 1,
        "revision": 3,
        "entries": [{"id": "existing"}],
    }
    paths.voice_manifest.write_text(json.dumps(existing_manifest), encoding="utf-8")
    store = VoiceStackStore(paths)

    snapshot = store.ensure_initialized(voice_stack_settings())

    assert snapshot.manifest_created is False
    assert json.loads(paths.voice_manifest.read_text(encoding="utf-8")) == existing_manifest


def test_voice_stack_does_not_rewrite_already_canonical_raw(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    samples = np.full((8_000, 2), 0.125, dtype=np.float32)
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(samples=samples, sample_rate=8_000))
    store = VoiceStackStore(paths)

    def fail_write(*_args, **_kwargs) -> None:
        raise AssertionError("canonical raw stack should not be rewritten")

    monkeypatch.setattr("secret_pond.audio.voice_stack.write_wav_atomic", fail_write)

    snapshot = store.ensure_initialized(voice_stack_settings())

    assert snapshot.raw_created is False
    assert snapshot.raw_normalized is False
    np.testing.assert_allclose(snapshot.buffer.samples, samples, atol=1e-4)


def test_voice_stack_tiles_short_existing_raw_to_loop_length(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    samples = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(samples=samples, sample_rate=8_000))
    store = VoiceStackStore(paths)

    snapshot = store.ensure_initialized(voice_stack_settings())
    loaded = read_wav(paths.voice_stack_raw)

    assert snapshot.raw_normalized is True
    assert loaded.samples.shape == (8_000, 2)
    np.testing.assert_allclose(loaded.samples[:4], np.tile(samples, (2, 1)), atol=1e-4)


def test_voice_stack_trims_long_existing_raw_to_loop_length(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    samples = np.linspace(-0.5, 0.5, 9_000, dtype=np.float32)
    stereo = np.column_stack([samples, samples])
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(samples=stereo, sample_rate=8_000))
    store = VoiceStackStore(paths)

    snapshot = store.ensure_initialized(voice_stack_settings())
    loaded = read_wav(paths.voice_stack_raw)

    assert snapshot.raw_normalized is True
    assert loaded.samples.shape == (8_000, 2)
    np.testing.assert_allclose(loaded.samples[:, 0], stereo[:8_000, 0], atol=1e-4)


def test_voice_stack_converts_sample_rate_and_channels_from_existing_raw(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    mono = np.sin(np.linspace(0.0, np.pi * 4, 4_000, dtype=np.float32)) * 0.25
    write_wav_atomic(paths.voice_stack_raw, AudioBuffer(samples=mono, sample_rate=16_000))
    store = VoiceStackStore(paths)

    snapshot = store.ensure_initialized(voice_stack_settings(sample_rate=8_000, channels=2))
    loaded = read_wav(paths.voice_stack_raw)

    assert snapshot.raw_normalized is True
    assert loaded.sample_rate == 8_000
    assert loaded.samples.shape == (8_000, 2)
    np.testing.assert_allclose(loaded.samples[:, 0], loaded.samples[:, 1], atol=1e-4)
