from __future__ import annotations

import pytest
from pydantic import ValidationError

from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    EqSettings,
    InputControlSettings,
    VoiceStackSettings,
)
from secret_pond.state import RuntimeStatus


def test_default_settings_define_three_layers_and_disarmed_input() -> None:
    settings = AppSettings()

    assert set(settings.layers.keys()) == {"low", "mid", "voice"}
    assert settings.input_control.armed is False
    assert settings.input_control.maximum_recording_seconds == 120.0
    assert settings.audio.sample_rate == 48_000
    assert settings.audio.channels == 2
    assert settings.voice_stack.loop_seconds == 60
    assert settings.voice_stack.mode == "live_ephemeral"


def test_eq_gain_range_is_validated() -> None:
    with pytest.raises(ValidationError):
        EqSettings(low_gain_db=99.0)


def test_lowpass_must_be_greater_than_highpass() -> None:
    with pytest.raises(ValidationError):
        EqSettings(highpass_hz=5_000.0, lowpass_hz=1_000.0)


def test_recording_maximum_must_be_greater_than_minimum() -> None:
    with pytest.raises(ValidationError):
        InputControlSettings(minimum_recording_seconds=3.0, maximum_recording_seconds=3.0)


def test_voice_stack_mode_accepts_test_library() -> None:
    settings = VoiceStackSettings(mode="test_library")

    assert settings.mode == "test_library"


def test_voice_stack_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        VoiceStackSettings(mode="archive")


def test_voice_stack_loop_seconds_are_validated() -> None:
    with pytest.raises(ValidationError):
        VoiceStackSettings(loop_seconds=0)

    with pytest.raises(ValidationError):
        VoiceStackSettings(loop_seconds=601)


def test_audio_loop_seconds_can_be_short_for_setup_or_tests() -> None:
    settings = AudioFormatSettings(loop_seconds=1)

    assert settings.loop_seconds == 1

    with pytest.raises(ValidationError):
        AudioFormatSettings(loop_seconds=0)


def test_runtime_status_values_are_stable() -> None:
    assert [status.value for status in RuntimeStatus] == [
        "idle",
        "armed",
        "recording",
        "processing",
        "rendering",
        "playing",
        "stopped",
        "error",
    ]
