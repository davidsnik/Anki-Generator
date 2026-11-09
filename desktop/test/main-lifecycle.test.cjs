"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { createRequire } = require("node:module");
const mainFile = path.join(__dirname, "..", "main.cjs");
const requireMain = createRequire(mainFile);
function deferred() {
  let resolve;
  const promise = new Promise((done) => (resolve = done));
  return { promise, resolve };
}
async function harness(t, Backend) {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), "anki-main-test-"));
  t.after(() => fsp.rm(root, { recursive: true, force: true }));
  const quit = deferred(),
    loaded = [];
  const app = {
    isPackaged: false,
    setName() {},
    setPath() {},
    requestSingleInstanceLock: () => false,
    quit: () => quit.resolve(),
    getVersion: () => "fixture",
    getPath: () => root,
  };
  const fakeElectron = {
    app,
    protocol: { registerSchemesAsPrivileged() {} },
    Notification: { isSupported: () => false },
    dialog: { showMessageBox: async () => ({ response: 0 }) },
  };
  const fakeProcess = {
    ...process,
    argv: [],
    env: { XDG_DATA_HOME: root, XDG_STATE_HOME: root, XDG_CACHE_HOME: root },
    resourcesPath: root,
  };
  const context = vm.createContext({
    require: (id) =>
      id === "electron"
        ? fakeElectron
        : id === "./lib/backend.cjs" && Backend
          ? { BackendSupervisor: Backend }
          : requireMain(id),
    __dirname: path.dirname(mainFile),
    process: fakeProcess,
    console,
    URL,
    Response,
    Map,
    Set,
    Buffer,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  });
  vm.runInContext(fs.readFileSync(mainFile, "utf8"), context, {
    filename: mainFile,
  });
  // The fake second instance exits at initialization; reset its observer for lifecycle work.
  const actualQuit = deferred();
  app.quit = () => actualQuit.resolve();
  context.fixtureWindow = {
    isDestroyed: () => false,
    isFocused: () => true,
    webContents: { getURL: () => "anki-shell://startup/", send() {} },
    loadURL: async (url) => loaded.push(url),
  };
  vm.runInContext("win=fixtureWindow", context);
  return {
    context,
    loaded,
    quit: actualQuit.promise,
    run: (source) => vm.runInContext(source, context),
  };
}
test("closing while a restart drains the old service queues quit and skips replacement spawn", async (t) => {
  const h = await harness(t);
  const drain = deferred();
  let stops = 0,
    launches = 0;
  const backend = {
    origin: "http://127.0.0.1:12345",
    child: { pid: 123 },
    call: async () => ({ active_jobs: 0, queued_jobs: 0 }),
    stop: async () => {
      stops++;
      if (stops === 1) await drain.promise;
      backend.child = null;
      backend.origin = null;
      return true;
    },
  };
  h.context.fixtureBackend = backend;
  h.context.replacement = async () => {
    launches++;
  };
  h.run(
    'backend=fixtureBackend;state={status:"ready"};launchBackend=replacement',
  );
  const restart = h.run("restartBackend()");
  while (stops === 0) await new Promise((resolve) => setImmediate(resolve));
  await h.run("requestQuit()");
  assert.equal(h.run("quitAfterRestart"), true);
  drain.resolve();
  await restart;
  await h.quit;
  assert.equal(launches, 0);
  assert.equal(h.run("quitting"), true);
  assert.equal(backend.child, null);
});
test("quit during startup cannot load a late ready renderer or leave a replacement service", async (t) => {
  const ready = deferred();
  let instance;
  class Backend extends EventEmitter {
    constructor() {
      super();
      this.child = { pid: 123 };
      this.origin = null;
      instance = this;
    }
    start() {
      return ready.promise;
    }
    async stop() {
      this.child = null;
      return true;
    }
  }
  const h = await harness(t, Backend);
  const launch = h.run("launchBackend()");
  await h.run("requestQuit()");
  await h.quit;
  instance.origin = "http://127.0.0.1:54321";
  ready.resolve({ version: "fixture", health: { version: "fixture" } });
  await launch;
  assert.deepEqual(h.loaded, []);
  assert.equal(instance.child, null);
  assert.equal(h.run("quitting"), true);
});
