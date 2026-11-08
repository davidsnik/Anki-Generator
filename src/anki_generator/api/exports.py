"""Anki/backup exports and download history."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Course, ExportRecord
from anki_generator.domain import ExportInput
from anki_generator.services.exporting import create_export
from anki_generator.services.records import export_view, require
from anki_generator.services.storage import safe_storage_path

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/exports")
def list_exports(request: Request, course_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        return [
            export_view(export)
            for export in session.scalars(
                select(ExportRecord)
                .where(ExportRecord.course_id == course_id)
                .order_by(ExportRecord.created_at.desc())
            )
        ]


@router.post("/courses/{course_id}/exports", status_code=201)
def export_course(request: Request, course_id: str, values: ExportInput) -> dict[str, Any]:
    rt = runtime(request)
    with rt.sessions.begin() as session:
        return export_view(create_export(session, rt.data_root, course_id, values))


@router.get("/exports/{export_id}/download")
def download_export(request: Request, export_id: str) -> FileResponse:
    rt = runtime(request)
    with rt.sessions() as session:
        export = require(session, ExportRecord, export_id)
        path = safe_storage_path(rt.data_root, export.storage_path)
        if not path.is_file():
            raise LookupError("The exported file is missing; create a new export")
        media = {"json": "application/json", "csv": "text/csv", "apkg": "application/octet-stream"}
        return FileResponse(
            path,
            media_type=media[export.format],
            filename=f"{export.deck_name.replace('/', '_')}.{export.format}",
        )
