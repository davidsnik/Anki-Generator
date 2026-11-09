"use strict";
const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  Notification,
  dialog,
  shell,
  session,
  protocol,
  ipcMain,
  screen,
} = require("electron");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const {
  desktopPaths,
  prepareDirectories,
  visibleBounds,
} = require("./lib/paths.cjs");
const { BackendSupervisor } = require("./lib/backend.cjs");
const { DesktopLog } = require("./lib/log.cjs");
const {
  sameOrigin,
  externalLink,
  injectToken,
  trustedFrame,
  safeFilename,
  downloadOpenable,
} = require("./lib/security.cjs");

app.setName("Anki Generator");
protocol.registerSchemesAsPrivileged([
  {
    scheme: "anki-shell",
    privileges: { standard: true, secure: true, supportFetchAPI: true },
  },
]);
function argumentsMap(values) {
  const result = { args: [] };
  for (let i = 0; i < values.length; i++) {
    const raw = values[i];
    if (!raw.startsWith("--")) continue;
    const equal = raw.indexOf("=");
    const key = raw.slice(2, equal < 0 ? undefined : equal);
    const value = equal < 0 ? values[i + 1] : raw.slice(equal + 1);
    if (
      [
        "data-directory",
        "state-directory",
        "backend-command",
        "backend-arg",
        "frontend-url",
      ].includes(key)
    ) {
      if (!value || (value.startsWith("--") && key !== "backend-arg"))
        throw new Error(`Missing --${key} value`);
      if (equal < 0) i++;
      if (key === "backend-arg") result.args.push(value);
      else result[key] = value;
    } else if (key === "devtools") result.devtools = true;
  }
  return result;
}
let options, paths;
try {
  options = argumentsMap(process.argv.slice(1));
  paths = desktopPaths(process.env, undefined, {
    data: options["data-directory"],
    state: options["state-directory"],
  });
  prepareDirectories(paths);
  app.setPath("userData", paths.chromium);
  app.setPath("sessionData", paths.cache);
  app.setPath("logs", paths.logs);
} catch {
  app.whenReady().then(() => {
    dialog.showErrorBox(
      "Workspace directory unavailable",
      "Anki Generator could not create its private desktop directories. Check your XDG paths and directory permissions.",
    );
    app.exit(1);
  });
}
const ownsInstance = paths && app.requestSingleInstanceLock();
if (paths && !ownsInstance) app.quit();
let win = null,
  tray = null,
  backend = null,
  privateSession = null,
  quitting = false,
  quitPending = false,
  restarting = false;
let quitAfterRestart = false;
let keptUnsavedChanges = 0;
let unsavedPromptOpen = false;
let state = {
  status: "starting",
  message: "Preparing your private workspace…",
  details: "",
};
let frontendOrigin = null,
  backendVersion = null,
  lastDownload = null,
  pollTimer = null,
  saveBoundsTimer = null;
const downloads = new Map();
let observedTasks = null,
  seenHistory = null;
const startedAt = Date.now();
const log = paths
  ? new DesktopLog(paths.logs, [
      process.env.OPENAI_API_KEY,
      process.env.ANKI_GENERATOR_DESKTOP_TOKEN,
    ])
  : null;
const icon = path.join(
  app.isPackaged ? process.resourcesPath : path.join(__dirname, "build"),
  "icon.png",
);
const boundsFile = paths ? path.join(paths.state, "window.json") : null;
const notificationFile = paths
  ? path.join(paths.state, "notifications.json")
  : null;
const readJSON = (file, fallback) => {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
};
const storeJSON = (file, value) => {
  try {
    const temporary = `${file}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(value), { mode: 0o600 });
    fs.renameSync(temporary, file);
  } catch {
    log?.write("preference-write-failed");
  }
};
function origins() {
  return new Set([
    "anki-shell://startup",
    ...(backend?.origin ? [backend.origin] : []),
    ...(frontendOrigin ? [frontendOrigin] : []),
  ]);
}
function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}
function publicInfo() {
  return {
    desktop: true,
    application_version: app.getVersion(),
    platform: process.platform,
    data_directory: paths.data,
    state_directory: paths.state,
    backend_version: backendVersion,
    status: state.status,
    message: state.message,
    details: state.details,
    notifications_supported: Notification.isSupported(),
    tray_available: !!tray,
    last_download: lastDownload,
  };
}
function setState(next) {
  state = { ...state, ...next };
  send("desktop:state", publicInfo());
}
function showWindow(route) {
  if (!win || win.isDestroyed()) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  if (route && state.status === "ready") send("desktop:navigate", route);
}
function confirmUnsavedChanges(window, event) {
  // Electron requires this decision synchronously. Preventing this event means
  // overriding the renderer's beforeunload veto, so only explicit discard does so.
  if (unsavedPromptOpen) {
    keptUnsavedChanges++;
    return;
  }
  unsavedPromptOpen = true;
  let choice;
  try {
    choice = dialog.showMessageBoxSync(window, {
      type: "question",
      title: "Unsaved changes",
      message: "Keep editing your unsaved changes?",
      detail:
        "This window has changes that have not been saved. Keep editing to save them, or discard them to continue closing, restarting or reloading the workspace.",
      buttons: ["Keep editing", "Discard changes"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
  } finally {
    unsavedPromptOpen = false;
  }
  if (choice === 1) event.preventDefault();
  else keptUnsavedChanges++;
}
function restoreAfterKeptChanges(previousState) {
  // A backend/window failure may arrive while the native decision is open.
  // Never overwrite that newer failure with an earlier "ready" snapshot.
  if (backend?.status === "failed" || state.status === "failed") return;
  setState(previousState);
}
async function loadWorkspace(url) {
  const before = keptUnsavedChanges;
  try {
    await win.loadURL(url);
    return true;
  } catch (error) {
    if (keptUnsavedChanges !== before && error.code === "ERR_ABORTED")
      return false;
    throw error;
  }
}
async function startupView() {
  if (
    win &&
    !win.isDestroyed() &&
    !win.webContents.getURL().startsWith("anki-shell://startup/")
  )
    if (!(await loadWorkspace("anki-shell://startup/"))) return false;
  send("desktop:state", publicInfo());
  return true;
}
function allowRequest(value, type) {
  if (sameOrigin(value, backend?.origin) || sameOrigin(value, frontendOrigin))
    return true;
  if (value.startsWith("anki-shell://startup/")) return true;
  if (frontendOrigin) {
    try {
      const url = new URL(value);
      if (
        url.protocol === "ws:" &&
        url.hostname === "127.0.0.1" &&
        url.port === "5173"
      )
        return true;
    } catch {}
  }
  if (value.startsWith("blob:"))
    return [...origins()].some((origin) => value.startsWith(`blob:${origin}/`));
  if (value.startsWith("data:") && ["image", "font"].includes(type))
    return true;
  // Chromium's own PDF viewer is isolated from the application preload.
  if (value.startsWith("chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/"))
    return true;
  return false;
}
function configureSession() {
  privateSession = session.fromPartition("persist:anki-generator");
  privateSession.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  );
  privateSession.setPermissionCheckHandler(() => false);
  privateSession.webRequest.onBeforeRequest(
    { urls: ["<all_urls>"] },
    (details, callback) => {
      if (
        frontendOrigin &&
        sameOrigin(details.url, frontendOrigin) &&
        new URL(details.url).pathname.startsWith("/api/") &&
        backend?.origin
      ) {
        const source = new URL(details.url);
        callback({
          redirectURL: `${backend.origin}${source.pathname}${source.search}`,
        });
        return;
      }
      callback({ cancel: !allowRequest(details.url, details.resourceType) });
    },
  );
  privateSession.webRequest.onBeforeSendHeaders(
    { urls: ["<all_urls>"] },
    (details, callback) =>
      callback({
        requestHeaders: injectToken(
          details.url,
          details.requestHeaders,
          backend?.origin,
          backend?.secret,
        ),
      }),
  );
  privateSession.webRequest.onHeadersReceived(
    { urls: ["http://127.0.0.1/*"] },
    (details, callback) => {
      const dev = frontendOrigin && sameOrigin(details.url, frontendOrigin);
      const headers = { ...details.responseHeaders };
      for (const key of Object.keys(headers))
        if (
          [
            "content-security-policy",
            "x-frame-options",
            "referrer-policy",
          ].includes(key.toLowerCase())
        )
          delete headers[key];
      const connect = dev
        ? `'self' ${backend.origin} ws://127.0.0.1:5173`
        : `'self'`;
      headers["Content-Security-Policy"] = [
        `default-src 'self'; script-src 'self'${dev ? " 'unsafe-inline'" : ""}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: ${dev ? backend.origin : ""}; font-src 'self' data:; connect-src ${connect}; worker-src 'self' blob:; frame-src 'self' blob: ${dev ? backend.origin : ""}; object-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'`,
      ];
      headers["X-Frame-Options"] = ["DENY"];
      headers["Referrer-Policy"] = ["no-referrer"];
      callback({ responseHeaders: headers });
    },
  );
  privateSession.protocol.handle("anki-shell", async (request) => {
    const url = new URL(request.url);
    const files = {
      "/": "startup.html",
      "/startup-renderer.js": "startup-renderer.js",
      "/startup.css": "startup.css",
      "/icon.png": null,
    };
    if (url.hostname !== "startup" || !Object.hasOwn(files, url.pathname))
      return new Response("Not found", { status: 404 });
    const file =
      url.pathname === "/icon.png"
        ? icon
        : path.join(__dirname, files[url.pathname]);
    try {
      return new Response(await fsp.readFile(file), {
        headers: {
          "Content-Type": url.pathname.endsWith(".js")
            ? "text/javascript"
            : url.pathname.endsWith(".css")
              ? "text/css"
              : url.pathname.endsWith(".png")
                ? "image/png"
                : "text/html",
          "Content-Security-Policy":
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        },
      });
    } catch {
      return new Response("The packaged startup screen is unavailable.", {
        status: 500,
      });
    }
  });
  privateSession.on("will-download", (event, item, contents) => {
    const url = item.getURL();
    if (contents !== win?.webContents || !allowRequest(url, "other")) {
      event.preventDefault();
      return;
    }
    const filename = safeFilename(item.getFilename());
    item.setSaveDialogOptions({
      title: "Save from Anki Generator",
      defaultPath: path.join(app.getPath("downloads"), filename),
      ...(path.extname(filename)
        ? {
            filters: [
              {
                name: "Exported file",
                extensions: [path.extname(filename).slice(1)],
              },
            ],
          }
        : {}),
    });
    item.once("done", (_event, result) => {
      if (result !== "completed") return;
      const id = require("node:crypto").randomUUID();
      const savedName = path.basename(item.getSavePath());
      downloads.set(id, { path: item.getSavePath(), filename: savedName });
      if (downloads.size > 50) downloads.delete(downloads.keys().next().value);
      lastDownload = { id, filename: savedName };
      send("desktop:download", lastDownload);
      log.write("download-saved", { extension: path.extname(filename) });
    });
  });
}
function secureWindow(window) {
  window.webContents.on("will-prevent-unload", (event) =>
    confirmUnsavedChanges(window, event),
  );
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (
      backend?.origin &&
      sameOrigin(url, backend.origin) &&
      /^\/api\/documents\/[^/]+\/source$/.test(new URL(url).pathname)
    ) {
      window.webContents.downloadURL(url);
      return { action: "deny" };
    }
    const external = externalLink(url);
    if (
      external &&
      !sameOrigin(external, backend?.origin) &&
      !sameOrigin(external, frontendOrigin)
    )
      void shell.openExternal(external).catch(() => {});
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (![...origins()].some((origin) => sameOrigin(url, origin))) {
      event.preventDefault();
      const external = externalLink(url);
      if (external) void shell.openExternal(external).catch(() => {});
    }
  });
  window.webContents.on("will-attach-webview", (event) =>
    event.preventDefault(),
  );
  window.webContents.on(
    "did-fail-load",
    (_event, code, _description, url, isMainFrame) => {
      if (isMainFrame && code !== -3 && !url.startsWith("anki-shell:")) {
        setState({
          status: "failed",
          message: "The workspace window could not load.",
          details:
            "The backend remains separate from this window. Retry to reconnect to your saved workspace.",
        });
        void startupView();
      }
    },
  );
  window.webContents.on("render-process-gone", () => {
    if (!quitting) {
      setState({
        status: "failed",
        message: "The workspace window stopped responding.",
        details: "Saved work remains available. Retry to reopen the workspace.",
      });
      void startupView();
    }
  });
}
function createWindow() {
  const saved = visibleBounds(
    readJSON(boundsFile, {}),
    screen.getAllDisplays(),
  );
  win = new BrowserWindow({
    width: saved.width,
    height: saved.height,
    ...(saved.x !== undefined ? { x: saved.x, y: saved.y } : {}),
    minWidth: 900,
    minHeight: 640,
    title: "Anki Generator",
    icon: fs.existsSync(icon) ? icon : undefined,
    backgroundColor: "#f8f9fc",
    show: false,
    autoHideMenuBar: false,
    webPreferences: {
      session: privateSession,
      preload: path.join(__dirname, "preload.cjs"),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false,
      backgroundThrottling: false,
      devTools: !app.isPackaged,
    },
  });
  secureWindow(win);
  if (saved.maximized) win.maximize();
  win.once("ready-to-show", () => win.show());
  win.webContents.on("did-finish-load", () =>
    send("desktop:state", publicInfo()),
  );
  const remember = () => {
    clearTimeout(saveBoundsTimer);
    saveBoundsTimer = setTimeout(() => {
      if (!win || win.isDestroyed()) return;
      storeJSON(boundsFile, {
        ...win.getNormalBounds(),
        maximized: win.isMaximized(),
      });
    }, 250);
  };
  for (const event of ["resize", "move", "maximize", "unmaximize"])
    win.on(event, remember);
  win.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      void requestQuit();
    }
  });
  return win.loadURL("anki-shell://startup/");
}
function menu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "File",
        submenu: [
          {
            label: "Your courses",
            accelerator: "CmdOrCtrl+Shift+O",
            click: () => showWindow("/courses"),
          },
          {
            label: "Tasks",
            accelerator: "CmdOrCtrl+Shift+T",
            click: () => showWindow("/tasks"),
          },
          { type: "separator" },
          {
            label: "Settings & diagnostics",
            accelerator: "CmdOrCtrl+,",
            click: () => showWindow("/settings"),
          },
          {
            label: "Open downloads folder",
            click: () => void shell.openPath(app.getPath("downloads")),
          },
          { type: "separator" },
          {
            label: "Quit Anki Generator",
            accelerator: "CmdOrCtrl+Q",
            click: () => void requestQuit(),
          },
        ],
      },
      {
        label: "Edit",
        submenu: [
          { role: "undo" },
          { role: "redo" },
          { type: "separator" },
          { role: "cut" },
          { role: "copy" },
          { role: "paste" },
          { role: "selectAll" },
        ],
      },
      {
        label: "View",
        submenu: [
          {
            label: "Reload workspace",
            accelerator: "CmdOrCtrl+R",
            click: () => {
              if (state.status === "ready" && !unsavedPromptOpen) win?.reload();
            },
          },
          { role: "resetZoom" },
          { role: "zoomIn" },
          { role: "zoomOut" },
          { type: "separator" },
          { role: "togglefullscreen" },
          ...(!app.isPackaged ? [{ role: "toggleDevTools" }] : []),
        ],
      },
      {
        label: "Help",
        submenu: [
          {
            label: "Export diagnostics…",
            click: () => void exportDiagnostics(),
          },
          {
            label: "Open logs folder",
            click: () => void shell.openPath(paths.logs),
          },
          { type: "separator" },
          {
            label: "About Anki Generator",
            click: () =>
              dialog.showMessageBox(win, {
                type: "info",
                title: "Anki Generator",
                message: `Anki Generator ${app.getVersion()}`,
                detail:
                  "Your university sources, connected to thoughtful Anki cards. Local storage; external processing only with consent.",
              }),
          },
        ],
      },
    ]),
  );
}
function createTray() {
  if (process.platform === "linux" && !process.env.DBUS_SESSION_BUS_ADDRESS)
    return;
  try {
    if (!fs.existsSync(icon)) return;
    tray = new Tray(icon);
    tray.setToolTip("Anki Generator");
    tray.on("click", () => showWindow());
    updateTray();
  } catch {
    tray = null;
    log.write("tray-unavailable");
  }
}
function updateTray(counts = {}) {
  if (!tray) return;
  const title = `${counts.running || 0} running · ${counts.queued || 0} queued`;
  tray.setToolTip(`Anki Generator · ${title}`);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: title, enabled: false },
      { label: "Open Anki Generator", click: () => showWindow() },
      { label: "View tasks", click: () => showWindow("/tasks") },
      { type: "separator" },
      { label: "Safely quit", click: () => void requestQuit() },
    ]),
  );
}
function claimNotice(key) {
  const items = readJSON(notificationFile, []);
  if (Array.isArray(items) && items.includes(key)) return false;
  storeJSON(notificationFile, [
    ...(Array.isArray(items) ? items.slice(-99) : []),
    key,
  ]);
  return true;
}
async function pollTasks() {
  if (state.status !== "ready" || !backend.origin) return;
  try {
    const summary = await backend.call("/api/tasks/summary", {
      maximum: 1024 * 1024,
    });
    updateTray(summary.counts);
    const current = new Map(summary.active_runs.map((task) => [task.id, task]));
    if (observedTasks) {
      const ended = [...observedTasks.values()]
        .filter((task) => !current.has(task.id))
        .slice(0, 16);
      for (const old of ended) {
        let task;
        try {
          task = await backend.call(
            `/api/tasks/${encodeURIComponent(old.id)}`,
            { maximum: 8 * 1024 * 1024 },
          );
        } catch {
          current.set(old.id, old);
          continue;
        }
        if (
          !["completed", "failed", "paused", "interrupted"].includes(
            task.status,
          )
        )
          continue;
        if (win?.isFocused() || !Notification.isSupported()) continue;
        const key = `${task.id}:${task.status}:${task.finished_at || task.updated_at || task.created_at}`;
        if (!claimNotice(key)) continue;
        const notice = new Notification({
          title:
            task.status === "completed"
              ? "Your course is ready"
              : task.status === "failed"
                ? "A course task needs attention"
                : "Course task paused",
          body: String(task.course_name || "Course task").slice(0, 160),
          silent: task.status === "completed",
        });
        notice.on("click", () =>
          showWindow(`/tasks/${encodeURIComponent(task.id)}`),
        );
        notice.show();
      }
    }
    const history = await backend.call(
      "/api/tasks?offset=0&limit=24&sort=newest",
      { maximum: 1024 * 1024 },
    );
    if (seenHistory && !win?.isFocused() && Notification.isSupported()) {
      for (const task of history.items) {
        if (
          seenHistory.get(task.id) === task.status ||
          (!seenHistory.has(task.id) &&
            Date.parse(task.created_at) < startedAt) ||
          !["completed", "failed", "paused", "interrupted"].includes(
            task.status,
          )
        )
          continue;
        const key = `${task.id}:${task.status}:${task.finished_at || task.updated_at || task.created_at}`;
        if (!claimNotice(key)) continue;
        const notice = new Notification({
          title:
            task.status === "completed"
              ? "Your course is ready"
              : "A course task needs attention",
          body: String(task.course_name || "Course task").slice(0, 160),
          silent: task.status === "completed",
        });
        notice.on("click", () =>
          showWindow(`/tasks/${encodeURIComponent(task.id)}`),
        );
        notice.show();
      }
    }
    seenHistory = new Map(history.items.map((task) => [task.id, task.status]));
    observedTasks = current;
  } catch {
    /* The renderer shows connection status; child exit handling owns crash recovery. */
  }
}
async function launchBackend() {
  if (
    app.isPackaged &&
    (options["backend-command"] ||
      options["frontend-url"] ||
      options.args.length)
  )
    throw new Error(
      "Development service overrides are unavailable in a packaged application.",
    );
  const command =
    options["backend-command"] ||
    path.join(
      process.resourcesPath,
      "backend",
      process.platform === "win32"
        ? "anki-generator-backend.exe"
        : "anki-generator-backend",
    );
  backend = new BackendSupervisor({ command, args: options.args, paths, log });
  const startingBackend = backend;
  backend.on("state", (next) => {
    setState(next);
    if (next.status === "failed") void startupView();
  });
  const ready = await backend.start();
  while (quitPending && !quitting)
    await new Promise((resolve) => setTimeout(resolve, 25));
  if (
    backend !== startingBackend ||
    quitting ||
    quitAfterRestart ||
    !startingBackend.origin
  )
    return;
  backendVersion = ready.version || ready.health.version;
  if (options["frontend-url"]) {
    const url = new URL(options["frontend-url"]);
    if (
      url.origin !== "http://127.0.0.1:5173" ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    )
      throw new Error("Development frontend must be http://127.0.0.1:5173.");
    frontendOrigin = url.origin;
  }
  await win.loadURL(frontendOrigin || backend.origin);
  if (options.devtools && !app.isPackaged)
    win.webContents.openDevTools({ mode: "detach" });
  clearInterval(pollTimer);
  observedTasks = null;
  void pollTasks();
  pollTimer = setInterval(() => void pollTasks(), 5000);
}
async function awaitShutdown() {
  let stopped = await backend.stop();
  while (!stopped) {
    const answer = await dialog.showMessageBox(win, {
      type: "warning",
      title: "Saving work is taking longer",
      message: "An in-flight operation is still finishing.",
      detail:
        "Keep waiting to save its response and checkpoints. Force quitting preserves earlier durable work, but an unfinished request may need to run again and may incur another charge.",
      buttons: ["Keep waiting", "Force quit…"],
      defaultId: 0,
      cancelId: 0,
    });
    if (answer.response === 1) {
      const confirm = await dialog.showMessageBox(win, {
        type: "warning",
        message: "Force quit the processing service?",
        detail:
          "The current operation may be repeated after recovery. Completed checkpoints remain saved.",
        buttons: ["Keep waiting", "Force quit"],
        defaultId: 0,
        cancelId: 0,
      });
      if (confirm.response === 1) {
        stopped = await backend.stop({ force: true, timeout: 10000 });
        continue;
      }
    }
    stopped = await backend.waitForExit();
  }
}
async function requestQuit() {
  if (quitting || quitPending || unsavedPromptOpen) return;
  if (restarting) {
    quitAfterRestart = true;
    setState({ message: "Finishing the current restart before closing…" });
    return;
  }
  quitPending = true;
  const previousState = { ...state };
  try {
    let active = 0,
      unknown = false;
    if (backend?.origin) {
      try {
        const status = await backend.call("/api/desktop/shutdown-status");
        active = status.active_jobs || 0;
      } catch {
        unknown = true;
      }
    }
    if (active || unknown) {
      const buttons = [
        "Keep application open",
        "Checkpoint & quit",
        ...(tray ? ["Keep running in tray"] : []),
      ];
      const answer = await dialog.showMessageBox(win, {
        type: "question",
        title: "Processing is still active",
        message: unknown
          ? "The processing service could not confirm its current state."
          : `${active} ${active === 1 ? "task is" : "tasks are"} still processing.`,
        detail:
          "Quitting waits for in-flight operations and saves recoverable checkpoints. Queued tasks remain stored. You can keep the application open while other courses finish.",
        buttons,
        defaultId: 0,
        cancelId: 0,
      });
      if (answer.response === 0) return;
      if (answer.response === 2) {
        win.hide();
        return;
      }
    }
    setState({
      status: "stopping",
      message: "Finishing current operations and saving checkpoints…",
      details:
        "Keep this window open until shutdown completes. Saved tasks can be resumed after relaunch.",
    });
    if (!(await startupView())) {
      restoreAfterKeptChanges(previousState);
      return;
    }
    clearInterval(pollTimer);
    if (backend) await awaitShutdown();
    quitting = true;
    app.quit();
  } catch (error) {
    log.write("shutdown-error", { message: error.message });
    await dialog.showMessageBox(win, {
      type: "error",
      message: "The application could not finish shutdown safely.",
      detail:
        "Your workspace remains open. Inspect diagnostics before retrying.",
    });
  } finally {
    quitPending = false;
  }
}
async function restartBackend() {
  if (restarting || quitPending || unsavedPromptOpen)
    throw new Error("A lifecycle operation is already in progress.");
  restarting = true;
  const previousState = { ...state };
  try {
    if (backend?.origin && state.status === "failed") {
      try {
        const health = await backend.call("/api/health");
        if (health.status === "ok") {
          setState({
            status: "ready",
            message: "Your workspace is ready.",
            details: "",
          });
          await win.loadURL(frontendOrigin || backend.origin);
          return { restarted: false, reconnected: true };
        }
      } catch {
        /* Reconnect failed; safely restart the owned service below. */
      }
    }
    if (backend?.origin && state.status === "ready") {
      const status = await backend.call("/api/desktop/shutdown-status");
      if (status.active_jobs || status.queued_jobs) {
        const result = await dialog.showMessageBox(win, {
          type: "warning",
          message: "Restart the processing service?",
          detail:
            "Active tasks will checkpoint and become recoverable. Queued work remains stored. This may take time while requests finish. A session-only API key must be entered again after restart.",
          buttons: ["Keep running", "Checkpoint & restart"],
          defaultId: 0,
          cancelId: 0,
        });
        if (result.response !== 1) return { restarted: false };
      }
    }
    setState({
      status: "starting",
      message: "Reconnecting to your saved workspace…",
      details: "",
    });
    if (!(await startupView())) {
      restoreAfterKeptChanges(previousState);
      return { restarted: false };
    }
    clearInterval(pollTimer);
    if (backend) await awaitShutdown();
    if (quitAfterRestart) return { restarted: false };
    await launchBackend();
    return { restarted: true };
  } catch (error) {
    if (error.code === "STARTUP_CANCELLED" || quitting || quitPending)
      return { restarted: false };
    setState({
      status: "failed",
      message: error.message,
      details:
        "Inspect diagnostics and retry. Your saved workspace has not been replaced.",
    });
    log.write("restart-failed", { message: error.message });
    return { restarted: false };
  } finally {
    restarting = false;
    if (quitAfterRestart) {
      quitAfterRestart = false;
      void requestQuit();
    }
  }
}
async function diagnostics() {
  let service = {};
  try {
    if (backend?.origin)
      service = await backend.call("/api/desktop/diagnostics");
  } catch {
    service = { runtime: "unavailable" };
  }
  return {
    format_version: 1,
    application_version: app.getVersion(),
    electron_version: process.versions.electron,
    chromium_version: process.versions.chrome,
    platform: process.platform,
    architecture: process.arch,
    ...service,
    desktop: {
      status: state.status,
      data_directory: paths.data,
      state_directory: paths.state,
      backend_pid: backend?.child?.pid || null,
    },
    desktop_events: log.entries(),
  };
}
async function exportDiagnostics() {
  try {
    const result = await dialog.showSaveDialog(win, {
      title: "Export safe application diagnostics",
      defaultPath: path.join(
        app.getPath("downloads"),
        "anki-generator-diagnostics.json",
      ),
      filters: [{ name: "Diagnostics JSON", extensions: ["json"] }],
    });
    if (result.canceled || !result.filePath) return { saved: false };
    await fsp.writeFile(
      result.filePath,
      JSON.stringify(await diagnostics(), null, 2),
      { mode: 0o600 },
    );
    return { saved: true };
  } catch {
    await dialog.showMessageBox(win, {
      type: "error",
      message: "Diagnostics could not be saved.",
      detail: "Check the selected destination and try again.",
    });
    return { saved: false };
  }
}
function installIPC() {
  const checked =
    (handler) =>
    async (event, ...args) => {
      if (!trustedFrame(event, win, origins()))
        throw new Error("Desktop action is not available to this frame.");
      return handler(...args);
    };
  ipcMain.handle(
    "desktop:info",
    checked(() => publicInfo()),
  );
  ipcMain.handle(
    "desktop:diagnostics",
    checked(() => diagnostics()),
  );
  ipcMain.handle(
    "desktop:export-diagnostics",
    checked(() => exportDiagnostics()),
  );
  ipcMain.handle(
    "desktop:restart",
    checked(() => restartBackend()),
  );
  ipcMain.handle(
    "desktop:open-directory",
    checked(async (kind) => {
      const directories = {
        data: paths.data,
        logs: paths.logs,
        exports: path.join(paths.data, "exports"),
        downloads: app.getPath("downloads"),
      };
      if (typeof kind !== "string" || !Object.hasOwn(directories, kind))
        throw new Error("Choose a supported application directory.");
      await fsp.mkdir(directories[kind], { recursive: true, mode: 0o700 });
      const error = await shell.openPath(directories[kind]);
      if (error) throw new Error("The desktop could not open this directory.");
      return { opened: true };
    }),
  );
  ipcMain.handle(
    "desktop:open-download",
    checked(async (id, action) => {
      if (
        typeof id !== "string" ||
        !["file", "folder"].includes(action) ||
        !downloads.has(id)
      )
        throw new Error("Choose a file saved by this application session.");
      const file = downloads.get(id);
      if (action === "folder") {
        shell.showItemInFolder(file.path);
        return { opened: true };
      }
      if (!downloadOpenable(file))
        throw new Error(
          "This file type cannot be opened from the application.",
        );
      const error = await shell.openPath(file.path);
      if (error)
        throw new Error("No desktop application could open the saved file.");
      return { opened: true };
    }),
  );
}
if (ownsInstance) {
  app.on("second-instance", () => showWindow());
  app.on("before-quit", (event) => {
    if (!quitting) {
      event.preventDefault();
      void requestQuit();
    }
  });
  app.on("window-all-closed", () => {
    if (!quitting) void requestQuit();
  });
  app.on("activate", () => showWindow());
  app
    .whenReady()
    .then(async () => {
      app.setAppUserModelId("org.anki_generator.AnkiGenerator");
      configureSession();
      installIPC();
      menu();
      await createWindow();
      createTray();
      try {
        await launchBackend();
      } catch (error) {
        if (error.code === "STARTUP_CANCELLED" || quitting || quitPending)
          return;
        setState({
          status: "failed",
          message: error.message,
          details:
            "Inspect diagnostics, check directory permissions, or retry startup.",
        });
        log.write("startup-failed", { message: error.message });
        await startupView();
      }
    })
    .catch((error) => {
      log.write("desktop-initialization-failed", { message: error.message });
      dialog.showErrorBox(
        "Anki Generator could not start",
        "The desktop shell could not initialize. Inspect its private state/logs directory, then relaunch.",
      );
      app.exit(1);
    });
}
