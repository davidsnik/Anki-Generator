"""GUI settings and credential endpoints never return stored API keys."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from anki_generator.api.runtime import runtime
from anki_generator.domain import InputModel
from anki_generator.llm.provider import OpenAIProvider
from anki_generator.services.settings import ApplicationSettings, get_settings, update_settings

router = APIRouter(prefix="/api/settings")


@router.get("")
def settings(request: Request) -> dict[str, Any]:
    rt = runtime(request)
    return {**get_settings(rt.sessions).model_dump(), "key_status": rt.secrets.status()}


@router.patch("")
def save_settings(request: Request, changes: dict[str, Any]) -> dict[str, Any]:
    rt = runtime(request)
    with rt.settings_lock:
        saved = update_settings(rt.sessions, changes)
        rt.runner.resources.configure(saved.tasks)
        rt.runner.wake()
    return {**saved.model_dump(), "key_status": rt.secrets.status()}


class KeyInput(InputModel):
    api_key: str = Field(min_length=1, max_length=1000, repr=False)
    persist: bool = False


@router.put("/key")
def set_key(request: Request, values: KeyInput) -> dict[str, Any]:
    rt = runtime(request)
    saved = rt.secrets.set(values.api_key, persist=values.persist)
    rt.model_discovery.invalidate()
    return saved


@router.delete("/key")
def remove_key(request: Request) -> dict[str, Any]:
    rt = runtime(request)
    removed = rt.secrets.remove()
    rt.model_discovery.invalidate()
    return removed


@router.post("/test")
def test_key(request: Request) -> dict[str, Any]:
    rt = runtime(request)
    provider = OpenAIProvider(
        rt.secrets.get() or "", resources=rt.runner.resources, job_id="settings-test"
    )
    model = get_settings(rt.sessions).models.generation
    try:
        result = provider.test(model)
    finally:
        provider.close_owned_client()
    connected = bool(result.get("connected"))
    return {
        "ok": connected,
        "message": "Connection and structured output verified."
        if connected
        else "The connection test did not confirm a successful connection. "
        "Check the selected model and API key, then retry.",
        **result,
    }


@router.get("/models")
def list_models(request: Request, refresh: bool = False) -> dict[str, Any]:
    rt = runtime(request)
    key = rt.secrets.get()
    saved = get_settings(rt.sessions)
    return rt.model_discovery.catalogue(
        key,
        lambda: OpenAIProvider(
            key or "",
            resources=rt.runner.resources,
            job_id="settings-models",
            retries=0,
            request_timeout=20,
        ),
        refresh=refresh,
        selected=[*saved.models.model_dump().values(), saved.processing.embedding_model],
    )


@router.post("/models/validate")
def validate_models(request: Request, changes: dict[str, Any]) -> dict[str, Any]:
    rt = runtime(request)
    if set(changes) - {"models", "reasoning_effort", "processing"}:
        raise ValueError("Only models, reasoning effort and processing settings can be checked")
    current = get_settings(rt.sessions).model_dump()
    for name, value in changes.items():
        current[name] = {**current[name], **value} if isinstance(value, dict) else value
    configured = ApplicationSettings.model_validate(current)
    key = rt.secrets.get()
    return rt.model_discovery.validate(
        configured,
        key,
        lambda: OpenAIProvider(
            key or "",
            resources=rt.runner.resources,
            job_id="settings-models",
            retries=0,
            request_timeout=20,
        ),
    )
