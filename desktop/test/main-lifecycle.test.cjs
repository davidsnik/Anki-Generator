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
  const nativeDialogs = [];
  const fakeElectron = {
    app,
    protocol: { registerSchemesAsPrivileged() {} },
    Notification: { isSupported: () => false },
    dialog: {
      showMessageBox: async (...args) => {
        nativeDialogs.push(args.at(-1));
        return { response: 0 };
      },
      showMessageBoxSync: (...args) => {
        nativeDialogs.push(args.at(-1));
        return 0;
      },
    },
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
    dialog: fakeElectron.dialog,
    nativeDialogs,
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

test("keeping an unsaved draft cancels quit before stopping the service and restores ready state", async (t) => {
  const h = await harness(t);
  let stops = 0;
  h.context.fixtureBackend = {
    origin: "http://127.0.0.1:12345",
    call: async () => ({ active_jobs: 0 }),
    stop: async () => {
      stops++;
      return true;
    },
  };
  h.context.fixtureWindow.webContents.getURL = () =>
    "http://127.0.0.1:12345/courses/fixture/cards";
  let overridden = false;
  h.context.fixtureWindow.loadURL = async () => {
    h.context.fixtureUnload = {
      preventDefault: () => {
        overridden = true;
      },
    };
    h.run("confirmUnsavedChanges(win,fixtureUnload)");
    if (!overridden)
      throw Object.assign(new Error("Navigation cancelled"), {
        code: "ERR_ABORTED",
      });
  };
  h.run(
    'backend=fixtureBackend;state={status:"ready",message:"Your workspace is ready.",details:""}',
  );
  await h.run("requestQuit()");
  assert.equal(stops, 0);
  assert.equal(overridden, false);
  assert.equal(h.run("state.status"), "ready");
  assert.equal(h.run("quitting"), false);
  assert.equal(h.run("quitPending"), false);
  assert.equal(h.nativeDialogs.length, 1);
  assert.deepEqual(
    [...h.nativeDialogs[0].buttons],
    ["Keep editing", "Discard changes"],
  );
  assert.equal(h.nativeDialogs[0].defaultId, 0);
  assert.equal(h.nativeDialogs[0].cancelId, 0);
});

test("explicit discard permits unload then drains the service and quits", async (t) => {
  const h = await harness(t);
  h.dialog.showMessageBoxSync = () => 1;
  let stopped = false,
    overridden = false;
  h.context.fixtureBackend = {
    origin: "http://127.0.0.1:12345",
    call: async () => ({ active_jobs: 0 }),
    stop: async () => {
      assert.equal(overridden, true);
      stopped = true;
      return true;
    },
  };
  h.context.fixtureWindow.webContents.getURL = () =>
    "http://127.0.0.1:12345/courses/fixture/cards";
  h.context.fixtureWindow.loadURL = async () => {
    h.context.fixtureUnload = {
      preventDefault: () => {
        overridden = true;
      },
    };
    h.run("confirmUnsavedChanges(win,fixtureUnload)");
  };
  h.run('backend=fixtureBackend;state={status:"ready"}');
  await h.run("requestQuit()");
  await h.quit;
  assert.equal(stopped, true);
  assert.equal(h.run("quitting"), true);
});

test("keeping an unsaved draft cancels restart without replacing the service", async (t) => {
  const h = await harness(t);
  let stops = 0,
    launches = 0;
  h.context.fixtureBackend = {
    origin: "http://127.0.0.1:12345",
    call: async () => ({ active_jobs: 0, queued_jobs: 0 }),
    stop: async () => {
      stops++;
      return true;
    },
  };
  h.context.replacement = async () => {
    launches++;
  };
  h.context.fixtureWindow.webContents.getURL = () =>
    "http://127.0.0.1:12345/courses/fixture/cards";
  h.context.fixtureWindow.loadURL = async () => {
    h.context.fixtureUnload = {
      preventDefault() {
        throw new Error("Keep must not override unload veto");
      },
    };
    h.run("confirmUnsavedChanges(win,fixtureUnload)");
    throw Object.assign(new Error("Navigation cancelled"), {
      code: "ERR_ABORTED",
    });
  };
  h.run(
    'backend=fixtureBackend;state={status:"ready",message:"Ready"};launchBackend=replacement',
  );
  const result = await h.run("restartBackend()");
  assert.equal(result.restarted, false);
  assert.equal(stops, 0);
  assert.equal(launches, 0);
  assert.equal(h.run("state.status"), "ready");
  assert.equal(h.run("restarting"), false);
  assert.equal(h.nativeDialogs.length, 1);
});

test("a genuine failed navigation remains a lifecycle error instead of looking like user cancellation", async (t) => {
  const h = await harness(t);
  h.context.fixtureWindow.loadURL = async () => {
    throw Object.assign(new Error("Unrelated navigation failure"), {
      code: "ERR_ABORTED",
    });
  };
  h.context.fixtureWindow.webContents.getURL = () => "http://127.0.0.1:12345/";
  h.run('state={status:"ready"}');
  await h.run("requestQuit()");
  assert.equal(
    h.nativeDialogs[0].message,
    "The application could not finish shutdown safely.",
  );
  assert.equal(h.run("quitting"), false);
});

test("a failure arriving during the native unsaved decision is not overwritten with stale ready state", async (t) => {
  const h = await harness(t);
  h.context.fixtureBackend = {
    status: "ready",
    origin: "http://127.0.0.1:12345",
    call: async () => ({ active_jobs: 0 }),
  };
  h.context.fixtureWindow.webContents.getURL = () =>
    "http://127.0.0.1:12345/cards";
  h.dialog.showMessageBoxSync = () => {
    h.run(
      'backend.status="failed";setState({status:"failed",message:"The service stopped"})',
    );
    return 0;
  };
  h.context.fixtureWindow.loadURL = async () => {
    h.context.fixtureUnload = { preventDefault() {} };
    h.run("confirmUnsavedChanges(win,fixtureUnload)");
    throw Object.assign(new Error("Navigation cancelled"), {
      code: "ERR_ABORTED",
    });
  };
  h.run('backend=fixtureBackend;state={status:"ready"}');
  await h.run("requestQuit()");
  assert.equal(h.run("state.status"), "failed");
  assert.equal(h.run("state.message"), "The service stopped");
});

test("the native unsaved prompt rejects nested lifecycle requests without queuing another quit", async (t) => {
  const h = await harness(t);
  h.dialog.showMessageBoxSync = () => {
    assert.equal(h.run("unsavedPromptOpen"), true);
    h.run("requestQuit()");
    return 0;
  };
  h.run("restarting=true");
  h.context.fixtureUnload = { preventDefault() {} };
  h.run("confirmUnsavedChanges(win,fixtureUnload)");
  assert.equal(h.run("quitAfterRestart"), false);
  assert.equal(h.run("unsavedPromptOpen"), false);
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
