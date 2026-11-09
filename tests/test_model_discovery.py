"""Account model metadata, privacy, cache isolation and pre-spend validation."""

from types import SimpleNamespace

import pytest

from anki_generator.llm.provider import OpenAIProvider, ProviderError
from anki_generator.services.model_discovery import ModelDiscovery
from anki_generator.services.settings import ApplicationSettings

DEFAULTS = ["gpt-6-astra", "text-embedding-3-small"]


def install_sdk(monkeypatch, ids=None, error=None, accessible=()):
    calls = []

    def list_models():
        calls.append("list")
        if error:
            raise error
        return [SimpleNamespace(id=item) for item in (ids if ids is not None else DEFAULTS)]

    def retrieve(identifier):
        calls.append(("retrieve", identifier))
        if identifier not in accessible:
            raise SimpleStatusError(404)
        return SimpleNamespace(id=identifier)

    monkeypatch.setattr(
        "openai.OpenAI",
        lambda **kwargs: SimpleNamespace(
            models=SimpleNamespace(list=list_models, retrieve=retrieve),
            close=lambda: calls.append("close"),
        ),
    )
    return calls


class SimpleStatusError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__("private key and raw SDK detail must not appear")


def test_missing_key_shows_honest_catalogue_and_validation(api_client):
    response = api_client.get("/api/settings/models")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "missing_key"
    assert data["fetched_at"] is None
    assert all(item["available"] is None for item in data["models"])
    assert (
        next(item for item in data["models"] if item["id"] == "gpt-6-astra")["name"]
        == "GPT-6 Astra"
    )
    validation = api_client.post("/api/settings/models/validate", json={}).json()
    assert not validation["valid"]
    assert validation["issues"][0]["code"] == "missing_key"


def test_account_listing_cache_refresh_and_credential_change(api_client, monkeypatch):
    calls = install_sdk(monkeypatch, [*DEFAULTS, "custom-visible"])
    key = "synthetic-private-key-A"
    api_client.put("/api/settings/key", json={"api_key": key})
    first = api_client.get("/api/settings/models").json()
    assert first["status"] == "ready" and not first["cached"]
    unknown = next(item for item in first["models"] if item["id"] == "custom-visible")
    assert unknown["available"] and unknown["compatibility"]["generation"] == "unknown"
    assert unknown["documentation"] is None and unknown["capabilities"]["vision"] is None
    assert key not in str(first) and "private" not in str(first)
    assert api_client.get("/api/settings/models").json()["cached"]
    assert calls.count("list") == 1
    assert not api_client.get("/api/settings/models?refresh=true").json()["cached"]
    assert calls.count("list") == 2
    api_client.put("/api/settings/key", json={"api_key": "synthetic-private-key-B"})
    assert not api_client.get("/api/settings/models").json()["cached"]
    assert calls.count("list") == 3
    api_client.delete("/api/settings/key")
    assert api_client.get("/api/settings/models").json()["status"] == "missing_key"


@pytest.mark.parametrize(
    "status,kind",
    [(401, "authentication"), (403, "permission"), (429, "rate_limit"), (503, "unavailable")],
)
def test_discovery_failure_is_friendly_sanitized_and_refreshable(
    api_client, monkeypatch, status, kind
):
    calls = install_sdk(monkeypatch, error=SimpleStatusError(status))
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    data = api_client.get("/api/settings/models").json()
    assert data["status"] == "error" and data["error"]["kind"] == kind
    assert data["fetched_at"] is None
    assert all(item["available"] is None for item in data["models"])
    assert "raw SDK" not in str(data) and "synthetic-test-key" not in str(data)
    assert calls == ["list", "close"]  # No long automatic retry loop.
    install_sdk(monkeypatch)
    assert api_client.get("/api/settings/models?refresh=true").json()["status"] == "ready"


def test_cache_expiry_and_failed_refresh_cannot_reuse_stale_success():
    now = [1000.0]
    discovery = ModelDiscovery(ttl=60, clock=lambda: now[0])
    calls = []

    def factory():
        return SimpleNamespace(
            models=lambda: calls.append(True) or DEFAULTS, close_owned_client=lambda: None
        )

    assert not discovery.catalogue("key", factory)["cached"]
    now[0] += 59
    assert discovery.catalogue("key", factory)["cached"]
    now[0] += 2
    assert not discovery.catalogue("key", factory)["cached"]
    assert len(calls) == 2

    def failure():
        raise ProviderError("Invalid key", kind="authentication")

    assert discovery.catalogue("key", failure, refresh=True)["status"] == "error"
    assert not discovery.catalogue("key", factory)["cached"]


def test_validation_known_incompatible_unavailable_and_custom_visibility(api_client, monkeypatch):
    calls = install_sdk(monkeypatch, accessible=("ft:advanced-custom",))
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    report = api_client.post("/api/settings/models/validate", json={}).json()
    assert report["valid"] and report["issues"] == []
    incompatible = api_client.post(
        "/api/settings/models/validate", json={"models": {"generation": "text-embedding-3-small"}}
    ).json()
    assert not incompatible["valid"]
    assert any(item["code"] == "incompatible" for item in incompatible["issues"])
    unavailable = api_client.post(
        "/api/settings/models/validate", json={"models": {"factual": "gpt-6.1-sol"}}
    ).json()
    assert not unavailable["valid"] and unavailable["issues"][0]["code"] == "unavailable"
    custom = api_client.post(
        "/api/settings/models/validate", json={"models": {"generation": "ft:advanced-custom"}}
    ).json()
    assert custom["valid"] and custom["issues"][0]["code"] == "unverified_capabilities"
    assert ("retrieve", "ft:advanced-custom") in calls
    missing = api_client.post(
        "/api/settings/models/validate", json={"models": {"generation": "custom-not-accessible"}}
    ).json()
    assert not missing["valid"] and missing["issues"][0]["code"] == "unavailable"


def test_model_preflight_blocks_before_job_creation_but_local_extraction_works(
    api_client, course, source_document, monkeypatch
):
    calls = install_sdk(monkeypatch, ["text-embedding-3-small"])
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    route = f"/api/courses/{course['id']}/runs"
    response = api_client.post(route, json={"mode": "generate", "consent": True})
    assert response.status_code == 400 and "unavailable" in response.text
    assert api_client.get(route).json() == []
    assert calls == ["list", "close"]
    response = api_client.post(route, json={"mode": "extract"})
    assert response.status_code == 202
    assert calls == ["list", "close"]


@pytest.mark.parametrize("failure", ["authentication", "incompatible", "embedding_access"])
def test_failed_preflight_never_creates_a_run(
    api_client, course, source_document, monkeypatch, failure
):
    calls = install_sdk(
        monkeypatch,
        ["gpt-6-astra"] if failure == "embedding_access" else DEFAULTS,
        error=SimpleStatusError(401) if failure == "authentication" else None,
    )
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    if failure == "incompatible":
        assert (
            api_client.patch(
                "/api/settings", json={"models": {"generation": "text-embedding-3-small"}}
            ).status_code
            == 200
        )
    route = f"/api/courses/{course['id']}/runs"
    response = api_client.post(route, json={"mode": "generate", "consent": True})
    assert response.status_code == 400
    assert api_client.get(route).json() == []
    assert calls == ["list", "close"]
    if failure == "authentication":
        assert "invalid or expired" in response.text
    elif failure == "incompatible":
        assert "cannot perform generation" in response.text
    else:
        assert "text-embedding-3-small is unavailable" in response.text


def test_missing_documents_do_not_make_an_account_request(api_client, course, monkeypatch):
    calls = install_sdk(monkeypatch)
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    response = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "generate", "consent": True}
    )
    assert response.status_code == 400 and "Import course documents" in response.text
    assert calls == []


def test_model_metadata_lookup_holds_no_sqlite_writer(
    api_client, course, source_document, monkeypatch
):
    from sqlalchemy import select

    from anki_generator.database.entities import Run

    rt = api_client.app.state.runtime
    observed = []

    def models():
        # A separate connection can take the physical writer while metadata is
        # being fetched. No job or source snapshot exists before this finishes.
        with rt.sessions.kw["bind"].connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            assert connection.execute(select(Run.id)).first() is None
            connection.rollback()
        observed.append(True)
        return DEFAULTS

    monkeypatch.setattr(
        "anki_generator.services.model_discovery.provider_for_discovery",
        lambda *_: SimpleNamespace(models=models, close_owned_client=lambda: None),
    )
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    submitted = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "generate", "consent": True}
    )
    assert submitted.status_code == 202, submitted.text
    assert observed == [True]


def test_resume_checks_frozen_configuration_before_requeuing(
    api_client, course, source_document, monkeypatch
):
    from anki_generator.database.entities import Run

    calls = install_sdk(monkeypatch)
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    route = f"/api/courses/{course['id']}/runs"
    submitted = api_client.post(route, json={"mode": "generate", "consent": True})
    assert submitted.status_code == 202
    identifier = submitted.json()["id"]
    rt = api_client.app.state.runtime
    with rt.sessions.begin() as session:
        run = session.get(Run, identifier)
        run.status = "paused"
        run.config = {**run.config, "models": {**run.config["models"], "generation": "gpt-6.1-sol"}}
    resumed = api_client.post(f"/api/runs/{identifier}/resume")
    assert resumed.status_code == 400 and "unavailable" in resumed.text
    assert api_client.get(f"/api/runs/{identifier}").json()["status"] == "paused"
    assert calls == ["list", "close"]  # Metadata cache reused, no generation calls.


def test_model_selection_persists_offline_without_replacing_custom_ids(api_client):
    response = api_client.patch(
        "/api/settings", json={"models": {"generation": "account-future-model"}}
    )
    assert response.status_code == 200
    data = api_client.get("/api/settings/models").json()
    custom = next(item for item in data["models"] if item["id"] == "account-future-model")
    assert custom["available"] is None and custom["compatibility"]["generation"] == "unknown"
    assert api_client.get("/api/settings").json()["models"]["generation"] == "account-future-model"


def test_unlisted_custom_model_is_unconfirmed_until_retrieved(api_client, monkeypatch):
    calls = install_sdk(monkeypatch, accessible=("ft:advanced-custom",))
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    api_client.patch("/api/settings", json={"models": {"generation": "ft:advanced-custom"}})
    catalogue = api_client.get("/api/settings/models").json()
    custom = next(item for item in catalogue["models"] if item["id"] == "ft:advanced-custom")
    known_missing = next(item for item in catalogue["models"] if item["id"] == "gpt-6.1-sol")
    assert custom["available"] is None
    assert known_missing["available"] is False
    report = api_client.post("/api/settings/models/validate", json={}).json()
    assert report["valid"] and report["issues"][0]["code"] == "unverified_capabilities"
    assert ("retrieve", "ft:advanced-custom") in calls


def test_unknown_embedding_capability_warning_describes_embedding_requirements():
    settings = ApplicationSettings(processing={"embedding_model": "future-embedding"})
    discovery = ModelDiscovery()

    def provider():
        return SimpleNamespace(
            models=lambda: [*DEFAULTS, "future-embedding"], close_owned_client=lambda: None
        )

    report = discovery.validate(settings, "synthetic", provider)
    assert report["valid"]
    warning = next(item for item in report["issues"] if item["stage"] == "embeddings")
    assert "Embeddings endpoint" in warning["message"] and "dimensions" in warning["message"]
    assert "Responses" not in warning["message"] and "source-image" not in warning["message"]


@pytest.mark.parametrize("listed", [True, False])
def test_custom_embedding_settings_persist_and_preflight_account_visibility(
    api_client, course, source_document, monkeypatch, listed
):
    identifier = "account-custom-embedding"
    calls = install_sdk(
        monkeypatch,
        [*DEFAULTS, identifier] if listed else DEFAULTS,
        accessible=(identifier,),
    )
    api_client.put("/api/settings/key", json={"api_key": "synthetic-test-key"})
    saved = api_client.patch(
        "/api/settings",
        json={
            "processing": {
                "embedding_model": identifier,
                "embedding_dimensions": 128,
            }
        },
    )
    assert saved.status_code == 200, saved.text
    assert api_client.get("/api/settings").json()["processing"]["embedding_model"] == identifier
    catalogue = api_client.get("/api/settings/models").json()
    custom = next(item for item in catalogue["models"] if item["id"] == identifier)
    assert custom["available"] is (True if listed else None)
    assert custom["compatibility"]["embeddings"] == "unknown"
    validated = api_client.post("/api/settings/models/validate", json={}).json()
    assert validated["valid"]
    assert validated["issues"][0]["stage"] == "embeddings"
    assert validated["issues"][0]["code"] == "unverified_capabilities"
    if not listed:
        assert ("retrieve", identifier) in calls
    submitted = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "generate", "consent": True}
    )
    assert submitted.status_code == 202, submitted.text
    from anki_generator.database.entities import Run

    with api_client.app.state.runtime.sessions() as session:
        frozen = session.get(Run, submitted.json()["id"]).config["processing"]
        assert frozen["embedding_model"] == identifier and frozen["embedding_dimensions"] == 128


@pytest.mark.parametrize(
    "identifier", ["", "bad model", "model\x00name", "model\x7fname", "x" * 201]
)
def test_custom_embedding_identifiers_reject_unsafe_or_unbounded_values(api_client, identifier):
    assert (
        api_client.patch(
            "/api/settings", json={"processing": {"embedding_model": identifier}}
        ).status_code
        == 400
    )


def test_known_embedding_dimension_guard_remains_enforced(api_client):
    assert (
        api_client.patch(
            "/api/settings",
            json={
                "processing": {
                    "embedding_model": "text-embedding-3-small",
                    "embedding_dimensions": 1537,
                }
            },
        ).status_code
        == 400
    )


@pytest.mark.parametrize("returned_dimensions", [128, 64])
def test_custom_embedding_transport_passes_exact_model_and_checks_vector_dimensions(
    returned_dimensions,
):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            data=[SimpleNamespace(index=0, embedding=[1.0] * returned_dimensions)],
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 2, "total_tokens": 2}),
        )

    provider = OpenAIProvider(
        "synthetic", client=SimpleNamespace(embeddings=SimpleNamespace(create=create))
    )
    if returned_dimensions == 128:
        result = provider.embed(
            ["A synthetic learning target"], model="custom-embedding", dimensions=128
        )
        assert result.model == "custom-embedding" and len(result.vectors[0]) == 128
    else:
        with pytest.raises(ProviderError, match="invalid embedding batch"):
            provider.embed(
                ["A synthetic learning target"], model="custom-embedding", dimensions=128
            )
    assert requests == [
        {
            "model": "custom-embedding",
            "input": ["A synthetic learning target"],
            "dimensions": 128,
            "encoding_format": "float",
        }
    ]


@pytest.mark.parametrize("connected", [False, True])
def test_connection_feedback_matches_actual_result(api_client, monkeypatch, connected):
    monkeypatch.setattr(
        "anki_generator.api.settings.OpenAIProvider",
        lambda *_args, **_kwargs: SimpleNamespace(
            test=lambda _model: {"connected": connected}, close_owned_client=lambda: None
        ),
    )
    response = api_client.post("/api/settings/test")
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is connected
    if connected:
        assert "verified" in result["message"]
    else:
        assert "did not confirm" in result["message"] and "retry" in result["message"]
        assert "verified" not in result["message"]


def test_interpret_preflight_ignores_models_unused_by_that_mode():
    discovery = ModelDiscovery()

    def provider():
        return SimpleNamespace(models=lambda: ["gpt-6-astra"], close_owned_client=lambda: None)

    settings = ApplicationSettings(models={"generation": "unavailable"})
    assert discovery.validate(settings, "key", provider, mode="interpret")["valid"]


def test_known_nonreasoning_model_omits_reasoning_and_embeddings_rejected_before_request():
    from pydantic import BaseModel

    class Result(BaseModel):
        answer: str

    calls = []
    provider = OpenAIProvider(
        "synthetic",
        client=SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **kwargs: (
                    calls.append(kwargs)
                    or SimpleNamespace(
                        output_parsed=Result(answer="yes"),
                        output=[],
                        status="completed",
                        usage=None,
                    )
                )
            )
        ),
    )
    provider.structured("factual", {}, Result, model="gpt-4.1")
    assert "reasoning" not in calls[0]
    with pytest.raises(ProviderError, match="structured card processing"):
        provider.structured("factual", {}, Result, model="text-embedding-3-small")
    assert len(calls) == 1
