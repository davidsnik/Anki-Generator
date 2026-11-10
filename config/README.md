# Configuration

Regular GUI settings are persisted as validated, non-secret SQLite records.
Settings includes stage-specific models, reasoning effort, revision bounds,
generation criteria, role influence, document processing, theme, storage diagnostics
and backup. Courses copy global generation defaults at creation and retain explicit
independent preferences thereafter.

Application configuration is defined in services/settings.py and domain.py.
Extraction limits are validated by ingestion/contracts.py. Provider keys are not
configuration records: use the GUI session store or an available secure OS keyring.
OPENAI_API_KEY is an optional externally supplied alternative; no .env loader is used.
Runs retain effective non-secret settings and source snapshots for reproducibility.

Prompt templates are separate packaged resources. Source role weights influence
importance/understanding, never bypass factual checks. Natural-language course
guidance is constrained by the same evidence and verification policy.

## Standalone discovery

The original inspect command uses built-in TOML-compatible discovery defaults.
config/default.toml documents them and is loaded only when explicitly selected:

    uv run anki-generator inspect fixtures/example-course --output outputs/example --config config/default.toml

Only supported_extensions and excluded_directory_names apply to standalone
discovery. Unknown keys are rejected. Extension recognition does not mean parsing.
The CLI skips nested symlinks, requested/marked output directories and configured
directory names. Existing manifests require --overwrite; output may not equal or
contain input. Identical inputs/exclusions yield identical version-1 JSON.
This TOML does not override graphical-application settings.

Developer benchmark JSON uses `benchmark.contracts.BenchmarkConfig`, separate from
discovery TOML. Keep private source selections, model experiments and annotations
under ignored `data/benchmarks/`; references never enter generation configuration.
See the [developer evaluation workflow](../docs/evaluation.md).
