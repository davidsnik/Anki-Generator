# Persistent data and contracts

SQLite uses foreign keys, WAL and busy timeouts. SQLAlchemy entities are in
database/entities.py. Startup runs Alembic migrations from database/migrations/;
the initial schema is revision 0001. No runtime create_all shortcut is used.

| Entity | Identity and retained data |
| --- | --- |
| Course | UUID; name, description, language, deck name, archive state and validated criteria |
| Document | UUID within course; original relative/display names, SHA-256 revision, immutable blob path, role, authority, linked question/solution, extraction key/status/artifact and warnings |
| Page | Document + one-based number; original dimensions, text/blocks, boxes, regions, warnings and extraction state |
| Concept | Stable semantic UUID; hierarchy, statement/kind/importance, assumptions/relationships/exercise evidence in metadata, sources, exclusions and coverage |
| Card | Stable semantic UUID and persistent note GUID; basic/cloze type, pedagogical kind, front/back/explanation, tags, evidence/media, exact revision, quality/review states and manual-edit flag |
| Revision | Card + revision number; full content snapshot, origin/instruction and timestamp |
| Verification | Card revision, run, stage/model/prompt version, verdict, issues, evidence and detailed reasoning |
| ReviewDecision | Card revision, explicit human decision/rationale and timestamp |
| Run | UUID/course; input and configuration snapshots, request, status/stage, timestamps, checkpoints, progress, errors/warnings, usage and metrics |
| Stage | Run + stage name; actual completed/total units, artifact references, timestamps/error/status |
| ExportRecord | Course/deck, selected IDs, format/count, private file path/hash and timestamp |
| ApplicationSetting | Validated non-secret application configuration; credentials are excluded |

Nested structured evidence/artifacts use JSON columns; originals, PNG regions,
cached responses and exports live in the private data tree. Source locations
retain document/page/region/quote and bounding box when known. Coordinate systems
are explicit in extraction artifacts; see [ingestion](ingestion.md).

Quality state is separate from human review. Generated cards begin pending and
unverified. Independent checks can produce verified, needs_review or rejected
outcomes; semantic duplicates remain explicit. Edits increment revision, preserve
the GUID and reset verification/review. Past checks remain attached to their checked
revision. Human approval of an otherwise unverified card needs a rationale and
does not rewrite machine-verification state. Removed sources invalidate cards.

The source hash is a byte revision, not a permanent document/concept/note ID.
Generated card targets reconcile semantic identities across runs; human edits keep
their IDs. Changing wording alone never changes the GUID. A model that changes
the semantic target key may still require human reconciliation.

## Migrations and backup

Create migrations alongside entity changes, review generated SQL, and test upgrade
from the previous revision. From an initialized checkout:

    uv run alembic -c alembic.ini revision --autogenerate -m "Describe schema change"
    uv run alembic -c alembic.ini upgrade head

The root Alembic configuration targets data/app/application.sqlite3. Runtime
programmatic configuration targets the selected data directory instead.

GUI backup uses SQLite's backup API for a consistent database snapshot and includes
originals, page artifacts, response caches/checkpoints and exports. Keys are excluded.
Backups contain private course data. Stop the app, back up the current directory,
then unpack a backup into an empty selected data directory before restarting.
Do not run two backend instances against one directory.

## Source coverage, semantic retrieval and export identity (migration 0004)

`SemanticVector` stores versioned neural vectors keyed by course/object/hash/model/
dimensions. `IdentityAlias` retains accepted semantic-key mappings;
`IdentityProposal` retains ambiguous candidates, prior alternatives and explicit
human resolution history. `SourceCoverageTarget` stores the independent original-
source inventory, hierarchy, exact provenance, competency dimension, explicit
concept/card mappings and assessment origin/status for each run. `ExportSnapshot`
retains per-card GUID, revision, content hash and export content; APKG snapshots
also retain stable note modification times. These are additive tables, not changes
to existing note GUIDs. Migration 0004 follows `0003_source_fidelity`; human source
replacement origin is added by migration 0005.

## Concurrent tasks (migration 0006)

Run records add priority, queue-entry time, submission key, active processing clock
and recovery count. Unique indexes prevent duplicate idempotency keys per course
and simultaneous executing jobs for one course. Additive ALTERs preserve existing
verification-to-run foreign keys. JobEvent stores append-only state/stage/resource
diagnostics with paged access and cascading ownership by run. Original run source
and configuration snapshots remain the reproducibility boundary.

New runs version their per-task output counters in progress. Idempotent per-card
checkpoint markers distinguish generated, reused, new and verified cards without
counting retries twice. These historical counters remain separate from current
course totals; legacy runs without recorded counters expose unknown values.
