from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.player import LayeredLoopPlayer


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
