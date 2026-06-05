from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from secret_pond.audio.file_io import read_wav
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths

SourceCategory = Literal["low", "mid", "voice_raw", "voice_stack"]


@dataclass(frozen=True)
class SourceCategoryConfig:
    id: SourceCategory
    label: str
    directory_name: str
    settings_field: str
    legacy_attr: str | None = None
    required: bool = True


SOURCE_CATEGORIES: dict[SourceCategory, SourceCategoryConfig] = {
    "low": SourceCategoryConfig(
        id="low",
        label="Low Source",
        directory_name="low_sources_dir",
        settings_field="low_path",
        legacy_attr="low_source",
    ),
    "mid": SourceCategoryConfig(
        id="mid",
        label="Mid Source",
        directory_name="mid_sources_dir",
        settings_field="mid_path",
        legacy_attr="mid_source",
    ),
    "voice_raw": SourceCategoryConfig(
        id="voice_raw",
        label="Voice Raw",
        directory_name="voice_raw_sources_dir",
        settings_field="voice_raw_path",
        required=False,
    ),
    "voice_stack": SourceCategoryConfig(
        id="voice_stack",
        label="Voice Stack",
        directory_name="voice_stack_sources_dir",
        settings_field="voice_stack_path",
        legacy_attr="voice_stack_raw",
    ),
}

RENDER_LAYER_CATEGORY: dict[str, SourceCategory] = {
    "low": "low",
    "mid": "mid",
    "voice": "voice_stack",
}


def source_category_ids() -> tuple[SourceCategory, ...]:
    return ("low", "mid", "voice_raw", "voice_stack")


def category_config(category: str) -> SourceCategoryConfig:
    if category not in SOURCE_CATEGORIES:
        msg = f"unknown source category: {category}"
        raise ValueError(msg)
    return SOURCE_CATEGORIES[category]  # type: ignore[index,return-value]


def category_directory(paths: ProjectPaths, category: str) -> Path:
    config = category_config(category)
    return getattr(paths, config.directory_name)


def selected_source_path(
    paths: ProjectPaths,
    settings: AppSettings,
    category: SourceCategory,
) -> Path | None:
    config = SOURCE_CATEGORIES[category]
    selected = getattr(settings.sources, config.settings_field)
    if selected:
        return resolve_category_path(paths, category, selected)
    if config.legacy_attr is None:
        return None
    return getattr(paths, config.legacy_attr)


def render_source_path(paths: ProjectPaths, settings: AppSettings, layer_id: str) -> Path:
    if layer_id not in RENDER_LAYER_CATEGORY:
        msg = f"unknown layer id: {layer_id}"
        raise ValueError(msg)
    path = selected_source_path(paths, settings, RENDER_LAYER_CATEGORY[layer_id])
    if path is None:
        msg = f"{layer_id} source file is not selected"
        raise FileNotFoundError(msg)
    return path


def source_library_payload(
    paths: ProjectPaths,
    settings: AppSettings,
    *,
    active_settings: AppSettings | None = None,
) -> dict[str, Any]:
    return {
        "categories": [
            category_payload(paths, settings, category_id, active_settings=active_settings)
            for category_id in source_category_ids()
        ],
    }


def category_payload(
    paths: ProjectPaths,
    settings: AppSettings,
    category: SourceCategory,
    *,
    active_settings: AppSettings | None = None,
) -> dict[str, Any]:
    config = SOURCE_CATEGORIES[category]
    selected = getattr(settings.sources, config.settings_field)
    active = selected_source_path(paths, settings, category)
    active_relative = _relative_path(paths.root, active) if active is not None else None
    applied = selected_source_path(paths, active_settings or settings, category)
    applied_relative = _relative_path(paths.root, applied) if applied is not None else None
    directory = category_directory(paths, category)
    files = [
        _source_file_payload(paths, file_path, active_relative, applied_relative)
        for file_path in _wav_files(directory)
    ]
    legacy = getattr(paths, config.legacy_attr) if config.legacy_attr is not None else None
    legacy_stat = legacy.stat() if legacy is not None and legacy.exists() else None
    return {
        "id": config.id,
        "label": config.label,
        "settings_field": config.settings_field,
        "required": config.required,
        "directory": _relative_path(paths.root, directory),
        "selected_path": selected,
        "active_path": active_relative,
        "active_exists": active.exists() if active is not None else False,
        "legacy_path": _relative_path(paths.root, legacy) if legacy is not None else None,
        "legacy_exists": legacy.exists() if legacy is not None else False,
        "legacy_size_bytes": legacy_stat.st_size if legacy_stat is not None else 0,
        "legacy_modified_at": (
            datetime.fromtimestamp(legacy_stat.st_mtime, UTC).isoformat()
            if legacy_stat is not None
            else None
        ),
        "files": files,
    }


def upload_source_file(
    paths: ProjectPaths,
    category: SourceCategory,
    *,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    directory = category_directory(paths, category)
    directory.mkdir(parents=True, exist_ok=True)
    basename = _safe_wav_filename(filename)
    destination = directory / basename
    if destination.exists():
        msg = f"source file already exists: {basename}"
        raise FileExistsError(msg)

    temp_path = directory / f".{destination.stem}.{uuid4().hex}.tmp.wav"
    try:
        temp_path.write_bytes(content)
        read_wav(temp_path)
        temp_path.replace(destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return _source_file_payload(paths, destination, active_relative=None, applied_relative=None)


def delete_source_file(
    paths: ProjectPaths,
    category: SourceCategory,
    relative_path: str,
    *,
    active_settings: AppSettings | None = None,
    draft_settings: AppSettings | None = None,
) -> None:
    path = resolve_category_path(paths, category, relative_path)
    if active_settings is not None and source_file_is_selected(
        paths,
        active_settings,
        category,
        relative_path,
    ):
        msg = "cannot delete the active source file"
        raise PermissionError(msg)
    if draft_settings is not None and source_file_is_selected(
        paths,
        draft_settings,
        category,
        relative_path,
    ):
        msg = "cannot delete the draft source file"
        raise PermissionError(msg)
    path.unlink()


def rename_source_file(
    paths: ProjectPaths,
    category: SourceCategory,
    relative_path: str,
    stem: str,
) -> str:
    path = resolve_category_path(paths, category, relative_path)
    next_stem = _safe_filename_stem(stem)
    destination = path.with_name(f"{next_stem}{path.suffix}")
    if destination == path:
        return _relative_path(paths.root, path)
    if destination.exists():
        msg = f"source file already exists: {destination.name}"
        raise FileExistsError(msg)
    path.replace(destination)
    return _relative_path(paths.root, destination)


def source_file_is_selected(
    paths: ProjectPaths,
    settings: AppSettings,
    category: SourceCategory,
    relative_path: str,
) -> bool:
    path = resolve_category_path(paths, category, relative_path)
    active = selected_source_path(paths, settings, category)
    return active is not None and path.resolve() == active.resolve()


def select_source(
    settings: AppSettings,
    category: SourceCategory,
    relative_path: str | None,
) -> AppSettings:
    config = SOURCE_CATEGORIES[category]
    if relative_path is not None:
        _validated_relative_wav_path(relative_path)
    return settings.model_copy(
        update={
            "sources": settings.sources.model_copy(
                update={config.settings_field: relative_path},
            )
        },
        deep=True,
    )


def select_existing_source(
    paths: ProjectPaths,
    settings: AppSettings,
    category: SourceCategory,
    relative_path: str | None,
) -> AppSettings:
    next_settings = select_source(settings, category, relative_path)
    if relative_path is not None:
        selected = selected_source_path(paths, next_settings, category)
        if selected is None or not selected.exists():
            msg = f"source file does not exist: {relative_path}"
            raise FileNotFoundError(msg)
    return next_settings


def resolve_category_path(
    paths: ProjectPaths,
    category: SourceCategory,
    relative_path: str,
) -> Path:
    _validated_relative_wav_path(relative_path)
    resolved = (paths.root / PurePosixPath(relative_path)).resolve()
    category_root = category_directory(paths, category).resolve()
    if not resolved.is_relative_to(category_root):
        msg = f"source path must stay under {category}"
        raise ValueError(msg)
    return resolved


def _source_file_payload(
    paths: ProjectPaths,
    path: Path,
    active_relative: str | None,
    applied_relative: str | None,
) -> dict[str, Any]:
    stat = path.stat()
    relative = _relative_path(paths.root, path)
    return {
        "name": path.name,
        "path": relative,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "active": relative == active_relative,
        "applied": relative == applied_relative,
    }


def _wav_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".wav"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def _validated_relative_wav_path(relative_path: str) -> PurePosixPath:
    normalized = relative_path.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        msg = "source path must be relative to the project root"
        raise ValueError(msg)
    if path.suffix.lower() != ".wav":
        msg = "source path must point to a .wav file"
        raise ValueError(msg)
    return path


def _safe_wav_filename(filename: str) -> str:
    basename = Path(filename).name.strip()
    if not basename or basename != filename or PurePosixPath(basename).suffix.lower() != ".wav":
        msg = "filename must be a plain .wav filename"
        raise ValueError(msg)
    return basename


def _safe_filename_stem(stem: str) -> str:
    basename = Path(stem).name.strip()
    if not basename or basename != stem:
        msg = "filename stem must be a plain filename"
        raise ValueError(msg)
    if PurePosixPath(basename).suffix:
        msg = "filename stem must not include an extension"
        raise ValueError(msg)
    return basename


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
