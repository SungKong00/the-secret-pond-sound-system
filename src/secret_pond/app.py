from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from secret_pond.services.runtime import SecretPondRuntime, build_runtime
from secret_pond.web.routes import router as api_router


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

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/health")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(api_router)
    return app


app = create_app()
