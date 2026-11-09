"""Official OpenAI SDK structured Responses with explicit, bounded failure handling."""

from __future__ import annotations

import base64
import copy
import json
import math
import random
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from anki_generator.orchestration.resources import GlobalResources

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
        jitter: Callable[[], float] = random.random,
        resources: GlobalResources | None = None,
        job_id: str = "interactive",
        checkpoint: Callable[[], None] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ):
        if not api_key:
            raise ProviderError("Configure an OpenAI API key in Settings.", kind="authentication")
        self._owns_client = client is None
        self._client_closed = False
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, max_retries=0, timeout=180.0)
        self.client = client
        self.retries = min(max(retries, 0), 5)
        self.sleep = sleep
        self.jitter = jitter
        self.resources = resources
        self.job_id = job_id
        self.checkpoint = checkpoint
        self.on_event = on_event

    def with_resources(
        self,
        resources: GlobalResources,
        job_id: str,
        *,
        checkpoint: Callable[[], None] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> OpenAIProvider:
        """Bind a job without mutating a possibly shared injected SDK transport."""
        bound = copy.copy(self)
        bound.resources, bound.job_id = resources, job_id
        bound.checkpoint, bound.on_event = checkpoint, on_event
        return bound

    def close_owned_client(self) -> bool:
        """Close internally created SDK sockets; injected/shared clients stay owned by callers."""
        if not self._owns_client or self._client_closed:
            return True
        try:
            self.client.close()
        except Exception:
            return False
        self._client_closed = True
        return True

    def _wait(self, delay: float) -> None:
        if self.checkpoint:
            self.checkpoint()
        if self.sleep is not time.sleep or self.checkpoint is None:
            self.sleep(delay)
        else:
            deadline = time.monotonic() + delay
            while (remaining := deadline - time.monotonic()) > 0:
                self.checkpoint()
                self.sleep(min(remaining, 0.2))
        if self.checkpoint:
            self.checkpoint()

    def _emit(self, kind: str, **details: Any) -> None:
        if self.on_event:
            self.on_event({"kind": kind, **details})

    def _request(self, call: Callable[[], Any], *, model: str, operation: str) -> tuple[Any, int]:
        """Acquire only for a physical attempt; checkpoints/backoff hold no slot."""
        for attempt in range(self.retries + 1):
            if self.checkpoint:
                self.checkpoint()
            slot = (
                self.resources.api(
                    self.job_id, model, checkpoint=self.checkpoint, on_event=self.on_event
                )
                if self.resources
                else nullcontext()
            )
            failure = None
            retry_after = None
            retry_allowed = True
            # Admission/checkpoint exceptions deliberately sit outside the SDK
            # error handler: pause/cancel is never converted to a provider failure.
            with slot:
                try:
                    return call(), attempt
                except ProviderError:
                    raise
                except ValidationError:
                    raise ProviderError(
                        "OpenAI returned an invalid response schema. Retry this stage.",
                        kind="invalid_output",
                    ) from None
                except Exception as exc:
                    failure = self._error(exc)
                    retry_after = retry_after_seconds(exc)
                    headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(
                        exc, "headers", {}
                    )
                    retry_allowed = headers.get("x-should-retry", "").lower() != "false"
            if not failure.retryable or attempt == self.retries:
                self._emit(
                    "api_failure",
                    operation=operation,
                    model=model,
                    attempts=attempt + 1,
                    error_kind=failure.kind,
                    retryable=failure.retryable,
                )
                raise failure from None
            if not retry_allowed:
                raise failure from None
            if retry_after is not None and retry_after > 120:
                raise ProviderError(
                    "OpenAI requested a wait beyond the automatic retry limit. "
                    "Retry this saved run later.",
                    kind=failure.kind,
                    retryable=True,
                ) from None
            delay = (
                retry_after
                if retry_after is not None and retry_after > 0
                else min(2**attempt * (0.75 + 0.5 * self.jitter()), 30)
            )
            self._emit(
                "api_retry",
                operation=operation,
                model=model,
                attempt=attempt + 1,
                max_attempts=self.retries + 1,
                delay_seconds=round(delay, 4),
                error_kind=failure.kind,
                retry_after=retry_after is not None,
            )
            self._wait(delay)
        raise AssertionError("Unreachable retry state")

    def embed(self, texts: list[str], *, model: str, dimensions: int):
        from anki_generator.llm.embeddings import embed

        return embed(self, texts, model=model, dimensions=dimensions)

    def models(self) -> list[str]:
        values, _ = self._request(
            lambda: list(self.client.models.list()), model="models-list", operation="models"
        )
        return sorted(item.id for item in values)

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
        prompt = settings.get("instructions_override") or prompt_file.read_text(encoding="utf-8")
        text = json.dumps(payload, ensure_ascii=False)
        if len(images or []) > 12:
            raise ProviderError("Split vision requests into at most 12 regions.", kind="input")
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": prompt,
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

        def physical_request():
            # Base64 and SDK JSON bodies are allocated only after shared admission,
            # never for every queued job. Rebuild per attempt so backoff releases
            # encoded payloads and failed SDK exception/request objects too.
            content = [{"type": "input_text", "text": text}]
            total_bytes = 0
            for image in images or []:
                size = image.stat().st_size
                if size > 20 * 1024 * 1024 or total_bytes + size > 64 * 1024 * 1024:
                    raise ProviderError(
                        "Vision regions exceed the 20 MiB per-image or 64 MiB request limit. "
                        "Reduce the image batch size.",
                        kind="input",
                    )
                raw = image.read_bytes()
                total_bytes += len(raw)
                if len(raw) > 20 * 1024 * 1024 or total_bytes > 64 * 1024 * 1024:
                    raise ProviderError(
                        "Vision input changed or exceeds its safe size.", kind="input"
                    )
                mime = "image/jpeg" if image.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
                encoded = base64.b64encode(raw).decode("ascii")
                content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime};base64,{encoded}",
                        "detail": "high",
                    }
                )
                del raw, encoded
            return self.client.responses.parse(
                **kwargs, input=[{"role": "user", "content": content}]
            )

        response, attempt = self._request(physical_request, model=model, operation=stage)
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
        usage_data["retry_count"] = attempt
        usage_data.update(estimate_cost(usage_data, model, getattr(response, "service_tier", None)))
        return ModelResult(
            data, usage_data, getattr(response, "model", model), getattr(response, "id", "")
        )

    @staticmethod
    def _error(exc: Exception) -> ProviderError:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        if name in {"LengthFinishReasonError", "ContentFilterFinishReasonError"}:
            return ProviderError(
                "The model response was truncated or filtered. Reduce the source chunk "
                "size or increase the output limit, then retry.",
                kind="incomplete",
            )
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
        if status in {408, 409} or (status is not None and status >= 500):
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


def retry_after_seconds(exc: Exception | None, *, now: float | None = None) -> float | None:
    """Read SDK response headers without persisting provider/request contents."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(
        exc, "headers", {}
    )
    for name, factor in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            delay = float(value) * factor
        except (TypeError, ValueError):
            if name != "retry-after":
                continue
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                delay = date.timestamp() - (time.time() if now is None else now)
            except (TypeError, ValueError, OverflowError):
                continue
        if math.isfinite(delay):
            return max(0, delay)
    return None


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
