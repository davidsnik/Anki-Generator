# Real disposable Anki integration

The optional `anki-integration` extra pins the official **Anki 26.09.4 core**
(PyPI normalizes the version to `26.9.4`). It contains the same Python/Rust collection,
importer and scheduler backend used by desktop Anki, without requiring the desktop
GUI. Production installation does not require it. The supported collection/package
API is documented in the [official module guide](https://github.com/ankitects/anki/blob/main/docs-site/addons/the-anki-module.mdx).

Run the integration suite:

    uv sync --locked --extra anki-integration
    uv run --locked --extra anki-integration pytest tests/integration/test_anki_roundtrip.py -q

Without the extra, pytest skips the integration module explicitly. With the pinned
extra installed, these tests exercise the real backend; no simulated importer or
mock scheduling implementation is substituted. Platform wheels require supported
Anki/Python/operating-system combinations. Dependency installation needs internet;
the tests themselves run locally and require neither AnkiWeb nor an OpenAI key.

Every test creates a new collection beneath pytest's temporary directory and closes
it afterward. The application also uses temporary storage. Tests never discover,
open or modify an existing user profile, collection, AnkiConnect server or sync
account. No paid provider request occurs.

## Executed compatibility cases

On Linux, the 11-case suite passed against Anki 26.09.4 with generated basic/cloze
notes and PNG media. Tested cases:

| Scenario | Actual observed result |
| --- | --- |
| Empty collection import | Two expected notes/cards, both note types, source fields, MathJax text and matching PNG bytes imported |
| Import identical package twice | Note/card counts and identifiers retained; no new duplicate notes |
| Edit app question and export in the same wall-clock second | `IfNewer` imports the changed field; note/card IDs retained |
| Add an app note | Exactly the additional note/card appears; existing identities remain |
| Archive/omit an app note from a later package | Existing Anki note/card remains; omission does not delete Anki content |
| Manually edit a note through Anki's API | Unchanged application re-export preserves the local wording with `IfNewer` and `Never`; `Always` replaces it when modification times differ |
| Review through the actual scheduler, then update that note | Review-log rows, card/note/deck IDs, queue/type, due, interval, ease, repetitions, lapses and remaining steps survive; tested with learning-progress import both off and on |
| Change tags | Imported replacement tag set matches the application's new tag set |
| Change explanation and mathematics | Fields update under `Always`; existing media bytes remain correct |

These are actual backend import/scheduler results, not package-structure inspection
alone. They cover unchanged note types and card templates. Desktop visual rendering,
other Anki versions, mobile importers, changed note-type schemas, cloze restructuring,
and unusual deck settings remain separate compatibility work.

## Update policy and timestamps

The exporter now persists a modification time for each exported note/content
revision. Unchanged content reuses its previous timestamp; a changed revision
advances it, including changes made within the same wall-clock second. Stable GUIDs
and unchanged model IDs provide matching, while stable content timestamps prevent a
later unchanged rebuild from claiming that all app notes were edited.

Anki's import settings still determine which existing note wins. `IfNewer` compares
modification times; `Never` preserves existing note contents; `Always` permits
replacement even by an older incoming version. In the tested core, equal timestamps
also skip an `Always` note update, as implemented in Anki's
[package importer](https://github.com/ankitects/anki/blob/main/rslib/src/import_export/package/apkg/import/notes.rs).
Monotonic same-second app revisions can be slightly ahead of the wall clock; they
do not provide a conflict resolver for simultaneous independent Anki edits.

A genuinely changed application note may replace an Anki-local change under
`IfNewer` if the incoming version is newer. `Always` can overwrite manual edits.
The application cannot inspect an arbitrary external collection through package
creation, and therefore cannot promise preservation of every manual edit or study
state under every setting. Review the export preview and keep a collection backup.
Anki's [package import documentation](https://docs.ankiweb.net/manual/importing/packaged-decks)
explains the update and learning-progress settings.

## Optional desktop confirmation

For visual checks, create a new disposable profile in desktop Anki before importing
synthetic exports. Confirm that this profile contains no personal notes and do not
sign it into AnkiWeb. Import a package, inspect both basic/cloze notes, equations and
images, review one card, then repeat imports after changing a question, tags,
explanation and card selection in a separate synthetic application course. Compare
counts and review history; exercise `IfNewer`, `Never` and `Always` deliberately.
Remove only that disposable profile afterward. These desktop steps were not run in
the current environment; the automated Python/Rust integration above was executed.
