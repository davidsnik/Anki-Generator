"""Bounded lifecycle logs containing only allowlisted diagnostic metadata."""

import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

EVENTS = {"starting", "ready", "parent_exited", "stopped", "startup_failed", "readiness_failed"}
MAX_LOG_BYTES = 1024 * 1024
BACKUP_COUNT = 3


class SafeServerFilter(logging.Filter):
    """Do not send exception values, URL details or credentials to shell logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = "Backend HTTP server reported a diagnostic event"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def event_record(event: str, *, category: str | None = None) -> dict[str, Any]:
    if event not in EVENTS:
        raise ValueError("Unknown desktop lifecycle event")
    record: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "pid": os.getpid(),
    }
    if category in {
        "configuration",
        "storage",
        "database",
        "bind",
        "runtime",
        "timeout",
        "resources",
    }:
        record["category"] = category
    return record


class LifecycleLog:
    def __init__(self, state_directory: Path):
        directory = state_directory / "logs"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        path = directory / "backend.log"
        # Private file creation precedes the logging handler's open.
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(descriptor)
        path.chmod(0o600)
        self.handler = RotatingFileHandler(
            path, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def event(self, name: str, *, category: str | None = None) -> None:
        message = json.dumps(event_record(name, category=category))
        self.handler.handle(logging.LogRecord("desktop", logging.INFO, "", 0, message, (), None))
        # Rollover preserves0600 from the previously created private file.
        Path(self.handler.baseFilename).chmod(0o600)

    def close(self) -> None:
        self.handler.close()


def safe_events(state_directory: Path | None) -> list[dict[str, Any]]:
    if state_directory is None:
        return []
    path = state_directory / "logs/backend.log"
    if not path.is_file() or path.is_symlink():
        return []
    result = []
    # Never copy a raw log line, exception, source, provider message or key.
    with path.open("rb") as stream:
        payload = stream.read(MAX_LOG_BYTES)
    for line in payload.splitlines()[-200:]:
        try:
            record = json.loads(line)
            timestamp = datetime.fromisoformat(record["timestamp"]).isoformat()
            if record["event"] not in EVENTS or type(record["pid"]) is not int:
                continue
            clean = {"timestamp": timestamp, "event": record["event"], "pid": record["pid"]}
            if record.get("category") in {
                "configuration",
                "storage",
                "database",
                "bind",
                "runtime",
                "timeout",
                "resources",
            }:
                clean["category"] = record["category"]
            result.append(clean)
        except (ValueError, TypeError, KeyError):
            continue
    return result
