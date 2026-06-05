from __future__ import annotations

from secret_pond.audio.devices import AudioDeviceInfo, FakeDeviceRegistry
from secret_pond.config import AppSettings
from secret_pond.services.device_inventory import device_inventory_payload, device_payload


def test_device_payload_serializes_optional_audio_device() -> None:
    assert device_payload(None) is None

    payload = device_payload(
        AudioDeviceInfo(
            id="speaker-1",
            name="Main Speakers",
            kind="output",
            max_input_channels=0,
            max_output_channels=2,
            default_sample_rate=44_100,
            host_api_name="WASAPI",
        )
    )

    assert payload == {
        "id": "speaker-1",
        "name": "Main Speakers",
        "kind": "output",
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_sample_rate": 44_100,
        "host_api_name": "WASAPI",
    }


def test_device_inventory_payload_lists_selected_devices_and_readiness_warnings() -> None:
    registry = FakeDeviceRegistry(
        [
            AudioDeviceInfo(
                id="mic-1",
                name="Built-in Mic",
                kind="input",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=48_000,
                host_api_name="Core Audio",
            ),
            AudioDeviceInfo(
                id="speaker-1",
                name="Main Speakers",
                kind="output",
                max_input_channels=0,
                max_output_channels=2,
                default_sample_rate=44_100,
                host_api_name="Core Audio",
            ),
        ]
    )
    settings = AppSettings.model_validate(
        {
            "audio": {"sample_rate": 48_000, "channels": 2},
            "devices": {
                "input_device_id": "missing-mic",
                "output_device_id": "speaker-1",
            },
        }
    )

    payload = device_inventory_payload(registry, settings)

    assert [device["id"] for device in payload["input_devices"]] == ["mic-1"]
    assert [device["id"] for device in payload["output_devices"]] == ["speaker-1"]
    assert payload["selected_input_device"] is None
    assert payload["selected_output_device"]["id"] == "speaker-1"
    assert payload["warnings"] == [
        "Configured input device is unavailable.",
        "Selected output default sample rate is 44100, but settings request 48000.",
    ]
