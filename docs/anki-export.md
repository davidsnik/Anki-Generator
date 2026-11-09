# Anki export and update behavior

The application creates genuine genanki .apkg packages and records each export.
It does not connect to Anki or modify its collection. JSON/CSV exports are available
for inspection/backup and may include unapproved cards; CSV formula triggers are escaped.

## Eligibility and fields

APKG includes human-approved, nonarchived notes with no failed/rejected/duplicate
quality status. Explicit selection cannot bypass the gate. A human-approved manual
card can export with a recorded unverified override. Unresolved identity proposals
block affected notes until explicitly reconciled. Missing required media/source
records, invalid cloze syntax, empty basic answers and unsafe field separators fail
the export with a diagnostic rather than silently dropping data.

Basic and cloze note types use stable versioned model IDs and consistent fields:
question/text, answer, optional explanation, source references, concept ID and card
identity. Text HTML is escaped, newlines preserved, and inline/display mathematics
uses Anki MathJax delimiters. Original referenced image tiles are copied into the
package under content-addressed names. They are ordinary image cards, not image occlusion.

## Identity and regeneration

Each stored card has a persistent note GUID independent of its question text.
Edits and repeated exports reuse that GUID, model IDs and the course-derived deck
ID. Cloze deletions can create multiple Anki cards from one note, so changing
deletion numbers or note type can affect card identity even when the note GUID stays.

Anki's importer matches existing notes by identity and note-type compatibility.
Keep the application note type, use the same collection, and inspect the importer's
update-existing-notes options. Review Anki's change summary before accepting updates.
Changing note type, cloze structure, GUIDs or import options can produce different
results. Scheduling behavior varies by Anki version and import settings; preservation
of all review history is not guaranteed. Back up the collection before importing.

Persistent semantic aliases and source/neural candidate reconciliation distinguish
stable targets from wording. Uncertain matches and deliberate splits/merges are
stored proposals. The GUI requires a rationale for new/match/split/merge decisions;
replacing an existing human-edited/reviewed target additionally requires explicit
permission. Matching preserves the prior note GUID, retains content history,
archives the extra candidate and requires fresh review. Similarity alone never
authorizes replacement.

The export preview compares current selection with the latest immutable export
snapshot and shows complete new, matching, modified, uncertain, missing and duplicate
counts with paged details. All pending course identities can be inspected separately,
including concepts outside the current selection. JSON/CSV remain useful for
inspection while Anki identity conflicts are unresolved.

Each APKG snapshot records the note's content hash and modification time. An
unchanged note keeps its previous modification time rather than appearing edited
whenever the package is rebuilt. A genuinely changed note advances monotonically,
including changes within the same wall-clock second. This supports `IfNewer`
updates but is not a conflict resolver for simultaneous application/Anki edits.

Importing a later smaller package does not delete notes absent from that package.
Deleting/rejecting a card in the application is not a command to remove it from Anki.
No implicit collection deletion, synchronization or AnkiConnect integration exists.

## Executed real Anki compatibility

Package tests inspect ZIP entries, collection.anki2 tables, notes/cards, templates,
tags, mathematical text, media and stable GUIDs. In addition, the optional official
Anki **26.09.4** core suite actually imported generated packages into disposable
Linux collections and exercised the real scheduler; all eleven cases passed.

| Tested setting/scenario | Observed result |
| --- | --- |
| New and identical repeated basic/cloze package imports | Expected notes/cards and PNG bytes; repeated import retained note/card IDs without duplicates |
| Same-second app edit, `IfNewer` | Changed question updated, with stable note/card identities |
| Added or omitted application note | New note added; omitted/archived note was not deleted from Anki |
| Anki-local edit, unchanged app re-export | `IfNewer` and `Never` preserved the local wording; `Always` replaced it when times differed |
| Actual scheduler review followed by note update | Tested card scheduling fields and review-log rows survived with learning-progress import both off and on |
| Changed tags, explanation and mathematics | Fields/tag set updated under `Always`; expected PNG media remained correct |

The tests use `merge_notetypes=False`, `update_notetypes=IfNewer` and unchanged
templates. In this core, equal note timestamps also skip an `Always` update.
Changed application content may overwrite an Anki-local edit when the chosen policy
and timestamps allow it. No universal preservation guarantee follows from these cases.

Desktop visual rendering, other Anki versions/mobile importers, changed note-type
schemas, changed cloze deletion structure and unusual deck configurations remain
separate validation. See [Anki integration](anki-integration.md) for executable
commands and exact scope. Tests never open a personal Anki profile, use AnkiWeb or
give the production application permission to modify an existing collection.
