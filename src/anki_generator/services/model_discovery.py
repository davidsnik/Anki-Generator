"""Credential-scoped, in-memory discovery and non-generating model preflight."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from anki_generator.domain import StageModels
from anki_generator.llm.model_catalogue import (
    CATALOGUE,
    DEFAULT_MODEL,
    VERIFIED_ON,
    model_description,
)
from anki_generator.llm.provider import OpenAIProvider, ProviderError
from anki_generator.services.settings import ApplicationSettings


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


class ModelDiscovery:
    """One credential's listing, never written to SQLite, disk, logs or backups.

    The lock coalesces concurrent discovery, not generation or SQLite writes.
    A failed refresh discards the previous success: stale availability is unsafe.
    """

    def __init__(self, *, ttl: float = 600, clock: Callable[[], float] = time.time):
        self.ttl, self.clock = ttl, clock
        self._lock = Lock()
        self._identity: bytes | None = None
        self._ids: set[str] = set()
        self._fetched_at: float | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._identity, self._fetched_at = None, None
            self._ids.clear()

    @staticmethod
    def _credential_identity(key: str) -> bytes:
        # An alternate API origin is a different account listing too. Only the
        # digest remains in memory, and neither it nor the key is returned.
        return hashlib.sha256(
            (key + "\0" + os.environ.get("OPENAI_BASE_URL", "")).encode()
        ).digest()

    def _listing(
        self, key: str, provider_factory: Callable[[], OpenAIProvider], *, refresh: bool
    ) -> tuple[set[str], float, bool]:
        identity = self._credential_identity(key)
        with self._lock:
            now = self.clock()
            if (
                not refresh
                and self._identity == identity
                and self._fetched_at is not None
                and now - self._fetched_at < self.ttl
            ):
                return self._ids.copy(), self._fetched_at, True
            self._identity, self._fetched_at = None, None
            self._ids.clear()
            provider = provider_factory()
            try:
                identifiers = provider.models()
            finally:
                provider.close_owned_client()
            if any(
                not isinstance(item, str)
                or not item
                or len(item) > 200
                or any(character.isspace() or ord(character) < 32 for character in item)
                for item in identifiers
            ):
                raise ProviderError("OpenAI returned an invalid model list.", kind="invalid_output")
            self._identity, self._ids = identity, set(identifiers)
            self._fetched_at = self.clock()
            return self._ids.copy(), self._fetched_at, False

    def catalogue(
        self,
        key: str | None,
        provider_factory: Callable[[], OpenAIProvider],
        *,
        refresh: bool = False,
        selected: list[str] | None = None,
    ) -> dict[str, Any]:
        ids: set[str] | None = None
        fetched_at = None
        cached = False
        error = None
        status = "missing_key"
        if key:
            try:
                ids, fetched_at, cached = self._listing(key, provider_factory, refresh=refresh)
                status = "ready"
            except ProviderError as exc:
                status = "error"
                error = {"kind": exc.kind, "message": str(exc), "retryable": exc.retryable}
        else:
            self.invalidate()
        identifiers = set(CATALOGUE) | (ids or set()) | set(selected or [])
        return {
            "status": status,
            "models": [
                model_description(
                    item,
                    item in ids if ids is not None and (item in ids or item in CATALOGUE) else None,
                )
                for item in sorted(identifiers)
            ],
            "defaults": StageModels().model_dump(),
            "default_embedding_model": "text-embedding-3-small",
            "recommendation": DEFAULT_MODEL,
            "fetched_at": _timestamp(fetched_at) if fetched_at is not None else None,
            "cache_expires_at": _timestamp(fetched_at + self.ttl)
            if fetched_at is not None
            else None,
            "cached": cached,
            "error": error,
            "catalogue_verified_on": VERIFIED_ON,
            "notice": (
                "Account discovery confirms model visibility, not endpoint permissions or billing. "
                "Compatibility comes from dated official documentation for exact recognized IDs; "
                "other models remain unverified. No prices are inferred."
            ),
        }

    def validate(
        self,
        settings: ApplicationSettings,
        key: str | None,
        provider_factory: Callable[[], OpenAIProvider],
        *,
        mode: str = "generate",
    ) -> dict[str, Any]:
        issues: list[dict[str, str]] = []

        def issue(stage: str, model: str, severity: str, code: str, message: str) -> None:
            issues.append(
                {
                    "stage": stage,
                    "model": model,
                    "severity": severity,
                    "code": code,
                    "message": message,
                }
            )

        if not key:
            issue("configuration", "", "error", "missing_key", "Add an OpenAI API key in Settings.")
            return {"valid": False, "issues": issues, "checked_at": _timestamp(self.clock())}
        try:
            ids, _, _ = self._listing(key, provider_factory, refresh=False)
        except ProviderError as exc:
            issue("configuration", "", "error", exc.kind, str(exc))
            return {"valid": False, "issues": issues, "checked_at": _timestamp(self.clock())}

        selected = settings.models.model_dump()
        # Interpretation stops before course reasoning and neural retrieval.
        # Validate only models that can run in this task mode.
        if mode == "interpret":
            selected = {"interpretation": selected["interpretation"]}
        else:
            selected["embeddings"] = settings.processing.embedding_model
        retrieved: dict[str, bool] = {}
        for stage, identifier in selected.items():
            description = model_description(identifier, identifier in ids)
            compatible = description["compatibility"][stage]
            if compatible == "unsupported":
                issue(
                    stage,
                    identifier,
                    "error",
                    "incompatible",
                    f"{description['name']} cannot perform {stage}. Choose a compatible model.",
                )
                continue
            if identifier not in ids:
                # Custom/fine-tuned IDs may not be returned in the list. A free
                # metadata lookup checks their visibility without sending data.
                if identifier in CATALOGUE:
                    retrieved[identifier] = False
                elif identifier not in retrieved:
                    provider = provider_factory()
                    try:
                        retrieved[identifier] = provider.retrieve_model(identifier) == identifier
                    except ProviderError as exc:
                        if exc.kind not in {"configuration", "permission"}:
                            issue(stage, identifier, "error", exc.kind, str(exc))
                            return {
                                "valid": False,
                                "issues": issues,
                                "checked_at": _timestamp(self.clock()),
                            }
                        retrieved[identifier] = False
                    finally:
                        provider.close_owned_client()
                if not retrieved[identifier]:
                    issue(
                        stage,
                        identifier,
                        "error",
                        "unavailable",
                        f"{identifier} is unavailable to this API key. Refresh models, check "
                        "project permissions, or choose another model.",
                    )
                    continue
            if compatible == "unknown":
                requirement = (
                    "This stage needs the Embeddings endpoint and output vectors with the "
                    "selected dimensions; their support is unverified. "
                    if stage == "embeddings"
                    else "This stage needs Responses, structured outputs and source-image input. "
                )
                issue(
                    stage,
                    identifier,
                    "warning",
                    "unverified_capabilities",
                    f"{identifier} is visible to your account, but compatibility is unverified. "
                    + requirement
                    + "The provider may reject this advanced selection.",
                )
            capability = CATALOGUE.get(identifier)
            if (
                capability
                and capability.reasoning_efforts
                and settings.reasoning_effort not in capability.reasoning_efforts
            ):
                issue(
                    stage,
                    identifier,
                    "error",
                    "reasoning_effort",
                    f"{description['name']} does not support the selected reasoning effort.",
                )
        return {
            "valid": not any(item["severity"] == "error" for item in issues),
            "issues": issues,
            "checked_at": _timestamp(self.clock()),
        }


def provider_for_discovery(rt: Any, key: str) -> OpenAIProvider:
    return OpenAIProvider(
        key, resources=rt.runner.resources, job_id="model-preflight", retries=0, request_timeout=20
    )


def preflight_run(rt: Any, effective: dict[str, Any], mode: str) -> None:
    if mode == "extract" or rt.runner.uses_custom_provider:
        # create_app(provider_factory=...) and direct Python assignment are
        # explicit testing seams. No HTTP flag or environment bypass exists.
        return
    key = rt.secrets.get()
    report = rt.model_discovery.validate(
        ApplicationSettings.model_validate(effective),
        key,
        lambda: provider_for_discovery(rt, key or ""),
        mode=mode,
    )
    errors = [item["message"] for item in report["issues"] if item["severity"] == "error"]
    if errors:
        raise ValueError("Model setup needs attention: " + " ".join(dict.fromkeys(errors)))
