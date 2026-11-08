"""Application-owned database, credential state, storage, and durable worker."""

from pathlib import Path
from typing import Any

from fastapi import Request

from anki_generator.database.connection import open_database
from anki_generator.services.settings import SecretStore


class Runtime:
    def __init__(self, data_root: Path, *, provider_factory: Any = None) -> None:
        self.data_root = data_root.resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.data_root.chmod(0o700)
        self.sessions = open_database(self.data_root)
        self.secrets = SecretStore()
        from anki_generator.orchestration.runner import DurableRunner

        self.runner = DurableRunner(
            self.sessions, self.data_root, self.secrets.get, provider_factory=provider_factory
        )


def runtime(request: Request) -> Runtime:
    return request.app.state.runtime
