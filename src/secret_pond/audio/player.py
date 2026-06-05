from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav
from secret_pond.audio.layers import LAYER_IDS, LayerId


@dataclass(frozen=True)
class LayerPlaybackState:
    enabled: bool = True
    realtime_trim_db: float = 0.0


@dataclass(frozen=True)
class MixerBlock:
    samples: np.ndarray
    next_frame_cursor: int
    peak_before_guard: float
    peak_after_guard: float


@dataclass(frozen=True)
class LayeredLoopPlayerSnapshot:
    layers: dict[LayerId, AudioBuffer] | None
    states: dict[LayerId, LayerPlaybackState]
    frame_cursor: int
    playing: bool
    peak_ceiling: float


class LayeredLoopPlayer:
    def __init__(self, peak_ceiling: float = 0.98) -> None:
        _validate_peak_ceiling(peak_ceiling)
        self._layers: dict[LayerId, AudioBuffer] | None = None
        self._states: dict[LayerId, LayerPlaybackState] = {
            layer_id: LayerPlaybackState() for layer_id in LAYER_IDS
        }
        self._frame_cursor = 0
        self._playing = False
        self._peak_ceiling = peak_ceiling

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def frame_cursor(self) -> int:
        return self._frame_cursor

    @property
    def layer_states(self) -> dict[LayerId, LayerPlaybackState]:
        return dict(self._states)

    @property
    def rendered_cache_ready(self) -> bool:
        return self._layers is not None

    def snapshot(self) -> LayeredLoopPlayerSnapshot:
        return LayeredLoopPlayerSnapshot(
            layers=None if self._layers is None else dict(self._layers),
            states=dict(self._states),
            frame_cursor=self._frame_cursor,
            playing=self._playing,
            peak_ceiling=self._peak_ceiling,
        )

    def restore(self, snapshot: LayeredLoopPlayerSnapshot) -> None:
        self._layers = None if snapshot.layers is None else dict(snapshot.layers)
        self._states = dict(snapshot.states)
        self._frame_cursor = snapshot.frame_cursor
        self._playing = snapshot.playing
        self._peak_ceiling = snapshot.peak_ceiling

    def load_rendered_layers(self, paths: Mapping[LayerId, Path]) -> None:
        layers = _load_rendered_layers(paths)
        _validate_loaded_layers(layers)
        self._layers = layers
        self._frame_cursor = 0
        self._playing = False

    def load_rendered_buffers(self, buffers: Mapping[LayerId, AudioBuffer]) -> None:
        layers = {layer_id: buffers[layer_id] for layer_id in LAYER_IDS}
        _validate_loaded_layers(layers)
        self._layers = layers
        self._frame_cursor = 0
        self._playing = False

    def reload_and_restart(self, paths: Mapping[LayerId, Path]) -> None:
        layers = _load_rendered_layers(paths)
        _validate_loaded_layers(layers)
        self._layers = layers
        self._frame_cursor = 0
        self._playing = True

    def restart(self) -> None:
        self._require_loaded()
        self._frame_cursor = 0
        self._playing = True

    def start(self) -> None:
        self._require_loaded()
        self._playing = True

    def stop(self) -> None:
        self._playing = False

    def next_block(self, block_size: int) -> MixerBlock:
        layers = self._require_loaded()
        if block_size <= 0:
            msg = "block_size must be greater than 0"
            raise ValueError(msg)
        if not self._playing:
            return MixerBlock(
                samples=np.zeros((block_size, _channel_count(layers)), dtype=np.float32),
                next_frame_cursor=self._frame_cursor,
                peak_before_guard=0.0,
                peak_after_guard=0.0,
            )

        block = mix_layer_blocks(
            layers,
            self._states,
            frame_cursor=self._frame_cursor,
            block_size=block_size,
            peak_ceiling=self._peak_ceiling,
        )
        self._frame_cursor = block.next_frame_cursor
        return block

    def set_enabled(self, layer_id: str, enabled: bool) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        current = self._states[normalized_layer_id]
        self._states[normalized_layer_id] = LayerPlaybackState(
            enabled=enabled,
            realtime_trim_db=current.realtime_trim_db,
        )

    def set_realtime_trim(self, layer_id: str, realtime_trim_db: float) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        current = self._states[normalized_layer_id]
        self._states[normalized_layer_id] = LayerPlaybackState(
            enabled=current.enabled,
            realtime_trim_db=realtime_trim_db,
        )

    def set_peak_ceiling(self, peak_ceiling: float) -> None:
        _validate_peak_ceiling(peak_ceiling)
        self._peak_ceiling = peak_ceiling

    def _require_loaded(self) -> dict[LayerId, AudioBuffer]:
        if self._layers is None:
            msg = "rendered layers must be loaded before playback"
            raise ValueError(msg)
        return self._layers


def mix_layer_blocks(
    layers: Mapping[LayerId, AudioBuffer],
    states: Mapping[LayerId, LayerPlaybackState],
    frame_cursor: int,
    block_size: int,
    peak_ceiling: float = 0.98,
) -> MixerBlock:
    _validate_mix_inputs(layers, frame_cursor, block_size, peak_ceiling)
    first_layer = layers[LAYER_IDS[0]]
    mixed = np.zeros((block_size, first_layer.channels), dtype=np.float32)

    for layer_id in LAYER_IDS:
        state = states.get(layer_id, LayerPlaybackState())
        if not state.enabled:
            continue

        layer_block = _read_wrapped(layers[layer_id].samples, frame_cursor, block_size)
        mixed += _apply_gain(layer_block, state.realtime_trim_db)

    peak_before = _peak(mixed)
    guarded = _guard_peak(mixed, peak_before, peak_ceiling)
    peak_after = _peak(guarded)
    next_cursor = (frame_cursor + block_size) % first_layer.frames
    return MixerBlock(
        samples=guarded,
        next_frame_cursor=next_cursor,
        peak_before_guard=peak_before,
        peak_after_guard=peak_after,
    )


def _load_rendered_layers(paths: Mapping[LayerId, Path]) -> dict[LayerId, AudioBuffer]:
    missing = [layer_id for layer_id in LAYER_IDS if layer_id not in paths]
    if missing:
        msg = f"missing rendered layer paths: {', '.join(missing)}"
        raise ValueError(msg)
    missing_files = [layer_id for layer_id in LAYER_IDS if not paths[layer_id].exists()]
    if missing_files:
        msg = f"missing rendered layer files: {', '.join(missing_files)}"
        raise FileNotFoundError(msg)
    return {layer_id: read_wav(paths[layer_id]) for layer_id in LAYER_IDS}


def _validate_loaded_layers(layers: Mapping[LayerId, AudioBuffer]) -> None:
    _validate_mix_inputs(layers, frame_cursor=0, block_size=1, peak_ceiling=0.98)


def _channel_count(layers: Mapping[LayerId, AudioBuffer]) -> int:
    return layers[LAYER_IDS[0]].channels


def _validate_layer_id(layer_id: str) -> LayerId:
    if layer_id not in LAYER_IDS:
        msg = f"unknown layer id: {layer_id}"
        raise ValueError(msg)
    return layer_id  # type: ignore[return-value]


def _validate_mix_inputs(
    layers: Mapping[LayerId, AudioBuffer],
    frame_cursor: int,
    block_size: int,
    peak_ceiling: float,
) -> None:
    missing = [layer_id for layer_id in LAYER_IDS if layer_id not in layers]
    if missing:
        msg = f"missing rendered layer buffers: {', '.join(missing)}"
        raise ValueError(msg)
    if block_size <= 0:
        msg = "block_size must be greater than 0"
        raise ValueError(msg)
    _validate_peak_ceiling(peak_ceiling)

    first = layers[LAYER_IDS[0]]
    if first.frames <= 0:
        msg = "layer buffers must contain at least one frame"
        raise ValueError(msg)
    if not 0 <= frame_cursor < first.frames:
        msg = "frame_cursor must be greater than or equal to 0 and less than the loop length"
        raise ValueError(msg)

    for layer_id in LAYER_IDS[1:]:
        layer = layers[layer_id]
        if layer.sample_rate != first.sample_rate:
            msg = "all layer buffers must have the same sample rate"
            raise ValueError(msg)
        if layer.channels != first.channels:
            msg = "all layer buffers must have the same channel count"
            raise ValueError(msg)
        if layer.frames != first.frames:
            msg = "all layer buffers must have the same frame count"
            raise ValueError(msg)


def _read_wrapped(samples: np.ndarray, frame_cursor: int, block_size: int) -> np.ndarray:
    loop_frames = samples.shape[0]
    indices = (np.arange(block_size) + frame_cursor) % loop_frames
    return samples[indices].astype(np.float32, copy=True)


def _apply_gain(samples: np.ndarray, gain_db: float) -> np.ndarray:
    gain = 10 ** (gain_db / 20.0)
    return (samples * gain).astype(np.float32)


def _guard_peak(samples: np.ndarray, peak: float, peak_ceiling: float) -> np.ndarray:
    if peak <= peak_ceiling:
        return samples.astype(np.float32, copy=True)
    return (samples * (peak_ceiling / peak)).astype(np.float32)


def _peak(samples: np.ndarray) -> float:
    if samples.shape[0] == 0:
        return 0.0
    return float(np.max(np.abs(samples)))


def _validate_peak_ceiling(peak_ceiling: float) -> None:
    if not np.isfinite(peak_ceiling) or peak_ceiling <= 0.0 or peak_ceiling > 1.0:
        msg = "peak_ceiling must be greater than 0 and less than or equal to 1"
        raise ValueError(msg)
