# Implementation verification — 8 November 2026

This report records executed local checks. Controlled-provider success establishes
application behavior; it does not establish the accuracy of a live model on an
unseen university course. No valid live OpenAI credentials were available.

## Executed checks

Commands below omit environment-specific executable paths and cache overrides.
The actual environment used uv 0.13.7, Python 3.12.14, Node 24.19.0 and pnpm 11.19.0.

| Command or check | Observed result |
| --- | --- |
| `./install.sh` | Locked Python/frontend installation, TypeScript check, production build and bundled asset copy passed |
| `uv lock --check --offline` | Lockfile current; 64 packages resolved |
| `uv run --locked --offline pytest -q` | 278 passed in 40.49 seconds; one Starlette/httpx deprecation warning |
| `uv run --locked --offline ruff check .` | Passed |
| `uv run --locked --offline ruff format --check .` | Passed; 88 Python files formatted |
| `pnpm --dir frontend run build` | Strict TypeScript and Vite production build passed |
| `pnpm --dir frontend test` | 20 tests passed in six files |
| `pnpm --dir frontend run format:check` | Passed |
| `pnpm --dir frontend test:e2e` | Two Chromium browser workflows passed against the explicitly controlled test server |
| `anki-generator --help` | Usable `inspect` and `serve` commands displayed |
| `anki-generator inspect fixtures/example-course --output /tmp/anki-generator-final-discovery --overwrite` | Three supported files; version-1 manifest validated using `DiscoveryManifest` |
| `alembic -c alembic.ini upgrade head` and `current` | Passed; revision `0001 (head)` |
| `bash -n install.sh run.sh dev.sh` | Passed |
| `uv build --offline --out-dir /tmp/anki-generator-final-build` | Source distribution and wheel built successfully |
| Isolated wheel installation and application smoke check from `/tmp` | Imports came from isolated site-packages; packaged migrations created SQLite; latest bundled GUI/assets, bootstrap and course creation passed |
| `./run.sh --no-open-browser` | Actual production launcher served GUI and `/api/health` on loopback port 8765 |
| `./dev.sh` with isolated data directory | Backend port 8000 and Vite port 5173 served successfully; Vite API proxy passed |
| Documentation links, Git-visible files and `git diff --check` | Relative links resolve; private/generated directories excluded; no whitespace errors |

The first production launch had zero courses and no configured key. Browser-test
data used a separate temporary workspace. Owned test/preview servers were stopped
after verification. No Git commits or pushes were made, so remote CI has not run.

The restricted execution sandbox blocks FastAPI TestClient's thread/event-loop
startup even for a minimal unrelated application. HTTP/backend/browser checks
therefore ran with local thread/socket access outside that sandbox. Tests were not
weakened or skipped. See [testing](testing.md) for reproducible normal commands.
Vite reports a non-fatal bundle-size warning; the local interface built and ran.

## Behavioral evidence

The backend suite covers discovery/schema/path safety, genuine PDF/image/Office
parsing, overlapping tall-page rendering, resource limits, API uploads and source
roles, SQLite migration/state, stable identities, consent and key isolation,
provider failure/refusal/retry handling, evidence and symbolic checks, bounded
revision, semantic decisions, actual coverage mappings, durable recovery/reuse,
human-edit preservation, backups and validated exports. APKG tests inspect the
real archive, SQLite notes, model templates, MathJax, tags, media and stable GUIDs.

The complete controlled browser workflow creates a course, uploads a genuine
mathematical PDF plus exercise/solution material, assigns roles, extracts pages,
configures a synthetic test key, confirms external-processing disclosure and waits
for the exact newly submitted generation run to complete. It then checks the
covered concept inventory, browses/flips cards, renders and edits mathematics,
attaches an actual source image, inspects revision/source evidence, records human
approval and downloads an APKG and backup. The separate responsive workflow checks
theme and mobile navigation with a multi-course sidebar.

Desktop and mobile screenshots were inspected, including the editor, side-by-side
source inspector with an original-coordinate highlight, knowledge map, settings
and drawer. Navigation, settled mobile drawer positioning and sidebar overflow
issues found during inspection were corrected and browser checks rerun.

## Requirement audit and feature status

| Area | Implemented behavior and evidence |
| --- | --- |
| Phase 0 foundation | Installable src package; deterministic local discovery CLI; versioned Pydantic manifest; synthetic fixtures; lockfiles; configuration/prompt policy; engineering instructions; offline tests and CI |
| Local application | React/TypeScript GUI, FastAPI API, SQLite/SQLAlchemy with packaged Alembic migrations, durable local worker, Linux installation/ordinary/development launchers |
| Course and source management | Course lifecycle/preferences; files/folders/ZIP; explicit educational roles, source authority and question/solution links; original preservation and previews |
| Ingestion | PDF text/blocks/geometry/graphics, bounded original-coordinate tiles, images/text/Markdown/LaTeX, practical DOCX/PPTX extraction; partial/unresolved states retained |
| Understanding and generation | Per-document/section analysis, hierarchical course synthesis, stable concepts, exercise competencies, role-aware configurable generation and named presets |
| Quality and orchestration | Separate factual/pedagogical/mathematical review, deterministic evidence checks, finite repair, semantic deduplication, explicit coverage and gap repair; durable checkpoints, pause/cancel/resume/retry and cache invalidation |
| Review and evidence | Basic/cloze/math/image cards, filters/search/study preview, editor/manual cards, revision comparisons, human decisions, targeted regeneration/topic actions, original page/region inspection |
| Export and safety | Genuine APKG, media/templates/MathJax/stable note GUIDs, human-approval gate and history, JSON/CSV and private backup; loopback/origin/CSRF protections, bounded archive/parsing paths and session/secure-store key handling |

Queued runs expose mode-specific pending stages without invented item totals.
Conditional work is labeled; unneeded stages become skipped when a run completes.
Actual persisted stage counts/errors remain authoritative. Regression checks also
confirm that completed interpretation/revision work does not remain running.

## Explicit limits and deferred work

- Live OpenAI generation/vision accuracy was not validated. Production uses the
  real official SDK; controlled responses exist only in explicitly injected tests.
- DOCX/PPTX native layout, equation objects and charts have partial support with
  visible warnings. Convert complex Office material to PDF for faithful inspection.
- Difficult handwriting, ambiguous notation, source conflicts and model uncertainty
  require human review. Model agreement and SymPy checks are not formal proof.
- Secure OS key storage depends on the host. Session-only storage works when an
  acceptable credential backend is unavailable; keys are excluded from SQLite/backup.
- APKG structure and stable regeneration were tested. Actual import/update/review
  history behavior across Anki versions/settings needs the disposable-collection
  compatibility matrix in the [roadmap](roadmap.md). No existing Anki collection
  was directly modified.
- True image occlusion and AnkiConnect synchronization are optional future work;
  ordinary image cards and downloadable APKG exports work.
- The reviewed multi-subject quality corpus, live-provider comparisons and larger
  course benchmarks remain evaluation work, with deliverables and acceptance
  criteria in the roadmap.

For operation, see the [README](../README.md); for technical boundaries, see
[architecture](architecture.md), [ingestion](ingestion.md),
[processing](processing.md), and [Anki export](anki-export.md).
