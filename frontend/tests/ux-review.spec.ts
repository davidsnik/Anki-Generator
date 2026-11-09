import { test, expect } from '@playwright/test';

test('document grouping and review choices stay clear, drafts are protected, and courses stay isolated', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create course', exact: true }).first().click();
  await page.getByLabel('Course name', { exact: true }).fill('UX review workspace');
  await page.getByRole('button', { name: 'Create course', exact: true }).last().click();
  await expect(
    page.getByRole('heading', { name: 'UX review workspace', exact: true }),
  ).toBeVisible();
  const coursePath = page.url().replace(/\/documents$/, '');
  await page.locator('input[type=file]:not([webkitdirectory])').setInputFiles([
    {
      name: 'Lecture.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('A positive real x satisfies x > 0.'),
    },
    {
      name: 'Exercises.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('State the domain assumption for x/x = 1.'),
    },
  ]);
  await page.getByRole('button', { name: 'Import materials', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Lecture.txt', exact: true })).toBeVisible();
  await page.getByLabel('Select displayed documents', { exact: true }).check();
  await page.getByLabel('Role for selected documents').selectOption('reference');
  await page.getByRole('button', { name: 'Apply role', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Role updated for 2 documents');
  await expect(page.locator('.document-labels')).toHaveText([/Other reference/, /Other reference/]);
  await page.getByRole('link', { name: 'Flashcards', exact: true }).click();
  await page.getByRole('button', { name: 'Add a card', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Question', exact: true })
    .fill('What does \\(x>0\\) require?');
  await page.getByLabel('Answer', { exact: true }).fill('The real variable is strictly positive.');
  await page.getByRole('button', { name: 'Save card', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Inspect & review', exact: true }).first().click();
  await expect(page.getByText('Card 1 of 1', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous card' })).toBeDisabled();
  await page.getByRole('button', { name: 'Edit card', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Question', exact: true })
    .fill('Which strict positivity assumption is required?');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Discard your card changes?' })).toBeVisible();
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Question', exact: true })).toHaveValue(
    'Which strict positivity assumption is required?',
  );
  await page.getByRole('textbox', { name: 'Question', exact: true }).press('Control+Enter');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Awaiting review', exact: true }).click();
  await page.getByRole('button', { name: 'List view', exact: true }).click();
  await page.getByRole('link', { name: 'Documents', exact: true }).click();
  await page.getByRole('link', { name: 'Flashcards', exact: true }).click();
  await expect(page.getByLabel('Review status', { exact: true })).toHaveValue('pending');
  await expect(page.getByRole('button', { name: 'List view', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByRole('button', { name: 'Approved cards', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No cards match these filters' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters', exact: true }).first().click();
  await expect(page.locator('.card-list-row')).toHaveCount(1);
  await page.screenshot({ path: '/tmp/anki-ux-review-light.png' });
  await page.getByRole('button', { name: 'New course', exact: true }).click();
  await page.getByLabel('Course name', { exact: true }).fill('Second isolated course');
  await page.getByRole('button', { name: 'Create course', exact: true }).last().click();
  await page.getByRole('link', { name: 'Flashcards', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Grid view', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByLabel('Review status', { exact: true })).toHaveValue('all');
  await page.goto(`${coursePath}/cards`);
  await expect(page.getByRole('button', { name: 'List view', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '/tmp/anki-ux-review-mobile.png', animations: 'disabled' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
