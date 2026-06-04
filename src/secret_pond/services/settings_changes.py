from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from secret_pond.config import AppSettings


@dataclass(frozen=True)
class SettingsChangePlan:
    runtime_config_changed: bool
    changed_runtime_fields: list[str]
    changed_sections: list[str]


_RuntimeFieldReader = Callable[[AppSettings], Any]

_RUNTIME_CONFIG_FIELDS: tuple[tuple[str, _RuntimeFieldReader], ...] = (
    ("audio.sample_rate", lambda settings: settings.audio.sample_rate),
    ("audio.channels", lambda settings: settings.audio.channels),
    ("devices.input_device_id", lambda settings: settings.devices.input_device_id),
    ("devices.output_device_id", lambda settings: settings.devices.output_device_id),
)


def runtime_config_field_names() -> list[str]:
    return [field_name for field_name, _read_field in _RUNTIME_CONFIG_FIELDS]


def classify_settings_change(active: AppSettings, draft: AppSettings) -> SettingsChangePlan:
    changed_runtime_fields = _changed_runtime_fields(active, draft)
    return SettingsChangePlan(
        runtime_config_changed=bool(changed_runtime_fields),
        changed_runtime_fields=changed_runtime_fields,
        changed_sections=_changed_sections(active, draft),
    )


def promote_runtime_config(active: AppSettings, draft: AppSettings) -> AppSettings:
    return active.model_copy(
        update={
            "audio": active.audio.model_copy(
                update={
                    "sample_rate": draft.audio.sample_rate,
                    "channels": draft.audio.channels,
                }
            ),
            "devices": draft.devices,
        },
        deep=True,
    )


def _changed_runtime_fields(active: AppSettings, draft: AppSettings) -> list[str]:
    changed: list[str] = []
    for field_name, read_field in _RUNTIME_CONFIG_FIELDS:
        if read_field(active) != read_field(draft):
            changed.append(field_name)
    return changed


def _changed_sections(active: AppSettings, draft: AppSettings) -> list[str]:
    changed: list[str] = []
    active_payload = active.model_dump(mode="json")
    draft_payload = draft.model_dump(mode="json")
    for section in sorted(active_payload):
        if active_payload[section] != draft_payload.get(section):
            changed.append(section)
    return changed
