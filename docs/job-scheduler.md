# Concurrent durable job scheduling

One local scheduler thread admits independent course jobs from SQLite. Each
admitted job runs its complete existing `CoursePipeline` in its own worker thread,
with its own model/configuration context and course-scoped artifacts. Two jobs are
admitted by default. This is actual concurrent backend execution, independent of
the bounded stage workers inside each job. No Redis, Celery or external worker
service is required.

`ApplicationSettings.tasks.max_concurrent_jobs` controls admissions live. Increasing
it admits waiting eligible jobs; decreasing it lets already running jobs drain.
It does not cancel or restart them. Both the background dispatcher and synchronous
`run_now` use the same capacity and course-exclusion checks. SQLite
`BEGIN IMMEDIATE` protects the short admission transaction, and a partial unique
index prevents two executing states for one course. Additional authorized jobs
for that course wait sequentially while other courses may use available capacity.

The queue persists priority and queue-entry time. Priority wins for newly queued
jobs; ties use FIFO and a stable ID tiebreaker. Jobs waiting at least 30 minutes
are admitted ahead of newer jobs, FIFO within that aged group, to prevent a stream
of new high-priority submissions from starving older work. Resume/retry re-enters
the queue at the current time. Startup preserves the existing order of queued jobs.

## Execution and maintenance boundaries

`runner._run_lock` is a short admission/maintenance gate, not a lock around the
whole pipeline. Backup and restoration first reject queued/prepared/executing jobs
and acquire this gate. No pipeline API call, resource wait or parser work holds
it. Thread reservations and per-course ownership are protected separately; they
also cover synchronous test/tool execution, so it cannot bypass job limits.

Application-wide resource limits are separate from job admissions. The shared
resource manager limits physical OpenAI attempts, optional model capacities,
per-job API usage and local subprocess work. Its eligible-job rotation prevents
one job from filling every waiting request position. Provider backoff releases a
physical-request slot; it does not hold a global resource while sleeping. Stage
worker counts and request settings recorded for a run remain separate from these
live application-wide budgets.

No database transaction remains open while waiting for an API call or local
parser. Progress/cache writes are short, and SQLite retains WAL/busy-timeout
configuration. The supported deployment is one application process per private
data directory, enforced by the existing launcher ownership lock; this is not a
distributed worker system.

Course input mutations immediately reject an already visible queued/executing job.
Otherwise they acquire SQLite's writer, recheck for active jobs and retain the
writer through the edit's commit. Submissions and claims
use the same writer boundary: an earlier edit is included in the submitted source
snapshot, while an earlier submission causes the waiting edit to be rejected.
The guard uses a no-op course update, so it also works inside an existing writer
transaction without changing course timestamps. Upload preparation and source
image rendering happen before this short guarded transaction.

## States, controls and recovery

Transitions are validated centrally in `orchestration/job_states.py`. Active work
uses `running`, `pausing` and `cancelling`; prepared evaluation variants are held
until their metadata is committed. Completed, failed, paused and cancelled jobs
remain inspectable with their exact configuration, checkpoints and state events.

Pause/cancel records the requested intermediate state immediately and stops new
units at checkpoints. A submitted provider call or parser may still finish.
Responses are saved before interruption propagates. The runner publishes `paused`
or `cancelled` only after the pipeline's bounded executors have drained every
in-flight unit. Until then the job retains its course reservation, active state and
maintenance protection. An individual failure or control never sets the scheduler's
application shutdown flag and does not stop unrelated jobs.

Successful completion, the final active-time interval and any evaluation case
snapshot are committed atomically. The evaluation snapshot lock precedes the
SQLite write transaction. A capture failure rolls back completion; concurrent
edits cannot enter between the completed status and the immutable result capture.
A pause/cancel accepted before this final write is also honored at that boundary.

Startup detects abandoned running, pausing, cancelling, interrupted or recovering
rows. It preserves completed work, records a recovery event/count, and pauses
interrupted work for explicit resumption; an already requested cancellation
becomes cancelled. Queued jobs remain eligible for normal automatic scheduling.
Active elapsed time excludes queue/paused intervals. After an unclean restart,
the last known active interval ends at the last durable update rather than counting
unknown offline time as processing. Active elapsed time includes resource waits
and provider backoff; it is wall time, not CPU time.

Shutdown stops new admissions, signals safe pause and joins the dispatcher and
workers. If an in-flight operation outlives the bounded shutdown wait, shutdown
raises an explicit error and storage remains unavailable for replacement. A new
worker is never silently substituted while an old one still owns the data.

Existing checkpoint guarantees remain unchanged: no exactly-once external billing
claim is made when a process dies after a provider accepts a request but before its
response is saved. Stale document/correction/crop snapshots are rejected on resume.

## Verification

`tests/test_concurrent_jobs.py` executes the real scheduler, native extraction,
pipeline, SQLite writes and controlled provider responses. Synchronization barriers
prove overlap without relying on speed assumptions. Cases cover:

- two course jobs active while a third queues, then automatic slot reuse;
- course/config/source/card isolation and synchronous admission enforcement;
- same-course sequencing without blocking independent courses;
- priority, FIFO, aging and live increases/decreases in job capacity;
- authentication, invalid-response, timeout and rate-limit failure isolation;
- individual pause/cancel and checkpoint-preserving resume;
- a single global API slot shared across two real job pipelines;
- startup state recovery and reuse of an actual saved provider result;
- active-time accounting and rejected terminal-state controls;
- pending pause/cancel with a second physical request still in flight, including
  explicit backup/restore rejection until that request finishes.

The existing pipeline, evaluation and restore regression suites also run against
this scheduler. Controlled provider tests establish concurrency and recovery wiring;
they are not paid API runs or a measurement of model accuracy.
`tests/test_job_mutation_races.py` uses real concurrent SQLite transactions to
verify both orderings of the guarded edit/submission boundary and the exact
correction fingerprint captured by the submitted job.
