"""Isolated API clients never use actual user credentials or a background worker."""

from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from fastapi.testclient import TestClient

from anki_generator.api.app import create_app


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def unavailable_keyring():
        raise RuntimeError("Tests use an isolated session-only credential store")

    monkeypatch.setattr(keyring, "get_keyring", unavailable_keyring)
    app = create_app(tmp_path / "application", start_worker=False)
    with TestClient(app) as client:
        bootstrap = client.get("/api/bootstrap")
        assert bootstrap.status_code == 200
        client.headers["X-CSRF-Token"] = bootstrap.json()["csrf_token"]
        yield client


@pytest.fixture
def course(api_client: TestClient) -> dict:
    response = api_client.post(
        "/api/courses", json={"name": "Analysis", "deck_name": "University::Analysis"}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def source_document(api_client: TestClient, course: dict) -> dict:
    content = b"For all x, f(x) = x squared. The function is continuous on the real line.\n"
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("lecture.txt", content, "text/plain"))],
        data={"category": "lecture", "authority": "official"},
    )
    assert response.status_code == 201, response.text
    return response.json()["documents"][0]


@pytest.fixture
def extracted_source(api_client: TestClient, course: dict, source_document: dict) -> dict:
    response = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
    assert response.status_code == 202, response.text
    api_client.app.state.runtime.runner.run_now(response.json()["id"])
    completed = api_client.get(f"/api/runs/{response.json()['id']}").json()
    assert completed["status"] == "completed", completed.get("error")
    pages = api_client.get(f"/api/documents/{source_document['id']}/pages").json()
    return {"document": source_document, "pages": pages, "run": completed}
