from __future__ import annotations

import base64
import binascii
import os
import secrets
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryRecord, StackHistoryStore
from secret_pond.services.public_voice_stack import PublicVoiceStackError, PublicVoiceStackService

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_public_app(
    *,
    root: Path | None = None,
    settings: PublicRecorderSettings | None = None,
) -> FastAPI:
    paths = ProjectPaths(_default_root() if root is None else root)
    paths.ensure_directories()
    public_settings = settings or PublicRecorderSettings.from_env()

    app = FastAPI(title="The Secret Pond Public Voice Stack Recorder")
    app.state.paths = paths
    app.state.public_settings = public_settings
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_admin(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        credentials = _parse_basic_authorization(authorization)
        if credentials is None:
            raise _admin_auth_error()
        username, password = credentials
        valid_username = secrets.compare_digest(
            username,
            public_settings.admin_username,
        )
        valid_password = secrets.compare_digest(
            password,
            public_settings.admin_password,
        )
        if not (valid_username and valid_password):
            raise _admin_auth_error()

    @app.get("/r/{token}")
    def public_recorder(token: str) -> FileResponse:
        if token != public_settings.public_recording_token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(STATIC_DIR / "public_recorder.html")

    @app.get("/admin", dependencies=[Depends(require_admin)])
    def admin_history() -> FileResponse:
        return FileResponse(STATIC_DIR / "public_admin.html")

    @app.post("/api/public/recordings", status_code=status.HTTP_201_CREATED)
    async def upload_public_recording(
        file: Annotated[UploadFile, File()],
        x_public_recording_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        try:
            if x_public_recording_token != public_settings.public_recording_token:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_token")

            content = await file.read(public_settings.max_upload_bytes + 1)
            if len(content) > public_settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="file_too_large",
                )
            upload_path = (
                paths.recordings_temp_dir
                / f"public-upload-{uuid4().hex}{_extension_for_upload(file)}"
            )
            upload_path.write_bytes(content)
            try:
                stack_service = PublicVoiceStackService(paths, public_settings)
                result = stack_service.add_upload_file(upload_path)
            except PublicVoiceStackError as exc:
                raise HTTPException(
                    status_code=_status_for_public_error(exc.code),
                    detail=exc.code,
                ) from exc
            except Exception as exc:
                upload_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="processing_failed",
                ) from exc
            return {
                "version_id": result.history_record.id,
                "stack_path": result.history_record.stack_path,
            }
        finally:
            await file.close()

    @app.get("/admin/versions", dependencies=[Depends(require_admin)])
    def list_admin_versions() -> dict[str, list[dict[str, str | int | float | None]]]:
        versions = StackHistoryStore(paths.public_history_file).list_versions()
        return {"versions": [_history_record_to_dict(version) for version in versions]}

    @app.get("/admin/versions/latest/download", dependencies=[Depends(require_admin)])
    def download_latest_stack_version() -> FileResponse:
        record = StackHistoryStore(paths.public_history_file).latest()
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
        return _download_response_for_record(paths, record)

    @app.get("/admin/versions/{version_id}/preview", dependencies=[Depends(require_admin)])
    def preview_stack_version(version_id: str) -> FileResponse:
        record = StackHistoryStore(paths.public_history_file).get(version_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
        return _preview_response_for_record(paths, record)

    @app.get("/admin/versions/{version_id}/download", dependencies=[Depends(require_admin)])
    def download_stack_version(version_id: str) -> FileResponse:
        record = StackHistoryStore(paths.public_history_file).get(version_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
        return _download_response_for_record(paths, record)

    @app.delete("/admin/versions/{version_id}", dependencies=[Depends(require_admin)])
    def delete_stack_version(version_id: str) -> dict[str, dict[str, str | int | float | None]]:
        history = StackHistoryStore(paths.public_history_file)
        record = history.get(version_id)
        if record is None or record.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
        stack_path = _stack_path_for_record(
            paths,
            record,
            include_deleted=True,
            require_exists=False,
        )
        stack_path.unlink(missing_ok=True)
        deleted = history.mark_deleted(version_id)
        if deleted is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
        return {"version": _history_record_to_dict(deleted)}

    return app


def _extension_for_upload(file: UploadFile) -> str:
    name = file.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix and len(suffix) <= 16:
        return suffix
    return ".webm"


def _default_root() -> Path:
    return Path(os.environ.get("APP_DATA_DIR", Path.cwd()))


def _status_for_public_error(code: str) -> int:
    if code == "lock_timeout":
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_CONTENT


def _admin_auth_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="admin_auth_required",
        headers={"WWW-Authenticate": "Basic"},
    )


def _parse_basic_authorization(authorization: str | None) -> tuple[str, str] | None:
    if authorization is None:
        return None
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def _history_record_to_dict(
    record: StackHistoryRecord,
) -> dict[str, str | int | float | None]:
    return {
        "id": record.id,
        "kind": record.kind,
        "created_at": record.created_at,
        "parent_version_id": record.parent_version_id,
        "stack_path": record.stack_path,
        "duration_seconds": record.duration_seconds,
        "file_size": record.file_size,
        "sha256": record.sha256,
        "added_chunks": record.added_chunks,
        "peak_before_guard": record.peak_before_guard,
        "peak_after_guard": record.peak_after_guard,
        "gain_reduction_db": record.gain_reduction_db,
        "deleted_at": record.deleted_at,
        "level_guard_rms_dbfs": record.level_guard_rms_dbfs,
        "level_guard_gain_db": record.level_guard_gain_db,
        "level_guard_peak_after": record.level_guard_peak_after,
    }


def _download_response_for_record(paths: ProjectPaths, record: StackHistoryRecord) -> FileResponse:
    stack_path = _stack_path_for_record(paths, record)
    return FileResponse(
        stack_path,
        media_type="audio/wav",
        filename=f"{record.id}.wav",
    )


def _preview_response_for_record(paths: ProjectPaths, record: StackHistoryRecord) -> FileResponse:
    stack_path = _stack_path_for_record(paths, record)
    return FileResponse(
        stack_path,
        media_type="audio/wav",
    )


def _stack_path_for_record(
    paths: ProjectPaths,
    record: StackHistoryRecord,
    *,
    include_deleted: bool = False,
    require_exists: bool = True,
) -> Path:
    if record.deleted_at is not None and not include_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
    raw_path = Path(record.stack_path)
    stack_path = raw_path if raw_path.is_absolute() else paths.root / raw_path
    resolved = stack_path.resolve()
    try:
        resolved.relative_to(paths.root.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="version_not_found",
        ) from exc
    if require_exists and (not resolved.exists() or not resolved.is_file()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version_not_found")
    return resolved
