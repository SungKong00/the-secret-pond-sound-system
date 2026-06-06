from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry, SoundDeviceRegistry


def test_fake_device_registry_lists_input_and_output_devices() -> None:
    registry = FakeDeviceRegistry(
        devices=[
            AudioDeviceInfo(
                id="mic-1",
                name="Test Microphone",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
            ),
            AudioDeviceInfo(
                id="speaker-1",
                name="Test Speakers",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=48_000,
            ),
        ]
    )

    assert [device.id for device in registry.list_input_devices()] == ["mic-1"]
    assert [device.id for device in registry.list_output_devices()] == ["speaker-1"]


def test_fake_device_registry_returns_none_for_missing_selected_device() -> None:
    registry = FakeDeviceRegistry(devices=[])

    assert registry.validate_input("missing") is None
    assert registry.validate_output("missing") is None


def test_sounddevice_registry_keeps_stable_ids_when_portaudio_indices_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_apis = [{"name": "Core Audio"}]
    raw_devices = [
        {"name": "Unused Output", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
    ]
    sounddevice = SimpleNamespace(
        query_hostapis=lambda: host_apis,
        query_devices=lambda: raw_devices,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)
    registry = SoundDeviceRegistry()

    original = registry.list_input_devices()[0]
    raw_devices[:] = [
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Unused Output", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    ]
    moved = registry.validate_input(original.id)

    assert moved is not None
    assert moved.id == original.id
    assert moved.portaudio_index == 0


def test_sounddevice_registry_falls_back_from_stale_numeric_index_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sounddevice = SimpleNamespace(
        query_hostapis=lambda: [{"name": "WASAPI"}],
        query_devices=lambda: [
            {
                "name": "Default Mic",
                "hostapi": 0,
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 48_000,
            },
        ],
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    selected = SoundDeviceRegistry().validate_input("3")

    assert selected is not None
    assert selected.name == "Default Mic"
    assert selected.portaudio_index == 0
