# Requirements and scope

## Objective

Transform heterogeneous university material into accurate, comprehensive,
educationally useful Anki decks. Mathematical precision, evidence and human judgment
take priority over quantity or API cost. Normal actions are graphical: configure,
create a course, import/categorize, select criteria, process, inspect, review and export.

## Implemented functionality

- Local React interface, FastAPI backend, SQLAlchemy/SQLite, Alembic migrations and
  Linux install/launch/development scripts.
- Linux Electron shell with a frozen one-folder Python backend, production assets,
  AppImage/RPM build paths, automatic authenticated startup, remembered window state,
  native save/open actions, conditional tray/notifications and desktop diagnostics.
  Browser development and the original inspect CLI remain available. Executed
  packaged checks are recorded separately in [verification](verification.md).
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
- Genuine concurrent course jobs with a persistent priority/FIFO queue, same-course
  exclusion, idempotent submissions, frozen inputs and separate global API/local
  budgets. Central Tasks provides paged history, independent controls, per-task
  output counters, events and live global/course indicators.
- Search/filter/flip/study, mathematical rendering, source-page inspection, persistent
  edits/history/review, targeted regeneration and manual cards.
- Real Anki packages, MathJax/media, stable GUIDs/note types, history, JSON/CSV and
  local backups. Existing Anki collections are never modified directly.
- GUI key/model/settings management; explicit external-processing confirmation;
  secure OS persistence where available and session-only fallback.
- Versioned evaluation datasets and annotations, structured reference concepts and
  card examples, isolated paired configurations, blind/randomized review,
  provenance-aware human/model/synthetic judgments, reusable reviewed examples,
  comparison reports and explicit unreviewed denominators. Research workflows use
  developer CLI tools and standalone reports, outside the ordinary application GUI.
- Original/effective transcription inspection, append-only corrections and human
  precedence, rendered mathematical previews, original-coordinate high-resolution
  region selection with zoom/pan, saved card/concept evidence and targeted retries.
- Independent original-source learning-target inspection and reconciliation,
  hierarchical concept/assumption/method/exercise coverage, real neural candidate
  retrieval followed by separate duplicate/identity judgments.
- Active bounded worker/API concurrency, conservative request budgets, bounded
  source/image/embedding batches, persistent caches, stage/source retries and
  server-paged card search/filtering and export details.
- Revision-aware bulk review/tags/topics/regeneration, typing-safe shortcuts,
  readable findings, full editable-field revision comparison and explicit restore.
- Persistent aliases and human new/match/split/merge decisions; export preview for
  new/matching/modified/uncertain/missing/duplicate notes and immutable export
  snapshots with stable content modification times.
- GUI backup validation, staged schema/integrity/media checks, clean or explicit
  replacement restore, recovery archive and crash-recoverable replacement.
- Preserved deterministic standalone discovery CLI and versioned manifest.

Desktop resources are read-only; XDG data/state paths persist independently of the
executable and working directory. Existing browser workspaces migrate explicitly
through validated backup/restore or deliberate selection of their data directory.
No automatic copying/merging or credential transfer occurs. The shell uses a
single-instance strategy plus backend workspace ownership; active work drains to
safe checkpoints before shutdown, with force termination requiring confirmation.

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

Human source-transcription verification, a supported symbolic calculation, an LLM
claim judgment and a human card decision have distinct meanings. Source corrections
retain original extraction and invalidate dependent checks/coverage. Human-verified
corrections survive automatic processing unless explicit replacement is requested.
Embedding similarity supplies candidates and is never an equivalence probability.
Pending identity conflicts block affected Anki notes until reconciled.

Evaluation reports must preserve source/correction/crop versions, effective
configuration and frozen card/reference snapshots. Existing-run captures represent
the current course at capture, not reconstructed historical outputs; they require
matching source versions and accept no new configuration override. Isolated paired
executions preserve the original course context. Synthetic and model labels never
count as independent human acceptance. Unknown/unreviewed results stay in their
stated denominators; absence of a numerical counterexample is not proof.

## Nonfunctional requirements

- Reproducibility: locked dependencies, versioned prompts/contracts, effective run
  configuration and responses; deterministic local work.
- Resumption: bounded checkpoints and cached responses, invalidation of affected
  descendants, preservation of unrelated work; no exactly-once provider guarantee.
- Observability: actual stages/counts, diagnostics, timestamps, token usage, reuse,
  and estimates only where reliable model pricing is available.
- Resource control: upload/archive limits, extraction memory/time/page/pixel budgets,
  bounded reasoning sections, worker/request concurrency, context allowances,
  paged collection APIs and finite retry/revision loops. Oversized indivisible
  claims fail visibly rather than losing mathematical assumptions by truncation.
- Privacy: local-by-default data, explicit external consent, no plaintext keys,
  secret logs, committed private sources or unexpected transmissions.
- Security: loopback/CSRF/origin/host guards, safe paths, inert imported content,
  sanitized rendering and no execution of document/model instructions.
- Desktop isolation: sandboxed/context-isolated renderer without Node access,
  restricted preload IPC/navigation/CSP and per-session authentication on every
  desktop HTTP route. No runtime developer-dependency installation is required.
- Maintainability: typed contracts, focused modules, failure-path tests, simple
  durable local worker rather than distributed infrastructure.

## Practical limits and excluded scope

Model agreement and supported symbolic calculations are not general formal proof.
Live accuracy still needs paid-provider evaluation and independently reviewed
multi-subject university sources. The initial committed evaluation references and
engineering workloads are synthetic. Private real-course inventories, extraction
cycles and local measurements are separate ignored artifacts; source-grounded
assistant annotations remain provisional and human judgments remain pending.
Optional Office conversion still
requires original-page review; native fallback cannot promise full equation/chart
layout. See [ingestion](ingestion.md), [mathematical verification](mathematical-verification.md)
and [performance](performance.md).

Actual import/update/scheduling cases passed against the official Anki 26.09.4 core
in disposable Linux collections. This is stronger than package-structure inspection
and narrower than a desktop/mobile/version compatibility guarantee. See the exact
tested settings and limitations in [Anki integration](anki-integration.md).
No full image-occlusion masking, AnkiConnect, hosted multi-user service, distributed
queue, mobile-native app, or universal scheduling-preserving Anki import guarantee
is supplied. Fedora KDE x86_64 is the initial desktop packaging target; the dated
verification record distinguishes build, frozen-backend, shell and installed-package
checks. Windows/macOS installers, older-Linux compatibility and host-specific
credential/Office sandbox behavior remain platform work. Study view is a preview,
not a replacement spaced-repetition scheduler. Back up collections and check Anki
import settings before updates. See the [current status and remaining work](roadmap.md).
