from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.renderer import LayerRenderer
from secret_pond.config import AppSettings, AudioFormatSettings
from secret_pond.paths import ProjectPaths


def renderer_settings(sample_rate: int = 8_000, channels: int = 2) -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(
            sample_rate=sample_rate,
            channels=channels,
            loop_seconds=1,
        ),
    )


def sine_wave(frequency: float, sample_rate: int = 8_000, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return np.sin(2 * np.pi * frequency * t).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


def write_required_sources(paths: ProjectPaths) -> None:
    paths.ensure_directories()
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=sine_wave(100.0) * 0.2, sample_rate=8_000),
    )
    write_wav_atomic(
        paths.mid_source,
        AudioBuffer(samples=sine_wave(1_000.0) * 0.2, sample_rate=8_000),
    )
    write_wav_atomic(
        paths.voice_stack_raw,
        AudioBuffer(samples=sine_wave(500.0) * 0.2, sample_rate=8_000),
    )


def test_renderer_creates_three_playback_files_with_same_frame_count(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)

    results = LayerRenderer(paths).render_all(settings)

    assert set(results) == {"low", "mid", "voice"}
    for output in (paths.low_playback, paths.mid_playback, paths.voice_playback):
        rendered = read_wav(output)
        assert rendered.sample_rate == 8_000
        assert rendered.samples.shape == (8_000, 2)


def test_renderer_normalizes_source_sample_rate_channels_and_loop_length(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings(sample_rate=8_000, channels=2)
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=np.ones(4_000, dtype=np.float32) * 0.2, sample_rate=16_000),
    )

    result = LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(result.output_path)

    assert rendered.sample_rate == 8_000
    assert rendered.samples.shape == (8_000, 2)
    np.testing.assert_allclose(rendered.samples[:, 0], rendered.samples[:, 1], atol=1e-4)


def test_renderer_does_not_modify_voice_stack_raw(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    before = paths.voice_stack_raw.read_bytes()
    settings.layers["voice"].eq.highpass_hz = 500.0

    LayerRenderer(paths).render_layer("voice", settings)

    assert paths.voice_stack_raw.read_bytes() == before


def test_renderer_highpass_filter_changes_output_measurably(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    low = sine_wave(60.0) * 0.25
    high = sine_wave(2_000.0) * 0.25
    write_wav_atomic(paths.low_source, AudioBuffer(samples=low + high, sample_rate=8_000))
    settings.layers["low"].eq.highpass_hz = 500.0

    result = LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(result.output_path)

    assert rms(rendered.samples[1_000:, 0]) < rms((low + high)[1_000:]) * 0.90


def test_renderer_missing_source_keeps_existing_rendered_file(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    previous = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.123, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, previous)

    with pytest.raises(FileNotFoundError, match="low"):
        LayerRenderer(paths).render_layer("low", settings)

    loaded = read_wav(paths.low_playback)
    np.testing.assert_allclose(loaded.samples, previous.samples, atol=1e-4)


def test_renderer_rejects_unknown_layer_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="layer"):
        LayerRenderer(ProjectPaths(tmp_path)).render_layer("unknown", renderer_settings())


def test_renderer_scales_peak_to_configured_ceiling(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    settings.audio.peak_ceiling = 0.5
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.9, sample_rate=8_000),
    )

    result = LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(result.output_path)

    assert result.peak_before_guard > settings.audio.peak_ceiling
    assert result.peak_after_guard == pytest.approx(0.5, abs=1e-4)
    assert float(np.max(np.abs(rendered.samples))) == pytest.approx(0.5, abs=1e-4)


def test_renderer_all_keeps_existing_files_when_any_layer_fails(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    previous = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.111, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, previous)
    write_wav_atomic(paths.mid_playback, previous)
    write_wav_atomic(paths.voice_playback, previous)
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=sine_wave(100.0) * 0.2, sample_rate=8_000),
    )
    write_wav_atomic(
        paths.voice_stack_raw,
        AudioBuffer(samples=sine_wave(500.0) * 0.2, sample_rate=8_000),
    )

    with pytest.raises(FileNotFoundError, match="mid"):
        LayerRenderer(paths).render_all(settings)

    for output in (paths.low_playback, paths.mid_playback, paths.voice_playback):
        np.testing.assert_allclose(read_wav(output).samples, previous.samples, atol=1e-4)


def test_renderer_all_rolls_back_when_replace_fails_mid_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    previous = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.111, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, previous)
    write_wav_atomic(paths.mid_playback, previous)
    write_wav_atomic(paths.voice_playback, previous)

    from secret_pond.audio import renderer

    real_replace = renderer._replace_file
    failed_once = False

    def fail_mid_output_replace(source: Path, destination: Path) -> None:
        nonlocal failed_once
        if destination == paths.mid_playback and not failed_once:
            failed_once = True
            raise OSError("simulated locked mid render")
        real_replace(source, destination)

    monkeypatch.setattr(renderer, "_replace_file", fail_mid_output_replace)

    with pytest.raises(OSError, match="locked"):
        LayerRenderer(paths).render_all(settings)

    for output in (paths.low_playback, paths.mid_playback, paths.voice_playback):
        np.testing.assert_allclose(read_wav(output).samples, previous.samples, atol=1e-4)
