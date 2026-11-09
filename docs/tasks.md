# Concurrent tasks

Start generation in one course, then navigate to another and start its generation.
Submission returns immediately after the validated job is persisted. The application
runs two independent course jobs by default; additional jobs remain in SQLite's
queue. Closing or navigating the browser does not stop backend work.

Open **Tasks** in the main navigation or click the running/queued indicator. Filter
history by course, status, job type and date; search course names/task IDs and sort
the paged results. Open a task for its stage pipeline, recorded configuration,
source versions, counters, usage, warnings, errors, event history and output links.
Actual stage counts are shown instead of a speculative overall percentage. New
tasks record their own generated, reused and verified card counters, retaining
those results after later course edits. Legacy tasks without these records show
unknown counters. Current course card/concept totals appear separately as context.

## Scheduling and resources

One dispatcher in the owning backend process admits bounded worker threads. Each
worker executes the existing deterministic pipeline with a private run context.
There is no external queue service. Short `BEGIN IMMEDIATE` transactions claim jobs
and update controls. SQLite WAL permits simultaneous readers and serializes short
writes. No API call, resource wait or document parser runs inside a claim transaction.

Settings has separate application-wide task limits:

| Limit | Default |
| --- | ---: |
| Simultaneously executing course jobs | 2 |
| Physical OpenAI requests across all jobs | 4 |
| Requests from one job | 2 |
| Local extraction/crop/calculation operations | 2 |

Optional per-model request caps and the existing frozen per-run stage/request caps
also apply. See [resource management](resource-management.md) for exact bounds,
fair admission, physical-attempt retries, Retry-After handling and memory limits.
Changing live capacity lets admitted work finish; lowering a limit does not kill
ongoing jobs. Recorded source/model/prompt/generation settings remain unchanged.

Equal-priority queued jobs enter FIFO order. Queued priority can be changed from
the dashboard, within -100 to 100. After 30 minutes waiting, jobs enter an older
FIFO group ahead of newer priorities, preventing continuous urgent submissions
from starving old work. Queue position reflects this policy; it is not an estimated
start time. Paused/retried jobs re-enter the queue with a new queue-entry timestamp.
A same-course job whose predecessor is still executing waits until that course is
available; other eligible courses may proceed.

## Ownership, snapshots and duplicate submissions

Only one backend process may own a data directory. The instance lock is acquired
before migrations or restore recovery. Within that process, in-memory reservations
and atomic database claims enforce the job cap. A partial unique SQLite index
also prevents two executing jobs for the same course. Each job uses separate
run artifacts; shared original blobs are immutable and caches remain course-scoped.

Normal submissions reject another queued/running job for the same course. Internal
bulk revision requests may prepare multiple same-course tasks, which execute
sequentially. Client-generated idempotency keys make a retried submission return
the existing task; reusing a key with different request data is rejected. Concurrent
submissions are serialized only for the short creation/check transaction.

Jobs snapshot source identities/hashes/roles/links, correction/crop revisions,
criteria, models, prompts, extraction settings and course name/description/language.
Changing course preferences or application generation defaults affects future jobs.
Original source mutations and card content edits in an actively processing course
remain guarded; other courses can be imported, edited, reviewed and exported.
Stale sources are rejected rather than mixed with recorded evidence on resume.

## States and controls

| State | Meaning and controls |
| --- | --- |
| Prepared | Internal staged submission, not admitted until its enclosing operation commits; may be cancelled |
| Queued | Persistent wait for job/course capacity; pause, cancel or change priority |
| Running | Executing pipeline; request pause or cancellation |
| Pausing / cancelling | No new work should start after safe checkpoints; in-flight calls may finish and save valid responses |
| Paused | All work has drained; resume from valid checkpoints or cancel |
| Cancelled | This attempt will not continue; valid partial artifacts remain available |
| Completed | Pipeline and any evaluation snapshot committed; results are available independently |
| Failed | An isolated error stopped this task; inspect safe diagnostics, retry or cancel |
| Interrupted / recovering | Startup detects unfinished prior ownership and retains valid work before settling paused/cancelled |

Controls operate on one job and use validated state transitions. Pause/cancel does
not claim to cancel a remote OpenAI request. Terminal paused/cancelled state is
published after in-flight work drains. Backups/restoration reject active processing.
The application retains database ownership if shutdown cannot confirm worker exit.

## Recovery and observability

Queued jobs remain queued after restart. Previously executing tasks are recovered
to paused with their checkpoints and an explanation; accepted cancellation is
settled cancelled. Resume explicitly after inspecting inputs. Restored backups
pause pending jobs so restored consent never silently starts external processing.
Successful responses are saved before checkpoint publication and reused on retry.
A crash after provider completion but before saving its response can still require
repeating that request; exactly-once billing is not guaranteed.

Elapsed time excludes queue and paused intervals for tasks created with this
scheduler. Recovery closes the known active interval at the last durable update;
unknown crash/offline time is not presented as measured processing. Legacy history
does not contain these active intervals and explicitly labels its wall-time fallback.
Usage and cost are shown only when actually
returned or supported by the dated estimate; missing usage is not a zero-cost claim.

The GUI polls bounded read models, retains the last known data on connection loss,
and refreshes on reconnect/focus and cross-tab mutations. Initial loading does not
become a global blocker during generation. Notifications describe observed state
changes and link to tasks; no desktop notification permission is required. Event
pages persist state, stage and sanitized resource diagnostics, without credentials
or source request bodies. The latest 100 jobs remain available through the legacy
course-processing endpoint; older history is accessible through paged Tasks APIs.

## Verification

The scheduler tests use real dispatch threads and deterministic provider barriers,
not sleeps as proof of overlap. They check capacity, FIFO/priority/aging,
same-course exclusion, failure/control isolation, persistence, checkpoint recovery,
stable configuration and course-specific outputs. Task API tests race identical and
conflicting submissions and check bounded history/events and migration safety.
Resource tests cover real physical-call admission and backoff. Browser tests start
multiple synthetic courses and inspect genuine simultaneous backend work, responsive
navigation, independent completion, review and export without paid API calls.

See [testing](testing.md) and the dated [verification report](verification.md) for
executed commands/results. These tests establish scheduling and integration behavior,
not live model accuracy, provider account throughput or cross-process execution.
