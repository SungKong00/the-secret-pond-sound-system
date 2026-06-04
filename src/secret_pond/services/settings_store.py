from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths

_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SettingsState:
    active: AppSettings
    draft: AppSettings


class SettingsStore:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def load(self) -> SettingsState:
        if not self._paths.settings_file.exists():
            default_state = SettingsState(active=AppSettings(), draft=AppSettings())
            self.save(default_state)
            return default_state

        payload = _read_settings_payload(self._paths.settings_file)
        return _state_from_payload(payload)

    def load_for_startup(self) -> SettingsState:
        state = self.load()
        if _startup_configuration_changed(state.active, state.draft):
            return self.save(
                SettingsState(
                    active=_active_with_startup_fields(state.active, state.draft),
                    draft=state.draft,
                )
            )
        return state

    def save(self, state: SettingsState) -> SettingsState:
        validated = SettingsState(
            active=_validated_settings_copy(state.active),
            draft=_validated_settings_copy(state.draft),
        )
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "active": validated.active.model_dump(mode="json"),
            "draft": validated.draft.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

        self._paths.ensure_directories()
        temp_path = self._paths.config_dir / f"settings.json.{uuid4().hex}.tmp"
        try:
            temp_path.write_text(f"{encoded}\n", encoding="utf-8")
            temp_path.replace(self._paths.settings_file)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return validated

    def set_draft(self, draft: AppSettings) -> SettingsState:
        current = self.load()
        return self.save(SettingsState(active=current.active, draft=draft))

    def apply_draft(self) -> SettingsState:
        current = self.load()
        return self.save(SettingsState(active=current.draft, draft=current.draft))

    def reset_draft(self) -> SettingsState:
        current = self.load()
        return self.save(SettingsState(active=current.active, draft=current.active))


def _read_settings_payload(path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = "settings file contains invalid JSON"
        raise ValueError(msg) from exc
    except OSError as exc:
        msg = "settings file cannot be read"
        raise ValueError(msg) from exc

    if not isinstance(payload, dict):
        msg = "settings file must contain a JSON object"
        raise ValueError(msg)
    return payload


def _state_from_payload(payload: dict[str, Any]) -> SettingsState:
    if payload.get("schema_version") != _SCHEMA_VERSION:
        msg = "settings schema_version is unsupported"
        raise ValueError(msg)
    if set(payload) != {"schema_version", "active", "draft"}:
        msg = "settings file must contain schema_version, active, and draft"
        raise ValueError(msg)

    active_payload = _validated_settings_payload(payload["active"], "active")
    draft_payload = _validated_settings_payload(payload["draft"], "draft")
    return SettingsState(
        active=AppSettings.model_validate(active_payload),
        draft=AppSettings.model_validate(draft_payload),
    )


def _validated_settings_payload(payload: Any, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        msg = f"settings {key} must be a JSON object"
        raise ValueError(msg)
    expected = set(AppSettings.model_fields)
    actual = set(payload)
    missing = expected - actual
    extra = actual - expected
    if extra or missing - {"sources"}:
        msg = f"settings {key} is missing required keys"
        raise ValueError(msg)
    if "sources" not in payload:
        return {
            **payload,
            "sources": AppSettings().sources.model_dump(mode="json"),
        }
    return payload


def _validated_settings_copy(settings: AppSettings) -> AppSettings:
    return AppSettings.model_validate(settings.model_dump(mode="json"))


def _startup_configuration_changed(active: AppSettings, draft: AppSettings) -> bool:
    return (
        active.audio.sample_rate != draft.audio.sample_rate
        or active.audio.channels != draft.audio.channels
        or active.devices.input_device_id != draft.devices.input_device_id
        or active.devices.output_device_id != draft.devices.output_device_id
    )


def _active_with_startup_fields(active: AppSettings, draft: AppSettings) -> AppSettings:
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
