# Desktop backend protocol and data safety

The Electron shell starts the bundled `anki-generator-backend` executable with
`--startup-file`, `--data-directory`, `--state-directory` and `--parent-pid`.
The Python entry calls `multiprocessing.freeze_support()` before importing the
application, so bounded PDF/Office/SymPy subprocesses use the frozen executable
without recursively launching another server. The existing browser `serve` and
deterministic `inspect` commands retain their behavior.

The desktop defaults are `$XDG_DATA_HOME/anki-generator` and
`$XDG_STATE_HOME/anki-generator`, falling back to `~/.local/share/anki-generator`
and `~/.local/state/anki-generator`. Relative XDG values are ignored. Data contains
SQLite, originals, derived previews, caches, jobs and exports. State contains
bounded lifecycle logs. Both directories are private and independent of the
executable, installation and current working directory. Explicit directory
arguments support isolated testing or a user-selected data location.

The shell supplies a random per-launch `ANKI_GENERATOR_DESKTOP_TOKEN` through the
child environment. Python consumes it before creating parser children; it never
appears in command arguments, startup metadata, renderer JavaScript, URLs or logs.
Desktop mode requires `X-Desktop-Token` on every HTTP request, including health,
bootstrap, assets and API documentation. Constant-time comparison supplements
the existing host/origin/CSRF guards. Browser mode does not acquire this extra
requirement. The shell must inject the header only for its own allocated origin.

The backend pre-binds a socket to `127.0.0.1:0` and gives that same socket to
Uvicorn. It never releases a probe port and later tries to reuse it. After an
authenticated health check succeeds, it atomically replaces the mode0600 startup
file with `{status:"ready",pid,host:"127.0.0.1",port,origin,version}`. Failures
instead publish `{status:"error",pid,code}` with a curated configuration, storage,
database, resources, bind, runtime or timeout category. Frozen startup rejects a
missing bundled frontend before publishing readiness. The shell additionally
checks the child PID, loopback origin and health response.

SIGTERM stops admission and waits for in-flight operations to finish and save
checkpoints. The ordinary maintenance stop default remains five seconds; desktop
shutdown waits 210 seconds at a time and continues waiting when necessary.
Configured parser timeouts can be longer. A timeout is not permission to kill the
backend automatically. An explicit force quit can lose the current unsaved unit;
previous durable checkpoints survive and restart recovery pauses interrupted
work. The parent monitor requests the same graceful shutdown when Electron exits.
On POSIX it verifies the original parent PID rather than watching a reused PID.
The per-data-directory process lock prevents duplicate workers and migrations.

## Retaining existing browser data

Migration is explicit and uses the established validated backup/restore workflow.
In the old browser application, pause active jobs and download a backup from
Settings. Close that application. In the desktop application, open Settings,
validate the backup, inspect the reported contents/warnings, then confirm a clean
restore or the separately confirmed replacement. Validation checks archive paths,
checksums, SQLite integrity, supported migrations and referenced source/media
files in staging. Replacement retains a recovery archive. This copies application
data without deleting the original browser directory. It does not merge databases.

Alternatively, close both applications and explicitly select the existing data
directory when launching the backend. The default browser checkout location is
`data/app`. Never run two processes against that directory. There is no automatic
directory search/copy, no silent overwrite, and no credential transfer in backups.
Configure the key in the desktop Settings screen; session storage remains available
when a supported secure OS credential store cannot be used.

## Diagnostics

Authenticated desktop-only endpoints are `GET /api/desktop/diagnostics`,
`GET /api/desktop/shutdown-status` and CSRF-protected
`POST /api/desktop/diagnostics/export`. Reports contain application/backend/schema
versions, directory locations, job counts, scheduler state, credential-store
availability and allowlisted lifecycle events. Exported ZIPs omit private paths,
keys, source/card content, database files and raw exceptions/logs. Backend lifecycle
logs rotate at 1MiB with three retained backups; they store only event categories,
timestamps and PIDs. Shell logs have a separate bounded policy. Uvicorn exception
values are not forwarded to shell logs.

`tests/test_desktop_api.py` and `tests/test_desktop_runtime.py` exercise actual local
processes, authentication, explicit browser-backup import, restart persistence,
local extraction, private paths/log rotation, second-instance rejection and
checkpoint shutdown. Actual PyInstaller/Electron/AppImage tests are a separate
packaging check; passing these source-runtime tests alone does not establish a
self-contained distribution or live OpenAI correctness.
