"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router
from .db import init_db
from .services import ServiceError
from .settings import load_settings
from .template_config import load_templates

log = logging.getLogger("workbench")

CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'")


def create_app(data_dir: str | None = None) -> FastAPI:
    settings = load_settings(data_dir)
    init_db(settings.db_path)
    load_templates()  # fail fast on an invalid template configuration

    app = FastAPI(title="Document Review Workbench", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.include_router(router, prefix="/api")

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body", "query", "path"))
            parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return JSONResponse(status_code=422, content={"detail": "; ".join(parts) or "Invalid request."})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.endswith("/content"):
            response.headers.setdefault("Content-Security-Policy", CSP)
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    dist = settings.frontend_dist
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"detail": "Frontend not built. Run 'npm run build' in frontend/, or use the Vite "
                                           "dev server on http://127.0.0.1:5173."})

    log.info("Data directory: %s", settings.data_dir)
    return app
