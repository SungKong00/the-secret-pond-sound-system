from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.player import LayeredLoopPlayer, _equal_power_crossfade_gains
from secret_pond.config import EqSettings


def stereo(value: float, frames: int = 4, sample_rate: int = 8_000) -> AudioBuffer:
    return AudioBuffer(
        samples=np.ones((frames, 2), dtype=np.float32) * value,
        sample_rate=sample_rate,
    )


def write_layers(root: Path, low: float, mid: float, voice: float, frames: int = 4) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "low": root / "low_playback.wav",
        "mid": root / "mid_playback.wav",
        "voice": root / "voice_playback.wav",
    }
    write_wav_atomic(paths["low"], stereo(low, frames=frames))
    write_wav_atomic(paths["mid"], stereo(mid, frames=frames))
    write_wav_atomic(paths["voice"], stereo(voice, frames=frames))
    return paths


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


class FailingVoiceActivationDict(dict):
    def __setitem__(self, key, value):
        if key == "voice":
            raise RuntimeError("voice activation failed")
        super().__setitem__(key, value)


def test_equal_power_voice_crossfade_gains_preserve_midpoint_and_endpoints() -> None:
    progress = np.array([0.0, 0.5, 1.0], dtype=np.float32)

    from_gain, to_gain = _equal_power_crossfade_gains(progress)

    np.testing.assert_allclose(from_gain, [1.0, np.sqrt(0.5), 0.0], atol=1e-6)
    np.testing.assert_allclose(to_gain, [0.0, np.sqrt(0.5), 1.0], atol=1e-6)


def test_player_loads_layers_into_memory_and_releases_files(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3)
    player = LayeredLoopPlayer()

    player.load_rendered_layers(paths)
    write_wav_atomic(paths["low"], stereo(0.9))

    player.start()
    block = player.next_block(4)

    np.testing.assert_allclose(block.samples, np.ones((4, 2), dtype=np.float32) * 0.6, atol=1e-6)
    assert read_wav(paths["low"]).samples[0, 0] == pytest.approx(0.9, abs=1e-4)


def test_player_start_and_next_block_advances_cursor(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)

    player.start()
    block = player.next_block(3)

    assert player.is_playing is True
    assert block.next_frame_cursor == 3
    assert player.frame_cursor == 3
    np.testing.assert_allclose(block.samples, np.ones((3, 2), dtype=np.float32) * 0.6, atol=1e-6)


def test_player_set_layer_buffer_preserves_cursor_for_next_block() -> None:
    low = np.column_stack(
        [
            np.arange(10, dtype=np.float32) / 100,
            np.arange(10, dtype=np.float32) / 100,
        ],
    )
    updated_low = np.column_stack(
        [
            np.arange(40, 50, dtype=np.float32) / 100,
            np.arange(40, 50, dtype=np.float32) / 100,
        ],
    )
    silence = np.zeros((10, 2), dtype=np.float32)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=low, sample_rate=8_000),
            "mid": AudioBuffer(samples=silence, sample_rate=8_000),
            "voice": AudioBuffer(samples=silence, sample_rate=8_000),
        },
        loop_frames=10,
    )
    player.start()
    player.next_block(4)

    player.set_layer_buffer(
        "low",
        AudioBuffer(samples=updated_low, sample_rate=8_000),
    )
    block = player.next_block(3)

    assert player.frame_cursor == 7
    assert block.next_frame_cursor == 7
    np.testing.assert_allclose(block.samples[:, 0], [0.44, 0.45, 0.46], atol=1e-6)


def test_player_first_start_reads_loaded_layers_from_frame_zero() -> None:
    low = np.column_stack(
        [
            np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06], dtype=np.float32),
            np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06], dtype=np.float32),
        ],
    )
    mid = np.column_stack(
        [
            np.array([0.10, 0.20, 0.30, 0.40, 0.50, 0.60], dtype=np.float32),
            np.array([0.10, 0.20, 0.30, 0.40, 0.50, 0.60], dtype=np.float32),
        ],
    )
    voice = np.column_stack(
        [
            np.array([0.001, 0.002, 0.003, 0.004, 0.005, 0.006], dtype=np.float32),
            np.array([0.001, 0.002, 0.003, 0.004, 0.005, 0.006], dtype=np.float32),
        ],
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=low, sample_rate=8_000),
            "mid": AudioBuffer(samples=mid, sample_rate=8_000),
            "voice": AudioBuffer(samples=voice, sample_rate=8_000),
        },
    )

    player.start()
    block = player.next_block(3)

    expected = low[:3] + mid[:3] + voice[:3]
    assert player.frame_cursor == 3
    assert block.next_frame_cursor == 3
    np.testing.assert_allclose(block.samples, expected, atol=1e-6)


def test_player_crossfades_loop_tail_into_next_loop_head_after_first_cycle() -> None:
    low = np.column_stack(
        [
            np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32),
            np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32),
        ],
    )
    silence = np.zeros((6, 2), dtype=np.float32)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=low, sample_rate=8_000),
            "mid": AudioBuffer(samples=silence, sample_rate=8_000),
            "voice": AudioBuffer(samples=silence, sample_rate=8_000),
        },
        loop_frames=6,
        loop_transition_frames=2,
    )

    player.start()
    first_cycle_head = player.next_block(4)
    transition = player.next_block(2)
    after_transition = player.next_block(2)

    np.testing.assert_allclose(first_cycle_head.samples[:, 0], [0.0, 0.1, 0.2, 0.3], atol=1e-6)
    np.testing.assert_allclose(
        transition.samples[:, 0],
        [0.4, 0.1],
        atol=1e-6,
    )
    np.testing.assert_allclose(after_transition.samples[:, 0], [0.2, 0.3], atol=1e-6)
    assert player.frame_cursor == 4


def test_player_configured_loop_transition_does_not_fade_normal_head_frames() -> None:
    loop_frames = 100
    source_frames = 120
    samples = np.zeros(source_frames, dtype=np.float32)
    samples[:40] = 0.5
    samples[loop_frames - 40 : loop_frames] = -0.5
    layer = AudioBuffer(
        samples=np.column_stack([samples, samples]),
        sample_rate=8_000,
    )
    silence = AudioBuffer(
        samples=np.zeros((source_frames, 2), dtype=np.float32),
        sample_rate=8_000,
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": layer,
            "mid": silence,
            "voice": silence,
        },
        loop_frames=loop_frames,
        loop_transition_frames=40,
    )

    player.start()
    block = player.next_block(4)

    np.testing.assert_allclose(
        block.samples[:, 0],
        np.ones(4, dtype=np.float32) * 0.5,
        atol=1e-6,
    )
    assert block.next_frame_cursor == 4


def test_player_single_frame_loop_transition_attaches_to_head_cursor() -> None:
    samples = np.column_stack(
        [
            np.array([0.0, 0.1, 0.2, 0.9], dtype=np.float32),
            np.array([0.0, 0.1, 0.2, 0.9], dtype=np.float32),
        ],
    )
    silence = np.zeros((4, 2), dtype=np.float32)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=samples, sample_rate=8_000),
            "mid": AudioBuffer(samples=silence, sample_rate=8_000),
            "voice": AudioBuffer(samples=silence, sample_rate=8_000),
        },
        loop_frames=4,
        loop_transition_frames=1,
    )

    player.start()
    player.next_block(3)
    transition = player.next_block(1)
    after_transition = player.next_block(1)

    assert transition.samples[0, 0] == pytest.approx(samples[0, 0], abs=1e-6)
    assert after_transition.samples[0, 0] == pytest.approx(samples[1, 0], abs=1e-6)
    assert player.frame_cursor == 2


def test_player_seek_during_playback_applies_short_ramp_in(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3, frames=512)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(16)

    player.seek(256)
    ramped = player.next_block(4)
    after_ramp = player.next_block(64)

    assert player.is_playing is True
    assert ramped.next_frame_cursor == 260
    assert player.frame_cursor == 324
    assert ramped.samples[0, 0] == pytest.approx(0.0, abs=1e-6)
    assert np.all(np.diff(ramped.samples[:, 0]) > 0.0)
    assert np.all(ramped.samples[:, 0] < 0.6)
    np.testing.assert_allclose(after_ramp.samples[-1], np.array([0.6, 0.6]), atol=1e-6)


def test_player_start_after_stopped_seek_emits_first_block_without_fade_in(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3, frames=512)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(16)
    player.seek(256)
    player.stop()

    player.start()
    block = player.next_block(4)

    assert player.is_playing is True
    assert block.next_frame_cursor == 260
    np.testing.assert_allclose(block.samples, np.ones((4, 2)) * 0.6, atol=1e-6)


def test_player_transition_disabled_smooths_raw_loop_boundary_with_declick_guard() -> None:
    loop_frames = 100
    source_frames = 120
    samples = np.zeros(source_frames, dtype=np.float32)
    samples[:40] = -1.0
    samples[loop_frames - 40 : loop_frames] = 1.0
    layer = AudioBuffer(
        samples=np.column_stack([samples, samples]),
        sample_rate=8_000,
    )
    silence = AudioBuffer(
        samples=np.zeros((source_frames, 2), dtype=np.float32),
        sample_rate=8_000,
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": layer,
            "mid": silence,
            "voice": silence,
        },
        loop_frames=loop_frames,
    )

    player.start()
    player.next_block(loop_frames - 40)
    block = player.next_block(80)

    assert abs(block.samples[39, 0]) < 0.05
    assert abs(block.samples[40, 0]) < 0.05
    assert abs(block.samples[40, 0] - block.samples[39, 0]) < 0.05
    assert block.samples[-1, 0] == pytest.approx(-1.0, abs=0.05)
    assert block.next_frame_cursor == 40


def test_player_stop_returns_silence_without_advancing_cursor(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(3)

    player.stop()
    block = player.next_block(2)

    assert player.is_playing is False
    assert player.frame_cursor == 3
    assert block.next_frame_cursor == 3
    np.testing.assert_allclose(block.samples, np.zeros((2, 2), dtype=np.float32))


def test_player_next_block_before_load_fails() -> None:
    with pytest.raises(ValueError, match="loaded"):
        LayeredLoopPlayer().next_block(2)


def test_player_enabled_and_realtime_trim_state_affect_next_block(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.2, mid=0.2, voice=0.2)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.set_enabled("mid", False)
    player.set_realtime_trim("voice", -6.0)

    player.start()
    block = player.next_block(4)

    expected_voice = 0.2 * (10 ** (-6.0 / 20.0))
    np.testing.assert_allclose(block.samples, np.ones((4, 2)) * (0.2 + expected_voice), atol=1e-6)


def test_player_realtime_trim_change_while_playing_applies_short_gain_ramp(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path, low=0.2, mid=0.2, voice=0.2, frames=512)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    before = player.next_block(4)

    player.set_realtime_trim("voice", -6.0)
    ramped = player.next_block(4)
    after_ramp = player.next_block(64)

    target_voice = 0.2 * (10 ** (-6.0 / 20.0))
    target_mix = 0.4 + target_voice
    np.testing.assert_allclose(before.samples, np.ones((4, 2)) * 0.6, atol=1e-6)
    assert ramped.samples[0, 0] == pytest.approx(0.6, abs=1e-6)
    assert np.all(np.diff(ramped.samples[:, 0]) < 0.0)
    assert np.all(ramped.samples[:, 0] > target_mix)
    np.testing.assert_allclose(
        after_ramp.samples[-1],
        np.array([target_mix, target_mix]),
        atol=1e-6,
    )


def test_player_enabled_change_while_playing_applies_short_mute_ramp(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path, low=0.2, mid=0.2, voice=0.2, frames=512)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    before = player.next_block(4)

    player.set_enabled("voice", False)
    muted_ramp = player.next_block(4)
    muted_after_ramp = player.next_block(64)
    player.set_enabled("voice", True)
    unmuted_ramp = player.next_block(4)
    unmuted_after_ramp = player.next_block(64)

    np.testing.assert_allclose(before.samples, np.ones((4, 2)) * 0.6, atol=1e-6)
    assert muted_ramp.samples[0, 0] == pytest.approx(0.6, abs=1e-6)
    assert np.all(np.diff(muted_ramp.samples[:, 0]) < 0.0)
    assert np.all(muted_ramp.samples[:, 0] > 0.4)
    np.testing.assert_allclose(
        muted_after_ramp.samples[-1],
        np.array([0.4, 0.4]),
        atol=1e-6,
    )
    assert unmuted_ramp.samples[0, 0] == pytest.approx(0.4, abs=1e-6)
    assert np.all(np.diff(unmuted_ramp.samples[:, 0]) > 0.0)
    assert np.all(unmuted_ramp.samples[:, 0] < 0.6)
    np.testing.assert_allclose(
        unmuted_after_ramp.samples[-1],
        np.array([0.6, 0.6]),
        atol=1e-6,
    )


def test_player_rejects_unknown_layer_state_updates() -> None:
    player = LayeredLoopPlayer()

    with pytest.raises(ValueError, match="layer"):
        player.set_enabled("unknown", True)

    with pytest.raises(ValueError, match="layer"):
        player.set_realtime_trim("unknown", 0.0)


def test_player_reload_and_restart_loads_new_files_and_preserves_states(tmp_path: Path) -> None:
    first_paths = write_layers(tmp_path / "first", low=0.1, mid=0.2, voice=0.3)
    second_paths = write_layers(tmp_path / "second", low=0.4, mid=0.5, voice=0.6)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(first_paths)
    player.set_enabled("mid", False)
    player.set_realtime_trim("voice", -6.0)
    player.start()
    player.next_block(3)

    player.reload_and_restart(second_paths)
    block = player.next_block(4)

    expected_voice = 0.6 * (10 ** (-6.0 / 20.0))
    assert player.is_playing is True
    assert player.frame_cursor == 0
    np.testing.assert_allclose(block.samples, np.ones((4, 2)) * (0.4 + expected_voice), atol=1e-6)


def test_player_reload_and_restart_clears_live_eq_state_for_rendered_cache(
    tmp_path: Path,
) -> None:
    first_paths = write_layers(tmp_path / "first", low=0.1, mid=0.2, voice=0.3)
    second_paths = write_layers(tmp_path / "second", low=0.4, mid=0.5, voice=0.6)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(first_paths)
    player.set_live_eq_state("mid", EqSettings(mid_gain_db=9.0))
    player.set_live_eq_state("voice", EqSettings(high_gain_db=-6.0))

    player.reload_and_restart(second_paths)

    assert player.live_eq_states == {
        "low": EqSettings(),
        "mid": EqSettings(),
        "voice": EqSettings(),
    }


def test_player_voice_crossfade_mixes_equal_power_voice_only_from_new_loop_start(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path / "first", low=0.1, mid=0.2, voice=0.0, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(2)

    superseded = player.start_voice_crossfade(
        stereo(0.4, frames=8),
        duration_frames=4,
        transition_target_id="vs-2",
    )
    assert player.frame_cursor == 0

    block = player.next_block(2)

    progress = np.array([0.0, 0.25], dtype=np.float32)
    expected_voice = 0.4 * np.sin(progress * np.pi / 2.0)
    expected = np.column_stack([0.3 + expected_voice, 0.3 + expected_voice])
    assert superseded is None
    assert player.frame_cursor == 2
    assert player.active_voice_transition_target_id == "vs-2"
    np.testing.assert_allclose(block.samples, expected, atol=1e-6)


def test_player_voice_crossfade_keeps_outgoing_position_and_starts_incoming_at_zero() -> None:
    frames = 8
    outgoing = np.column_stack(
        [
            np.linspace(0.0, 0.7, num=frames, dtype=np.float32),
            np.linspace(0.0, 0.7, num=frames, dtype=np.float32),
        ],
    )
    incoming = np.column_stack(
        [
            np.linspace(0.0, 0.35, num=frames, dtype=np.float32),
            np.linspace(0.0, 0.35, num=frames, dtype=np.float32),
        ],
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=frames),
            "mid": stereo(0.0, frames=frames),
            "voice": AudioBuffer(samples=outgoing, sample_rate=8_000),
        }
    )
    player.start()
    player.next_block(5)

    player.start_voice_crossfade(
        AudioBuffer(samples=incoming, sample_rate=8_000),
        duration_frames=4,
        transition_target_id="vs-2",
    )
    assert player.frame_cursor == 0

    block = player.next_block(3)

    progress = np.array([0.0, 0.25, 0.5], dtype=np.float32)
    from_gain, to_gain = _equal_power_crossfade_gains(progress)
    expected = outgoing[[5, 6, 7], 0] * from_gain + incoming[[0, 1, 2], 0] * to_gain
    np.testing.assert_allclose(block.samples[:, 0], expected, atol=1e-6)
    assert player.frame_cursor == 3


def test_player_voice_crossfade_finishes_active_before_latest_queued_target() -> None:
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=8),
            "mid": stereo(0.0, frames=8),
            "voice": stereo(0.0, frames=8),
        }
    )
    player.start()

    player.start_voice_crossfade(
        stereo(0.4, frames=8),
        duration_frames=2,
        transition_target_id="first",
    )
    superseded = player.start_voice_crossfade(
        stereo(0.8, frames=8),
        duration_frames=2,
        transition_target_id="second",
    )

    assert superseded == "first"
    assert player.active_voice_transition_target_id == "first"

    first_finish = player.next_block(2)

    assert player.active_voice_transition_target_id == "second"
    assert 0.0 < first_finish.samples[-1, 0] < 0.4

    second_start = player.next_block(1)

    assert player.active_voice_transition_target_id == "second"
    np.testing.assert_allclose(second_start.samples, np.ones((1, 2)) * 0.4, atol=1e-6)


def test_player_transition_disabled_can_replace_voice_stack_immediately() -> None:
    old_voice = np.column_stack(
        [
            np.array([0.0, 0.1, 0.2, 0.3, 0.4], dtype=np.float32),
            np.array([0.0, 0.1, 0.2, 0.3, 0.4], dtype=np.float32),
        ],
    )
    new_voice = np.column_stack(
        [
            np.array([0.5, 0.6, 0.7, 0.8, 0.9], dtype=np.float32),
            np.array([0.5, 0.6, 0.7, 0.8, 0.9], dtype=np.float32),
        ],
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=5),
            "mid": stereo(0.0, frames=5),
            "voice": AudioBuffer(samples=old_voice, sample_rate=8_000),
        }
    )
    player.start()
    player.next_block(3)

    superseded = player.replace_voice_stack_immediate(
        AudioBuffer(samples=new_voice, sample_rate=8_000),
        transition_target_id="new",
    )
    block = player.next_block(2)

    assert superseded is None
    assert player.active_voice_transition_target_id is None
    assert player.active_voice_identity == "new"
    assert block.next_frame_cursor == 2
    np.testing.assert_allclose(block.samples[:, 0], new_voice[:2, 0], atol=1e-6)


def test_player_transition_disabled_switches_voice_stack_at_loop_boundary() -> None:
    old_voice = np.column_stack(
        [
            np.array([0.0, 0.1, 0.2, 0.3, 0.4], dtype=np.float32),
            np.array([0.0, 0.1, 0.2, 0.3, 0.4], dtype=np.float32),
        ],
    )
    new_voice = np.column_stack(
        [
            np.array([0.5, 0.6, 0.7, 0.8, 0.9], dtype=np.float32),
            np.array([0.5, 0.6, 0.7, 0.8, 0.9], dtype=np.float32),
        ],
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=5),
            "mid": stereo(0.0, frames=5),
            "voice": AudioBuffer(samples=old_voice, sample_rate=8_000),
        }
    )
    player.start()
    player.next_block(2)

    superseded = player.switch_voice_stack_at_loop_boundary(
        AudioBuffer(samples=new_voice, sample_rate=8_000),
        transition_target_id="new",
    )
    block = player.next_block(5)

    assert superseded is None
    assert player.active_voice_transition_target_id is None
    assert player.active_voice_identity == "new"
    assert block.next_frame_cursor == 2
    np.testing.assert_allclose(
        block.samples[:, 0],
        np.array([0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float32),
        atol=1e-6,
    )


def test_player_transition_disabled_queued_during_active_fade_applies_after_fade() -> None:
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=8),
            "mid": stereo(0.0, frames=8),
            "voice": stereo(0.0, frames=8),
        }
    )
    player.start()
    player.start_voice_crossfade(
        stereo(0.4, frames=8),
        duration_frames=2,
        transition_target_id="first",
    )

    superseded = player.replace_voice_stack_immediate(
        stereo(0.8, frames=8),
        transition_target_id="second",
    )
    player.next_block(2)
    block = player.next_block(1)

    assert superseded == "first"
    assert player.active_voice_transition_target_id is None
    assert player.active_voice_identity == "second"
    np.testing.assert_allclose(block.samples, np.ones((1, 2)) * 0.8, atol=1e-6)


def test_player_voice_crossfade_can_transition_low_mid_and_voice_together(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path / "first", low=0.01, mid=0.02, voice=0.03, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(2)

    next_layers = {
        "low": stereo(0.04, frames=8),
        "mid": stereo(0.05, frames=8),
        "voice": stereo(0.06, frames=8),
    }
    player.start_voice_crossfade(
        next_layers["voice"],
        duration_frames=4,
        transition_target_id="vs-2",
        next_layers=next_layers,
    )
    assert player.frame_cursor == 0

    block = player.next_block(2)

    progress = np.array([0.0, 0.25], dtype=np.float32)
    from_gain, to_gain = _equal_power_crossfade_gains(progress)
    expected_layer_sum = (
        (0.01 + 0.02 + 0.03) * from_gain
        + (0.04 + 0.05 + 0.06) * to_gain
    )
    expected = np.column_stack([expected_layer_sum, expected_layer_sum])
    assert player.frame_cursor == 2
    assert player.active_voice_transition_target_id == "vs-2"
    np.testing.assert_allclose(block.samples, expected, atol=1e-6)


def test_player_voice_eq_update_is_audible_during_active_voice_crossfade(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path / "first", low=0.0, mid=0.0, voice=0.1, frames=512)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.next_block(16)
    player.start_voice_crossfade(
        stereo(0.1, frames=512),
        duration_frames=128,
        transition_target_id="vs-2",
    )

    before = rms(player.next_block(16).samples[:, 0])
    player.set_layer_buffer("voice", stereo(0.3, frames=512))
    player.set_live_eq_state("voice", EqSettings(mid_gain_db=6.0))
    after = rms(player.next_block(16).samples[:, 0])

    assert player.active_voice_transition_target_id == "vs-2"
    assert after > before * 1.5


def test_player_voice_crossfade_restarts_low_mid_voice_layers_from_zero_cursor(
    tmp_path: Path,
) -> None:
    frames = 8
    low_samples = np.column_stack(
        [
            np.linspace(0.01, 0.08, num=frames, dtype=np.float32),
            np.linspace(0.01, 0.08, num=frames, dtype=np.float32),
        ],
    )
    mid_samples = np.column_stack(
        [
            np.linspace(0.10, 0.135, num=frames, dtype=np.float32),
            np.linspace(0.10, 0.135, num=frames, dtype=np.float32),
        ],
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": AudioBuffer(samples=low_samples, sample_rate=8_000),
            "mid": AudioBuffer(samples=mid_samples, sample_rate=8_000),
            "voice": stereo(0.0, frames=frames),
        }
    )
    player.start()
    player.next_block(3)

    player.start_voice_crossfade(
        stereo(0.2, frames=frames),
        duration_frames=4,
        transition_target_id="vs-2",
    )
    block = player.next_block(4)

    cursor_indices = np.array([0, 1, 2, 3])
    progress = np.array([0.0, 0.25, 0.5, 0.75], dtype=np.float32)
    expected_voice = 0.2 * np.sin(progress * np.pi / 2.0)
    expected_non_voice = low_samples[cursor_indices, 0] + mid_samples[cursor_indices, 0]
    expected = np.column_stack(
        [
            expected_non_voice + expected_voice,
            expected_non_voice + expected_voice,
        ],
    )

    assert player.frame_cursor == 4
    assert block.next_frame_cursor == 4
    np.testing.assert_allclose(block.samples, expected, atol=1e-6)


def test_player_voice_crossfade_continues_new_loop_cursor_across_transition_boundary() -> None:
    frames = 8
    mid_samples = np.column_stack(
        [
            np.linspace(0.10, 0.17, num=frames, dtype=np.float32),
            np.linspace(0.10, 0.17, num=frames, dtype=np.float32),
        ],
    )
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=frames),
            "mid": AudioBuffer(samples=mid_samples, sample_rate=8_000),
            "voice": stereo(0.0, frames=frames),
        }
    )
    player.start()
    player.next_block(5)

    player.start_voice_crossfade(
        stereo(0.0, frames=frames),
        duration_frames=4,
        transition_target_id="vs-2",
    )
    during_crossfade = player.next_block(3)
    after_crossfade = player.next_block(3)

    np.testing.assert_allclose(
        during_crossfade.samples[:, 0],
        mid_samples[[0, 1, 2], 0],
        atol=1e-6,
    )
    np.testing.assert_allclose(
        after_crossfade.samples[:, 0],
        mid_samples[[3, 4, 5], 0],
        atol=1e-6,
    )
    assert player.frame_cursor == 6
    assert player.active_voice_transition_target_id is None


def test_player_voice_crossfade_preserves_mid_runtime_trim_state(tmp_path: Path) -> None:
    paths = write_layers(tmp_path / "first", low=0.0, mid=0.2, voice=0.0, frames=512)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.set_realtime_trim("mid", -6.0)
    mid_state_before_crossfade = player.layer_states["mid"]

    player.start_voice_crossfade(
        stereo(0.2, frames=512),
        duration_frames=128,
        transition_target_id="vs-2",
    )
    player.next_block(16)

    assert player.layer_states["mid"] == mid_state_before_crossfade


def test_player_voice_crossfade_finishes_by_installing_candidate_voice(tmp_path: Path) -> None:
    paths = write_layers(tmp_path / "first", low=0.0, mid=0.0, voice=0.0, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()

    player.start_voice_crossfade(
        stereo(0.4, frames=8),
        duration_frames=2,
        transition_target_id="vs-2",
    )
    player.next_block(2)
    block = player.next_block(2)

    assert player.active_voice_transition_target_id is None
    np.testing.assert_allclose(block.samples, np.ones((2, 2)) * 0.4, atol=1e-6)


def test_player_voice_crossfade_activation_failure_continues_current_voice() -> None:
    current_voice = stereo(0.2, frames=8)
    next_voice = stereo(0.7, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": stereo(0.0, frames=8),
            "mid": stereo(0.0, frames=8),
            "voice": current_voice,
        },
        active_voice_identity="current-vs",
    )
    player.start()
    player.start_voice_crossfade(
        next_voice,
        duration_frames=2,
        transition_target_id="next-vs",
    )
    player._layers = FailingVoiceActivationDict(player._layers)  # type: ignore[attr-defined]

    block = player.next_block(2)

    snapshot = player.snapshot()
    assert player.active_voice_identity == "current-vs"
    assert snapshot.active_voice_identity == "current-vs"
    assert snapshot.layers is not None
    assert snapshot.layers["voice"] is current_voice
    assert player.active_voice_transition_target_id is None
    assert player.frame_cursor == 2
    np.testing.assert_allclose(
        block.samples,
        np.ones((2, 2), dtype=np.float32) * 0.2,
        atol=1e-6,
    )


def test_player_load_rendered_layers_clears_pending_voice_crossfade_and_stays_stopped(
    tmp_path: Path,
) -> None:
    first_paths = write_layers(tmp_path / "first", low=0.0, mid=0.0, voice=0.0, frames=8)
    second_paths = write_layers(tmp_path / "second", low=0.1, mid=0.1, voice=0.1, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(first_paths)
    player.start()
    player.start_voice_crossfade(
        stereo(0.4, frames=8),
        duration_frames=4,
        transition_target_id="vs-2",
    )

    player.load_rendered_layers(second_paths)
    block = player.next_block(2)

    assert player.active_voice_transition_target_id is None
    assert player.is_playing is False
    np.testing.assert_allclose(block.samples, np.zeros((2, 2)), atol=1e-6)


def test_player_load_rendered_layers_clears_live_eq_state_for_stopped_rendered_cache(
    tmp_path: Path,
) -> None:
    first_paths = write_layers(tmp_path / "first", low=0.0, mid=0.0, voice=0.0, frames=8)
    second_paths = write_layers(tmp_path / "second", low=0.1, mid=0.1, voice=0.1, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(first_paths)
    player.set_live_eq_state("mid", EqSettings(mid_gain_db=9.0))
    player.set_live_eq_state("voice", EqSettings(high_gain_db=-6.0))

    player.load_rendered_layers(second_paths)

    assert player.is_playing is False
    assert player.live_eq_states == {
        "low": EqSettings(),
        "mid": EqSettings(),
        "voice": EqSettings(),
    }


def test_player_load_rendered_layers_uses_configured_loop_frames(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3, frames=24)
    player = LayeredLoopPlayer()

    player.load_rendered_layers(paths, loop_frames=8)
    player.start()
    player.seek(6)
    block = player.next_block(5)

    assert block.next_frame_cursor == 3
    assert player.frame_cursor == 3


def test_player_latest_voice_crossfade_target_waits_until_active_transition_finishes(
    tmp_path: Path,
) -> None:
    paths = write_layers(tmp_path / "first", low=0.0, mid=0.0, voice=0.0, frames=8)
    player = LayeredLoopPlayer()
    player.load_rendered_layers(paths)
    player.start()
    player.start_voice_crossfade(
        stereo(0.2, frames=8),
        duration_frames=4,
        transition_target_id="old",
    )

    superseded = player.start_voice_crossfade(
        stereo(0.5, frames=8),
        duration_frames=2,
        transition_target_id="new",
    )
    player.next_block(2)
    player.next_block(2)
    block = player.next_block(1)

    assert superseded == "old"
    assert player.active_voice_transition_target_id == "new"
    np.testing.assert_allclose(block.samples, np.ones((1, 2)) * 0.2, atol=1e-6)


def test_player_restart_requires_loaded_layers_resets_cursor_and_preserves_states(
    tmp_path: Path,
) -> None:
    player = LayeredLoopPlayer()
    with pytest.raises(ValueError, match="loaded"):
        player.restart()

    paths = write_layers(tmp_path, low=0.2, mid=0.2, voice=0.2, frames=8)
    player.load_rendered_layers(paths)
    player.set_enabled("mid", False)
    player.set_realtime_trim("voice", -6.0)
    player.start()
    player.next_block(3)

    player.restart()

    states = player.layer_states
    assert player.is_playing is True
    assert player.frame_cursor == 0
    assert states["mid"].enabled is False
    assert states["voice"].realtime_trim_db == -6.0


def test_player_reload_failure_preserves_existing_runtime_state(tmp_path: Path) -> None:
    good_paths = write_layers(tmp_path / "good", low=0.1, mid=0.2, voice=0.3)
    bad_paths = write_layers(tmp_path / "bad", low=0.4, mid=0.5, voice=0.6)
    bad_paths["mid"].unlink()
    player = LayeredLoopPlayer()
    player.load_rendered_layers(good_paths)
    player.set_enabled("mid", False)
    player.start()
    player.next_block(3)

    with pytest.raises(FileNotFoundError, match="mid"):
        player.reload_and_restart(bad_paths)

    assert player.is_playing is True
    assert player.frame_cursor == 3
    block = player.next_block(1)
    np.testing.assert_allclose(block.samples, np.ones((1, 2), dtype=np.float32) * 0.4, atol=1e-6)


def test_player_snapshot_restore_recovers_loaded_state_and_peak_ceiling(
    tmp_path: Path,
) -> None:
    first_paths = write_layers(tmp_path / "first", low=0.6, mid=0.6, voice=0.6, frames=6)
    second_paths = write_layers(tmp_path / "second", low=0.1, mid=0.1, voice=0.1, frames=6)
    player = LayeredLoopPlayer(peak_ceiling=0.95)
    player.load_rendered_layers(first_paths)
    player.set_enabled("mid", False)
    player.set_realtime_trim("voice", -6.0)
    player.start()
    player.next_block(3)
    snapshot = player.snapshot()

    player.set_enabled("mid", True)
    player.set_realtime_trim("voice", 0.0)
    player.set_peak_ceiling(0.25)
    player.reload_and_restart(second_paths)
    player.restore(snapshot)

    states = player.layer_states
    expected_voice = 0.6 * (10 ** (-6.0 / 20.0))
    assert player.is_playing is True
    assert player.frame_cursor == 3
    assert states["mid"].enabled is False
    assert states["voice"].realtime_trim_db == -6.0
    block = player.next_block(2)
    np.testing.assert_allclose(
        block.samples,
        np.ones((2, 2), dtype=np.float32) * (0.6 + expected_voice),
        atol=1e-6,
    )


def test_player_snapshot_restore_can_return_to_unloaded_state(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3)
    player = LayeredLoopPlayer()
    snapshot = player.snapshot()
    player.load_rendered_layers(paths)
    player.start()

    player.restore(snapshot)

    assert player.is_playing is False
    with pytest.raises(ValueError, match="loaded"):
        player.next_block(1)


def test_player_set_peak_ceiling_validates_range() -> None:
    player = LayeredLoopPlayer()

    with pytest.raises(ValueError, match="peak_ceiling"):
        player.set_peak_ceiling(0.0)

    with pytest.raises(ValueError, match="peak_ceiling"):
        player.set_peak_ceiling(1.5)


def test_player_load_rejects_mismatched_rendered_formats(tmp_path: Path) -> None:
    paths = write_layers(tmp_path, low=0.1, mid=0.2, voice=0.3)
    write_wav_atomic(paths["voice"], stereo(0.3, sample_rate=16_000))

    with pytest.raises(ValueError, match="sample rate"):
        LayeredLoopPlayer().load_rendered_layers(paths)
