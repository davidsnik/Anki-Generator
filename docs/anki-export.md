# Anki export and update behavior

The application creates genuine genanki .apkg packages and records each export.
It does not connect to Anki or modify its collection. JSON/CSV exports are available
for inspection/backup and may include unapproved cards; CSV formula triggers are escaped.

## Eligibility and fields

APKG includes human-approved, nonarchived notes with no failed/rejected/duplicate
quality status. Explicit selection cannot bypass the gate. A human-approved manual
card can export with a recorded unverified override. Missing required media/source
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

Importing a later smaller package does not delete notes absent from that package.
Deleting/rejecting a card in the application is not a command to remove it from Anki.
No implicit collection deletion, synchronization or AnkiConnect integration exists.

Package tests inspect ZIP entries, collection.anki2 tables, notes/cards, templates,
tags, mathematical text, media, and stable GUIDs across edited/repeated exports.
These structural tests do not claim a live Anki import was performed.
