# Requirements and scope

## Objective

Transform heterogeneous university material into accurate, comprehensive,
educationally useful Anki decks. Mathematical precision, evidence and human judgment
take priority over quantity or API cost. Normal actions are graphical: configure,
create a course, import/categorize, select criteria, process, inspect, review and export.

## Implemented functionality

- Local React interface, FastAPI backend, SQLAlchemy/SQLite, Alembic migrations and
  Linux install/launch/development scripts.
- Course creation, renaming, archival/deletion, deck/language/preferences and statistics.
- Multi-file/folder/ZIP import with notes/lecture/exercises/solutions/reference roles,
  authority and question/solution links; original files persist separately.
- Text/scanned/handwritten PDFs, long-page tiles, PNG/JPEG, UTF-8 text/Markdown/LaTeX,
  and practical DOCX/PPTX extraction with explicit limitations and diagnostics.
- Course understanding before cards: hierarchical concepts, exercise competencies,
  source influence, assumptions/conflicts and semantic stable identities.
- Configurable basic/cloze, mathematics, diagrams and explanations; independent
  factual/pedagogical/mathematical checks, semantic duplication decisions, coverage
  audit and bounded targeted revision/gap filling.
- Durable jobs with actual progress/stages/usage, intermediate artifacts, incremental
  caches, diagnosis, pause/cancel, resume/retry and restart recovery.
- Search/filter/flip/study, mathematical rendering, source-page inspection, persistent
  edits/history/review, targeted regeneration and manual cards.
- Real Anki packages, MathJax/media, stable GUIDs/note types, history, JSON/CSV and
  local backups. Existing Anki collections are never modified directly.
- GUI key/model/settings management; explicit external-processing confirmation;
  secure OS persistence where available and session-only fallback.
- Preserved deterministic standalone discovery CLI and versioned manifest.

## Correctness and verification requirements

Every generated concept/card must retain actual document/page evidence, with
region/span where known. Unknown locations stay unknown. Extracted text does not
establish that diagrams/equations were captured. Ambiguous handwriting, assumptions,
source conflicts and failed regions stay visible. Source role informs importance
and review context rather than determining truth automatically.

The [card specification](flashcard-guidelines.md) governs retrieval targets, notation,
assumptions and transfer. Quantity follows knowledge targets. Natural-language
guidance cannot bypass evidence/checks. Generation never implies verification, and
a revision limit never approves failure. Edits invalidate checks on older revisions.

Anki requires human approval; failed/duplicate cards cannot bypass the gate through
selection. An unverified manual card can receive a human override with rationale;
this remains distinct from machine verification. Question text alone is never note
identity. Regeneration preserves known IDs/manual work; semantic identity changes
can still require reconciliation.

## Nonfunctional requirements

- Reproducibility: locked dependencies, versioned prompts/contracts, effective run
  configuration and responses; deterministic local work.
- Resumption: bounded checkpoints and cached responses, invalidation of affected
  descendants, preservation of unrelated work; no exactly-once provider guarantee.
- Observability: actual stages/counts, diagnostics, timestamps, token usage, reuse,
  and estimates only where reliable model pricing is available.
- Resource control: upload/archive limits, extraction memory/time/page/pixel budgets,
  bounded reasoning sections and finite retry/revision loops.
- Privacy: local-by-default data, explicit external consent, no plaintext keys,
  secret logs, committed private sources or unexpected transmissions.
- Security: loopback/CSRF/origin/host guards, safe paths, inert imported content,
  sanitized rendering and no execution of document/model instructions.
- Maintainability: typed contracts, focused modules, failure-path tests, simple
  durable local worker rather than distributed infrastructure.

## Practical limits and excluded scope

Model agreement and symbolic spot checks are not formal proof. Live accuracy needs
separate evaluation and human mathematical review. Office native complex equations,
charts/layout require original review or PDF conversion; see [ingestion](ingestion.md).
No full image-occlusion masking, AnkiConnect, hosted multi-user service, distributed
queue, mobile-native app, or universal scheduling-preserving Anki import guarantee
is supplied. Back up collections and check Anki import settings before updates.
