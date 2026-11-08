"""Prevent two backend processes from spending against the same durable queue."""

import os
from pathlib import Path
from typing import IO


class InstanceLock:
    def __init__(self, root: Path) -> None:
        self.path = root / ".application.lock"
        self.stream: IO[str] | None = None

    def acquire(self) -> None:
        stream = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError(
                "Another application instance owns this data directory. Stop it first, "
                "or choose a different --data-directory."
            ) from exc
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        self.stream = stream

    def release(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None
