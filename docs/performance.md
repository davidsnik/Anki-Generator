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
