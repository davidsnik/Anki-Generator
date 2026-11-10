"""Streaming private ZIP inventory with bounded, staged extraction and stable identities."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from anki_generator.benchmark.contracts import DatasetManifest, DatasetSource
from anki_generator.processing.state import digest
from anki_generator.services.storage import SUPPORTED_UPLOADS, safe_relative


def write_new_json(path: Path, value: dict) -> Path:
    """Never replace an earlier experiment or its annotations."""
    if path.is_symlink():
        raise ValueError("Artifact output cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    path.chmod(0o600)
    return path


def course_identity(relative: str) -> tuple[str, str]:
    parts = PurePosixPath(relative).parts[:-1]
    lower = [part.casefold() for part in parts]
    if "courses" in lower and lower.index("courses") + 1 < len(parts):
        index = lower.index("courses") + 1
        return "/".join(parts[: index + 1]), parts[index]
    if "selfstudy" in lower and lower.index("selfstudy") + 1 < len(parts):
        index = lower.index("selfstudy") + 1
        return "/".join(parts[: index + 1]), parts[index]
    roles = {"notes", "exercises", "solutions", "slides", "lectures", "summaries"}
    while parts and parts[-1].casefold() in roles:
        parts = parts[:-1]
    return "/".join(parts) or "unassigned", parts[-1] if parts else "Unassigned"


def role_hints(relative: str) -> list[str]:
    value = relative.casefold()
    rules = {
        "solutions": ("solution", "answer", "uitwerking", "worked"),
        "exercises": ("exercise", "problem", "exam", "assignment", "tentamen"),
        "personal_notes": ("notes", "aantekening", "summary", "samenvatting"),
        "lecture": ("lecture", "slides", "hoorcollege"),
        "reference": ("studyguide", "study guide", "syllabus", "literature", "reference"),
    }
    return [role for role, words in rules.items() if any(word in value for word in words)]


def relationship_candidates(sources: list[DatasetSource]) -> list[dict]:
    """Conservative filename matches are leads for review, never established pairings."""
    question = re.compile(r"\b(?:questions?|exercises?|problems?|assignments?|exam)\b", re.I)
    solution = re.compile(r"\b(?:solutions?|answers?|uitwerkingen?|worked)\b", re.I)
    candidates, groups = [], {}
    for source in sources:
        title = re.sub(r"[_-]+", " ", PurePosixPath(source.relative_path).stem)
        has_question, has_solution = bool(question.search(title)), bool(solution.search(title))
        if has_question and has_solution:
            candidates.append(
                {
                    "kind": "possible_questions_and_solutions_within_document",
                    "source_ids": [source.id],
                    "status": "unconfirmed",
                    "basis": "both question and solution words occur in the filename",
                }
            )
        elif has_question or has_solution:
            stem = solution.sub(" ", question.sub(" ", title)).casefold()
            stem = re.sub(r"\b(?:and|with|the|of)\b", " ", stem)
            stem = " ".join(re.findall(r"\w+", stem))
            if stem:
                groups.setdefault((source.course_id, stem), {"questions": [], "solutions": []})[
                    "questions" if has_question else "solutions"
                ].append(source.id)
    for (_course, _stem), group in sorted(groups.items()):
        if len(group["questions"]) == len(group["solutions"]) == 1:
            candidates.append(
                {
                    "kind": "possible_exercise_solution_pair",
                    "source_ids": group["questions"] + group["solutions"],
                    "status": "unconfirmed",
                    "basis": "same course and distinctive filename after removing role words",
                }
            )
    return candidates


def inventory_zip(
    archive_path: Path,
    *,
    extract_to: Path | None = None,
    max_members: int = 20000,
    max_member_bytes: int = 512 * 1024 * 1024,
    max_expanded_bytes: int = 8 * 1024 * 1024 * 1024,
) -> DatasetManifest:
    """Hash every source; never execute files or load the entire archive into RAM."""
    archive_path = archive_path.resolve(strict=True)
    if not archive_path.is_file():
        raise ValueError("The dataset archive must be a regular file")
    original_stat = archive_path.stat()
    if extract_to is not None:
        if extract_to.exists() or extract_to.is_symlink():
            raise ValueError("Extraction destination must be new; originals are never overwritten")
        extract_to.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    stage = None
    try:
        with ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > max_members:
                raise ValueError("Dataset exceeds the archive member limit")
            seen: set[str] = set()
            total = 0
            for member in members:
                name = member.filename.rstrip("/") if member.is_dir() else member.filename
                safe_relative(name)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                    raise ValueError("Dataset archives cannot contain links or special files")
                if member.flag_bits & 1:
                    raise ValueError("Encrypted datasets are unsupported")
                if member.is_dir():
                    continue
                if name in seen:
                    raise ValueError("Dataset contains duplicate paths")
                seen.add(name)
                total += member.file_size
                if member.file_size > max_member_bytes or total > max_expanded_bytes:
                    raise ValueError("Dataset expansion exceeds the configured limits")
                if member.file_size / max(member.compress_size, 1) > 1000:
                    raise ValueError("Dataset exceeds the safe compression ratio")
            if extract_to is not None:
                stage = Path(tempfile.mkdtemp(prefix=".dataset-", dir=extract_to.parent))
                stage.chmod(0o700)
            sources = []
            for member in sorted(members, key=lambda value: value.filename):
                if member.is_dir():
                    continue
                name = member.filename
                target = stage / name if stage else None
                if target:
                    target.parent.mkdir(parents=True, exist_ok=True)
                sha = hashlib.sha256()
                actual = 0
                with archive.open(member) as incoming:
                    outgoing = target.open("xb") if target else None
                    try:
                        while block := incoming.read(1024 * 1024):
                            actual += len(block)
                            if actual > member.file_size or actual > max_member_bytes:
                                raise ValueError("Dataset member expanded beyond declared bounds")
                            sha.update(block)
                            if outgoing:
                                outgoing.write(block)
                    finally:
                        if outgoing:
                            outgoing.close()
                if actual != member.file_size:
                    raise ValueError("Dataset member size does not match archive metadata")
                if target:
                    target.chmod(0o600)
                content_hash = sha.hexdigest()
                course_id, course_name = course_identity(name)
                suffix = PurePosixPath(name).suffix.lower()
                sources.append(
                    DatasetSource(
                        id=digest({"path": name, "sha256": content_hash})[:24],
                        relative_path=name,
                        sha256=content_hash,
                        size_bytes=actual,
                        source_type=suffix.removeprefix("."),
                        supported=suffix in SUPPORTED_UPLOADS,
                        course_id=course_id,
                        course_name=course_name,
                        role_candidates=role_hints(name),
                    )
                )
        final_stat = archive_path.stat()
        if (original_stat.st_size, original_stat.st_mtime_ns, original_stat.st_ctime_ns) != (
            final_stat.st_size,
            final_stat.st_mtime_ns,
            final_stat.st_ctime_ns,
        ):
            raise ValueError(
                "Dataset archive changed during inventory; no originals were published"
            )
        signature = digest([source.model_dump(exclude={"metadata"}) for source in sources])
        manifest = DatasetManifest(
            dataset_id=f"course-{signature[:16]}",
            dataset_sha256=signature,
            created_at=datetime.now(UTC).isoformat(),
            archive_sha256=archive_hash,
            archive_bytes=archive_path.stat().st_size,
            source_root=str(extract_to.resolve()) if extract_to else None,
            sources=sources,
            relationships=relationship_candidates(sources),
            limitations=[
                "Course grouping and role candidates come from paths, not human confirmation.",
                "No filename establishes authority, handwriting, mathematical truth or quality.",
                "Unsupported source types are inventoried but never executed.",
            ],
        )
        if stage:
            stage.rename(extract_to)
            stage = None
        return manifest
    except BadZipFile as exc:
        raise ValueError("The dataset ZIP is damaged or invalid") from exc
    finally:
        if stage:
            shutil.rmtree(stage)


def inventory_summary(manifest: DatasetManifest) -> dict:
    courses = Counter(source.course_id for source in manifest.sources)
    return {
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": manifest.dataset_sha256,
        "files": len(manifest.sources),
        "supported_files": sum(source.supported for source in manifest.sources),
        "types": dict(Counter(source.source_type for source in manifest.sources)),
        "courses": dict(sorted(courses.items())),
        "expanded_bytes": sum(source.size_bytes for source in manifest.sources),
    }
