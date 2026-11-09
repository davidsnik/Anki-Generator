"""Application-owned database, credential state, storage, and durable worker."""

from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import Request

from anki_generator.database.connection import open_database
from anki_generator.services.settings import SecretStore


class Runtime:
    def __init__(self, data_root: Path, *, provider_factory: Any = None) -> None:
        self.provider_kind = "injected_test_provider" if provider_factory is not None else "openai"
        self.data_root = data_root.resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.data_root.chmod(0o700)
        from anki_generator.services.backups import recover_interrupted_restore

        recover_interrupted_restore(self.data_root)
        self.access_lock = Lock()
        self.restore_validation_lock = Lock()
        self.settings_lock = Lock()
        self.active_requests = 0
        self.maintenance_mode = False
        self.restore_tokens: dict[str, Any] = {}
        self.sessions = open_database(self.data_root)
        self.secrets = SecretStore()
        from anki_generator.orchestration.runner import DurableRunner

        self.runner = DurableRunner(
            self.sessions, self.data_root, self.secrets.get, provider_factory=provider_factory
        )


def runtime(request: Request) -> Runtime:
    return request.app.state.runtime
