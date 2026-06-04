from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

DeviceKind = Literal["input", "output"]


@dataclass(frozen=True)
class AudioDeviceInfo:
    id: str
    name: str
    kind: DeviceKind
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: int | None
    host_api_name: str | None = None


class AudioDeviceRegistry(Protocol):
    def list_input_devices(self) -> list[AudioDeviceInfo]: ...

    def list_output_devices(self) -> list[AudioDeviceInfo]: ...

    def validate_input(self, device_id: str | None) -> AudioDeviceInfo | None: ...

    def validate_output(self, device_id: str | None) -> AudioDeviceInfo | None: ...


class FakeDeviceRegistry:
    def __init__(self, devices: list[AudioDeviceInfo]) -> None:
        self._devices = devices

    def list_input_devices(self) -> list[AudioDeviceInfo]:
        return [device for device in self._devices if device.kind == "input"]

    def list_output_devices(self) -> list[AudioDeviceInfo]:
        return [device for device in self._devices if device.kind == "output"]

    def validate_input(self, device_id: str | None) -> AudioDeviceInfo | None:
        return self._validate(device_id, "input")

    def validate_output(self, device_id: str | None) -> AudioDeviceInfo | None:
        return self._validate(device_id, "output")

    def _validate(self, device_id: str | None, kind: DeviceKind) -> AudioDeviceInfo | None:
        devices = self.list_input_devices() if kind == "input" else self.list_output_devices()
        if device_id is None:
            return devices[0] if devices else None
        return next((device for device in devices if device.id == device_id), None)


class SoundDeviceRegistry:
    def list_input_devices(self) -> list[AudioDeviceInfo]:
        return [device for device in self._list_devices() if device.kind == "input"]

    def list_output_devices(self) -> list[AudioDeviceInfo]:
        return [device for device in self._list_devices() if device.kind == "output"]

    def validate_input(self, device_id: str | None) -> AudioDeviceInfo | None:
        return self._validate(device_id, "input")

    def validate_output(self, device_id: str | None) -> AudioDeviceInfo | None:
        return self._validate(device_id, "output")

    def _validate(self, device_id: str | None, kind: DeviceKind) -> AudioDeviceInfo | None:
        devices = self.list_input_devices() if kind == "input" else self.list_output_devices()
        if device_id is None:
            return devices[0] if devices else None
        return next((device for device in devices if device.id == device_id), None)

    def _list_devices(self) -> list[AudioDeviceInfo]:
        import sounddevice as sd

        devices: list[AudioDeviceInfo] = []
        host_apis = sd.query_hostapis()
        for index, raw in enumerate(sd.query_devices()):
            default_sample_rate = raw.get("default_samplerate")
            sample_rate = int(default_sample_rate) if default_sample_rate else None
            max_input = int(raw.get("max_input_channels", 0))
            max_output = int(raw.get("max_output_channels", 0))
            name = str(raw.get("name", f"Device {index}"))
            host_api_name = _host_api_name(host_apis, raw.get("hostapi"))

            if max_input > 0:
                devices.append(
                    AudioDeviceInfo(
                        id=str(index),
                        name=name,
                        kind="input",
                        max_input_channels=max_input,
                        max_output_channels=max_output,
                        default_sample_rate=sample_rate,
                        host_api_name=host_api_name,
                    )
                )

            if max_output > 0:
                devices.append(
                    AudioDeviceInfo(
                        id=str(index),
                        name=name,
                        kind="output",
                        max_input_channels=max_input,
                        max_output_channels=max_output,
                        default_sample_rate=sample_rate,
                        host_api_name=host_api_name,
                    )
                )

        return devices


def _host_api_name(host_apis: object, host_api_index: object) -> str | None:
    if host_api_index is None:
        return None
    try:
        host_api = host_apis[int(host_api_index)]  # type: ignore[index]
    except (IndexError, TypeError, ValueError):
        return None
    name = host_api.get("name") if isinstance(host_api, dict) else None
    return str(name) if name else None
