from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.output import SoundDeviceOutput
from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.config import EqSettings


class ScriptedPlayer:
    def __init__(
        self,
        *,
        fail_start: bool = False,
        fail_next_block: bool = False,
    ) -> None:
        self.fail_start = fail_start
        self.fail_next_block = fail_next_block
        self.is_playing = False
        self.start_calls = 0
        self.stop_calls = 0
        self.block_requests: list[int] = []

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError("player start failed")
        self.is_playing = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_playing = False

    def next_block(self, block_size: int):
        self.block_requests.append(block_size)
        if self.fail_next_block:
            raise RuntimeError("mix failed")
        samples = np.ones((block_size, 2), dtype=np.float32) * 0.25
        return SimpleNamespace(samples=samples)


class FakeOutputStream:
    def __init__(self, callback, fail_start: bool = False, fail_stop: bool = False) -> None:
        self.callback = callback
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        if self.fail_start:
            raise OSError("stream start failed")
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        if self.fail_stop:
            raise OSError("stream stop failed")

    def close(self) -> None:
        self.closed = True

    def pull(self, frames: int, channels: int = 2, status=None) -> np.ndarray:
        outdata = np.empty((frames, channels), dtype=np.float32)
        self.callback(outdata, frames, None, status)
        return outdata


class CapturingOutputStreamFactory:
    def __init__(
        self,
        *,
        fail_create: bool = False,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:
        self.fail_create = fail_create
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.calls: list[dict] = []
        self.streams: list[FakeOutputStream] = []

    def __call__(self, **kwargs) -> FakeOutputStream:
        self.calls.append(kwargs)
        if self.fail_create:
            raise OSError("stream create failed")
        stream = FakeOutputStream(
            kwargs["callback"],
            fail_start=self.fail_start,
            fail_stop=self.fail_stop,
        )
        self.streams.append(stream)
        return stream


def test_sounddevice_output_passes_stream_configuration_and_normalizes_device_id() -> None:
    factory = CapturingOutputStreamFactory()
    player = ScriptedPlayer()
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        device_id="3",
        block_size=512,
        stream_factory=factory,
    )

    output.start()

    assert factory.calls[0]["samplerate"] == 48_000
    assert factory.calls[0]["channels"] == 2
    assert factory.calls[0]["device"] == 3
    assert factory.calls[0]["dtype"] == "float32"
    assert factory.calls[0]["blocksize"] == 512
    assert output.is_running is True
    assert player.start_calls == 1


def test_sounddevice_output_callback_writes_player_block() -> None:
    factory = CapturingOutputStreamFactory()
    player = ScriptedPlayer()
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        stream_factory=factory,
    )

    output.start()
    rendered = factory.streams[0].pull(frames=4)

    assert player.block_requests == [4]
    np.testing.assert_allclose(rendered, np.ones((4, 2), dtype=np.float32) * 0.25)


def test_sounddevice_output_callback_survives_rapid_live_eq_parameter_changes() -> None:
    player = LayeredLoopPlayer()
    player.load_rendered_buffers(
        {
            "low": _stereo_layer(0.05, frames=256),
            "mid": _stereo_layer(0.10, frames=256),
            "voice": _stereo_layer(0.15, frames=256),
        }
    )
    factory = CapturingOutputStreamFactory()
    output = SoundDeviceOutput(
        sample_rate=8_000,
        channels=2,
        player=player,
        block_size=17,
        stream_factory=factory,
    )

    output.start()
    stream = factory.streams[0]
    for index in range(64):
        gain_db = -12.0 + (index % 25)
        player.set_live_eq_state("mid", EqSettings(mid_gain_db=gain_db))
        player.set_layer_buffer("mid", _stereo_layer(0.02 + (index * 0.001), frames=256))
        rendered = stream.pull(frames=17)

        assert output.latest_error is None
        assert rendered.shape == (17, 2)
        assert rendered.dtype == np.float32
        assert np.all(np.isfinite(rendered))


def test_sounddevice_output_callback_writes_silence_and_stores_error_on_player_failure() -> None:
    factory = CapturingOutputStreamFactory()
    player = ScriptedPlayer(fail_next_block=True)
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        stream_factory=factory,
    )

    output.start()
    rendered = factory.streams[0].pull(frames=4)

    np.testing.assert_allclose(rendered, np.zeros((4, 2), dtype=np.float32))
    assert output.latest_error == "mix failed"


def test_sounddevice_output_stores_callback_statuses() -> None:
    factory = CapturingOutputStreamFactory()
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=ScriptedPlayer(),
        stream_factory=factory,
    )

    output.start()
    factory.streams[0].pull(frames=1, status="underflow")

    assert output.latest_status == "underflow"
    assert output.statuses == ["underflow"]


def test_sounddevice_output_closes_stream_and_stops_player_when_stream_start_fails() -> None:
    factory = CapturingOutputStreamFactory(fail_start=True)
    player = ScriptedPlayer()
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        stream_factory=factory,
    )

    with pytest.raises(OSError, match="start failed"):
        output.start()

    assert factory.streams[0].closed is True
    assert output.is_running is False
    assert player.stop_calls == 1
    assert player.is_playing is False
    assert output.latest_error == "stream start failed"


def test_sounddevice_output_does_not_create_stream_when_player_start_fails() -> None:
    factory = CapturingOutputStreamFactory()
    player = ScriptedPlayer(fail_start=True)
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        stream_factory=factory,
    )

    with pytest.raises(RuntimeError, match="player start failed"):
        output.start()

    assert factory.calls == []
    assert factory.streams == []
    assert output.is_running is False
    assert output.latest_error == "player start failed"


def test_sounddevice_output_stops_player_when_stream_factory_fails() -> None:
    factory = CapturingOutputStreamFactory(fail_create=True)
    player = ScriptedPlayer()
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        stream_factory=factory,
    )

    with pytest.raises(OSError, match="create failed"):
        output.start()

    assert player.start_calls == 1
    assert player.stop_calls == 1
    assert output.is_running is False
    assert output.latest_error == "stream create failed"


def test_sounddevice_output_rejects_double_start_and_stop_before_start() -> None:
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=ScriptedPlayer(),
        stream_factory=CapturingOutputStreamFactory(),
    )

    with pytest.raises(RuntimeError, match="not running"):
        output.stop()

    output.start()
    with pytest.raises(RuntimeError, match="already running"):
        output.start()


def test_sounddevice_output_stop_closes_stream_even_when_stream_stop_fails() -> None:
    factory = CapturingOutputStreamFactory(fail_stop=True)
    player = ScriptedPlayer()
    output = SoundDeviceOutput(
        sample_rate=48_000,
        channels=2,
        player=player,
        stream_factory=factory,
    )

    output.start()

    with pytest.raises(OSError, match="stop failed"):
        output.stop()

    assert factory.streams[0].closed is True
    assert output.is_running is False
    assert player.stop_calls == 1


def _stereo_layer(value: float, *, frames: int) -> AudioBuffer:
    return AudioBuffer(
        samples=np.ones((frames, 2), dtype=np.float32) * value,
        sample_rate=8_000,
    )
