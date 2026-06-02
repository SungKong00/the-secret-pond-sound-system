from __future__ import annotations

from dataclasses import dataclass
from math import log10
from pathlib import Path
from uuid import uuid4

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.effects import apply_highpass, apply_lowpass
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.layers import LAYER_IDS, LayerId
from secret_pond.config import AppSettings, LayerSettings
from secret_pond.paths import ProjectPaths


@dataclass(frozen=True)
class RenderResult:
    layer_id: LayerId
    output_path: Path
    peak_before_guard: float
    peak_after_guard: float
    gain_reduction_db: float


class LayerRenderer:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def render_layer(self, layer_id: str, settings: AppSettings) -> RenderResult:
        normalized_layer_id = _validate_layer_id(layer_id)
        buffer = self._render_buffer(normalized_layer_id, settings)
        result, guarded = _guard_rendered_buffer(
            normalized_layer_id,
            self._output_path(normalized_layer_id),
            buffer,
            settings.audio.peak_ceiling,
        )
        write_wav_atomic(result.output_path, guarded)
        return result

    def render_all(self, settings: AppSettings) -> dict[LayerId, RenderResult]:
        self._paths.ensure_directories()
        rendered: dict[LayerId, tuple[RenderResult, AudioBuffer]] = {}
        temp_paths: dict[LayerId, Path] = {}
        try:
            for layer_id in LAYER_IDS:
                buffer = self._render_buffer(layer_id, settings)
                result, guarded = _guard_rendered_buffer(
                    layer_id,
                    self._output_path(layer_id),
                    buffer,
                    settings.audio.peak_ceiling,
                )
                temp_path = _temp_render_path(result.output_path)
                write_wav_atomic(temp_path, guarded)
                temp_paths[layer_id] = temp_path
                rendered[layer_id] = (result, guarded)

            _replace_render_set(
                {
                    layer_id: (temp_paths[layer_id], rendered[layer_id][0].output_path)
                    for layer_id in LAYER_IDS
                },
            )
        finally:
            for path in temp_paths.values():
                if path.exists():
                    path.unlink()

        return {layer_id: rendered[layer_id][0] for layer_id in LAYER_IDS}

    def _render_buffer(self, layer_id: LayerId, settings: AppSettings) -> AudioBuffer:
        source_path = self._source_path(layer_id)
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
        return _apply_playback_filters(source, layer_settings)

    def _source_path(self, layer_id: LayerId) -> Path:
        if layer_id == "low":
            return self._paths.low_source
        if layer_id == "mid":
            return self._paths.mid_source
        return self._paths.voice_stack_raw

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


def _apply_playback_filters(buffer: AudioBuffer, layer_settings: LayerSettings) -> AudioBuffer:
    filtered = apply_highpass(buffer, layer_settings.eq.highpass_hz)
    nyquist = filtered.sample_rate / 2
    if layer_settings.eq.lowpass_hz >= nyquist:
        return filtered
    return apply_lowpass(filtered, layer_settings.eq.lowpass_hz)


def _guard_rendered_buffer(
    layer_id: LayerId,
    output_path: Path,
    buffer: AudioBuffer,
    peak_ceiling: float,
) -> tuple[RenderResult, AudioBuffer]:
    peak_before = _peak(buffer.samples)
    if peak_before > peak_ceiling:
        scale = peak_ceiling / peak_before
        guarded = AudioBuffer(samples=buffer.samples * scale, sample_rate=buffer.sample_rate)
        peak_after = _peak(guarded.samples)
        gain_reduction_db = 20 * log10(peak_before / peak_after)
    else:
        guarded = buffer
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


def _replace_render_set(replacements: dict[LayerId, tuple[Path, Path]]) -> None:
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
        raise
    finally:
        for backup_path in backups:
            if backup_path.exists():
                backup_path.unlink()


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
