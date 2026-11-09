# Desktop application

Anki Generator's Linux desktop distribution contains Electron, the existing
production React interface, and a PyInstaller one-folder Python backend. Opening
the application starts its private backend automatically. Normal use needs no
Python, uv, Node.js, pnpm, Vite server, or separately started browser. Local import,
extraction, corrections, review, backup and export work offline. OpenAI analysis
and embeddings need a configured key, network access and the existing run consent.

Fedora Linux with KDE Plasma on x86_64 is the initial target. Windows, macOS,
other CPU architectures and older Linux distributions are not established release
targets. Read the dated [verification report](verification.md) for actual packaged
checks and environmental limitations; a successful build is not a runtime test.

## Launch the portable AppImage

The release build produces:

```text
dist/desktop/Anki-Generator-0.1.0-x86_64.AppImage
dist/desktop/Anki-Generator-0.1.0-x86_64.rpm
```

Move the AppImage anywhere convenient, mark it executable in Dolphin's permissions
dialog, and open it. The equivalent terminal commands are:

```sh
chmod +x Anki-Generator-0.1.0-x86_64.AppImage
./Anki-Generator-0.1.0-x86_64.AppImage
```

The startup screen shows readiness or an actionable failure with retry and
diagnostics. The backend binds an available loopback port; no fixed port needs
configuration. A second launch focuses the existing application for that workspace.
The backend also independently locks its data directory before migration or recovery.

On a system without usable FUSE, the AppImage runtime can extract and run itself:

```sh
./Anki-Generator-0.1.0-x86_64.AppImage --appimage-extract-and-run
```

This uses temporary space and takes longer to start; persistent course data still
lives in the user-data directory. It does not disable Chromium's sandbox. See the
[AppImage FUSE guidance](https://docs.appimage.org/user-guide/troubleshooting/fuse.html).

## Install the Fedora RPM

Use the graphical package installer or, from the directory containing the release:

```sh
sudo dnf install ./Anki-Generator-0.1.0-x86_64.rpm
```

Launch **Anki Generator** from the application menu. The package installs the
runtime under `/opt/anki-generator`, desktop metadata under
`/usr/share/applications`, and icons under `/usr/share/icons/hicolor`. It uses the
same user-data location as the AppImage. Package upgrades or removal do not delete
that user-data tree. Do not run the application as root.

The RPM declares its Linux GUI/library requirements, including glibc, GTK3, NSS,
X11/Wayland-related libraries, ALSA, libsecret and xdg-utils. These are operating
system dependencies, not development tools. The AppImage also requires compatible
host libraries and a graphical desktop. The current build host is Fedora 44 with
glibc 2.43; older-glibc compatibility is not implied. PyInstaller deliberately uses
the host's libc, so a broader release should be built on its oldest supported
Linux base and tested there. See [PyInstaller's Linux compatibility notes](https://www.pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible).

LibreOffice and bubblewrap remain optional external system components for isolated
Office-to-PDF rendering. The bundled native DOCX/PPTX extraction works without them
and retains its explicit layout/equation limitations. See [ingestion](ingestion.md).

## Daily use and desktop controls

The course, source correction, evaluation, Tasks and export workflows are the same
as the existing application. Configure the key in Settings; session-only storage
is always available. Secure persistence is offered only when the packaged runtime
can use an available OS credential store. No plaintext-key fallback is created.

- File/folder inputs open the platform's file chooser; drag and drop remains
  available. Export downloads open a native save dialog.
- Settings → **Desktop workspace** shows application/backend versions and storage
  locations, offers directory buttons, restart and diagnostics, and lets you open
  the last saved file or show its folder. Only files saved in the current session
  are eligible for these opening actions.
- Native menus expose courses, Tasks, Settings, downloads, zoom and diagnostics.
  Window bounds and maximized state are remembered; disconnected-display positions
  are brought back into view. Wayland compositors control absolute window placement,
  so a saved X/Y position may be ignored while the saved size is restored.
  Native window decorations remain in use.
- External HTTP/HTTPS links open in the default browser. They cannot replace the
  application workspace or acquire its preload privileges.
- Where a tray is available, its menu shows running/queued counts and can reopen
  the window or Tasks. Observed task completion/failure can produce a native
  notification while the application is unfocused, subject to desktop support.
  Notifications and tray availability depend on the running desktop session.

Navigating between views does not stop generation. The existing durable scheduler
still runs independent courses concurrently under shared global API/local budgets;
see [Tasks](tasks.md) and [resource management](resource-management.md).

## Closing, restarting and interrupted work

Closing with active work offers keeping the window open, **Checkpoint & quit**, and
**Keep running in tray** when available. Tray support is optional; the checkpoint
workflow remains available without it. Quitting stops new admissions and waits for
in-flight work to save recoverable results. Queued tasks remain persisted.

An in-flight provider call or parser may take time. Desktop shutdown allows a
210-second backend drain interval, with the shell allowing a small additional
margin. If work still has not drained, it offers **Keep waiting** or a separately
confirmed **Force quit**. It never treats the timeout as automatic permission to
kill the process. Force quit can lose the current unsaved unit, and a completed
provider request may need to be repeated after recovery. Earlier durable results
remain available; exactly-once provider billing is not guaranteed.

Unexpected backend exit shows a recovery screen. Retry there or use **Restart
processing service** in Settings. Interrupted executing tasks recover paused with
their saved checkpoints; inspect and resume them from Tasks. The shell's parent
monitor requests graceful backend shutdown if the shell disappears. Reopening a
busy workspace never starts a competing backend against the same database.

## Storage, backups and migration

Application resources are read-only. Persistent locations follow XDG conventions:

| Contents | Default location |
| --- | --- |
| SQLite, originals, derived evidence, cards, caches, checkpoints, exports and backups | `$XDG_DATA_HOME/anki-generator`, otherwise `~/.local/share/anki-generator` |
| Window state, shell profile and rotating lifecycle logs | `$XDG_STATE_HOME/anki-generator`, otherwise `~/.local/state/anki-generator` |
| Chromium cache | `$XDG_CACHE_HOME/anki-generator/chromium`, otherwise `~/.cache/anki-generator/chromium` |

Use absolute XDG paths. For an explicitly selected workspace, the executable also
accepts `--data-directory /absolute/path` and `--state-directory /absolute/path`.
Moving or replacing the executable does not move these directories. Never store
private data in the installation or extracted AppImage directory. GUI backup
contains private course data; diagnostic exports are separate from backups.

The browser/development application still defaults to the checkout's `data/app`.
Desktop mode does not search for, silently copy, or overwrite it. To retain courses:

1. In the old application, pause/stop active work and create a backup from Settings.
2. Close the old application so it no longer owns its data directory.
3. Open the desktop application. In Settings → **Data & storage**, choose
   **Validate & restore backup** and select the archive.
4. Inspect the validation report. Confirm clean restore or the separately confirmed
   replacement of an existing desktop workspace. Replacement retains a recovery
   archive; restoration is not a database merge.
5. Confirm your courses and sources, then configure your API key again if needed.
   Credentials are excluded from backups; the original browser data remains intact.

Validation stages archive paths, checksums, SQLite integrity, supported schema
migrations and referenced sources/media before replacement. Restored pending jobs
remain paused until explicitly resumed. Alternatively, after closing both apps,
launch desktop with `--data-directory` pointing at the existing absolute directory.
This reuses that workspace directly; it does not create a separate migrated copy.
Back up before changing application versions, and never open the same directory
from two backend processes. See [data contracts](data-model.md).

## Security boundary

Electron uses `sandbox: true`, `contextIsolation: true`, disabled renderer Node
integration, a restricted CSP, denied renderer permission requests, and validated
main-frame IPC. The preload exposes a small set of desktop actions rather than
arbitrary paths, shell execution or Electron APIs. App-only navigation, denied
new windows and request filtering keep remote content outside this boundary.
These controls follow the [Electron security guide](https://www.electronjs.org/docs/latest/tutorial/security).

The shell creates a random token for each launch, passes it to its child privately,
and adds `X-Desktop-Token` only to its allocated backend origin. Every desktop HTTP
route, including assets and health, requires this token in addition to existing
host/origin/CSRF checks. The token is absent from URLs, process arguments and
renderer JavaScript. Opening the loopback URL in an ordinary browser therefore
does not expose the desktop backend. Browser development mode retains its existing
separate protections. See the [backend protocol](desktop-backend.md).

OpenAI credentials stay backend-side in memory or a usable secure OS credential
store. Native integration does not bypass consent, input/archive/parser limits,
verification, human approval, identity conflicts, or Anki export policy. Production
never silently substitutes a deterministic test provider. Chromium sandbox flags
must remain enabled; `--no-sandbox` is not a supported launch or packaging fix.

## Build and develop

Build-time prerequisites are Linux x86_64, uv, Node.js 24 LTS (or compatible 22.13+),
pnpm, and `rpm-build` for RPM output. A first build downloads locked dependencies,
Electron and packaging tools. This network/toolchain requirement does not apply to
users launching the resulting release. Keep adequate disk space for the Python
bundle, Electron payload and temporary AppImage/RPM artifacts.

```sh
./scripts/build-desktop.sh
```

The script creates a dedicated `build/desktop/venv`, synchronizes locked Python and
both frontend/desktop pnpm environments, runs Python lint/format/tests and frontend/
shell unit tests, builds React, copies its assets, creates icons, freezes the
backend and assembles Electron. Electron Builder creates the AppImage; native
`rpmbuild` creates the RPM from the same unpacked payload, avoiding a separate
legacy FPM/Ruby toolchain. Outputs and sizes are printed under `dist/desktop`.

Current pins are Electron 45.2.3, Electron Builder 26.18.0 and PyInstaller 6.22.3.
They are recorded in `desktop/package.json`, its lockfile, `pyproject.toml` and
`uv.lock`. [Electron Builder's Linux configuration](https://www.electron.build/docs/linux/)
describes its packaging boundary; the Fedora spec lives in `desktop/build`.

Useful variants:

```sh
./scripts/build-desktop.sh --appimage-only
./scripts/build-desktop.sh --backend-only
./scripts/build-desktop.sh --skip-checks
./scripts/dev-desktop.sh
```

`--skip-checks` explicitly omits checks; it is not release verification. Backend-only
output is `build/desktop/backend/anki-generator-backend/anki-generator-backend` and
requires the entire sibling bundle. Do not copy only that executable. Production
assets, prompts, migrations, parser templates, certificate resources, native
libraries and keyring metadata are collected by `packaging/backend.spec`.
`multiprocessing.freeze_support()` runs before application imports so parser and
symbolic child processes can spawn from the frozen backend safely.

Desktop development uses source Python with production frontend assets. For
frontend hot reload, use the managed HMR mode:

```sh
./scripts/dev-desktop.sh --hmr --devtools
```

The script starts and health-checks its own Vite server at
`http://127.0.0.1:5173`, fails if that port is occupied, and cleans up its own
Vite/Electron processes on exit. The shell manages the source backend and redirects
API requests to its allocated origin. React edits reload through Vite. Python
changes require **Restart processing service** in Settings; active tasks retain
the checkpoint confirmation workflow. No frozen rebuild is needed for source
changes in this mode.

Only the exact development frontend origin is allowed; packaged releases reject
service overrides. The script clears inherited `ELECTRON_RUN_AS_NODE` and
`NODE_OPTIONS` so VS Code/Codex terminals can launch the shell normally. Open the
repository in the editor, run the script in a terminal, and retain the established
Python/frontend checks. Browser `./install.sh`, `./run.sh`, `./dev.sh` and the
deterministic `anki-generator inspect` CLI remain available.

## Test the distribution and maintain releases

Source/unit checks cannot prove a self-contained release. Copy the AppImage and
whole backend bundle outside the checkout; run from an unrelated directory with
temporary XDG/data paths. The opt-in backend checks use:

```sh
ANKI_TEST_FROZEN_BACKEND=/tmp/copied-backend/anki-generator-backend \
  uv run --locked pytest tests/test_frozen_desktop.py -q
pnpm --dir desktop test
node tests/desktop/launch-smoke.cjs /tmp/Anki-Generator-0.1.0-x86_64.AppImage
node tests/desktop/workflow.cjs /tmp/Anki-Generator-0.1.0-x86_64.AppImage
node tests/desktop/lifecycle.cjs /tmp/Anki-Generator-0.1.0-x86_64.AppImage
```

Frozen tests exercise actual bundled resources/native libraries and an explicitly
controlled local server through the real OpenAI SDK. They do not measure paid
OpenAI accuracy. The GUI smoke test uses isolated storage and a null test keyring,
opens the actual packaged shell, checks local import/extraction/navigation,
security and persistence, and saves screenshots. A graphical desktop or an
appropriate graphical test session is required. Keep personal credentials and
collections out of release tests. Full executed commands/results belong in
[verification](verification.md), with [testing guidance](testing.md).
Playwright Electron launches must set `chromiumSandbox: true` and assert the
absence of `--no-sandbox`; test key entry must use the dedicated null keyring.

Before release, run the existing backend/frontend/browser checks plus packaged
lifecycle tests: missing resources/startup failure, unexpected child exit, second
instance, normal and active-job close, recovery and migration. Inspect actual
fonts/icons/mathematics/previews, native dialogs and KDE menu/tray behavior. Test
the RPM in an isolated target system; extracting it alone is not an installed KDE
launch test. Keep package and backend versions aligned. Update locked dependencies
deliberately, rebuild after any resource/migration change, and repeat packaged
tests after Electron/PyInstaller/parser changes.

Updates are manual: safely quit, back up, then replace the AppImage or install the
new RPM. Startup applies supported Alembic migrations under the workspace lock.
No automatic update download or cross-version downgrade guarantee is implemented.
Preserve a pre-upgrade backup if an older application version may be needed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| AppImage reports FUSE unavailable | Use the extract-and-run command above or repair the host FUSE setup; keep the sandbox enabled. |
| Sandbox or host-library launch error | Use a compatible normal desktop session and current system libraries; inspect logs. For installed RPMs, verify package ownership/permissions rather than disabling the sandbox. |
| Startup screen reports storage/database failure | Check the displayed data/state paths, permissions and free space. Close any other process owning the workspace. Keep the database and use a validated backup for recovery; do not delete it to suppress the error. |
| Missing bundled resources | Replace/reinstall the complete distribution. Developers must rebuild the frontend and frozen backend together. |
| Backend stops or a view cannot load | Use Retry or Settings → Restart processing service, then inspect Tasks. Durable checkpoints survive; interrupted work needs explicit resume. |
| Shutdown keeps waiting | Let in-flight work finish. Force quit requires confirmation and may repeat the unfinished provider unit after recovery. |
| Secure key persistence is unavailable | Use session-only storage; check the desktop credential service separately. Packaging must not create a plaintext fallback. |
| Tray or notifications do not appear | Check the desktop's tray/notification configuration. Keep the window open or choose checkpoint-and-quit; work does not depend on tray support. |
| External file cannot open | Save succeeded independently of desktop file associations. Use Show in folder and open it with an installed suitable application. |
| Sources seem missing after moving from browser mode | Desktop and checkout data defaults differ. Use the explicit validated backup/restore procedure above. |

Settings and the Help menu expose diagnostics and the logs directory without a
terminal. Backend lifecycle logs rotate at 1 MiB with three backups; shell logs have
their own bounded rotation. **Export desktop diagnostics** saves a shell JSON
report containing versions, safe events and private local directory locations;
it excludes API keys and document/card contents. The separate backend diagnostic
ZIP also omits private paths. Application backup archives
contain course data and must not be confused with diagnostic bundles.
