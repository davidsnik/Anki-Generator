"""Conservative context accounting and lossless batching; never truncate claims."""

import json
from collections.abc import Callable, Iterable
from typing import Any


class ContextBudgetError(ValueError):
    pass


def token_upper_bound(value: Any) -> int:
    """UTF-8 byte count bounds BPE text-token count without downloading a tokenizer.

    This is deliberately conservative and is reported as a bound, not measured API
    usage. Provider token counts remain authoritative after a request completes.
    """
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    )
    return len(text.encode("utf-8"))


def ensure_request_budget(
    payload: dict[str, Any], prompt: str, schema: dict[str, Any], *, budget: int, images: int = 0
) -> dict[str, int | str]:
    # Reserve tokens for framing/schema and bounded high-detail image tiles. Each
    # tile is capped by ingestion; the API may report fewer actual image tokens.
    text_bound = (
        token_upper_bound(payload) + token_upper_bound(prompt) + token_upper_bound(schema) + 512
    )
    image_reserve = images * 4096
    total = text_bound + image_reserve
    if total > budget:
        raise ContextBudgetError(
            f"Request needs a conservative {total}-token context allowance, exceeding the "
            f"configured {budget}. Split the evidence/target batch "
            "or increase the GUI context budget. "
            "No source statement or mathematical assumption was silently truncated."
        )
    return {
        "input_token_upper_bound": total,
        "text_byte_bound": text_bound,
        "image_token_reserve": image_reserve,
        "accounting": "conservative_bound_not_usage",
    }


def bounded_batches(
    items: Iterable[Any],
    *,
    max_bytes: int,
    max_items: int,
    serialize: Callable[[Any], Any] = lambda item: item,
) -> list[list[Any]]:
    batches = []
    current = []
    size = 0
    for item in items:
        item_size = token_upper_bound(serialize(item))
        if item_size > max_bytes:
            raise ContextBudgetError(
                "One evidence/learning-target record exceeds the context budget; "
                "split it at source boundaries before requesting a model."
            )
        if current and (size + item_size > max_bytes or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += item_size
    if current:
        batches.append(current)
    return batches
