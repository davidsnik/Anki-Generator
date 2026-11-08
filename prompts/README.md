# Prompt templates

Production templates are versioned, packaged resources under
src/anki_generator/prompts/. They cover visual interpretation, document knowledge,
course consolidation, generation, factual/pedagogical/mathematical review,
deduplication, coverage and revision. PROMPT_VERSION in processing/contracts.py
identifies the contract version; cache keys also include exact template contents.

Each call uses a Pydantic structured output through the official Responses SDK.
Source content is untrusted data. Evidence IDs/quotes/geometry are checked against
actual inputs; model confidence never substitutes for evidence. Separate review
calls use original text/visual context, not just the generator's summary.

Keep provider/model/reasoning choices and course preferences in settings. Preserve
responses, schema/prompt/model metadata, usage and failures for audit/replay.
Test template changes against controlled fixtures and held-out reviewed cases;
evaluate factual precision, assumptions, uncertainty, redundancy and coverage.
Use offline recorded/synthetic providers in regression tests; live evaluation is
explicit and reports usage. Never put private material, credentials or run transcripts
in the template directory. See [processing](../docs/processing.md) and
[quality requirements](../docs/flashcard-guidelines.md).
