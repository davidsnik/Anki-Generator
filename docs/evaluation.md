# Developer evaluation and private benchmark workflow

Benchmarks, model comparisons and research annotations are developer tools. They
run without Electron, a web server or the normal GUI. Source correction and card
review remain ordinary application features. The former research screen has been
removed; its database/API records remain readable for compatibility and backups.

The benchmark package reuses production ingestion, the durable runner, source
validation, mathematical checks and retrieval. It does not implement a second
flashcard pipeline. No benchmark command makes a paid request by default.

## Private datasets and reproducibility

```sh
make benchmark
make benchmark ARGS='inventory /path/to/course-materials.zip --output data/benchmarks/inventory.json --extract-to data/benchmarks/originals'
make benchmark ARGS='profile data/benchmarks/inventory.json --output data/benchmarks/profile.json'
```

Inventory streams every member through SHA-256, validates all paths/links,
duplicates, encryption and expansion bounds before staged extraction, and never
executes notebooks, scripts or other unsupported files. Originals are unchanged.
Course grouping and role hints inferred from paths remain explicitly unconfirmed.
Exercise/solution relationships are conservative filename candidates, including
possible questions and answers in the same file; each candidate remains
unconfirmed until original-source review establishes the relationship.
The developer streaming limit accommodates larger archives than the GUI's bounded
upload batch; it does not relax the GUI's memory limits.

Profile uses bounded child processes to inspect all PDF page geometry and sample
first/middle/last native-text counters. Zero native text plus drawing paths is an
observed characteristic, not a proven handwriting diagnosis. Content sampling is
recorded; sampled counters must not be described as all-page transcription results.

Private archives, extracted documents, configurations, annotations and results
belong under ignored `data/benchmarks/`. Root ZIP archives are ignored too. Only
schemas, developer code and synthetic fixtures belong in Git. Application payload
allowlists do not include these private directories.

## Workload configuration

Create a JSON configuration using the `BenchmarkConfig` schema in
`src/anki_generator/benchmark/contracts.py`. Source IDs come from the manifest:

```json
{
  "schema_version": "1",
  "name": "Course section fidelity",
  "execution": "local_extract",
  "workloads": [{
    "id": "section",
    "name": "Selected source section",
    "samples": [{
      "source_id": "SOURCE_ID_FROM_MANIFEST",
      "page_numbers": [1, 2],
      "split": "development",
      "stratum": "ordinary_digital",
      "rationale": "Predeclared ordinary pages, alongside separate difficult cases"
    }]
  }]
}
```

Use `page_numbers: null` for complete documents. Record purposive difficult-case
sampling separately from representative selection and held-out cases; neither a
small sample nor overlapping workloads supports population-wide accuracy claims.
The validated `extraction` field accepts production extraction options. The
`pipeline` field accepts existing model, reasoning, criteria, processing and prompt
settings. Reference answers and annotations are forbidden configuration fields.

Execution modes:

| Mode | What executes | Repetitions and limits |
| --- | --- | --- |
| `local_extract` | Production bounded parser on selected pages; original-coordinate visual regions and native text | One pass; no credential lookup or provider calls |
| `local_pipeline` | Production source import, durable extraction jobs and caches, with no generation/vision | Complete files; `repetitions: 2` measures cold then unchanged-workspace reuse |
| `live_pipeline` | Production generation and verification through the official SDK | Complete files; requires configured key plus both `--live` and `--consent` |

```sh
make benchmark ARGS='run data/benchmarks/inventory.json --config data/benchmarks/config.json --output data/benchmarks/runs'
```

Each attempt creates a unique directory. Earlier attempts, including failures, are
not overwritten. Results retain the frozen source manifest, selected pages/splits,
configuration, source/prompt/harness hashes, Git revision and dirty-state metadata,
exact production-source and harness snapshots, workload diagnostics and artifacts.
A source-hash mismatch fails the workload instead of silently creating a new
baseline. Runtime imports are checked against the requested implementation.

An archived baseline can be selected with `--implementation-root /path/to/source`.
It must contain `src/anki_generator`; preserve its commit provenance when making a
`git archive` snapshot. The same harness can then measure old and new production
code on identical files. Run performance comparisons sequentially on the same
host; record external load, repetitions and environmental differences.

## Offline references and human annotation

```sh
make benchmark ARGS='review-export data/benchmarks/runs/RUN/result.json --output data/benchmarks/review'
make benchmark-report ARGS='data/benchmarks/runs/RUN/result.json --output data/benchmarks/report.md'
```

The review package includes source IDs/hashes/pages, every original-coordinate tile
with its bounding box, frozen cards/concepts and a pending JSON annotation template.
Blind export hides configuration labels. Inspect original evidence and fill only
judgments actually made. A named human reviewer must explicitly attest completed
human judgments; model or deterministic labels cannot claim human validation.

Annotations bind to the exact run, dataset, case content and source hashes. Coverage
mappings also bind to the normalized reference-inventory hash; changing target
statements or assumptions requires a new reviewed mapping. Annotations
support correctness/assumptions, clarity/atomicity/usefulness, notation/support,
coverage, error categories/severity, retrieval relevance, reference transcription,
actual editing/regeneration actions and observed active review seconds. Leave
unknown dimensions, unavailable timing and unreviewed cases pending. A timestamp
or answer length is not observed human effort.

```sh
make benchmark ARGS='annotations-validate data/benchmarks/runs/RUN/result.json data/benchmarks/review/annotations.json'
make benchmark ARGS='annotations-validate data/benchmarks/runs/RUN/result.json annotations.json --import-to data/benchmarks/labels-v2.json --existing data/benchmarks/labels-v1.json'
make benchmark-report ARGS='data/benchmarks/runs/RUN/result.json --annotations data/benchmarks/labels-v2.json --output data/benchmarks/reviewed-report.md'
```

Imports are append-only; corrections supersede earlier event IDs rather than
mutating them. All observed human activity events remain available for effort
accounting, while quality rates use current judgments. These declarations record
provenance but cannot authenticate reviewer expertise or independence.

Independent expected targets use `ReferenceInventory` with dataset ID/hash,
origin/method, completeness, concepts, assumptions, exercise competencies and
original source references. Add them only to reporting/review commands using
`--references path.json`, including annotation validation, retrieval and comparison.
They never enter generation requests. A model's separate visual reading remains
provisional model evidence; matching a possibly incorrect student solution is
source agreement, not mathematical proof.

Portable example cards can also use the existing `evaluation.DatasetInput`
contract, validated with
`make benchmark ARGS='reference-validate data/benchmarks/reference-examples.json'`.
Keep provisional examples `unreviewed`, retain their model origin and unknown
quality dimensions, and explain any expected-label schema limitation in their
annotations. Schema validity never promotes examples to academic ground truth.

## Metrics and comparisons

Reports separate four evidence levels: deterministic structural/calculation checks,
model judgments, independently source-grounded judgments, and human validation.
Independence is orthogonal to label origin. Never combine these into one accuracy
percentage. Missing labels remain missing, with explicit denominators.

Quality rates include accepted unchanged, editing/rejection, dimensions and error
categories. Descriptive Wilson intervals do not correct selection bias or dependent
cards/reviewers. Coverage uses independently supplied reference targets, separately
by reference origin and mapping-judgment origin; generated concepts do not supply
a gold denominator. Incomplete reference inventories are labeled incomplete.

Literal character/word edit rates require reference transcriptions and do not
establish mathematical equivalence. Retrieval precision uses explicit hit labels;
recall requires a declared complete relevant set. Unjudged hits/queries remain
visible. Cosine scores and model confidence are not relevance truth. Original-page
retrieval and semantic duplicate/identity candidates are different tasks.

```sh
make benchmark ARGS='retrieval RUN/result.json --annotations labels.json --output data/benchmarks/retrieval.json'
make benchmark ARGS='compare BASE/result.json NEW/result.json --output data/benchmarks/comparison.md'
```

Comparison requires the same dataset revision, execution mode and selected
workloads/pages/splits. Settings/model changes remain recorded. Cases pair only
with matching IDs and original source references. Model-declared target identity
is not human-confirmed semantic equivalence; unmatched outputs remain unpaired.
Quality deltas require comparable judgments in both runs, not just more cards.

## Performance and live experiments

Optional production telemetry is enabled with
`DurableRunner(..., profiler_factory=lambda run_id: PipelineMeasurements())`.
It records pipeline phases, source retrieval, API attempts/retries, cache activity,
observed usage and symbolic work. Inclusive wall spans can overlap; initiating-thread
CPU excludes other threads and parser children. Process RSS is a high-water mark,
not instantaneous total memory. Fresh parser wall/CPU/RSS and PDF render timings
are measured in bounded children; cached artifacts do not replay those costs.
Failed/retried attempts retain separate snapshots. Unknown usage and prices remain
null; a known-price subtotal is not complete billing.

To compare models, run separately named configurations with identical frozen
inputs, varying any of the six stage-model settings, reasoning or prompt overrides,
then use the same independent references/criteria and comparison command. Live
execution is opt-in:

```sh
make benchmark ARGS='run inventory.json --config live-config.json --output data/benchmarks/live --live --consent'
```

This transmits selected source text/images and embeddings and may incur charges.
The worker bounds physical pipeline attempts and elapsed time **per workload**;
total allowed attempts can be the configured bound times the workload count.
Metadata preflight is separate. Quota/permission/errors and unknown capabilities still apply. Saved
responses support diagnosis; exactly-once remote billing is not guaranteed. Never
record credentials in experiment files. The current real-course validation pass
was explicitly restricted to offline experiments, so no live model comparison,
card-quality percentage or observed human review time is claimed.

`make benchmark-smoke` verifies the CLI with synthetic text and real local parsing.
`make benchmark-engineering ARGS='--output data/benchmarks/engineering.json'`
measures authored mathematical-domain controls and historical-vector cache behavior.
These are engineering regressions, not real-course semantic accuracy. Ordinary
`make test`/CI remain offline. Historical evaluation APIs/datasets stay available
for compatibility; their previous GUI and heuristic review-time estimates are not
used as human evidence in these developer reports.

See [testing](testing.md), [mathematical boundaries](mathematical-verification.md),
[ingestion](ingestion.md), [performance](performance.md) and the dated
[verification record](verification.md).
