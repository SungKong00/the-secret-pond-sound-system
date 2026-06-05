from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from math import log10
from pathlib import Path
from uuid import uuid4

import numpy as np
from scipy.signal import butter, sosfilt

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.layers import LAYER_IDS, LayerId
from secret_pond.audio.source_library import render_source_path
from secret_pond.config import AppSettings, EqSettings, LayerSettings
from secret_pond.paths import ProjectPaths

_LOW_BAND_HZ = 250.0
_HIGH_BAND_HZ = 2_000.0


@dataclass(frozen=True)
class RenderResult:
    layer_id: LayerId
    output_path: Path
    peak_before_guard: float
    peak_after_guard: float
    gain_reduction_db: float


@dataclass(frozen=True)
class _RenderedAudio:
    samples: np.ndarray
    sample_rate: int


@dataclass
class StagedRenderSet:
    results: dict[LayerId, RenderResult]
    paths: dict[LayerId, Path]
    _replacements: dict[LayerId, tuple[Path, Path]]
    _committed: list[tuple[Path, Path | None]] = field(default_factory=list)
    _backups: list[Path] = field(default_factory=list)

    def commit(self) -> None:
        if self._committed:
            return
        self._committed, self._backups = _commit_render_set(self._replacements)

    def rollback(self) -> None:
        if not self._committed:
            return
        _rollback_render_set(self._committed)
        self._committed = []

    def cleanup(self) -> None:
        for temp_path, _output_path in self._replacements.values():
            _safe_unlink(temp_path)
        for backup_path in self._backups:
            _safe_unlink(backup_path)
        self._backups = []
        self._committed = []


class LayerRenderer:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def render_layer(self, layer_id: str, settings: AppSettings) -> RenderResult:
        normalized_layer_id = _validate_layer_id(layer_id)
        rendered_audio = self._render_audio(normalized_layer_id, settings)
        result, guarded = _guard_rendered_buffer(
            normalized_layer_id,
            self._output_path(normalized_layer_id),
            rendered_audio,
            settings.audio.peak_ceiling,
        )
        write_wav_atomic(result.output_path, guarded)
        return result

    def render_all(self, settings: AppSettings) -> dict[LayerId, RenderResult]:
        staged = self.stage_all(settings)
        try:
            staged.commit()
            return staged.results
        finally:
            staged.cleanup()

    def render_layer_buffer(self, layer_id: str, settings: AppSettings) -> AudioBuffer:
        normalized_layer_id = _validate_layer_id(layer_id)
        rendered_audio = self._render_audio(normalized_layer_id, settings)
        _result, guarded = _guard_rendered_buffer(
            normalized_layer_id,
            self._output_path(normalized_layer_id),
            rendered_audio,
            settings.audio.peak_ceiling,
        )
        return guarded

    def stage_all(self, settings: AppSettings) -> StagedRenderSet:
        self._paths.ensure_directories()
        rendered: dict[LayerId, tuple[RenderResult, AudioBuffer]] = {}
        temp_paths: dict[LayerId, Path] = {}
        try:
            for layer_id in LAYER_IDS:
                rendered_audio = self._render_audio(layer_id, settings)
                result, guarded = _guard_rendered_buffer(
                    layer_id,
                    self._output_path(layer_id),
                    rendered_audio,
                    settings.audio.peak_ceiling,
                )
                temp_path = _temp_render_path(result.output_path)
                write_wav_atomic(temp_path, guarded)
                temp_paths[layer_id] = temp_path
                rendered[layer_id] = (result, guarded)

            replacements = {
                layer_id: (temp_paths[layer_id], rendered[layer_id][0].output_path)
                for layer_id in LAYER_IDS
            }
            return StagedRenderSet(
                results={layer_id: rendered[layer_id][0] for layer_id in LAYER_IDS},
                paths=dict(temp_paths),
                _replacements=replacements,
            )
        except Exception:
            for path in temp_paths.values():
                _safe_unlink(path)
            raise

    def _render_audio(self, layer_id: LayerId, settings: AppSettings) -> _RenderedAudio:
        source_path = self._source_path(layer_id, settings)
        if not source_path.exists():
            msg = f"{layer_id} source file does not exist: {source_path}"
            raise FileNotFoundError(msg)

        target_frames = settings.audio.sample_rate * settings.audio.loop_seconds
        source = read_wav(source_path).to_canonical(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        source = source.to_frame_count(target_frames)
        layer_settings = settings.layers[layer_id]
        samples = _apply_playback_filters(source.samples, source.sample_rate, layer_settings)
        samples = _apply_three_band_eq(samples, source.sample_rate, layer_settings.eq)
        samples = _apply_gain(samples, layer_settings.volume_db)
        return _RenderedAudio(samples=samples, sample_rate=source.sample_rate)

    def _source_path(self, layer_id: LayerId, settings: AppSettings) -> Path:
        return render_source_path(self._paths, settings, layer_id)

    def _output_path(self, layer_id: LayerId) -> Path:
        if layer_id == "low":
            return self._paths.low_playback
        if layer_id == "mid":
            return self._paths.mid_playback
        return self._paths.voice_playback


def _validate_layer_id(layer_id: str) -> LayerId:
    if layer_id not in LAYER_IDS:
        msg = f"unknown layer id: {layer_id}"
        raise ValueError(msg)
    return layer_id  # type: ignore[return-value]


def _apply_playback_filters(
    samples: np.ndarray,
    sample_rate: int,
    layer_settings: LayerSettings,
) -> np.ndarray:
    filtered = _apply_filter(samples, sample_rate, layer_settings.eq.highpass_hz, "highpass")
    nyquist = sample_rate / 2
    if layer_settings.eq.lowpass_hz >= nyquist:
        return filtered
    return _apply_filter(filtered, sample_rate, layer_settings.eq.lowpass_hz, "lowpass")


def _apply_three_band_eq(samples: np.ndarray, sample_rate: int, eq: EqSettings) -> np.ndarray:
    if eq.low_gain_db == 0.0 and eq.mid_gain_db == 0.0 and eq.high_gain_db == 0.0:
        return samples.astype(np.float32, copy=True)

    low = _apply_filter(samples, sample_rate, _LOW_BAND_HZ, "lowpass")
    high = _apply_filter(samples, sample_rate, _HIGH_BAND_HZ, "highpass")
    mid = samples - low - high
    return (
        _apply_gain(low, eq.low_gain_db)
        + _apply_gain(mid, eq.mid_gain_db)
        + _apply_gain(high, eq.high_gain_db)
    ).astype(np.float32)


def _apply_filter(
    samples: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
    btype: str,
    order: int = 4,
) -> np.ndarray:
    _validate_cutoff(cutoff_hz, sample_rate)
    sos = butter(order, cutoff_hz, btype=btype, fs=sample_rate, output="sos")
    return sosfilt(sos, samples, axis=0).astype(np.float32)


def _validate_cutoff(cutoff_hz: float, sample_rate: int) -> None:
    nyquist = sample_rate / 2
    if not np.isfinite(cutoff_hz) or cutoff_hz <= 0 or cutoff_hz >= nyquist:
        msg = f"cutoff_hz must be greater than 0 and less than Nyquist ({nyquist})"
        raise ValueError(msg)


def _apply_gain(samples: np.ndarray, gain_db: float) -> np.ndarray:
    gain = 10 ** (gain_db / 20.0)
    return (samples.astype(np.float32, copy=False) * gain).astype(np.float32)


def _guard_rendered_buffer(
    layer_id: LayerId,
    output_path: Path,
    rendered_audio: _RenderedAudio,
    peak_ceiling: float,
) -> tuple[RenderResult, AudioBuffer]:
    peak_before = _peak(rendered_audio.samples)
    if peak_before > peak_ceiling:
        scale = peak_ceiling / peak_before
        guarded = AudioBuffer(
            samples=rendered_audio.samples * scale,
            sample_rate=rendered_audio.sample_rate,
        )
        peak_after = _peak(guarded.samples)
        gain_reduction_db = 20 * log10(peak_before / peak_after)
    else:
        guarded = AudioBuffer(
            samples=rendered_audio.samples,
            sample_rate=rendered_audio.sample_rate,
        )
        peak_after = peak_before
        gain_reduction_db = 0.0

    return (
        RenderResult(
            layer_id=layer_id,
            output_path=output_path,
            peak_before_guard=peak_before,
            peak_after_guard=peak_after,
            gain_reduction_db=gain_reduction_db,
        ),
        guarded,
    )


def _peak(samples: np.ndarray) -> float:
    if samples.shape[0] == 0:
        return 0.0
    return float(np.max(np.abs(samples)))


def _temp_render_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.stem}.{uuid4().hex}.tmp.wav")


def _backup_render_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.stem}.{uuid4().hex}.bak.wav")


def _commit_render_set(
    replacements: dict[LayerId, tuple[Path, Path]],
) -> tuple[list[tuple[Path, Path | None]], list[Path]]:
    committed: list[tuple[Path, Path | None]] = []
    moved_backups: list[tuple[Path, Path]] = []
    backups: list[Path] = []
    try:
        for layer_id in LAYER_IDS:
            temp_path, output_path = replacements[layer_id]
            backup_path: Path | None = None
            if output_path.exists():
                backup_path = _backup_render_path(output_path)
                _replace_file(output_path, backup_path)
                backups.append(backup_path)
                moved_backups.append((output_path, backup_path))
            _replace_file(temp_path, output_path)
            committed.append((output_path, backup_path))
    except Exception:
        _rollback_render_set(committed)
        _restore_uncommitted_backups(moved_backups, committed)
        for backup_path in backups:
            _safe_unlink(backup_path)
        raise
    return committed, backups


def _replace_render_set(replacements: dict[LayerId, tuple[Path, Path]]) -> None:
    _committed, backups = _commit_render_set(replacements)
    for backup_path in backups:
        _safe_unlink(backup_path)


def _rollback_render_set(committed: list[tuple[Path, Path | None]]) -> None:
    for output_path, backup_path in reversed(committed):
        if output_path.exists():
            output_path.unlink()
        if backup_path is not None and backup_path.exists():
            _replace_file(backup_path, output_path)


def _restore_uncommitted_backups(
    moved_backups: list[tuple[Path, Path]],
    committed: list[tuple[Path, Path | None]],
) -> None:
    committed_backup_paths = {backup_path for _output_path, backup_path in committed}
    for output_path, backup_path in reversed(moved_backups):
        if backup_path in committed_backup_paths:
            continue
        if output_path.exists():
            output_path.unlink()
        if backup_path.exists():
            _replace_file(backup_path, output_path)


def _replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


def _safe_unlink(path: Path) -> None:
    with suppress(OSError, FileNotFoundError):
        if path.exists():
            path.unlink()
