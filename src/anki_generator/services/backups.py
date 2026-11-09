"""Validated private snapshots and crash-recoverable replacement of owned data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic.script import ScriptDirectory

from anki_generator.database.connection import migration_config, open_database
from anki_generator.services.settings import ApplicationSettings
from anki_generator.services.storage import safe_relative

MANAGED = (
    "application.sqlite3",
    "application.sqlite3-wal",
    "application.sqlite3-shm",
    "originals",
    "artifacts",
    "runs",
    "cache",
    "exports",
)
MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_EXPANDED_BYTES = 16 * 1024**3
MAX_BACKUP_MEMBERS = 200000


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024**2):
            digest.update(chunk)
    return digest.hexdigest()


def durable_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def remove_owned(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def recover_interrupted_restore(root: Path) -> None:
    """Rollback an incomplete swap before SQLite or the job runner is opened."""
    journal_path = root / ".restore-journal.json"
    if not journal_path.is_file():
        return
    journal = json.loads(journal_path.read_text())
    if journal.get("phase") not in {"swapping", "committed"}:
        raise ValueError("Restore journal phase is invalid; preserve recovery files for inspection")
    for name in ("previous", "staging"):
        value = journal.get(name, "")
        if not value.startswith(".restore-") or Path(value).name != value:
            raise ValueError("Restore journal contains an invalid owned directory")
    previous, staging = root / journal["previous"], root / journal["staging"]
    if journal["phase"] != "committed":
        for name in MANAGED:
            if (previous / name).exists():
                remove_owned(root / name)
                os.replace(previous / name, root / name)
            elif name not in journal["existing"] and name in journal["incoming"]:
                remove_owned(root / name)
    for directory in (previous, staging):
        if directory.exists():
            shutil.rmtree(directory)
    journal_path.unlink()
    journal_path.with_suffix(".new").unlink(missing_ok=True)


def inspect_migrated_schema(sessions: Any) -> None:
    """A revision stamp does not prove that the declared schema actually exists."""
    from sqlalchemy import inspect

    from anki_generator.database.entities import Base

    inspector = inspect(sessions.kw["bind"])
    for name, table in Base.metadata.tables.items():
        if not inspector.has_table(name):
            raise ValueError("Backup is missing a required application table after migration")
        actual = {column["name"]: column for column in inspector.get_columns(name)}
        if set(actual) != set(table.columns.keys()):
            raise ValueError("Backup columns do not match the declared application schema")
        for column in table.columns:
            if actual[column.name]["type"]._type_affinity != column.type._type_affinity:
                raise ValueError("Backup column types do not match the application schema")
            if actual[column.name]["nullable"] != column.nullable:
                raise ValueError(
                    "Backup nullability constraints do not match the application schema"
                )
        if set(inspector.get_pk_constraint(name)["constrained_columns"]) != {
            column.name for column in table.primary_key.columns
        }:
            raise ValueError("Backup primary identities do not match the application schema")
        actual_foreign = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                item.get("options", {}).get("ondelete"),
            )
            for item in inspector.get_foreign_keys(name)
        }
        expected_foreign = {
            (
                tuple(column.name for column in item.columns),
                next(iter(item.elements)).column.table.name,
                tuple(element.column.name for element in item.elements),
                item.ondelete,
            )
            for item in table.foreign_key_constraints
        }
        if actual_foreign != expected_foreign:
            raise ValueError(
                "Backup source/identity relationships do not match the application schema"
            )
        actual_unique = {
            tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)
        }
        from sqlalchemy import UniqueConstraint

        expected_unique = {
            tuple(column.name for column in item.columns)
            for item in table.constraints
            if isinstance(item, UniqueConstraint)
        }
        if actual_unique != expected_unique:
            raise ValueError("Backup uniqueness constraints do not match the application schema")


def inspect_database(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        schema = connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        from anki_generator.database.entities import Base

        if any(
            kind == "table" and name not in {*Base.metadata.tables, "alembic_version"}
            for kind, name, _ in schema
        ):
            raise ValueError("Backup contains tables outside the supported application schema")
        if any(
            kind in {"trigger", "view"} or (ddl and "CREATE VIRTUAL TABLE" in ddl.upper())
            for kind, _, ddl in schema
        ):
            raise ValueError("Backup contains unsupported executable database schema")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Backup database failed integrity validation")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup contains inconsistent source/card identities")
        revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        known = {
            item.revision
            for item in ScriptDirectory.from_config(migration_config()).walk_revisions()
        }
        if len(revisions) != 1 or revisions[0][0] not in known:
            raise ValueError("Backup schema is newer than this application or is unsupported")
        if connection.execute(
            "SELECT 1 FROM settings WHERE key != 'application' OR length(value) > 2097152 LIMIT 1"
        ).fetchone():
            raise ValueError("Backup contains unsupported or oversized application settings")
        for (value,) in connection.execute("SELECT value FROM settings WHERE key='application'"):
            ApplicationSettings.model_validate(json.loads(value))
        counts = {
            name: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for name, table in [
                ("courses", "courses"),
                ("documents", "documents"),
                ("cards", "cards"),
                ("revisions", "revisions"),
            ]
        }
        paths = []
        for value, serialized_extraction in connection.execute(
            "SELECT storage_path, extraction FROM documents"
        ):
            paths.append(owned_reference(value, "originals"))
            extraction = json.loads(serialized_extraction) if serialized_extraction else {}
            if not isinstance(extraction, dict):
                raise ValueError("Backup document extraction must be a structured object")
            artifact_dir = extraction.get("artifact_dir")
            if artifact_dir:
                owned_reference(artifact_dir, "artifacts")
            rendered = extraction.get("rendered_source_path")
            if rendered:
                if not artifact_dir:
                    raise ValueError("Backup rendered sources require an extraction directory")
                paths.append(safe_relative(f"{artifact_dir}/{safe_relative(rendered)}"))
            pages = extraction.get("pages", [])
            if not isinstance(pages, list):
                raise ValueError("Backup extraction pages must be a structured list")
            for page in pages:
                if not isinstance(page, dict) or not isinstance(page.get("regions", []), list):
                    raise ValueError("Backup extraction regions must be structured objects")
                for region in page.get("regions", []):
                    if not isinstance(region, dict):
                        raise ValueError("Backup source regions must be structured objects")
                    if region.get("storage_path"):
                        paths.append(owned_reference(region["storage_path"], "artifacts"))
                    elif region.get("image_path"):
                        if not artifact_dir:
                            raise ValueError("Backup region media requires an extraction directory")
                        paths.append(
                            safe_relative(f"{artifact_dir}/{safe_relative(region['image_path'])}")
                        )
        for (value,) in connection.execute("SELECT storage_path FROM exports"):
            paths.append(owned_reference(value, "exports"))
        tables = {name for kind, name, _ in schema if kind == "table"}
        if "selected_source_regions" in tables:
            paths.extend(
                owned_reference(row[0], "artifacts")
                for row in connection.execute("SELECT image_path FROM selected_source_regions")
            )
        return {**counts, "schema_version": revisions[0][0], "referenced_files": paths}
    except (sqlite3.DatabaseError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Backup database format is invalid or incompatible") from error
    finally:
        connection.close()


def owned_reference(value: str, namespace: str) -> str:
    relative = safe_relative(value)
    if not relative.startswith(namespace + "/"):
        raise ValueError("Backup references a file outside its application-owned namespace")
    return relative


def create_archive(rt: Any, destination: Path, *, include_originals: bool = True) -> dict[str, Any]:
    if any((rt.data_root / name).is_symlink() for name in MANAGED):
        raise ValueError("Backup refuses symbolic links in application-owned paths")
    with tempfile.TemporaryDirectory(prefix="anki-backup-snapshot-") as directory:
        copied = Path(directory) / "application.sqlite3"
        source = sqlite3.connect(rt.data_root / "application.sqlite3")
        target = sqlite3.connect(copied)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        summary = inspect_database(copied)
        files = {"application.sqlite3": copied}
        for name in MANAGED[3:]:
            if name == "originals" and not include_originals:
                continue
            base = rt.data_root / name
            if base.is_dir():
                for path in base.rglob("*"):
                    if path.is_symlink():
                        raise ValueError("Backup refuses symbolic links in the private data tree")
                    if path.is_file():
                        files[path.relative_to(rt.data_root).as_posix()] = path
        manifest = {
            "format": "anki-generator-backup",
            "version": 2,
            "schema_version": summary["schema_version"],
            "includes_originals": include_originals,
            "files": {
                name: {"size": path.stat().st_size, "sha256": file_digest(path)}
                for name, path in files.items()
            },
        }
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, path in files.items():
                archive.write(path, name)
            archive.writestr("backup-manifest.json", json.dumps(manifest, indent=2))
        return {key: value for key, value in summary.items() if key != "referenced_files"}


def validate_archive(archive_path: Path, staging: Path) -> tuple[dict[str, Any], list[str]]:
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Backup exceeds the 4 GiB compressed limit")
    warnings = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_BACKUP_MEMBERS:
                raise ValueError("Backup has an unsupported number of files")
            names = set()
            file_names = set()
            total = 0
            for entry in entries:
                name = safe_relative(entry.filename.rstrip("/"))
                if name in names:
                    raise ValueError("Backup contains duplicate archive paths")
                names.add(name)
                if not entry.is_dir():
                    file_names.add(name)
                if entry.flag_bits & 1 or entry.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise ValueError("Encrypted or unsupported backup compression is not accepted")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError("Backup contains a symbolic link or unsupported file type")
                top = name.split("/")[0]
                if top not in {*MANAGED[3:], "application.sqlite3", "backup-manifest.json"}:
                    raise ValueError(
                        "Backup contains an unexpected file outside application-owned data"
                    )
                if top in {"application.sqlite3", "backup-manifest.json"} and name != top:
                    raise ValueError("Backup root metadata must be regular files")
                if name == top and top in MANAGED[3:] and not entry.is_dir():
                    raise ValueError("Backup data folders cannot be replaced by regular files")
                if (
                    name == top
                    and top in {"application.sqlite3", "backup-manifest.json"}
                    and entry.is_dir()
                ):
                    raise ValueError("Backup database and manifest must be regular files")
                total += entry.file_size
                if (
                    total > MAX_EXPANDED_BYTES
                    or entry.file_size / max(entry.compress_size, 1) > 1000
                ):
                    raise ValueError("Backup expansion exceeds safe size or compression limits")
            if total > shutil.disk_usage(staging).free:
                raise ValueError("Insufficient local disk space to validate this backup")
            if any(
                parent.as_posix() in file_names
                for name in names
                for parent in Path(name).parents
                if parent != Path(".")
            ):
                raise ValueError("Backup contains a file that is also used as a parent folder")
            for entry in entries:
                destination = staging / safe_relative(entry.filename.rstrip("/"))
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024**2)
        manifest_path = staging / "backup-manifest.json"
        if manifest_path.is_file():
            if manifest_path.stat().st_size > 32 * 1024**2:
                raise ValueError("Backup manifest is too large")
            manifest = json.loads(manifest_path.read_text())
            if not isinstance(manifest, dict):
                raise ValueError("Backup manifest must be a structured object")
            if manifest.get("format") != "anki-generator-backup" or manifest.get("version") != 2:
                raise ValueError("Unsupported backup manifest version")
            expected = manifest.get("files", {})
            if not isinstance(expected, dict) or any(
                not isinstance(metadata, dict)
                or type(metadata.get("size")) is not int
                or metadata["size"] < 0
                or not isinstance(metadata.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"])
                for metadata in expected.values()
            ):
                raise ValueError("Backup file manifest has invalid size or checksum entries")
            actual = {
                path.relative_to(staging).as_posix()
                for path in staging.rglob("*")
                if path.is_file() and path != manifest_path
            }
            if set(expected) != actual:
                raise ValueError("Backup files do not match the manifest")
            for name, metadata in expected.items():
                path = staging / safe_relative(name)
                if (
                    path.stat().st_size != metadata["size"]
                    or file_digest(path) != metadata["sha256"]
                ):
                    raise ValueError("Backup file checksum mismatch")
            includes_originals = bool(manifest.get("includes_originals"))
        else:
            includes_originals = (staging / "originals").is_dir()
            warnings.append(
                "Legacy backup has no file checksum manifest; database/path checks still apply."
            )
        summary = inspect_database(staging / "application.sqlite3")
        missing = [
            name for name in summary.pop("referenced_files") if not (staging / name).is_file()
        ]
        non_original_missing = [name for name in missing if not name.startswith("originals/")]
        if non_original_missing or (includes_originals and missing):
            raise ValueError("Backup is missing required source, media or export files")
        if missing:
            warnings.append(
                f"{len(missing)} original files excluded; "
                "original viewing/reprocessing will be unavailable."
            )
        # Dry-run upgrades affect only staged data. Restored jobs never start sending
        # evidence using consent inherited from a backup.
        sessions = open_database(staging)
        try:
            inspect_migrated_schema(sessions)
            with sessions.begin() as session:
                from sqlalchemy import select

                from anki_generator.database.entities import Run

                for run in session.scalars(
                    select(Run).where(
                        Run.status.in_(["queued", "prepared", "running", "pausing", "cancelling"])
                    )
                ):
                    run.status = "paused"
                    run.pause_requested = False
                    run.cancel_requested = False
                    run.error = (
                        "Restored from backup; inspect inputs and explicitly resume processing."
                    )
        finally:
            sessions.kw["bind"].dispose()
        return {
            **summary,
            "bytes": total,
            "includes_originals": includes_originals,
            "missing_originals": len(missing),
        }, warnings
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("Backup archive or checksum manifest is malformed") from error


@contextmanager
def maintenance(rt: Any):
    with rt.access_lock:
        if rt.maintenance_mode or rt.active_requests > 1:
            raise ValueError("Wait for other local requests to finish before backup or restoration")
        rt.maintenance_mode = True
    acquired = False
    try:
        from sqlalchemy import select

        from anki_generator.database.entities import Run

        with rt.sessions() as session:
            if session.scalar(
                select(Run.id)
                .where(Run.status.in_(["queued", "prepared", "running", "pausing", "cancelling"]))
                .limit(1)
            ):
                raise ValueError("Pause or cancel active processing before backup or restoration")
        acquired = rt.runner._run_lock.acquire(blocking=False)
        if not acquired:
            raise ValueError("Worker is finishing a checkpoint; retry after it is paused")
        yield
    finally:
        if acquired:
            rt.runner._run_lock.release()
        with rt.access_lock:
            rt.maintenance_mode = False


def stage_restore(rt: Any, stream: Any) -> dict[str, Any]:
    now = time.monotonic()
    for token, item in list(rt.restore_tokens.items()):
        if item["expires"] < now:
            item["temporary"].cleanup()
            del rt.restore_tokens[token]
    if len(rt.restore_tokens) >= 3:
        raise ValueError("Finish or discard a pending restore before validating another backup")
    temporary = tempfile.TemporaryDirectory(prefix="anki-restore-validate-")
    directory = Path(temporary.name)
    archive = directory / "input.zip"
    try:
        count = 0
        with archive.open("wb") as destination:
            while chunk := stream.read(1024**2):
                count += len(chunk)
                if count > MAX_ARCHIVE_BYTES:
                    raise ValueError("Backup exceeds the 4 GiB compressed limit")
                destination.write(chunk)
        staging = directory / "data"
        staging.mkdir()
        summary, warnings = validate_archive(archive, staging)
        token = uuid4().hex
        rt.restore_tokens[token] = {
            "temporary": temporary,
            "staging": staging,
            "summary": summary,
            "expires": now + 3600,
        }
        return {
            "token": token,
            "summary": summary,
            "warnings": warnings,
            "requires_confirmation": True,
            "version_compatible": True,
            "expires_in_seconds": 3600,
        }
    except Exception:
        temporary.cleanup()
        raise


def restore_staged(rt: Any, token: str, *, mode: str, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("Explicit confirmation is required after reviewing backup validation")
    if mode not in {"clean", "replace"}:
        raise ValueError("Choose clean restoration or explicit replacement")
    item = rt.restore_tokens.get(token)
    if not item or item["expires"] < time.monotonic():
        raise ValueError("Restore validation expired; upload and validate the archive again")
    from sqlalchemy import func, select

    from anki_generator.database.entities import Course
    from anki_generator.database.evaluation_entities import EvaluationDataset

    with maintenance(rt):
        with rt.sessions() as session:
            if mode == "clean" and (
                session.scalar(select(func.count()).select_from(Course))
                or session.scalar(select(func.count()).select_from(EvaluationDataset))
            ):
                raise ValueError(
                    "Clean restoration requires an empty application; "
                    "use confirmed replacement otherwise"
                )
            if mode == "clean" and any(
                (rt.data_root / name).is_symlink()
                or ((rt.data_root / name).is_dir() and any((rt.data_root / name).iterdir()))
                or (rt.data_root / name).is_file()
                for name in MANAGED[3:]
            ):
                raise ValueError(
                    "Clean restoration requires empty owned data folders; "
                    "use replacement with recovery backup"
                )
        identifier = uuid4().hex
        staging = rt.data_root / f".restore-staging-{identifier}"
        previous = rt.data_root / f".restore-previous-{identifier}"
        try:
            shutil.copytree(item["staging"], staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        recovery_name = None
        if mode == "replace":
            recovery_name = f"{identifier}.zip"
            recovery = rt.data_root / "recovery" / recovery_name
            recovery.parent.mkdir(exist_ok=True)
            try:
                create_archive(rt, recovery)
            except Exception:
                recovery.unlink(missing_ok=True)
                shutil.rmtree(staging, ignore_errors=True)
                raise
        was_running = bool(rt.runner._thread and rt.runner._thread.is_alive())
        try:
            rt.runner.stop()
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if rt.runner._thread and rt.runner._thread.is_alive():
            shutil.rmtree(staging, ignore_errors=True)
            raise ValueError("Worker has not stopped; no data was moved. Restart before restoring.")
        rt.sessions.kw["bind"].dispose()
        journal = {
            "phase": "swapping",
            "previous": previous.name,
            "staging": staging.name,
            "existing": [name for name in MANAGED if (rt.data_root / name).exists()],
            "incoming": [name for name in MANAGED if (staging / name).exists()],
        }
        journal_path = rt.data_root / ".restore-journal.json"
        restored_sessions = None
        try:
            previous.mkdir()
            durable_json(journal_path, journal)
            for name in journal["existing"]:
                os.replace(rt.data_root / name, previous / name)
            for name in journal["incoming"]:
                os.replace(staging / name, rt.data_root / name)
            restored_sessions = open_database(rt.data_root)
            rt.sessions = restored_sessions
            rt.runner.session_factory = rt.sessions
            from anki_generator.services.settings import get_settings

            rt.runner.resources.configure(get_settings(rt.sessions).tasks)
            durable_json(journal_path, {**journal, "phase": "committed"})
        except Exception:
            if restored_sessions is not None:
                restored_sessions.kw["bind"].dispose()
            recover_interrupted_restore(rt.data_root)
            for directory in (previous, staging):
                if directory.exists():
                    shutil.rmtree(directory)
            rt.sessions = open_database(rt.data_root)
            rt.runner.session_factory = rt.sessions
            from anki_generator.services.settings import get_settings

            rt.runner.resources.configure(get_settings(rt.sessions).tasks)
            if was_running:
                rt.runner.start()
            raise
        cleanup_pending = False
        try:
            recover_interrupted_restore(rt.data_root)
            item["temporary"].cleanup()
        except OSError:
            # The committed database is already live. Leave the journal for the
            # next startup rather than reporting a rollback that did not occur.
            cleanup_pending = True
        finally:
            del rt.restore_tokens[token]
            if was_running:
                rt.runner.start()
        return {
            "restored": True,
            "counts": item["summary"],
            "recovery_backup": f"/api/backup/recovery/{recovery_name}" if recovery_name else None,
            "jobs_paused": True,
            "cleanup_pending": cleanup_pending,
        }
