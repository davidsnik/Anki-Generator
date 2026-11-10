"""Small reproducible synthetic controls for observed implementation defects.

These profiles measure bounded-calculation decisions and vector-cache mechanics,
not real model quality. They make no external requests and do not touch user data.
Run the same module against baseline/current package paths for paired evidence.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
from pathlib import Path
from time import perf_counter, thread_time
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from anki_generator.database.entities import Base, Course
from anki_generator.database.pipeline_entities import SemanticVector
from anki_generator.processing.contracts import SymbolicCheck
from anki_generator.processing.mathematics import _calculate
from anki_generator.services.semantic import ensure_vectors, representation_text


def mathematical_domain_profile() -> dict[str, Any]:
    cases = [
        (
            "excluded_stationary_point",
            {
                "lhs": "x/x",
                "rhs": "0",
                "variables": ["x"],
                "assumptions": ["x != 0"],
                "operation": "optimization_stationary",
                "variable": "x",
            },
            "uncertain",
        ),
        (
            "integral_leaves_assumed_domain",
            {
                "lhs": "sqrt(x*x)",
                "rhs": "0",
                "variables": ["x"],
                "assumptions": ["x > 0"],
                "operation": "integrate",
                "variable": "x",
                "bounds": ["-1", "1"],
            },
            "uncertain",
        ),
        (
            "valid_integral_with_domain",
            {
                "lhs": "sqrt(x*x)",
                "rhs": "3/2",
                "variables": ["x"],
                "assumptions": ["x > 0"],
                "operation": "integrate",
                "variable": "x",
                "bounds": ["1", "2"],
            },
            "pass",
        ),
    ]
    rows = []
    for identifier, values, expected in cases:
        check = SymbolicCheck(**values, purpose="Synthetic domain-boundary engineering control")
        started = perf_counter()
        result = _calculate(check)
        rows.append(
            {
                "id": identifier,
                "input": check.model_dump(),
                "expected_verdict": expected,
                "result": result,
                "wall_seconds": perf_counter() - started,
                "decision_matches_reference": result["verdict"] == expected,
            }
        )
    return {
        "cases": rows,
        "matching_decisions": sum(row["decision_matches_reference"] for row in rows),
        "denominator": len(rows),
        "reference_origin": "deterministic_authored_domain_control",
        "scope": "Underlying bounded-calculation semantics; not arbitrary proof validation.",
    }


def semantic_cache_profiles(
    *, objects_count: int = 100, dimensions: int = 64, repetitions: int = 5
) -> list[dict[str, Any]]:
    if not 1 <= objects_count <= 2000 or not 2 <= dimensions <= 3072 or not 1 <= repetitions <= 20:
        raise ValueError("Engineering workload dimensions/repetitions exceed bounded limits")
    rows = []
    for history in (0, 50):
        decoded = [0]

        def deserialize(value, counter=decoded):
            counter[0] += 1
            return json.loads(value)

        with tempfile.TemporaryDirectory(prefix="anki-vector-cache-profile-") as temporary:
            engine = create_engine(
                f"sqlite:///{Path(temporary) / 'vectors.sqlite'}", json_deserializer=deserialize
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(engine)
            objects = [
                {"id": f"object-{i}", "title": f"Target {i}", "assumptions": ["x > 0"]}
                for i in range(objects_count)
            ]
            active_vector = [1.0] + [0.0] * (dimensions - 1)
            with sessions.begin() as session:
                course = Course(name="Synthetic historical-vector profile", deck_name="Profile")
                session.add(course)
                session.flush()
                course_id = course.id
                for item in objects:
                    hashes = [hashlib.sha256(representation_text(item).encode()).hexdigest()]
                    hashes.extend(
                        hashlib.sha256(f"old-{h}-{item['id']}".encode()).hexdigest()
                        for h in range(history)
                    )
                    session.add_all(
                        SemanticVector(
                            course_id=course_id,
                            object_type="concept",
                            object_id=item["id"],
                            text_hash=fingerprint,
                            model="synthetic-engineering-profile",
                            dimensions=dimensions,
                            vector=active_vector,
                        )
                        for fingerprint in hashes
                    )

            def unexpected_embedding(*args):
                raise AssertionError("Unchanged exact targets must reuse cached vectors")

            trials = []
            for _ in range(repetitions):
                decoded[0] = 0
                started, cpu = perf_counter(), thread_time()
                result = ensure_vectors(
                    sessions,
                    course_id,
                    objects,
                    object_type="concept",
                    model="synthetic-engineering-profile",
                    dimensions=dimensions,
                    embed_call=unexpected_embedding,
                )
                elapsed, consumed = perf_counter() - started, thread_time() - cpu
                assert len(result) == objects_count
                assert all(vector == active_vector for vector in result.values())
                trials.append(
                    {
                        "wall_seconds": elapsed,
                        "initiating_thread_cpu_seconds": consumed,
                        "vector_json_rows_decoded": decoded[0],
                        "returned_vectors": len(result),
                        "embedding_calls": 0,
                    }
                )
            rows.append(
                {
                    "historical_versions_per_object": history,
                    "requested_objects": objects_count,
                    "dimensions": dimensions,
                    "stored_rows": objects_count * (history + 1),
                    "repetitions": repetitions,
                    "trials": trials,
                    "wall_seconds_mean": sum(t["wall_seconds"] for t in trials) / repetitions,
                    "decoded_rows_mean": sum(t["vector_json_rows_decoded"] for t in trials)
                    / repetitions,
                    "scope": "Query + decoding active vectors; database seeding is excluded.",
                }
            )
            engine.dispose()
    return rows


def collect_engineering_profiles() -> dict[str, Any]:
    from datetime import UTC, datetime

    return {
        "schema_version": "1",
        "created_at": datetime.now(UTC).isoformat(),
        "evidence": "deterministic_synthetic_engineering",
        "source_sha256": {
            name: hashlib.sha256(Path(inspect.getfile(function)).read_bytes()).hexdigest()
            for name, function in (("mathematics", _calculate), ("semantic_cache", ensure_vectors))
        },
        "mathematics": mathematical_domain_profile(),
        "semantic_cache": semantic_cache_profiles(),
        "limitations": [
            "Author-created controls, not real-course or independently human-validated quality.",
            "No model responses, API usage, cost, or retrieval relevance is simulated.",
            "Timing varies by machine/cache/load; five paired trials are descriptive evidence.",
            "Domain cases call underlying semantics; subprocess resource guards "
            "have separate tests.",
        ],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    # File-path entry point permits the new collector to import the untouched
    # baseline package via PYTHONPATH, which does not have benchmark/ yet.
    if arguments.output.exists():
        parser.error("Choose a new output file; existing measurements are immutable")
    report = collect_engineering_profiles()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(arguments.output)
