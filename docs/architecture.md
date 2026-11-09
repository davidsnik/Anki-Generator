# Architecture

## Runtime and boundaries

Desktop mode uses an Electron shell and a bundled PyInstaller one-folder backend.
Electron starts that backend on an allocated `127.0.0.1` socket, validates actual
health/readiness, then displays the existing production React interface. Bundled
assets, prompts, migrations and native libraries are read-only; XDG data/state and
the workspace lock are independent of install location and current directory.
The Python entry handles frozen multiprocessing before application imports.

Browser `run.sh` still launches `anki-generator serve`. FastAPI serves the built React/Vite frontend
and a same-origin JSON API. One local dispatcher polls SQLite for durable jobs and
admits bounded independent course-job threads; bounded stage threads run independent
units inside each pipeline. There
is no Redis, external database or request-scoped long-running background task.
The existing inspect CLI remains independent and entirely local.

The established src/anki_generator/ package is retained:

| Layer | Location and responsibility |
| --- | --- |
| Desktop shell | desktop/: isolated sandboxed window/preload, child lifecycle, authenticated origin, native menus/dialogs/tray/diagnostics; packaging/ and scripts/: locked frozen/backend release assembly |
| Interface | frontend/src: routed React views, TanStack Query, reusable accessible controls, KaTeX, source previews and light/dark themes |
| HTTP | api/: validation, host/origin/CSRF guards, CRUD, streaming upload limits, progress and downloads |
| Application | services/: credentials/settings, evidence-aware revisions/reviews, storage and export policy |
| Persistence | database/: SQLAlchemy entities, SQLite/WAL and versioned Alembic migrations |
| Ingestion | ingestion/: original discovery plus subprocess-bounded extraction and visual regions |
| Reasoning | llm/, processing/: official Responses SDK, typed contracts, evidence validation and concrete stage modules |
| Orchestration | orchestration/: persisted queue, dispatcher/job threads, global resource admission, safe checkpoints and restart recovery |
| Evaluation | evaluation/, api/evaluations.py and database/evaluation_entities.py: portable references, isolated paired runs, frozen snapshots, blind cases, labeled judgments and reports |
| Prompts | src/anki_generator/prompts/: packaged versioned templates, separate from course data |

The frontend uses scoped CSS and reusable native controls instead of a Tailwind/
shadcn stack, keeping the local dependency/build surface smaller while retaining
consistent design tokens, responsive layouts and interaction states. React owns UI
state; TanStack Query synchronizes server state. Provider keys are never exposed by GETs.

Desktop context isolation and renderer sandboxing remain enabled with Node disabled.
The main process injects a random session header only for its backend origin;
every desktop route, including static assets/health, authenticates it. The renderer
does not receive that secret. Restricted IPC, navigation, permissions and CSP keep
native privileges outside imported/generated content. Browser mode retains its
existing host/origin/CSRF protections without the desktop header requirement.
See [desktop usage/build](desktop.md) and [backend protocol](desktop-backend.md).

## Implemented pipeline

| Stage | Input → output | Failure and quality behavior |
| --- | --- | --- |
| Import/discovery | Categorized files → hash-addressed originals and stable document records | Reject traversal/unsafe ZIPs; report unsupported formats/duplicates; preserve role/authority |
| Extraction | Original + settings → pages, blocks, geometry, tiles, diagnostics | Subprocess limits; incomplete regions stay partial/unresolved; preserve originals |
| Visual interpretation/correction | Suspicious original tiles and text → transcription, equations, uncertainty; append-only human corrections → effective evidence | Consent/key for model calls; human precedence by default; retain original extraction, correction revisions and explicitly confirmed automatic overrides |
| Document understanding | Role-aware sections → concepts, competencies and evidence | Validate actual document/page/region/quotes; retain conflicts and assumptions |
| Course synthesis | Document analyses → hierarchy and relationships | Stable semantic IDs, terminology reconciliation, exercise frequency and importance rationale |
| Generation | Consolidated concepts/evidence/preferences → basic/cloze candidates | Learning-target identities independent of wording; preserve manual work |
| Factual review | Candidate + original evidence → verdict/issues | Independent call; missing/contradictory evidence blocks verification |
| Pedagogical review | Candidate + criteria → clarity/atomicity/transfer verdict | Separate prompt/call and actionable issues |
| Mathematics | Mathematical card + evidence → model review and supported identity/calculus/matrix/domain/counterexample calculations | Restricted AST-to-SymPy construction and subprocess budgets; calculation results are separate from source/human verification; undecidable or no counterexample is not proof |
| Revision | Issues + candidate + evidence → next revision | Finite attempts; recheck changed content; failures remain reviewable |
| Deduplication | Cached neural representations → bounded cosine candidates → separate semantic judgments | Embeddings propose candidates, not equivalence; preserve distinct learning targets and human work |
| Coverage | Independently inspected original sources → target hierarchy → inventory/card mappings and gaps | Inspect source chunks/visuals without trusting only the initial inventory; retain assumptions, methods and exercise competencies; bounded repair and unresolved-page gates |
| Human review | Card, source, revisions and checks → individual/bulk edits/decisions | Explicit IDs and expected revisions; edits invalidate checks; earlier snapshots restore as new revisions; failed/duplicate cards cannot be approved |
| Export | Eligible notes/media + prior immutable export → preview and .apkg/JSON/CSV | Reconcile uncertain identity, reuse stable GUID/model/deck IDs and content timestamps; safe templates/media; no live collection writes |

## Reliability and identity

Runs snapshot source hashes/roles/authority/links, criteria, models and extraction
settings, correction/crop revisions, processing budgets and prompt content hashes.
Changed inputs require a fresh run. Stages, diagnostics, usage and response
artifacts survive requests and restarts. Interrupted running jobs become paused.
Pause/cancel takes effect at a safe boundary rather than halfway through an API
request or atomic database update. Run responses include a mode-specific pending
stage plan before the worker starts. Conditional visual, mathematical and repair
work is labeled; missing stages become skipped after successful completion or
not-run after cancellation. Planned rows omit unknown item totals and never
replace recorded stage counts, statuses or diagnostics. Failed and paused runs
retain pending future work for retry/resumption. This is a read-only view, not
invented checkpoints or a percentage estimate.

Extraction keys include source hash and extraction settings/version. Model cache
keys include stage, prompt content, schema, evidence/payload, images, model and
reasoning settings. Recorded responses avoid repeated calls but do not guarantee
identical new requests. A crash before checkpointing a successful request can repeat
that request. Unrelated extraction remains reusable after criteria/source changes.

The desktop supervisor adds single-instance focus, authenticated readiness,
restart/error diagnostics and checkpoint-aware shutdown around this scheduler.
Closing during active work offers keep-open, safe quit and tray mode when available.
A drain timeout leads to keep-waiting or explicitly confirmed force quit, never an
automatic kill. Parent monitoring and per-data locks prevent competing orphan
ownership; unexpected interruption retains the existing paused recovery semantics.

Course/document/card IDs and note GUIDs persist in SQLite. Hashes identify byte
revisions, not permanent Anki identities. Concepts/cards reconcile semantic targets;
model identity drift can still need human reconciliation. Human edits preserve note
GUIDs. Schema changes require Alembic migrations, never runtime create_all changes.

Persistent `IdentityAlias` and `IdentityProposal` records separate exact stable
targets from uncertain neural/source matches. Splits/merges and human-reviewed
replacement require explicit decisions and retain revisions. Export preview
compares GUIDs and content hashes against immutable `ExportSnapshot` records;
unchanged notes retain their Anki modification time, while changed content advances
monotonically. The local cosine index stores an `n × dimensions` matrix and performs
bounded-candidate retrieval without allocating an all-pairs matrix. It is still
linear per query. See [semantic retrieval](semantic-retrieval.md).

`bounded_map` dispatches only independent units and returns stable input order.
A shared fair admission manager bounds physical external attempts across jobs,
with separate per-job/model caps and local parser/calculation limits; persisted progress/usage updates
are serialized. Pause/cancel stops new dispatch at checkpoints while in-flight
calls may complete and save results. Every request checks conservative UTF-8
text/schema/framing bounds and an image allowance; these are not measured usage.
Oversized indivisible claims fail instead of dropping assumptions. Stage retries
create a new attempt using prior configuration and reusable unrelated artifacts;
stale source/correction/crop snapshots are rejected. See [processing](processing.md)
and the limitations of the [measured workloads](performance.md).

Card search/filter/sort uses bounded SQL pages with counts and facets. Coverage
targets, blind evaluation cases, identity proposals and export details also expose
paged APIs. The GUI does not fetch complete card sets to filter them. Some server
aggregations, including export classification, still inspect the selected
collection and use memory proportional to it.

The original version-1 discovery manifest remains sorted and free of absolute root
paths/timestamps. It inventories bytes, not extracted meaning.

## Security, privacy and evaluation

Loopback, host/origin validation and per-process CSRF protect the interface. Streaming
body and ZIP member/path/size/ratio limits precede parsing. Extraction has file/page/
pixel/CPU/memory/time budgets. Original files remain immutable. Card HTML is escaped;
mathematics rendering disables unsafe trust. Source text never supplies executable
instructions or tool permissions.

Keys live in session memory or a supported secure OS keyring, optionally the
environment. No plaintext key persistence exists. GUI consent discloses transmission.
Curated provider errors exclude keys. Backups include private course data and omit
credentials. Use one backend process per data directory and a trusted local user;
this is not a hosted multi-user service. The data tree is assumed stable rather
than hostile concurrently rewritten. Discovery no-clobber writes require hard links.

Controlled-provider/browser tests establish state transitions, wiring, evidence
gates and package structure; they do not measure live model accuracy. Handwriting,
difficult mathematics, source mistakes and semantic drift need expert review and a
broader manually reviewed evaluation set. Live API validation is separate.

## Evaluation and restore boundaries

Datasets retain versioned reference concepts/examples, source manifests and label
provenance. New paired variants copy the same original course context into isolated
courses; prepared runs enter the queue only after experiment metadata commits.
Completed outputs are frozen before later user edits. Existing-run capture is
explicitly `current_course_at_capture`, requires matching source versions and
accepts no configuration override. It does not reconstruct historical card output.
Blind randomized pages hide model/configuration labels. Human, synthetic and model
judgments remain distinct, as do independent review and unassessed dimensions.
Promoting reviewed examples creates a new benchmark version without rewriting an
old experiment. See [evaluation](evaluation.md).

Backups use a consistent SQLite snapshot plus owned originals/artifacts, with
credentials excluded. Restore first validates a bounded private archive in staging:
paths/types, checksums where present, schema/migration compatibility, database
integrity/foreign keys and referenced media. Older supported backups may migrate
only in staging. Explicit clean/replacement policy and maintenance coordination
precede swapping owned data. Replacement retains a recovery archive; a durable
journal permits recovery from an interrupted process during a swap; it is not a
power-loss durability guarantee. Restored pending jobs are paused
instead of inheriting permission to send evidence automatically. This is
application-state restoration, not a merge or an Anki collection operation.

Real disposable Anki 26.09.4 core tests additionally exercise import/scheduler
behavior; they are separate from controlled model tests and from desktop/mobile
visual compatibility. See [Anki integration](anki-integration.md).

Concurrent course scheduling, queue ownership/state transitions, task read models,
input snapshots, history and live GUI synchronization are described in [tasks](tasks.md).
[Resource management](resource-management.md) documents global admission and backoff.
