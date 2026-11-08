import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
test('a local learner can create a course, import role-aware sources, generate, review, refine, and export', async ({
  page,
}) => {
  const name = `University mathematics ${Date.now()}`;
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Good things take understanding.' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Create course', exact: true }).first().click();
  await page.getByLabel('Course name', { exact: true }).fill(name);
  await page
    .getByLabel('Description optional')
    .fill('A controlled synthetic course for browser-level integration.');
  await page.getByRole('button', { name: 'Create course', exact: true }).last().click();
  await expect(page.getByRole('heading', { name })).toBeVisible();
  const courseUrl = page.url().replace(/\/documents$/, '');
  await page.locator('input[type=file]:not([webkitdirectory])').setInputFiles([
    {
      name: '01-lecture.pdf',
      mimeType: 'application/pdf',
      buffer: readFileSync(new URL('../../fixtures/e2e/01-lecture.pdf', import.meta.url)),
    },
    {
      name: 'Exercises.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(
        'Exercise. For a right triangle, a^2 + b^2 = c^2. Find the hypotenuse when the positive leg lengths are 3 and 4. State the right-angle assumption before applying the theorem.',
      ),
    },
    {
      name: 'Solutions.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(
        'Worked solution. For a right triangle, a^2 + b^2 = c^2. With a = 3 and b = 4, c^2 = 9 + 16 = 25. Because c is a positive length, c = 5. This method requires a right triangle.',
      ),
    },
  ]);
  await page.getByLabel('Category for Exercises.txt').selectOption('exercises');
  await page.getByLabel('Category for Solutions.txt').selectOption('solutions');
  await page.getByRole('button', { name: 'Import materials', exact: true }).click();
  await expect(page.getByRole('button', { name: '01-lecture.pdf', exact: true })).toBeVisible();
  await expect(page.getByText('Worked solutions', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Extract locally', exact: true }).click();
  await page.getByRole('link', { name: 'Processing', exact: true }).click();
  await expect(page.getByText('Completed', { exact: true }).first()).toBeVisible({
    timeout: 60000,
  });
  await page.getByRole('link', { name: 'Documents', exact: true }).click();
  await page.getByRole('button', { name: 'Preview 01-lecture.pdf', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Extracted text', exact: true }).click();
  await expect(page.getByRole('dialog').locator('pre')).toContainText('right triangle');
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.goto('/settings');
  await page.getByLabel('OpenAI API key', { exact: true }).fill('sk-browser-controlled-provider');
  await page.getByRole('button', { name: 'Save API key', exact: true }).click();
  await expect(page.getByText('Key configured', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.locator('.toast[role=status]')).toContainText(
    'Controlled test provider connection',
  );
  await page.goto(`${courseUrl}/documents`);
  await page.getByRole('button', { name: 'Generate cards', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start processing', exact: true })).toBeDisabled();
  await page
    .getByLabel(
      'I approve sending this course material to OpenAI for the processing described above.',
    )
    .check();
  const startedResponse = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/runs'),
  );
  await page.getByRole('button', { name: 'Start processing', exact: true }).click();
  const generatedRun = await (await startedResponse).json();
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`/api/runs/${generatedRun.id}`);
        expect(response.ok()).toBe(true);
        return (await response.json()).status;
      },
      {
        timeout: 90000,
        message: 'the specific generation run started through the GUI must finish successfully',
      },
    )
    .toBe('completed');
  await expect(page.getByRole('heading', { name: 'Completed', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Knowledge map', exact: true }).click();
  await expect(page.locator('.concept-node').first()).toBeVisible();
  await expect(page.locator('.coverage-strip>div').nth(1).locator('strong')).toHaveText('1');
  await page.screenshot({ path: '/tmp/anki-ui-knowledge.png', fullPage: false });
  await page.getByRole('link', { name: 'Flashcards', exact: true }).click();
  await expect(page.locator('.card-tile').first()).toBeVisible();
  await page.getByRole('button', { name: 'Reveal answer', exact: true }).first().click();
  await expect(
    page.getByRole('button', { name: 'Show question', exact: true }).first(),
  ).toBeVisible();
  await page.getByLabel('Search questions, answers, or tags…').fill('unlikely-nonexistent-query');
  await expect(page.getByRole('heading', { name: 'No cards match these filters' })).toBeVisible();
  await page.getByLabel('Search questions, answers, or tags…').fill('');
  await page.getByRole('button', { name: 'Inspect & review' }).first().click();
  await page.getByRole('button', { name: 'Edit card', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Question', exact: true })
    .fill(
      'For a right triangle with positive leg lengths \\(a,b\\), how is the hypotenuse length \\(c\\) determined?',
    );
  await page
    .getByRole('textbox', { name: 'Answer', exact: true })
    .fill('The positive hypotenuse length is \\(c=\\sqrt{a^2+b^2}\\).');
  await page.locator('.source-region-options input[type=checkbox]').first().check();
  await expect(page.getByRole('dialog').locator('.editor-preview .flashcard img')).toBeVisible();
  await expect(page.getByRole('dialog').locator('.katex').first()).toBeVisible();
  await page.getByRole('dialog').evaluate((dialog) => {
    dialog.scrollTop = 0;
  });
  await page.screenshot({ path: '/tmp/anki-ui-editor.png', fullPage: false });
  await page.getByRole('button', { name: 'Save card', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('button', { name: 'Inspect & review' }).first().click();
  await page
    .getByLabel('Review rationale required for unverified approval')
    .fill(
      'I checked the right-angle assumption and positive-length condition against the original lecture.',
    );
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.locator('.toast[role=status]')).toContainText('review decision');
  await page.getByRole('button', { name: 'Compare previous revisions' }).click();
  await expect(page.locator('.revision-list article').first()).toBeVisible();
  await page.locator('.source-chips button').first().click();
  await expect(page.locator('.source-highlight').first()).toBeVisible();
  await page.getByRole('dialog').evaluate((dialog) => {
    dialog.scrollTop = 0;
  });
  await page.screenshot({ path: '/tmp/anki-ui-inspector.png', fullPage: false });
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.getByRole('link', { name: 'Exports', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Generate & download APKG' })).toBeEnabled();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Generate & download APKG' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.apkg$/);
  await expect(page.locator('.export-history tbody tr').first()).toBeVisible();
  await page.goto('/settings');
  const backup = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Create data backup', exact: true }).click();
  expect((await backup).suggestedFilename()).toMatch(/\.zip$/);
  await page.screenshot({ path: '/tmp/anki-ui-settings.png', fullPage: false });
  await page.goto('/');
  await page.screenshot({ path: '/tmp/anki-ui-dashboard.png', fullPage: false });
  expect(errors).toEqual([]);
});
test('responsive navigation and dark theme remain usable on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
  await page.getByRole('link', { name: 'Settings', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'A workspace that thinks with you.' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Toggle navigation', exact: true })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
  await expect(page.locator('.sidebar')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
  await page.getByRole('button', { name: 'Switch to dark theme', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.locator('.sidebar-backdrop').click({ position: { x: 350, y: 400 } });
  await expect
    .poll(async () => {
      const box = await page.locator('.sidebar').boundingBox();
      return box ? box.x + box.width : 0;
    })
    .toBeLessThanOrEqual(0);
  await page.screenshot({
    path: '/tmp/anki-ui-mobile-viewport.png',
    fullPage: false,
    animations: 'disabled',
  });
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
  await expect(page.locator('.sidebar')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
  await page.locator('.sidebar').evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: '/tmp/anki-ui-mobile-drawer.png',
    fullPage: false,
    animations: 'disabled',
  });
});
