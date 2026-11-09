import { expect, test } from '@playwright/test';

test('settings guide key setup, discover and validate models, and preserve unsaved preferences', async ({
  page,
}) => {
  const bootstrap = await (await page.request.get('/api/bootstrap')).json();
  const headers = { 'X-CSRF-Token': bootstrap.csrf_token };
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.request.delete('/api/settings/key', { headers });
  await page.goto('/settings');
  await expect(page.getByText('No API key configured', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refresh models' })).toBeDisabled();
  await expect(page.getByText(/Add an API key above/)).toBeVisible();
  await page.screenshot({ path: '/tmp/anki-ux-models-settings-first-use.png', fullPage: false });
  await page.getByLabel('OpenAI API key', { exact: true }).fill('sk-browser-controlled-provider');
  await page.getByRole('button', { name: 'Save API key', exact: true }).click();
  await expect(page.getByText('Key configured', { exact: true })).toBeVisible();
  await expect(page.getByText(/6 account models/)).toBeVisible();
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.locator('.key-connection-result')).toContainText('Connected.');
  const model = page.getByRole('combobox', { name: 'Default processing model', exact: true });
  await model.fill('sol');
  await expect(page.getByRole('option', { name: /GPT-6.1 Sol/ })).toBeVisible();
  await model.press('Enter');
  await expect(model).toHaveValue('GPT-6.1 Sol');
  await expect(page.getByText('You have unsaved preferences')).toBeVisible();
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.getByRole('link', { name: 'Settings', exact: true }).click();
  await expect(model).toHaveValue('GPT-6.1 Sol');
  await page.getByRole('button', { name: 'Refresh models', exact: true }).click();
  await expect(page.getByText(/6 account models · refreshed list/)).toBeVisible();
  await expect(model).toHaveValue('GPT-6.1 Sol');
  await page.getByRole('button', { name: 'Save preferences', exact: true }).last().click();
  await expect(page.getByText('You have unsaved preferences')).toHaveCount(0);
  await page.reload();
  await expect(model).toHaveValue('GPT-6.1 Sol');
  await page.getByText('Choose different models by stage', { exact: true }).click();
  await page.getByRole('combobox', { name: 'Document interpretation', exact: true }).fill('astra');
  await page.getByRole('combobox', { name: 'Document interpretation', exact: true }).press('Enter');
  await page.getByRole('combobox', { name: 'Flashcard generation', exact: true }).fill('luna');
  await page.getByRole('combobox', { name: 'Flashcard generation', exact: true }).press('Enter');
  await page.getByRole('button', { name: 'Save preferences', exact: true }).last().click();
  await expect(page.getByText('You have unsaved preferences')).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole('combobox', { name: 'Document interpretation', exact: true }),
  ).toHaveValue('GPT-6 Astra');
  await expect(
    page.getByRole('combobox', { name: 'Flashcard generation', exact: true }),
  ).toHaveValue('GPT-6 Luna');
  await page.getByRole('button', { name: 'Check model setup', exact: true }).click();
  await expect(page.getByText('Model setup checked', { exact: true })).toBeVisible();
  await page
    .getByRole('heading', { name: 'Models for your courses', exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: '/tmp/anki-ux-models-settings-light.png', fullPage: false });
  const defaultSection = page.locator('.model-preferences > .model-picker').first();
  await defaultSection.getByRole('button', { name: 'Advanced: custom model', exact: true }).click();
  await defaultSection.getByLabel('Custom model ID', { exact: true }).fill('custom-visible-test');
  await defaultSection.getByRole('button', { name: 'Use model', exact: true }).click();
  await page.getByRole('button', { name: 'Check model setup', exact: true }).click();
  await expect(page.getByText('Model setup checked', { exact: true })).toBeVisible();
  await expect(page.locator('.model-validation')).toContainText(
    /unverified|not documented|unknown/i,
  );
  await defaultSection.getByRole('button', { name: 'Advanced: custom model', exact: true }).click();
  await defaultSection.getByLabel('Custom model ID', { exact: true }).fill('not-accessible-test');
  await defaultSection.getByRole('button', { name: 'Use model', exact: true }).click();
  await page.getByRole('button', { name: 'Check model setup', exact: true }).click();
  await expect(page.getByText('Model setup needs attention', { exact: true })).toBeVisible();
  await expect(page.locator('.model-validation')).toContainText(/unavailable|access/i);
  await page.getByLabel('OpenAI API key', { exact: true }).fill('sk-invalid-test');
  await page.getByRole('button', { name: 'Save API key', exact: true }).click();
  await expect(
    page.getByText('The API key was rejected. Replace it in Settings.', { exact: true }),
  ).toBeVisible();
  await expect(model).toHaveValue('not-accessible-test');
  await page.getByLabel('OpenAI API key', { exact: true }).fill('sk-browser-controlled-provider');
  await page.getByRole('button', { name: 'Save API key', exact: true }).click();
  await expect(page.getByText(/6 account models/)).toBeVisible();
  await page.getByLabel('Color theme', { exact: true }).selectOption('dark');
  await model.fill('astra');
  await model.press('Enter');
  await page.getByText('Choose different models by stage', { exact: true }).click();
  await page.locator('.model-preferences').scrollIntoViewIfNeeded();
  await model.click();
  await expect(
    page.getByRole('listbox', { name: 'Default processing model models' }),
  ).toBeVisible();
  expect(await model.evaluate((input) => getComputedStyle(input).borderWidth)).toBe('0px');
  await page.screenshot({ path: '/tmp/anki-ux-models-settings-dark.png', fullPage: false });
  await model.press('Escape');
  await page.setViewportSize({ width: 900, height: 720 });
  await page.locator('#model-preferences').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '/tmp/anki-ux-models-settings-narrow.png', fullPage: false });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(errors).toEqual([]);
  await page.request.patch('/api/settings', { headers, data: bootstrap.settings });
});
