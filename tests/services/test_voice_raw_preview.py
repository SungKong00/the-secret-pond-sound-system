from __future__ import annotations

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.config import AppSettings
from secret_pond.services.voice_raw_preview import (
    prepare_voice_raw_preview,
    start_voice_raw_preview,
)


class PreviewVoiceSource:
    def __init__(self, layers: dict[str, AudioBuffer]) -> None:
        self.layers = layers

    def preview_layers(
        self,
        relative_path: str,
        settings: AppSettings,
    ) -> dict[str, AudioBuffer]:
        return self.layers


class PreviewPlayer:
    def __init__(self, output: PreviewOutput) -> None:
        self.output = output
        self.is_playing = True
        self.load_observations: list[tuple[bool, bool]] = []
        self.loaded_layers: dict[str, AudioBuffer] | None = None
        self.replace_calls = 0
        self.restart_calls = 0
        self.stop_calls = 0

    def load_rendered_buffers(self, layers: dict[str, AudioBuffer]) -> None:
        self.load_observations.append((self.output.is_running, self.is_playing))
        self.loaded_layers = dict(layers)
        self.is_playing = False

    def replace_rendered_buffers(self, layers: dict[str, AudioBuffer]) -> None:
        self.replace_calls += 1
        self.loaded_layers = dict(layers)

    def set_peak_ceiling(self, peak_ceiling: float) -> None:
        self.peak_ceiling = peak_ceiling

    def set_enabled(self, layer_id: str, enabled: bool) -> None:
        pass

    def set_realtime_trim(self, layer_id: str, trim_db: float) -> None:
        pass

    def restart(self) -> None:
        self.restart_calls += 1
        self.is_playing = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_playing = False


class PreviewOutput:
    def __init__(self) -> None:
        self.is_running = True
        self.start_calls = 0
        self.stop_calls = 0
        self.player: PreviewPlayer | None = None

    def start(self) -> None:
        self.start_calls += 1
        if self.player is not None:
            self.player.is_playing = True
        self.is_running = True

    def stop(self) -> None:
        self.stop_calls += 1
        if self.player is not None:
            self.player.stop()
        self.is_running = False


class PreviewRuntime:
    def __init__(self) -> None:
        output = PreviewOutput()
        player = PreviewPlayer(output)
        output.player = player
        self.output = output
        self.player = player
        self.voice_source = PreviewVoiceSource(
            {
                layer_id: AudioBuffer(
                    samples=np.zeros((32, 2), dtype=np.float32),
                    sample_rate=8_000,
                )
                for layer_id in ("low", "mid", "voice")
            }
        )
        self.voice_raw_preview_path: str | None = None
        self.voice_raw_preview_resume_main = False
        self.voice_raw_preview_layers: dict[str, AudioBuffer] | None = None


def test_start_voice_raw_preview_stops_main_playback_before_loading_preview() -> None:
    runtime = PreviewRuntime()
    settings = AppSettings()

    start_voice_raw_preview(runtime, "data/sources/voice/raw/VR0610_213112.wav", settings)

    assert runtime.output.stop_calls == 1
    assert runtime.player.load_observations == [(False, False)]
    assert runtime.output.start_calls == 1
    assert runtime.output.is_running is True
    assert runtime.player.is_playing is True
    assert runtime.voice_raw_preview_path == "data/sources/voice/raw/VR0610_213112.wav"


def test_reprocessing_voice_raw_preview_publishes_new_active_preview_source() -> None:
    runtime = PreviewRuntime()
    settings = AppSettings()
    first_voice = AudioBuffer(
        samples=np.full((32, 2), 0.1, dtype=np.float32),
        sample_rate=8_000,
    )
    second_voice = AudioBuffer(
        samples=np.full((32, 2), 0.4, dtype=np.float32),
        sample_rate=8_000,
    )
    runtime.voice_source.layers = {
        "low": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "mid": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "voice": first_voice,
    }

    prepare_voice_raw_preview(runtime, "data/sources/voice/raw/VR0610_213112.wav", settings)
    runtime.voice_source.layers = {
        "low": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "mid": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "voice": second_voice,
    }

    prepare_voice_raw_preview(runtime, "data/sources/voice/raw/VR0610_213112.wav", settings)

    assert runtime.voice_raw_preview_layers is not None
    assert runtime.voice_raw_preview_layers["voice"] is second_voice
    assert runtime.player.loaded_layers is not None
    assert runtime.player.loaded_layers["voice"] is second_voice


def test_start_voice_raw_preview_replaces_running_preview_without_transport_restart() -> None:
    runtime = PreviewRuntime()
    settings = AppSettings()
    first_voice = AudioBuffer(
        samples=np.full((32, 2), 0.1, dtype=np.float32),
        sample_rate=8_000,
    )
    second_voice = AudioBuffer(
        samples=np.full((32, 2), 0.4, dtype=np.float32),
        sample_rate=8_000,
    )
    runtime.voice_source.layers = {
        "low": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "mid": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "voice": first_voice,
    }
    start_voice_raw_preview(runtime, "data/sources/voice/raw/VR0610_213112.wav", settings)
    runtime.output.start_calls = 0
    runtime.output.stop_calls = 0
    runtime.player.stop_calls = 0
    runtime.player.restart_calls = 0
    runtime.player.replace_calls = 0
    runtime.voice_source.layers = {
        "low": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "mid": AudioBuffer(samples=np.zeros((32, 2), dtype=np.float32), sample_rate=8_000),
        "voice": second_voice,
    }

    start_voice_raw_preview(runtime, "data/sources/voice/raw/VR0610_213112.wav", settings)

    assert runtime.output.stop_calls == 0
    assert runtime.output.start_calls == 0
    assert runtime.output.is_running is True
    assert runtime.player.stop_calls == 0
    assert runtime.player.restart_calls == 0
    assert runtime.player.replace_calls == 1
    assert runtime.player.is_playing is True
    assert runtime.player.loaded_layers is not None
    assert runtime.player.loaded_layers["voice"] is second_voice


def test_reprocessing_active_voice_raw_preview_swaps_audible_buffer_without_cursor_reset() -> None:
    frames = 8
    settings = AppSettings().model_copy(
        update={
            "audio": AppSettings().audio.model_copy(
                update={"sample_rate": 8_000, "channels": 2, "loop_seconds": 1},
            ),
        },
        deep=True,
    )
    first_voice = AudioBuffer(
        samples=np.column_stack(
            [
                np.linspace(0.01, 0.08, num=frames, dtype=np.float32),
                np.linspace(0.01, 0.08, num=frames, dtype=np.float32),
            ],
        ),
        sample_rate=8_000,
    )
    second_voice = AudioBuffer(
        samples=np.column_stack(
            [
                np.linspace(0.11, 0.18, num=frames, dtype=np.float32),
                np.linspace(0.11, 0.18, num=frames, dtype=np.float32),
            ],
        ),
        sample_rate=8_000,
    )
    silence = AudioBuffer(samples=np.zeros((frames, 2), dtype=np.float32), sample_rate=8_000)
    player = LayeredLoopPlayer()
    player.load_rendered_buffers({"low": silence, "mid": silence, "voice": first_voice})
    player.set_enabled("low", False)
    player.set_enabled("mid", False)
    player.start()
    player.next_block(3)
    runtime = PreviewRuntime()
    runtime.player = player
    runtime.voice_raw_preview_path = "data/sources/voice/raw/VR0610_213112.wav"
    runtime.voice_source.layers = {"low": silence, "mid": silence, "voice": second_voice}

    prepare_voice_raw_preview(runtime, "data/sources/voice/raw/VR0610_213112.wav", settings)
    block = player.next_block(2)

    assert player.is_playing is True
    np.testing.assert_allclose(block.samples[:, 0], second_voice.samples[3:5, 0], atol=1e-6)
