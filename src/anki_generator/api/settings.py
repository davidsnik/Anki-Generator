"""GUI settings and credential endpoints never return stored API keys."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from anki_generator.api.runtime import runtime
from anki_generator.domain import InputModel
from anki_generator.llm.provider import DEFAULT_MODEL, OpenAIProvider
from anki_generator.services.settings import get_settings, update_settings

router = APIRouter(prefix="/api/settings")


@router.get("")
def settings(request: Request) -> dict[str, Any]:
    rt = runtime(request)
    return {**get_settings(rt.sessions).model_dump(), "key_status": rt.secrets.status()}


@router.patch("")
def save_settings(request: Request, changes: dict[str, Any]) -> dict[str, Any]:
    rt = runtime(request)
    return {**update_settings(rt.sessions, changes).model_dump(), "key_status": rt.secrets.status()}


class KeyInput(InputModel):
    api_key: str = Field(min_length=1, max_length=1000, repr=False)
    persist: bool = False


@router.put("/key")
def set_key(request: Request, values: KeyInput) -> dict[str, Any]:
    return runtime(request).secrets.set(values.api_key, persist=values.persist)


@router.delete("/key")
def remove_key(request: Request) -> dict[str, Any]:
    return runtime(request).secrets.remove()


@router.post("/test")
def test_key(request: Request) -> dict[str, Any]:
    rt = runtime(request)
    provider = OpenAIProvider(rt.secrets.get() or "")
    model = get_settings(rt.sessions).models.generation
    result = provider.test(model)
    return {
        "ok": bool(result.get("connected")),
        "message": "Connection and structured output verified.",
        **result,
    }


@router.get("/models")
def list_models(request: Request) -> dict[str, Any]:
    rt = runtime(request)
    models = (
        OpenAIProvider(rt.secrets.get() or "").models() if rt.secrets.get() else [DEFAULT_MODEL]
    )
    return {"models": [{"id": model} for model in models], "recommendation": DEFAULT_MODEL}
