# Architecture

## Runtime and boundaries

run.sh launches anki-generator serve. FastAPI serves the built React/Vite frontend
and a same-origin JSON API. One local worker polls SQLite for durable jobs. There
is no Redis, external database or request-scoped long-running background task.
The existing inspect CLI remains independent and entirely local.

The established src/anki_generator/ package is retained:

| Layer | Location and responsibility |
| --- | --- |
| Interface | frontend/src: routed React views, TanStack Query, reusable accessible controls, KaTeX, source previews and light/dark themes |
| HTTP | api/: validation, host/origin/CSRF guards, CRUD, streaming upload limits, progress and downloads |
| Application | services/: credentials/settings, evidence-aware revisions/reviews, storage and export policy |
| Persistence | database/: SQLAlchemy entities, SQLite/WAL and versioned Alembic migrations |
| Ingestion | ingestion/: original discovery plus subprocess-bounded extraction and visual regions |
| Reasoning | llm/, processing/: official Responses SDK, typed contracts, evidence validation and concrete stage modules |
| Orchestration | orchestration/: persisted queue, worker, safe checkpoints and restart recovery |
| Prompts | src/anki_generator/prompts/: packaged versioned templates, separate from course data |

The frontend uses scoped CSS and reusable native controls instead of a Tailwind/
shadcn stack, keeping the local dependency/build surface smaller while retaining
consistent design tokens, responsive layouts and interaction states. React owns UI
state; TanStack Query synchronizes server state. Provider keys are never exposed by GETs.

## Implemented pipeline

| Stage | Input → output | Failure and quality behavior |
| --- | --- | --- |
| Import/discovery | Categorized files → hash-addressed originals and stable document records | Reject traversal/unsafe ZIPs; report unsupported formats/duplicates; preserve role/authority |
| Extraction | Original + settings → pages, blocks, geometry, tiles, diagnostics | Subprocess limits; incomplete regions stay partial/unresolved; preserve originals |
| Visual interpretation | Suspicious original tiles and text → transcription, equations, uncertainty | Consent/key required; preserve original images and uncertain alternatives |
| Document understanding | Role-aware sections → concepts, competencies and evidence | Validate actual document/page/region/quotes; retain conflicts and assumptions |
| Course synthesis | Document analyses → hierarchy and relationships | Stable semantic IDs, terminology reconciliation, exercise frequency and importance rationale |
| Generation | Consolidated concepts/evidence/preferences → basic/cloze candidates | Learning-target identities independent of wording; preserve manual work |
| Factual review | Candidate + original evidence → verdict/issues | Independent call; missing/contradictory evidence blocks verification |
| Pedagogical review | Candidate + criteria → clarity/atomicity/transfer verdict | Separate prompt/call and actionable issues |
| Mathematics | Mathematical card + evidence → review and suitable symbolic checks | Limited AST-to-SymPy grammar; no evaluation of arbitrary strings; undecidable is not proof |
| Revision | Issues + candidate + evidence → next revision | Finite attempts; recheck changed content; failures remain reviewable |
| Deduplication | Retrieved card pairs → semantic decisions | Similar vocabulary alone never removes a card; preserve distinct targets |
| Coverage | Inventory + verified mappings → gaps/overlap report | Include exercise methods and unresolved sources; bounded targeted filling |
| Human review | Card, source, revisions and checks → edits/decisions | Edits invalidate old checks; overrides need rationale; failed/duplicate cards cannot be approved |
| Export | Eligible notes/media → .apkg, JSON/CSV, history | Persistent GUID/model/deck IDs, safe templates/media; no live collection writes |

## Reliability and identity

Runs snapshot source hashes/roles/authority/links, criteria, models and extraction
settings. Changed inputs require a fresh run. Stages, diagnostics, usage and response
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

Course/document/card IDs and note GUIDs persist in SQLite. Hashes identify byte
revisions, not permanent Anki identities. Concepts/cards reconcile semantic targets;
model identity drift can still need human reconciliation. Human edits preserve note
GUIDs. Schema changes require Alembic migrations, never runtime create_all changes.

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
