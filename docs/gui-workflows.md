# Evidence and review workflows

The local application keeps course sources, extraction, corrections, cards, reviews
and evaluation records separately. A model verdict is not an independent human label.

## Get started and choose models

Create a course and import files or a folder. Suggested educational roles remain
editable; select several documents in the source library to apply a role together.
Local extraction, source inspection, manual cards and export work without a key.
Generation first checks for documents, a configured key and a usable model setup,
then requires the existing external-processing consent.

Settings discovers the account's models automatically after key setup. Search the
**Default processing model** selector to choose one model for all six stages, or
expand **Choose different models by stage** to retain separate choices. Use
**Refresh models** to bypass the account-list cache and **Check model setup** to
check a draft before saving. Custom identifiers remain available under Advanced;
unknown capabilities are reported explicitly. See [model discovery](models.md).

Study presets and Quiet/Balanced/More parallel work cover common preferences.
Extraction limits, prompts and other technical controls remain under advanced
sections. Settings keeps unsaved drafts when switching pages; the save bar and
`Ctrl`/`⌘` + `S` save them. Background updates do not replace a draft. API-key
storage and connection testing have separate feedback from preference saving.

## Correct a transcription or select visual evidence

Open a course's **Documents** tab and choose **Correct or crop** on a source.
The same workbench is available from a card's source inspector. Select a page,
compare the untouched original with the effective transcription, edit the text and
mathematical notation, enter a rationale, then save. Mark the transcription as
independently checked only after checking its original evidence. Replacing a
previously verified correction requires a separate replacement checkbox. Original
extraction and correction history remain available.

Use **Select region** and drag a rectangle over the original page. Zoom changes
presentation; the saved bounds remain in original page coordinates. **Pan** and
scrolling allow inspection of wide or tall pages. Choose a readable image-quality
preset, or expand advanced crop settings for DPI and exact geometry. Save the crop,
then attach it to a card or concept. Card attachment creates a new human revision
and invalidates earlier checks. The workbench supports local extraction of the
selected page or vision interpretation of the page/crop; vision requires visible
consent. Preserved human corrections are not replaced by default. Sources without
faithful original rendering cannot provide a genuine crop; the server reports this
limitation instead of manufacturing a source image.
Closing the workbench or changing pages asks before discarding an unsaved
transcription correction. Saved corrections remain in history.

## Review a large card collection

Search questions, answers or tags, or filter by topic, original document, card
type, human review state and verification outcome. The **Needs attention** filter
includes unresolved verification and pending review. Lists are paged on the server;
selecting a displayed page adds only its explicit card IDs and opened revisions.
Selections can span pages. Bulk approval, rejection, attention flags, tags, topic
changes and regeneration all show the selected count and require a rationale.
The backend rejects stale selections. External regeneration additionally requires
consent, and replacing human edits has its own explicit permission.

Quick filters expose all cards, awaiting review, needs attention and approved
cards. **Clear filters** also recovers from an empty search. Filter, search and
view choices remain separate for each course for the browser/window session;
explicit bulk selections are not restored. The inspector shows position and
disables navigation at the ends. Card edits ask before discarding a changed draft;
`Ctrl`/`⌘` + `Enter` saves a valid card.

In the card inspector use `←` / `→` for previous/next, `Space` or `f` to flip,
`a` to approve, `r` to reject, `e` to edit, `g` to regenerate, `x` to select and
`s` to inspect original evidence. Shortcuts pause while typing and during nested
confirmation dialogs. Study view supports flip, previous/next and edit. Study
view is a local preview; Anki handles actual spaced repetition after import.

**Compare previous revisions** shows question, answer, explanation, tags and source
differences. Restoring an earlier snapshot creates a new revision, preserves its
stable Anki note identity, and requires fresh verification/review.

## Inspect coverage and processing

The knowledge map displays extracted concepts and card counts. Its independent
source-grounded audit lists paged learning targets, their original evidence,
mapped concepts and covering verified cards. Filter target kind/state to inspect
omissions and unresolved mappings. Missing targets are not silently counted as
covered.

Processing retains run history and stage checkpoints. Failed runs can retry saved
work. **Retry this stage** creates a targeted run from its prior configuration and
valid unrelated work, subject to source freshness and human-edit protection. Model
stages require fresh consent. Individual document and failed-upload retries leave
successful unrelated imports available.

Settings expose bounded workers/API concurrency, context/output budgets, source
chunks, vision and embedding batches, coverage repair rounds and identity
thresholds. Advanced per-stage prompt overrides affect new runs after saving.
Each run retains its effective configuration for reproducibility.

## Developer evaluation

Benchmarks, research annotations, model comparisons and performance reports run
through the CLI, outside this interface. Ordinary card review and source correction
remain available here. The earlier research route is retired; existing evaluation
records remain in application backups for compatibility. See the
[developer evaluation guide](evaluation.md).

## Check identity and export safely

The Exports tab compares selected notes against the prior export's immutable
snapshot: new, matching, modified, uncertain, missing and duplicate categories.
Inspect all pending identity decisions, including concept proposals outside the
current export selection. Reconcile actual candidates as matches, new targets,
splits or merges with a rationale. Replacing reviewed content requires explicit
permission. Unresolved identity conflicts block Anki export. Missing notes are
reported; the application never deletes notes from an Anki collection.

Use the all-course selection for eligible approved notes, or turn it off and select
specific cards across pages. Anki export retains stable GUIDs; actual Anki update
and scheduling behavior depends on the user's import options and Anki version.
JSON/CSV are inspection exports, not a complete application backup.

## Back up and restore

Settings can download an application backup containing sources, revisions and
evidence; API keys are excluded. **Validate & restore backup** uploads a ZIP and
shows compatibility, record counts and warnings before any restoration. Choose a
clean-state restore or explicit replacement of the current application state,
then type `RESTORE`. Replacement retains a recovery archive. Active jobs must
be stopped; archive paths, schema and integrity are checked by the backend. Restore
does not merge two application databases or modify an Anki collection.

## Run independent courses together

Start generation from a course and approve its visible external-processing
consent. Submission immediately saves a task with its source and configuration
snapshot. The confirmation offers **View task** and leaves you in the course;
you can open another course and submit its task. Repeated retries of the same
open submission dialog retain one idempotency key. The backend rejects a
conflicting task for the same course.

Open **Tasks** from the main navigation or the header's running/queued indicator.
The default allows two course tasks, four shared OpenAI requests, two local
operations and two OpenAI requests per task. Settings → **Processing speed** offers
presets; **Customize shared resource limits** changes those independent limits, with optional per-model
caps. Save preferences to apply them; lowering a limit drains existing work
rather than terminating requests. Per-pipeline worker and context settings remain
additional constraints. Changes to models and course criteria affect future
submissions, while each existing task keeps its recorded configuration.

The task list pages 24 records and filters by course, status, job type, date range
and course-name/task-ID search. Sort by newest, oldest or priority. Running and
queued tasks have distinct states; queued tasks show saved queue position and
priority controls. Higher priority requests an earlier position, subject to
scheduler fairness and capacity. Open a task for its pipeline, actual stage work,
configuration, paged event history, warnings, usage and current-course output
links. Per-task extraction/generation/verification counters are separate from
current-course inventory totals. Historical tasks without a recorded counter show
an unknown value; elapsed processing excludes queue and paused time when recorded
by the current scheduler. No completion percentage or finish estimate is inferred.

Pause, resume, cancel or retry only the selected task when its current state
permits the action. Cancellation requires confirmation. A pause or cancellation
request stops future scheduling at safe boundaries; an OpenAI request already in
flight may finish and save its response. Other courses continue independently.
A completed course's cards can be inspected, reviewed and exported while another
course is still processing. Course headers and overview cards link directly to
their current task; the course Processing tab retains its recent history and links
to the complete paged task history.

Task summaries refresh about every 1.5 seconds with active work and every five
seconds when idle. Focus, reconnection and cross-tab messages request fresh
server state. A disconnected view explicitly labels its last known state and
keeps cached content available; reconnect or reload reconciles against persistent
backend records. Notifications describe confirmed transitions, link to the task
and deduplicate across tabs instead of replaying old task completions on startup.
See [tasks.md](tasks.md) for scheduler, resource and restart-recovery details.
