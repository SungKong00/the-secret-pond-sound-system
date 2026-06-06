from __future__ import annotations

import pytest
from pydantic import ValidationError

from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    EqSettings,
    InputControlSettings,
    LayerSettings,
    PlaybackSettings,
    SourceSelectionSettings,
    VoiceStackSettings,
)
from secret_pond.state import RuntimeStatus


def test_default_settings_define_three_layers_and_disarmed_input() -> None:
    settings = AppSettings()

    assert set(settings.layers.keys()) == {"low", "mid", "voice"}
    assert settings.sources.low_path is None
    assert settings.sources.mid_path is None
    assert settings.sources.voice_stack_path is None
    assert settings.input_control.armed is False
    assert settings.input_control.maximum_recording_seconds == 120.0
    assert settings.audio.sample_rate == 48_000
    assert settings.audio.channels == 2
    assert settings.playback.apply_mode == "stable"
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


def test_playback_apply_mode_accepts_live_and_rejects_unknown_value() -> None:
    assert PlaybackSettings(apply_mode="live").apply_mode == "live"

    with pytest.raises(ValidationError):
        PlaybackSettings(apply_mode="preview")


def test_voice_stack_loop_seconds_are_validated() -> None:
    with pytest.raises(ValidationError):
        VoiceStackSettings(loop_seconds=0)

    with pytest.raises(ValidationError):
        VoiceStackSettings(loop_seconds=601)


def test_non_eq_db_boost_ranges_accept_operator_headroom() -> None:
    assert LayerSettings(volume_db=12.0).volume_db == 12.0
    assert VoiceStackSettings(insert_gain_db=12.0).insert_gain_db == 12.0

    with pytest.raises(ValidationError):
        LayerSettings(volume_db=12.5)

    with pytest.raises(ValidationError):
        VoiceStackSettings(insert_gain_db=12.5)


def test_voice_stack_transition_seconds_defaults_to_three_seconds() -> None:
    assert AppSettings().voice_stack.transition_seconds == 3


@pytest.mark.parametrize("duration", [1, 10])
def test_voice_stack_transition_seconds_accepts_configured_range(
    duration: int,
) -> None:
    settings = VoiceStackSettings(transition_seconds=duration)

    assert settings.transition_seconds == duration


@pytest.mark.parametrize("duration", [0, 11])
def test_voice_stack_transition_seconds_rejects_out_of_range_values(
    duration: int,
) -> None:
    with pytest.raises(ValidationError):
        VoiceStackSettings(transition_seconds=duration)


def test_audio_loop_seconds_can_be_short_for_setup_or_tests() -> None:
    settings = AudioFormatSettings(loop_seconds=1)

    assert settings.loop_seconds == 1

    with pytest.raises(ValidationError):
        AudioFormatSettings(loop_seconds=0)


def test_source_selection_accepts_relative_wav_paths() -> None:
    settings = SourceSelectionSettings(
        low_path="data/sources/low/pond-low.wav",
        mid_path="data/sources/mid/pond-mid.wav",
        voice_raw_path="data/sources/voice/raw/2026-06-05T101500.wav",
        voice_stack_path="data/sources/voice/stack/2026-06-05T101700.wav",
    )

    assert settings.low_path == "data/sources/low/pond-low.wav"
    assert settings.voice_stack_path == "data/sources/voice/stack/2026-06-05T101700.wav"


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/low.wav",
        "../low.wav",
        "data/sources/low/not-a-wav.mp3",
    ],
)
def test_source_selection_rejects_unsafe_or_non_wav_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceSelectionSettings(low_path=path)


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
