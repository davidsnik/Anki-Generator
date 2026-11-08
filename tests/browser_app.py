"""Explicit test-only browser host. Never imported by the production launcher.

Run: uv run uvicorn tests.browser_app:create_browser_app --factory --port 8766
"""

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from anki_generator.api.app import create_app
from tests.support.controlled_provider import ControlledProvider


def create_browser_app() -> FastAPI:
    directory = Path(
        os.environ.get("ANKI_TEST_DATA_DIR") or tempfile.mkdtemp(prefix="anki-browser-")
    )
    provider = ControlledProvider()
    app = create_app(directory, provider_factory=lambda key, config: provider)
    app.state.runtime.secrets._keyring = None
    # Replace only test-host network diagnostics; no mock path exists in production.
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/settings/test", "/api/settings/models"}
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
    def controlled_models() -> dict[str, Any]:
        return {"models": [{"id": "gpt-6-astra"}], "recommendation": "gpt-6-astra"}

    def test_route_priority(route: Any) -> int:
        path = getattr(route, "path", "")
        if path in {"/api/settings/test", "/api/settings/models"}:
            return 0
        return 2 if path == "/{path:path}" else 1

    app.router.routes.sort(key=test_route_priority)
    return app
