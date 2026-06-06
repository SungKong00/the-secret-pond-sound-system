from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal, Protocol

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
    portaudio_index: int | None = None


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
        selected = next((device for device in devices if device.id == device_id), None)
        if selected is not None:
            return selected
        legacy_selected = _legacy_portaudio_device(device_id, devices)
        if legacy_selected is not None:
            return legacy_selected
        if _is_legacy_portaudio_id(device_id):
            return devices[0] if devices else None
        return None

    def _list_devices(self) -> list[AudioDeviceInfo]:
        import sounddevice as sd

        host_apis = sd.query_hostapis()
        candidates: list[dict[str, Any]] = []
        for index, raw in enumerate(sd.query_devices()):
            default_sample_rate = raw.get("default_samplerate")
            sample_rate = int(default_sample_rate) if default_sample_rate else None
            max_input = int(raw.get("max_input_channels", 0))
            max_output = int(raw.get("max_output_channels", 0))
            name = str(raw.get("name", f"Device {index}"))
            host_api_name = _host_api_name(host_apis, raw.get("hostapi"))

            if max_input > 0:
                candidates.append(
                    {
                        "index": index,
                        "name": name,
                        "kind": "input",
                        "max_input_channels": max_input,
                        "max_output_channels": max_output,
                        "default_sample_rate": sample_rate,
                        "host_api_name": host_api_name,
                    }
                )

            if max_output > 0:
                candidates.append(
                    {
                        "index": index,
                        "name": name,
                        "kind": "output",
                        "max_input_channels": max_input,
                        "max_output_channels": max_output,
                        "default_sample_rate": sample_rate,
                        "host_api_name": host_api_name,
                    }
                )

        return _audio_devices_from_candidates(candidates)


def stream_device_id(
    device: AudioDeviceInfo | None,
    configured_device_id: str | None,
) -> str | None:
    if configured_device_id is None:
        return None
    if device and device.portaudio_index is not None:
        return str(device.portaudio_index)
    return configured_device_id


def _host_api_name(host_apis: object, host_api_index: object) -> str | None:
    if host_api_index is None:
        return None
    try:
        host_api = host_apis[int(host_api_index)]  # type: ignore[index]
    except (IndexError, TypeError, ValueError):
        return None
    name = host_api.get("name") if isinstance(host_api, dict) else None
    return str(name) if name else None


def _audio_devices_from_candidates(candidates: list[dict[str, Any]]) -> list[AudioDeviceInfo]:
    seen: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    devices: list[AudioDeviceInfo] = []
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        seen[identity] += 1
        occurrence = seen[identity]
        stable_id = _stable_device_id(
            kind=candidate["kind"],
            host_api_name=candidate["host_api_name"],
            name=candidate["name"],
            occurrence=occurrence,
        )
        devices.append(
            AudioDeviceInfo(
                id=stable_id,
                name=candidate["name"],
                kind=candidate["kind"],
                max_input_channels=candidate["max_input_channels"],
                max_output_channels=candidate["max_output_channels"],
                default_sample_rate=candidate["default_sample_rate"],
                host_api_name=candidate["host_api_name"],
                portaudio_index=candidate["index"],
            )
        )
    return devices


def _candidate_identity(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate["kind"]),
        _identity_text(candidate["host_api_name"]),
        _identity_text(candidate["name"]),
    )


def _stable_device_id(
    *,
    kind: str,
    host_api_name: str | None,
    name: str,
    occurrence: int,
) -> str:
    host = host_api_name or "default-host"
    material = "\0".join([kind, host, name, str(occurrence)])
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:10]
    return f"{kind}:{_slug(host)}:{_slug(name)}:{digest}"


def _identity_text(value: object) -> str:
    return str(value or "").casefold().strip()


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or "device"


def _legacy_portaudio_device(
    device_id: str,
    devices: list[AudioDeviceInfo],
) -> AudioDeviceInfo | None:
    if not _is_legacy_portaudio_id(device_id):
        return None
    index = int(device_id)
    return next((device for device in devices if device.portaudio_index == index), None)


def _is_legacy_portaudio_id(device_id: str) -> bool:
    return device_id.isdigit()
