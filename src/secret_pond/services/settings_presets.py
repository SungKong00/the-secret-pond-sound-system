from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator

from secret_pond.config import (
    AppSettings,
    LayerSettings,
    SourceSelectionSettings,
    VoiceStackSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_store import SettingsState

_SCHEMA_VERSION = 1
_SOURCE_FIELDS = ("low_path", "mid_path", "voice_raw_path", "voice_stack_path")


class PresetPlaybackSettings(BaseModel):
    master_volume_db: float = Field(default=-6.0, ge=-60.0, le=6.0)


class SettingsPresetPayload(BaseModel):
    layers: dict[str, LayerSettings]
    sources: SourceSelectionSettings
    voice_stack: VoiceStackSettings
    playback: PresetPlaybackSettings

    @model_validator(mode="after")
    def validate_layers(self) -> SettingsPresetPayload:
        if set(self.layers) != {"low", "mid", "voice"}:
            msg = "preset layers must contain exactly low, mid, and voice"
            raise ValueError(msg)
        return self


class PresetSourceReference(BaseModel):
    path: str
    size_bytes: int = 0
    modified_at: str | None = None


class SettingsPreset(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    created_at: str
    updated_at: str
    payload: SettingsPresetPayload
    source_refs: dict[str, PresetSourceReference] = Field(default_factory=dict)


class PresetSourceMissingError(FileNotFoundError):
    def __init__(self, missing_sources: list[str]) -> None:
        self.missing_sources = missing_sources
        super().__init__(f"preset references missing source files: {', '.join(missing_sources)}")


class PresetNotFoundError(KeyError):
    def __init__(self, preset_id: str) -> None:
        self.preset_id = preset_id
        super().__init__(f"preset not found: {preset_id}")


class PresetStore:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def list_presets(self) -> list[SettingsPreset]:
        return self._load()

    def create_from_draft(self, name: str, draft: AppSettings) -> SettingsPreset:
        presets = self._load()
        now = _now_iso()
        preset = SettingsPreset(
            id=f"preset-{uuid4().hex}",
            name=_validated_name(name),
            created_at=now,
            updated_at=now,
            payload=_payload_from_settings(draft),
            source_refs=_source_refs(self._paths, draft.sources),
        )
        presets.append(preset)
        self._save(presets)
        return preset

    def update_from_draft(
        self,
        preset_id: str,
        name: str | None,
        draft: AppSettings,
    ) -> SettingsPreset:
        presets = self._load()
        index = _preset_index(presets, preset_id)
        current = presets[index]
        preset = current.model_copy(
            update={
                "name": _validated_name(name) if name is not None else current.name,
                "updated_at": _now_iso(),
                "payload": _payload_from_settings(draft),
                "source_refs": _source_refs(self._paths, draft.sources),
            },
            deep=True,
        )
        presets[index] = preset
        self._save(presets)
        return preset

    def delete(self, preset_id: str) -> None:
        presets = self._load()
        index = _preset_index(presets, preset_id)
        del presets[index]
        self._save(presets)

    def load_to_draft(self, preset_id: str, current: SettingsState) -> SettingsState:
        preset = self.get(preset_id)
        _raise_for_missing_sources(self._paths, preset.payload.sources)
        draft = _apply_payload_to_draft(current.draft, preset.payload)
        return SettingsState(active=current.active, draft=draft)

    def get(self, preset_id: str) -> SettingsPreset:
        presets = self._load()
        return presets[_preset_index(presets, preset_id)]

    def replace_source_path(self, old_path: str, new_path: str) -> list[SettingsPreset]:
        presets = self._load()
        changed: list[SettingsPreset] = []
        next_presets: list[SettingsPreset] = []
        for preset in presets:
            next_preset = _replace_preset_source_path(preset, old_path, new_path)
            next_presets.append(next_preset)
            if next_preset != preset:
                changed.append(next_preset)
        if changed:
            self._save(next_presets)
        return changed

    def preset_names_referencing_source(self, relative_path: str) -> list[str]:
        names: list[str] = []
        for preset in self._load():
            if relative_path in _preset_source_paths(preset):
                names.append(preset.name)
        return names

    def _load(self) -> list[SettingsPreset]:
        if not self._paths.presets_file.exists():
            return []
        payload = _read_presets_payload(self._paths.presets_file)
        return _presets_from_payload(payload)

    def _save(self, presets: list[SettingsPreset]) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "presets": [preset.model_dump(mode="json") for preset in presets],
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        self._paths.ensure_directories()
        temp_path = self._paths.config_dir / f"presets.json.{uuid4().hex}.tmp"
        try:
            temp_path.write_text(f"{encoded}\n", encoding="utf-8")
            temp_path.replace(self._paths.presets_file)
        finally:
            if temp_path.exists():
                temp_path.unlink()


def _payload_from_settings(settings: AppSettings) -> SettingsPresetPayload:
    return SettingsPresetPayload(
        layers={
            layer_id: layer.model_copy(deep=True)
            for layer_id, layer in settings.layers.items()
        },
        sources=settings.sources.model_copy(deep=True),
        voice_stack=settings.voice_stack.model_copy(deep=True),
        playback=PresetPlaybackSettings(master_volume_db=settings.playback.master_volume_db),
    )


def _apply_payload_to_draft(
    draft: AppSettings,
    payload: SettingsPresetPayload,
) -> AppSettings:
    return draft.model_copy(
        update={
            "layers": {
                layer_id: layer.model_copy(deep=True)
                for layer_id, layer in payload.layers.items()
            },
            "sources": payload.sources.model_copy(deep=True),
            "voice_stack": payload.voice_stack.model_copy(deep=True),
            "playback": draft.playback.model_copy(
                update={"master_volume_db": payload.playback.master_volume_db},
            ),
        },
        deep=True,
    )


def _source_refs(
    paths: ProjectPaths,
    sources: SourceSelectionSettings,
) -> dict[str, PresetSourceReference]:
    refs: dict[str, PresetSourceReference] = {}
    for field_name in _SOURCE_FIELDS:
        relative_path = getattr(sources, field_name)
        if relative_path is None:
            continue
        path = paths.root / PurePosixPath(relative_path)
        stat = path.stat() if path.exists() else None
        refs[field_name] = PresetSourceReference(
            path=relative_path,
            size_bytes=stat.st_size if stat is not None else 0,
            modified_at=(
                datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
                if stat is not None
                else None
            ),
        )
    return refs


def _raise_for_missing_sources(paths: ProjectPaths, sources: SourceSelectionSettings) -> None:
    missing = [
        relative_path
        for relative_path in _source_paths(sources)
        if not (paths.root / PurePosixPath(relative_path)).exists()
    ]
    if missing:
        raise PresetSourceMissingError(missing)


def _source_paths(sources: SourceSelectionSettings) -> list[str]:
    return [
        relative_path
        for relative_path in (getattr(sources, field_name) for field_name in _SOURCE_FIELDS)
        if relative_path is not None
    ]


def _preset_source_paths(preset: SettingsPreset) -> list[str]:
    return _source_paths(preset.payload.sources)


def _replace_preset_source_path(
    preset: SettingsPreset,
    old_path: str,
    new_path: str,
) -> SettingsPreset:
    updates: dict[str, str] = {}
    for field_name in _SOURCE_FIELDS:
        if getattr(preset.payload.sources, field_name) == old_path:
            updates[field_name] = new_path
    if not updates:
        return preset
    sources = preset.payload.sources.model_copy(update=updates)
    source_refs = dict(preset.source_refs)
    for field_name in updates:
        current = source_refs.get(field_name)
        source_refs[field_name] = PresetSourceReference(
            path=new_path,
            size_bytes=current.size_bytes if current is not None else 0,
            modified_at=current.modified_at if current is not None else None,
        )
    return preset.model_copy(
        update={
            "updated_at": _now_iso(),
            "payload": preset.payload.model_copy(update={"sources": sources}, deep=True),
            "source_refs": source_refs,
        },
        deep=True,
    )


def _preset_index(presets: list[SettingsPreset], preset_id: str) -> int:
    for index, preset in enumerate(presets):
        if preset.id == preset_id:
            return index
    raise PresetNotFoundError(preset_id)


def _validated_name(name: str | None) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        msg = "preset name is required"
        raise ValueError(msg)
    if len(normalized) > 80:
        msg = "preset name must be 80 characters or fewer"
        raise ValueError(msg)
    return normalized


def _read_presets_payload(path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = "presets file contains invalid JSON"
        raise ValueError(msg) from exc
    except OSError as exc:
        msg = "presets file cannot be read"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = "presets file must contain a JSON object"
        raise ValueError(msg)
    return payload


def _presets_from_payload(payload: dict[str, Any]) -> list[SettingsPreset]:
    if payload.get("schema_version") != _SCHEMA_VERSION:
        msg = "presets schema_version is unsupported"
        raise ValueError(msg)
    raw_presets = payload.get("presets")
    if not isinstance(raw_presets, list):
        msg = "presets file must contain a presets list"
        raise ValueError(msg)
    try:
        return [SettingsPreset.model_validate(raw_preset) for raw_preset in raw_presets]
    except ValidationError as exc:
        msg = "presets file contains invalid preset data"
        raise ValueError(msg) from exc


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
