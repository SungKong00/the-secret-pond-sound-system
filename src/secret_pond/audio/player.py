from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav
from secret_pond.audio.layers import LAYER_IDS, LayerId
from secret_pond.config import EqSettings


@dataclass(frozen=True)
class LayerPlaybackState:
    enabled: bool = True
    realtime_trim_db: float = 0.0
    realtime_gain_ramp: RealtimeGainRampState | None = None
    realtime_mute_ramp: RealtimeMuteRampState | None = None


@dataclass(frozen=True)
class RealtimeGainRampState:
    from_gain_db: float
    to_gain_db: float
    duration_frames: int
    elapsed_frames: int = 0


@dataclass(frozen=True)
class RealtimeMuteRampState:
    from_gain: float
    to_gain: float
    duration_frames: int
    final_enabled: bool
    elapsed_frames: int = 0


@dataclass(frozen=True)
class MixerBlock:
    samples: np.ndarray
    next_frame_cursor: int
    peak_before_guard: float
    peak_after_guard: float


@dataclass(frozen=True)
class VoiceCrossfadeState:
    from_layers: dict[LayerId, AudioBuffer]
    to_layers: dict[LayerId, AudioBuffer]
    transition_layer_ids: frozenset[LayerId]
    duration_frames: int
    elapsed_frames: int
    transition_target_id: str
    from_frame_cursor: int = 0

    @property
    def from_buffer(self) -> AudioBuffer:
        return self.from_layers["voice"]

    @property
    def to_buffer(self) -> AudioBuffer:
        return self.to_layers["voice"]


@dataclass(frozen=True)
class QueuedVoiceTransitionState:
    to_layers: dict[LayerId, AudioBuffer]
    transition_layer_ids: frozenset[LayerId]
    duration_frames: int
    transition_target_id: str


@dataclass(frozen=True)
class SeekEnvelopeState:
    duration_frames: int
    elapsed_frames: int = 0


@dataclass(frozen=True)
class LayeredLoopPlayerSnapshot:
    layers: dict[LayerId, AudioBuffer] | None
    states: dict[LayerId, LayerPlaybackState]
    live_eq_states: dict[LayerId, EqSettings]
    frame_cursor: int
    playing: bool
    peak_ceiling: float
    voice_transition: VoiceCrossfadeState | None
    queued_voice_transition: QueuedVoiceTransitionState | None
    seek_envelope: SeekEnvelopeState | None
    active_voice_identity: str | None = None
    loop_frames: int | None = None


class LayeredLoopPlayer:
    def __init__(self, peak_ceiling: float = 0.98) -> None:
        _validate_peak_ceiling(peak_ceiling)
        self._layers: dict[LayerId, AudioBuffer] | None = None
        self._states: dict[LayerId, LayerPlaybackState] = {
            layer_id: LayerPlaybackState() for layer_id in LAYER_IDS
        }
        self._live_eq_states: dict[LayerId, EqSettings] = _default_live_eq_states()
        self._frame_cursor = 0
        self._playing = False
        self._peak_ceiling = peak_ceiling
        self._voice_transition: VoiceCrossfadeState | None = None
        self._queued_voice_transition: QueuedVoiceTransitionState | None = None
        self._seek_envelope: SeekEnvelopeState | None = None
        self._active_voice_identity: str | None = None
        self._loop_frames: int | None = None

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
    def live_eq_states(self) -> dict[LayerId, EqSettings]:
        return {
            layer_id: eq.model_copy(deep=True)
            for layer_id, eq in self._live_eq_states.items()
        }

    @property
    def rendered_cache_ready(self) -> bool:
        return self._layers is not None

    @property
    def active_voice_transition_target_id(self) -> str | None:
        if self._voice_transition is None:
            return None
        return self._voice_transition.transition_target_id

    @property
    def active_voice_identity(self) -> str | None:
        return self._active_voice_identity

    def snapshot(self) -> LayeredLoopPlayerSnapshot:
        return LayeredLoopPlayerSnapshot(
            layers=None if self._layers is None else dict(self._layers),
            states=dict(self._states),
            live_eq_states=self.live_eq_states,
            frame_cursor=self._frame_cursor,
            playing=self._playing,
            peak_ceiling=self._peak_ceiling,
            voice_transition=self._voice_transition,
            queued_voice_transition=self._queued_voice_transition,
            seek_envelope=self._seek_envelope,
            active_voice_identity=self._active_voice_identity,
            loop_frames=self._loop_frames,
        )

    def restore(self, snapshot: LayeredLoopPlayerSnapshot) -> None:
        self._layers = None if snapshot.layers is None else dict(snapshot.layers)
        self._states = dict(snapshot.states)
        self._live_eq_states = {
            layer_id: snapshot.live_eq_states.get(layer_id, EqSettings()).model_copy(deep=True)
            for layer_id in LAYER_IDS
        }
        self._frame_cursor = snapshot.frame_cursor
        self._playing = snapshot.playing
        self._peak_ceiling = snapshot.peak_ceiling
        self._voice_transition = snapshot.voice_transition
        self._queued_voice_transition = snapshot.queued_voice_transition
        self._seek_envelope = snapshot.seek_envelope
        self._active_voice_identity = snapshot.active_voice_identity
        self._loop_frames = snapshot.loop_frames

    def load_rendered_layers(self, paths: Mapping[LayerId, Path]) -> None:
        layers = _load_rendered_layers(paths)
        _validate_loaded_layers(layers)
        self._layers = layers
        self._live_eq_states = _default_live_eq_states()
        self._loop_frames = _default_loop_frames(layers)
        self._frame_cursor = 0
        self._playing = False
        self._voice_transition = None
        self._queued_voice_transition = None
        self._seek_envelope = None
        self._active_voice_identity = None

    def load_rendered_buffers(
        self,
        buffers: Mapping[LayerId, AudioBuffer],
        *,
        active_voice_identity: str | None = None,
        loop_frames: int | None = None,
    ) -> None:
        _validate_loaded_layers(buffers, loop_frames=loop_frames)
        layers = {layer_id: buffers[layer_id] for layer_id in LAYER_IDS}
        self._layers = layers
        self._loop_frames = _resolve_layer_loop_frames(layers, loop_frames)
        self._frame_cursor = 0
        self._playing = False
        self._voice_transition = None
        self._queued_voice_transition = None
        self._seek_envelope = None
        self._active_voice_identity = active_voice_identity

    def replace_rendered_buffers(self, buffers: Mapping[LayerId, AudioBuffer]) -> None:
        _validate_loaded_layers(buffers, loop_frames=self._loop_frames)
        layers = {layer_id: buffers[layer_id] for layer_id in LAYER_IDS}
        self._layers = layers
        self._loop_frames = _resolve_layer_loop_frames(layers, self._loop_frames)
        self._frame_cursor %= self._loop_frames
        self._voice_transition = None
        self._queued_voice_transition = None
        self._seek_envelope = None

    def set_layer_buffer(self, layer_id: str, buffer: AudioBuffer) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        layers = self._require_loaded()
        next_layers = dict(layers)
        next_buffer = buffer
        if (
            self._voice_transition is not None
            and normalized_layer_id in self._voice_transition.transition_layer_ids
        ):
            next_buffer = _canonical_layer_candidate(normalized_layer_id, buffer, layers)
            next_transition_layers = dict(self._voice_transition.to_layers)
            next_transition_layers[normalized_layer_id] = next_buffer
            _validate_loaded_layers(next_transition_layers, loop_frames=self._loop_frames)
            self._voice_transition = replace(
                self._voice_transition,
                to_layers=next_transition_layers,
            )
        next_layers[normalized_layer_id] = next_buffer
        _validate_loaded_layers(next_layers, loop_frames=self._loop_frames)
        self._layers = next_layers

    def set_live_eq_state(self, layer_id: str, eq: EqSettings) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        self._live_eq_states[normalized_layer_id] = eq.model_copy(deep=True)

    def reload_and_restart(self, paths: Mapping[LayerId, Path]) -> None:
        layers = _load_rendered_layers(paths)
        _validate_loaded_layers(layers)
        self._layers = layers
        self._live_eq_states = _default_live_eq_states()
        self._loop_frames = _default_loop_frames(layers)
        self._frame_cursor = 0
        self._playing = True
        self._voice_transition = None
        self._queued_voice_transition = None
        self._seek_envelope = None
        self._active_voice_identity = None

    def start_voice_crossfade(
        self,
        next_voice: AudioBuffer,
        *,
        duration_frames: int,
        transition_target_id: str,
        next_layers: Mapping[LayerId, AudioBuffer] | None = None,
    ) -> str | None:
        layers = self._require_loaded()
        if duration_frames <= 0:
            msg = "duration_frames must be greater than 0"
            raise ValueError(msg)
        if not transition_target_id:
            msg = "transition_target_id must be a non-empty string"
            raise ValueError(msg)

        candidate_layers = (
            _canonical_transition_layers(next_layers, layers)
            if next_layers is not None
            else dict(layers)
        )
        candidate_layers["voice"] = _canonical_voice_candidate(next_voice, layers)
        loop_frames = self._require_loop_frames()
        _validate_loaded_layers(candidate_layers, loop_frames=loop_frames)
        transition_layer_ids = frozenset(LAYER_IDS if next_layers is not None else ("voice",))
        superseded = self.active_voice_transition_target_id
        if self._voice_transition is not None:
            self._queued_voice_transition = QueuedVoiceTransitionState(
                to_layers={layer_id: candidate_layers[layer_id] for layer_id in LAYER_IDS},
                transition_layer_ids=transition_layer_ids,
                duration_frames=duration_frames,
                transition_target_id=transition_target_id,
            )
            return superseded
        self._voice_transition = VoiceCrossfadeState(
            from_layers={layer_id: layers[layer_id] for layer_id in LAYER_IDS},
            to_layers={layer_id: candidate_layers[layer_id] for layer_id in LAYER_IDS},
            transition_layer_ids=transition_layer_ids,
            duration_frames=duration_frames,
            elapsed_frames=0,
            transition_target_id=transition_target_id,
            from_frame_cursor=self._frame_cursor,
        )
        self._frame_cursor = 0
        self._seek_envelope = None
        return superseded

    def restart(self) -> None:
        self._require_loaded()
        self._frame_cursor = 0
        self._playing = True

    def seek(self, frame_cursor: int) -> None:
        layers = self._require_loaded()
        loop_frames = self._require_loop_frames()
        if not 0 <= frame_cursor < loop_frames:
            msg = "frame_cursor must be greater than or equal to 0 and less than the loop length"
            raise ValueError(msg)
        self._frame_cursor = frame_cursor
        self._seek_envelope = (
            _seek_envelope_for_layer(layers[LAYER_IDS[0]]) if self._playing else None
        )

    def start(self) -> None:
        self._require_loaded()
        self._playing = True

    def stop(self) -> None:
        self._playing = False

    def next_block(self, block_size: int) -> MixerBlock:
        layers = self._require_loaded()
        loop_frames = self._require_loop_frames()
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

        preserve_realtime_ramp_layers: frozenset[LayerId] = frozenset()
        if self._voice_transition is None:
            block = mix_layer_blocks(
                layers,
                self._states,
                frame_cursor=self._frame_cursor,
                block_size=block_size,
                loop_frames=loop_frames,
                peak_ceiling=self._peak_ceiling,
            )
            self._frame_cursor = block.next_frame_cursor
        else:
            block = mix_layer_blocks_with_voice_crossfade(
                layers,
                self._states,
                self._voice_transition,
                frame_cursor=self._frame_cursor,
                block_size=block_size,
                loop_frames=loop_frames,
                peak_ceiling=self._peak_ceiling,
            )
            preserve_realtime_ramp_layers = (
                self._voice_transition.transition_layer_ids | frozenset({"mid"})
            )
            elapsed_frames = self._voice_transition.elapsed_frames + block_size
            if elapsed_frames >= self._voice_transition.duration_frames:
                transition_target_id = self._voice_transition.transition_target_id
                current_layers = dict(layers)
                try:
                    for layer_id in LAYER_IDS:
                        if layer_id not in self._voice_transition.transition_layer_ids:
                            continue
                        layers[layer_id] = self._voice_transition.to_layers[layer_id]
                except Exception:
                    for layer_id, buffer in current_layers.items():
                        try:
                            layers[layer_id] = buffer
                        except Exception:
                            pass
                    self._voice_transition = None
                    block = mix_layer_blocks(
                        layers,
                        self._states,
                        frame_cursor=self._frame_cursor,
                        block_size=block_size,
                        loop_frames=loop_frames,
                        peak_ceiling=self._peak_ceiling,
                    )
                    self._frame_cursor = block.next_frame_cursor
                else:
                    self._active_voice_identity = transition_target_id
                    self._voice_transition = None
                    self._frame_cursor = block.next_frame_cursor
                    self._promote_queued_voice_transition()
            else:
                self._voice_transition = replace(
                    self._voice_transition,
                    elapsed_frames=elapsed_frames,
                )
                self._frame_cursor = block.next_frame_cursor
        if self._seek_envelope is not None:
            block = _apply_seek_envelope(block, self._seek_envelope)
            elapsed_frames = self._seek_envelope.elapsed_frames + block_size
            if elapsed_frames >= self._seek_envelope.duration_frames:
                self._seek_envelope = None
            else:
                self._seek_envelope = replace(
                    self._seek_envelope,
                    elapsed_frames=elapsed_frames,
                )
        self._advance_realtime_gain_ramps(
            block_size,
            preserve_layer_ids=preserve_realtime_ramp_layers,
        )
        return block

    def _promote_queued_voice_transition(self) -> None:
        queued = self._queued_voice_transition
        if queued is None:
            return
        layers = self._require_loaded()
        self._voice_transition = VoiceCrossfadeState(
            from_layers={layer_id: layers[layer_id] for layer_id in LAYER_IDS},
            to_layers={layer_id: queued.to_layers[layer_id] for layer_id in LAYER_IDS},
            transition_layer_ids=queued.transition_layer_ids,
            duration_frames=queued.duration_frames,
            elapsed_frames=0,
            transition_target_id=queued.transition_target_id,
            from_frame_cursor=self._frame_cursor,
        )
        self._queued_voice_transition = None
        self._frame_cursor = 0
        self._seek_envelope = None

    def set_enabled(self, layer_id: str, enabled: bool) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        current = self._states[normalized_layer_id]
        ramp = self._realtime_mute_ramp(
            normalized_layer_id,
            current=current,
            enabled=enabled,
        )
        if ramp is None:
            next_enabled = enabled
        else:
            next_enabled = True
        self._states[normalized_layer_id] = LayerPlaybackState(
            enabled=next_enabled,
            realtime_trim_db=current.realtime_trim_db,
            realtime_gain_ramp=current.realtime_gain_ramp,
            realtime_mute_ramp=ramp,
        )

    def set_enabled_immediate(self, layer_id: str, enabled: bool) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        current = self._states[normalized_layer_id]
        self._states[normalized_layer_id] = LayerPlaybackState(
            enabled=enabled,
            realtime_trim_db=current.realtime_trim_db,
            realtime_gain_ramp=current.realtime_gain_ramp,
        )

    def set_realtime_trim(self, layer_id: str, realtime_trim_db: float) -> None:
        normalized_layer_id = _validate_layer_id(layer_id)
        current = self._states[normalized_layer_id]
        ramp = self._realtime_gain_ramp(
            normalized_layer_id,
            from_gain_db=current.realtime_trim_db,
            to_gain_db=realtime_trim_db,
        )
        self._states[normalized_layer_id] = LayerPlaybackState(
            enabled=current.enabled,
            realtime_trim_db=realtime_trim_db,
            realtime_gain_ramp=ramp,
            realtime_mute_ramp=current.realtime_mute_ramp,
        )

    def set_peak_ceiling(self, peak_ceiling: float) -> None:
        _validate_peak_ceiling(peak_ceiling)
        self._peak_ceiling = peak_ceiling

    def _require_loaded(self) -> dict[LayerId, AudioBuffer]:
        if self._layers is None:
            msg = "rendered layers must be loaded before playback"
            raise ValueError(msg)
        return self._layers

    def _require_loop_frames(self) -> int:
        if self._loop_frames is None:
            layers = self._require_loaded()
            self._loop_frames = _default_loop_frames(layers)
        return self._loop_frames

    def _realtime_gain_ramp(
        self,
        layer_id: LayerId,
        *,
        from_gain_db: float,
        to_gain_db: float,
    ) -> RealtimeGainRampState | None:
        if from_gain_db == to_gain_db or not self._playing or self._layers is None:
            return None
        duration_frames = _short_ramp_frames(self._layers[layer_id])
        return RealtimeGainRampState(
            from_gain_db=from_gain_db,
            to_gain_db=to_gain_db,
            duration_frames=duration_frames,
        )

    def _realtime_mute_ramp(
        self,
        layer_id: LayerId,
        *,
        current: LayerPlaybackState,
        enabled: bool,
    ) -> RealtimeMuteRampState | None:
        if current.enabled == enabled and current.realtime_mute_ramp is None:
            return None
        if not self._playing or self._layers is None:
            return None

        current_gain = _current_mute_gain(current)
        target_gain = 1.0 if enabled else 0.0
        if current_gain == target_gain:
            return None
        return RealtimeMuteRampState(
            from_gain=current_gain,
            to_gain=target_gain,
            duration_frames=_short_ramp_frames(self._layers[layer_id]),
            final_enabled=enabled,
        )

    def _advance_realtime_gain_ramps(
        self,
        block_size: int,
        *,
        preserve_layer_ids: frozenset[LayerId] = frozenset(),
    ) -> None:
        next_states: dict[LayerId, LayerPlaybackState] = {}
        changed = False
        for layer_id, state in self._states.items():
            if layer_id in preserve_layer_ids:
                next_states[layer_id] = state
                continue
            gain_ramp = state.realtime_gain_ramp
            mute_ramp = state.realtime_mute_ramp
            if gain_ramp is None and mute_ramp is None:
                next_states[layer_id] = state
                continue

            next_gain_ramp: RealtimeGainRampState | None = None
            if gain_ramp is not None:
                elapsed_frames = gain_ramp.elapsed_frames + block_size
                if elapsed_frames < gain_ramp.duration_frames:
                    next_gain_ramp = replace(gain_ramp, elapsed_frames=elapsed_frames)

            next_enabled = state.enabled
            next_mute_ramp: RealtimeMuteRampState | None = None
            if mute_ramp is not None:
                elapsed_frames = mute_ramp.elapsed_frames + block_size
                if elapsed_frames >= mute_ramp.duration_frames:
                    next_enabled = mute_ramp.final_enabled
                else:
                    next_mute_ramp = replace(mute_ramp, elapsed_frames=elapsed_frames)

            if next_gain_ramp is None and next_mute_ramp is None:
                next_states[layer_id] = LayerPlaybackState(
                    enabled=next_enabled,
                    realtime_trim_db=state.realtime_trim_db,
                )
            else:
                next_states[layer_id] = LayerPlaybackState(
                    enabled=next_enabled,
                    realtime_trim_db=state.realtime_trim_db,
                    realtime_gain_ramp=next_gain_ramp,
                    realtime_mute_ramp=next_mute_ramp,
                )
            changed = True
        if changed:
            self._states = next_states


def mix_layer_blocks(
    layers: Mapping[LayerId, AudioBuffer],
    states: Mapping[LayerId, LayerPlaybackState],
    frame_cursor: int,
    block_size: int,
    peak_ceiling: float = 0.98,
    loop_frames: int | None = None,
) -> MixerBlock:
    cycle_frames = _validate_mix_inputs(
        layers,
        frame_cursor,
        block_size,
        peak_ceiling,
        loop_frames=loop_frames,
    )
    first_layer = layers[LAYER_IDS[0]]
    mixed = np.zeros((block_size, first_layer.channels), dtype=np.float32)

    for layer_id in LAYER_IDS:
        state = states.get(layer_id, LayerPlaybackState())
        if not state.enabled:
            continue

        layer_block = _read_wrapped(
            layers[layer_id].samples,
            frame_cursor,
            block_size,
            loop_frames=cycle_frames,
        )
        mixed += _apply_realtime_gain(layer_block, state)

    peak_before = _peak(mixed)
    guarded = _guard_peak(mixed, peak_before, peak_ceiling)
    peak_after = _peak(guarded)
    next_cursor = (frame_cursor + block_size) % cycle_frames
    return MixerBlock(
        samples=guarded,
        next_frame_cursor=next_cursor,
        peak_before_guard=peak_before,
        peak_after_guard=peak_after,
    )


def mix_layer_blocks_with_voice_crossfade(
    layers: Mapping[LayerId, AudioBuffer],
    states: Mapping[LayerId, LayerPlaybackState],
    voice_transition: VoiceCrossfadeState,
    frame_cursor: int,
    block_size: int,
    peak_ceiling: float = 0.98,
    loop_frames: int | None = None,
) -> MixerBlock:
    cycle_frames = _validate_mix_inputs(
        layers,
        frame_cursor,
        block_size,
        peak_ceiling,
        loop_frames=loop_frames,
    )
    _validate_mix_inputs(
        voice_transition.from_layers,
        voice_transition.from_frame_cursor,
        block_size,
        peak_ceiling,
        loop_frames=cycle_frames,
    )
    _validate_mix_inputs(
        voice_transition.to_layers,
        frame_cursor,
        block_size,
        peak_ceiling,
        loop_frames=cycle_frames,
    )
    first_layer = layers[LAYER_IDS[0]]
    mixed = np.zeros((block_size, first_layer.channels), dtype=np.float32)

    progress = np.clip(
        (voice_transition.elapsed_frames + np.arange(block_size, dtype=np.float32))
        / voice_transition.duration_frames,
        0.0,
        1.0,
    )
    from_gain, to_gain = _equal_power_crossfade_gains(progress)
    from_gain = from_gain[:, np.newaxis]
    to_gain = to_gain[:, np.newaxis]

    for layer_id in LAYER_IDS:
        state = states.get(layer_id, LayerPlaybackState())
        if not state.enabled:
            continue
        if layer_id not in voice_transition.transition_layer_ids:
            layer_block = _read_wrapped(
                layers[layer_id].samples,
                frame_cursor,
                block_size,
                loop_frames=cycle_frames,
            )
            mixed += _apply_realtime_gain(layer_block, state)
            continue
        from_frame_cursor = (
            voice_transition.from_frame_cursor + voice_transition.elapsed_frames
        ) % cycle_frames
        from_block = _read_wrapped(
            voice_transition.from_layers[layer_id].samples,
            from_frame_cursor,
            block_size,
            loop_frames=cycle_frames,
        )
        to_block = _read_wrapped(
            voice_transition.to_layers[layer_id].samples,
            frame_cursor,
            block_size,
            loop_frames=cycle_frames,
        )
        layer_block = (from_block * from_gain + to_block * to_gain).astype(np.float32)
        mixed += _apply_realtime_gain(layer_block, state)

    peak_before = _peak(mixed)
    guarded = _guard_peak(mixed, peak_before, peak_ceiling)
    peak_after = _peak(guarded)
    next_cursor = (frame_cursor + block_size) % cycle_frames
    return MixerBlock(
        samples=guarded,
        next_frame_cursor=next_cursor,
        peak_before_guard=peak_before,
        peak_after_guard=peak_after,
    )


def _canonical_voice_candidate(
    next_voice: AudioBuffer,
    layers: Mapping[LayerId, AudioBuffer],
) -> AudioBuffer:
    return _canonical_layer_candidate("voice", next_voice, layers)


def _canonical_transition_layers(
    next_layers: Mapping[LayerId, AudioBuffer],
    layers: Mapping[LayerId, AudioBuffer],
) -> dict[LayerId, AudioBuffer]:
    missing = [layer_id for layer_id in LAYER_IDS if layer_id not in next_layers]
    if missing:
        msg = f"missing transition layer buffers: {', '.join(missing)}"
        raise ValueError(msg)
    candidates = {
        layer_id: _canonical_layer_candidate(layer_id, next_layers[layer_id], layers)
        for layer_id in LAYER_IDS
    }
    _validate_loaded_layers(candidates)
    return candidates


def _canonical_layer_candidate(
    layer_id: LayerId,
    next_buffer: AudioBuffer,
    layers: Mapping[LayerId, AudioBuffer],
) -> AudioBuffer:
    current_layer = layers[layer_id]
    candidate = next_buffer.to_canonical(
        sample_rate=current_layer.sample_rate,
        channels=current_layer.channels,
    ).to_frame_count(current_layer.frames)
    candidate_layers = dict(layers)
    candidate_layers[layer_id] = candidate
    _validate_loaded_layers(candidate_layers)
    return candidate


def _seek_envelope_for_layer(layer: AudioBuffer) -> SeekEnvelopeState:
    duration_frames = _short_ramp_frames(layer)
    return SeekEnvelopeState(duration_frames=duration_frames)


def _short_ramp_frames(layer: AudioBuffer) -> int:
    return max(1, min(layer.frames, layer.sample_rate // 200))


def _apply_seek_envelope(block: MixerBlock, seek_envelope: SeekEnvelopeState) -> MixerBlock:
    frame_offsets = seek_envelope.elapsed_frames + np.arange(
        block.samples.shape[0],
        dtype=np.float32,
    )
    gains = np.clip(frame_offsets / seek_envelope.duration_frames, 0.0, 1.0)[:, np.newaxis]
    samples = (block.samples * gains).astype(np.float32)
    peak_after = _peak(samples)
    return MixerBlock(
        samples=samples,
        next_frame_cursor=block.next_frame_cursor,
        peak_before_guard=block.peak_before_guard,
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


def _default_live_eq_states() -> dict[LayerId, EqSettings]:
    return {layer_id: EqSettings() for layer_id in LAYER_IDS}


def _validate_loaded_layers(
    layers: Mapping[LayerId, AudioBuffer],
    *,
    loop_frames: int | None = None,
) -> None:
    _validate_mix_inputs(
        layers,
        frame_cursor=0,
        block_size=1,
        peak_ceiling=0.98,
        loop_frames=loop_frames,
    )


def _default_loop_frames(layers: Mapping[LayerId, AudioBuffer]) -> int:
    return _resolve_layer_loop_frames(layers, None)


def _resolve_layer_loop_frames(
    layers: Mapping[LayerId, AudioBuffer],
    loop_frames: int | None,
) -> int:
    if loop_frames is not None:
        if loop_frames <= 0:
            msg = "loop_frames must be greater than 0"
            raise ValueError(msg)
        return loop_frames
    return layers[LAYER_IDS[0]].frames


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
    *,
    loop_frames: int | None = None,
) -> int:
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
    cycle_frames = first.frames if loop_frames is None else loop_frames
    if cycle_frames <= 0:
        msg = "loop_frames must be greater than 0"
        raise ValueError(msg)
    if not 0 <= frame_cursor < cycle_frames:
        msg = "frame_cursor must be greater than or equal to 0 and less than the loop length"
        raise ValueError(msg)

    for layer_id in LAYER_IDS[1:]:
        layer = layers[layer_id]
        if layer.frames <= 0:
            msg = "layer buffers must contain at least one frame"
            raise ValueError(msg)
        if layer.sample_rate != first.sample_rate:
            msg = "all layer buffers must have the same sample rate"
            raise ValueError(msg)
        if layer.channels != first.channels:
            msg = "all layer buffers must have the same channel count"
            raise ValueError(msg)
        if loop_frames is None and layer.frames != first.frames:
            msg = "all layer buffers must have the same frame count"
            raise ValueError(msg)
    return cycle_frames


def _read_wrapped(
    samples: np.ndarray,
    frame_cursor: int,
    block_size: int,
    *,
    loop_frames: int | None = None,
) -> np.ndarray:
    source_frames = samples.shape[0]
    cycle_frames = source_frames if loop_frames is None else loop_frames
    cycle_indices = (np.arange(block_size) + frame_cursor) % cycle_frames
    indices = cycle_indices % source_frames
    return samples[indices].astype(np.float32, copy=True)


def _apply_gain(samples: np.ndarray, gain_db: float) -> np.ndarray:
    gain = 10 ** (gain_db / 20.0)
    return (samples * gain).astype(np.float32)


def _apply_realtime_gain(samples: np.ndarray, state: LayerPlaybackState) -> np.ndarray:
    if state.realtime_gain_ramp is None:
        gained = _apply_gain(samples, state.realtime_trim_db)
    else:
        gained = _apply_gain_ramp(samples, state.realtime_gain_ramp)
    if state.realtime_mute_ramp is None:
        return gained
    return _apply_mute_ramp(gained, state.realtime_mute_ramp)


def _apply_gain_ramp(samples: np.ndarray, ramp: RealtimeGainRampState) -> np.ndarray:
    from_gain = _db_to_gain(ramp.from_gain_db)
    to_gain = _db_to_gain(ramp.to_gain_db)
    frame_offsets = ramp.elapsed_frames + np.arange(samples.shape[0], dtype=np.float32)
    progress = np.clip(frame_offsets / ramp.duration_frames, 0.0, 1.0)
    gains = from_gain + ((to_gain - from_gain) * progress)
    return (samples * gains[:, np.newaxis]).astype(np.float32)


def _apply_mute_ramp(samples: np.ndarray, ramp: RealtimeMuteRampState) -> np.ndarray:
    frame_offsets = ramp.elapsed_frames + np.arange(samples.shape[0], dtype=np.float32)
    progress = np.clip(frame_offsets / ramp.duration_frames, 0.0, 1.0)
    gains = ramp.from_gain + ((ramp.to_gain - ramp.from_gain) * progress)
    return (samples * gains[:, np.newaxis]).astype(np.float32)


def _equal_power_crossfade_gains(progress: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    clipped = np.clip(progress, 0.0, 1.0)
    return (
        np.cos(clipped * np.pi / 2.0).astype(np.float32),
        np.sin(clipped * np.pi / 2.0).astype(np.float32),
    )


def _current_mute_gain(state: LayerPlaybackState) -> float:
    ramp = state.realtime_mute_ramp
    if ramp is None:
        return 1.0 if state.enabled else 0.0
    progress = min(1.0, ramp.elapsed_frames / ramp.duration_frames)
    return ramp.from_gain + ((ramp.to_gain - ramp.from_gain) * progress)


def _db_to_gain(gain_db: float) -> float:
    return 10 ** (gain_db / 20.0)


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
