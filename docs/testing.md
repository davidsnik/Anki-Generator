# Testing and verification

## Offline checks

    uv sync --locked
    uv run --locked pytest
    uv run --locked ruff check .
    uv run --locked ruff format --check .
    pnpm --dir frontend install --frozen-lockfile
    pnpm --dir frontend run build
    pnpm --dir frontend test
    pnpm --dir frontend run format:check

Python tests cover original discovery/schema safety, genuine PDF/image/Office
extraction, long-page tiles and subprocess budgets, persistence, provider failure/
retry/refusal handling, evidence/mathematical checks, durable jobs and complete HTTP
course-to-Anki behavior. APKG tests inspect real ZIP/SQLite/media/templates/IDs.
Frontend unit tests cover mathematical/cloze rendering, configuration and controls.

The deterministic provider is under tests/support. Production has no fake-provider
selection or fallback. Tests explicitly inject it through the application factory.
No valid API key or paid call is required.

## Browser workflow

Install the official Playwright Chromium browser once:

    pnpm --dir frontend exec playwright install chromium

In one terminal, start the explicitly controlled test server:

    uv run uvicorn tests.browser_app:create_browser_app --factory --host 127.0.0.1 --port 8766

In a second terminal:

    pnpm --dir frontend test:e2e

The test host uses temporary SQLite/storage and controlled diagnostics/generation;
it is separate from the production launcher. Browser tests create courses, assign
roles, upload sources, extract, configure a test key, confirm processing, browse/
edit/review source-linked mathematics and export. Responsive/theme checks are separate.
The default base URL is http://127.0.0.1:8766; ANKI_E2E_BASE_URL overrides it.
PLAYWRIGHT_BROWSERS_PATH can select a custom browser installation location.

A successful TypeScript/build check does not establish visual quality. Inspect
desktop/mobile light/dark screenshots, source previews, long dialogs and mathematics.
Tests save failure artifacts under ignored frontend/test-results/.

## Live validation and environmental limits

Live-provider evaluation is opt-in with a legitimately configured key. It may cost
money and transmit the explicitly selected course evidence. Offline test success
never implies live accuracy. Likewise, structural APKG validation does not establish
a real Anki version's import/update scheduling behavior.

Some restricted execution environments block TestClient/thread/event-loop or
browser loopback sockets even for a minimal unrelated FastAPI app. Run such checks
where local sockets are permitted; do not weaken tests or report them as passed
when blocked. A harmless Starlette/httpx deprecation warning may appear with the
currently locked test-client combination.

GitHub Actions runs Python checks, frontend build/unit/format checks, fixture
discovery and the controlled browser workflow. Remote CI execution requires a push;
local execution is reported separately.
