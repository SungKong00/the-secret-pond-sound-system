from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from secret_pond.audio.source_library import (
    delete_source_file,
    select_existing_source,
    upload_source_file,
)
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_store import SettingsState


class SourceLibraryMutationError(RuntimeError):
    """Raised when a source library mutation cannot be completed atomically."""


@dataclass(frozen=True)
class SourceUploadMutationResult:
    file: dict[str, Any]
    settings_state: SettingsState


def select_source_file_and_update_draft(
    runtime: SecretPondRuntime,
    category: str,
    relative_path: str | None,
) -> SettingsState:
    try:
        settings_state = runtime.settings_store.patch_draft(
            lambda draft: select_existing_source(
                runtime.paths,
                draft,
                category,
                relative_path,
            ),
        )
    except (FileNotFoundError, ValueError):
        raise
    except Exception as exc:
        raise SourceLibraryMutationError(str(exc)) from exc
    runtime.settings_state = settings_state
    return settings_state


def delete_source_file_from_library(
    runtime: SecretPondRuntime,
    category: str,
    relative_path: str,
    *,
    settings_state: SettingsState,
) -> SettingsState:
    delete_source_file(
        runtime.paths,
        category,
        relative_path,
        active_settings=settings_state.active,
        draft_settings=settings_state.draft,
    )
    return settings_state


def upload_source_file_and_maybe_select(
    runtime: SecretPondRuntime,
    category: str,
    *,
    filename: str,
    content: bytes,
    select_after_upload: bool,
) -> SourceUploadMutationResult:
    file_payload = upload_source_file(
        runtime.paths,
        category,
        filename=filename,
        content=content,
    )
    if not select_after_upload:
        return SourceUploadMutationResult(
            file=file_payload,
            settings_state=runtime.settings_store.load(),
        )

    try:
        settings_state = runtime.settings_store.patch_draft(
            lambda draft: select_existing_source(
                runtime.paths,
                draft,
                category,
                file_payload["path"],
            ),
        )
    except Exception as exc:
        _rollback_uploaded_source_file(runtime, category, file_payload["path"])
        raise SourceLibraryMutationError(str(exc)) from exc

    runtime.settings_state = settings_state
    return SourceUploadMutationResult(file=file_payload, settings_state=settings_state)


def _rollback_uploaded_source_file(
    runtime: SecretPondRuntime,
    category: str,
    relative_path: str,
) -> None:
    with suppress(OSError, ValueError):
        delete_source_file(runtime.paths, category, relative_path)
