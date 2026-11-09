/* Actual packaged GUI + real SDK against an explicitly synthetic HTTP fixture. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { spawn } = require("node:child_process");
const {
  expect: baseExpect,
} = require("../../frontend/node_modules/@playwright/test");
const expect = baseExpect.configure({ timeout: 30000 });
const { launch } = require("./launch-smoke.cjs");
const ROOT = path.resolve(__dirname, "../..");
const KEY = "sk-controlled-packaged-desktop-no-paid-requests";
const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function api(page, route, method = "GET", body) {
  return page.evaluate(
    async ({ route, method, body }) => {
      const initial = await (await fetch("/api/bootstrap")).json();
      const response = await fetch(route, {
        method,
        headers: {
          "X-CSRF-Token": initial.csrf_token,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok)
        throw new Error(
          `Packaged API ${route}: ${response.status} ${await response.text()}`,
        );
      return response.json();
    },
    { route, method, body },
  );
}

async function navigate(page, route) {
  await page.goto(new URL(route, page.url()).href);
}

async function createCourse(page, name, source, folder = false) {
  await navigate(page, "/courses");
  await page.getByRole("button", { name: "New course", exact: true }).click();
  await page.getByLabel("Course name", { exact: true }).fill(name);
  await page
    .getByRole("button", { name: "Create course", exact: true })
    .last()
    .click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  const id = page.url().match(/\/courses\/([^/]+)/)[1];
  // Use the actual chooser path, including Chromium's directory chooser.
  const chooser = page.waitForEvent("filechooser");
  await page
    .getByRole("button", {
      name: folder ? "Upload folder" : "Choose files",
      exact: true,
    })
    .click();
  await (await chooser).setFiles(source);
  await page
    .getByRole("button", { name: "Import materials", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: folder ? "lecture.txt" : path.basename(source),
      exact: true,
    }),
  ).toBeVisible();
  const documents = await api(page, `/api/courses/${id}/documents`);
  assert.equal(documents.length, 1);
  if (folder) assert(documents[0].relative_path.includes("nested/"));
  return { id, name, document: documents[0] };
}

async function generate(page, course) {
  await navigate(page, `/courses/${course.id}/documents`);
  await page
    .getByRole("button", { name: "Generate cards", exact: true })
    .click();
  await page
    .getByLabel(
      "I approve sending this course material to OpenAI for the processing described above.",
    )
    .check();
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/courses/${course.id}/runs`),
  );
  await page
    .getByRole("button", { name: "Start processing", exact: true })
    .click();
  const result = await response;
  assert(result.ok());
  return result.json();
}

async function main() {
  const artifact = path.resolve(process.argv[2] || "");
  assert(
    !artifact.startsWith(ROOT + path.sep),
    "Test a distribution copied outside the checkout",
  );
  const workspace =
    process.argv[3] ||
    (await fs.mkdtemp(path.join(os.tmpdir(), "anki-desktop-workflow-")));
  await fs.mkdir(workspace, { recursive: true });
  const ready = path.join(workspace, "provider.json");
  const provider = spawn(
    path.join(ROOT, ".venv/bin/python"),
    ["-m", "tests.support.desktop_provider_server", "--ready-file", ready],
    { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] },
  );
  let providerOrigin, current;
  const documents = [];
  const control = async (route, body) => {
    const response = await fetch(providerOrigin + route, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${KEY}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok)
      throw new Error(
        `Provider control ${response.status}: ${await response.text()}`,
      );
    return response.json();
  };
  try {
    for (let attempt = 0; attempt < 200; attempt++) {
      try {
        providerOrigin = JSON.parse(await fs.readFile(ready, "utf8")).origin;
        break;
      } catch {
        /* awaiting real readiness */
      }
      assert.equal(provider.exitCode, null);
      await sleep(50);
    }
    assert(providerOrigin);
    current = await launch(artifact, workspace, {
      OPENAI_BASE_URL: providerOrigin + "/v1/",
    });
    const { app, page, errors } = current;
    await navigate(page, "/settings");
    await page.getByLabel("OpenAI API key", { exact: true }).fill(KEY);
    await page
      .getByRole("button", { name: "Save API key", exact: true })
      .click();
    await expect(
      page.getByText("Key configured", { exact: true }),
    ).toBeVisible();
    assert.equal(
      (await api(page, "/api/bootstrap")).key_status.storage,
      "session",
    );
    await page
      .getByRole("button", { name: "Test connection", exact: true })
      .click();
    await expect(page.locator(".toast")).toContainText("verified");
    const folder = path.join(workspace, "source-folder");
    await fs.mkdir(path.join(folder, "nested"), { recursive: true });
    await fs.writeFile(
      path.join(folder, "nested/lecture.txt"),
      "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary.",
    );
    const text = path.join(workspace, "source.txt");
    await fs.writeFile(
      text,
      "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary.",
    );
    const courses = [
      await createCourse(
        page,
        "Desktop geometry A",
        path.join(ROOT, "fixtures/e2e/01-lecture.pdf"),
      ),
      await createCourse(page, "Desktop geometry B", folder, true),
      await createCourse(page, "Desktop geometry C", text),
    ];
    documents.push(...courses.map((course) => course.document.id));
    await control("/control/gates", { document_ids: documents });
    const runs = [];
    for (const course of courses) runs.push(await generate(page, course));
    await expect
      .poll(async () => (await control("/control")).waiting.length, {
        timeout: 90000,
      })
      .toBe(2);
    assert.equal((await api(page, `/api/runs/${runs[2].id}`)).status, "queued");
    await navigate(page, "/tasks");
    await expect(
      page.getByRole("link", { name: "2 running · 1 queued tasks" }),
    ).toBeVisible();
    await page.screenshot({
      path: path.join(workspace, "concurrent-tasks.png"),
    });
    await control("/control/release", { document_ids: [documents[0]] });
    await expect
      .poll(async () => (await api(page, `/api/runs/${runs[0].id}`)).status, {
        timeout: 90000,
      })
      .toBe("completed");
    await expect
      .poll(async () => (await control("/control")).waiting.sort(), {
        timeout: 30000,
      })
      .toEqual([documents[1], documents[2]].sort());
    await navigate(page, `/courses/${courses[0].id}/cards`);
    await page
      .getByRole("button", { name: "Inspect & review" })
      .first()
      .click();
    await page.getByRole("button", { name: "Edit card", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Question", exact: true })
      .fill(
        "For a right triangle with positive legs \\(a,b\\), determine \\(c\\).",
      );
    await page
      .getByRole("textbox", { name: "Answer", exact: true })
      .fill("\\(c=\\sqrt{a^2+b^2}\\).");
    await page
      .locator(".source-region-options input[type=checkbox]")
      .first()
      .check();
    await expect(
      page.getByRole("dialog").locator(".katex").first(),
    ).toBeVisible();
    await expect(
      page
        .getByRole("dialog")
        .locator(".editor-preview .flashcard img")
        .first(),
    ).toBeVisible();
    await page.screenshot({
      path: path.join(workspace, "math-source-review.png"),
    });
    await page.getByRole("button", { name: "Save card", exact: true }).click();
    await page
      .getByRole("button", { name: "Inspect & review" })
      .first()
      .click();
    await page
      .getByLabel("Review rationale required for unverified approval")
      .fill(
        "Synthetic test author checked the positive-root and right-angle conditions against the synthetic original.",
      );
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.locator(".toast")).toContainText("review decision");
    await page
      .getByRole("button", { name: "Close dialog", exact: true })
      .click();
    const exportPath = path.join(workspace, "approved.apkg");
    await app.evaluate(({ session }, destination) => {
      session
        .fromPartition("persist:anki-generator")
        .on("will-download", (_event, item) => item.setSavePath(destination));
    }, exportPath);
    await page.getByRole("link", { name: "Exports", exact: true }).click();
    await page
      .getByRole("button", { name: "Save Anki package (.apkg)", exact: true })
      .click();
    await expect
      .poll(async () => {
        try {
          return (await fs.readFile(exportPath)).subarray(0, 2).toString();
        } catch {
          return "";
        }
      })
      .toBe("PK");
    await expect
      .poll(
        async () =>
          (await page.evaluate(() => window.ankiDesktop.info())).last_download
            ?.filename || "",
      )
      .toMatch(/\.apkg$/);
    const download = (await page.evaluate(() => window.ankiDesktop.info()))
      .last_download;
    await app.evaluate(({ shell }) => {
      global.__desktopOpens = [];
      shell.openPath = async (value) => {
        global.__desktopOpens.push(value);
        return "";
      };
      shell.showItemInFolder = (value) => global.__desktopOpens.push(value);
      shell.openExternal = async (value) => global.__desktopOpens.push(value);
    });
    await page.evaluate(
      (id) => window.ankiDesktop.openDownload(id, "folder"),
      download.id,
    );
    assert(
      (await app.evaluate(() => global.__desktopOpens)).includes(exportPath),
    );
    assert(
      await page.evaluate(async () => {
        try {
          await window.ankiDesktop.openDirectory("/tmp");
          return false;
        } catch {
          return true;
        }
      }),
    );
    const before = page.url();
    await page.evaluate(() => {
      const anchor = document.createElement("a");
      anchor.href = "https://example.com/desktop-test";
      document.body.append(anchor);
      anchor.click();
    });
    await expect
      .poll(async () =>
        (await app.evaluate(() => global.__desktopOpens)).includes(
          "https://example.com/desktop-test",
        ),
      )
      .toBe(true);
    assert.equal(page.url(), before);
    assert.equal((await app.windows()).length, 1);
    const diagnosticPath = path.join(workspace, "diagnostics.json");
    await app.evaluate(({ dialog }, destination) => {
      dialog.showSaveDialog = async () => ({
        canceled: false,
        filePath: destination,
      });
    }, diagnosticPath);
    await page.evaluate(() => window.ankiDesktop.exportDiagnostics());
    const diagnostic = await fs.readFile(diagnosticPath, "utf8");
    assert(!diagnostic.includes(KEY));
    assert(JSON.parse(diagnostic).schema_version === "0006_concurrent_tasks");
    assert.deepEqual(errors, []);
    // Actual close while two HTTP operations are still inside provider barriers.
    await app.evaluate(({ dialog }) => {
      global.__closePrompts = [];
      dialog.showMessageBox = async (_window, options) => {
        global.__closePrompts.push(options);
        return { response: 1 };
      };
    });
    const closing = app.close();
    await sleep(500);
    await control("/control/release", { document_ids: documents.slice(1) });
    await closing;
    current = undefined;
    current = await launch(artifact, workspace, {
      OPENAI_BASE_URL: providerOrigin + "/v1/",
    });
    for (const run of runs.slice(1))
      assert.equal(
        (await api(current.page, `/api/runs/${run.id}`)).status,
        "paused",
      );
    const saved = await api(
      current.page,
      `/api/courses/${courses[0].id}/cards`,
    );
    assert.equal(saved.length, 1);
    assert.equal(saved[0].review_status, "approved");
    await current.app.close();
    current = undefined;
    console.log(
      JSON.stringify(
        {
          result: "passed",
          artifact,
          workspace,
          courses: courses.map((c) => c.id),
          provider: await control("/control"),
        },
        null,
        2,
      ),
    );
  } catch (error) {
    if (current) {
      await current.page
        .screenshot({
          path: path.join(workspace, "failure.png"),
          fullPage: true,
        })
        .catch(() => {});
      console.error("Packaged workflow failed at", current.page.url());
      console.error("Renderer errors:", current.errors);
    }
    throw error;
  } finally {
    if (providerOrigin && documents.length)
      await control("/control/release", { document_ids: documents }).catch(
        () => {},
      );
    if (current) {
      await current.app
        .evaluate(({ dialog }) => {
          dialog.showMessageBox = async () => ({ response: 1 });
        })
        .catch(() => {});
      await current.app.close().catch(() => {});
    }
    provider.kill("SIGTERM");
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
