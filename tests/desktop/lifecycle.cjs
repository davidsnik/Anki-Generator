/* Actual final Linux distribution lifecycle tests; no production test mode. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { spawn } = require("node:child_process");
const {
  _electron: electron,
  expect: baseExpect,
} = require("../../frontend/node_modules/@playwright/test");
const { launch } = require("./launch-smoke.cjs");
const expect = baseExpect.configure({ timeout: 30000 });
const ROOT = path.resolve(__dirname, "../..");
const windows = new Set();
const ownedBackends = new Set();

function environment(workspace) {
  const value = {
    ...process.env,
    APPIMAGE_EXTRACT_AND_RUN: "1",
    XDG_DATA_HOME: path.join(workspace, "data"),
    XDG_STATE_HOME: path.join(workspace, "state"),
    XDG_CONFIG_HOME: path.join(workspace, "config"),
    XDG_CACHE_HOME: path.join(workspace, "cache"),
    OPENAI_API_KEY: "",
    PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring",
  };
  delete value.ELECTRON_RUN_AS_NODE;
  delete value.NODE_OPTIONS;
  return value;
}
async function sandboxed(app) {
  const actual = await app.evaluate(({ BrowserWindow }) => {
    const prefs =
      BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
    return {
      sandbox: prefs.sandbox,
      isolation: prefs.contextIsolation,
      node: prefs.nodeIntegration,
      noSandbox: process.argv.includes("--no-sandbox"),
    };
  });
  assert.equal(actual.sandbox, true);
  assert.equal(actual.isolation, true);
  assert.equal(actual.node, false);
  assert.equal(
    actual.noSandbox,
    false,
    "Playwright must not disable Chromium sandboxing",
  );
  return actual;
}
async function rawLaunch(artifact, workspace) {
  await fs.mkdir(workspace, { recursive: true });
  const app = await electron.launch({
    executablePath: artifact,
    chromiumSandbox: true,
    cwd: workspace,
    env: environment(workspace),
    timeout: 120000,
  });
  windows.add(app);
  const page = await app.firstWindow({ timeout: 120000 });
  page.setDefaultTimeout(30000);
  await sandboxed(app);
  await page.waitForFunction(() => !!window.ankiDesktop);
  return { app, page, workspace };
}
async function readyLaunch(artifact, workspace, overrides = {}) {
  await fs.mkdir(workspace, { recursive: true });
  const current = await launch(artifact, workspace, overrides);
  current.workspace = workspace;
  windows.add(current.app);
  await sandboxed(current.app);
  return current;
}
async function pidOf(page) {
  const diagnostics = await page.evaluate(() =>
    window.ankiDesktop.diagnostics(),
  );
  const pid = diagnostics.desktop.backend_pid;
  assert(Number.isInteger(pid) && pid > 1);
  ownedBackends.add(pid);
  return pid;
}
async function dead(pid) {
  await expect
    .poll(
      () => {
        try {
          process.kill(pid, 0);
          return false;
        } catch (error) {
          if (error.code === "ESRCH") return true;
          throw error;
        }
      },
      { timeout: 30000 },
    )
    .toBe(true);
  ownedBackends.delete(pid);
}
async function close(current) {
  if (!current || !windows.has(current.app)) return;
  await current.app
    .evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => ({ response: 1 });
    })
    .catch(() => {});
  await current.app.close();
  windows.delete(current.app);
}
async function events(workspace) {
  try {
    return (
      await fs.readFile(
        path.join(workspace, "state/anki-generator/logs/desktop.log"),
        "utf8",
      )
    )
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}
async function secondInstanceExit(child, description) {
  let deadline;
  try {
    return await Promise.race([
      new Promise((resolve, reject) => {
        child.once("error", reject);
        child.once("exit", resolve);
      }),
      new Promise((_resolve, reject) => {
        deadline = setTimeout(() => {
          child.kill("SIGTERM");
          reject(new Error(description));
        }, 30000);
      }),
    ]);
  } finally {
    clearTimeout(deadline);
  }
}
async function diagnosticExport(current, destination) {
  await current.app.evaluate(({ dialog }, filePath) => {
    dialog.showSaveDialog = async () => ({ canceled: false, filePath });
  }, destination);
  await current.page
    .getByRole("button", { name: "Export diagnostics", exact: true })
    .click();
  await expect
    .poll(async () => {
      try {
        return (await fs.stat(destination)).size;
      } catch {
        return 0;
      }
    })
    .toBeGreaterThan(0);
  const text = await fs.readFile(destination, "utf8");
  const report = JSON.parse(text);
  assert.equal(report.desktop.status, "failed");
  assert(!text.includes("ANKI_GENERATOR_DESKTOP_TOKEN"));
  assert(!text.includes("sk-"));
  return report;
}
async function failed(current, message) {
  await expect(
    current.page.getByRole("heading", {
      name: "Let’s get your workspace back.",
    }),
  ).toBeVisible({ timeout: 120000 });
  await expect(current.page.locator("#message")).toContainText(message);
  await expect(
    current.page.getByRole("button", { name: "Retry startup", exact: true }),
  ).toBeVisible();
  await expect(
    current.page.getByRole("button", {
      name: "Export diagnostics",
      exact: true,
    }),
  ).toBeVisible();
}
async function dashboard(current) {
  await expect(
    current.page.getByRole("heading", {
      name: "Good things take understanding.",
    }),
  ).toBeVisible({ timeout: 120000 });
}
async function createFixture(page, name) {
  await page
    .getByRole("button", { name: "Create course", exact: true })
    .first()
    .click();
  await page.getByLabel("Course name", { exact: true }).fill(name);
  await page
    .getByRole("button", { name: "Create course", exact: true })
    .last()
    .click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  const courseId = page.url().match(/\/courses\/([^/]+)/)[1];
  await page.locator("input[type=file]:not([webkitdirectory])").setInputFiles({
    name: "lifecycle-lecture.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "For a right triangle, a^2 + b^2 = c^2. Synthetic lifecycle evidence.",
    ),
  });
  await page
    .getByRole("button", { name: "Import materials", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "lifecycle-lecture.txt", exact: true }),
  ).toBeVisible();
  return courseId;
}

async function recoveryAndInstances(artifact, directory) {
  let current = await readyLaunch(artifact, directory);
  try {
    const name = "Packaged lifecycle persistence fixture";
    const courseId = await createFixture(current.page, name);
    const before = await pidOf(current.page);
    const oldOrigin = new URL(current.page.url()).origin;
    process.kill(before, "SIGKILL");
    await failed(current, "stopped unexpectedly");
    await dead(before);
    await diagnosticExport(
      current,
      path.join(directory, "crash-diagnostics.json"),
    );
    await current.page.screenshot({
      path: path.join(directory, "backend-crash.png"),
    });
    await current.page
      .getByRole("button", { name: "Retry startup", exact: true })
      .click();
    await dashboard(current);
    const recovered = await pidOf(current.page);
    assert.notEqual(recovered, before);
    assert.notEqual(new URL(current.page.url()).origin, oldOrigin);
    await current.page.goto(
      new URL(`/courses/${courseId}/documents`, current.page.url()).href,
    );
    await expect(
      current.page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    await expect(
      current.page.getByRole("button", {
        name: "lifecycle-lecture.txt",
        exact: true,
      }),
    ).toBeVisible();
    await current.app.evaluate(({ app, BrowserWindow }) => {
      global.__lifecycleSecondInstances = 0;
      app.on("second-instance", () => {
        global.__lifecycleSecondInstances++;
      });
      BrowserWindow.getAllWindows()[0].hide();
    });
    const second = spawn(artifact, [], {
      cwd: directory,
      env: environment(directory),
      stdio: ["ignore", "ignore", "pipe"],
    });
    let stderr = "";
    second.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk.toString()).slice(-4000);
    });
    const secondExit = await secondInstanceExit(
      second,
      `Second instance did not exit: ${stderr}`,
    );
    assert.equal(secondExit, 0);
    await expect
      .poll(() => current.app.evaluate(() => global.__lifecycleSecondInstances))
      .toBe(1);
    assert.equal(
      await current.app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].isVisible(),
      ),
      true,
    );
    assert.equal(await pidOf(current.page), recovered);
    assert.equal(
      (await events(directory)).filter(
        (item) => item.event === "backend-spawned",
      ).length,
      2,
    );
    const bounds = await current.app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (win.isMaximized()) win.unmaximize();
      win.setBounds({ x: 66, y: 77, width: 1110, height: 780 });
      return win.getNormalBounds();
    });
    await expect
      .poll(async () => {
        try {
          const saved = JSON.parse(
            await fs.readFile(
              path.join(directory, "state/anki-generator/window.json"),
              "utf8",
            ),
          );
          return saved;
        } catch {
          return [];
        }
      })
      .toEqual({ ...bounds, maximized: false });
    const windowPlatform = await current.app.evaluate(({ app }) =>
      app.commandLine.getSwitchValue("ozone-platform"),
    );
    await close(current);
    await dead(recovered);
    current = await readyLaunch(artifact, directory);
    const restored = await current.app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].getNormalBounds(),
    );
    assert.deepEqual(
      [restored.width, restored.height],
      [bounds.width, bounds.height],
    );
    // Native Wayland compositors own placement. Electron documents positioning
    // as unsupported there; the stored coordinates still prove persistence.
    if (windowPlatform !== "wayland") assert.deepEqual(restored, bounds);
    await current.page.goto(
      new URL(`/courses/${courseId}/documents`, current.page.url()).href,
    );
    await expect(
      current.page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    await expect(
      current.page.getByRole("button", {
        name: "lifecycle-lecture.txt",
        exact: true,
      }),
    ).toBeVisible();
    const finalPid = await pidOf(current.page);
    await current.page.screenshot({
      path: path.join(directory, "recovered-persistence.png"),
    });
    await close(current);
    await dead(finalPid);
    current = null;
    return {
      passed: true,
      courseId,
      recoveredBackendPid: recovered,
      secondInstanceExited: true,
      rememberedBounds: {
        saved: bounds,
        restored,
        platform: windowPlatform,
        compositorOwnsPlacement: windowPlatform === "wayland",
      },
    };
  } finally {
    await close(current);
  }
}
async function missingResources(unpacked, directory) {
  const copy = path.join(directory, "payload");
  await fs.cp(unpacked, copy, { recursive: true, preserveTimestamps: true });
  const executable = path.join(copy, "anki-generator");
  const backend = path.join(copy, "resources/backend/anki-generator-backend");
  const index = path.join(
    copy,
    "resources/backend/_internal/anki_generator/web_assets/index.html",
  );
  let current;
  try {
    await fs.rename(backend, `${backend}.disabled`);
    const missingBinary = path.join(directory, "missing-binary");
    current = await rawLaunch(executable, missingBinary);
    await failed(current, "ENOENT");
    await diagnosticExport(
      current,
      path.join(missingBinary, "diagnostics.json"),
    );
    await current.page.screenshot({
      path: path.join(missingBinary, "startup-error.png"),
    });
    await fs.rename(`${backend}.disabled`, backend);
    await current.page
      .getByRole("button", { name: "Retry startup", exact: true })
      .click();
    await dashboard(current);
    const recoveredPid = await pidOf(current.page);
    await close(current);
    await dead(recoveredPid);
    current = null;
    await fs.rename(index, `${index}.disabled`);
    const missingFrontend = path.join(directory, "missing-frontend");
    current = await rawLaunch(executable, missingFrontend);
    await failed(current, "resources are missing");
    await diagnosticExport(
      current,
      path.join(missingFrontend, "diagnostics.json"),
    );
    await current.page.screenshot({
      path: path.join(missingFrontend, "startup-error.png"),
    });
    await fs.rename(`${index}.disabled`, index);
    await current.page
      .getByRole("button", { name: "Retry startup", exact: true })
      .click();
    await dashboard(current);
    const secondPid = await pidOf(current.page);
    await close(current);
    await dead(secondPid);
    current = null;
    return {
      passed: true,
      modifiedCopyOnly: copy,
      missingExecutableRecovered: true,
      missingFrontendRecovered: true,
    };
  } finally {
    await close(current);
    await fs.rename(`${backend}.disabled`, backend).catch(() => {});
    await fs.rename(`${index}.disabled`, index).catch(() => {});
  }
}
async function corruptDatabase(artifact, directory) {
  const data = path.join(directory, "data/anki-generator");
  await fs.mkdir(data, { recursive: true });
  const file = path.join(data, "application.sqlite3");
  const bytes = Buffer.from(
    "Deliberately corrupted synthetic SQLite lifecycle fixture.",
  );
  await fs.writeFile(file, bytes, { mode: 0o600 });
  let current = await rawLaunch(artifact, directory);
  try {
    await failed(current, "database");
    assert.deepEqual(await fs.readFile(file), bytes);
    await diagnosticExport(current, path.join(directory, "diagnostics.json"));
    await current.page.screenshot({
      path: path.join(directory, "database-error.png"),
    });
    await current.page
      .getByRole("button", { name: "Retry startup", exact: true })
      .click();
    await failed(current, "database");
    assert.deepEqual(
      await fs.readFile(file),
      bytes,
      "Retry must not silently reset the database",
    );
    await close(current);
    current = null;
    return {
      passed: true,
      corruptedDatabaseRetained: true,
      retryAndDiagnosticsAvailable: true,
    };
  } finally {
    await close(current);
  }
}
async function quitDuringStartup(artifact, directory) {
  const current = await rawLaunch(artifact, directory);
  try {
    const info = await current.page.evaluate(() => window.ankiDesktop.info());
    assert.equal(
      info.status,
      "starting",
      "Observe the real startup phase before closing",
    );
    const closed = current.app.waitForEvent("close", { timeout: 30000 });
    await current.app
      .evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
      .catch((error) => {
        if (!/closed|Target/.test(error.message)) throw error;
      });
    await closed;
    windows.delete(current.app);
    const spawned = (await events(directory)).filter(
      (item) => item.event === "backend-spawned",
    );
    for (const event of spawned) {
      ownedBackends.add(event.pid);
      await dead(event.pid);
    }
    return {
      passed: true,
      observedStatus: info.status,
      backendProcessesReaped: spawned.length,
    };
  } finally {
    await close(current);
  }
}
async function quitDuringRestart(artifact, directory) {
  const current = await readyLaunch(artifact, directory);
  let pid;
  try {
    pid = await pidOf(current.page);
    await current.app.evaluate((_electron, backendPid) => {
      const { ChildProcess } = process.getBuiltinModule("child_process");
      const original = ChildProcess.prototype.kill;
      ChildProcess.prototype.kill = function (signal) {
        if (signal === "SIGTERM" && this.pid === backendPid) {
          original.call(this, "SIGSTOP");
          global.__lifecycleHeldStop = backendPid;
        }
        return original.call(this, signal);
      };
    }, pid);
    await current.page.evaluate(() => {
      void window.ankiDesktop.restartBackend();
    });
    await expect
      .poll(() =>
        current.app.evaluate(() => global.__lifecycleHeldStop || null),
      )
      .toBe(pid);
    const closed = current.app.waitForEvent("close", { timeout: 30000 });
    await current.app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    process.kill(pid, "SIGCONT");
    await closed;
    windows.delete(current.app);
    await dead(pid);
    const spawned = (await events(directory)).filter(
      (item) => item.event === "backend-spawned",
    );
    assert.equal(
      spawned.length,
      1,
      "A queued quit must not launch a replacement backend",
    );
    return {
      passed: true,
      controlledOsSignalBarrier: true,
      backendSpawns: spawned.length,
    };
  } finally {
    if (pid) {
      try {
        process.kill(pid, "SIGCONT");
      } catch {}
    }
    await close(current);
  }
}
async function api(page, route, method = "GET", body) {
  return page.evaluate(
    async ({ route, method, body }) => {
      const bootstrap = await (await fetch("/api/bootstrap")).json();
      const response = await fetch(route, {
        method,
        headers: {
          "X-CSRF-Token": bootstrap.csrf_token,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok)
        throw new Error(
          `Lifecycle API ${route}: ${response.status} ${await response.text()}`,
        );
      return response.json();
    },
    { route, method, body },
  );
}
async function keepRunningInTray(artifact, directory) {
  const key = "sk-controlled-packaged-desktop-no-paid-requests";
  const ready = path.join(directory, "provider.json");
  await fs.mkdir(directory, { recursive: true });
  const provider = spawn(
    path.join(ROOT, ".venv/bin/python"),
    ["-m", "tests.support.desktop_provider_server", "--ready-file", ready],
    { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] },
  );
  let current, origin, documentId;
  const control = async (route, body) => {
    const response = await fetch(origin + route, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!response.ok)
      throw new Error(`Lifecycle provider control: ${response.status}`);
    return response.json();
  };
  try {
    await expect
      .poll(async () => {
        try {
          origin = JSON.parse(await fs.readFile(ready, "utf8")).origin;
          return !!origin;
        } catch {
          assert.equal(provider.exitCode, null);
          return false;
        }
      })
      .toBe(true);
    current = await readyLaunch(artifact, directory, {
      OPENAI_BASE_URL: origin + "/v1/",
    });
    const info = await current.page.evaluate(() => window.ankiDesktop.info());
    if (!info.tray_available)
      return {
        skipped: true,
        reason: "No desktop tray was available in this session.",
      };
    const pid = await pidOf(current.page);
    const courseId = await createFixture(
      current.page,
      "Synthetic tray lifecycle fixture",
    );
    documentId = (
      await api(current.page, `/api/courses/${courseId}/documents`)
    )[0].id;
    await api(current.page, "/api/settings/key", "PUT", {
      api_key: key,
      persist: false,
    });
    await control("/control/gates", { document_ids: [documentId] });
    const run = await api(
      current.page,
      `/api/courses/${courseId}/runs`,
      "POST",
      { mode: "generate", consent: true },
    );
    await expect
      .poll(
        async () => {
          const response = await fetch(origin + "/control", {
            headers: { Authorization: `Bearer ${key}` },
          });
          return (await response.json()).waiting;
        },
        { timeout: 90000 },
      )
      .toEqual([documentId]);
    await current.app.evaluate(({ dialog }) => {
      global.__lifecycleTrayPrompt = null;
      dialog.showMessageBox = async (_window, options) => {
        global.__lifecycleTrayPrompt = options;
        return { response: 2 };
      };
    });
    await current.app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await expect
      .poll(() =>
        current.app.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0].isVisible(),
        ),
      )
      .toBe(false);
    const prompt = await current.app.evaluate(
      () => global.__lifecycleTrayPrompt,
    );
    assert.equal(prompt.buttons[2], "Keep running in tray");
    assert.equal(await pidOf(current.page), pid);
    assert.equal(
      (await api(current.page, `/api/runs/${run.id}`)).status,
      "running",
    );
    const second = spawn(artifact, [], {
      cwd: directory,
      env: environment(directory),
      stdio: "ignore",
    });
    assert.equal(
      await secondInstanceExit(
        second,
        "Tray restoration second instance did not exit",
      ),
      0,
    );
    await expect
      .poll(() =>
        current.app.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0].isVisible(),
        ),
      )
      .toBe(true);
    assert.equal(await pidOf(current.page), pid);
    await current.page.screenshot({
      path: path.join(directory, "tray-restored.png"),
    });
    await api(current.page, `/api/runs/${run.id}/cancel`, "POST");
    await control("/control/release", { document_ids: [documentId] });
    await expect
      .poll(
        async () => (await api(current.page, `/api/runs/${run.id}`)).status,
        { timeout: 90000 },
      )
      .toBe("cancelled");
    await close(current);
    await dead(pid);
    current = null;
    return {
      passed: true,
      trayAvailable: true,
      actualActiveJobKeptRunning: true,
      secondInstanceRestoredWindow: true,
      syntheticLocalProviderOnly: true,
    };
  } finally {
    if (origin && documentId)
      await control("/control/release", { document_ids: [documentId] }).catch(
        () => {},
      );
    await close(current);
    provider.kill("SIGTERM");
    await new Promise((resolve) => {
      if (provider.exitCode !== null) resolve();
      else provider.once("exit", resolve);
    });
  }
}
async function main() {
  const artifact = path.resolve(
    process.argv[2] ||
      "/tmp/anki-desktop-final-release/Anki-Generator.AppImage",
  );
  const unpacked = path.resolve(
    process.argv[3] || path.join(ROOT, "dist/desktop/linux-unpacked"),
  );
  const workspace = path.resolve(
    process.argv[4] ||
      (await fs.mkdtemp(path.join(os.tmpdir(), "anki-desktop-lifecycle-"))),
  );
  assert(
    !artifact.startsWith(ROOT + path.sep),
    "Test the actual distribution copied outside the checkout",
  );
  await fs.access(artifact);
  await fs.mkdir(workspace, { recursive: true });
  const report = {
    artifact,
    unpacked,
    workspace,
    sandboxDisabled: false,
    results: {},
  };
  try {
    report.results.recoveryAndInstances = await recoveryAndInstances(
      artifact,
      path.join(workspace, "recovery"),
    );
    report.results.missingResources = await missingResources(
      unpacked,
      path.join(workspace, "resources"),
    );
    report.results.corruptDatabase = await corruptDatabase(
      artifact,
      path.join(workspace, "corrupt-database"),
    );
    report.results.quitDuringStartup = await quitDuringStartup(
      artifact,
      path.join(workspace, "startup-quit"),
    );
    report.results.quitDuringRestart = await quitDuringRestart(
      artifact,
      path.join(workspace, "restart-quit"),
    );
    report.results.keepRunningInTray = await keepRunningInTray(
      artifact,
      path.join(workspace, "tray"),
    );
    report.result = "passed";
  } catch (error) {
    report.result = "failed";
    report.error = { message: error.message, stack: error.stack };
    throw error;
  } finally {
    for (const app of [...windows]) {
      await close({ app }).catch(() => {
        app.process().kill("SIGTERM");
        windows.delete(app);
      });
    }
    for (const pid of ownedBackends) {
      try {
        process.kill(pid, "SIGCONT");
        process.kill(pid, "SIGTERM");
      } catch {}
    }
    const spawnedPids = new Set();
    for (const relative of [
      "recovery",
      "resources/missing-binary",
      "resources/missing-frontend",
      "corrupt-database",
      "startup-quit",
      "restart-quit",
      "tray",
    ]) {
      for (const item of await events(path.join(workspace, relative))) {
        if (item.event === "backend-spawned" && Number.isInteger(item.pid))
          spawnedPids.add(item.pid);
      }
    }
    for (const pid of spawnedPids) await dead(pid);
    report.ownedBackendProcessesStopped = true;
    report.ownedBackendProcessCount = spawnedPids.size;
    await fs.writeFile(
      path.join(workspace, "report.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report, null, 2));
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
