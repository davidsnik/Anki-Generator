# Processing and quality methodology

A persisted run snapshots document identities, hashes, roles, authority, exercise/solution links, course criteria, model IDs, and prompt versions. The local worker uses SQLite rather than request-scoped background tasks. Original imports remain unchanged.

The implemented sequence is:

1. Extract and render each unchanged document locally. Cache identity includes its SHA-256, extractor version, and every extraction option. Failures remain explicit; one failed document does not conceal readable material or count as complete coverage.
2. Interpret every suspicious visual region with the selected OpenAI interpretation model. Tall pages remain overlapping regions with original page coordinates. Uncertain symbols/transcriptions remain uncertain. Interpretation results are distinct from deterministic extraction and originals.
3. Analyze bounded document sections and visual regions according to their educational role. Exercise analyses retain concepts, techniques, prerequisites, reasoning, transferable strategies, pitfalls, and sources. Student notes/solutions are not assumed correct.
4. Consolidate these inventories into a hierarchical course map. Large inventories use intermediate consolidations that retain assumptions and references. Stable concept UUIDs derive from semantic keys; existing title/kind matches retain identity when terminology changes. Invalid or cyclic hierarchies fail visibly.
5. Generate cards from mapped learning targets, original source excerpts, exercise analysis, and configurable criteria. Card quantity follows learning targets rather than quotas. Basic and cloze cards may include referenced source images. Topic exclusions include descendants.
6. Independently review factual support, pedagogy, and mathematical correctness in separate calls. Factual/mathematical reviewers receive original source excerpts and original visual evidence, with bounded image batches covering every referenced visual region. A generator's confidence never establishes correctness.
7. Use bounded symbolic checks for suitable polynomial/rational equalities. A restricted Python AST constructs SymPy expressions without `eval`, `sympify(string)`, `parse_expr`, attributes, arbitrary functions, or imported code. Equality checks do not prove domains, theorem hypotheses, or general mathematical correctness. Unsupported checks remain uncertain.
8. Revise actionable defects, then repeat independent reviews, up to the configured finite limit. Exhausting the limit never promotes a card. A refusal, missing quotation, uncertain transcription, unresolved source conflict, or rejected check remains visible.
9. Retrieve possible duplicates using concept overlap and word-set similarity; ask a separate semantic comparison to distinguish actual redundant recall targets from useful distinctions. Duplicate proposals require an existing retrieved card ID. Human-approved/edited cards are preserved.
10. Audit actual verified card targets and their explicit concept mappings against the complete eligible inventory and source-role coverage. Deterministically unmapped concepts remain gaps regardless of the model's assessment. A bounded targeted generation pass addresses genuine gaps and repeats review/deduplication/audit. Unresolved document regions prevent complete coverage.

`verified` means the automated checks passed. Human review remains a separate persisted decision. Cards awaiting review, rejected cards, unresolved checks, and semantic duplicates are not automatically made export-ready. The export interface states its selection policy.

## Traceability and identity

Every non-topic concept and candidate requires a supporting quotation and real document/page identity. The application validates quotations against preserved text or visual interpretations, validates regions and page bounds, and adds spatial boxes only where actual extracted blocks or regions establish them. Visual interpretations are model-produced claims; independent reviewers can inspect the original images. Uncertain interpretation cannot become verified evidence through model agreement.

Reviewer text is copied directly from the original extraction around supporting quotations. Character ranges point into the complete stored page text; original pages remain available for wider context. Evidence is never replaced with a generating model's summary.

Generated card UUIDs derive from the course, stable mapped concept UUIDs, and a semantic learning-target key, never question wording. Anki note UUIDs derive from the persistent card UUID. Wording revisions retain note identity. Concept splits, merges, or intentionally new learning targets can produce new identities; existing human edits and decisions are preserved unless replacement is explicitly confirmed. Old revisions remain inspectable.

## Checkpoints, cache invalidation, and recovery

Each completed model result is atomically saved before the SQLite checkpoint is committed. Cache identity includes the original payload, image bytes, full prompt text, structured-output schema, requested model, reasoning effort, and output budget. Per-run checkpoints preserve the frozen retrieval/prompt input when resuming, even if subsequent stages have created new cards. Completed candidate checkpoints prevent older draft revisions from replaying after interruption.

Unchanged extraction and per-document understanding can be reused when card criteria change. Source/role/authority/link changes invalidate the corresponding understanding inputs. A paused/failed run refuses to resume against changed source snapshots; start a new run for those inputs. Existing cards are not bulk-deleted by regeneration.

The single local worker processes a persistent SQLite queue. Pause and cancel take effect at the next safe document/model/card checkpoint; a provider call already in flight may finish and its result is saved. On startup, an interrupted `running` job becomes `paused` with an explanation and may resume from saved results. Retry preserves successful earlier calls and revisions. The launcher runs one backend worker; distributed/multi-process job ownership is outside this local architecture.

There is an unavoidable provider boundary: if the process dies after OpenAI finishes a request but before its response is saved, that single request may need to be repeated. There is no claim of exactly-once external billing.

## OpenAI configuration and privacy

Production always uses the official backend OpenAI Python SDK, Responses API, and Pydantic structured outputs. No fake provider is substituted when credentials are missing. Deterministic providers exist only under `tests/`.

The UI requires informed run consent before sending source excerpts and rendered regions. Local extraction needs no external consent or key. `store=False` is sent on Responses requests. This setting does not replace OpenAI's applicable account retention policy. Local sources, transcriptions, prompts/results, and checkpoints remain in the application's private data directory and are included in project backup; credentials are excluded.

The default `gpt-6-astra` capability declaration (image input, structured outputs, and reasoning efforts) was checked against [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra) on 2026-11-08. Unknown account models receive no guessed reasoning or temperature parameters. The GUI connection test makes a small real structured Responses request against the selected model; the account model list alone is not a capability guarantee. Vision compatibility is checked when image requests are made. Configuration failures are actionable rather than silently switching models.

Transient network, timeout, rate-limit, and server failures use bounded exponential retries. Authentication, billing-credit, permission, invalid configuration, refusal, malformed structured output, and incomplete responses fail visibly and preserve earlier checkpoints. SDK exception messages and keys are not stored in run errors.

Usage records input/output/total token counts for new calls and separate cache hits. Published Standard text-token prices yield clearly labeled estimates only for the verified default model and recognized tiers; unknown prices remain unavailable. Estimates are distinct from provider billing and link to their dated source. The [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) documents the SDK interface and refusal/incomplete response cases.

No live paid OpenAI request is part of the automated test suite. Automated tests use controlled structured responses to exercise the real local extraction, orchestration, quality decisions, revision, coverage, persistence, and export integration.
