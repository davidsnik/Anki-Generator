"""Reviewable backup validation and explicitly confirmed clean/replacement restore."""

import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from starlette.background import BackgroundTask

from anki_generator.api.runtime import runtime
from anki_generator.domain import InputModel
from anki_generator.services.backups import (
    create_archive,
    maintenance,
    restore_staged,
    stage_restore,
)

router = APIRouter(prefix="/api")


@router.post("/backup")
def download_backup(request: Request, include_originals: bool = True) -> FileResponse:
    rt = runtime(request)
    temporary = tempfile.TemporaryDirectory(prefix="anki-backup-download-")
    destination = Path(temporary.name) / "anki-generator-backup.zip"
    try:
        with maintenance(rt):
            create_archive(rt, destination, include_originals=include_originals)
    except Exception:
        temporary.cleanup()
        raise
    return FileResponse(
        destination,
        media_type="application/zip",
        filename="anki-generator-backup.zip",
        background=BackgroundTask(temporary.cleanup),
    )


@router.post("/backup/validate")
def validate_backup(request: Request, file: Annotated[UploadFile, File()]) -> dict:
    rt = runtime(request)
    if not rt.restore_validation_lock.acquire(blocking=False):
        raise ValueError("Another backup is being validated; wait for it to finish")
    try:
        return stage_restore(rt, file.file)
    finally:
        file.file.close()
        rt.restore_validation_lock.release()


class RestoreInput(InputModel):
    token: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")
    confirm: bool = False
    mode: Literal["clean", "replace"] = "clean"


@router.post("/backup/restore")
def restore_backup(request: Request, values: RestoreInput) -> dict:
    return restore_staged(runtime(request), values.token, mode=values.mode, confirm=values.confirm)


@router.delete("/backup/validation/{token}")
def discard_validation(request: Request, token: str) -> dict:
    rt = runtime(request)
    item = rt.restore_tokens.pop(token, None)
    if item:
        item["temporary"].cleanup()
    return {"discarded": True}


@router.get("/backup/recovery/{filename}")
def download_recovery(request: Request, filename: str) -> FileResponse:
    import re

    if not re.fullmatch(r"[a-f0-9]{32}\.zip", filename):
        raise ValueError("Invalid recovery backup identifier")
    path = runtime(request).data_root / "recovery" / filename
    if not path.is_file():
        raise LookupError("Recovery backup not found")
    return FileResponse(path, media_type="application/zip", filename="anki-generator-recovery.zip")
