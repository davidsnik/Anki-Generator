"""Bounded private traces of actual production rankings, with judgments pending.

This observer receives identifiers and cosine scores, never source text, request
bodies, vectors or credentials. IDs can reference private course objects, so the
result belongs in the experiment's private artifact directory, not application logs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from typing import Any


def _identity(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("Retrieval trace identifiers must be nonempty bounded strings")
    return value


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("Retrieval counts must be nonnegative integers or unknown")
    return value


class RetrievalCapture:
    def __init__(self, *, max_queries: int = 10000, max_hits: int = 128) -> None:
        if (
            type(max_queries) is not int
            or not 1 <= max_queries <= 100000
            or type(max_hits) is not int
            or not 1 <= max_hits <= 1000
        ):
            raise ValueError("Retrieval capture limits must be bounded positive integers")
        self.max_queries, self.max_hits = max_queries, max_hits
        self._lock = threading.Lock()
        self._cases: list[dict[str, Any]] = []
        self._observed = 0
        self._dropped = 0
        self._truncated_hits = 0

    def __call__(self, event: dict[str, Any]) -> None:
        if event.get("kind") != "semantic_candidates":
            raise ValueError("Only actual semantic candidate traces are supported")
        with self._lock:
            self._observed += 1
            if len(self._cases) >= self.max_queries:
                self._dropped += 1
                return
            stage = _identity(event.get("stage"))
            query_id = _identity(event.get("query_id"), optional=True)
            query_kind = _identity(event.get("query_kind"))
            candidate_kind = _identity(event.get("candidate_kind"))
            run_id = _identity(event.get("run_id"), optional=True)
            hits = event.get("hits")
            if not isinstance(hits, list):
                raise ValueError("Retrieval trace must contain its actual ordered hits")
            rows = []
            for rank, hit in enumerate(hits[: self.max_hits], start=1):
                identifier = _identity(hit.get("id"))
                score = hit.get("score")
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    raise ValueError("Retrieval scores must be finite numeric observations")
                try:
                    score = float(score)
                except OverflowError:
                    raise ValueError("Retrieval score exceeds finite numeric range") from None
                if not math.isfinite(score):
                    raise ValueError("Retrieval scores must be finite numeric observations")
                rows.append({"id": identifier, "score": float(score), "rank": rank})
            missing = max(0, len(hits) - len(rows))
            self._truncated_hits += missing
            identity = hashlib.sha256(
                json.dumps([stage, query_id, query_kind, self._observed]).encode()
            ).hexdigest()[:24]
            self._cases.append(
                {
                    "id": f"retrieval-{identity}",
                    "kind": "semantic_candidates",
                    "stage": stage,
                    "query": {"id": query_id, "kind": query_kind},
                    "candidate_kind": candidate_kind,
                    "production_run_id": run_id,
                    "hits": rows,
                    "corpus_count": _count(event.get("corpus_count")),
                    "requested_limit": _count(event.get("requested_limit")),
                    "allowed_count": _count(event.get("allowed_count")),
                    "excluded_count": _count(event.get("excluded_count")),
                    "observed_hit_count": len(hits),
                    "capture_truncated": missing > 0,
                    "judgment_status": "pending",
                    "score_scope": "Observed cosine ranking only; not relevance, equivalence "
                    "or correctness probability. Independent relevance labels are pending.",
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": "1",
                "cases": copy.deepcopy(self._cases),
                "observed_queries": self._observed,
                "captured_queries": len(self._cases),
                "dropped_queries": self._dropped,
                "truncated_hits": self._truncated_hits,
                "limits": {"max_queries": self.max_queries, "max_hits": self.max_hits},
                "label_status": "No relevance judgments supplied by capture.",
                "privacy": "Private experiment identifiers; no raw vectors or source content.",
            }
