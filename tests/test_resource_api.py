"""HTTP settings and rendering share the runner's real resource manager."""

import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image
from test_global_resources import wait_for

from anki_generator.llm.provider import OpenAIProvider
from anki_generator.services.task_options import TaskOptions


def test_saved_limits_reconfigure_pending_requests_without_recreating_manager(api_client):
    rt = api_client.app.state.runtime
    resources = rt.runner.resources
    resources.configure(TaskOptions(api_concurrency=1))
    with ThreadPoolExecutor(max_workers=1) as worker:
        with resources.api("existing", "model"):
            future = worker.submit(lambda: acquire_once(resources))
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            saved = api_client.patch(
                "/api/settings", json={"tasks": {"api_concurrency": 2, "local_concurrency": 1}}
            )
            assert saved.status_code == 200, saved.text
            assert future.result(timeout=3)
        assert rt.runner.resources is resources
    assert resources.snapshot()["api_concurrency"] == 2
    assert resources.snapshot()["local_concurrency"] == 1
    assert api_client.get("/api/settings").json()["tasks"]["api_concurrency"] == 2
    for invalid in [
        {"api_concurrency": 0},
        {"per_model_concurrency": {"model": True}},
        {"unsupported_resource": 4},
    ]:
        assert api_client.patch("/api/settings", json={"tasks": invalid}).status_code == 400
    assert resources.snapshot()["api_concurrency"] == 2


def acquire_once(resources):
    with resources.api("pending", "model"):
        return True


@pytest.mark.parametrize("endpoint", ["test", "models"])
def test_connection_and_model_endpoints_use_shared_request_capacity(
    api_client, monkeypatch, endpoint
):
    rt = api_client.app.state.runtime
    rt.secrets.set("synthetic-never-sent-to-a-provider")
    resources = rt.runner.resources
    resources.configure(TaskOptions(api_concurrency=1))
    calls = []

    def parse(**kwargs):
        calls.append("test")
        return SimpleNamespace(
            status="completed",
            output=[],
            usage=None,
            id="controlled",
            model=kwargs["model"],
            output_parsed=kwargs["text_format"](connected=True),
        )

    def models():
        calls.append("models")
        return [SimpleNamespace(id="controlled-model")]

    def factory(key, **context):
        assert context["resources"] is resources
        return OpenAIProvider(
            key,
            client=SimpleNamespace(
                responses=SimpleNamespace(parse=parse), models=SimpleNamespace(list=models)
            ),
            **context,
        )

    monkeypatch.setattr("anki_generator.api.settings.OpenAIProvider", factory)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with resources.api("course-job", "model"):
            method = api_client.post if endpoint == "test" else api_client.get
            future = worker.submit(method, f"/api/settings/{endpoint}")
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            assert calls == []
            assert api_client.get("/api/health").status_code == 200
        response = future.result(timeout=4)
    assert response.status_code == 200, response.text
    assert calls == [endpoint]
    assert resources.snapshot()["api_active"] == 0


def test_selected_crop_waits_for_local_budget_while_api_remains_responsive(api_client, course):
    rt = api_client.app.state.runtime
    image = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(image, format="PNG")
    uploaded = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("diagram.png", image.getvalue(), "image/png"))],
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["documents"][0]
    submitted = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
    assert submitted.status_code == 202, submitted.text
    rt.runner.run_now(submitted.json()["id"])
    rt.runner.resources.configure(TaskOptions(local_concurrency=1))
    with ThreadPoolExecutor(max_workers=1) as worker:
        with rt.runner.resources.local("other-course-parser"):
            future = worker.submit(
                api_client.post,
                f"/api/documents/{document['id']}/regions",
                json={"page_number": 1, "bbox": [1, 1, 20, 20], "dpi": 144, "label": "Evidence"},
            )
            wait_for(lambda: rt.runner.resources.snapshot()["local_waiting"] == 1)
            assert api_client.get("/api/health").status_code == 200
        response = future.result(timeout=15)
    assert response.status_code == 201, response.text
    region = response.json()
    preview = api_client.get(region["image_url"])
    assert preview.status_code == 200
    with Image.open(io.BytesIO(preview.content)) as cropped:
        assert cropped.size == (19, 19)
    assert rt.runner.resources.snapshot()["local_active"] == 0


def test_zip_preparation_runs_off_event_loop_and_keeps_task_polling_responsive(
    api_client, course, monkeypatch
):
    from anki_generator.api import documents

    entered = threading.Event()
    release = threading.Event()
    original_unpack = documents.unpack_zip

    def blocked_unpack(content):
        entered.set()
        assert release.wait(timeout=10)
        return original_unpack(content)

    monkeypatch.setattr(documents, "unpack_zip", blocked_unpack)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("chapter.txt", "Synthetic independent upload")

    def poll():
        return (
            api_client.get("/api/health").status_code,
            api_client.get("/api/tasks/summary").status_code,
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        upload = workers.submit(
            api_client.post,
            f"/api/courses/{course['id']}/documents",
            files=[("files", ("sources.zip", archive.getvalue(), "application/zip"))],
        )
        try:
            assert entered.wait(timeout=3)
            # Both requests must finish while ZIP preparation is deliberately
            # blocked. A blocked ASGI event loop cannot satisfy this handshake.
            assert workers.submit(poll).result(timeout=3) == (200, 200)
            assert not upload.done()
        finally:
            release.set()
        response = upload.result(timeout=4)
    assert response.status_code == 201, response.text
    assert response.json()["documents"][0]["filename"] == "chapter.txt"


def test_source_hash_and_storage_do_not_hold_sqlite_writer_during_upload(
    api_client, course, monkeypatch
):
    from anki_generator.api import documents

    entered = threading.Event()
    release = threading.Event()
    original_store = documents.store_bytes

    def blocked_store(*args):
        entered.set()
        assert release.wait(timeout=10)
        return original_store(*args)

    monkeypatch.setattr(documents, "store_bytes", blocked_store)
    with ThreadPoolExecutor(max_workers=2) as workers:
        upload = workers.submit(
            api_client.post,
            f"/api/courses/{course['id']}/documents",
            files=[("files", ("chapter.txt", b"Synthetic independent source", "text/plain"))],
        )
        try:
            assert entered.wait(timeout=3)
            other_write = workers.submit(
                api_client.post, "/api/courses", json={"name": "Independent course"}
            )
            assert other_write.result(timeout=3).status_code == 201
            assert not upload.done()
        finally:
            release.set()
        response = upload.result(timeout=4)
    assert response.status_code == 201, response.text


def test_cleanup_winning_before_import_commit_never_creates_missing_source_reference(
    api_client, course, monkeypatch
):
    from anki_generator.api import documents
    from anki_generator.services.cleanup import remove_unreferenced_blob

    rt = api_client.app.state.runtime
    stored = threading.Event()
    release = threading.Event()
    paths = []
    original_store = documents.store_bytes
    content = b"Synthetic upload racing deletion of an unreferenced shared blob"

    def prepared_then_wait(*args):
        result = original_store(*args)
        paths.append(result[0])
        stored.set()
        assert release.wait(timeout=10)
        return result

    monkeypatch.setattr(documents, "store_bytes", prepared_then_wait)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(
            api_client.post,
            f"/api/courses/{course['id']}/documents",
            files=[("files", ("chapter.txt", content, "text/plain"))],
        )
        try:
            assert stored.wait(timeout=3)
            remove_unreferenced_blob(rt.sessions, rt.data_root, paths[0])
            assert not (rt.data_root / paths[0]).exists()
        finally:
            release.set()
        response = pending.result(timeout=4)
    assert response.status_code == 400 and "retry" in response.text.lower()
    assert api_client.get(f"/api/courses/{course['id']}/documents").json() == []
    monkeypatch.setattr(documents, "store_bytes", original_store)
    retried = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("chapter.txt", content, "text/plain"))],
    )
    assert retried.status_code == 201, retried.text
    document = retried.json()["documents"][0]
    assert api_client.get(f"/api/documents/{document['id']}/source").content == content


@pytest.mark.parametrize("endpoint", ["test", "models"])
def test_settings_closes_internally_created_sdk_clients(api_client, monkeypatch, endpoint):
    rt = api_client.app.state.runtime
    rt.secrets.set("synthetic-never-sent")
    closed = []

    def parse(**kwargs):
        return SimpleNamespace(
            status="completed",
            output=[],
            usage=None,
            id="controlled",
            model=kwargs["model"],
            output_parsed=kwargs["text_format"](connected=True),
        )

    monkeypatch.setattr(
        "openai.OpenAI",
        lambda **kwargs: SimpleNamespace(
            responses=SimpleNamespace(parse=parse),
            models=SimpleNamespace(list=lambda: [SimpleNamespace(id="controlled")]),
            close=lambda: closed.append(True),
        ),
    )
    method = api_client.post if endpoint == "test" else api_client.get
    response = method(f"/api/settings/{endpoint}")
    assert response.status_code == 200, response.text
    assert closed == [True]
