"""Remove owned course files without deleting blobs shared by another course."""

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from anki_generator.database.entities import Document
from anki_generator.services.storage import safe_storage_path


def remove_unreferenced_blob(sessions: sessionmaker, root: Path, relative: str) -> None:
    with sessions() as session:
        if session.scalar(select(Document.id).where(Document.storage_path == relative).limit(1)):
            return
    safe_storage_path(root, relative).unlink(missing_ok=True)


def remove_owned_directory(root: Path, relative: str) -> None:
    path = safe_storage_path(root, relative)
    if path.is_dir():
        shutil.rmtree(path)
