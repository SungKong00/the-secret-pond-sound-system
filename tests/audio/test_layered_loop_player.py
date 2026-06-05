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


def test_player_voice_crossfade_mixes_equal_power_voice_only_without_resetting_cursor(
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
    block = player.next_block(2)

    progress = np.array([0.0, 0.25], dtype=np.float32)
    expected_voice = 0.4 * np.sin(progress * np.pi / 2.0)
    expected = np.column_stack([0.3 + expected_voice, 0.3 + expected_voice])
    assert superseded is None
    assert player.frame_cursor == 4
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


def test_player_voice_crossfade_keeps_low_mid_layers_on_current_cursor(
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

    cursor_indices = np.array([3, 4, 5, 6])
    progress = np.array([0.0, 0.25, 0.5, 0.75], dtype=np.float32)
    expected_voice = 0.2 * np.sin(progress * np.pi / 2.0)
    expected_non_voice = low_samples[cursor_indices, 0] + mid_samples[cursor_indices, 0]
    expected = np.column_stack(
        [
            expected_non_voice + expected_voice,
            expected_non_voice + expected_voice,
        ],
    )
    reset_cursor_non_voice = low_samples[:4, 0] + mid_samples[:4, 0]

    assert player.frame_cursor == 7
    assert block.next_frame_cursor == 7
    assert not np.allclose(expected_non_voice, reset_cursor_non_voice)
    np.testing.assert_allclose(block.samples, expected, atol=1e-6)


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


def test_player_latest_voice_crossfade_target_wins(tmp_path: Path) -> None:
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
    block = player.next_block(2)

    assert superseded == "old"
    assert player.active_voice_transition_target_id is None
    np.testing.assert_allclose(block.samples, np.ones((2, 2)) * 0.5, atol=1e-6)


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
