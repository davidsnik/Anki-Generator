# Shared resource management

Job scheduling and request capacity use separate application settings under `tasks`.
Changes apply to the live scheduler and resource manager; they do not change the
recorded source, model, prompt or generation criteria of an existing job.

| Setting | Default | Range and effect |
| --- | --- | --- |
| `max_concurrent_jobs` | 2 | 1–8 independently running course jobs |
| `api_concurrency` | 4 | 1–16 active physical OpenAI request attempts across the application |
| `per_job_api_concurrency` | 2 | 1–16 active requests per job, also subject to the global limit |
| `per_model_concurrency` | `{}` | Optional model-ID → integer limit, each 1–16 |
| `local_concurrency` | 2 | 1–4 document/crop rendering or symbolic calculation operations |

The per-run `processing.concurrency` setting bounds independent stage workers, and
`processing.api_concurrency` provides an additional frozen per-run API cap. Neither
replaces the application-wide limits. Raising a worker count cannot bypass a lower
shared request limit. Lowering a live limit allows admitted work to finish and
admits further work only when capacity falls below the new limit.

## Admission and fairness

One `GlobalResources` instance belongs to the application runner. Responses,
embeddings, connection tests and model-list requests share its API pool. Production
transport acquires a slot for each physical SDK attempt and releases it before
retry backoff. Explicitly injected test providers receive the same shared admission
at the pipeline boundary; production does not substitute such providers.

Requests wait FIFO within each job and round-robin across eligible jobs. A request
for a model at its configured limit cannot block a different eligible job/model.
Waiting threads hold neither an API slot nor a database transaction. Local document
extraction, selected-region rendering and symbolic subprocesses use a separate pool,
so a parser does not occupy API capacity. HTTP endpoints remain synchronous FastAPI
thread-pool handlers; CPU parsing/calculation runs in the existing bounded child
processes, outside the API event loop.

Upload preparation, ZIP expansion, hashing and source-file fsync also run in an HTTP
worker thread before the short guarded SQLite insert. Cleanup serializes its final
unreferenced-blob check and unlink with reference creation; a prepared upload whose
blob disappeared fails cleanly for retry instead of committing a broken source.

The request pool also bounds expensive request preparation: vision image bytes and
base64 payloads are allocated only after admission, released between retries, and
limited to 12 regions, 20 MiB per image and 64 MiB of raw images per physical request.
Oversized inputs fail with a request to reduce image batch size. Image cache hashes
are streamed. Existing parser limits on file/page/pixel counts, process time and
memory still apply. These are configured bounds, not automatic memory-pressure
measurement or an operating-system-wide resource controller.

## Failures, retries and interruption

The official SDK's internal retries are disabled. The application makes at most
four attempts by default (three retries), with a bounded retry setting of at most
five retries. Network failures, timeouts, HTTP 408/409, rate limits and server errors
are eligible for retries. Authentication, permission, insufficient credit, invalid
configuration, refusals, invalid output and incomplete responses fail immediately.

`retry-after-ms`, numeric `Retry-After` and HTTP-date `Retry-After` are respected.
Delays above 120 seconds fail visibly for later manual retry rather than retrying
earlier than the provider requested. Otherwise absent/invalid delay headers use
exponential backoff with random jitter (0.75–1.25 times the exponential delay,
capped at 30 seconds). An explicit provider `x-should-retry: false` prevents retry.
These headers and bounded behavior follow the installed official SDK's documented
transport handling; this application owns the attempts so shared slots remain free
throughout backoff.

Resource waiting and production backoff check pause/cancel at approximately
200-millisecond boundaries. An already submitted HTTP call may still finish or
reach its configured 180-second timeout. The application does not claim to cancel
that remote work; a successful response is preserved before later interruption.
Retry exhaustion affects its own job. Other eligible jobs can use free capacity
while it waits or fails.

Internally created SDK clients are explicitly closed when a job finishes, pauses
or fails, and after connection/model-list endpoints complete. Injected SDK clients
remain owned by their caller. Pipeline cleanup also releases its provider reference
so job callbacks do not retain completed processing contexts.

Task events persist sanitized resource wait/acquisition and retry/failure details,
including operation, model, attempt count and delay. They contain no API keys,
source contents, raw SDK errors or complete request bodies. Provider token usage is
recorded only when actually returned; failure-event counts are not a fabricated
estimate of provider billing. Shared snapshots expose active/waiting counts per
job/model for diagnostics.

## Verification

`tests/test_global_resources.py` uses real threads and synchronization barriers with
controlled SDK transports. It proves cross-job overlap, queue fairness, limits,
live reconfiguration, cancelled-wait cleanup, separate local capacity, Responses/
embedding admission, independent progress during backoff, Retry-After handling,
interruption and lazy image allocation. `tests/test_resource_api.py` exercises live
settings and settings-provider endpoints against the same manager. The existing
provider suite checks request shapes and permanent/temporary error distinctions.
No paid requests are made by these tests; live provider throughput and account
limits require a separate consented measurement.
