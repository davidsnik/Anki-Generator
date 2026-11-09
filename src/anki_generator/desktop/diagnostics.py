"""Desktop-only safe diagnostics, with no raw logs, sources or credential values."""

import io
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import text

from anki_generator.api.runtime import runtime
from anki_generator.desktop.logs import BACKUP_COUNT, MAX_LOG_BYTES, safe_events
from anki_generator.services.task_views import counts


def create_router(state_directory: Path | None, *, shutdown_timeout: float) -> APIRouter:
    router = APIRouter(prefix="/api/desktop")

    def status(request: Request) -> dict[str, Any]:
        rt = runtime(request)
        with rt.sessions() as session:
            jobs = counts(session)
        snapshot = rt.runner.scheduler_snapshot()
        # Scheduler errors are curated, but exporting only presence also protects
        # future changes from accidentally disclosing a provider/source message.
        snapshot["error"] = bool(snapshot["error"])
        return {
            "active_jobs": jobs["active"],
            "queued_jobs": jobs["queued"],
            "paused_jobs": jobs["paused"],
            "scheduler": snapshot,
            "checkpoint_shutdown_timeout_seconds": shutdown_timeout,
        }

    def report(request: Request, *, for_export: bool = False) -> dict[str, Any]:
        rt = runtime(request)
        try:
            application_version = version("anki-generator")
        except PackageNotFoundError:
            application_version = "unknown"
        with rt.sessions() as session:
            schema_version = session.scalar(text("SELECT version_num FROM alembic_version"))
        key_status = rt.secrets.status()
        result = {
            "format_version": 1,
            "application_version": application_version,
            "backend_version": request.app.version,
            "schema_version": schema_version,
            "platform": platform.system(),
            "runtime": status(request),
            "credential_storage": {
                "persistent_available": key_status["persistent_available"],
                "storage": key_status["storage"],
            },
            "logs": {
                "max_file_bytes": MAX_LOG_BYTES,
                "backup_count": BACKUP_COUNT,
                "events": safe_events(state_directory),
            },
            "migration": {
                "mode": "explicit_backup_restore",
                "automatic_directory_copy": False,
                "credentials_included": False,
            },
        }
        if not for_export:
            result["data_directory"] = str(rt.data_root)
            result["state_directory"] = str(state_directory) if state_directory else None
        return result

    @router.get("/shutdown-status")
    def shutdown_status(request: Request) -> dict[str, Any]:
        return status(request)

    @router.get("/diagnostics")
    def diagnostics(request: Request) -> dict[str, Any]:
        return report(request)

    @router.post("/diagnostics/export")
    def export_diagnostics(request: Request) -> Response:
        stream = io.BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostics.json", json.dumps(report(request, for_export=True), indent=2)
            )
            archive.writestr(
                "README.txt",
                "Contains versions, job counts and allowlisted lifecycle events. "
                "No credentials, source documents, card contents, raw logs or private paths.\n",
            )
        return Response(
            stream.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="anki-generator-diagnostics.zip"'
            },
        )

    return router
