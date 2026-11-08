# Roadmap

Phase 0 establishes a local discovery tool. All document interpretation, models,
cards, and Anki export below are future work. Each milestone adds working behavior
and tests; proposed modules and dependencies are introduced when required.

## 0. Repository foundation — completed

**Objective:** provide an installable, agent-ready Python project and useful local
discovery command.

**Deliverables:** `uv` project and lockfile, Typer CLI, validated versioned discovery
manifest, TOML settings, synthetic fixtures, tests, Ruff, CI, and project documents.

**Acceptance:** installation, help, fixture inspection, tests, lint, and formatting
checks pass; output is deterministic and safe around symlinks and existing results.
No provider account or network is needed to run discovery or tests.

**Verified:** Python 3.12 installation, all 106 tests, Ruff lint/format checks,
fixture CLI discovery, source/wheel builds, and an isolated wheel installation.
The GitHub Actions workflow is configured; its remote execution awaits a push.

## 1. Reviewed evaluation set and digital PDF extraction — next

**Objective:** establish evidence and a measurable baseline before choosing complex
extraction or generation techniques.

**Deliverables:** a small redistributable digital PDF fixture with equations and a
diagram; page-aware extraction; typed blocks and diagnostics; a manually reviewed
set of learning targets, evidence locations, accepted cards, and deliberate defects.
Start with approximately 20 targets spanning definitions, conditions, procedures,
and exercise transfer; record reviewer corrections and dataset version.

**Acceptance:** extracted text and equation/figure locations can be checked against
rendered source pages; unreadable pages are explicit failures. At least one human
has checked the reference set. Define factual accuracy, target coverage, ambiguity,
redundancy, and acceptance-rate denominators. Reserve examples for held-out checks.

Evaluate PyMuPDF first. Add another extractor only when reviewed failures justify
it. The first implementation task is this bounded PDF extractor and fixture, not a
general document framework.

## 2. Small end-to-end vertical slice

**Depends on:** milestone 1.

**Objective:** learn from one short course fragment before expanding every stage.

**Deliverables:** digital PDF → evidence-linked knowledge records → structured
candidate cards → separate factual/pedagogical checks → human-readable review
output and a tiny Anki package. Use a minimal explicit topic list and controlled
prompt; configure external calls explicitly. Introduce only the model/export
dependencies needed for this slice.

**Acceptance:** every exported card is reviewed and traceable to a source location;
one deliberately wrong/ambiguous candidate is blocked; mathematics renders in an
imported sample package. Record baseline dataset metrics, request versions, and
usage. Offline tests replay synthetic responses; live model evaluation is separate.
This limited exporter proves the path; regeneration guarantees arrive in milestone 9.

## 3. Handwriting, mathematics, and visual evidence

**Depends on:** milestones 1–2.

**Objective:** handle cases a text layer cannot represent faithfully.

**Deliverables:** handwritten-page fixtures, region/page images, equation and figure
interpretation, uncertainty records, and a fallback/review policy. Compare vision
and deterministic extraction on the reviewed examples.

**Acceptance:** ambiguous symbols and missing diagram context are surfaced; original
regions remain available for review. Report symbol/condition failures separately
from prose quality. No unreviewed uncertain transcription is silently approved.

## 4. Course-level knowledge mapping

**Depends on:** milestones 2–3; digital-only courses may proceed after 2.

**Objective:** establish learning scope across multiple documents.

**Deliverables:** topic and prerequisite map, learning targets, importance evidence
from lectures/exercises, links to sources, and unmapped/failed material reports.

**Acceptance:** a reviewed mini-course has cross-document topic links and an explicit
scope; omitted, conflicting, and unreadable content remains visible in coverage.

## 5. Structured knowledge extraction and normalization

**Depends on:** milestone 4.

**Objective:** separate supported knowledge from its flashcard wording.

**Deliverables:** versioned knowledge records with definitions, claims, assumptions,
methods, evidence, and stable concept identities; conflict and duplicate handling.

**Acceptance:** each claim can be checked at its source; incompatible assumptions
are not merged; mathematical conditions survive normalization in regression cases.

## 6. Configurable flashcard generation

**Depends on:** milestone 5; expands the generator from milestone 2.

**Objective:** apply the [quality specification](flashcard-guidelines.md) across
courses without editing application code.

**Deliverables:** course preferences, supported card styles, versioned structured
prompts, separate answer/explanation fields, and diagram-aware candidates.

**Acceptance:** two synthetic course profiles produce appropriate differences;
schema failures are reported; exercise-derived cards test transferable knowledge.
Evaluate on held-out examples and document regressions.

## 7. Independent factual and pedagogical verification

**Depends on:** milestones 5–6; strengthens the initial checks from milestone 2.

**Objective:** make evidence-based approval a separate stage.

**Deliverables:** independent review contracts, deterministic checks where useful,
issue categories, revision invalidation, and bounded targeted repair.

**Acceptance:** seeded factual, assumption, notation, and ambiguity defects are
detected at measured rates. Uncertain or failed checks cannot become approval.
Publish dataset metrics and reviewer agreement; retain known failures.

## 8. Semantic deduplication and coverage audit

**Depends on:** milestones 4–7.

**Objective:** improve breadth without padding the deck with repeated facts.

**Deliverables:** near-duplicate proposals, coverage per learning target, exclusions
with reasons, and targeted requests for gap-filling or revision.

**Acceptance:** reviewed paraphrases are identified while distinct assumptions stay
separate; a deliberately omitted target is reported. Decisions preserve evidence
and produce measurable coverage/redundancy changes on the evaluation set.

## 9. Durable Anki identity and safe regeneration

**Depends on:** milestones 6–8; hardens the minimal exporter from milestone 2.

**Objective:** export accurate cards repeatedly without damaging user study state.

**Deliverables:** persistent concept/card/note identities, media validation, source
references, schema migrations, change preview, and an explicit user-edit policy.
Evaluate SQLite for identity persistence and `genanki` for complete package output.

**Acceptance:** unchanged cards retain IDs; wording edits, moved sources, splits,
and conflicts follow tested rules. A test collection retains scheduling after the
documented update path; no implicit note deletion or live-collection mutation occurs.

## 10. Human review and iterative refinement

**Depends on:** milestones 7–9; human review remains required in the earlier slice.

**Objective:** make correction and uncertainty resolution practical.

**Deliverables:** review workflow showing originals, evidence, issues, diffs, and
separate human decisions; targeted revision with complete history.

**Acceptance:** a reviewer can correct a card, trigger the relevant checks, and
export the approved revision. Pending items remain excluded by default. Measure
human acceptance rate and time per reviewed card alongside factual correctness.

## 11. Incremental processing, resumption, and performance

**Depends on:** validated contracts from preceding milestones; preserve basic
artifacts and run metadata as soon as model processing begins.

**Objective:** process large courses efficiently while preserving auditability.

**Deliverables:** content/config/prompt-aware invalidation, checkpoints, cache reuse,
bounded concurrency, retry limits, stage timing, and token/cost reporting.

**Acceptance:** interrupted runs resume without duplicate accepted results; changing
one source reprocesses the affected descendants; a prompt/schema change invalidates
the appropriate cache. Representative larger-course runs report resource usage and
retain identical deterministic artifacts for unchanged inputs.
