"""Bounded, traversal-safe input storage and ZIP import planning."""

import hashlib
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

SUPPORTED_UPLOADS = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md", ".tex", ".docx", ".pptx"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_BATCH_BYTES = 512 * 1024 * 1024
MAX_ZIP_MEMBERS = 2000


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value == "."
        or "\x00" in value
        or "\\" in value
        or path.is_absolute()
        or PureWindowsPath(value).drive
        or ".." in path.parts
        or path.as_posix() != value
        or len(value) > 1000
    ):
        raise ValueError("File paths must be normalized relative paths without traversal")
    return value


def safe_storage_path(root: Path, relative: str) -> Path:
    path = root / safe_relative(relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Stored path escapes the application data directory")
    return path


def store_bytes(root: Path, content: bytes, suffix: str) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    relative = f"originals/{digest}{suffix.lower()}"
    destination = safe_storage_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".upload-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            destination.chmod(0o600)
        finally:
            Path(temporary).unlink(missing_ok=True)
    elif hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError("Stored original hash mismatch; restore your data backup")
    return relative, digest


def unpack_zip(content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Validate all archive paths and sizes before reading any member content."""
    import io

    files: list[tuple[str, bytes]] = []
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise ValueError(f"ZIP exceeds the {MAX_ZIP_MEMBERS}-entry limit")
            total = 0
            seen: set[str] = set()
            for member in members:
                name = member.filename.rstrip("/") if member.is_dir() else member.filename
                safe_relative(name)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("ZIP archives may not contain symlinks")
                if member.flag_bits & 1:
                    raise ValueError("Encrypted ZIP archives are unsupported")
                if member.is_dir():
                    continue
                if name in seen:
                    raise ValueError("ZIP contains duplicate paths")
                seen.add(name)
                total += member.file_size
                if member.file_size > MAX_UPLOAD_BYTES or total > MAX_BATCH_BYTES:
                    raise ValueError("ZIP expansion exceeds the configured safe import limits")
                if member.file_size / max(member.compress_size, 1) > 1000:
                    raise ValueError("ZIP compression ratio exceeds the safe import limit")
            for member in members:
                if member.is_dir():
                    continue
                if Path(member.filename).suffix.lower() not in SUPPORTED_UPLOADS:
                    warnings.append(f"Skipped unsupported archive member: {member.filename}")
                    continue
                data = archive.read(member)
                if len(data) != member.file_size:
                    raise ValueError("ZIP member size does not match its metadata")
                files.append((member.filename, data))
    except zipfile.BadZipFile as exc:
        raise ValueError("The ZIP archive is damaged or invalid") from exc
    return files, warnings
