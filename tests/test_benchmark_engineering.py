"""Reproducible synthetic controls remain distinct from course-quality evidence."""

import pytest

from anki_generator.benchmark.engineering import (
    mathematical_domain_profile,
    semantic_cache_profiles,
)


def test_domain_controls_and_cache_trials_report_real_observations_without_api():
    mathematics = mathematical_domain_profile()
    assert mathematics["matching_decisions"] == mathematics["denominator"] == 3
    assert mathematics["reference_origin"] == "deterministic_authored_domain_control"
    profiles = semantic_cache_profiles(objects_count=3, dimensions=2, repetitions=2)
    assert len(profiles) == 2
    for row in profiles:
        assert row["decoded_rows_mean"] == 3
        assert row["wall_seconds_mean"] >= 0
        assert all(trial["returned_vectors"] == 3 for trial in row["trials"])
        assert all(trial["embedding_calls"] == 0 for trial in row["trials"])


@pytest.mark.parametrize(
    "values",
    [{"objects_count": 0}, {"dimensions": 10000}, {"repetitions": 100}],
)
def test_engineering_profiles_have_bounded_configuration(values):
    with pytest.raises(ValueError, match="bounded"):
        semantic_cache_profiles(**values)
