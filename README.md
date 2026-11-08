# Anki Generator

A local course-material workspace for building evidence-backed university Anki
decks. Import sources, map the course, generate and independently check cards,
review original evidence, and export a real .apkg.

The Python/FastAPI backend owns documents, credentials, SQLite state and a durable
worker. The React interface runs in your browser. Import and local extraction
send nothing to a provider. Analysis requires your OpenAI key and a confirmation
describing which text and rendered regions leave the machine.

## Install and launch

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/),
Node.js 24 LTS (or 22.13+) and pnpm. uv manages Python 3.12;
the frontend pins its package manager.

    ./install.sh
    ./run.sh

Installation uses committed Python and frontend lockfiles and builds the interface.
run.sh starts the backend/worker at http://127.0.0.1:8765, serves the built frontend,
and opens your browser. After installation, Node and the internet are unnecessary
for local browsing, extraction, editing and export. OpenAI processing needs a
network connection and incurs API charges.

    ./run.sh --no-open-browser
    ./run.sh --port 8766
    ./run.sh --data-directory /path/to/private/workspace
    ./dev.sh

Development runs the backend on :8000 and Vite on :5173 with live reload. Default
data lives in data/app/ in this checkout. Stop the application before moving its
data directory. ANKI_GENERATOR_DATA_DIR is an optional launch override; regular
application settings are available in the GUI.

## Your first course

1. In onboarding or Settings, enter an OpenAI key and test the selected model.
   Session-only storage is always available; secure persistence is offered only
   when the OS credential store is usable. Keys never enter SQLite.
2. Create a course and choose its deck name, language and generation preferences.
3. Import files, a folder or ZIP. Assign Lecture, Personal notes, Exercises,
   Worked solutions or Reference roles, source authority, and question/solution links.
4. Run local extraction to inspect pages without external calls, or start analysis
   after confirming the OpenAI disclosure. Progress shows actual stages, counts,
   checkpoints, warnings, usage and pause/resume/cancel/retry controls.
5. Inspect concepts and coverage gaps. Browse and flip basic/cloze cards, inspect
   mathematics, images and sources, edit, regenerate and record review decisions.
   Edits retain history and invalidate prior checks.
6. Approve cards, then export Anki, JSON or CSV. Anki export requires human approval
   and blocks failed/duplicate candidates. A human can approve an otherwise
   unverified manual card with an explicit rationale; it remains unverified by models.

Independent checks are evidence, not proof. Review assumptions and uncertain
transcriptions. A revision limit never converts failure into approval.

## Documents, privacy and data

Supported imports: text/scanned/handwritten PDFs, PNG/JPEG, UTF-8 text, Markdown,
LaTeX, DOCX, PPTX and ZIP collections. Tall PDFs use overlapping bounded tiles with
original coordinates. Scans, mathematics and graphics receive visual analysis where
indicated. Unreadable or uncertain material stays visible.

DOCX/PPTX text and embedded raster images are extracted; synthetic previews do not
reproduce native Office layout. Complex equation objects, charts and unsupported
elements are flagged. Convert these to PDF for faithful visual analysis. See
[format support and limits](docs/ingestion.md).

Keep private inputs and user data under ignored data/. Synthetic fixtures are
safe to track. Never commit private sources or credentials. Settings backup exports
a consistent SQLite snapshot and local artifacts; treat the archive as private.
Stop the app before restoring its contents into a data directory. Provider keys
are excluded from backups.

The backend binds to loopback and validates hosts/origins and a CSRF token. It is
a personal local application, not an authenticated multi-user network service.
Imported content and generated HTML are untrusted. No Anki collection is modified
directly. Read [Anki export behavior](docs/anki-export.md) before importing updates.

## Develop and verify

    uv sync --locked
    uv run --locked pytest
    uv run --locked ruff check .
    uv run --locked ruff format --check .
    pnpm --dir frontend install --frozen-lockfile
    pnpm --dir frontend run build
    pnpm --dir frontend test
    pnpm --dir frontend test:e2e

Tests use temporary storage and an explicitly injected deterministic provider.
Production has no simulated generation fallback. Automated tests require no live
key or paid calls. Browser setup is described in [testing](docs/testing.md).
Executed checks, requirement coverage and validation limits are recorded in the
[verification report](docs/verification.md).
The original deterministic discovery command remains available:

    uv run anki-generator inspect fixtures/example-course --output outputs/example

Read [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md),
[data models](docs/data-model.md), [requirements](docs/requirements.md),
[card quality](docs/flashcard-guidelines.md), and [roadmap](docs/roadmap.md).
Templates are packaged in src/anki_generator/prompts/; see
[prompt policy](prompts/README.md). [Troubleshooting](docs/troubleshooting.md)
covers startup, provider, extraction and export failures.
