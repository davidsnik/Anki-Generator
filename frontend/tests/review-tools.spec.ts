import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
test('corrections, coordinate crops, bulk revisions, blind evaluation and scalable browsing integrate with the real local API', async ({
  page,
}) => {
  test.setTimeout(180000);
  await page.goto('/');
  const bootstrap = await (await page.request.get('/api/bootstrap')).json();
  const headers = { 'X-CSRF-Token': bootstrap.csrf_token };
  const name = `Evidence workbench ${Date.now()}`;
  const course = await (
    await page.request.post('/api/courses', {
      headers,
      data: {
        name,
        description: 'Explicit synthetic browser fixture',
        deck_name: name,
        language: 'English',
      },
    })
  ).json();
  const coursePath = `/courses/${course.id}`;
  const benchmarkName = `Synthetic geometry benchmark ${course.id}`;
  await page.goto(`${coursePath}/documents`);
  await page.locator('input[type=file]:not([webkitdirectory])').setInputFiles({
    name: 'misread-math.pdf',
    mimeType: 'application/pdf',
    buffer: readFileSync(new URL('../../fixtures/ingestion/misread-math.pdf', import.meta.url)),
  });
  await page.getByRole('button', { name: 'Import materials', exact: true }).click();
  await expect(page.getByRole('button', { name: 'misread-math.pdf', exact: true })).toBeVisible();
  const runResponse = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().endsWith('/runs'),
  );
  await page.getByRole('button', { name: 'Extract locally', exact: true }).click();
  const run = await (await runResponse).json();
  let captureRunId = run.id;
  await expect
    .poll(async () => (await (await page.request.get(`/api/runs/${run.id}`)).json()).status, {
      timeout: 60000,
    })
    .toBe('completed');
  const docs = await (await page.request.get(`/api/courses/${course.id}/documents`)).json();
  const doc = docs[0];
  const one = await (
    await page.request.post(`/api/courses/${course.id}/cards`, {
      headers,
      data: {
        question: 'What assumption is required for the Pythagorean theorem?',
        answer: 'The triangle has a right angle.',
        sources: [
          { document_id: doc.id, page_number: 1, quote: 'For a right triangle, a^2 + b^2 = c^2.' },
        ],
        tags: ['synthetic'],
      },
    })
  ).json();
  const two = await (
    await page.request.post(`/api/courses/${course.id}/cards`, {
      headers,
      data: {
        question: 'Which side is the hypotenuse?',
        answer: 'The side opposite the right angle.',
        sources: [{ document_id: doc.id, page_number: 1 }],
        tags: ['synthetic'],
      },
    })
  ).json();
  const original = await (await page.request.get(`/api/documents/${doc.id}/interpretation`)).json();
  expect(original.pages[0].original_text).toContain('a^2 - b^2');
  await page.getByRole('button', { name: 'Correct or crop misread-math.pdf', exact: true }).click();
  const modal = page.getByRole('dialog');
  await expect(modal.getByLabel('Corrected transcription')).toContainText('a^2 - b^2');
  await modal
    .getByLabel('Corrected transcription')
    .fill(
      'For a right triangle, \\(a^2 + b^2 = c^2\\). The hypotenuse c is opposite the right angle.',
    );
  await modal
    .getByLabel('Correction rationale')
    .fill(
      'Controlled browser correction against the immutable original PDF; synthetic test, not an independent expert judgment.',
    );
  await modal.getByRole('button', { name: 'Save transcription correction', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Human correction saved');
  await modal.getByRole('button', { name: 'Zoom in source', exact: true }).click();
  await expect(modal.locator('output')).toHaveText('125%');
  const canvas = modal.locator('.source-page-canvas');
  const rect = await canvas.boundingBox();
  expect(rect).not.toBeNull();
  await page.mouse.move(rect!.x + 70, rect!.y + 90);
  await page.mouse.down();
  await page.mouse.move(rect!.x + 300, rect!.y + 280, { steps: 8 });
  await page.mouse.up();
  await expect(modal.getByTestId('crop-selection')).toBeVisible();
  const cropResponse = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().endsWith(`/documents/${doc.id}/regions`),
  );
  await modal.getByRole('button', { name: 'Save evidence crop', exact: true }).click();
  const crop = await (await cropResponse).json();
  expect(crop.bbox[2]).toBeGreaterThan(crop.bbox[0]);
  expect(crop.pixel_width).toBeGreaterThan(100);
  expect(crop.bbox[0]).toBeCloseTo((70 * original.pages[0].width) / rect!.width, 0);
  await modal.getByRole('combobox', { name: 'Attach to card', exact: true }).selectOption(one.id);
  await modal.getByRole('button', { name: 'Attach selected evidence', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Saved crop attached');
  await expect(modal.getByAltText('Saved high-resolution evidence crop')).toBeVisible();
  await modal.getByRole('button', { name: 'Correction history', exact: true }).click();
  await expect(
    modal.getByText(
      'Controlled browser correction against the immutable original PDF; synthetic test, not an independent expert judgment.',
      { exact: true },
    ),
  ).toBeVisible();
  await modal.evaluate((el) => (el.scrollTop = 0));
  await page.screenshot({ path: '/tmp/anki-ui-source-workbench.png', animations: 'disabled' });
  await modal.getByRole('button', { name: 'Close dialog', exact: true }).click();
  // Capture a fresh source/correction/crop manifest rather than reusing the pre-correction run.
  const snapshotResponse = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().endsWith('/runs'),
  );
  await page.getByRole('button', { name: 'Extract locally', exact: true }).click();
  const snapshotRun = await (await snapshotResponse).json();
  captureRunId = snapshotRun.id;
  await expect
    .poll(
      async () => (await (await page.request.get(`/api/runs/${snapshotRun.id}`)).json()).status,
      { timeout: 60000 },
    )
    .toBe('completed');
  await page.goto(`${coursePath}/cards`);
  await page.getByLabel(`Select card ${one.id}`, { exact: true }).check();
  await page.getByLabel(`Select card ${two.id}`, { exact: true }).check();
  await page.getByLabel('Bulk card action').selectOption('tags');
  await page.getByRole('button', { name: 'Review bulk action', exact: true }).click();
  await page
    .getByLabel('Reason / regeneration guidance')
    .fill('Explicit synthetic grouping for the controlled integration test.');
  await page.getByLabel('Add tags').fill('geometry,exam');
  await page.getByRole('button', { name: 'Confirm selected action', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Bulk action applied');
  const updated = await (await page.request.get(`/api/cards/${one.id}`)).json();
  expect(updated.tags).toContain('geometry');
  expect(updated.revision_number).toBe(3);
  await page.getByRole('button', { name: 'Inspect & review' }).first().click();
  await page.getByRole('button', { name: 'Compare previous revisions' }).click();
  await expect(page.locator('.revision-field.changed').first()).toBeVisible();
  await page.getByRole('button', { name: 'Restore selected revision', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm action', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Earlier content restored');
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.goto('/evaluation');
  await page.getByRole('button', { name: 'Create benchmark', exact: true }).click();
  await page.getByLabel('Dataset name').fill(benchmarkName);
  await page.getByLabel('Reference provenance').selectOption('synthetic');
  await page.getByLabel('Linked source course').selectOption(course.id);
  await page.getByRole('button', { name: 'Add reference target', exact: true }).click();
  await page.getByLabel('Target label').fill('Right-angle assumption');
  await page.getByLabel('Topic', { exact: true }).fill('Geometry');
  await page.getByLabel('Supporting source document').selectOption(doc.id);
  await page.getByLabel('Supporting quotation').fill('For a right triangle, a^2 + b^2 = c^2.');
  await page.getByRole('button', { name: 'Save dataset', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Reference dataset saved');
  await page
    .locator('.evaluation-datasets > section')
    .filter({ has: page.getByRole('heading', { name: benchmarkName, exact: true }) })
    .getByRole('button', { name: 'Compare configurations' })
    .click();
  for (const select of await page.getByLabel('Reuse completed run').all())
    await select.selectOption(captureRunId);
  await page.getByRole('button', { name: 'Create paired experiment', exact: true }).click();
  await expect(
    page.getByText('Blind review hides model/configuration labels.', { exact: false }),
  ).toBeVisible();
  await expect(page.getByText('Blind case', { exact: false }).first()).toBeVisible();
  await page.getByLabel('Judgment provenance').selectOption('synthetic');
  await page.getByLabel('Reviewer name').fill('Controlled browser test');
  await page
    .getByLabel('Evidence and rationale')
    .fill(
      'Synthetic test label exercises storage and denominators; no independent human quality claim.',
    );
  await page.getByRole('button', { name: 'Save quality judgment', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Judgment saved');
  await expect(
    page.getByRole('button', { name: 'Save reviewed example to benchmark' }),
  ).toBeDisabled();
  await page.getByRole('button', { name: 'Reveal comparison results and configurations' }).click();
  await expect(
    page
      .getByRole('heading', {
        name: 'Human results and explicit unreviewed denominators',
      })
      .first(),
  ).toBeVisible();
  await page.getByRole('dialog').evaluate((el) => (el.scrollTop = 0));
  await page.screenshot({ path: '/tmp/anki-ui-evaluation.png', animations: 'disabled' });
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  const requests: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes(`/api/courses/${course.id}/cards`)) requests.push(r.url());
  });
  const seed = await page.request.post('/api/test/seed-cards', {
    headers,
    data: { course_id: course.id, count: 1500 },
  });
  expect(seed.ok()).toBe(true);
  await page.goto(`${coursePath}/cards`);
  await expect(page.locator('.card-tile')).toHaveCount(24);
  await expect(page.locator('.pagination')).toContainText('1,502');
  await page.getByRole('button', { name: 'Inspect & review' }).last().click();
  const nextPageResponse = page.waitForResponse((response) =>
    response.url().includes('/cards-page?offset=24&'),
  );
  await page.keyboard.press('ArrowRight');
  await nextPageResponse;
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await expect(page.locator('.pagination')).toContainText('25–48');
  await page.getByLabel('Search questions, answers, or tags…').fill('fixture 1499');
  await expect(page.locator('.card-tile')).toHaveCount(1);
  expect(requests.filter((url) => new URL(url).pathname.endsWith('/cards'))).toEqual([]);
  await page.screenshot({ path: '/tmp/anki-ui-scalable-cards.png', animations: 'disabled' });
  await page.goto('/settings');
  const backupDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Create data backup', exact: true }).click();
  const archive = await backupDownload;
  const archivePath = await archive.path();
  expect(archivePath).not.toBeNull();
  await page.getByRole('button', { name: 'Validate & restore backup' }).click();
  await expect(page.getByRole('heading', { name: 'Validate before restoring' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Validate backup', exact: true })).toBeDisabled();
  await page.getByRole('dialog').locator('input[type=file]').setInputFiles(archivePath!);
  await page.getByRole('button', { name: 'Validate backup', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Validation passed', exact: true })).toBeVisible();
  await page.getByLabel('Restoration policy').selectOption('replace');
  await page.getByLabel('Type RESTORE to confirm').fill('RESTORE');
  await page.screenshot({ path: '/tmp/anki-ui-backup-restore.png', animations: 'disabled' });
  const restoredResponse = page.waitForResponse((r) => r.url().endsWith('/api/backup/restore'));
  await page.getByRole('button', { name: 'Restore validated backup', exact: true }).click();
  const restored = await restoredResponse;
  expect(restored.ok()).toBe(true);
  await expect(page.getByRole('heading', { name: 'Backup restored successfully' })).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Download pre-restore recovery backup' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Open restored workspace' }).click();
  await expect(page).toHaveURL('/');
  const afterRestore = await page.request.get(`/api/courses/${course.id}/cards-page?limit=24`);
  expect((await afterRestore.json()).total).toBe(1502);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${coursePath}/cards`);
  await expect(page.locator('.card-tile')).toHaveCount(24);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: '/tmp/anki-ui-mobile-review.png', animations: 'disabled' });
  await page.goto(`${coursePath}/documents`);
  await page.getByRole('button', { name: 'Correct or crop misread-math.pdf', exact: true }).click();
  await expect(page.getByRole('dialog').getByLabel('Corrected transcription')).toContainText(
    'a^2 + b^2',
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: '/tmp/anki-ui-mobile-source.png', animations: 'disabled' });
});
