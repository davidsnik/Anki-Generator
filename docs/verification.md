# Implementation verification

Updated 9 November 2026. This report separates the current desktop release checks,
historical application checks, actual disposable Anki imports and validation
that has not been performed. Controlled model responses and synthetic labels do
not establish accuracy on unseen university courses. No live paid OpenAI evaluation
or independently reviewed multi-subject quality result is recorded here.

## Linux desktop release — 9 November 2026

The final distribution bundles Electron **45.2.3** and a one-folder Python backend,
built with Electron Builder **26.18.0** and PyInstaller **6.22.3**. The release was copied
outside the checkout to `/tmp/anki-desktop-final-release` and launched from an
unrelated working directory. Test workspaces, credentials and Anki collections
were isolated; no paid provider call or private course/collection was used.

| Command or check | Recorded result and scope |
| --- | --- |
| `./scripts/build-desktop.sh` | Passed the complete default build: Python Ruff lint/format (**172 files**), **453 Python tests passed / 6 optional checks skipped in 132.81 seconds**, **53 frontend unit tests**, **16 shell unit tests**, strict TypeScript/Vite, frontend formatting and AppImage/RPM packaging. Log: `/tmp/anki-generator-desktop-final-build.log`. The default run omits opt-in frozen checks and the optional Anki extra. |
| Final shell correction and repackaging | Actual lifecycle QA found that a delayed failed-startup child exit could replace the useful database diagnosis with a generic crash message. The supervisor now retains the curated error. **17/17 shell tests passed**, including the delayed-exit regression; formatting passed. Electron/AppImage/RPM were rebuilt from the repaired shell with unchanged Python/frontend payloads. |
| `ANKI_TEST_FROZEN_BACKEND=/tmp/anki-desktop-final-release/backend/anki-generator-backend uv run --locked --offline --extra anki-integration pytest -q --tb=short` | **469 passed, no skips, in 170.63 seconds**; one harmless Starlette/httpx deprecation warning. Includes **5 actual copied frozen-backend checks** and **11 official Anki 26.09.4 core cases**. |
| Final Python/repository checks | Ruff lint and format passed for **172 Python files**; `git diff --check` passed. |
| Final browser regression suite | **4/4 passed in 40.1 seconds**: concurrent courses 12.9s, review/evaluation/restore tools 11.9s, generation/export 12.2s, mobile/dark navigation 2.4s. |
| `node tests/desktop/launch-smoke.cjs /tmp/anki-desktop-final-release/Anki-Generator.AppImage` | Actual copied AppImage passed visible-window startup, bundled local PDF import/extraction/source preview, Settings/Tasks navigation, close/relaunch and course/document persistence. |
| `node tests/desktop/workflow.cjs /tmp/anki-desktop-final-release/Anki-Generator.AppImage` | Actual packaged workflow passed: file/folder chooser paths, two concurrent held courses and a third queued, independent completion/review/export, mathematical content/original region/human approval, native APKG save dispatch, diagnostics, external-link dispatch and active-close checkpoint/relaunch paused recovery. |
| `node tests/desktop/lifecycle.cjs <copied-AppImage> <linux-unpacked> <temporary-workspace>` | **All 6 scenario groups passed** on the final AppImage hash below: unexpected child exit/retry and retained course/document; second instance and remembered size; missing executable/frontend repair; corrupted database retention with actionable diagnostics/retry; quit during startup; quit during a held restart without replacement launch; and active-job tray/background restoration. Related scenarios share groups. All 11 observed backend processes and the fixture stopped. Report: `/tmp/anki-desktop-final-lifecycle-4/report.json`. |
| Actual Fedora RPM | The final repaired RPM was installed through DNF in a fresh official Fedora 44 rootless container; `rpm -V`, regular UID 1000 launch, Overview/Settings, health, Tasks summary, native window identity/icon, graceful exit and uninstall with retained schema-0006 database passed. Evidence: `/tmp/anki-generator-rpm-final-qa/evidence/`. Before the shell-only error-message correction, the same backend/frontend and RPM spec also passed actual replacement with course/document/extraction retention. Disposable containers were removed; host packages were untouched. |
| Renderer sandbox | Final packaged GUI tests explicitly used `chromiumSandbox: true` and checked absence of `--no-sandbox`, context isolation enabled and renderer Node disabled. The installed RPM renderer had `NoNewPrivs: 1` and `Seccomp: 2`, while its main process had `Seccomp: 0`. Unauthorized desktop bootstrap requests returned HTTP 401. |
| Native identity and visual QA | Actual WM_CLASS and the 512px application icon matched the packaged identity. Mathematical source/review, concurrent Tasks and RPM desktop Settings screenshots were visually inspected; layouts/assets were clean. Native Wayland retains compositor control of absolute window X/Y placement; saved window size restores. |
| Packaged credential persistence | The actual copied frozen backend saved a synthetic key in KDE SecretService, read it back, retained `keyring` status after backend restart, and removed it successfully. The probe selected the standard keyring `KeePassXC` attribute scheme plus a unique application marker after asserting no matching item existed, leaving the normal application credential attributes untouched. Cleanup confirmed no test item remained. Evidence: `/tmp/anki-packaged-keyring-qa/result.json`. Other synthetic GUI/frozen tests used a null keyring and session-only test keys. |

Native save destinations, file opening and external-browser dispatch were exercised
with controlled destination/launcher stubs. These checks establish the application's
dialog/dispatch boundaries, not manual acceptance of an OS dialog or receipt by an
external browser/application. The real SDK connected to an explicitly controlled
HTTP fixture, including image requests and concurrent processing; production did
not substitute a fake provider. Python/Node/Playwright belonged to the test harness,
not the runtime requirements of the copied application.

One GUI workflow run overlapping other desktop automation timed out opening the
third course. A fresh isolated rerun of the entire workflow passed on the final
artifact; failure screenshot/error capture was added to the harness. The overlap
was not isolated as a cause, and no application change was inferred from that
single automation timeout. The final smoke and full workflow used the
`smoke-repaired` and `workflow-repaired-isolated` workspaces, respectively.

The frozen-backend suite exercised bundled PDF/image/Office parsers, spawned SymPy,
SQLite migrations, concurrent real-SDK transports to the fixture, APKG generation,
backup/restore, persistence, second-owner rejection, corrupt-database failure,
safe checkpoints and abrupt termination/recovery. No repository-relative resources
or development Python environment were needed by the copied executable.

Final release artifacts:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `dist/desktop/Anki-Generator-0.1.0-x86_64.AppImage` | 227034051 | `cf3cb63dfa7818e761d5a0df362ae42da58bc92974ac5f13c15f46d705ed01e0` |
| `dist/desktop/Anki-Generator-0.1.0-x86_64.rpm` | 200468411 | `41be332fb452b8f44ed5296f51eb459cd17c0073d204fbbacdeeeb5e247498e0` |

The release directory also retains `SHA256SUMS`. Final relative Markdown links
passed across 24 top-level documentation files, desktop/test source formatting
passed, and `git diff --check` was clean. Generated pnpm lockfiles retain their
package-manager formatting rather than being treated as hand-formatted source.

The execution environment has no `/dev/fuse`; AppImage checks used its standard
extract-and-run path with Chromium sandboxing retained. A mounted FUSE launch,
KDE Wayland launcher grouping and OS notification receipt remain manual validation.
Other Linux/glibc bases and Windows/macOS remain unestablished. See
[desktop usage/build](desktop.md) and [test commands](testing.md).

## Concurrent Tasks — 9 November 2026, before desktop packaging

These checks include the earlier quality/review improvements and the completed
concurrent scheduler, shared resources, task APIs and GUI. These totals predate the
desktop release checks above. All processing data,
browser hosts and Anki collections used for verification were temporary. No paid
provider requests were made.

| Command or check | Recorded result and scope |
| --- | --- |
| `uv run --locked --offline --extra anki-integration pytest -q --tb=short` | **441 passed in 139.26 seconds**, no skips; one non-fatal Starlette/httpx deprecation warning. Includes all 11 official Anki core cases. |
| `uv run --no-sync ruff check .` and `uv run --no-sync ruff format --check .` | Passed; all **157 Python files** formatted. |
| `uv lock --check --offline` | Current; 74 packages resolved. No new dependency was needed for concurrent Tasks. |
| `pnpm --dir frontend build` and `pnpm --dir frontend format:check` | Strict TypeScript/Vite build and Prettier passed. |
| `pnpm --dir frontend test` | **49 tests passed**, including Tasks rendering/controls/counters, settings, synchronization and existing review/evaluation workflows. |
| `ANKI_E2E_BASE_URL=http://127.0.0.1:8767 pnpm --dir frontend test:e2e` | **4/4 passed in 41.3 seconds** against a fresh final backend: concurrent Tasks 13.7s, evidence/review/evaluation/restore 11.9s, original generation/APKG 12.6s and mobile/dark navigation 2.3s. |
| `./install.sh` | Final normal locked installation, TypeScript/Vite build and bundled asset copy passed in 7.93 seconds. All 117 packaged frontend files matched the production build. Normal installation omits the optional Anki test extra. |
| Installed package | Offline sdist/wheel build and isolated installation of the wheel plus 58 runtime packages passed. From outside the checkout, imports resolved to site-packages; all 117 frontend assets matched, migration head was `0006_concurrent_tasks`, GUI/task routes, bootstrap, CLI help and a three-document version-1 discovery manifest passed. |
| Launchers | Actual `run.sh --no-open-browser --data-directory <temporary directory> --port <available port>` and `dev.sh` with isolated data passed. Production Tasks/GUI/bootstrap and development backend/Vite proxy were checked; all owned servers stopped. |
| Repository checks | Shell syntax, relative links in 23 Markdown files, ignored private/generated paths and `git diff --check` passed. No commits or pushes were made. |

Real scheduler/provider barriers prove simultaneous work in two courses, a third
persistent queued task, automatic capacity reuse, independent controls/failures,
same-course exclusion and course-specific outputs. The browser test reviews and
exports one completed course while other jobs are still running. Backend cases
also cover global/per-job/model API admission, fair queues, live limits,
Retry-After/backoff, cleanup, upload responsiveness, duplicate submission races,
immutable source/config snapshots, safe drain/shutdown and checkpoint recovery.
Migration tests retain existing verification foreign keys and card GUIDs.

The first combined pass exposed an edit guard waiting on evaluation completion
instead of immediately rejecting a known active job, and an older artifact test
treating new card-counter metadata as a file path. The guard now rejects visible
active jobs before its writer-locked mandatory recheck; both edit/submission race
orderings remain tested. The artifact test still checks all structured-call
budgets and requires a nonempty set. Focused regressions and the complete suite
above passed after both corrections.

Desktop Tasks/queue/detail and mobile light/dark card/detail screenshots were
inspected. No overflow or browser page errors were observed. Live updates use
bounded polling with reconnect/focus and cross-tab refresh; this is not a provider
throughput benchmark. Live API latency/cost/quality, real account limits and broad
academic-document accuracy remain unmeasured.

## Six improvement areas — 9 November 2026, before concurrent Tasks

These results predate the concurrent Tasks extension. They are retained as the
verified baseline for the broader quality/review improvements; current totals are
recorded separately above.

| Check | Recorded result and scope |
| --- | --- |
| Frontend production build | Strict TypeScript and Vite passed for the completed workflows; framework/math chunks are separated. Explicit embedding-consent and human-independence label amendments also passed build/unit/format checks. |
| Frontend unit tests | 37 tests passed in seven files, including source coordinates, revision guards/diffs, shortcuts, dataset serialization, unknown denominators, retry consent and restore gates. |
| Frontend formatting and test host | Prettier check passed; `tests/browser_app.py` passed Ruff check/format. |
| New controlled browser workflow | Passed in 11.9 seconds against the frozen backend. Real local APIs exercised correction/crop attachment, bulk revisions/restore, fresh source capture, blind synthetic judgments, 1,500-card SQL paging/search, keyboard page-boundary navigation, full backup validate/replace/recovery and mobile views. |
| Actual Anki integration | Eleven Linux cases passed with the optional official Anki 26.09.4 Python/Rust importer/scheduler in disposable collections; see the exact [matrix](anki-integration.md). |
| Optional Office engine | LibreOffice 26.2.7.3 rendered genuine synthetic DOCX/PPTX through the isolated engine; PDF images were inspected. Native fallback and unavailable sandbox remain explicit limitations. |
| Engineering workloads | Real local extraction/persistence/context/cache/recovery and SQL/vector-index mechanics measured across 3–200 documents, 12 visual PDF pages and 1k/10k-card stores; provider responses/vectors and usage were simulated. See [report](performance.md). |
| Final combined backend | `uv run --locked --offline --extra anki-integration pytest -q`: **374 passed in 112.51 seconds**, no skips; one non-fatal Starlette/httpx deprecation warning. Includes all 11 actual Anki cases, source/Office/math, migration, snapshot concurrency, identity, coverage and recovery. |
| Combined controlled browser suite | All three Chromium workflows passed against the frozen backend in **26.5 seconds**: new evidence/evaluation/restore 11.9s, original generation/source review/APKG 11.6s, responsive/dark/mobile navigation 2.3s. |
| Python lint/format and lockfile | `uv run --locked --offline --extra anki-integration ruff check .` and `ruff format --check .`: passed, 138 Python files formatted. `uv lock --check --offline`: current, 74 packages resolved. |
| Locked installation | `./install.sh`: Python/frontend dependency synchronization, strict TypeScript/Vite build and bundled asset copy passed. Default installation omits the optional Anki test extra. |
| Final packaging | `uv build --offline --out-dir /tmp/anki-generator-improvements-build`: sdist and wheel built. A separate virtual environment installed locked public dependencies and the wheel. From `/tmp`, imports resolved to its site-packages; bundled GUI/assets, current migrations, course/evaluation/paging APIs and backup validation passed. Offline dependency resolution initially lacked binary wheels; public locked dependency installation succeeded with network access. |
| CLI and production/development launch | CLI help and three-file version-1 discovery manifest passed; shell syntax passed. `./run.sh --no-open-browser --port 8767 --data-directory /tmp/anki-generator-improvements-launch` served GUI/health/bootstrap with empty isolated data. `./dev.sh` with separate temporary data served backend/Vite and API proxy. Owned servers were stopped. |

The largest repeated-short-source engineering profile measured 200 documents at
130.27 seconds cold / 8.79 cached, with zero new simulated provider calls in the
cached run. The 10,000-card profile measured a 25-row SQL page at about 7.6 ms and
vector-index construction plus 100 searches at 0.788 seconds using a 5.12 MB,
128-dimensional matrix. These are single local observations; random/test vectors,
repeated learning targets and simulated provider latency cannot establish real
course accuracy, live cost or service-level performance. The [machine-readable
report](benchmarks/performance-2026-11-09.json) records limits and recovery details.

Desktop/mobile viewport screenshots were inspected for source correction and
125% crop selection, original-coordinate highlights, mathematical previews,
revision/source review, compact evaluation denominators, backup confirmation and
mobile source/card layouts. Local QA images are under `/tmp/anki-ui-*.png`.
The evaluation report visibly distinguishes human-origin labels from judgments
marked independently checked, shows unreviewed counts, and leaves 0/0 acceptance
as **Not measured**. Synthetic test judgments never become independent human results.

## Required workflow coverage

| Workflow | Executed evidence |
| --- | --- |
| A — Course evaluation | Full controlled paired variants, same frozen sources with cloned crops/corrections, distinct settings/prompt hashes, blind review, portable labels and reports. Browser judgments are explicitly synthetic. Atomic completion/case capture rejects concurrent edits until commit and recovers from snapshot failure. |
| B — Source correction | Genuine PDF has a wrong invisible OCR minus and visible plus. GUI corrects and saves crop/evidence; full pipeline regression uses corrected mathematics while retaining original extraction/history. |
| C — Omitted source target | Independent source audit recovers an assumption deliberately omitted from initial extraction; new target is reconciled, generated and independently checked. Generic model-key collisions retain distinct statements. |
| D — Semantic duplication | Actual vector retrieval mechanics with controlled vectors distinguish paraphrases from changed assumptions; separate semantic decisions preserve useful distinctions. No live embedding-recall claim. |
| E — Interrupted processing | Durable pause/cancel/failure/restart tests reuse valid responses; measured interrupted workload resumes. Actual worker lock-wait shutdown/restart and stale revision/source guards are exercised. |
| F — Anki update | Eleven official 26.09.4 core import/scheduler tests cover the nine requested update scenarios in disposable collections. |
| G — Large-course browsing | SQL test pages 2,500 cards; browser checks 1,500 seeded cards without the legacy all-card API and crosses a page boundary by keyboard; measured collection profiles include 10,000 cards. |
| H — Backup restoration | ZIP/SQLite round trip preserves sources, corrections, reviews, revisions, evaluation data and GUIDs. Genuine revision-0001 backup upgrades to current head and pauses queued jobs. Faults, schema/media damage, unsafe paths, symlinks and second-instance ownership are tested. |

These workflows use synthetic sources/controlled model responses except for the
explicitly real local parsers, Office engine, database, browser and Anki core.
The first combined pass found three obsolete assertions (revision0001 and the
old stage order); expectations were updated to the migrated schema and expanded
stage plan, and the final complete suite passed.

## Historical baseline — 8 November 2026

These commands/results predate the six improvement areas and remain recorded for
traceability. Their counts, migration head and package/launcher results describe
that baseline, not the latest state. The environment used uv 0.13.7, Python
3.12.14, Node 24.19.0 and pnpm 11.19.0. Commands omit local executable/cache paths.

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

The baseline production launch had zero courses and no configured key. Its browser
checks used a separate temporary workspace; owned servers were stopped afterward.
Current improvement checks also use temporary storage, including backup replacement
and disposable Anki profiles. No private collection or source corpus is required.
No commits or pushes have been made as part of this work; remote CI is not claimed.

The execution sandbox blocked minimal FastAPI TestClient thread/event-loop startup
and browser loopback access. Relevant checks ran where local sockets/threads were
permitted; tests were not weakened to report a pass. The baseline's non-fatal Vite
bundle-size warning was removed by separating framework and mathematical chunks
in the current frontend build. See [testing](testing.md) for reproducible commands.

## Requirement and evidence boundaries

| Area | What the implementation/checks establish | What they do not establish |
| --- | --- | --- |
| Evaluation | Versioned reference/source snapshots, isolated paired variants, provenance-aware blind judgments, explicit denominators and reproducible reports | Independent expert quality or causal model improvement without suitable human references and actually executed comparisons |
| Source fidelity | Original/effective text separation, append-only correction history and precedence, exact crop geometry and saved evidence; genuine synthetic OCR-sign regression | Reliable reading of all handwriting, arbitrary Office layouts, omitted diagrams or advanced mathematical notation |
| Mathematics | Safe bounded AST/SymPy operations, explicit domains/assumptions, calculational verdicts and counterexamples | General theorem/proof verification; no counterexample is not proof |
| Coverage and semantic decisions | Independent original-source targets, hierarchy and actual mappings, neural-candidate plumbing plus separate semantic judgments | Guaranteed extraction completeness, live neural recall/precision or correct equivalence merely from cosine similarity |
| Performance/recovery | Bounded active workers/requests, conservative contexts, paged card APIs, persisted reuse and fault/restart mechanics under measured fixtures | Exactly-once external billing, unlimited-course capacity, guaranteed live latency, or power-loss durability |
| Review/restore | Explicit card/revision selection, stale guards, typing-safe keys, full field diffs, new revisions on restore, staged archive validation and process-crash recovery | Automatic human approval, merging arbitrary databases, or restoring/modifying an Anki collection |
| Anki | Real generated packages and actual 26.09.4 core import/update/scheduler cases under stated settings | Universal desktop/mobile/version rendering, changed note-type/cloze compatibility or preservation under every import policy |

Source transcription verification, supported deterministic calculations, LLM claim
judgments, human-origin labels and independently checked human judgments remain
separate evidence. Revision limits never promote failure. Human edits invalidate
older checks and preserve GUID/history; unresolved identity proposals require
explicit reconciliation before affected APKG notes can export.

## Remaining validation and scope

- Supply a held-out, independently reviewed, legally redistributable multi-subject
  corpus and record disagreements, uncertainty and missing/unreviewed denominators.
- Execute explicit opt-in live OpenAI/embedding/vision comparisons with real usage,
  latency and independent labels; no such result is claimed by offline tests.
- Broaden real Anki compatibility beyond unchanged templates in Linux 26.09.4 core;
  desktop GUI/mobile visual checks and unusual note/deck settings are outstanding.
- Expand diverse full-course, difficult handwriting/Office and real concurrency
  workloads beyond the controlled engineering profiles.
- OS keyring and optional Office isolation depend on the host. Packaged Secret
  Service writes, broader Linux/glibc bases, mounted-FUSE startup, native KDE launcher
  grouping and notification receipt remain unestablished. Fedora RPM and AppImage
  extract-and-run checks are recorded above; native Windows/macOS packaging remains work.
- Image occlusion, AnkiConnect/synchronization, a standalone spaced-repetition
  scheduler, mobile-native and hosted multi-user products are outside current scope.

See [current status/roadmap](roadmap.md), [GUI workflows](gui-workflows.md),
[architecture](architecture.md), [ingestion](ingestion.md),
[mathematics](mathematical-verification.md), [evaluation](evaluation.md),
[semantic retrieval](semantic-retrieval.md) and [Anki export](anki-export.md).
