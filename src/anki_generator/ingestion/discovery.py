"""Discover local files without parsing them or following nested symlinks."""

import hashlib
import os
import stat
from pathlib import Path

from pydantic import ValidationError

from anki_generator.config import DiscoverySettings
from anki_generator.models import DiscoveryManifest, DocumentRecord

OUTPUT_MARKER = ".anki-generator-output"
HASH_CHUNK_SIZE = 1024 * 1024


class DiscoveryError(ValueError):
    """The source tree could not be inventoried completely."""


def _hash_file(path: Path) -> tuple[int, str]:
    # O_NOFOLLOW prevents a final-component link swapped in since scandir.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise DiscoveryError(f"Not a regular file: {path}")
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(stream.fileno())
        signature_before = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        signature_after = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if signature_before != signature_after or size != after.st_size:
            raise DiscoveryError(f"File changed while hashing; retry on a stable tree: {path}")
        return size, digest.hexdigest()


def discover_documents(
    course_directory: Path,
    *,
    output_directory: Path | None = None,
    settings: DiscoverySettings | None = None,
) -> DiscoveryManifest:
    """Inventory a stable tree. Read failures abort rather than imply full coverage.

    The caller-selected root is resolved once; nested symlinks are always skipped.
    Hashes describe bytes observed during this run, not permanent document identities.
    """
    settings = settings or DiscoverySettings()
    documents: list[DocumentRecord] = []
    excluded: list[str] = []
    unsupported = 0
    symlinks = 0
    try:
        root = course_directory.resolve(strict=True)
        if not root.is_dir():
            raise DiscoveryError(f"Course path is not a directory: {course_directory}")
        output = output_directory.resolve() if output_directory is not None else None
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    if entry.is_symlink():
                        symlinks += 1
                    elif entry.is_dir(follow_symlinks=False):
                        if (
                            path == output
                            or entry.name in settings.excluded_directory_names
                            or os.path.lexists(path / OUTPUT_MARKER)
                        ):
                            excluded.append(relative)
                        else:
                            pending.append(path)
                    elif (
                        not entry.is_file(follow_symlinks=False)
                        or path.suffix.lower() not in settings.supported_extensions
                    ):
                        unsupported += 1
                    else:
                        if not path.resolve(strict=True).is_relative_to(root):
                            raise DiscoveryError(f"File escaped the course directory: {path}")
                        size, digest = _hash_file(path)
                        documents.append(
                            DocumentRecord(
                                relative_path=relative,
                                file_type=path.suffix.lower()[1:],
                                size_bytes=size,
                                sha256=digest,
                            )
                        )
        return DiscoveryManifest(
            documents=tuple(sorted(documents, key=lambda document: document.relative_path)),
            skipped_unsupported=unsupported,
            skipped_symlinks=symlinks,
            excluded_directories=tuple(sorted(excluded)),
        )
    except (OSError, ValidationError, RuntimeError) as exc:
        raise DiscoveryError(f"Cannot inspect {course_directory}: {exc}") from exc
