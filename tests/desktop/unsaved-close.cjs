/* Native unsaved-change choices on an actual packaged, sandboxed desktop app. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const {
  expect: baseExpect,
} = require("../../frontend/node_modules/@playwright/test");
const { launch } = require("./launch-smoke.cjs");
const expect = baseExpect.configure({ timeout: 30000 });

async function main() {
  const artifact = path.resolve(process.argv[2] || "");
  const workspace =
    process.argv[3] ||
    (await fs.mkdtemp(path.join(os.tmpdir(), "anki-unsaved-gui-")));
  await fs.mkdir(workspace, { recursive: true });
  let current;
  let backendPid;
  const evidence = { artifact, workspace, nativePrompts: [] };
  try {
    current = await launch(artifact, workspace);
    let { app, page } = current;
    page.on("dialog", (dialog) => {
      void dialog.dismiss().catch(() => {});
    });
    const security = await app.evaluate(({ BrowserWindow, dialog }) => {
      globalThis.__unsavedQA = { choice: 0, prompts: [], unexpected: [] };
      dialog.showMessageBoxSync = (...args) => {
        const options = args.at(-1);
        globalThis.__unsavedQA.prompts.push(options);
        return globalThis.__unsavedQA.choice;
      };
      dialog.showMessageBox = async (...args) => {
        globalThis.__unsavedQA.unexpected.push(args.at(-1));
        return { response: 0 };
      };
      const preferences =
        BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
      return {
        sandbox: preferences.sandbox,
        isolation: preferences.contextIsolation,
        node: preferences.nodeIntegration,
        noSandbox: process.argv.includes("--no-sandbox"),
      };
    });
    assert.equal(security.sandbox, true);
    assert.equal(security.isolation, true);
    assert.equal(security.node, false);
    assert.equal(security.noSandbox, false);
    evidence.security = security;
    await page
      .getByRole("button", { name: "Create course", exact: true })
      .first()
      .click();
    const courseName = "Native unsaved changes";
    await page.getByLabel("Course name", { exact: true }).fill(courseName);
    await page
      .getByRole("button", { name: "Create course", exact: true })
      .last()
      .click();
    await expect(
      page.getByRole("heading", { name: courseName, exact: true }),
    ).toBeVisible();
    const courseId = page.url().match(/\/courses\/([^/]+)/)[1];
    await page.getByRole("link", { name: "Flashcards", exact: true }).click();
    await page.getByRole("button", { name: "Add a card", exact: true }).click();
    const question =
      "Unsaved question preserved by the native Keep editing choice";
    const answer = "Unsaved answer preserved until explicitly discarded";
    await page.getByLabel("Question", { exact: true }).fill(question);
    await page.getByLabel("Answer", { exact: true }).fill(answer);
    backendPid = (await page.evaluate(() => window.ankiDesktop.diagnostics()))
      .desktop.backend_pid;
    const origin = new URL(page.url()).origin;
    await page.screenshot({
      path: path.join(workspace, "dirty-before-close.png"),
    });
    // This changes only the test's native user decision, not product control flow.
    await app.evaluate(({ BrowserWindow }) => {
      setTimeout(() => BrowserWindow.getAllWindows()[0].close(), 0);
    });
    await expect
      .poll(() => app.evaluate(() => globalThis.__unsavedQA.prompts.length))
      .toBe(1);
    await expect
      .poll(() =>
        page
          .evaluate(() => window.ankiDesktop.info())
          .then((info) => info.status),
      )
      .toBe("ready");
    assert.equal(
      (await fetch(origin + "/api/health")).status,
      401,
      "The same private backend must still be alive",
    );
    assert.deepEqual(
      await page
        .locator("textarea")
        .evaluateAll((nodes) => nodes.slice(0, 2).map((node) => node.value)),
      [question, answer],
    );
    assert.equal(
      (await page.evaluate(() => window.ankiDesktop.diagnostics())).desktop
        .backend_pid,
      backendPid,
    );
    await page.screenshot({
      path: path.join(workspace, "dirty-kept-after-close.png"),
    });
    // Restart also retains a draft when the user keeps editing.
    await page.evaluate(() => window.ankiDesktop.restartBackend());
    await expect
      .poll(() => app.evaluate(() => globalThis.__unsavedQA.prompts.length))
      .toBe(2);
    assert.equal(
      (await page.evaluate(() => window.ankiDesktop.info())).status,
      "ready",
    );
    assert.equal(
      (await page.evaluate(() => window.ankiDesktop.diagnostics())).desktop
        .backend_pid,
      backendPid,
    );
    assert.deepEqual(
      await page
        .locator("textarea")
        .evaluateAll((nodes) => nodes.slice(0, 2).map((node) => node.value)),
      [question, answer],
    );
    // Reload uses the same native choice and keeps both the draft and service.
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].reload();
    });
    await expect
      .poll(() => app.evaluate(() => globalThis.__unsavedQA.prompts.length))
      .toBe(3);
    assert.deepEqual(
      await page
        .locator("textarea")
        .evaluateAll((nodes) => nodes.slice(0, 2).map((node) => node.value)),
      [question, answer],
    );
    // An explicit discard permits restart and replaces only the owned service.
    await app.evaluate(() => {
      globalThis.__unsavedQA.choice = 1;
    });
    void page
      .evaluate(() => window.ankiDesktop.restartBackend())
      .catch(() => {});
    await expect
      .poll(() => app.evaluate(() => globalThis.__unsavedQA.prompts.length))
      .toBe(4);
    await expect(
      page.getByRole("heading", { name: "Good things take understanding." }),
    ).toBeVisible({ timeout: 120000 });
    const replacementPid = (
      await page.evaluate(() => window.ankiDesktop.diagnostics())
    ).desktop.backend_pid;
    assert.notEqual(replacementPid, backendPid);
    await expect
      .poll(() => {
        try {
          process.kill(backendPid, 0);
          return false;
        } catch (error) {
          if (error.code === "ESRCH") return true;
          throw error;
        }
      })
      .toBe(true);
    backendPid = replacementPid;
    await page.goto(new URL(`/courses/${courseId}/cards`, page.url()).href);
    await page.getByRole("button", { name: "Add a card", exact: true }).click();
    await page
      .getByLabel("Question", { exact: true })
      .fill("Explicitly discarded close draft");
    await page
      .getByLabel("Answer", { exact: true })
      .fill("Close is authorized only by Discard changes");
    evidence.nativePrompts = await app.evaluate(
      () => globalThis.__unsavedQA.prompts,
    );
    assert.equal(evidence.nativePrompts.length, 4);
    for (const prompt of evidence.nativePrompts) {
      assert.deepEqual(prompt.buttons, ["Keep editing", "Discard changes"]);
      assert.equal(prompt.defaultId, 0);
      assert.equal(prompt.cancelId, 0);
    }
    assert.deepEqual(
      await app.evaluate(() => globalThis.__unsavedQA.unexpected),
      [],
    );
    const closed = app.waitForEvent("close", { timeout: 30000 });
    await app.evaluate(({ BrowserWindow }) => {
      setTimeout(() => BrowserWindow.getAllWindows()[0].close(), 0);
    });
    await closed;
    current = undefined;
    await expect
      .poll(() => {
        try {
          process.kill(backendPid, 0);
          return false;
        } catch (error) {
          if (error.code === "ESRCH") return true;
          throw error;
        }
      })
      .toBe(true);
    backendPid = undefined;
    // Saved course remains; neither deliberately discarded manual draft became a card.
    current = await launch(artifact, workspace);
    ({ app, page } = current);
    await page.goto(new URL(`/courses/${courseId}/cards`, page.url()).href);
    await expect(
      page.getByRole("button", { name: "Add a card", exact: true }),
    ).toBeVisible();
    assert.equal(await page.locator(".card-tile").count(), 0);
    await app.close();
    current = undefined;
    const log = await fs.readFile(
      path.join(workspace, "state/anki-generator/logs/desktop.log"),
      "utf8",
    );
    assert(
      !log.includes('"event":"shutdown-error"'),
      "Keeping drafts must not create a shutdown error",
    );
    assert(
      !log.includes('"event":"restart-failed"'),
      "Keeping drafts must not create a restart failure",
    );
    evidence.result = "passed";
    evidence.coverage = [
      "native close keeps draft and ready service",
      "restart keeps draft and original service",
      "reload keeps draft",
      "discard permits restart",
      "discard permits graceful close",
      "saved course persists and discarded drafts are absent",
    ];
    await fs.writeFile(
      path.join(workspace, "unsaved-close-result.json"),
      JSON.stringify(evidence, null, 2),
    );
    console.log(JSON.stringify(evidence, null, 2));
  } finally {
    if (current) {
      await current.app
        .evaluate(({ dialog }) => {
          dialog.showMessageBoxSync = () => 1;
          dialog.showMessageBox = async () => ({ response: 1 });
        })
        .catch(() => {});
      await current.app.close().catch(() => {});
    }
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
