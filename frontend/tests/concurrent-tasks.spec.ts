import { test, expect, type Page } from '@playwright/test';

async function createCourse(page: Page, name: string) {
  await page.goto('/courses');
  await page.getByRole('button', { name: 'New course', exact: true }).click();
  await page.getByLabel('Course name', { exact: true }).fill(name);
  await page
    .getByLabel('Description optional')
    .fill(
      'Controlled synthetic concurrency fixture. Independent source ownership; no domain-quality claim.',
    );
  await page.getByRole('button', { name: 'Create course', exact: true }).last().click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  const id = page.url().match(/\/courses\/([^/]+)/)![1];
  const filename = `${name.replace(/[^a-zA-Z]/g, '-')}-lecture.txt`;
  await page.locator('input[type=file]:not([webkitdirectory])').setInputFiles({
    name: filename,
    mimeType: 'text/plain',
    buffer: Buffer.from(
      `Synthetic source owned by ${name}.\nFor a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is required. The hypotenuse is the positive side opposite the right angle.`,
    ),
  });
  await page.getByRole('button', { name: 'Import materials', exact: true }).click();
  await expect(page.getByRole('button', { name: filename, exact: true })).toBeVisible();
  return { id, name };
}
async function start(page: Page, id: string) {
  await page.goto(`/courses/${id}/documents`);
  await page.getByRole('button', { name: 'Generate cards', exact: true }).click();
  await page
    .getByLabel(
      'I approve sending this course material to OpenAI for the processing described above.',
    )
    .check();
  const response = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().endsWith(`/courses/${id}/runs`),
  );
  await page.getByRole('button', { name: 'Start processing', exact: true }).click();
  const request = await response;
  expect(request.ok()).toBe(true);
  await expect(page).toHaveURL(new RegExp(`/courses/${id}/documents$`));
  return (await request.json()) as { id: string; status: string };
}

test('genuinely concurrent synthetic courses keep independent progress, queue, controls and exportable outputs', async ({
  page,
  context,
}) => {
  test.setTimeout(240000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/settings');
  await page
    .getByLabel('OpenAI API key', { exact: true })
    .fill('sk-controlled-concurrency-fixture');
  await page.getByRole('button', { name: 'Save API key', exact: true }).click();
  await expect(page.getByText('Key configured', { exact: true })).toBeVisible();
  await page.getByText('Customize shared resource limits', { exact: true }).click();
  await page.getByLabel('Simultaneous course tasks').fill('2');
  await page.getByLabel('Shared OpenAI request limit').fill('4');
  await page.getByLabel('Shared local processing limit').fill('2');
  await page.getByLabel('OpenAI requests per task').fill('2');
  const savePreferences = page.getByRole('button', { name: 'Save preferences', exact: true });
  if (await savePreferences.isEnabled()) {
    await savePreferences.click();
    await expect(page.locator('.toast')).toContainText('saved');
  }
  const configured = await (await page.request.get('/api/settings')).json();
  expect(configured.tasks).toMatchObject({
    max_concurrent_jobs: 2,
    api_concurrency: 4,
    local_concurrency: 2,
  });
  const stamp = Date.now();
  const a = await createCourse(page, `Continuous Optimization ${stamp}`);
  const b = await createCourse(page, `Machine Learning ${stamp}`);
  const c = await createCourse(page, `Probability Theory ${stamp}`);
  const bootstrap = await (await page.request.get('/api/bootstrap')).json();
  const headers = { 'X-CSRF-Token': bootstrap.csrf_token };
  const post = async (path: string, data: unknown = {}) => {
    const response = await page.request.post(path, { headers, data });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  };
  await post('/api/test/concurrency', { course_ids: [a.id, b.id, c.id] });
  const jobs: Array<{ id: string }> = [];
  const release = async (id: string) => post(`/api/test/concurrency/${id}/release`);
  const state = async () =>
    (await (await page.request.get('/api/test/concurrency')).json()) as {
      waiting: string[];
      entered: Record<string, string>;
    };
  const status = async (id: string) =>
    (await (await page.request.get(`/api/tasks/${id}`)).json()).status as string;
  let other: Page | undefined;
  try {
    const first = await start(page, a.id);
    jobs.push(first);
    const second = await start(page, b.id);
    jobs.push(second);
    // Both provider calls must be inside barriers simultaneously. A serial worker cannot satisfy this.
    await expect
      .poll(async () => (await state()).waiting.sort(), { timeout: 45000 })
      .toEqual([a.id, b.id].sort());
    expect((await state()).entered).toHaveProperty(a.id);
    expect((await state()).entered).toHaveProperty(b.id);
    const third = await start(page, c.id);
    jobs.push(third);
    await expect.poll(() => status(third.id)).toBe('queued');
    await page.getByRole('link', { name: 'Tasks', exact: true }).click();
    await expect(page.getByRole('link', { name: '2 running · 1 queued tasks' })).toBeVisible();
    const firstRow = page.getByTestId(`task-${first.id}`),
      secondRow = page.getByTestId(`task-${second.id}`),
      thirdRow = page.getByTestId(`task-${third.id}`);
    await expect(firstRow.getByText('Running', { exact: true })).toBeVisible();
    await expect(secondRow.getByText('Running', { exact: true })).toBeVisible();
    await expect(thirdRow.locator('.badge').filter({ hasText: 'Queued' })).toBeVisible();
    await thirdRow.getByRole('button', { name: 'Priority 0', exact: true }).click();
    await page.getByLabel('Priority', { exact: true }).fill('5');
    await page.getByRole('button', { name: 'Save priority', exact: true }).click();
    await expect(thirdRow.getByRole('button', { name: 'Priority 5', exact: true })).toBeVisible();
    other = await context.newPage();
    await other.goto('/tasks');
    await expect(
      other
        .getByTestId(`task-${third.id}`)
        .getByRole('button', { name: 'Priority 5', exact: true }),
    ).toBeVisible();
    await page.bringToFront();
    await thirdRow.getByRole('button', { name: `Move ${c.name} earlier in queue` }).click();
    await expect(
      other
        .getByTestId(`task-${third.id}`)
        .getByRole('button', { name: 'Priority 6', exact: true }),
    ).toBeVisible();
    await context.setOffline(true);
    await expect(page.getByText('Tasks · reconnecting', { exact: true })).toBeVisible();
    await expect(firstRow).toBeVisible();
    await context.setOffline(false);
    await expect(page.getByRole('link', { name: '2 running · 1 queued tasks' })).toBeVisible();
    await page.reload();
    await expect(
      page.getByTestId(`task-${first.id}`).getByText('Running', { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: '/tmp/anki-ui-task-queue.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.getByLabel('Task status').selectOption('running');
    await expect(page.locator('.task-card')).toHaveCount(2);
    await page.screenshot({
      path: '/tmp/anki-ui-tasks.png',
      fullPage: true,
      animations: 'disabled',
    });
    await page.goto(`/tasks/${first.id}`);
    await expect(page.getByRole('heading', { name: a.name, exact: true })).toBeVisible();
    await page.getByRole('tab', { name: 'Configuration', exact: true }).click();
    await expect(page.locator('.task-configuration')).toContainText('gpt-6-astra');
    await page.getByRole('tab', { name: 'Activity', exact: true }).click();
    await expect(page.locator('.task-events li').first()).toBeVisible();
    await page.getByRole('tab', { name: 'Pipeline', exact: true }).click();
    await page.screenshot({
      path: '/tmp/anki-ui-task-detail.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.goto(`/courses/${b.id}/documents`);
    await expect(
      page.getByRole('link', { name: new RegExp(`View task for ${b.name}: Running`) }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Generate cards', exact: true })).toBeDisabled();
    // Completion of A admits queued C even though B is still held in its own request.
    await release(a.id);
    await expect.poll(() => status(first.id), { timeout: 60000 }).toBe('completed');
    const completedA = await (await page.request.get(`/api/tasks/${first.id}`)).json();
    expect(completedA.statistics.concepts_extracted).toBeGreaterThan(0);
    expect(completedA.statistics.cards_generated).toBe(1);
    expect(completedA.statistics.cards_verified).toBe(1);
    await expect
      .poll(async () => (await state()).waiting.sort(), { timeout: 30000 })
      .toEqual([b.id, c.id].sort());
    expect(await status(second.id)).toBe('running');
    await page.goto(`/courses/${a.id}/cards`);
    await expect(page.locator('.card-tile').first()).toBeVisible();
    await page.getByRole('button', { name: 'Inspect & review' }).first().click();
    await page
      .getByLabel('Review rationale required for unverified approval')
      .fill(
        'Synthetic browser exercise: checked source ownership, right-angle condition and formula. This is not independent human validation.',
      );
    await page.getByRole('button', { name: 'Approve', exact: true }).click();
    await expect(page.locator('.toast')).toContainText('review decision');
    await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
    await page.getByRole('link', { name: 'Exports', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save Anki package (.apkg)' })).toBeEnabled();
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Save Anki package (.apkg)' }).click();
    expect((await download).suggestedFilename()).toMatch(/\.apkg$/);
    expect(await status(second.id)).toBe('running');
    // Pause and cancel operate only on their selected tasks, at safe request boundaries.
    await page.goto('/tasks');
    await page
      .getByTestId(`task-${second.id}`)
      .getByRole('button', { name: 'Pause', exact: true })
      .click();
    await expect.poll(() => status(second.id)).toBe('pausing');
    await release(b.id);
    await expect.poll(() => status(second.id), { timeout: 45000 }).toBe('paused');
    await page
      .getByTestId(`task-${third.id}`)
      .getByRole('button', { name: 'Cancel', exact: true })
      .click();
    await expect(page.getByRole('dialog')).toContainText('already in flight');
    await page.getByRole('button', { name: 'Cancel this task', exact: true }).click();
    await release(c.id);
    await expect.poll(() => status(third.id), { timeout: 45000 }).toBe('cancelled');
    expect(await status(first.id)).toBe('completed');
    expect(await status(second.id)).toBe('paused');
    await page
      .getByTestId(`task-${second.id}`)
      .getByRole('button', { name: 'Resume', exact: true })
      .click();
    await expect.poll(() => status(second.id), { timeout: 60000 }).toBe('completed');
    const cardsA = await (await page.request.get(`/api/courses/${a.id}/cards`)).json();
    const cardsB = await (await page.request.get(`/api/courses/${b.id}/cards`)).json();
    expect(cardsA).toHaveLength(1);
    expect(cardsB).toHaveLength(1);
    expect(cardsA[0].course_id).toBe(a.id);
    expect(cardsB[0].course_id).toBe(b.id);
    expect(cardsA[0].id).not.toBe(cardsB[0].id);
    expect(cardsA[0].note_guid).not.toBe(cardsB[0].note_guid);
    const documentsA = await (await page.request.get(`/api/courses/${a.id}/documents`)).json();
    const documentsB = await (await page.request.get(`/api/courses/${b.id}/documents`)).json();
    expect(
      cardsA[0].sources.every((source: { document_id: string }) =>
        documentsA.some((doc: { id: string }) => doc.id === source.document_id),
      ),
    ).toBe(true);
    expect(
      cardsB[0].sources.every((source: { document_id: string }) =>
        documentsB.some((doc: { id: string }) => doc.id === source.document_id),
      ),
    ).toBe(true);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/tasks');
    await page.getByLabel('Task course').selectOption(b.id);
    await expect(
      page.getByTestId(`task-${second.id}`).locator('.badge').filter({ hasText: 'Completed' }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.screenshot({
      path: '/tmp/anki-ui-tasks-mobile.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.getByTestId(`task-${second.id}`).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: '/tmp/anki-ui-tasks-mobile-card.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.goto(`/tasks/${second.id}`);
    await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
    await page.getByRole('button', { name: 'Switch to dark theme', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.locator('.sidebar-backdrop').click({ position: { x: 350, y: 400 } });
    await expect
      .poll(async () => {
        const box = await page.locator('.sidebar').boundingBox();
        return box ? box.x + box.width : 0;
      })
      .toBeLessThanOrEqual(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.screenshot({
      path: '/tmp/anki-ui-task-mobile-detail.png',
      fullPage: false,
      animations: 'disabled',
    });
    expect(errors).toEqual([]);
  } finally {
    await context.setOffline(false);
    for (const item of [a, b, c]) await release(item.id).catch(() => {});
    for (const job of jobs) {
      const current = await status(job.id).catch(() => null);
      if (current && ['queued', 'running', 'pausing', 'paused', 'failed'].includes(current))
        await post(`/api/runs/${job.id}/cancel`).catch(() => {});
    }
    await other?.close();
  }
});
