"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    from .db.database import init_db
    from .db.migration import migrate_if_needed
    from .services.scheduler import start_scheduler, stop_scheduler
    init_db()
    migrate_if_needed()
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="BrushUp", lifespan=lifespan)

    # Routers (must be registered before static files mount)
    from .routers import data, auth, problems, focus, sync_router, chat, resume, settings
    app.include_router(data.router)
    app.include_router(auth.router)
    app.include_router(problems.router)
    app.include_router(focus.router)
    app.include_router(sync_router.router)
    app.include_router(chat.router)
    app.include_router(resume.router)
    app.include_router(settings.router)

    # Static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Catch-all index (must be last)
    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
