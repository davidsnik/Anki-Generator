"""Non-secret settings in SQLite; credentials in memory or a secure OS keyring."""

import os
from typing import Any, Literal

from pydantic import Field
from sqlalchemy.orm import sessionmaker

from anki_generator.database.entities import ApplicationSetting
from anki_generator.domain import GenerationCriteria, InputModel, RoleInfluence, StageModels
from anki_generator.ingestion.contracts import ExtractionOptions


class ApplicationSettings(InputModel):
    models: StageModels = Field(default_factory=StageModels)
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_revisions: int = Field(default=2, ge=0, le=5)
    criteria: GenerationCriteria = Field(default_factory=GenerationCriteria)
    role_influence: RoleInfluence = Field(default_factory=RoleInfluence)
    extraction: ExtractionOptions = Field(default_factory=ExtractionOptions)
    theme: Literal["light", "dark", "system"] = "system"


def get_settings(sessions: sessionmaker) -> ApplicationSettings:
    with sessions() as session:
        record = session.get(ApplicationSetting, "application")
        return ApplicationSettings.model_validate(record.value if record else {})


def update_settings(sessions: sessionmaker, changes: dict[str, Any]) -> ApplicationSettings:
    current = get_settings(sessions).model_dump()
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key] = {**current[key], **value}
        else:
            current[key] = value
    validated = ApplicationSettings.model_validate(current)
    with sessions.begin() as session:
        session.merge(ApplicationSetting(key="application", value=validated.model_dump()))
    return validated


class SecretStore:
    """Only trusted system keyring backends may persist keys. No plaintext fallback."""

    service = "anki-generator"
    username = "openai-api-key"

    def __init__(self) -> None:
        self._session_key: str | None = None
        self._ignore_environment = False
        self._keyring: Any = None
        self.notice = "Session-only storage: the key is forgotten when the application stops."
        try:
            import keyring

            backend = keyring.get_keyring()
            module = type(backend).__module__
            if (
                module
                in {
                    "keyring.backends.SecretService",
                    "keyring.backends.macOS",
                    "keyring.backends.Windows",
                }
                and backend.priority > 0
            ):
                # Checking the store also establishes that the service is unlocked/usable.
                backend.get_password(self.service, self.username)
                self._keyring = backend
        except Exception:
            self._keyring = None

    def get(self) -> str | None:
        if self._session_key:
            return self._session_key
        if self._keyring:
            try:
                value = self._keyring.get_password(self.service, self.username)
                if value:
                    return value
            except Exception:
                self._keyring = None
        return None if self._ignore_environment else os.environ.get("OPENAI_API_KEY") or None

    def set(self, api_key: str, *, persist: bool = False) -> dict[str, Any]:
        if not api_key.strip() or len(api_key) > 1000 or any(c.isspace() for c in api_key):
            raise ValueError("Enter a nonempty API key without whitespace")
        self._session_key = api_key
        self._ignore_environment = True
        if self._keyring:
            try:
                # Replacing with a session key must remove a stale persistent key.
                if self._keyring.get_password(self.service, self.username):
                    self._keyring.delete_password(self.service, self.username)
                if persist:
                    self._keyring.set_password(self.service, self.username, api_key)
                    self._session_key = None
            except Exception:
                self._keyring = None
                self.notice = "The OS credential store is unavailable; using session-only storage."
        return self.status()

    def remove(self) -> dict[str, Any]:
        self._session_key = None
        self._ignore_environment = True
        if self._keyring:
            try:
                if self._keyring.get_password(self.service, self.username):
                    self._keyring.delete_password(self.service, self.username)
            except Exception as exc:
                raise ValueError("Unable to remove the key from the OS credential store") from exc
        return self.status()

    def status(self) -> dict[str, Any]:
        configured = bool(self.get())
        storage = "none"
        if configured:
            storage = (
                "session"
                if self._session_key
                else (
                    "environment"
                    if not self._ignore_environment and os.environ.get("OPENAI_API_KEY")
                    else "keyring"
                )
            )
        return {
            "configured": configured,
            "storage": storage,
            "persistent_available": self._keyring is not None,
            "notice": self.notice
            if not self._keyring
            else ("Keys can be stored in your operating system's secure credential store."),
        }
