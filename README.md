# Anki Generator

A local course-material workspace for building evidence-backed university Anki
decks. Import sources, map the course, generate and independently check cards,
correct source interpretations, review original evidence, compare generation strategies,
and export a real .apkg.

The Python/FastAPI backend owns documents, credentials, SQLite state and a durable
concurrent task scheduler. The React interface runs in the desktop window or your
browser. Import and local extraction send nothing to a provider. Analysis requires
your OpenAI key and a confirmation
describing which text and rendered regions leave the machine.

## Desktop application

The Linux desktop distribution bundles Electron, Python, the backend and the
production interface. Open the AppImage or install the Fedora RPM; it starts its
own private service and saves data outside the installation. No Python/Node
development environment or manual server startup is needed for normal use.

```sh
chmod +x Anki-Generator-0.1.0-x86_64.AppImage
./Anki-Generator-0.1.0-x86_64.AppImage
```

Release artifacts are built under `dist/desktop`. See the [desktop guide](docs/desktop.md)
for RPM installation, FUSE fallback, migration of existing browser data, persistent
paths, native controls, troubleshooting and builds. The dated
[verification report](docs/verification.md) records which packaged checks ran.
Linux/Fedora KDE is the initial target; Windows/macOS packaging remains future work.

## Development and browser mode

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/),
Node.js 24 LTS (or 22.13+) and pnpm. uv manages Python 3.12;
the frontend pins its package manager. LibreOffice and bubblewrap are optional
system packages for isolated DOCX/PPTX rendering; native extraction remains
available when the engine or its sandbox is unavailable.

```sh
make doctor
make setup
make dev
```

The root Makefile is the common development interface. `make dev` opens the desktop
window with frontend hot reload; restart the processing service from Settings after
Python changes. `make build` creates a runnable desktop directory, `make run` opens
it, and `make package` produces AppImage/RPM releases. See `make help` and the
[development guide](docs/development.md) for all targets and Fedora prerequisites.

For the browser interface:

```sh
make build-web
make run-browser
```

Installation uses committed Python and frontend lockfiles and builds the interface.
run.sh starts the backend/worker at http://127.0.0.1:8765, serves the built frontend,
and opens your browser. After installation, Node and the internet are unnecessary
for local browsing, extraction, editing and export. OpenAI processing needs a
network connection and incurs API charges.

    ./run.sh --no-open-browser
    ./run.sh --port 8766
    ./run.sh --data-directory /path/to/private/workspace
    ./dev.sh

Legacy `./install.sh`, `./run.sh`, `./dev.sh` and focused packaging scripts remain
available. See the desktop guide before changing packaging.

`make dev-browser` runs the browser backend on :8000 and Vite on :5173 with live
reload. Browser-mode data lives in data/app/ in this checkout; desktop development
uses the same XDG paths as the installed desktop app unless explicitly overridden.
Stop the application before moving its
data directory. ANKI_GENERATOR_DATA_DIR is an optional launch override; regular
application settings are available in the GUI.

## Your first course

1. In onboarding or Settings, enter an OpenAI key, choose a model and test the connection.
   Session-only storage is always available; secure persistence is offered only
   when the OS credential store is usable. Keys never enter SQLite.
2. Create a course and choose its deck name, language and generation preferences.
3. Import files, a folder or ZIP. Assign Lecture, Personal notes, Exercises,
   Worked solutions or Reference roles, source authority, and question/solution links.
4. Run local extraction to inspect pages without external calls. Correct text or
   mathematical symbols, inspect correction history, and save original-coordinate
   evidence crops with zoom/pan. Alternatively, start analysis
   after confirming the OpenAI disclosure. Progress shows actual stages, counts,
   checkpoints, warnings, usage and pause/resume/cancel/retry controls.
5. Inspect the knowledge map and independent source-grounded coverage targets.
   Search/filter server-paged basic/cloze cards, inspect mathematics and sources,
   edit or regenerate, and review individually or in explicit revision-guarded
   selections. Keyboard shortcuts, field-level revision comparisons and restoring
   an earlier snapshot support review. Edits retain history and invalidate checks.
6. Approve cards, inspect the identity/update preview, resolve uncertain matches,
   then export Anki, JSON or CSV. Anki export requires human approval
   and blocks failed/duplicate candidates. A human can approve an otherwise
   unverified manual card with an explicit rationale; it remains unverified by models.

Settings discovers the models available to your account and offers searchable
choices, refresh and a configuration check before generation. Most users can keep
the default for all stages; advanced choices retain per-stage overrides and custom
identifiers. Unknown capabilities remain explicitly unverified. See
[model selection and compatibility](docs/models.md).

The Evaluation workspace maintains versioned reference datasets, source-linked
annotations, blind judgments and reproducible paired comparisons. Reports separate
automatic checks, model judgments, synthetic labels, human-origin labels, recorded
review independence and unreviewed denominators. New comparison runs require consent; captures of current
course cards under completed runs are labeled separately. See the
[GUI workflows](docs/gui-workflows.md) and [evaluation guide](docs/evaluation.md).

Independent checks are evidence, not proof. Review assumptions and uncertain
transcriptions. A revision limit never converts failure into approval.

Start generation in multiple courses without waiting for the first to finish.
**Tasks** shows running jobs, a persistent queue and paged history; the header and
course links retain live status while you navigate. Pause, resume, cancel, retry
or change queued priority independently. Settings exposes separate job, global
API, per-job/model API and local processing limits. Defaults are two course jobs
and four API requests. See [concurrent tasks](docs/tasks.md) for snapshots,
recovery, controls and limits.

## Documents, privacy and data

Supported imports: text/scanned/handwritten PDFs, PNG/JPEG, UTF-8 text, Markdown,
LaTeX, DOCX, PPTX and ZIP collections. Tall PDFs use overlapping bounded tiles with
original coordinates. Scans, mathematics and graphics receive visual analysis where
indicated. Unreadable or uncertain material stays visible.

DOCX/PPTX can render to PDF through isolated LibreOffice when the required engine
and operating-system sandbox are available. Otherwise native text/tables and
embedded raster extraction report layout, equation and chart limitations. Neither
conversion nor a plausible transcription establishes accuracy. Review the original
or supply a PDF when fidelity is insufficient. See
[format support and limits](docs/ingestion.md).

Browser/development data belongs under ignored data/. Desktop data defaults to
`~/.local/share/anki-generator`, with state/logs under `~/.local/state/anki-generator`
and support for absolute XDG overrides. Moving or replacing the executable does
not remove it. Import existing browser courses explicitly through validated backup/
restore; desktop never silently copies the checkout's `data/app`.
Synthetic fixtures are safe to track. Never commit private sources or credentials.
Settings can create a
private application backup and validate/restore it through the GUI. Validation
checks archive paths, file checksums, database/schema consistency and referenced
media in staging before restoration. Choose a clean state or explicitly confirmed
replacement; replacement retains a downloadable recovery archive. Active jobs must
be stopped as directed. Provider keys are excluded. JSON/CSV exports are not a
complete application backup.

The backend binds to loopback and validates hosts/origins and a CSRF token. Desktop
also requires a per-launch token on every route; its sandboxed, isolated renderer
receives narrowly scoped native actions. It is a personal local application,
not an authenticated multi-user network service.
Imported content and generated HTML are untrusted. No Anki collection is modified
directly. Read [Anki export behavior](docs/anki-export.md) before importing updates.

## Develop and verify

```sh
make setup
make check
make build-web
pnpm --dir frontend exec playwright install chromium
make test-browser
```

`make test-backend`, `make test-frontend` and `make test-desktop` run focused suites;
`make format` applies source formatting. `make clean` removes generated build/test
outputs while preserving application data, credentials and development dependencies.

Tests use temporary storage and an explicitly injected deterministic provider.
Production has no simulated generation fallback. Automated tests require no live
key or paid calls. Browser setup is described in [testing](docs/testing.md).
An optional pinned Anki core suite imports into disposable collections and tests
real update/scheduler behavior; see [Anki integration](docs/anki-integration.md).
Engineering workloads and their limits are documented in
[performance](docs/performance.md). Executed checks, requirement coverage and
validation limits are recorded in the
[verification report](docs/verification.md).
Desktop source/lifecycle and actual copied-distribution checks are described in the
[desktop guide](docs/desktop.md) and [backend protocol](docs/desktop-backend.md).
The original deterministic discovery command remains available:

    uv run anki-generator inspect fixtures/example-course --output outputs/example

Read [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md),
[data models](docs/data-model.md), [requirements](docs/requirements.md),
[card quality](docs/flashcard-guidelines.md), and [roadmap](docs/roadmap.md).
Templates are packaged in src/anki_generator/prompts/; see
[prompt policy](prompts/README.md). [Troubleshooting](docs/troubleshooting.md)
covers startup, provider, extraction and export failures.
