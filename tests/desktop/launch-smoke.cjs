/* Run with Node against an actual AppImage outside the checkout. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const {
  _electron: electron,
  expect: baseExpect,
} = require("../../frontend/node_modules/@playwright/test");
const expect = baseExpect.configure({ timeout: 30000 });

async function launch(artifact, workspace, overrides = {}) {
  const environment = { ...process.env };
  delete environment.ELECTRON_RUN_AS_NODE;
  delete environment.NODE_OPTIONS;
  const app = await electron.launch({
    executablePath: artifact,
    chromiumSandbox: true,
    cwd: workspace,
    timeout: 120000,
    env: {
      ...environment,
      APPIMAGE_EXTRACT_AND_RUN: "1",
      XDG_DATA_HOME: path.join(workspace, "data"),
      XDG_STATE_HOME: path.join(workspace, "state"),
      XDG_CONFIG_HOME: path.join(workspace, "config"),
      XDG_CACHE_HOME: path.join(workspace, "cache"),
      OPENAI_API_KEY: "",
      PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring",
      ...overrides,
    },
  });
  const page = await app.firstWindow({ timeout: 120000 });
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await expect(
    page.getByRole("heading", { name: "Good things take understanding." }),
  ).toBeVisible({ timeout: 120000 });
  return { app, page, errors };
}

async function main() {
  const artifact = path.resolve(process.argv[2] || "");
  assert(
    !artifact.startsWith(path.resolve(__dirname, "../..") + path.sep),
    "Copy the artifact outside the repository before testing",
  );
  const workspace =
    process.argv[3] ||
    (await fs.mkdtemp(path.join(os.tmpdir(), "anki-desktop-gui-")));
  await fs.mkdir(workspace, { recursive: true });
  let current;
  try {
    current = await launch(artifact, workspace);
    const { app, page, errors } = current;
    const window = await app.evaluate(({ app, BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      const prefs = win.webContents.getLastWebPreferences();
      return {
        packaged: app.isPackaged,
        version: app.getVersion(),
        sandbox: prefs.sandbox,
        isolation: prefs.contextIsolation,
        node: prefs.nodeIntegration,
        title: win.getTitle(),
        visible: win.isVisible(),
        processSandboxDisabled: process.argv.includes("--no-sandbox"),
      };
    });
    assert.equal(window.packaged, true);
    assert.equal(window.sandbox, true);
    assert.equal(window.isolation, true);
    assert.equal(window.node, false);
    assert.equal(window.visible, true);
    assert.equal(window.processSandboxDisabled, false);
    const info = await page.evaluate(() => window.ankiDesktop.info());
    assert(info.data_directory.startsWith(workspace));
    assert.equal(await page.evaluate(() => typeof window.require), "undefined");
    const unauthorized = await fetch(new URL("/api/bootstrap", page.url()));
    assert.equal(unauthorized.status, 401);
    const courseName = "Packaged desktop persistence";
    await page
      .getByRole("button", { name: "Create course", exact: true })
      .first()
      .click();
    await page.getByLabel("Course name", { exact: true }).fill(courseName);
    await page
      .getByRole("button", { name: "Create course", exact: true })
      .last()
      .click();
    await expect(
      page.getByRole("heading", { name: courseName, exact: true }),
    ).toBeVisible();
    const courseId = page.url().match(/\/courses\/([^/]+)/)[1];
    await page
      .locator("input[type=file]:not([webkitdirectory])")
      .setInputFiles(
        path.resolve(__dirname, "../../fixtures/e2e/01-lecture.pdf"),
      );
    await page
      .getByRole("button", { name: "Import materials", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "01-lecture.pdf", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Extract locally", exact: true })
      .click();
    await page.getByRole("link", { name: "Processing", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Completed", exact: true }),
    ).toBeVisible({ timeout: 90000 });
    await page.getByRole("link", { name: "Documents", exact: true }).click();
    await page
      .getByRole("button", { name: "Preview 01-lecture.pdf", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog").locator("img").first()).toBeVisible();
    await page.screenshot({ path: path.join(workspace, "document.png") });
    await page
      .getByRole("button", { name: "Close dialog", exact: true })
      .click();
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await expect(
      page.getByLabel("OpenAI API key", { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: path.join(workspace, "settings.png"),
      fullPage: true,
    });
    await page.goto(new URL("/tasks", page.url()).href);
    await expect(
      page.getByRole("heading", { name: "Your learning, in motion." }),
    ).toBeVisible();
    await page.screenshot({ path: path.join(workspace, "tasks.png") });
    assert.deepEqual(errors, []);
    await app.close();
    current = await launch(artifact, workspace);
    await current.page.goto(
      new URL(`/courses/${courseId}/documents`, current.page.url()).href,
    );
    await expect(
      current.page.getByRole("heading", { name: courseName, exact: true }),
    ).toBeVisible();
    await expect(
      current.page.getByRole("button", { name: "01-lecture.pdf", exact: true }),
    ).toBeVisible();
    await current.app.close();
    current = undefined;
    console.log(
      JSON.stringify(
        { result: "passed", artifact, workspace, window, courseId },
        null,
        2,
      ),
    );
  } finally {
    if (current) await current.app.close().catch(() => {});
  }
}
module.exports = { launch };
if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
