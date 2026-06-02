from __future__ import annotations

from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry


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
