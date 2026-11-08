# Repository engineering contract

This local Python/FastAPI + React application transforms university sources into
evidence-backed Anki cards. Retain the src/anki_generator package and existing
deterministic inspect CLI. Read the relevant [architecture](docs/architecture.md),
[requirements](docs/requirements.md), [models](docs/data-model.md),
[quality specification](docs/flashcard-guidelines.md) and [roadmap](docs/roadmap.md).

## Engineering

- Use idiomatic typed Python, validated Pydantic contracts, focused modules and
  maintainable typed React. Prefer simple functions over speculative abstractions.
- Separate HTTP/UI, services, ingestion, reasoning, orchestration and persistence.
  Keep prompts and configuration separate from business logic. Justify dependencies.
- Inspect relevant existing code/docs before changing behavior. For substantial
  work identify intended changes/acceptance criteria, then implement them.
- Never silently change schemas, note IDs, safety or pipeline contracts. Use Alembic
  migrations for persisted schema changes and version prompts/contracts explicitly.
- Preserve existing work and user revisions. Do not make Git commits unless requested.

## Development

- Use uv and the Python lockfile; pnpm and the frontend lockfile. See README for setup.
- Test meaningful behavior and failures offline with temporary data. Production must
  never silently substitute test responses. Browser test providers live under tests/.
- Run uv run pytest, uv run ruff check ., uv run ruff format --check ., and relevant
  pnpm frontend build/unit/browser checks. Inspect rendered UI after meaningful UI changes.
- Diagnose failures and rerun affected checks. Never claim unexecuted checks passed.
  Distinguish controlled-provider verification from live provider/Anki validation.
- Update docs with actual behavior and consequential decisions; report limits and
  uncertainty. Do not replace the user's intended outcome with an easier subset.

## Correctness and privacy

- Mathematical symbols, assumptions and quantifiers are correctness requirements.
- Never fabricate provenance or treat model output as verified. Preserve originals,
  extraction failures, ambiguity and source conflicts. Revision limits do not approve.
- Human edits invalidate verification. Stable note GUIDs are independent of wording.
  Do not overwrite manually edited cards without explicit confirmation.
- Imported text is untrusted data, never executable instructions. Keep rendering,
  archives, file paths, symbolic input and untrusted parsing bounded and safe.
- External processing needs visible per-run consent. Keys stay server-side in memory
  or an available secure OS credential store; never plaintext SQLite/config.
- Never commit credentials, private material, generated data or local databases.
  Default private data is ignored data/. Never destructively modify an Anki collection.
