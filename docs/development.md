# Development commands

Use the root Makefile for everyday work. It delegates desktop assembly and process
management to the existing focused scripts; browser mode and the inspect CLI remain
available. Commands run from the repository root.

```sh
make doctor
make setup
make dev
```

`make dev` opens the desktop window with React hot reload. Python changes need
**Settings → Restart processing service**. Stop with the normal window controls or
Ctrl+C; active work keeps the existing checkpoint and confirmation rules. Add
`ARGS=--devtools` to inspect the source renderer. A busy port 5173 is reported
instead of attaching to someone else's development server.

## Tools and Fedora setup

Install GNU Make, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Node.js 24 LTS (or 22.13+) and pnpm 11.19.0. Python dependencies use `uv.lock`;
frontend and desktop dependencies use their frozen pnpm lockfiles. uv obtains
Python 3.12, so no global Python package installation is needed.

On Fedora, `sudo dnf install make rpm-build` supplies Make and the optional RPM
builder. The graphical runtime uses GTK3, NSS, ALSA, libsecret, X11/Wayland libraries
and xdg-utils; packaged RPMs declare them. LibreOffice and bubblewrap are optional
for isolated Office rendering. Native Office extraction remains usable without
them. `make doctor` reports missing tools separately from optional runtime features;
`make doctor ARGS=--package` also requires `rpmbuild`.

Tool paths can be overridden without editing scripts:

```sh
make UV=/path/to/uv PNPM=/path/to/pnpm NODE=/path/to/node setup
```

The helpers add the selected executables' directories to child-process `PATH`,
including Electron Builder's internal `pnpm` calls. Use the usual executable names
(`uv`, `pnpm`, `node`) in those directories. Standard uv controls such as `UV_PYTHON`
and `UV_CACHE_DIR` remain available. No developer-specific absolute path is part of
the build.

## Everyday targets

| Command | Behavior |
| --- | --- |
| `make` / `make help` | List commands and descriptions. |
| `make setup` | Synchronize locked Python, frontend and Electron dependencies. |
| `make setup-browser` | Synchronize only Python/frontend dependencies. |
| `make dev` | Desktop development with frontend hot reload. |
| `make dev-browser` | Browser development with Python/Vite live reload. |
| `make build-web` | Type-check/build React, then copy production assets into the Python package. |
| `make build` | Run checks and build the complete unpacked desktop app, without RPM/FUSE requirements. |
| `make run` | Start `dist/desktop/linux-unpacked/anki-generator`; asks for a build if absent. |
| `make run-browser` | Start the production browser interface, building it if needed. |
| `make test` | Python, frontend and desktop-shell unit tests. |
| `make lint` | Python lint and shell syntax checks. |
| `make typecheck` | Strict TypeScript checking without build output. |
| `make format-check` | Check Python, frontend and desktop-shell formatting. |
| `make format` | Apply those formatters. |
| `make check` | Lint, formatting, TypeScript and all unit tests; source files are not rewritten. |
| `make package` | Check/build the frozen backend and produce AppImage + Fedora RPM. |
| `make clean` | Remove generated repository build/test outputs. |
| `make doctor` | Diagnose tools and explain optional desktop features. |

`make setup` does not build the interface. Use `make build-web` for browser/CLI
production assets, `make dev` for development, or `make build` for the actual local
desktop application. `make run ARGS='--data-directory /absolute/private/workspace'`
passes application options to the built shell.

`make clean` has a fixed allowlist: root `build/` and `dist/`, frontend production/
test reports, TypeScript build metadata, copied Python web assets and pytest/Ruff caches. It preserves
`desktop/build/` source metadata, `.venv/`, `node_modules/`, all source files,
checkout `data/`, exports under `outputs/`, XDG user data/state/cache and credentials.
It never removes or resets a database or user profile. The generated desktop-build
environment inside `build/` is recreated by the next desktop build.

## Tests and release checks

```sh
make test-backend PYTEST_ARGS='tests/test_config.py -q'
make test-frontend
make test-desktop
make test-anki
pnpm --dir frontend exec playwright install chromium
make test-browser
```

The browser target builds the interface and owns an isolated temporary offline test
host on an allocated loopback port. It uses a null keyring and controlled provider,
clears a live key from the child environment, and cleans up its own backend. It does
not connect to the usual development workspace or a separately running server.
Pass Playwright options with `ARGS`, for example `ARGS='--project chromium'`.
CI can install Chromium's system dependencies using Playwright's `--with-deps`.

Anki tests use the optional locked `anki-integration` extra in disposable collections.
Normal Python tests explicitly skip that module when the extra is absent, as well
as frozen-backend tests when no copied executable is selected. They require no paid
API calls. See [testing](testing.md) for scope, credential isolation and limitations.

```sh
make package
make package PACKAGE_ARGS=--appimage-only
make package PACKAGE_ARGS=--backend-only
make test-frozen FROZEN_BACKEND=/tmp/copied-backend/anki-generator-backend
make test-packaged APPIMAGE=/tmp/copied-release/Anki-Generator.AppImage
```

Keep the entire frozen backend folder beside its executable. Copied-distribution
checks intentionally require artifacts outside the checkout; GUI checks also need
a graphical session and the original unpacked payload for lifecycle fault injection
(`UNPACKED=/path/to/linux-unpacked` overrides it). They retain Chromium sandboxing
and use test-only provider fixtures. The packaged sequence also verifies native
Keep editing/Discard choices for unsaved edits during close, restart and reload.
`PACKAGE_ARGS=--skip-checks` explicitly skips
the packaging script's source checks; it never constitutes release verification.

`make build`/`make package` use a dedicated environment under `build/desktop/venv`.
The scripts, PyInstaller spec, Electron metadata and native RPM spec remain the
authoritative packaging implementation. See [desktop usage and builds](desktop.md)
for storage, migration, security, Linux compatibility and installation. Actual dated
results belong in [verification](verification.md).

Legacy `install.sh`, `run.sh`, `dev.sh` and direct packaging scripts remain supported.
Developer experiments are opt-in and never require Electron:

```sh
make benchmark
make benchmark-smoke
make benchmark ARGS='inventory /path/to/private.zip --output data/benchmarks/inventory.json --extract-to data/benchmarks/originals'
make benchmark-report ARGS='data/benchmarks/runs/<run>/result.json --output data/benchmarks/report.md'
```

`make eval` aliases `make benchmark`. `make benchmark-engineering` measures authored
math-boundary/vector-cache controls; these are engineering measurements rather
than real-course accuracy. Ordinary tests and CI never run paid experiments.
See [evaluation](evaluation.md) for frozen inputs, archived implementations,
private artifacts, human annotation, model comparisons and live-call gates.

The deterministic inspect workflow also remains available:

```sh
uv run --locked anki-generator inspect fixtures/example-course --output outputs/example
```
