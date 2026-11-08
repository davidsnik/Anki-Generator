# Configuration

Phase 0 uses TOML, read with Python's standard-library `tomllib` and validated with
Pydantic. This avoids a YAML dependency and keeps supported settings explicit.
Only discovery settings are implemented. [default.toml](default.toml) documents
the built-in defaults, including supported extensions and excluded directory names.
Recognizing an extension does not provide a parser for that format.

The CLI uses built-in defaults unless a file is explicitly supplied:

```sh
uv run anki-generator inspect fixtures/example-course --output /tmp/anki-inspect \
  --config config/default.toml
```

There is no automatic loading from the repository or course directory. A supplied
file may override either discovery setting; omitted settings keep their defaults.
Unknown sections/keys and invalid values are rejected. The supported shape is:

```toml
[discovery]
supported_extensions = [".pdf", ".md", ".txt"]
excluded_directory_names = [".git", ".venv", "__pycache__", "output", "outputs", "runs"]
```

Configured extensions are unique lowercase suffixes with a leading dot; filename
matching is case-insensitive. Directory exclusions are names, not paths; they apply
recursively. The requested output directory and
directories marked with `.anki-generator-output` are also excluded independently
of this setting. All nested symlinks are skipped. A user-selected input root may
resolve through a symlink; output directories and manifests must not be symlinks.

Configuration affects file selection, not document content interpretation. Keep
reproducible application configuration under version control; keep private course
paths, preferences containing private data, and credentials in ignored local files.
No API key or external service is required for the initial CLI. The JSON manifest
has no timestamps or absolute source paths; identical tree contents, settings, and
exclusions produce identical output bytes. Existing manifests require the explicit
`--overwrite` flag, even when a valid output directory already exists.

## Future separation

Add settings only alongside behavior that consumes and tests them. General
application configuration will define processing policies, resource limits, model
selection and reasoning effort, verification requirements, and export behavior.
Course-specific preferences will define scope, learning level, terminology,
language, card styles, and explanation depth. Define and document precedence before
introducing overlapping configuration layers.

Provider secrets belong in environment variables or another explicit local secret
mechanism, never committed TOML or prompts. Prompt templates live in `prompts/`;
business rules live in application code. Future runs must preserve the effective
non-secret settings and relevant versions so outputs can be audited and resumed.

Changing settings that affect an artifact must invalidate that artifact's cache.
External processing must make clear which material is sent to the configured
provider. See [requirements](../docs/requirements.md) for the privacy contract and
[architecture](../docs/architecture.md) for stage boundaries.
