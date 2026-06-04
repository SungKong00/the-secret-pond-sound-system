from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.layers import LAYER_IDS
from secret_pond.audio.renderer import LayerRenderer
from secret_pond.config import AppSettings, AudioFormatSettings, SourceSelectionSettings
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


def tone_magnitude(samples: np.ndarray, sample_rate: int, frequency: float) -> float:
    mono = samples[:, 0] if samples.ndim == 2 else samples
    spectrum = np.abs(np.fft.rfft(mono[1_000:]))
    bin_index = int(round(frequency * len(mono[1_000:]) / sample_rate))
    return float(spectrum[bin_index])


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


def hidden_render_files(paths: ProjectPaths) -> list[Path]:
    return list(paths.rendered_layers_dir.glob(".*.wav"))


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


def test_renderer_uses_selected_library_source_before_legacy_path(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    settings.layers["low"].volume_db = 0.0
    selected_path = paths.low_sources_dir / "selected-low.wav"
    legacy = sine_wave(100.0) * 0.05
    selected = sine_wave(100.0) * 0.35
    write_wav_atomic(paths.low_source, AudioBuffer(samples=legacy, sample_rate=8_000))
    write_wav_atomic(selected_path, AudioBuffer(samples=selected, sample_rate=8_000))
    settings.sources = SourceSelectionSettings(
        low_path="data/sources/low/selected-low.wav",
    )

    result = LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(result.output_path)

    assert rms(rendered.samples) > rms(legacy) * 3.0


def test_renderer_falls_back_to_legacy_source_when_no_library_selection(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    settings.layers["mid"].volume_db = 0.0
    write_wav_atomic(
        paths.mid_source,
        AudioBuffer(samples=sine_wave(1_000.0) * 0.25, sample_rate=8_000),
    )

    result = LayerRenderer(paths).render_layer("mid", settings)

    assert result.output_path == paths.mid_playback
    assert paths.mid_playback.exists()


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
    settings.layers["low"].volume_db = 0.0
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.9, sample_rate=8_000),
    )

    result = LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(result.output_path)

    assert result.peak_before_guard > settings.audio.peak_ceiling
    assert result.peak_after_guard == pytest.approx(0.5, abs=1e-4)
    assert float(np.max(np.abs(rendered.samples))) == pytest.approx(0.5, abs=1e-4)


def test_renderer_applies_volume_db_as_baked_base_gain(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=sine_wave(500.0) * 0.2, sample_rate=8_000),
    )
    settings.layers["low"].volume_db = -6.0
    quiet = LayerRenderer(paths).render_layer("low", settings)
    quiet_samples = read_wav(quiet.output_path).samples
    settings.layers["low"].volume_db = 0.0
    full = LayerRenderer(paths).render_layer("low", settings)
    full_samples = read_wav(full.output_path).samples

    assert rms(quiet_samples) == pytest.approx(rms(full_samples) * (10 ** (-6.0 / 20.0)), rel=0.02)


def test_renderer_zero_three_band_eq_gains_preserve_filtered_signal(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    settings.layers["low"].volume_db = 0.0
    source = sine_wave(500.0) * 0.2
    write_wav_atomic(paths.low_source, AudioBuffer(samples=source, sample_rate=8_000))

    LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(paths.low_playback)

    assert tone_magnitude(rendered.samples, 8_000, 500.0) == pytest.approx(
        tone_magnitude(source, 8_000, 500.0),
        rel=0.03,
    )


@pytest.mark.parametrize(
    ("gain_name", "frequency"),
    [
        ("low_gain_db", 100.0),
        ("mid_gain_db", 1_000.0),
        ("high_gain_db", 3_000.0),
    ],
)
def test_renderer_three_band_eq_boosts_target_band(
    tmp_path: Path,
    gain_name: str,
    frequency: float,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    settings.layers["low"].volume_db = 0.0
    source = (sine_wave(100.0) + sine_wave(1_000.0) + sine_wave(3_000.0)) * 0.1
    write_wav_atomic(paths.low_source, AudioBuffer(samples=source, sample_rate=8_000))
    baseline_result = LayerRenderer(paths).render_layer("low", settings)
    baseline = read_wav(baseline_result.output_path).samples
    setattr(settings.layers["low"].eq, gain_name, 6.0)

    boosted_result = LayerRenderer(paths).render_layer("low", settings)
    boosted = read_wav(boosted_result.output_path).samples

    assert tone_magnitude(boosted, 8_000, frequency) > (
        tone_magnitude(baseline, 8_000, frequency) * 1.5
    )


def test_renderer_boost_peak_guard_uses_preclip_peak(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    settings = renderer_settings()
    settings.audio.peak_ceiling = 0.5
    settings.layers["low"].volume_db = 6.0
    write_wav_atomic(
        paths.low_source,
        AudioBuffer(samples=sine_wave(500.0) * 0.8, sample_rate=8_000),
    )

    result = LayerRenderer(paths).render_layer("low", settings)
    rendered = read_wav(result.output_path)

    assert result.peak_before_guard > 1.0
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


def test_renderer_stage_all_does_not_replace_outputs_until_commit(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    previous = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.111, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, previous)
    write_wav_atomic(paths.mid_playback, previous)
    write_wav_atomic(paths.voice_playback, previous)

    staged = LayerRenderer(paths).stage_all(settings)

    assert set(staged.results) == set(LAYER_IDS)
    for output in (paths.low_playback, paths.mid_playback, paths.voice_playback):
        np.testing.assert_allclose(read_wav(output).samples, previous.samples, atol=1e-4)
    assert hidden_render_files(paths)

    staged.commit()

    for output in (paths.low_playback, paths.mid_playback, paths.voice_playback):
        assert read_wav(output).samples.shape == previous.samples.shape
        assert not np.allclose(read_wav(output).samples, previous.samples, atol=1e-4)
    staged.cleanup()
    assert hidden_render_files(paths) == []


def test_renderer_staged_rollback_restores_previous_outputs(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    previous = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.111, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, previous)
    write_wav_atomic(paths.mid_playback, previous)
    write_wav_atomic(paths.voice_playback, previous)
    staged = LayerRenderer(paths).stage_all(settings)
    staged.commit()

    staged.rollback()
    staged.cleanup()

    for output in (paths.low_playback, paths.mid_playback, paths.voice_playback):
        np.testing.assert_allclose(read_wav(output).samples, previous.samples, atol=1e-4)
    assert hidden_render_files(paths) == []


def test_renderer_staged_rollback_removes_outputs_without_previous_files(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    staged = LayerRenderer(paths).stage_all(settings)
    staged.commit()

    staged.rollback()
    staged.cleanup()

    assert not paths.low_playback.exists()
    assert not paths.mid_playback.exists()
    assert not paths.voice_playback.exists()
    assert hidden_render_files(paths) == []


def test_renderer_stage_all_cleans_partial_temps_when_mid_stage_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    from secret_pond.audio import renderer

    real_write = renderer.write_wav_atomic

    def fail_mid_temp(path: Path, buffer: AudioBuffer) -> None:
        if path.name.startswith(".mid_playback"):
            raise OSError("simulated mid temp write failure")
        real_write(path, buffer)

    monkeypatch.setattr(renderer, "write_wav_atomic", fail_mid_temp)

    with pytest.raises(OSError, match="mid temp"):
        LayerRenderer(paths).stage_all(settings)

    assert hidden_render_files(paths) == []
    assert not paths.low_playback.exists()
    assert not paths.mid_playback.exists()
    assert not paths.voice_playback.exists()


def test_renderer_cleanup_is_best_effort_after_successful_commit(
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

    original_unlink = Path.unlink
    real_backup = renderer._backup_render_path

    def locked_backup_path(output_path: Path) -> Path:
        backup_path = real_backup(output_path)
        if output_path == paths.low_playback:
            return backup_path.with_name(".low_playback.locked.bak.wav")
        return backup_path

    def fail_locked_backup_unlink(path: Path, *args, **kwargs) -> None:
        if path.name == ".low_playback.locked.bak.wav":
            raise OSError("simulated backup cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(renderer, "_backup_render_path", locked_backup_path)
    monkeypatch.setattr(Path, "unlink", fail_locked_backup_unlink)

    results = LayerRenderer(paths).render_all(settings)

    assert set(results) == set(LAYER_IDS)
    assert paths.low_playback.exists()
    assert paths.mid_playback.exists()
    assert paths.voice_playback.exists()


def test_renderer_rollback_after_cleanup_does_not_delete_committed_outputs(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    settings = renderer_settings()
    write_required_sources(paths)
    previous = AudioBuffer(samples=np.ones((8_000, 2), dtype=np.float32) * 0.111, sample_rate=8_000)
    write_wav_atomic(paths.low_playback, previous)
    write_wav_atomic(paths.mid_playback, previous)
    write_wav_atomic(paths.voice_playback, previous)
    staged = LayerRenderer(paths).stage_all(settings)
    staged.commit()
    staged.cleanup()

    staged.rollback()

    assert paths.low_playback.exists()
    assert paths.mid_playback.exists()
    assert paths.voice_playback.exists()
    assert hidden_render_files(paths) == []


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
