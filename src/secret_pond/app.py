from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from secret_pond.services.runtime import SecretPondRuntime, build_runtime
from secret_pond.web.routes import router as api_router
from secret_pond.web.websocket import router as websocket_router

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def create_app(
    runtime: SecretPondRuntime | None = None,
    root: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.runtime is None:
            app.state.runtime = build_runtime(app.state.root)
        yield

    app = FastAPI(title="The Secret Pond Sound System", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.root = root or Path.cwd()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.include_router(api_router)
    app.include_router(websocket_router)
    return app


app = create_app()
