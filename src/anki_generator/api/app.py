"""Single-origin local application with CSRF, origin, host, and body-size guards."""

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select, text
from starlette.middleware.cors import CORSMiddleware

from anki_generator.api import (
    backups,
    card_tools,
    cards,
    courses,
    documents,
    evaluations,
    exports,
    quality_inventory,
    runs,
    settings,
    source_fidelity,
    tasks,
)
from anki_generator.api.runtime import Runtime
from anki_generator.api.security import RequestActivity, RequestBodyLimit
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
    desktop_token: str | None = None,
    desktop_state_directory: Path | None = None,
    desktop_shutdown_timeout: float = 210,
) -> FastAPI:
    if desktop_token is not None and (
        not 32 <= len(desktop_token) <= 256
        or not desktop_token.isascii()
        or any(character.isspace() for character in desktop_token)
    ):
        raise ValueError("Desktop authentication requires a strong ASCII session token")
    root = data_root or Path(os.environ.get("ANKI_GENERATOR_DATA_DIR", "data/app"))
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    instance_lock = InstanceLock(root)
    # Recovery and migrations mutate state too, so ownership must precede Runtime.
    # The explicit test-only start_worker=False mode permits isolated test clients.
    if start_worker:
        instance_lock.acquire()
    try:
        rt = Runtime(root, provider_factory=provider_factory)
    except BaseException:
        instance_lock.release()
        raise
    csrf_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            if start_worker:
                rt.runner.start()
            yield
        finally:
            # If shutdown cannot stop a worker, retain ownership of its database.
            # Releasing the process lock while that thread is alive is unsafe.
            if start_worker:
                if desktop_token is None:
                    rt.runner.stop()
                else:
                    # A deliberately long parser may exceed the ordinary grace
                    # period. Keep ownership until its safe checkpoint; only an
                    # explicitly confirmed force quit may interrupt that work.
                    while True:
                        try:
                            await asyncio.to_thread(
                                rt.runner.stop, timeout=desktop_shutdown_timeout
                            )
                            break
                        except ValueError:
                            continue
            try:
                rt.sessions.kw["bind"].dispose()
                for item in rt.restore_tokens.values():
                    item["temporary"].cleanup()
            finally:
                instance_lock.release()

    app = FastAPI(title="Anki Generator", version="1.0", lifespan=lifespan)
    app.state.runtime = rt
    app.state.csrf_token = csrf_token
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(RequestActivity, runtime=rt)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def secure_local_requests(request: Request, call_next: Any):
        if desktop_token is not None and not secrets.compare_digest(
            request.headers.get("x-desktop-token", "").encode(), desktop_token.encode()
        ):
            return JSONResponse(
                {"detail": "Desktop session authentication required"}, status_code=401
            )
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
        body_limit = (
            (4096 + 10) * 1024 * 1024
            if request.url.path == "/api/backup/validate"
            else 522 * 1024 * 1024
        )
        if length > body_limit:
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
                    "schema_version": session.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    "worker": "persistent local worker",
                },
            }

    for router in (
        courses.router,
        documents.router,
        cards.router,
        card_tools.router,
        runs.router,
        settings.router,
        exports.router,
        evaluations.router,
        source_fidelity.router,
        quality_inventory.router,
        backups.router,
        tasks.router,
    ):
        app.include_router(router)

    if desktop_token is not None:
        from anki_generator.desktop.diagnostics import create_router

        app.include_router(
            create_router(desktop_state_directory, shutdown_timeout=desktop_shutdown_timeout)
        )

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
