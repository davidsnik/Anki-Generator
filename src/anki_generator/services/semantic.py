"""Persistent neural representations and bounded local cosine candidate retrieval."""

import hashlib
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

import numpy as np
from sqlalchemy import select, tuple_

from anki_generator.database.pipeline_entities import SemanticVector
from anki_generator.processing.state import digest
from anki_generator.services.measurements import PipelineMeasurements


def representation_text(item: dict[str, Any]) -> str:
    """Preserve question/answer targets and their mathematical assumptions intact."""
    fields = [
        str(item.get(key, ""))
        for key in ("title", "statement", "description", "question", "answer")
    ]
    assumptions = item.get("assumptions", item.get("metadata_json", {}).get("assumptions", []))
    return "\n".join([*fields, "Assumptions: " + "; ".join(assumptions)]).strip()


def ensure_vectors(
    sessions: Any,
    course_id: str,
    objects: list[dict[str, Any]],
    *,
    object_type: str,
    model: str,
    dimensions: int,
    embed_call: Callable[[list[str], str], Any],
    batch_size: int = 32,
    force: bool = False,
    measurements: PipelineMeasurements | None = None,
) -> dict[str, list[float]]:
    fingerprints = {
        item["id"]: hashlib.sha256(representation_text(item).encode()).hexdigest()
        for item in objects
    }
    result = {}
    # Query exact active revisions through the existing unique index. Historical
    # revisions remain reusable, without repeatedly decoding their JSON vectors.
    # 250 pairs + four fixed parameters stays below SQLite's legacy 999 limit.
    requested = list(fingerprints.items())
    span = (
        measurements.measure("semantic_vectors", operation="cache_lookup")
        if measurements is not None
        else nullcontext()
    )
    with span, sessions() as session:
        if not force:
            for offset in range(0, len(requested), 250):
                rows = session.execute(
                    select(SemanticVector.object_id, SemanticVector.vector).where(
                        SemanticVector.course_id == course_id,
                        SemanticVector.object_type == object_type,
                        SemanticVector.model == model,
                        SemanticVector.dimensions == dimensions,
                        tuple_(SemanticVector.object_id, SemanticVector.text_hash).in_(
                            requested[offset : offset + 250]
                        ),
                    )
                )
                for object_id, vector in rows:
                    result[object_id] = vector
    missing = [item for item in objects if item["id"] not in result]
    if measurements is not None:
        measurements.count("semantic_vectors", "requested_vectors", len(objects))
        measurements.count("semantic_vectors", "cache_hits", len(result))
        measurements.count("semantic_vectors", "cache_misses", len(missing))
    for offset in range(0, len(missing), batch_size):
        batch = missing[offset : offset + batch_size]
        response = embed_call(
            [representation_text(item) for item in batch],
            f"{object_type}:{digest([(item['id'], fingerprints[item['id']]) for item in batch])}",
        )
        if len(response.vectors) != len(batch):
            raise ValueError("Semantic embedding provider returned the wrong number of vectors")
        with sessions() as session:
            for item, vector in zip(batch, response.vectors, strict=True):
                row = session.scalar(
                    select(SemanticVector).where(
                        SemanticVector.course_id == course_id,
                        SemanticVector.object_type == object_type,
                        SemanticVector.object_id == item["id"],
                        SemanticVector.text_hash == fingerprints[item["id"]],
                        SemanticVector.model == model,
                        SemanticVector.dimensions == dimensions,
                    )
                )
                if row is not None:
                    row.vector = vector
                else:
                    session.add(
                        SemanticVector(
                            course_id=course_id,
                            object_type=object_type,
                            object_id=item["id"],
                            text_hash=fingerprints[item["id"]],
                            model=model,
                            dimensions=dimensions,
                            vector=vector,
                        )
                    )
                result[item["id"]] = vector
            session.commit()
    return result


class SemanticIndex:
    """O(n*d) vectorized retrieval per query; no dense all-pairs matrix allocation."""

    def __init__(
        self,
        vectors: dict[str, list[float]],
        *,
        measurements: PipelineMeasurements | None = None,
    ):
        self.measurements = measurements
        span = (
            measurements.measure("retrieval", operation="index_build")
            if measurements is not None
            else nullcontext()
        )
        with span:
            self._initialize(vectors)
        if measurements is not None:
            measurements.count("retrieval", "indices_built")
            measurements.count("retrieval", "indexed_vectors", len(self.ids))
            measurements.count("retrieval", "matrix_bytes_allocated", self.matrix.nbytes)

    def _initialize(self, vectors: dict[str, list[float]]) -> None:
        self.ids = list(vectors)
        if not vectors:
            self.matrix = np.empty((0, 0), dtype=np.float32)
            return
        matrix = np.asarray([vectors[key] for key in self.ids], dtype=np.float32)
        if not np.isfinite(matrix).all() or matrix.ndim != 2:
            raise ValueError("Semantic vectors must be finite and have consistent dimensions")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if (norms == 0).any():
            raise ValueError("Semantic vectors cannot have zero norm")
        self.matrix = matrix / norms

    def search(
        self,
        vector: list[float],
        *,
        limit: int = 12,
        exclude: set[str] | None = None,
        allowed: set[str] | None = None,
        query_id: str | None = None,
        stage: str = "semantic_search",
        query_kind: str = "unknown",
        candidate_kind: str = "unknown",
    ) -> list[tuple[str, float]]:
        span = (
            self.measurements.measure("retrieval", operation="cosine_search")
            if self.measurements is not None
            else nullcontext()
        )
        with span:
            ranked = self._search(vector, limit=limit, exclude=exclude, allowed=allowed)
        if self.measurements is not None:
            self.measurements.count("retrieval", "queries")
            self.measurements.count("retrieval", "candidates_returned", len(ranked))
            if self.measurements.captures_retrieval:
                self.measurements.observe_retrieval(
                    {
                        "kind": "semantic_candidates",
                        "stage": stage,
                        "query_id": query_id,
                        "query_kind": query_kind,
                        "candidate_kind": candidate_kind,
                        "corpus_count": len(self.ids),
                        "requested_limit": limit,
                        "allowed_count": len(allowed) if allowed is not None else None,
                        "excluded_count": len(exclude or ()),
                        "hits": [
                            {"id": identifier, "score": score} for identifier, score in ranked
                        ],
                    }
                )
        return ranked

    def _search(
        self,
        vector: list[float],
        *,
        limit: int,
        exclude: set[str] | None,
        allowed: set[str] | None,
    ) -> list[tuple[str, float]]:
        if not len(self.ids):
            return []
        query = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(query)
        if not np.isfinite(query).all() or norm == 0 or len(query) != self.matrix.shape[1]:
            raise ValueError("Invalid semantic query vector")
        scores = self.matrix @ (query / norm)
        if allowed is not None:
            scores = np.asarray(
                [
                    score if identifier in allowed else -np.inf
                    for identifier, score in zip(self.ids, scores, strict=True)
                ]
            )
        count = min(len(scores), limit + len(exclude or set()))
        indices = np.argpartition(-scores, count - 1)[:count] if count else []
        ranked = sorted(
            (
                (self.ids[int(i)], float(scores[i]))
                for i in indices
                if self.ids[int(i)] not in (exclude or set()) and np.isfinite(scores[i])
            ),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return ranked[:limit]
