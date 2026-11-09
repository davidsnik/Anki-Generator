# Semantic candidates and persistent identities

Production uses OpenAI `text-embedding-3-small` neural embeddings (512 dimensions
by default), through the official Python SDK. `text-embedding-3-large` is also
selectable. No word-overlap substitute is labeled semantic. Requests include the
complete target statement, question/answer and explicit assumptions. Irreducibly
oversized targets fail rather than losing hypotheses. The external-processing
consent covers these representations as well as excerpts and images.

Vectors are versioned by course, object type/ID, exact representation hash, model
and dimensions. The local NumPy index performs normalized cosine retrieval and
retains at most the configured candidate count. It stores an `n × dimensions`
matrix, not an `n × n` similarity matrix. Retrieval is linear per query; this is a
local application, not a distributed approximate-neighbor service. Repeated
retrieval avoids repeated embedding API calls when representations are unchanged.

Similarity supplies candidates, not an equivalence verdict. A separate structured
LLM comparison evaluates the actual recall target, assumptions, quantifier order,
procedural vs theoretical competence and useful distinctions. A returned duplicate
must name a supplied candidate. Human-edited/approved cards remain preserved.

Concept/card identities reconcile against persistent aliases, source-page overlap
and neural candidates. Exact unchanged targets reuse their stored IDs. A changed
key/wording can retain the old ID only after a separate equivalence review,
preserved assumptions, sufficient similarity, a sufficient nearest-candidate
margin and source/related-concept support. These thresholds are heuristics, not
calibrated correctness probabilities. Splits, merges and uncertain matches create
persisted identity proposals. Pending proposals block APKG export of affected
cards; JSON/CSV remain available for inspection.

The identity screen records explicit new, match, split or merge decisions and a
rationale. Matching a candidate into a previous card preserves the previous GUID,
archives the extra candidate, retains revisions and creates a new pending-review
revision. Replacing a human-edited or reviewed previous card requires explicit
confirmation. No live Anki collection is modified by this action.

Export preview compares stable GUIDs and content hashes with the latest immutable
export snapshot. It reports complete new/matching/modified/uncertain/missing/
duplicate counts and paginated details. Missing notes are information only: an
export does not delete them from Anki. APKG snapshots also retain each note's
modification timestamp. Unchanged content keeps its previous timestamp; changed
content advances monotonically, including exports made within the same second.
This avoids presenting an unchanged package as a newer application edit.

## Reproducible checks

`fixtures/semantic/cases.json` distinguishes low-word-overlap paraphrases from
changed assumptions, reversed conditional probabilities, quantifier order,
assumption vs conclusion and procedure vs theorem. The labels are explicitly
**author-created synthetic references**, not independent human judgments.

Offline pytest exercises real vector retrieval mechanics with injected vectors,
then checks the separate verification/identity/export decisions. It does not
establish the quality of OpenAI's neural representation. The opt-in command

```sh
uv run python tests/semantic_benchmark.py --live --consent --output /tmp/semantic.json
```

uses `OPENAI_API_KEY` only in process memory, performs real embedding and separate
Responses calls, and saves per-case decisions, cosine values, actual usage and
reference-agreement denominators. It has not been run in this implementation
session; no live semantic accuracy result is claimed. The small synthetic set
cannot replace the application's independent human evaluation datasets.

The SDK interface and input limits follow the
[official embedding reference](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)
and [embedding guide](https://developers.openai.com/api/docs/guides/embeddings).
