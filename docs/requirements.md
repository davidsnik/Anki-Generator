# Requirements

## Status and objective

The application turns a local university course directory into source-supported,
educationally useful Anki cards. Correctness, coverage, and learning value take
priority over token cost. Efficient reuse and visible resource usage still matter.

Phase 0 implements **local file discovery only**: `anki-generator inspect` records
relative paths, types, byte sizes, and SHA-256 hashes in a validated, versioned JSON
manifest. It does not read document content semantically, generate cards, contact a
model provider, or export an Anki deck. The configured extensions identify files
eligible for discovery; they do not imply working format parsers.

Current inspection succeeds for an empty directory and reports unsupported-file
and symlink counts. It skips nested symlinks, configured directory names, the
requested output directory, and directories bearing `.anki-generator-output`.
Read/hash errors abort without publishing a partial manifest. Existing manifests
require `--overwrite`; output may not equal or contain the input directory.

## Intended workflow (planned)

1. Select course materials and course preferences; preview what will be processed.
2. Discover documents, preserve originals, and extract content with page/region
   provenance, including text, equations, handwriting, and meaningful graphics.
3. Map course topics, prerequisites, learning goals, and evidence from exercises.
4. Extract supported knowledge items and generate focused retrieval prompts.
5. Independently check facts and pedagogy, then audit redundancy and coverage.
6. Revise targeted problems and route unresolved uncertainty to human review.
7. Export approved cards with stable identities and repeat safely after updates.

## Functional requirements

### Inputs and discovery

- Accept a directory and recursively inspect supported documents in deterministic
  order. See [configuration](../config/README.md) for the current extension policy.
- Record source-relative paths and content hashes; never equate a file extension
  with successful extraction or trustworthiness.
- Handle missing inputs, unreadable files, unsupported entries, empty courses,
  symlinks, and output collisions explicitly. Avoid scanning generated outputs or
  traversing symlinks into other directories. Never silently overwrite results.
- Eventually extract digitally generated and handwritten PDFs, lecture slides,
  exercises, worked solutions, LaTeX, images, and other formats where practical.
  Text extraction alone is insufficient for many mathematical documents.

### Knowledge and generation (planned)

- Course-specific settings must select learning scope, depth, terminology,
  language, card styles, explanation detail, and treatment of prerequisites.
- Cards must satisfy [the quality specification](flashcard-guidelines.md), with
  precise assumptions, quantifiers, notation, and one identifiable retrieval target.
- Preserve supporting evidence through every transformation. A derived claim must
  link to an actual document and specific page, region, or source span when known.
  Unavailable locations remain unknown; the system must not invent them.
- Reuse diagrams when they help retrieval or understanding, retaining source and
  region metadata. Export must support mathematical notation and image media.
- Exercises and solutions inform topic importance and transferable methods without
  reducing the deck to memorized answers to arbitrary exercise instances.

### Verification and review (planned)

- Track factual verification separately from pedagogical assessment. Generated
  output and a model's confidence are not proof of correctness.
- Check answers against source evidence and, where appropriate, independent
  derivations or deterministic checks. Surface conflicting sources and uncertain
  extraction, especially symbols, theorem conditions, and diagrams.
- Audit coverage against the course map and supported learning targets, including
  material that failed extraction. Report gaps rather than silently excluding them.
- Track redundancy, ambiguity, revision history, reviewer decisions, and unresolved
  questions. Unresolved correctness failures block approval and export by default.
- Permit human correction, rejection, and approval with preserved provenance.

### Output and identity (planned)

- Produce reviewable intermediate records and Anki packages with MathJax-compatible
  mathematics, referenced media, source information, and explicit verification state.
- Give concepts, cards, and Anki notes persistent identities independent of question
  wording. A question edit must not automatically create a new note.
- Distinguish source document identity from its path and current content revision.
  Content hashes detect changes but are not a complete identity or migration policy.
- Rebuilding a deck must preserve scheduling and user edits through an explicit,
  tested update policy. Preview changes; never delete notes or alter a live Anki
  collection as an implicit side effect.

## Nonfunctional requirements

- **Reproducibility:** version schemas, configuration, prompts, extraction tools,
  models, and relevant request parameters. Deterministic operations must be stable;
  record LLM outputs because later reruns may differ even with identical requests.
- **Resumption:** persist stage results and failures, invalidate affected artifacts
  after source/configuration changes, and resume without unnecessary model calls.
- **Observability:** expose stage progress, warnings, errors, elapsed time, provider
  usage, and retry decisions without leaking source contents or secrets into logs.
- **Failure handling:** distinguish permanent validation problems from transient
  provider/tool failures. Bound retries, keep diagnostics actionable, preserve
  partial evidence, and report incomplete coverage. Never fabricate missing output.
- **Scale:** allow bounded processing of large collections and reusable artifacts;
  introduce concurrency only with explicit resource limits and repeatable behavior.
- **Privacy:** Phase 0 operates entirely locally. Future external processing must
  be explicitly configured and make clear which text, page images, and metadata
  leave the computer. Keep credentials out of repositories and logs. Do not commit
  private course materials, local databases, run artifacts, or exported decks.
- **Maintainability:** use typed, validated contracts, small focused modules, local
  tests without credentials or network access, and dependencies justified by current
  behavior. Keep prompts, settings, and orchestration separate from business rules.

## Non-goals for Phase 0

Document parsing, OCR, LLM calls, knowledge graphs, card generation, verification,
human review UI, persistence beyond the discovery manifest, and Anki export remain
future work. Hosted services, autonomous agent frameworks, distributed processing,
and direct modification of existing Anki collections are outside this foundation.
