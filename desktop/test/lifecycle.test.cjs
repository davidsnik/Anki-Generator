"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { BackendSupervisor, request } = require("../lib/backend.cjs");
const { desktopPaths, visibleBounds } = require("../lib/paths.cjs");
const {
  injectToken,
  backendOrigin,
  externalLink,
  trustedFrame,
  safeFilename,
  downloadOpenable,
} = require("../lib/security.cjs");
const { redact, DesktopLog } = require("../lib/log.cjs");
async function fixture(t, mode = "ready") {
  const directory = await fs.mkdtemp(
    path.join(os.tmpdir(), "anki-shell-test-"),
  );
  const supervisor = new BackendSupervisor({
    command: process.execPath,
    args: [path.join(__dirname, "backend-fixture.cjs")],
    paths: { data: directory, state: directory },
    env: {
      FIXTURE_MODE: mode,
      PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring",
      OPENAI_API_KEY: "",
    },
    startupTimeout: 4000,
  });
  t.after(async () => {
    await supervisor.stop({ force: true, timeout: 3000 });
    await fs.rm(directory, { recursive: true, force: true });
  });
  return supervisor;
}
test("starts from a private readiness record, authenticates health and shuts down its owned child", async (t) => {
  const backend = await fixture(t);
  const ready = await backend.start();
  assert.match(ready.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.equal(ready.pid, backend.child.pid);
  assert.equal((await backend.call("/api/health")).status, "ok");
  await assert.rejects(
    () => request(ready.origin, "wrong-token", "/api/health"),
    /HTTP 403/,
  );
  assert.equal(await backend.stop({ timeout: 3000 }), true);
  assert.equal(backend.child, null);
  assert.equal(await backend.waitForExit(10), true);
});
test("does not accept wildcard/remote origins or a different process readiness record", async (t) => {
  for (const mode of ["remote", "wrong-pid"]) {
    const backend = await fixture(t, mode);
    await assert.rejects(() => backend.start(), /invalid|private loopback/);
  }
});
test("maps safe startup error codes before trying to construct a server origin", async (t) => {
  const backend = await fixture(t, "storage");
  await assert.rejects(
    () => backend.start(),
    /data or state directory is unavailable/,
  );
});
test("a missing executable reports launch failure and leaves no phantom child to await", async (t) => {
  const backend = await fixture(t);
  backend.options.command = path.join(
    os.tmpdir(),
    "anki-deliberately-missing-executable",
  );
  await assert.rejects(() => backend.start(), /could not start \(ENOENT\)/);
  assert.equal(backend.child, null);
  assert.equal(await backend.stop(), true);
});
test("a delayed startup child exit preserves the curated database failure", async (t) => {
  const backend = await fixture(t, "database-delayed-exit");
  const states = [];
  backend.on("state", (state) => states.push(state));
  const exit = new Promise((resolve) => backend.once("exit", resolve));
  await assert.rejects(
    () => backend.start(),
    /database could not open or migrate/,
  );
  await exit;
  assert.equal(backend.child, null);
  assert.equal(backend.status, "failed");
  const failures = states.filter((state) => state.status === "failed");
  assert.equal(failures.length, 1);
  assert.match(failures[0].message, /database could not open or migrate/);
  assert.match(failures[0].message, /Existing data was retained/);
});
test("unexpected backend termination surfaces recoverable failure rather than silently restarting", async (t) => {
  const backend = await fixture(t);
  const states = [];
  backend.on("state", (state) => states.push(state));
  await backend.start();
  const exit = new Promise((resolve) => backend.once("exit", resolve));
  backend.child.kill("SIGKILL");
  await exit;
  assert.equal(backend.status, "failed");
  assert.equal(backend.origin, null);
  assert.match(states.at(-1).message, /stopped unexpectedly/);
});
test("shutdown timeout retains ownership until the user explicitly permits force termination", async (t) => {
  const backend = await fixture(t, "slow-stop");
  await backend.start();
  assert.equal(await backend.stop({ timeout: 120 }), false);
  assert.ok(backend.child);
  assert.equal(await backend.stop({ force: true, timeout: 3000 }), true);
});
test("desktop token is injected only for the exact owned origin and stripped on redirects", () => {
  const headers = {
    "X-Desktop-Token": "renderer-value",
    Accept: "application/json",
  };
  assert.equal(
    injectToken(
      "http://127.0.0.1:38111/api/health",
      headers,
      "http://127.0.0.1:38111",
      "secret",
    )["X-Desktop-Token"],
    "secret",
  );
  for (const url of [
    "http://127.0.0.1:38112/api/health",
    "https://example.com",
    "http://127.0.0.1.evil.example:38111/",
  ])
    assert.equal(
      injectToken(url, headers, "http://127.0.0.1:38111", "secret")[
        "X-Desktop-Token"
      ],
      undefined,
    );
  assert.throws(() => backendOrigin("http://0.0.0.0:80"));
  assert.throws(() => backendOrigin("http://user:password@127.0.0.1:80"));
  assert.equal(externalLink("javascript:alert(1)"), null);
  assert.equal(externalLink("file:///tmp/file"), null);
  assert.equal(
    externalLink("https://docs.ankiweb.net/"),
    "https://docs.ankiweb.net/",
  );
});
test("privileged IPC requires the owned main frame, not an iframe or other window", () => {
  const mainFrame = { origin: "http://127.0.0.1:1234" };
  const webContents = { mainFrame };
  const window = { webContents, isDestroyed: () => false };
  const origins = new Set([mainFrame.origin]);
  assert.equal(
    trustedFrame(
      { sender: webContents, senderFrame: mainFrame },
      window,
      origins,
    ),
    true,
  );
  assert.equal(
    trustedFrame(
      { sender: webContents, senderFrame: { origin: mainFrame.origin } },
      window,
      origins,
    ),
    false,
  );
  assert.equal(
    trustedFrame({ sender: {}, senderFrame: mainFrame }, window, origins),
    false,
  );
  assert.equal(
    trustedFrame(
      { sender: webContents, senderFrame: mainFrame },
      window,
      new Set(["https://example.com"]),
    ),
    false,
  );
});
test("persistent XDG paths are independent of executable location and current directory", () => {
  const actual = desktopPaths(
    {
      XDG_DATA_HOME: "/tmp/data",
      XDG_STATE_HOME: "/tmp/state",
      XDG_CACHE_HOME: "/tmp/cache",
    },
    "/home/fixture",
  );
  assert.equal(actual.data, "/tmp/data/anki-generator");
  assert.equal(actual.state, "/tmp/state/anki-generator");
  assert.equal(
    desktopPaths({}, "/home/fixture").data,
    "/home/fixture/.local/share/anki-generator",
  );
  assert.throws(() =>
    desktopPaths({}, "/home/fixture", { data: "relative/path" }),
  );
  assert.equal(
    desktopPaths(
      { XDG_DATA_HOME: "relative/path", XDG_STATE_HOME: "../state" },
      "/home/fixture",
    ).data,
    "/home/fixture/.local/share/anki-generator",
  );
  assert.throws(() =>
    desktopPaths({}, "/home/fixture", { data: "/tmp/invalid\0path" }),
  );
});
test("window bounds recover when a saved display is disconnected", () => {
  const displays = [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }];
  assert.deepEqual(
    visibleBounds({ x: 9000, y: 9000, width: 1200, height: 800 }, displays),
    { width: 1200, height: 800, maximized: false },
  );
  assert.equal(
    visibleBounds(
      { x: 50, y: 50, width: 1200, height: 800, maximized: true },
      displays,
    ).x,
    50,
  );
});
test("logs redact secrets, filenames cannot traverse, and rotation stays bounded", async (t) => {
  assert.equal(safeFilename("../../secret\n.apkg"), ".._.._secret_.apkg");
  assert.equal(
    redact("Bearer abc.def api_key=sk-123456789 token-value", [
      "token-value",
    ]).includes("token-value"),
    false,
  );
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "anki-log-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const log = new DesktopLog(dir, ["private-token"]);
  await fs.writeFile(log.file, "x".repeat(1024 * 1024 + 1));
  log.write("test", { value: "private-token" });
  assert.equal((await fs.stat(`${log.file}.1`)).size, 1024 * 1024 + 1);
  assert.ok(log.entries()[0].includes("[redacted]"));
});

test("opening a saved export refuses executable extensions even after a destination rename", () => {
  assert.equal(
    downloadOpenable({ filename: "cards.apkg", path: "/tmp/cards.apkg" }),
    true,
  );
  assert.equal(
    downloadOpenable({ filename: "cards.apkg", path: "/tmp/cards.desktop" }),
    false,
  );
  assert.equal(
    downloadOpenable({ filename: "script.sh", path: "/tmp/script.sh" }),
    false,
  );
});

test("stop before spawn cancels pending startup and removes its private handoff directory", async (t) => {
  const backend = await fixture(t);
  const chmod = fs.chmod.bind(fs);
  let release, entered;
  const blocked = new Promise((resolve) => (release = resolve)),
    atChmod = new Promise((resolve) => (entered = resolve));
  let temporary,
    spawns = 0;
  t.mock.method(fs, "chmod", async (directory, mode) => {
    temporary = directory;
    entered();
    await blocked;
    return chmod(directory, mode);
  });
  backend.options.spawn = () => {
    spawns++;
    throw new Error("must not spawn");
  };
  const starting = backend.start();
  const rejected = assert.rejects(
    starting,
    (error) => error.code === "STARTUP_CANCELLED",
  );
  await atChmod;
  assert.equal(await backend.stop({ timeout: 20 }), true);
  release();
  await rejected;
  assert.equal(spawns, 0);
  await assert.rejects(fs.stat(temporary), { code: "ENOENT" });
});
test("stop after spawn cancels readiness instead of publishing a failed or ready workspace", async (t) => {
  const backend = await fixture(t, "gated-ready");
  const spawn = require("node:child_process").spawn;
  let resolveSpawn;
  const spawned = new Promise((resolve) => (resolveSpawn = resolve));
  let readies = 0;
  backend.on("ready", () => readies++);
  backend.options.spawn = (...args) => {
    const child = spawn(...args);
    child.once("spawn", resolveSpawn);
    return child;
  };
  const starting = backend.start();
  const rejected = assert.rejects(
    starting,
    (error) => error.code === "STARTUP_CANCELLED",
  );
  await spawned;
  assert.equal(await backend.stop({ timeout: 3000 }), true);
  await rejected;
  assert.equal(readies, 0);
  assert.notEqual(backend.status, "failed");
  assert.equal(backend.child, null);
});
