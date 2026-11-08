# Anki Generator

A local Python application being developed to turn university course materials into
accurate, source-backed Anki flashcards. Correctness, mathematical precision,
coverage, and educational value guide the design.

**Phase 0 currently provides local document discovery.** It recursively inventories
supported files and writes a validated JSON manifest. It reads file bytes to compute
hashes; it does not parse documents, interpret mathematics, call an LLM, generate
cards, or export Anki decks.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run these
commands from the repository root:

```sh
uv python install 3.12
uv sync --locked
uv run --locked anki-generator --help
```

The project targets Python 3.12, recorded in `.python-version`, and declares Python
`>=3.12` compatibility. `uv sync --locked` creates `.venv`, installs the package and
development tools, and checks that the committed `uv.lock` matches `pyproject.toml`.
Initial environment setup can download Python and dependencies. The installed CLI
and automated tests run without network access or API credentials.

## Inspect a course

```sh
uv run --locked anki-generator inspect fixtures/example-course --output outputs/example
```

This writes `outputs/example/manifest.json` and a `.anki-generator-output` marker.
The synthetic course contains Markdown lecture notes, plain-text exercises with
solutions, and LaTeX source. See [fixtures/README.md](fixtures/README.md).

To select the example configuration explicitly:

```sh
uv run --locked anki-generator inspect fixtures/example-course --output outputs/example --config config/default.toml --overwrite
```

Existing `manifest.json` files are preserved unless `--overwrite` is supplied.
An empty course produces a valid empty manifest. Invalid paths, unreadable files,
invalid configuration, and unsafe output paths report errors and a nonzero exit
status. Keep the input tree unchanged during an inspection.

Default filename extensions are `.pdf`, `.tex`, `.md`, `.txt`, `.png`, `.jpg`,
`.jpeg`, `.tif`, `.tiff`, `.webp`, `.pptx`, and `.docx`, case-insensitively. These
are discovery categories; recognition of an extension does not validate or parse
its contents. Unsupported files are counted and skipped.

Discovery skips nested file and directory symlinks. It excludes the selected output
directory, directories containing the reserved `.anki-generator-output` marker,
and directory names configured for exclusion. The defaults are `.git`, `.venv`,
`__pycache__`, `output`, `outputs`, and `runs`. The output directory must not equal
or contain the course directory.

Manifest schema version `"1"` records sorted relative POSIX paths, filename types,
byte sizes, SHA-256 hashes, skipped-file counts, and excluded directories. For an
unchanged input tree and configuration, its JSON is deterministic; it contains no
timestamps or absolute source paths. A content hash identifies a byte revision,
not a permanent document or Anki card identity. The validated contract lives in
[models.py](src/anki_generator/models.py).

## Develop

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Apply formatting with `uv run --locked ruff format .`. Tests use synthetic inputs
and temporary output directories. [CI](.github/workflows/ci.yml) runs the checks
and an example CLI invocation on Python 3.12.

Read [AGENTS.md](AGENTS.md) and the relevant contracts before changing behavior.
For a new pipeline stage, define its typed input/output and source provenance,
implement a small working slice, and test success, uncertainty, and failure cases.
Add a module only when that stage is implemented. Keep deterministic operations
separate from model calls and update the documentation alongside the code.

## Data and configuration

Place private course inputs under ignored `data/` and generated results under
ignored `outputs/` or `runs/`. Synthetic fixtures remain version controlled. If you
choose other locations, add appropriate ignore rules yourself before staging
files; inspect `git status` before committing. Manifests contain filenames,
sizes, and hashes and should be treated as user data. Never commit credentials,
private course materials, generated decks, or local databases.

All current processing stays local. Future provider-backed stages will require
explicit configuration and clear disclosure of which content leaves the machine.
`.env.example` documents the current lack of required credentials. No `.env`
loader or provider integration is implemented.

[config/default.toml](config/default.toml) shows the validated discovery settings;
the same defaults apply without `--config`. Future model selection, reasoning
effort, card preferences, verification, and export options will be added only when
their stages exist. [prompts/README.md](prompts/README.md) describes the planned
prompt lifecycle.

## Design and next work

- [Requirements](docs/requirements.md): current scope, future behavior, and data safety.
- [Architecture](docs/architecture.md): typed stages, evidence, persistence, and failures.
- [Flashcard guidelines](docs/flashcard-guidelines.md): mathematical and pedagogical quality.
- [Roadmap](docs/roadmap.md): milestones, evaluation data, and acceptance criteria.

The next milestone is a small PDF extraction slice with page-level provenance,
preserved mathematical and visual context, and explicit extraction failures.
Course knowledge mapping, OpenAI structured outputs, independent verification,
human review, stable Anki identities, and export are planned. Candidate future
tools include PyMuPDF/Docling, vision-capable models, SQLite, and `genanki`; they
are deliberately absent from the initial dependency set.
