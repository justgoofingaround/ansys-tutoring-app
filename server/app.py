"""App factory. Run from the repo root:

    .venv\\Scripts\\python -m uvicorn server.app:app --port 8000

Startup: ensures dirs + schema, seeds the instructor from env vars
(INSTRUCTOR_USERNAME / INSTRUCTOR_PASSWORD) if no instructor exists.
Serves the built SPA from webapp/dist when present (one origin in prod;
dev uses the Vite proxy instead).
"""

import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from .config import REPO_ROOT, Settings
from .routers import auth as auth_router
from .routers import chatbot as chatbot_router
from .routers import events as events_router
from .routers import instructor as instructor_router
from .routers import quizzes as quizzes_router
from .routers import reports as reports_router
from .routers import student as student_router
from .routers import tutorials as tutorials_router
from .security import hash_password
from .services import quiz_store, tutorial_store

WEBAPP_DIST = REPO_ROOT / "webapp" / "dist"


def seed_instructor(settings: Settings) -> None:
    if not (settings.instructor_username and settings.instructor_password):
        return
    conn = dbmod.connect(settings.db_path)
    try:
        if conn.execute("SELECT 1 FROM users WHERE role = 'instructor'").fetchone():
            return
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
            (
                settings.instructor_username,
                hash_password(settings.instructor_password),
                "instructor",
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    dbmod.init_db(settings.db_path)
    seed_instructor(settings)
    conn = dbmod.connect(settings.db_path)
    try:
        tutorial_store.seed_if_empty(conn, settings)
        quiz_store.seed_quizzes(conn)
    finally:
        conn.close()

    application = FastAPI(title="ME-UY 4214 Tutoring Hub", docs_url="/docs")
    application.state.settings = settings

    application.include_router(auth_router.router)
    application.include_router(instructor_router.router)
    application.include_router(tutorials_router.router)
    application.include_router(quizzes_router.router)
    application.include_router(events_router.router)
    application.include_router(student_router.router)
    application.include_router(reports_router.router)
    application.include_router(chatbot_router.router)

    # Reference screenshots for tutorial steps (authored under
    # mock_server/data/images/<tutorial>/, served read-only to the web runner).
    images_dir = REPO_ROOT / "mock_server" / "data" / "images"
    if images_dir.is_dir():
        application.mount(
            "/tutorial-images", StaticFiles(directory=images_dir), name="tutorial-images"
        )

    if WEBAPP_DIST.is_dir():
        application.mount(
            "/assets", StaticFiles(directory=WEBAPP_DIST / "assets"), name="assets"
        )

        @application.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str, request: Request):
            # SPA catch-all: anything that isn't /api or /docs gets index.html.
            candidate = WEBAPP_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEBAPP_DIST / "index.html")

    return application


app = create_app()
