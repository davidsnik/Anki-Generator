"""Official SDK request shapes and provider failure policy, without network calls."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from anki_generator.llm import OpenAIProvider, ProviderError
from anki_generator.llm.provider import DEFAULT_MODEL, MODEL_CAPABILITIES, estimate_cost


class Answer(BaseModel):
    answer: str


class StatusError(Exception):
    def __init__(self, status_code, code=None):
        self.status_code = status_code
        self.code = code
        super().__init__("SECRET-KEY raw private SDK error must never be persisted")


class FakeResponses:
    def __init__(self, *values):
        self.values = iter(values)
        self.requests = []

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        result = next(self.values)
        if isinstance(result, Exception):
            raise result
        return result


def response(**overrides):
    defaults = dict(
        status="completed",
        output_parsed=Answer(answer="Supported"),
        output=[],
        usage=SimpleNamespace(
            model_dump=lambda: {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        ),
        model=DEFAULT_MODEL,
        id="response-test",
    )
    return SimpleNamespace(**(defaults | overrides))


def provider(*values):
    fake = FakeResponses(*values)
    sleeps = []
    instance = OpenAIProvider(
        "SECRET-KEY",
        client=SimpleNamespace(responses=fake),
        sleep=sleeps.append,
        jitter=lambda: 0.5,
    )
    return instance, fake, sleeps


def invoke(instance, **kwargs):
    return instance.structured(
        "factual", {"evidence": "source"}, Answer, model=DEFAULT_MODEL, **kwargs
    )


def test_supported_sdk_structured_shape_and_no_provider_storage():
    instance, fake, _ = provider(response())
    result = invoke(instance)
    request = fake.requests[0]
    assert request["text_format"] is Answer
    assert request["store"] is False
    assert request["reasoning"] == {"effort": "high"}
    assert request["input"][0]["content"][0]["type"] == "input_text"
    assert result.data.answer == "Supported"
    assert result.usage["total_tokens"] == 120
    assert result.usage["estimated_cost_usd"] > 0
    assert "SECRET-KEY" not in str(result)


def test_unknown_model_does_not_guess_reasoning_or_temperature():
    instance, fake, _ = provider(response())
    instance.structured("factual", {}, Answer, model="account-custom-model")
    assert "reasoning" not in fake.requests[0]
    assert "temperature" not in fake.requests[0]


@pytest.mark.parametrize(
    "status,kind,retryable",
    [
        (401, "authentication", False),
        (403, "permission", False),
        (400, "configuration", False),
        (404, "configuration", False),
        (422, "configuration", False),
        (429, "rate_limit", True),
        (503, "unavailable", True),
    ],
)
def test_errors_are_actionable_sanitized_and_bounded(status, kind, retryable):
    instance, fake, sleeps = provider(*[StatusError(status) for _ in range(4)])
    with pytest.raises(ProviderError) as caught:
        invoke(instance)
    assert caught.value.kind == kind
    assert caught.value.retryable == retryable
    assert "SECRET-KEY" not in str(caught.value)
    assert len(fake.requests) == (4 if retryable else 1)
    assert sleeps == ([1, 2, 4] if retryable else [])


def test_billing_quota_is_permanent():
    instance, fake, sleeps = provider(StatusError(429, "insufficient_quota"))
    with pytest.raises(ProviderError, match="credit") as caught:
        invoke(instance)
    assert caught.value.kind == "billing"
    assert len(fake.requests) == 1 and not sleeps


def test_transient_failures_retry_then_succeed():
    instance, fake, sleeps = provider(TimeoutError(), StatusError(503), response())
    assert invoke(instance).data.answer == "Supported"
    assert sleeps == [1, 2] and len(fake.requests) == 3


@pytest.mark.parametrize(
    "value,kind",
    [
        (response(status="incomplete"), "incomplete"),
        (response(output_parsed=None), "invalid_output"),
        (response(output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])]), "refusal"),
    ],
)
def test_invalid_incomplete_refused_responses_are_not_accepted(value, kind):
    instance, fake, sleeps = provider(value)
    with pytest.raises(ProviderError) as caught:
        invoke(instance)
    assert caught.value.kind == kind
    assert len(fake.requests) == 1 and not sleeps


def test_vision_regions_are_backend_encoded_with_supported_content_shape(tmp_path):
    image = tmp_path / "region.png"
    image.write_bytes(b"fake-png-for-request-shape")
    instance, fake, _ = provider(response())
    invoke(instance, images=[image])
    content = fake.requests[0]["input"][0]["content"][1]
    assert content["type"] == "input_image" and content["detail"] == "high"
    assert content["image_url"].startswith("data:image/png;base64,")


def test_verified_model_registry_and_effort_validation():
    assert MODEL_CAPABILITIES[DEFAULT_MODEL]["vision"]
    instance, fake, _ = provider(response())
    with pytest.raises(ProviderError, match="reasoning effort"):
        invoke(instance, settings={"reasoning_effort": "guessed-effort"})
    assert not fake.requests


def test_pricing_estimates_never_guess_unknown_models_or_tiers():
    usage = {
        "input_tokens": 1000,
        "output_tokens": 1000,
        "input_tokens_details": {"cached_tokens": 500},
    }
    assert estimate_cost(usage, DEFAULT_MODEL, "default")["estimated_cost_usd"] == 0.0555
    assert estimate_cost(usage, "unknown-model", None)["estimated_cost_usd"] is None
    assert estimate_cost(usage, DEFAULT_MODEL, "flex")["estimated_cost_usd"] is None


def test_invalid_schema_exception_is_reported_without_private_output():
    from pydantic import ValidationError

    try:
        Answer.model_validate({"untrusted_field": "SECRET-KEY"})
    except ValidationError as error:
        instance, fake, sleeps = provider(error)
    with pytest.raises(ProviderError) as caught:
        invoke(instance)
    assert caught.value.kind == "invalid_output"
    assert "SECRET-KEY" not in str(caught.value)
    assert not sleeps and len(fake.requests) == 1


def test_failed_response_status_cannot_accept_an_incidental_parsed_field():
    instance, _, _ = provider(response(status="failed"))
    with pytest.raises(ProviderError) as caught:
        invoke(instance)
    assert caught.value.kind == "incomplete"
