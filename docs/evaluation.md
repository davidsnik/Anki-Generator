# Quality evaluation

Evaluation measures output against declared references and recorded judgments.
It does not infer truth from model agreement. The repository includes a portable
[synthetic benchmark](../fixtures/evaluation/synthetic-probability.json), with
seven learning targets and seven accepted or deliberately flawed examples. All
labels are synthetic; no independent human or real-course accuracy is claimed.

## Evaluate your course

1. Import your sources and inspect local extraction in **Documents**. Correct
   transcription errors and save any required crops before freezing a benchmark.
2. Open **Evaluation** and create a dataset linked to that course. Add the important
   concepts, assumptions, competencies and original source locations. Add good and
   flawed reference cards with rationale. Record source interpretation errors and
   missing concepts as annotations. Declare synthetic, unreviewed or human-reference
   provenance accurately. A human-reference declaration requires a reviewer name.
3. Create a two-variant comparison in the GUI (the API accepts up to eight named
   variants). Each new executed variant
   starts from an isolated archived course copy with the same original documents,
   roles, source corrections and crops. Copies do not overwrite the working course.
   Model runs require your configured key and explicit consent. Production uses
   OpenAI; deterministic injected providers are confined to test code.
4. Change models, reasoning settings, processing settings, generation criteria or
   versioned stage prompt overrides. Runs retain effective settings, prompt hashes,
   source hashes and versions, stage outcomes, usage and errors. No evaluation
   setting disables source or quality gates. Office rendering is environment dependent;
   extraction version/settings are retained, but identical font installation is not
   guaranteed across machines.
5. Review the randomized, paged blind cases against original evidence. Record a
   label, observed quality dimensions, mapped reference targets, rationale and reviewer.
   Mark independence only if you actually checked the source independently. Reveal
   configurations after reviewing. An app declaration cannot authenticate expertise
   or independence.
6. Download the report. Keep a domain-reviewed held-out split and collect multiple
   reviewers before drawing conclusions about university-course quality. A paired
   delta is descriptive evidence, not a statistical significance test.

An existing completed run can instead capture the **current course state at capture**
without model calls. Sources must still match that run, including roles, corrections
and selected regions. Configuration overrides are disallowed for captures. Such a
snapshot may include subsequent human card edits, so it is labeled separately from
an isolated pipeline-output experiment. Freshly executed variants are snapshotted
when their runs complete, before later edits. Source changes during setup abort the
comparison rather than silently pairing different inputs.

## Portable dataset format

The versioned JSON format is validated by
`evaluation/contracts.py:DatasetInput`. Import/export is available in the GUI and
at `POST /api/evaluations/datasets/import` and
`GET /api/evaluations/datasets/{id}/export`.

| Field | Meaning |
| --- | --- |
| `schema_version`, `version` | Format version `"1"` and independently incremented dataset revision |
| `name`, `description`, `course_id` | Dataset identity and optional local source-course binding |
| `provenance`, `reviewer` | `synthetic`, `unreviewed`, or declared `human_reference`; responsible reviewer |
| `sources` | Source hashes, relative paths and optional original locations/metadata; private source bytes are not embedded |
| `reference_concepts` | Unique IDs, labels, topic, kind, importance, assumptions, competencies, source and rationale |
| `reference_cards` | Question/answer, mapped concept IDs, expected label, explicit label origin, dimensions, rationale, sources, reviewer and independence |
| `annotations` | Missing concepts and interpretation errors with expected/actual content and rationale |

Card labels are `correct_useful`, `needs_improvement`, `incorrect`, `ambiguous`,
`redundant` and `not_worth_memorizing`. Dimensions may be true, false or unknown:
factual correctness, mathematical correctness, assumptions, atomicity, attribution,
usefulness and unambiguity. Redundancy judgments depend on the rest of the deck.

Import does not import source documents or invent local document IDs. A nonexistent
local course binding is cleared. Bind the imported dataset explicitly to a course
with the appropriate sources before executing a new comparison. Check original
references after moving between workspaces; annotation source objects are portable
metadata rather than an automatic cross-workspace document-ID resolver.

Judgments are append-only. A later judgment supersedes the same reviewer's earlier
judgment for the same case and origin in metrics; the report retains both events.
Explicit promotion copies genuinely human-labeled cases into a new dataset version;
synthetic/model labels cannot be promoted as human examples. Earlier experiment
references and card snapshots remain immutable.

## What the report establishes

| Measurement | Denominator and interpretation |
| --- | --- |
| Schema and source-location validity | All captured cards; locations must exist in the same course. This does not establish that the cited content supports the answer. |
| Automatic reference coverage | Exact normalized concept-title matches divided by reference targets; an inspection aid with explicit missing targets, not semantic or human truth. |
| Model outcomes | Actual current-revision stage verdicts and reported issue categories, separate from reference judgments. |
| Human/synthetic/model acceptance | `correct_useful` judgments divided by latest judgments of that origin; not all unreviewed cards. |
| Review progress | Distinct reviewed cases divided by all cases in the variant, separately per origin. |
| Quality dimensions | True observations divided by non-null observations for that dimension and origin. Unknown is never counted as correct. |
| Reviewed coverage | Reference targets explicitly mapped by reviewers to useful/needs-improvement cards, separated by origin. |
| Reference-decision agreement | Binary agreement between model `verified` status and reference `correct_useful` acceptance on exact question/answer matches, separated by label origin; not six-label classification or paraphrase matching. |
| Paired comparison | Change in accepted judgments on reference targets reviewed in both variants; incomplete without shared human-reviewed targets. |
| Estimated review burden | Sum of `max(10, 0.8 × answer word count)` seconds; a heuristic, not measured learning time or an Anki schedule. |

The dashboard also shows label distributions, common failures, topic weaknesses,
failed examples and unreviewed counts. Zero observations display **Not measured**.
Multiple reviewers contribute separate judgments, so rates are judgment-weighted;
the report does not currently calculate inter-rater agreement or confidence intervals.

## Regression and live evaluation

Run the deterministic evaluation and pipeline tests without credentials:

    uv run --locked pytest tests/test_evaluation.py tests/test_pipeline_quality.py

The synthetic JSON is suitable for import/export and deliberate-defect regression
checks. Source corrections, omission recovery, semantic candidate retrieval,
mathematical counterexamples, stable identities and actual Anki import have separate
tests described in [testing](testing.md). Synthetic vectors test retrieval plumbing;
they do not validate live embedding quality.

Live evaluation uses the same GUI workflow with real imported sources, a configured
OpenAI key and consent on each executed comparison. No live provider evaluation or
independently human-reviewed corpus was available during this implementation.
Reports identify injected-test versus OpenAI execution. Neither a passing regression
suite nor a synthetic score establishes factual accuracy on a real course.
