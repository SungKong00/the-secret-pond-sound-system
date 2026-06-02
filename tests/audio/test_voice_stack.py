from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

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


def load_manifest(paths: ProjectPaths) -> dict:
    return json.loads(paths.voice_manifest.read_text(encoding="utf-8"))


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


def test_voice_stack_add_persists_chunks_in_test_library_mode(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "test_library"
    settings.voice_stack.insert_gain_db = 0.0
    store = VoiceStackStore(paths)
    samples = np.zeros((8_000, 2), dtype=np.float32)
    samples[:4_000] = 0.25
    voice = AudioBuffer(samples=samples, sample_rate=8_000)

    result = store.add_processed_voice(
        voice,
        settings,
        processing_settings_snapshot={"normalize_peak": 0.35},
        offset_frames=2_000,
    )
    loaded = read_wav(paths.voice_stack_raw)
    manifest = load_manifest(paths)

    assert result.added_chunks == 1
    assert result.entries[0]["source_mode"] == "test_library"
    assert result.entries[0]["accepted_clip_path"].startswith("data/processed/accepted/")
    assert Path(result.entries[0]["accepted_clip_path"]).is_absolute() is False
    assert (tmp_path / result.entries[0]["accepted_clip_path"]).exists()
    assert manifest["revision"] == 1
    assert manifest["entries"] == result.entries
    np.testing.assert_allclose(loaded.samples[:2_000], 0.0, atol=1e-4)
    np.testing.assert_allclose(loaded.samples[2_000:6_000], 0.25, atol=1e-4)
    np.testing.assert_allclose(loaded.samples[6_000:], 0.0, atol=1e-4)


def test_voice_stack_add_does_not_persist_chunks_in_live_ephemeral_mode(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "live_ephemeral"
    settings.voice_stack.insert_gain_db = 0.0
    store = VoiceStackStore(paths)
    voice = AudioBuffer(samples=np.ones((1_000, 2), dtype=np.float32) * 0.1, sample_rate=8_000)

    result = store.add_processed_voice(voice, settings, offset_frames=0)
    manifest = load_manifest(paths)

    assert list(paths.accepted_dir.glob("*.wav")) == []
    assert "accepted_clip_path" not in result.entries[0]
    assert "accepted_clip_path" not in manifest["entries"][0]


def test_voice_stack_add_splits_long_voice_into_multiple_manifest_entries(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "test_library"
    settings.voice_stack.insert_gain_db = 0.0
    store = VoiceStackStore(paths)
    voice = AudioBuffer(samples=np.ones((12_000, 2), dtype=np.float32) * 0.1, sample_rate=8_000)

    result = store.add_processed_voice(voice, settings, offset_frames=0)
    manifest = load_manifest(paths)

    assert result.added_chunks == 2
    assert manifest["revision"] == 1
    assert len(manifest["entries"]) == 2
    assert [entry["duration_seconds"] for entry in manifest["entries"]] == [1.0, 0.5]
    assert len(list(paths.accepted_dir.glob("*.wav"))) == 2


def test_voice_stack_add_tiles_final_short_chunk_to_loop_length(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "live_ephemeral"
    settings.voice_stack.insert_gain_db = 0.0
    store = VoiceStackStore(paths)
    voice = AudioBuffer(
        samples=np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
        sample_rate=8_000,
    )

    store.add_processed_voice(voice, settings, offset_frames=0)
    loaded = read_wav(paths.voice_stack_raw)

    np.testing.assert_allclose(
        loaded.samples[:4],
        np.array([[0.1, 0.2], [0.3, 0.4], [0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
        atol=1e-4,
    )


def test_voice_stack_add_wraps_chunk_around_loop_end(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "live_ephemeral"
    settings.voice_stack.insert_gain_db = 0.0
    store = VoiceStackStore(paths)
    samples = np.ones((8_000, 2), dtype=np.float32) * 0.1
    samples[4_000:] = 0.2
    voice = AudioBuffer(samples=samples, sample_rate=8_000)

    store.add_processed_voice(voice, settings, offset_frames=6_000)
    loaded = read_wav(paths.voice_stack_raw)

    np.testing.assert_allclose(loaded.samples[:2_000], 0.1, atol=1e-4)
    np.testing.assert_allclose(loaded.samples[2_000:6_000], 0.2, atol=1e-4)
    np.testing.assert_allclose(loaded.samples[6_000:], 0.1, atol=1e-4)


def test_voice_stack_add_peak_guard_uses_preclip_mix_peak(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "live_ephemeral"
    settings.voice_stack.insert_gain_db = 0.0
    store = VoiceStackStore(paths)
    first = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.8, sample_rate=8_000)
    second = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.8, sample_rate=8_000)

    store.add_processed_voice(first, settings, offset_frames=0)
    result = store.add_processed_voice(second, settings, offset_frames=0)
    loaded = read_wav(paths.voice_stack_raw)

    assert result.peak_before_guard == pytest.approx(1.6, rel=1e-4)
    assert result.peak_after_guard == pytest.approx(0.98, rel=1e-4)
    assert result.gain_reduction_db > 0
    assert float(np.max(np.abs(loaded.samples))) == pytest.approx(0.98, abs=1e-4)


def test_voice_stack_add_preserves_existing_manifest_entries(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "live_ephemeral"
    paths.ensure_directories()
    existing_entry = {"id": "existing", "source_mode": "test_library"}
    paths.voice_manifest.write_text(
        json.dumps({"schema_version": 1, "revision": 7, "entries": [existing_entry]}),
        encoding="utf-8",
    )
    store = VoiceStackStore(paths)
    voice = AudioBuffer(samples=np.ones((1_000, 2), dtype=np.float32) * 0.1, sample_rate=8_000)

    store.add_processed_voice(voice, settings, offset_frames=0)
    manifest = load_manifest(paths)

    assert manifest["revision"] == 8
    assert manifest["entries"][0] == existing_entry
    assert len(manifest["entries"]) == 2


def test_voice_stack_add_uses_deterministic_offsets_when_offset_is_omitted(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "live_ephemeral"
    store = VoiceStackStore(paths)
    voice = AudioBuffer(samples=np.ones((1_000, 2), dtype=np.float32) * 0.1, sample_rate=8_000)

    first = store.add_processed_voice(voice, settings)
    second = store.add_processed_voice(voice, settings)

    assert first.entries[0]["offset_frames"] != 0
    assert second.entries[0]["offset_frames"] != first.entries[0]["offset_frames"]
    assert 0 <= first.entries[0]["offset_frames"] < 8_000
    assert 0 <= second.entries[0]["offset_frames"] < 8_000


def test_voice_stack_add_rejects_invalid_offset(tmp_path: Path) -> None:
    store = VoiceStackStore(ProjectPaths(tmp_path))
    settings = voice_stack_settings()
    voice = AudioBuffer(samples=np.ones((1_000, 2), dtype=np.float32), sample_rate=8_000)

    with pytest.raises(ValueError, match="offset"):
        store.add_processed_voice(voice, settings, offset_frames=-1)

    with pytest.raises(ValueError, match="offset"):
        store.add_processed_voice(voice, settings, offset_frames=8_000)


def test_voice_stack_add_keeps_manifest_unchanged_when_raw_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings()
    settings.voice_stack.mode = "test_library"
    store = VoiceStackStore(paths)
    voice = AudioBuffer(samples=np.ones((1_000, 2), dtype=np.float32) * 0.1, sample_rate=8_000)
    store.ensure_initialized(settings)
    before_manifest = paths.voice_manifest.read_text(encoding="utf-8")
    real_write = write_wav_atomic

    def fail_raw_write(path: Path, buffer: AudioBuffer) -> None:
        if path == paths.voice_stack_raw:
            raise OSError("simulated raw write failure")
        real_write(path, buffer)

    monkeypatch.setattr("secret_pond.audio.voice_stack.write_wav_atomic", fail_raw_write)

    with pytest.raises(OSError, match="simulated"):
        store.add_processed_voice(voice, settings, offset_frames=0)

    assert paths.voice_manifest.read_text(encoding="utf-8") == before_manifest
    assert list(paths.accepted_dir.glob("*.wav")) == []


def test_voice_stack_add_applies_insert_gain_and_canonicalizes_mono_input(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = voice_stack_settings(sample_rate=8_000, channels=2)
    settings.voice_stack.mode = "live_ephemeral"
    settings.voice_stack.insert_gain_db = -6.0
    store = VoiceStackStore(paths)
    voice = AudioBuffer(samples=np.ones(8_000, dtype=np.float32) * 0.5, sample_rate=8_000)

    store.add_processed_voice(voice, settings, offset_frames=0)
    loaded = read_wav(paths.voice_stack_raw)
    expected_peak = 0.5 * (10 ** (-6.0 / 20.0))

    assert loaded.sample_rate == 8_000
    assert loaded.samples.shape == (8_000, 2)
    np.testing.assert_allclose(loaded.samples[:, 0], loaded.samples[:, 1], atol=1e-4)
    assert float(np.max(np.abs(loaded.samples))) == pytest.approx(expected_peak, rel=1e-3)
