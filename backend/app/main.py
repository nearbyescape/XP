"""FastAPI application (uvicorn app.main:app)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from . import __version__, db, log
from .api import admin, public, stream
from .config import get_settings

NOINDEX = "noindex, nofollow, noarchive, nosnippet, noimageindex, notranslate"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.setup(settings.log_level)
    db.configure(settings.database_url)
    stream.broadcaster.start()
    yield
    await stream.broadcaster.stop()
    await db.engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.environment == "production":
        key = settings.secret_key.get_secret_value()
        if key == "change-me" or len(key) < 32:
            raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters")
    app = FastAPI(title=f"{settings.app_name} API", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs" if settings.environment != "production" else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if settings.environment != "production" else None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if not settings.indexing_allowed:
            response.headers["X-Robots-Tag"] = NOINDEX
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path.startswith("/api/") and request.url.path != "/api/stream":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/robots.txt", include_in_schema=False)
    async def robots():  # served by nginx in production; here for direct API access
        crawlable = settings.search_indexing in ("true", "deindex")
        body = "User-agent: *\nAllow: /\n" if crawlable else "User-agent: *\nDisallow: /\n"
        return PlainTextResponse(body)

    app.include_router(public.open_router)
    app.include_router(public.router)
    app.include_router(stream.router)
    app.include_router(admin.router)
    return app


app = create_app()
