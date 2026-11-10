"""Official neural embeddings transport with the same curated failure policy."""

import math
from dataclasses import dataclass
from typing import Any

from anki_generator.llm.provider import OpenAIProvider, ProviderError


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    usage: dict[str, Any]


def embed(
    provider: OpenAIProvider, texts: list[str], *, model: str, dimensions: int
) -> EmbeddingResult:
    if not texts or len(texts) > 128 or any(not text.strip() for text in texts):
        raise ProviderError(
            "Embedding batches require 1–128 nonempty inputs.", kind="configuration"
        )
    # UTF-8 bytes conservatively bound token count; never truncate a recall target.
    if any(len(text.encode("utf-8")) > 8000 for text in texts):
        raise ProviderError(
            "A semantic target exceeds the safe embedding input budget; "
            "split the target instead of truncating it.",
            kind="configuration",
        )
    response, attempt = provider._request(
        lambda: provider._measured_sdk_call(
            lambda: provider.client.embeddings.create(
                model=model, input=texts, dimensions=dimensions, encoding_format="float"
            ),
            operation="embeddings",
        ),
        model=model,
        operation="embeddings",
    )
    try:
        records = sorted(response.data, key=lambda item: item.index)
        if [record.index for record in records] != list(range(len(texts))):
            raise ValueError("Invalid embedding record indexes")
        vectors = [list(record.embedding) for record in records]
        if any(
            len(vector) != dimensions
            or not all(math.isfinite(value) for value in vector)
            or sum(value * value for value in vector) == 0
            for vector in vectors
        ):
            raise ValueError("Invalid embedding vectors")
        usage = response.usage.model_dump()
        return EmbeddingResult(
            vectors,
            response.model,
            {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": 0,
                "total_tokens": usage.get("total_tokens", 0),
                "estimated_cost_usd": None,
                "retry_count": attempt,
                "representation": "openai_neural_embedding",
            },
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ProviderError(
            "OpenAI returned an invalid embedding batch.", kind="invalid_output"
        ) from None
