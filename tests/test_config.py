from __future__ import annotations

import pytest
from pydantic import ValidationError

from secret_pond.config import AppSettings, EqSettings
from secret_pond.state import RuntimeStatus


def test_default_settings_define_three_layers_and_disarmed_input() -> None:
    settings = AppSettings()

    assert set(settings.layers.keys()) == {"low", "mid", "voice"}
    assert settings.input_control.armed is False
    assert settings.audio.sample_rate == 48_000
    assert settings.audio.channels == 2


def test_eq_gain_range_is_validated() -> None:
    with pytest.raises(ValidationError):
        EqSettings(low_gain_db=99.0)


def test_lowpass_must_be_greater_than_highpass() -> None:
    with pytest.raises(ValidationError):
        EqSettings(highpass_hz=5_000.0, lowpass_hz=1_000.0)


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
