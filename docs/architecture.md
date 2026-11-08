# Architecture

## Current implementation

`anki_generator` is a Python package in `src/`, exposed through the
`anki-generator` Typer command. The implemented flow is:

```text
directory + validated discovery settings
    -> deterministic file discovery and SHA-256 hashing
    -> Pydantic manifest
    -> versioned JSON output
```

The CLI handles arguments and feedback; ingestion code handles discovery; models
define serialized contracts. No parser, model client, pipeline framework, or
speculative stage modules are needed for this flow. TOML configuration uses the
standard library and validates only settings discovery actually consumes.

`manifest.json` uses schema version `"1"` and hash algorithm `"sha256"`. Each
document has `relative_path`, `file_type`, `size_bytes`, and `sha256`. Paths are
normalized relative POSIX paths without traversal; the lowercase type must match
the filename suffix and hashes contain exactly 64 lowercase hexadecimal characters.
Pydantic tuples serialize as JSON arrays. Documents and excluded directory paths
are sorted and unique; unsupported/symlink counts describe skipped entries.

The manifest contains no timestamps or absolute source-root metadata. Consumers
must explicitly supply the source root and validate file hashes before using
records in later stages; a manifest alone cannot locate or guarantee unchanged
source bytes. Identical inputs and exclusions produce identical JSON bytes. An
output marker prevents later scans from treating generated runs as source material.

Discovery skips all nested symlinks; an explicitly supplied root may resolve through
one. Output is rejected when it equals or contains the input, and output/manifest
symlinks are rejected. Errors abort instead of writing a partial manifest; explicit
`--overwrite` is required to replace one. Publication is atomic; a write failure
may leave an empty marked output directory, but never a partially written manifest.
Ordinary concurrent content changes are
detected during hashing where possible; discovery is not a filesystem snapshot
and does not defend against a hostile process changing the tree concurrently.

No-clobber publication requires hard-link support on the output filesystem; an
unsupported filesystem produces a visible error rather than a weaker write.

A discovery manifest inventories bytes, not document meaning. A successful scan
does not establish readability, extraction quality, course coverage, or factual
correctness. Supported discovery extensions are defined in configuration.

## Planned processing pipeline

Use a deterministic Python orchestrator to run explicit stages. Specialized LLM
tasks receive bounded inputs, evidence, and validated output schemas; they do not
choose arbitrary actions or determine whether their own work is approved.

The following are **future contracts**, not existing classes or implemented APIs.
Introduce concrete models when each stage is implemented.

| Stage | Responsibility and input → output | Failure policy |
| --- | --- | --- |
| 1. Discovery and ingestion | Course directory → source records, hashes, immutable source snapshots or verified references | Report unreadable or unsupported sources and output conflicts; never imply full coverage after an incomplete scan. |
| 2. Structured extraction | Source record + original bytes → page/span/region blocks, equations, figures, reading order, extraction diagnostics | Retain original pages and uncertain alternatives; route failed or ambiguous regions to another extractor or review. |
| 3. Course knowledge map | Extracted blocks + syllabus/exercise evidence → topics, prerequisites, learning targets, importance rationale | Record competing interpretations and unmapped documents; do not infer absent content as covered. |
| 4. Knowledge extraction | Map + source blocks → normalized claims, definitions, conditions, methods, evidence links | Reject unsupported claims; retain conflicts and uncertain notation for resolution. |
| 5. Candidate generation | Supported knowledge items + style preferences → candidate cards with target, answer, explanation, evidence | Validate structured output; bounded retries for malformed responses; keep rejected candidates and reasons. |
| 6. Independent verification | Candidates + original evidence → factual verdicts, pedagogical verdicts, issues | Check independently of generation; unsupported or uncertain correctness blocks approval. Tool/provider failure is a failed check, not a pass. |
| 7. Deduplication and coverage | Verified candidates + course map → duplicate groups, uncovered targets, audit report | Preserve disputed near-duplicates; distinguish missing knowledge from excluded scope and extraction failures. |
| 8. Targeted revision | Specific issues/gaps + evidence → revised candidates and change history | Reverify changed claims; bound revision loops and escalate unresolved issues. |
| 9. Human review | Uncertain/selected candidates + issues + source view → recorded decisions and edits | Preserve pending state and reviewer rationale; edits invalidate affected checks. |
| 10. Anki export | Approved records + persistent identities + media → package and update report | Validate mathematics/media/IDs, write atomically, and fail safely without modifying an existing collection. |

## Contracts and provenance

Each stage accepts and returns typed, validated records with an explicit schema
version. Keep original content and evidence references available across stages:

- A source record identifies a document, its course-relative location, hash,
  content revision, and extraction status.
- A source location identifies a page and/or text span or image region. Coordinate
  systems and page numbering must be explicit; unknown fields stay unknown.
- Evidence links a knowledge item or card claim to source locations and relevant
  context. Evidence may support a claim, conflict with it, or be insufficient.
- Knowledge items and cards have stable IDs, revision history, and links to their
  learning targets. Persistent Anki note IDs are separate from display wording.
- Verification records identify the check, verdict, issues, evidence inspected,
  model/tool version, and the exact candidate revision checked.
- Model runs record prompt version/hash, model identifier, relevant parameters,
  validated response, usage, and errors. Human decisions have separate status.

Schema evolution must use explicit versions and migration rules. A content hash
detects changes and enables cache reuse; it does not replace persistent identity.
A renamed document and an edited card both need deliberate reconciliation rules.

## Deterministic work and model reasoning

Python should own path safety, hashing, parsing, schema validation, artifact writes,
cache keys, retry limits, state transitions, IDs, and export. Use parsers and
deterministic mathematics checks where they can reliably answer the question.

Models are appropriate for ambiguous layout/handwriting interpretation, semantic
course mapping, evidence-supported knowledge extraction, useful retrieval prompts,
and contextual reviews. Vision may be necessary even when a PDF has a text layer.
Model output is an interpretation requiring validation, never a replacement for
the original source. Independent review must receive evidence and may disagree.

## Artifacts, resumption, and scale

Keep stage outputs, diagnostics, input hashes, and run metadata so a developer can
inspect and rerun a stage independently. Start with readable local artifacts;
consider SQLite when persistent identities, cross-run queries, and transactional
updates require it. Do not introduce storage abstractions before that need exists.

Cache keys must include source revision, stage/schema version, configuration, and
relevant prompt/model/extractor versions. Rerun only affected descendants; manual
edits and new evidence invalidate relevant verification. Reusing a recorded model
response is reproducible; requesting a new response is not guaranteed identical.

For large courses, extract and process bounded document/page groups, then combine
their evidence into course-level analysis. Preserve cross-document links and
diagnostics. Add limited concurrency, checkpoints, and usage reporting after the
small evaluation slice establishes correctness. Never silently drop a failed page
to make a run appear complete.

## Configuration and safety boundaries

Keep application settings, course preferences, prompt templates, model choices,
and pedagogical policy separate. See [configuration](../config/README.md) and
[prompt conventions](../prompts/README.md). No course-specific facts belong in code.

Phase 0 performs no network operations. A future model stage must require explicit
provider configuration and disclose the data sent. Preserve originals; generated
outputs are separate artifacts. Export must have a tested, explicit merge policy
before it can update notes, and must never implicitly delete user material.

## Decisions and questions for later milestones

- **Chosen:** `src/` layout, Typer, Pydantic, TOML, `uv`, pytest, and Ruff; only
  dependencies needed by the implemented feature are installed.
- **Proposed:** PyMuPDF for initial PDF extraction; evaluate Docling against the
  reviewed fixtures before adding it. OpenAI structured outputs and vision are
  candidates for reasoning/handwriting; `genanki` for package export; SQLite for
  durable identities. None is integrated yet.
- **Resolve through evaluation:** layout/region representation, equation fidelity,
  confidence policy, reviewer independence, and minimum human-review thresholds.
- **Resolve before regeneration:** source renames/splits, concept/card identity
  reconciliation, edited-note ownership, deletion policy, and scheduling preservation.
- **Resolve before external calls:** consent UX, retention/redaction policy, model
  capabilities, request budgets, timeout/retry behavior, and provider data handling.

The [roadmap](roadmap.md) orders these decisions around a small tested vertical
slice instead of implementing the full design in advance.
