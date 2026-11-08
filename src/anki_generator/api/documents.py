"""Safe batch/ZIP import and read-only source inspection."""

import json
import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Card, Concept, Course, Document, Page
from anki_generator.domain import DocumentCategory, DocumentPatch
from anki_generator.services.cleanup import remove_owned_directory, remove_unreferenced_blob
from anki_generator.services.records import document_view, page_view, require
from anki_generator.services.storage import (
    MAX_BATCH_BYTES,
    MAX_UPLOAD_BYTES,
    SUPPORTED_UPLOADS,
    safe_relative,
    safe_storage_path,
    store_bytes,
    unpack_zip,
)

router = APIRouter(prefix="/api")
MAX_BATCH_DOCUMENTS = 2000


@router.get("/courses/{course_id}/documents")
def list_documents(request: Request, course_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        return [
            document_view(document)
            for document in session.scalars(
                select(Document)
                .where(Document.course_id == course_id)
                .order_by(Document.relative_path)
            )
        ]


@router.post("/courses/{course_id}/documents", status_code=201)
async def upload_documents(
    request: Request,
    course_id: str,
    files: Annotated[list[UploadFile], File()],
    paths: Annotated[str, Form()] = "[]",
    category: Annotated[DocumentCategory, Form()] = "lecture",
    authority: Annotated[str, Form()] = "unknown",
) -> dict[str, Any]:
    rt = runtime(request)
    if authority not in {"official", "student", "unknown"}:
        raise ValueError("Choose official, student, or unknown source authority")
    requested_paths = json.loads(paths)
    if not isinstance(requested_paths, list) or not all(
        isinstance(path, str) for path in requested_paths
    ):
        raise ValueError("paths must be a list of relative filenames")
    if requested_paths and len(requested_paths) != len(files):
        raise ValueError("Each upload must have one relative filename")
    if not files or len(files) > 2000:
        raise ValueError("Upload between 1 and 2000 files per batch")
    with rt.sessions() as session:
        require(session, Course, course_id)
        ensure_idle(session, course_id)
    candidates: list[tuple[str, bytes]] = []
    warnings: list[str] = []
    total = 0
    for index, upload in enumerate(files):
        name = safe_relative(requested_paths[index] if requested_paths else upload.filename or "")
        content = bytearray()
        while chunk := await upload.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                raise ValueError(f"{name} exceeds the 200 MiB upload limit")
        await upload.close()
        total += len(content)
        if total > MAX_BATCH_BYTES:
            raise ValueError("Upload batch exceeds the 512 MiB limit")
        suffix = Path(name).suffix.lower()
        if suffix == ".zip":
            members, archive_warnings = unpack_zip(bytes(content))
            if len(candidates) + len(members) > MAX_BATCH_DOCUMENTS:
                raise ValueError("Expanded upload exceeds the 2000-document batch limit")
            if sum(len(data) for _, data in [*candidates, *members]) > MAX_BATCH_BYTES:
                raise ValueError("Expanded batch exceeds the 512 MiB limit")
            candidates.extend(members)
            warnings.extend(archive_warnings)
        elif suffix in SUPPORTED_UPLOADS:
            candidates.append((name, bytes(content)))
        else:
            raise ValueError(f"Unsupported file type: {suffix or 'no extension'} ({name})")
    if sum(len(content) for _, content in candidates) > MAX_BATCH_BYTES:
        raise ValueError("Expanded batch exceeds the 512 MiB limit")
    if not candidates:
        raise ValueError("The upload contains no supported course documents")
    if len({name for name, _ in candidates}) != len(candidates):
        raise ValueError("The batch contains duplicate relative filenames")
    imported: list[dict[str, Any]] = []
    with rt.sessions.begin() as session:
        ensure_idle(session, course_id)
        for name, content in candidates:
            relative, digest = store_bytes(rt.data_root, content, Path(name).suffix)
            document = session.scalar(
                select(Document).where(
                    Document.course_id == course_id, Document.relative_path == name
                )
            )
            if document and document.sha256 != digest:
                raise ValueError(
                    f"{name} already exists with different content; rename or remove it first"
                )
            if document is None:
                document = Document(
                    course_id=course_id,
                    filename=Path(name).name,
                    relative_path=name,
                    category=category,
                    authority=authority,
                    sha256=digest,
                    size_bytes=len(content),
                    mime_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                    storage_path=relative,
                )
                session.add(document)
                session.flush()
            else:
                warnings.append(f"Already imported unchanged: {name}")
            imported.append(document_view(document))
    return {"documents": imported, "warnings": warnings}


@router.patch("/documents/{document_id}")
def edit_document(request: Request, document_id: str, values: DocumentPatch) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        document = require(session, Document, document_id)
        ensure_idle(session, document.course_id)
        if values.filename is not None:
            if Path(values.filename).name != values.filename or "\\" in values.filename:
                raise ValueError("Display filename must be a filename, without directories")
            if Path(values.filename).suffix.lower() != Path(document.relative_path).suffix.lower():
                raise ValueError("Renaming may not change the document format")
            document.filename = values.filename
        if values.linked_document_id:
            linked = require(session, Document, values.linked_document_id)
            if linked.course_id != document.course_id or linked.id == document.id:
                raise ValueError("Linked exercise/solution must be another document in this course")
        for key in ("category", "authority", "linked_document_id"):
            if key in values.model_fields_set:
                if getattr(values, key) is None and key != "linked_document_id":
                    raise ValueError(f"{key} cannot be null")
                setattr(document, key, getattr(values, key))
        if values.reprocess:
            document.extraction_key = ""
            document.status = "imported"
        return document_view(document)


@router.delete("/documents/{document_id}")
def delete_document(request: Request, document_id: str) -> dict[str, bool]:
    rt = runtime(request)
    with rt.sessions.begin() as session:
        document = require(session, Document, document_id)
        blob = document.storage_path
        ensure_idle(session, document.course_id)
        for card in session.scalars(select(Card).where(Card.course_id == document.course_id)):
            if any(
                ref.get("document_id") == document_id for ref in [*card.sources, *card.image_refs]
            ):
                card.verification_status = "failed"
                card.review_status = "pending"
                card.issues = [
                    *card.issues,
                    "Supporting source was removed. Replace the evidence and reverify.",
                ]
        for concept in session.scalars(
            select(Concept).where(Concept.course_id == document.course_id)
        ):
            if any(ref.get("document_id") == document_id for ref in concept.sources):
                concept.coverage_status = "unresolved"
        session.execute(delete(Document).where(Document.id == document_id))
    remove_unreferenced_blob(rt.sessions, rt.data_root, blob)
    remove_owned_directory(rt.data_root, f"artifacts/{document_id}")
    return {"deleted": True}


@router.get("/documents/{document_id}/source")
def original_document(request: Request, document_id: str) -> FileResponse:
    rt = runtime(request)
    with rt.sessions() as session:
        document = require(session, Document, document_id)
        path = safe_storage_path(rt.data_root, document.storage_path)
        # Only PDFs and raster images may render inline. HTML-like text stays inert.
        media_type = (
            document.mime_type
            if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}
            else "text/plain"
        )
        return FileResponse(
            path,
            media_type=media_type,
            filename=document.filename,
            content_disposition_type="inline",
        )


@router.get("/documents/{document_id}/pages")
def document_pages(request: Request, document_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Document, document_id)
        return [
            page_view(document_id, page)
            for page in session.scalars(
                select(Page).where(Page.document_id == document_id).order_by(Page.page_number)
            )
        ]


@router.get("/documents/{document_id}/regions/{region_id}")
def document_region(request: Request, document_id: str, region_id: str) -> FileResponse:
    rt = runtime(request)
    with rt.sessions() as session:
        document = require(session, Document, document_id)
        region = next(
            (
                region
                for page in session.scalars(select(Page).where(Page.document_id == document_id))
                for region in page.regions
                if region["id"] == region_id
            ),
            None,
        )
        if region is None:
            raise LookupError("Source region not found; run local extraction first")
        directory = document.extraction.get("artifact_dir", "")
        path = safe_storage_path(rt.data_root, f"{directory}/{region['image_path']}")
        if not path.is_file():
            raise LookupError("Source image is missing; reprocess this document")
        return FileResponse(path, media_type="image/png")
