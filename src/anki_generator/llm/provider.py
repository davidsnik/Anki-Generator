"""Official OpenAI SDK structured Responses with explicit, bounded failure handling."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gpt-6-astra"
# Capability declarations are intentionally conservative. Unknown model IDs can be
# selected, but must be tested through Responses instead of guessing parameters.
MODEL_CAPABILITIES = {
    "gpt-6-astra": {
        "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        "structured_outputs": True,
        "vision": True,
        "documentation": "https://developers.openai.com/api/docs/models/gpt-6-astra",
        "verified_on": "2026-11-08",
    },
}


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider", retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@dataclass(frozen=True)
class ModelResult:
    data: BaseModel
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    response_id: str = ""


class Provider(Protocol):
    def structured(
        self,
        stage: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        *,
        model: str,
        images: list[Path] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ModelResult: ...


class OpenAIProvider:
    """No keys are logged, serialized, or exposed in error messages."""

    def __init__(
        self,
        api_key: str,
        *,
        client: Any = None,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ProviderError("Configure an OpenAI API key in Settings.", kind="authentication")
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, max_retries=0, timeout=180.0)
        self.client = client
        self.retries = min(max(retries, 0), 5)
        self.sleep = sleep

    def models(self) -> list[str]:
        try:
            return sorted(item.id for item in self.client.models.list())
        except Exception as exc:
            raise self._error(exc) from None

    def test(self, model: str = DEFAULT_MODEL) -> dict[str, Any]:
        class ConnectionCheck(BaseModel):
            connected: bool

        # Actual selected-model and Structured Outputs capability check, with no
        # course material transmitted. models.list alone does not establish this.
        result = self.structured(
            "connection",
            {"instruction": "Return connected=true."},
            ConnectionCheck,
            model=model,
        )
        return {"connected": result.data.connected, "model": result.model, "usage": result.usage}

    def structured(
        self,
        stage: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        *,
        model: str,
        images: list[Path] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ModelResult:
        from importlib.resources import files

        settings = settings or {}
        prompt_file = files("anki_generator.prompts").joinpath(f"{stage}.txt")
        if not prompt_file.is_file():
            prompt_file = files("anki_generator.prompts").joinpath("generic.txt")
        prompt = prompt_file.read_text(encoding="utf-8")
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)},
        ]
        for image in images or []:
            if image.stat().st_size > 20 * 1024 * 1024:
                raise ProviderError(
                    "A source region exceeds the 20 MiB vision limit.", kind="input"
                )
            mime = "image/jpeg" if image.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime};base64,{encoded}",
                    "detail": "high",
                }
            )
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": prompt,
            "input": [{"role": "user", "content": content}],
            "text_format": schema,
            "max_output_tokens": int(settings.get("max_output_tokens", 16000)),
            "store": False,
        }
        if model in MODEL_CAPABILITIES:
            effort = settings.get("reasoning_effort", "high")
            if effort not in MODEL_CAPABILITIES[model]["reasoning_efforts"]:
                raise ProviderError(
                    "Unsupported reasoning effort for the selected model.", kind="configuration"
                )
            kwargs["reasoning"] = {"effort": effort}
        for attempt in range(self.retries + 1):
            try:
                response = self.client.responses.parse(**kwargs)
                if getattr(response, "status", None) == "incomplete":
                    raise ProviderError(
                        "The model response was incomplete. Reduce source chunk size or increase "
                        "the output token limit, then retry.",
                        kind="incomplete",
                    )
                if getattr(response, "status", "completed") not in {None, "completed"}:
                    raise ProviderError(
                        "OpenAI did not complete this response. The saved run can be retried.",
                        kind="incomplete",
                    )
                for output in getattr(response, "output", []):
                    for part in getattr(output, "content", []):
                        if getattr(part, "type", "") == "refusal":
                            raise ProviderError(
                                "OpenAI refused this request; inspect the source and instructions.",
                                kind="refusal",
                            )
                data = getattr(response, "output_parsed", None)
                if not isinstance(data, schema):
                    raise ProviderError(
                        "The model returned invalid structured output. Retry the "
                        "stage or select another supported model.",
                        kind="invalid_output",
                    )
                usage = getattr(response, "usage", None)
                usage_data = usage.model_dump() if hasattr(usage, "model_dump") else {}
                # Price only the dated, verified Standard schedule; unknown tiers/models
                # remain unpriced rather than inventing provider charges.
                usage_data.update(
                    estimate_cost(usage_data, model, getattr(response, "service_tier", None))
                )
                return ModelResult(
                    data, usage_data, getattr(response, "model", model), getattr(response, "id", "")
                )
            except ProviderError:
                raise
            except ValidationError:
                raise ProviderError(
                    "OpenAI returned an invalid response schema. Retry this stage.",
                    kind="invalid_output",
                ) from None
            except Exception as exc:
                if type(exc).__name__ in {
                    "LengthFinishReasonError",
                    "ContentFilterFinishReasonError",
                }:
                    raise ProviderError(
                        "The model response was truncated or filtered. Reduce the source chunk "
                        "size or increase the output limit, then retry.",
                        kind="incomplete",
                    ) from None
                error = self._error(exc)
                if not error.retryable or attempt == self.retries:
                    raise error from None
                self.sleep(min(2**attempt, 16))
        raise AssertionError("Unreachable retry state")

    @staticmethod
    def _error(exc: Exception) -> ProviderError:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        if status == 401 or "Authentication" in name:
            return ProviderError(
                "The OpenAI API key is invalid or expired. Replace it in Settings.",
                kind="authentication",
            )
        if status == 403:
            return ProviderError(
                "This API key cannot access the selected model. Check project "
                "permissions or choose another model.",
                kind="permission",
            )
        if status == 429:
            code = getattr(exc, "code", "")
            if code == "insufficient_quota":
                return ProviderError(
                    "OpenAI reports insufficient API credit. Check billing and "
                    "project spend limits.",
                    kind="billing",
                )
            return ProviderError(
                "OpenAI rate limit reached. Wait briefly and retry this run.",
                kind="rate_limit",
                retryable=True,
            )
        if status in {400, 404, 422}:
            return ProviderError(
                "OpenAI rejected the model, context length, schema, or parameter. "
                "Test the selected model in Settings; reduce source chunk size "
                "if the context limit was exceeded.",
                kind="configuration",
            )
        if status is not None and status >= 500:
            return ProviderError(
                "OpenAI is temporarily unavailable. Retry this saved run.",
                kind="unavailable",
                retryable=True,
            )
        if (
            "Timeout" in name
            or "Connection" in name
            or isinstance(exc, (TimeoutError, ConnectionError))
        ):
            return ProviderError(
                "The OpenAI connection timed out or failed. Check the network "
                "and retry this saved run.",
                kind="network",
                retryable=True,
            )
        return ProviderError(
            "The OpenAI request failed. Check model configuration and retry; "
            "private request details have been omitted.",
            kind="provider",
        )


def estimate_cost(usage: dict[str, Any], model: str, service_tier: str | None) -> dict[str, Any]:
    """Published Standard text-token estimate, explicitly distinct from billing.

    No guess is made for unknown models, tiers, image-token accounting outside
    usage, cache writes, or tools. This application does not enable API tools.
    """
    if model != "gpt-6-astra" or service_tier not in {None, "default", "standard"}:
        return {"estimated_cost_usd": None}
    incoming = int(usage.get("input_tokens", 0))
    outgoing = int(usage.get("output_tokens", 0))
    cached = min(incoming, int(usage.get("input_tokens_details", {}).get("cached_tokens", 0)))
    long_context = incoming > 272000
    cost = ((incoming - cached) * 10 + cached) * (2 if long_context else 1)
    cost += outgoing * 50 * (1.5 if long_context else 1)
    return {
        "estimated_cost_usd": round(cost / 1000000, 8),
        "cost_is_estimate": True,
        "pricing_source": "https://developers.openai.com/api/docs/models/gpt-6-astra",
        "pricing_verified_on": "2026-11-08",
        "pricing_basis": "Published Standard text-token rates; actual provider charges may differ.",
    }
