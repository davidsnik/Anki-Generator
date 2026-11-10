# Testing and verification

## Offline checks

    make setup
    make check
    make build-web

`make test-backend`, `make test-frontend` and `make test-desktop` run focused
suites. `make lint`, `make format-check` and `make typecheck` are non-mutating;
`make format` applies formatting. See the [development guide](development.md)
for tool overrides, packaging and safe cleanup. Direct uv/pnpm commands remain
available for selecting individual checks.

Python tests cover original discovery/schema safety, genuine PDF/image/Office
extraction, long-page tiles and subprocess budgets, persistence, provider failure/
retry/refusal handling, evidence/mathematical checks, durable jobs and complete HTTP
course-to-Anki behavior. APKG tests inspect real ZIP/SQLite/media/templates/IDs.
Frontend unit tests cover mathematical/cloze rendering, presets and configuration,
coordinate inversion, typing-safe shortcuts, explicit bulk revision guards,
semantic field diffs, transcription replacement permission, targeted retry consent,
identity/export blocking and restore validation. Developer Python tests cover
origin-separated evaluation denominators, source/case binding, annotation history,
retrieval/fidelity metrics and benchmark snapshots. Model
tests cover credential-scoped discovery/cache invalidation, exact documented
capabilities, unknown/custom IDs, inaccessible selections, preflight before job
creation, custom embedding dimensions and real SDK transport to a local fixture.
Interaction tests cover combobox keyboard use, settings draft/save races,
per-course card filters, guarded card edits and source-quality presets.

Focused offline suites are also directly runnable:

    uv run --locked pytest tests/test_evaluation.py tests/test_source_fidelity.py tests/test_mathematical_operations.py
    uv run --locked pytest tests/test_card_tools.py tests/test_backup_restore.py tests/test_restore_recovery_races.py

These commands describe the current checks; the dated verification report states
which versions were actually executed. No full final backend pass is inferred from
a focused run.

The deterministic provider is under tests/support. Production has no fake-provider
selection or fallback. Tests explicitly inject it through the application factory.
No valid API key or paid call is required.

## Browser workflow

Install the official Playwright Chromium browser once:

    pnpm --dir frontend exec playwright install chromium

Build and run all workflows against an owned temporary test host:

    make test-browser

The runner selects a free loopback port, isolates data and credentials, waits for
readiness, propagates test failures and stops its own server. Select tests with,
for example, `make test-browser ARGS='--grep "model selection"'`.
For manually inspecting the controlled host, use two terminals:

    uv run uvicorn tests.browser_app:create_browser_app --factory --host 127.0.0.1 --port 8766
    pnpm --dir frontend test:e2e

The test host uses temporary SQLite/storage and controlled diagnostics/generation;
it is separate from the production launcher. **Use this test host, not a personal
workspace:** the new workflow intentionally validates and replaces application
data from its downloaded backup. Never point it at the production data directory.
Test-only diagnostics and 1,500-card bulk fixture insertion exist only in
`tests/browser_app.py`, with no production provider-selection mode.

Browser tests create courses, assign
roles, upload sources, extract, configure a test key, confirm processing, browse/
edit/review source-linked mathematics and export. Responsive/theme checks are separate.
Model/settings workflows cover session-key entry, connection feedback, discovery,
search/keyboard selection, per-stage overrides, refresh/reload, draft preservation,
custom IDs, inaccessible selections and invalid-key errors. Review UX workflows
exercise bulk source roles, guarded edits, persisted filters, course switching and
narrow layouts. The additional evidence/review workflow uses the deliberately wrong invisible OCR
sign in a genuine PDF, corrects its transcription through the GUI, saves a zoomed
original-coordinate crop, attaches it to a card, applies revision-aware bulk tags,
compares/restores content, confirms research navigation is absent,
pages/searches 1,500 cards, crosses a page boundary with review keys,
and validates/restores a real backup with recovery download. Synthetic labels are
declared synthetic and do not imply independent expert approval.
The default base URL is http://127.0.0.1:8766; ANKI_E2E_BASE_URL overrides it.
PLAYWRIGHT_BROWSERS_PATH can select a custom browser installation location.

A successful TypeScript/build check does not establish visual quality. Inspect
desktop/mobile light/dark screenshots, source previews, long dialogs and mathematics.
Tests save failure artifacts under ignored frontend/test-results/.

The implementation workflow also saved viewport screenshots under
`/tmp/anki-ui-*.png`; these are local QA artifacts rather than required repository
fixtures. Desktop source selection/transcription,
restore confirmation/recovery, and mobile source/card layouts were inspected.

## Packaged Linux desktop

Build with `make build` for a runnable directory or `make package` for AppImage/RPM.
These call `scripts/build-desktop.sh`, which synchronizes locked build dependencies,
runs source/backend/frontend/shell checks, builds production assets, freezes the
one-folder backend and produces AppImage/RPM artifacts. Building alone does not
establish that the copied release starts or that multiprocessing/resources work.
Default pytest explicitly skips the opt-in frozen checks and the Anki integration
module when its optional extra is absent.

After a build, copy the actual artifact and entire backend bundle outside the
checkout. For example, from the repository root:

```sh
desktop_qa_directory="$(mktemp -d /tmp/anki-desktop-qa.XXXXXX)"
cp dist/desktop/Anki-Generator-0.1.0-x86_64.AppImage \
  "$desktop_qa_directory/Anki-Generator.AppImage"
cp -a build/desktop/backend/anki-generator-backend "$desktop_qa_directory/backend"
ANKI_TEST_FROZEN_BACKEND="$desktop_qa_directory/backend/anki-generator-backend" \
  uv run --locked --extra anki-integration pytest tests/test_frozen_desktop.py -q
make test-desktop
make test-packaged APPIMAGE="$desktop_qa_directory/Anki-Generator.AppImage"
```

Install the optional Anki extra first when running the combined suite described
above; add `--offline` only when its locked dependencies are already available.
`ANKI_TEST_FROZEN_BACKEND` identifies the copied executable, not its directory.
Keep the entire one-folder payload beside it. GUI tests launch from isolated
working directories with temporary XDG data/state/cache paths and need a graphical
session. The copied application itself requires no developer Python/Node/Vite
process; those tools are used only by the external test harness.

Every Playwright Electron launch must explicitly use **`chromiumSandbox: true`**.
Playwright otherwise injects `--no-sandbox`, which invalidates security evidence
even if BrowserWindow preferences say `sandbox: true`. The packaged tests assert
that the flag is absent, renderer Node is disabled, context isolation is enabled,
and unauthenticated desktop requests are rejected. Runtime checks of the installed
RPM additionally distinguish the sandboxed renderer's `Seccomp`/`NoNewPrivs` from
the main process. Do not weaken sandboxing to make a test launch succeed.

Use the harnesses' dedicated **null keyring**, cleared production key and explicitly
controlled test endpoint. A session-only key operation can delete an existing
stored service key, so temporary data directories alone are insufficient credential
isolation. No personal keyring entry, source collection or real API key is needed.
The controlled HTTP server exercises the real SDK and frozen pipeline; its
synthetic responses are not evidence of paid OpenAI accuracy.

The smoke test covers actual visible startup, local PDF import/extraction,
navigation and persistence across relaunch. The workflow covers file/folder chooser
paths, multiple courses/queueing, mathematical evidence, human approval, export,
diagnostics and checkpoint shutdown. Save/open/external-link checks use controlled
destination/launcher stubs; they do not prove manual OS-dialog acceptance or external
application receipt. Lifecycle coverage/result must be read in the dated
[verification report](verification.md), not inferred from these runnable commands.
The unsaved-edit harness additionally checks native keep/discard decisions for
close, restart and reload, retained draft/ready state, backend process ownership
and persistence after relaunch. It runs with `make test-packaged`.

Test RPM installation, replacement and removal separately in an isolated Fedora
system as a regular desktop user. Verify package contents/permissions, actual
sandboxing and data persistence; an extracted RPM is insufficient installation
evidence. Inspect real packaged fonts/icons, source previews, mathematics, Tasks,
dialogs and Settings. FUSE-mounted AppImage startup, native Wayland launcher
grouping and notification delivery require their own host checks. The current
environment lacks `/dev/fuse`, so recorded AppImage tests use standard
extract-and-run with Chromium sandboxing retained. See the [desktop guide](desktop.md).

## Actual Anki core integration

    make test-anki PYTEST_ARGS=-q

The extra pins Anki 26.09.4's official Python/Rust importer and scheduler backend
(`26.9.4` package version). Eleven Linux cases passed in disposable temporary
collections: initial/repeated imports, added/omitted notes, same-second updates,
manual Anki edits under `IfNewer`/`Never`/`Always`, real review history/scheduling,
tags, mathematics and PNG media. Without the extra the module skips explicitly.
The suite never opens a user profile or contacts AnkiWeb. It is actual importer
behavior, not a mocked importer or a claim that the desktop GUI was inspected.
See [the tested matrix and limitations](anki-integration.md).

## Engineering workloads and optional live experiments

    uv run --locked python tests/performance_workloads.py --output /tmp/anki-performance.json

This exercises real extraction/rendering, durable pipeline state, context and
concurrency plumbing, cache/recovery, SQL card pages and local vector-index memory.
Its provider/vectors and token usage are explicitly simulated. The checked-in
[measured report](performance.md) covers 3–200 documents, 12 visual PDF pages and
1k/10k-card stores. Single observations are not performance guarantees or evidence
of live semantic quality.

The optional neural duplicate comparison requires both explicit flags and an
in-memory `OPENAI_API_KEY`:

    uv run --locked python tests/semantic_benchmark.py --live --consent --output /tmp/semantic.json

Its author-created reference cases are synthetic. This live command was not run in
the implementation session. Developer CLI experiments and portable reference datasets
are documented in [evaluation](evaluation.md); independent human judgments must
be supplied and labeled rather than synthesized from model opinions.

## Live validation and environmental limits

Live-provider evaluation is opt-in with a legitimately configured key. It may cost
money and transmit the explicitly selected course evidence. Offline test success
never implies live accuracy. Structural APKG validation, actual core integration,
desktop rendering, cross-version compatibility and independent academic quality
are separate evidence categories.

Some restricted execution environments block TestClient/thread/event-loop or
browser loopback sockets even for a minimal unrelated FastAPI app. Run such checks
where local sockets are permitted; do not weaken tests or report them as passed
when blocked. A harmless Starlette/httpx deprecation warning may appear with the
currently locked test-client combination.

GitHub Actions runs Python checks, frontend build/unit/format checks, fixture
discovery and the controlled browser workflow. Remote CI execution requires a push;
local execution is reported separately. The optional Anki extra, paid live model
evaluations, Office system packages and measured performance profiles are not
implicitly installed or run by the default CI job.

## Concurrent scheduler and task manager

    uv run --locked pytest tests/test_concurrent_jobs.py tests/test_tasks_api.py tests/test_tasks_migration.py tests/test_global_resources.py tests/test_resource_api.py
    uv run --locked pytest tests/test_job_mutation_races.py tests/test_task_output_counters.py

Real scheduler/provider barriers establish cross-course overlap, bounded active jobs,
queued admission, state/control/failure isolation, fair resource slots and backoff.
Task pages and events are bounded; simultaneous submission and legacy migration
cases exercise actual SQLite transactions. The concurrent browser workflow uses
synthetic courses and a gated provider; it does not bypass the production scheduler.
See [tasks](tasks.md) for usage and [resource management](resource-management.md) for limits.

## Developer benchmark regression and offline smoke

```sh
uv run --locked pytest tests/test_benchmark_runner.py tests/test_benchmark_profile.py tests/test_benchmark_review_metrics.py tests/test_benchmark_engineering.py tests/test_developer_measurements.py
make benchmark-smoke
```

Tests use synthetic archives/PDF/Office files, temporary private directories and
the actual bounded parser/durable runner. They cover traversal/link/expansion
rejection, stable manifests, immutable source/harness snapshots, changed-source
failure, live-call opt-in gates, interruption cleanup, portable case references,
provenance/unknown denominators, literal transcription metrics, explicit relevance,
observed human effort and paired-input guards. None needs a real key.

Source-fidelity regressions cover localized PDF lines without moving existing tile
geometry, unsupported math-font controls, native OOXML structures and unverified
Office conversion supplements, partial-coverage preservation, human correction
history, parser/render measurements and cache reuse. The opt-in copied frozen
suite includes these native Office equations and actual parser measurements.
See [developer evaluation](evaluation.md) for private real-source experiments;
they remain opt-in and outside ordinary CI and GUI workflows.
