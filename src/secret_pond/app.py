from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse


def create_app() -> FastAPI:
    app = FastAPI(title="The Secret Pond Sound System")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/health")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
