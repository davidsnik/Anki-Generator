"""Small, exact-ID capability catalogue checked against official model pages.

Account discovery is authoritative for availability, not capability or pricing.
Never infer capabilities from a model's prefix, snapshot or fine-tuning parent.
"""

from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "gpt-6-astra"
VERIFIED_ON = "2026-11-09"
STAGES = ("interpretation", "knowledge", "generation", "factual", "pedagogical", "coverage")


@dataclass(frozen=True)
class ModelCapabilities:
    name: str
    group: str
    responses: bool
    structured_outputs: bool
    vision: bool
    embeddings: bool
    reasoning_efforts: tuple[str, ...] = ()


_REASONING = ("low", "medium", "high", "xhigh", "max")
CATALOGUE = {
    "gpt-6-astra": ModelCapabilities("GPT-6 Astra", "general", True, True, True, False, _REASONING),
    "gpt-6.1-sol": ModelCapabilities("GPT-6.1 Sol", "general", True, True, True, False, _REASONING),
    "gpt-6-luna": ModelCapabilities(
        "GPT-6 Luna", "general", True, True, True, False, ("none", *_REASONING)
    ),
    "gpt-4.1": ModelCapabilities("GPT-4.1", "general", True, True, True, False),
    "text-embedding-3-small": ModelCapabilities(
        "Text Embedding 3 Small", "embeddings", False, False, False, True
    ),
    "text-embedding-3-large": ModelCapabilities(
        "Text Embedding 3 Large", "embeddings", False, False, False, True
    ),
}


def model_description(identifier: str, available: bool | None) -> dict[str, Any]:
    known = CATALOGUE.get(identifier)
    capabilities = {
        name: getattr(known, name) if known else None
        for name in ("responses", "structured_outputs", "vision", "embeddings")
    }
    capabilities["reasoning_efforts"] = list(known.reasoning_efforts) if known else None
    compatibility = {}
    for stage in (*STAGES, "embeddings"):
        if known is None:
            compatibility[stage] = "unknown"
        else:
            supported = (
                known.embeddings
                if stage == "embeddings"
                else known.responses and known.structured_outputs and known.vision
            )
            # Evidence images can be attached by knowledge, review and coverage
            # as well as interpretation. Every general stage needs vision.
            compatibility[stage] = "supported" if supported else "unsupported"
    return {
        "id": identifier,
        "name": known.name if known else identifier,
        "group": known.group if known else "unverified",
        "available": available,
        "capabilities": capabilities,
        "compatibility": compatibility,
        "recommended_for": list(STAGES)
        if identifier == DEFAULT_MODEL
        else (["embeddings"] if identifier == "text-embedding-3-small" else []),
        "documentation": f"https://developers.openai.com/api/docs/models/{identifier}"
        if known
        else None,
        "verified_on": VERIFIED_ON if known else None,
    }
