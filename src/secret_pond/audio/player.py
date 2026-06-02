from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
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
    if not np.isfinite(peak_ceiling) or peak_ceiling <= 0.0 or peak_ceiling > 1.0:
        msg = "peak_ceiling must be greater than 0 and less than or equal to 1"
        raise ValueError(msg)

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
