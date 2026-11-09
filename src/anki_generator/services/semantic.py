"""Persistent neural representations and bounded local cosine candidate retrieval."""

import hashlib
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import select

from anki_generator.database.pipeline_entities import SemanticVector
from anki_generator.processing.state import digest


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
) -> dict[str, list[float]]:
    fingerprints = {
        item["id"]: hashlib.sha256(representation_text(item).encode()).hexdigest()
        for item in objects
    }
    result = {}
    with sessions() as session:
        for row in session.scalars(
            select(SemanticVector).where(
                SemanticVector.course_id == course_id,
                SemanticVector.object_type == object_type,
                SemanticVector.model == model,
                SemanticVector.dimensions == dimensions,
            )
        ):
            if not force and fingerprints.get(row.object_id) == row.text_hash:
                result[row.object_id] = row.vector
    missing = [item for item in objects if item["id"] not in result]
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

    def __init__(self, vectors: dict[str, list[float]]):
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
