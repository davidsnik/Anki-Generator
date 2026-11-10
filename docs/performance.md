# Measured local engineering workloads

Measured on 2026-11-09 in the implementation container using
`uv run python tests/performance_workloads.py --output /tmp/performance.json`.
The [machine-readable report](benchmarks/performance-2026-11-09.json) contains
per-stage measured API-unit durations, request/cache counters, SQL statement
counts, memory observations and recovery details. Timings are one observation per
profile, not latency guarantees. All sources are generated synthetic fixtures.

The workload runs real isolated local extraction, SQLite persistence, bounded
parallel processing, context checks and neural-retrieval plumbing with an
**explicitly injected deterministic test provider**. Its vectors are simulated;
these numbers establish engineering behavior, not live semantic quality or API
latency. Token counts are simulated and no provider cost can be inferred.

| Profile | Documents / pages | Cold seconds | Cached seconds | New successful response calls cold / cached | Cached response artifacts | Peak RSS MiB* |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| small | 3 / 3 | 2.44 | 0.25 | 17 / 0 | 10 | 131.1 |
| medium | 24 / 24 | 16.77 | 1.03 | 61 / 0 | 54 | 133.0 |
| large | 100 / 100 | 61.70 | 4.17 | 223 / 0 | 216 | 139.0 |
| many_short | 200 / 200 | 130.27 | 8.79 | 435 / 0 | 428 | 144.8 |
| mathematics_visual | 3 / 12 | 4.14 | 1.64 | 111 / 0 | 104 | 149.2 |
| restart_recovery | 24 / 24 | 23.83 | 1.01 | 61 / 0 | 54 | 149.5 |

*RSS is the process cumulative high-water mark; later rows are not isolated
per-workload peaks. The PDF workload contains original vector diagrams and four
mathematical pages per document, requiring real rendering/visual-region plumbing.
The text workloads deliberately use repeated short source targets to stress
per-document extraction and consolidation. They do not model a whole diverse
university course's unknown number of unique concepts or resulting card count.

The repeated run reuses unchanged extraction, understanding, synthesis,
independent source inspection and review artifacts. The final cached runs made no
new simulated provider calls. Complete-response checkpoints and content hashes
are reused; no claim is made about provider requests whose process dies before
saving a response.

The recovery workload injects a failure during independent review, creates a fresh
runner against the same database/artifacts, and resumes the failed attempt. The
report records the successful checkpoints before interruption and calls before
and after recovery. Failed requests have no response usage to aggregate; the
provider fixture's attempt count therefore exceeds successful-response counters.
Separate pytest cases cover actual worker shutdown while waiting on a maintenance
lock, restarting the persistent queue, concurrency limits, pause/cancel, stale
sources, and card-revision preservation.

## Large card collections and retrieval memory

The collection profiles insert actual SQLite card rows, select a 25-card page,
and build/query the actual NumPy cosine index using seeded random vectors.
Random vectors measure runtime/memory only; they are not semantic representations
and are never used as a production substitute.

| Cards | Build + 100 retrieval queries seconds | Matrix bytes | 25-card SQL page seconds |
| --- | ---: | ---: | ---: |
| 1000 | 0.0163 | 512000 | 0.0024 |
| 10000 | 0.7879 | 5120000 | 0.0076 |

These profiles use 128-dimensional vectors for a compact reproducible timing case.
Production's default 512 dimensions uses approximately four times the matrix
storage at the same collection size. Retrieval is linear per query and pairwise
verifications are capped by the configured candidate count. There is no dense
all-pairs similarity allocation. Export preview returns bounded detail pages and
complete counts, but computes its classification over the selected collection;
very large selections still require memory proportional to that collection.

The optional real neural/LLM comparison command and its synthetic reference labels
are documented in [semantic retrieval](semantic-retrieval.md). It has not been run
with a paid key in this session. Independent human acceptance, live accuracy and
latency/cost on real courses remain separate evaluation results, not conclusions
from these controlled engineering profiles.

## Real private-course extraction — 9 November 2026

Actual offline production runs use three complete supplied course collections,
with a fresh isolated application workspace for each revision. Each cold run is
followed by one unchanged-workspace repeat. These are single serial same-host
observations, not distributions or statistically supported speed claims; operating
system file caches were already warm. No API, vision or generation executed.

| Supplied collection | Documents / pages | Baseline cold / repeat seconds | Improved cold / repeat seconds |
| --- | ---: | ---: | ---: |
| Analysis I | 6 / 29 | 7.568 / 0.591 | 7.807 / 0.652 |
| Transistor Circuits | 9 / 44 | 9.348 / 0.682 | 9.660 / 0.961 |
| Markov processes | 9 / 79 | 19.248 / 1.284 | 19.425 / 1.313 |

All twelve durable jobs completed across the two revisions. The improved telemetry
records 24 cold extraction misses and 24 repeat hits, with no fresh parser reports
on repeat. This validates cache reuse, without claiming a new extraction speedup.
Improved isolated workload-parent peaks were 132.65, 134.23 and 186.04 MiB;
maximum waited-child peaks were 166.55, 124.50 and 199.00 MiB. These separate peaks
must not be added into simultaneous memory consumption.

A distinct purposive fidelity workload processes 14 PDFs plus both original raster
images: 100 page/image cases and 240 visual regions. Baseline/current native text
and region geometry match on 100/100 cases. Wall time was 22.366/22.593 seconds;
current measured PDF rendering consumed 10.197 seconds, parser CPU 18.181 seconds
and maximum waited-child RSS 226.33 MiB. The baseline has no parser-internal timing
instrumentation, so that component remains unmeasured. Four deliberately selected
partial documents retain partial coverage; extraction success is not source
completeness or transcription accuracy.

All these offline workloads made zero API requests, consumed zero model tokens
and incurred zero API cost. They provide no live-model latency/cost estimate,
generated-card quality rate, semantic relevance score or observed human review
effort. Private configurations, raw results, machine-readable metrics, comparisons
and the full report remain under ignored `data/benchmarks/`; corrected fidelity
configuration v3 records the development poster honestly rather than calling it
held out. Workloads overlap and their page counts are not independent samples.

## Optional pipeline instrumentation

Developer benchmark runs can inject a `PipelineMeasurements` recorder through
`DurableRunner(..., profiler_factory=...)`. Ordinary application runs leave this
disabled. The recorder adds no background sampler, external calls or GUI controls;
it aggregates numeric observations without source text, filenames, API keys,
request bodies or raw provider errors. Import and export services can use the same
recorder context from developer tools without launching Electron.

`create_export(..., measurements=recorder)` optionally records a format-specific
export span and successful export/card counts. Approval, verification, identity and
media checks still run normally. A rejected export records a failed span without
counting cards as exported or bypassing the human-approval gate. This hook is
disabled by default and adds no application interface.

Measured operations include extraction, interpretation, knowledge extraction and
consolidation, original-source excerpt/image selection, cosine index construction
and search, generation, factual/mathematical/pedagogical response units, bounded
symbolic calculations, deduplication, coverage and regeneration. Cache activity is
recorded separately for extraction, response artifacts, checkpoints and exact
semantic-vector revisions. Existing durable job progress/card counts accompany
these measurements; generated, machine-verified and human-approved counts retain
their distinct meanings.

`Run.metrics.developer_measurements` contains the latest execution snapshot.
`developer_measurement_attempts` preserves each snapshot across failures and retries
instead of replacing the original measurements. These developer aggregates are
separate from the existing successful-response `Run.usage` and persisted stage
windows. Their scopes are explicit:

| Observation | Actual scope and limitation |
| --- | --- |
| Wall spans | Inclusive elapsed intervals; nested or concurrent span sums are not total runtime. The enclosing pipeline span is measured separately. |
| Span CPU | Initiating thread only; excludes other stage threads and child processes. |
| Parent process CPU/RSS | Shared Python process; CPU includes concurrent jobs, and RSS is a cumulative lifetime high-water mark. Neither is a per-stage or isolated job peak. |
| Parser worker wall/CPU | Extraction interval inside the spawned parser, excluding process bootstrap and result publication. Lazy imports during extraction are included. CPU excludes external conversion child processes. The parent parser span includes admission, spawning and artifact publication. |
| Parser worker RSS | Individual worker lifetime peak, including its imports. The maximum across workers is not simultaneous process-tree memory. Unsupported platforms leave it unmeasured. |
| PDF rendering | Actual `get_pixmap` and PNG-save elapsed time, plus completed region count; separate from native text/layout extraction. |
| SDK attempts | Client invocations after preparation, including failed invocations. They do not establish remote acceptance or billed request counts. Retry/backoff and resource waits are separate counters. |
| Tokens | Usage returned with valid responses, never estimated from source lengths. Missing fields remain null; partial observed sums include missing-field counts. Failed or otherwise unreturned usage remains unknown. |
| Cost | A subtotal for responses with a documented supported price schedule; unpriced response counts prevent treating it as a complete bill. |

Fresh parser measurements are stored in the extraction result and aggregated only
when parsing actually runs. A cache hit retains the earlier artifact without
replaying its worker duration, CPU or memory as newly executed work. Older extraction
artifacts remain readable with measurements absent. Failed workers without a
measurement result remain unmeasured; failure does not imply zero resource usage.

Original-source excerpt/image selection is a location-based operation. Cosine
retrieval proposes semantic candidates. Timings and candidate counts for either
operation do not measure relevance, Recall@k or Precision@k. Those require separate
reference judgments; no live embedding or human relevance quality is inferred from
the offline instrumentation.

Developer experiments can additionally attach a bounded `RetrievalCapture` through
`PipelineMeasurements(retrieval_observer=capture)`. The production semantic index
then emits actual ordered candidate IDs and cosine scores for deduplication,
identity reconciliation, source-target matching and target coverage. Query/run IDs,
stage and repetition retain their context; vectors, source text, credentials and
relevance judgments are not captured by this observer. Traces belong in private
experiment artifacts, separately from the numeric telemetry. Limits report dropped
queries and truncated hit lists, and observer failure visibly fails the opted-in
experiment with a numeric failure counter rather than silently omitting evidence.

The benchmark worker binds captured card/concept IDs and per-run source targets
to portable source hashes where available. Attached Card/Concept objects are
context from the final course state after the repetitions, rather than immutable
query-time wording snapshots. An opaque `candidate:<digest>` identity query may
have no persisted object; its query remains unresolved and ineligible for paired
comparison. The worker preserves the real IDs and ranking instead of inventing a
replacement query. Source-audit targets remain model-produced context, not human
reference truth. Every captured ranking starts with relevance pending, so neither
its score nor its source binding supplies a relevance label. Extraction-only
experiments make no semantic searches and correctly retain an empty retrieval
list. Older implementations without the hook likewise provide no observed
rankings; they must not be assigned simulated retrieval-quality results.

## Paired revision-cache measurements

The 2026-11-09 code audit found that every semantic cache lookup loaded all stored
vector revisions for the course/object type/model/dimension, then discarded stale
revisions in Python. The production query now selects only the requested
`(object_id, text_hash)` pairs in batches of 250, using the existing persisted
identity and cache contract. Historical revisions remain available for reuse when
a correction is reverted; no migration or destructive cache pruning is involved.

The same developer collector ran against an untouched baseline source snapshot
and the improved package. Each workload requested 100 unchanged 64-dimensional
vectors from actual temporary SQLite databases, with five timed queries per
configuration. Database construction is outside the timed interval. The rows below
measure query execution and JSON/vector decoding, not embedding quality.

| Stored history per object | Stored vectors | Decoded rows per query, baseline → improved | Mean query milliseconds, baseline → improved |
| --- | ---: | ---: | ---: |
| No historical revisions | 100 | 100 → 100 | 2.005 → 1.924 |
| 50 historical revisions | 5,100 | 5,100 → 100 | 113.363 → 1.914 |

The revision-heavy control used approximately 1/59 of the baseline query time in
these five local observations, with identical returned vectors and zero embedding calls
in both implementations. The row-decoding reduction is structural evidence of the
fix; timing differences are descriptive and depend on machine load and caches.
They do not establish end-to-end course speed, real API latency, cost savings or
semantic retrieval quality.

The Git-ignored paired outputs are
`data/benchmarks/engineering/baseline-2026-11-09.json` and
`data/benchmarks/engineering/improved-2026-11-09.json`. They preserve production
source hashes, each trial, actual decoded-row counts and configuration. The same
collector also records the
[bounded-calculus domain controls](mathematical-verification.md#measured-domain-boundary-regression-controls).
Run a new offline profile with
`make benchmark-engineering ARGS='--output data/benchmarks/engineering/new-profile.json'`.
The direct Python file entry point also permits an untouched baseline package on
`PYTHONPATH` to be measured with the identical collector. Existing output files
are never overwritten.
