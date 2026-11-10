"""Revision-aware caches avoid decoding historical/irrelevant vector JSON."""

import hashlib
from types import SimpleNamespace

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from anki_generator.database.entities import Base, Course
from anki_generator.database.pipeline_entities import SemanticVector
from anki_generator.services.measurements import PipelineMeasurements
from anki_generator.services.semantic import ensure_vectors, representation_text


def test_cache_queries_only_active_pairs_in_bounded_batches_and_preserves_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vectors.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    objects = [{"id": f"object-{i}", "title": f"Target {i}"} for i in range(510)]
    with sessions.begin() as session:
        course = Course(name="Synthetic vector revisions", deck_name="Cache tests")
        session.add(course)
        session.flush()
        course_id = course.id
        for item in objects:
            for fingerprint in (
                hashlib.sha256(representation_text(item).encode()).hexdigest(),
                "stale-revision",
            ):
                session.add(
                    SemanticVector(
                        course_id=course_id,
                        object_type="concept",
                        object_id=item["id"],
                        text_hash=fingerprint,
                        model="test-model",
                        dimensions=2,
                        vector=[1.0, 0.0],
                    )
                )
    # If the query loads an old revision, its JSON decoder will fail. This makes
    # selecting just active fingerprints observable, independently of timing.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE semantic_vectors SET vector = 'invalid-json' WHERE text_hash = ?",
            ("stale-revision",),
        )
    query_parameters = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT") and "semantic_vectors" in statement:
            query_parameters.append(len(parameters))

    def unexpected_call(*args):
        raise AssertionError("Unchanged targets must not call the embedding provider")

    recorder = PipelineMeasurements()
    result = ensure_vectors(
        sessions,
        course_id,
        objects,
        object_type="concept",
        model="test-model",
        dimensions=2,
        embed_call=unexpected_call,
        measurements=recorder,
    )
    assert len(result) == 510 and all(vector == [1.0, 0.0] for vector in result.values())
    assert len(query_parameters) == 3 and max(query_parameters) <= 504
    assert recorder.snapshot()["counts"]["semantic_vectors"]["cache_hits"] == 510
    assert recorder.snapshot()["counts"]["semantic_vectors"]["cache_misses"] == 0

    changed = {**objects[0], "title": "Corrected assumption"}
    calls = []

    def embed(texts, key):
        calls.append(texts)
        return SimpleNamespace(vectors=[[0.0, 1.0] for _ in texts])

    updated = ensure_vectors(
        sessions,
        course_id,
        [changed],
        object_type="concept",
        model="test-model",
        dimensions=2,
        embed_call=embed,
    )
    assert updated[changed["id"]] == [0.0, 1.0] and len(calls) == 1
    restored = ensure_vectors(
        sessions,
        course_id,
        [objects[0]],
        object_type="concept",
        model="test-model",
        dimensions=2,
        embed_call=unexpected_call,
    )
    assert restored[objects[0]["id"]] == [1.0, 0.0]
    with sessions() as session:
        assert len(list(session.scalars(select(SemanticVector.id)))) == 1021
    engine.dispose()
