"""Single-origin local application with CSRF, origin, host, and body-size guards."""

import os
import secrets
import sqlite3
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from starlette.background import BackgroundTask
from starlette.middleware.cors import CORSMiddleware

from anki_generator.api import cards, courses, documents, exports, runs, settings
from anki_generator.api.runtime import Runtime
from anki_generator.api.security import RequestBodyLimit
from anki_generator.database.entities import Course, Run
from anki_generator.llm import ProviderError
from anki_generator.services.instance_lock import InstanceLock
from anki_generator.services.records import course_view, run_view
from anki_generator.services.settings import get_settings


def create_app(
    data_root: Path | None = None,
    *,
    provider_factory: Any = None,
    start_worker: bool = True,
    frontend_directory: Path | None = None,
) -> FastAPI:
    root = data_root or Path(os.environ.get("ANKI_GENERATOR_DATA_DIR", "data/app"))
    rt = Runtime(root, provider_factory=provider_factory)
    csrf_token = secrets.token_urlsafe(32)
    instance_lock = InstanceLock(rt.data_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker:
            instance_lock.acquire()
        try:
            if start_worker:
                rt.runner.start()
            yield
        finally:
            if start_worker:
                rt.runner.stop()
                instance_lock.release()
            rt.sessions.kw["bind"].dispose()

    app = FastAPI(title="Anki Generator", version="1.0", lifespan=lifespan)
    app.state.runtime = rt
    app.state.csrf_token = csrf_token
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def secure_local_requests(request: Request, call_next: Any):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "Only loopback hosts are allowed"}, status_code=403)
        origin = request.headers.get("origin")
        own_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        allowed = {own_origin, "http://127.0.0.1:5173", "http://localhost:5173"}
        if origin and origin not in allowed:
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed"}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are not allowed"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(
                request.headers.get("x-csrf-token", "").encode(), csrf_token.encode()
            ):
                return JSONResponse(
                    {"detail": "Missing or invalid local session token; reload the application"},
                    status_code=403,
                )
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if length > 522 * 1024 * 1024:
            return JSONResponse(
                {"detail": "Request exceeds the 512 MiB upload limit"}, status_code=413
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' "
            "ws://127.0.0.1:5173 ws://localhost:5173; worker-src 'self' blob:; "
            "frame-src 'self' blob:; object-src 'self'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(LookupError)
    async def missing(request: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> JSONResponse:
        if isinstance(exc, ValidationError):
            errors = exc.errors(include_input=False, include_context=False, include_url=False)
            return JSONResponse({"detail": errors}, status_code=400)
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {key: item[key] for key in ("loc", "msg", "type") if key in item}
            for item in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(ProviderError)
    async def provider_failed(request: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "kind": exc.kind}, status_code=502)

    @app.exception_handler(OSError)
    async def storage_failed(request: Request, exc: OSError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": (
                    "Local storage could not be read or written. Check disk space and permissions."
                )
            },
            status_code=500,
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "1.0"}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        with rt.sessions() as session:
            return {
                "csrf_token": csrf_token,
                "settings": get_settings(rt.sessions).model_dump(),
                "key_status": rt.secrets.status(),
                "courses": [
                    course_view(session, course)
                    for course in session.scalars(select(Course).order_by(Course.updated_at.desc()))
                ],
                "recent_runs": [
                    run_view(session, run)
                    for run in session.scalars(
                        select(Run).order_by(Run.created_at.desc()).limit(10)
                    )
                ],
                "diagnostics": {
                    "data_directory": str(rt.data_root),
                    "database": "SQLite / Alembic",
                    "external_provider": "OpenAI (explicit per-run consent)",
                    "schema_version": "0001",
                    "worker": "persistent local worker",
                },
            }

    @app.post("/api/backup")
    def backup() -> FileResponse:
        # SQLite backup API gives a consistent DB snapshot, including WAL commits.
        temporary = tempfile.TemporaryDirectory(prefix="anki-backup-")
        directory = Path(temporary.name)
        copied_db = directory / "application.sqlite3"
        source = sqlite3.connect(rt.data_root / "application.sqlite3")
        target = sqlite3.connect(copied_db)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        archive_path = directory / "anki-generator-backup.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(copied_db, "application.sqlite3")
            for folder in ("originals", "artifacts", "runs", "cache", "exports"):
                base = rt.data_root / folder
                if base.is_dir():
                    for path in base.rglob("*"):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, path.relative_to(rt.data_root).as_posix())
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename="anki-generator-backup.zip",
            background=BackgroundTask(temporary.cleanup),
        )

    for router in (
        courses.router,
        documents.router,
        cards.router,
        runs.router,
        settings.router,
        exports.router,
    ):
        app.include_router(router)

    frontend = frontend_directory
    if frontend is None:
        checkout_frontend = Path(__file__).resolve().parents[3] / "frontend/dist"
        bundled_frontend = Path(__file__).resolve().parents[1] / "web_assets"
        frontend = (
            checkout_frontend if (checkout_frontend / "index.html").is_file() else bundled_frontend
        )
    if (frontend / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")

        @app.get("/{path:path}")
        def frontend_page(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise LookupError("API endpoint not found")
            candidate = (frontend / path).resolve()
            if candidate.is_relative_to(frontend.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")
    else:

        @app.get("/")
        def missing_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": (
                        "Frontend is not built. Run ./install.sh from the repository, "
                        "then ./run.sh."
                    )
                },
                status_code=503,
            )

    return app
