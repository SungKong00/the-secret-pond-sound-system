from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from secret_pond.services.file_snapshots import (
    FileSnapshot,
    capture_file_snapshot,
    restore_file_snapshot,
)
from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.services.settings_store import SettingsState

_T = TypeVar("_T")


class RecordingControlError(RuntimeError):
    """Raised when a recording control fails after best-effort rollback."""


@dataclass(frozen=True)
class RecordingSideEffectSnapshot:
    voice_stack_raw: FileSnapshot
    voice_manifest: FileSnapshot
    voice_playback: FileSnapshot
    voice_raw_files: set[Path]
    voice_stack_files: set[Path]
    accepted_files: set[Path]
    controller_sources: Any
    settings_state: SettingsState


def run_recording_transaction(runtime: SecretPondRuntime, control: Callable[[], _T]) -> _T:
    snapshot = capture_recording_side_effects(runtime)
    try:
        return control()
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        rollback_detail = restore_recording_side_effects(runtime, snapshot)
        detail = str(exc)
        if rollback_detail:
            detail = f"{detail}; rollback issues: {rollback_detail}"
        raise RecordingControlError(detail) from exc


def capture_recording_side_effects(
    runtime: SecretPondRuntime,
) -> RecordingSideEffectSnapshot:
    paths = runtime.paths
    current = runtime.settings_store.load()
    return RecordingSideEffectSnapshot(
        voice_stack_raw=capture_file_snapshot(paths.voice_stack_raw),
        voice_manifest=capture_file_snapshot(paths.voice_manifest),
        voice_playback=capture_file_snapshot(paths.voice_playback),
        voice_raw_files=set(paths.voice_raw_sources_dir.glob("*.wav")),
        voice_stack_files=set(paths.voice_stack_sources_dir.glob("*.wav")),
        accepted_files=set(paths.accepted_dir.glob("*.wav")),
        controller_sources=runtime.controller.settings.sources.model_copy(deep=True),
        settings_state=SettingsState(
            active=current.active.model_copy(deep=True),
            draft=current.draft.model_copy(deep=True),
        ),
    )


def restore_recording_side_effects(
    runtime: SecretPondRuntime,
    snapshot: RecordingSideEffectSnapshot,
) -> str:
    paths = runtime.paths
    rollback_errors: list[str] = []
    for path, file_snapshot in (
        (paths.voice_stack_raw, snapshot.voice_stack_raw),
        (paths.voice_manifest, snapshot.voice_manifest),
        (paths.voice_playback, snapshot.voice_playback),
    ):
        try:
            restore_file_snapshot(path, file_snapshot)
        except Exception as exc:
            rollback_errors.append(f"{path.name} restore failed: {exc}")

    for directory, before in (
        (paths.voice_raw_sources_dir, snapshot.voice_raw_files),
        (paths.voice_stack_sources_dir, snapshot.voice_stack_files),
        (paths.accepted_dir, snapshot.accepted_files),
    ):
        try:
            _remove_new_wavs(directory, before)
        except Exception as exc:
            rollback_errors.append(f"{directory.name} cleanup failed: {exc}")

    try:
        runtime.controller.settings.sources = snapshot.controller_sources.model_copy(deep=True)
    except Exception as exc:
        rollback_errors.append(f"controller source restore failed: {exc}")
    try:
        runtime.settings_store.save(snapshot.settings_state)
        runtime.settings_state = snapshot.settings_state
    except Exception as exc:
        rollback_errors.append(f"settings restore failed: {exc}")

    return "; ".join(rollback_errors)


def _remove_new_wavs(directory: Path, before: set[Path]) -> None:
    for path in set(directory.glob("*.wav")) - before:
        path.unlink(missing_ok=True)
