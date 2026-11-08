# Repository engineering contract

This local Python application will turn university course materials into accurate,
source-supported Anki flashcards. Phase 0 implements deterministic file discovery,
not document parsing or generation. Use `anki_generator` for the package and
`anki-generator` for the CLI.

Read the relevant [requirements](docs/requirements.md),
[architecture](docs/architecture.md), [card guidelines](docs/flashcard-guidelines.md),
and [roadmap](docs/roadmap.md) before changing their contracts.

## Engineering conventions

- Write readable, idiomatic, typed Python with focused modules and validated data
  contracts. Prefer simple functions and standard-library tools over frameworks,
  speculative abstractions, empty modules, or unnecessary dependencies.
- Follow the existing `src/` layout and naming. Justify new dependencies against
  implemented behavior. Keep deterministic logic separate from model reasoning.
- Do not silently change serialized schemas, identity rules, safety policies, or
  architectural contracts; update their version/documentation and relevant tests.
- Keep prompts, configuration, course preferences, and business logic separate.

## Workflow

- Inspect relevant code and documents first. For substantial work, identify the
  intended changes and observable acceptance criteria, then implement them.
- Add or update tests for meaningful behavior changes. Tests must run without
  credentials, paid calls, or network access; use temporary output directories.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run ruff format --check .`
  as appropriate. Run relevant CLI smoke checks after CLI/configuration changes.
  Diagnose failures and rerun affected checks; never claim an unexecuted check passed.
- Update documentation when behavior or decisions change. Report consequential
  assumptions, remaining limitations, and unverified behavior.
- Preserve existing work. Do not make Git commits unless explicitly requested.

## Correctness and data safety

- Mathematical notation, assumptions, and quantifiers are part of correctness.
- Never fabricate provenance or treat model-generated content as verified.
  Preserve uncertainty, conflicting evidence, extraction failures, and originals.
- Do not send course material to external services unexpectedly. External model
  stages require explicit configuration and visible data-handling behavior.
- Never commit credentials, private course documents, generated user artifacts,
  local databases, or decks. Keep synthetic fixtures reproducible and tracked.
- Avoid destructive actions against Anki collections. Persistent identities and
  scheduling require an explicit, tested regeneration policy.
