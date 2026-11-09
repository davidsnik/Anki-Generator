"""Explicit test-only browser host. Never imported by the production launcher.

Run: uv run uvicorn tests.browser_app:create_browser_app --factory --port 8766
"""

import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import insert, select

from anki_generator.api.app import create_app
from anki_generator.database.entities import Card, Course, Document, Page, Revision, new_id
from anki_generator.services.records import require
from anki_generator.services.settings import ApplicationSettings, get_settings
from tests.support.controlled_provider import ControlledProvider


class ScaleInput(BaseModel):
    course_id: str
    count: int = Field(default=1500, ge=1, le=5000)


class GateInput(BaseModel):
    course_ids: list[str] = Field(min_length=1, max_length=8)


class BrowserGates:
    """Test-only provider barriers prove scheduler overlap without timing guesses."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.gates: dict[str, threading.Event] = {}
        self.entered: dict[str, str] = {}
        self.waiting: set[str] = set()

    def configure(self, courses: list[str]) -> None:
        with self.lock:
            if self.waiting:
                raise HTTPException(409, "Release existing browser gates first")
            self.gates = {course: threading.Event() for course in courses}
            self.entered = {}

    def wait(self, course_id: str) -> None:
        with self.lock:
            gate = self.gates.get(course_id)
            if gate is None or gate.is_set():
                return
            self.entered[course_id] = datetime.now(UTC).isoformat()
            self.waiting.add(course_id)
        try:
            if not gate.wait(timeout=180):
                from anki_generator.llm import ProviderError

                raise ProviderError("Browser test gate timed out", kind="network", retryable=False)
        finally:
            with self.lock:
                self.waiting.discard(course_id)

    def release(self, course_id: str) -> None:
        with self.lock:
            gate = self.gates.get(course_id)
            if gate is None:
                raise HTTPException(404, "Browser gate not found")
            gate.set()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "entered": dict(self.entered),
                "waiting": sorted(self.waiting),
                "released": [course for course, gate in self.gates.items() if gate.is_set()],
                "provider": "controlled synthetic provider; no external requests",
            }


def create_browser_app() -> FastAPI:
    directory = Path(
        os.environ.get("ANKI_TEST_DATA_DIR") or tempfile.mkdtemp(prefix="anki-browser-")
    )
    provider = ControlledProvider()
    app = create_app(directory, provider_factory=lambda key, config: provider)
    gates = BrowserGates()

    def gated_call(stage: str, payload: dict[str, Any]) -> None:
        if stage != "knowledge" or not payload.get("document_id"):
            return
        # Read and close the transaction before waiting at the provider boundary.
        with app.state.runtime.sessions() as session:
            document = session.get(Document, payload["document_id"])
            course_id = document.course_id if document else None
        if course_id:
            gates.wait(course_id)

    provider.on_call = gated_call
    app.state.runtime.secrets._keyring = None
    # Replace only test-host network diagnostics; no mock path exists in production.
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", "")
        not in {"/api/settings/test", "/api/settings/models", "/api/settings/models/validate"}
    ]

    @app.post("/api/settings/test")
    def controlled_connection_test() -> dict[str, Any]:
        if not app.state.runtime.secrets.get():
            raise ValueError("Configure the test API key first")
        return {
            "ok": True,
            "connected": True,
            "model": "gpt-6-astra",
            "message": "Controlled test provider connection (no external requests).",
        }

    @app.get("/api/settings/models")
    def controlled_models(refresh: bool = False) -> dict[str, Any]:
        rt = app.state.runtime
        saved = get_settings(rt.sessions)
        return rt.model_discovery.catalogue(
            rt.secrets.get(),
            MetadataProvider,
            refresh=refresh,
            selected=[*saved.models.model_dump().values(), saved.processing.embedding_model],
        )

    class MetadataProvider:
        def models(self) -> list[str]:
            if app.state.runtime.secrets.get() == "sk-invalid-test":
                from anki_generator.llm import ProviderError

                raise ProviderError(
                    "The API key was rejected. Replace it in Settings.", kind="authentication"
                )
            return [
                "gpt-6-astra",
                "gpt-6.1-sol",
                "gpt-6-luna",
                "text-embedding-3-small",
                "text-embedding-3-large",
                "custom-visible-test",
            ]

        def retrieve_model(self, identifier: str) -> str:
            from anki_generator.llm import ProviderError

            if identifier in self.models():
                return identifier
            raise ProviderError(
                "This model is unavailable to the test account.", kind="configuration"
            )

        def close_owned_client(self) -> None:
            pass

    @app.post("/api/settings/models/validate")
    def controlled_model_validation(changes: dict[str, Any]) -> dict[str, Any]:
        rt = app.state.runtime
        current = get_settings(rt.sessions).model_dump()
        for name, value in changes.items():
            current[name] = {**current[name], **value} if isinstance(value, dict) else value
        return rt.model_discovery.validate(
            ApplicationSettings.model_validate(current), rt.secrets.get(), MetadataProvider
        )

    @app.post("/api/test/concurrency")
    def configure_gates(values: GateInput) -> dict[str, Any]:
        with app.state.runtime.sessions() as session:
            for course_id in values.course_ids:
                require(session, Course, course_id)
        gates.configure(values.course_ids)
        return gates.snapshot()

    @app.get("/api/test/concurrency")
    def gate_state() -> dict[str, Any]:
        return gates.snapshot()

    @app.post("/api/test/concurrency/{course_id}/release")
    def release_gate(course_id: str) -> dict[str, Any]:
        gates.release(course_id)
        return gates.snapshot()

    @app.post("/api/test/seed-cards")
    def seed_cards(values: ScaleInput, request: Request) -> dict[str, Any]:
        """Synthetic pagination fixture; this route exists only in the test host."""
        with app.state.runtime.sessions.begin() as session:
            require(session, Course, values.course_id)
            document = session.scalar(
                select(Document).where(Document.course_id == values.course_id)
            )
            page = (
                session.scalar(select(Page).where(Page.document_id == document.id))
                if document
                else None
            )
            sources = (
                [
                    {
                        "document_id": document.id,
                        "page_number": page.page_number,
                        "quote": "For a right triangle, a^2 + b^2 = c^2.",
                    }
                ]
                if document and page
                else []
            )
            rows = [
                {
                    "id": new_id(),
                    "course_id": values.course_id,
                    "question": (
                        f"Synthetic pagination fixture {i:04d}: "
                        "which right-angle assumption is required?"
                    ),
                    "answer": "The triangle must have a right angle.",
                    "sources": sources,
                    "tags": ["synthetic", "pagination"],
                    "manually_edited": True,
                }
                for i in range(values.count)
            ]
            session.execute(insert(Card), rows)
            session.execute(
                insert(Revision),
                [
                    {
                        "card_id": row["id"],
                        "revision_number": 1,
                        "snapshot": {
                            "question": row["question"],
                            "answer": row["answer"],
                            "sources": sources,
                            "tags": row["tags"],
                            "explanation": "",
                        },
                        "origin": "synthetic_test",
                    }
                    for row in rows
                ],
            )
            return {"count": len(rows), "card_ids": [row["id"] for row in rows]}

    def test_route_priority(route: Any) -> int:
        path = getattr(route, "path", "")
        if path in {
            "/api/settings/test",
            "/api/settings/models",
            "/api/settings/models/validate",
        } or path.startswith("/api/test/"):
            return 0
        return 2 if path == "/{path:path}" else 1

    app.router.routes.sort(key=test_route_priority)
    return app
