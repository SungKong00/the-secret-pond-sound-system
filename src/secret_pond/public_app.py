from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_voice_stack import PublicVoiceStackError, PublicVoiceStackService

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_public_app(
    *,
    root: Path | None = None,
    settings: PublicRecorderSettings | None = None,
) -> FastAPI:
    paths = ProjectPaths(Path.cwd() if root is None else root)
    paths.ensure_directories()
    public_settings = settings or PublicRecorderSettings.from_env()

    app = FastAPI(title="The Secret Pond Public Voice Stack Recorder")
    app.state.paths = paths
    app.state.public_settings = public_settings
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/r/{token}")
    def public_recorder(token: str) -> FileResponse:
        if token != public_settings.public_recording_token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(STATIC_DIR / "public_recorder.html")

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
            upload_path = paths.recordings_temp_dir / f"public-upload-{uuid4().hex}{_extension_for_upload(file)}"
            upload_path.write_bytes(content)
            try:
                result = PublicVoiceStackService(paths, public_settings).add_upload_file(upload_path)
            except PublicVoiceStackError as exc:
                raise HTTPException(
                    status_code=_status_for_public_error(exc.code),
                    detail=exc.code,
                ) from exc
            return {
                "version_id": result.history_record.id,
                "stack_path": result.history_record.stack_path,
            }
        finally:
            await file.close()

    return app


def _extension_for_upload(file: UploadFile) -> str:
    name = file.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix and len(suffix) <= 16:
        return suffix
    return ".webm"


def _status_for_public_error(code: str) -> int:
    if code == "lock_timeout":
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_CONTENT
