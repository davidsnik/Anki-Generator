import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TaskCard, TasksPage } from './TasksPage';
import { TaskControls } from './TaskControls';
import {
  claimTaskNotification,
  GlobalTaskIndicator,
  TaskLiveProvider,
  taskMutationEvent,
} from './live';
import { defaultTaskLimits, SchedulerPreferences } from './SchedulerPreferences';
import { taskActions } from './types';
import type { Task, TaskSummary } from './types';
import { CourseTaskStatus } from './CourseTaskStatus';
import { RunDialog } from '../../pages/Processing';
import { ToastProvider } from '../../components/UI';
import { setCsrfToken } from '../../services/api';
import type { Course, Json } from '../../services/types';

const course: Course = {
  id: 'course-a',
  name: 'Continuous Optimization',
  description: 'Synthetic fixture',
  deck_name: 'Optimization',
  language: 'English',
  criteria: {},
  archived: false,
};
const task: Task = {
  id: 'task-a',
  course_id: course.id,
  course_name: course.name,
  status: 'running',
  priority: 0,
  mode: 'generate',
  created_at: '2026-11-09T12:00:00Z',
  current_stage: 'knowledge',
  allowed_actions: ['pause', 'cancel'],
  statistics: {
    documents_total: 12,
    documents_processed: 2,
    pages_processed: 4,
    concepts_current: 10,
    cards_current: 20,
    cards_verified_current: 18,
    concepts_extracted: 3,
    cards_generated: 4,
    cards_reused: 1,
    cards_verified: 2,
  },
  stages: [{ name: 'knowledge', status: 'running', completed: 2, total: 12 }],
};
function summary(items: Task[] = []): TaskSummary {
  return {
    active_runs: items,
    counts: {
      running: items.filter((x) => x.status === 'running').length,
      queued: items.filter((x) => x.status === 'queued').length,
      active: items.filter((x) => x.status === 'running').length,
      paused: 0,
      failed: 0,
    },
    limits: defaultTaskLimits,
  };
}
function response(data: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => data };
}
function wrap(node: React.ReactNode, route = '/tasks') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const view = render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <ToastProvider>{node}</ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { ...view, client };
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('accurate independent task controls', () => {
  it('labels current course totals and measurable stage work without inventing a percentage', () => {
    wrap(<TaskCard task={task} />);
    expect(screen.getByText(/2 \/ 12 items/)).toBeVisible();
    expect(screen.getByLabelText('Current course inventory')).toHaveTextContent(
      '10 Concepts in course',
    );
    expect(screen.getByText('Concepts extracted')).toBeVisible();
    expect(screen.getByLabelText('Current course inventory')).toHaveTextContent(
      '20 Cards in course',
    );
    expect(screen.getByText('Cards generated')).toBeVisible();
    expect(screen.getByLabelText('Current course inventory')).toHaveTextContent(
      '18 Verified cards in course',
    );
    expect(screen.getByText('Cards verified')).toBeVisible();
    expect(screen.queryByText(/%|remaining|generated this run/i)).toBeNull();
  });
  for (const [status, label, action] of [
    ['running', 'Pause', 'pause'],
    ['paused', 'Resume', 'resume'],
    ['failed', 'Retry', 'retry'],
  ]) {
    it(`sends ${action} for only the selected task`, async () => {
      const fetch = vi.fn().mockResolvedValue(response({}));
      vi.stubGlobal('fetch', fetch);
      setCsrfToken('csrf');
      wrap(<TaskControls task={{ ...task, status, allowed_actions: [action] }} />);
      fireEvent.click(screen.getByRole('button', { name: label }));
      await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
      expect(fetch.mock.calls[0][0]).toBe(`/api/runs/task-a/${action}`);
      expect(new Headers(fetch.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('csrf');
    });
  }
  it('requires cancellation confirmation, follows server actions, and bounds queued priorities', async () => {
    const fetch = vi.fn().mockResolvedValue(response({}));
    vi.stubGlobal('fetch', fetch);
    wrap(
      <TaskControls
        task={{ ...task, status: 'queued', priority: 100, allowed_actions: ['cancel'] }}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
    expect(screen.getByRole('button', { name: /Move .* earlier/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toHaveTextContent('already in flight may finish');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel this task' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(fetch.mock.calls[0][0]).toBe('/api/runs/task-a/cancel');
    expect(taskActions({ ...task, status: 'completed', allowed_actions: [] })).toEqual([]);
  });
  it('withdraws cancellation if a live update completes the task while its confirmation is open', () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    function Harness() {
      const [finished, setFinished] = useState(false);
      return (
        <>
          <TaskControls
            task={finished ? { ...task, status: 'completed', allowed_actions: [] } : task}
          />
          <button onClick={() => setFinished(true)}>Receive completion update</button>
        </>
      );
    }
    wrap(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Receive completion update' }));
    expect(screen.getByRole('button', { name: 'Cancel this task' })).toBeDisabled();
    expect(screen.getByRole('dialog')).toHaveTextContent('cancellation is no longer available');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('retains a launch intent key after a failed request and offers a task link without navigation', async () => {
    let posts = 0;
    const bodies: Json[] = [];
    const fetch = vi.fn(async (_url: string, options?: RequestInit) => {
      if (_url.endsWith('/settings/models/validate')) return response({ valid: true, issues: [] });
      if (_url.endsWith('/settings'))
        return response({ key_status: { configured: true }, models: {}, processing: {} });
      if (_url.endsWith('/documents'))
        return response([{ id: 'document-a', filename: 'Lecture.pdf' }]);
      if (options?.method === 'POST') {
        bodies.push(JSON.parse(String(options.body)));
        posts++;
        return posts === 1
          ? response({ detail: 'Temporary network failure' }, 503)
          : response({ ...task, status: 'queued' });
      }
      return response([]);
    });
    vi.stubGlobal('fetch', fetch);
    const close = vi.fn();
    function Location() {
      return <output data-testid="location">{useLocation().pathname}</output>;
    }
    wrap(
      <>
        <Location />
        <RunDialog course={course} onClose={close} />
      </>,
      '/courses/course-a/documents',
    );
    fireEvent.click(
      screen.getByLabelText(
        'I approve sending this course material to OpenAI for the processing described above.',
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Start processing' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Start processing' }));
    await screen.findByText('Temporary network failure');
    fireEvent.click(screen.getByRole('button', { name: 'Start processing' }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(bodies[0].idempotency_key).toMatch(/^[\da-f-]{36}$/i);
    expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
    expect(screen.getByTestId('location')).toHaveTextContent('/courses/course-a/documents');
    expect(screen.getByRole('link', { name: 'View task' })).toHaveAttribute(
      'href',
      '/tasks/task-a',
    );
  });
});

it('uses server pagination, course/status/type/search/sort and inclusive date filters', async () => {
  const fetch = vi.fn(async (_url: string) =>
    response({ items: [task], total: 30, offset: 24, limit: 24, summary: {} }),
  );
  vi.stubGlobal('fetch', fetch);
  wrap(
    <TasksPage courses={[course]} />,
    '/tasks?offset=24&status=running&mode=generate&course_id=course-a&q=Optimization&sort=priority&date_from=2026-11-01&date_to=2026-11-09',
  );
  await screen.findByRole('article', { name: 'Task Continuous Optimization' });
  const query = new URL(String(fetch.mock.calls[0][0]), 'http://local').searchParams;
  expect(query.get('offset')).toBe('24');
  expect(query.get('limit')).toBe('24');
  expect(query.get('status')).toBe('running');
  expect(query.get('course_id')).toBe('course-a');
  expect(query.get('sort')).toBe('priority');
  expect(query.get('date_from')).toBe(new Date('2026-11-01T00:00:00').toISOString());
  expect(query.get('date_to')).toBe(new Date('2026-11-09T23:59:59.999').toISOString());
  fireEvent.change(screen.getByLabelText('Task type'), { target: { value: 'extract' } });
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) => String(call[0]).includes('mode=extract') && String(call[0]).includes('offset=0'),
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText('Search courses or task IDs…'), {
    target: { value: 'new query' },
  });
  await waitFor(() =>
    expect(fetch.mock.calls.some((call) => String(call[0]).includes('q=new+query'))).toBe(true),
  );
});

it('preserves current cards when a background refresh fails', async () => {
  let fail = false;
  const fetch = vi.fn(async () =>
    fail
      ? response({ detail: 'Connection lost' }, 503)
      : response({ items: [task], total: 1, offset: 0, limit: 24, summary: {} }),
  );
  vi.stubGlobal('fetch', fetch);
  const { client } = wrap(<TasksPage courses={[course]} />);
  await screen.findByRole('article', { name: 'Task Continuous Optimization' });
  fail = true;
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['tasks', 'list'] });
  });
  await screen.findByText('Connection lost');
  expect(screen.getByRole('article', { name: 'Task Continuous Optimization' })).toBeVisible();
});

it('edits distinct global and per-model concurrency limits without silently saving them', () => {
  function Harness() {
    const [value, setValue] = useState<Json>({});
    return (
      <>
        <SchedulerPreferences value={value} onChange={setValue} />
        <output data-testid="value">{JSON.stringify(value)}</output>
      </>
    );
  }
  wrap(<Harness />);
  fireEvent.click(screen.getByText('Customize shared resource limits'));
  fireEvent.change(screen.getByLabelText('Simultaneous course tasks'), { target: { value: '3' } });
  fireEvent.change(screen.getByLabelText('Shared OpenAI request limit'), {
    target: { value: '5' },
  });
  fireEvent.change(screen.getByLabelText('Shared local processing limit'), {
    target: { value: '2' },
  });
  fireEvent.click(screen.getByText('Optional limits for specific models'));
  fireEvent.click(screen.getByRole('button', { name: 'Add model limit' }));
  fireEvent.click(screen.getByRole('button', { name: 'Advanced: custom model' }));
  fireEvent.change(screen.getByLabelText('Custom model ID'), {
    target: { value: 'gpt-6-astra' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Use model' }));
  fireEvent.change(screen.getByLabelText('Model concurrency 1'), { target: { value: '2' } });
  expect(JSON.parse(screen.getByTestId('value').textContent!)).toMatchObject({
    max_concurrent_jobs: 3,
    api_concurrency: 5,
    local_concurrency: 2,
    per_job_api_concurrency: 2,
    per_model_concurrency: { 'gpt-6-astra': 2 },
  });
  expect(screen.getByText(/Save preferences to apply/)).toBeVisible();
});

it('applies understandable speed presets while preserving custom model caps', () => {
  const change = vi.fn();
  wrap(
    <SchedulerPreferences
      value={{ per_model_concurrency: { 'gpt-6-astra': 1 } }}
      onChange={change}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: /Quiet/ }));
  expect(change).toHaveBeenCalledWith(
    expect.objectContaining({
      max_concurrent_jobs: 1,
      api_concurrency: 2,
      local_concurrency: 1,
      per_model_concurrency: { 'gpt-6-astra': 1 },
    }),
  );
});

class FakeChannel {
  static instances: FakeChannel[] = [];
  onmessage: ((event: { data: unknown }) => void) | null = null;
  postMessage = vi.fn();
  close = vi.fn();
  constructor() {
    FakeChannel.instances.push(this);
  }
}
describe('reliable task synchronization', () => {
  it('refreshes on focus, reconnect and cross-tab changes while keeping the last known state', async () => {
    vi.stubGlobal('BroadcastChannel', FakeChannel);
    const fetch = vi.fn().mockResolvedValue(response(summary([task])));
    vi.stubGlobal('fetch', fetch);
    wrap(
      <TaskLiveProvider>
        <GlobalTaskIndicator />
        <CourseTaskStatus courseId={course.id} courseName={course.name} />
      </TaskLiveProvider>,
    );
    await screen.findByRole('link', { name: '1 running · 0 queued tasks' });
    expect(
      screen.getByRole('link', { name: 'View task for Continuous Optimization: Running' }),
    ).toHaveAttribute('href', '/tasks/task-a');
    const count = fetch.mock.calls.length;
    fireEvent(window, new Event('focus'));
    await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(count));
    const focused = fetch.mock.calls.length;
    act(() => FakeChannel.instances.at(-1)!.onmessage?.({ data: {} }));
    await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(focused));
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    fireEvent(window, new Event('offline'));
    expect(screen.getByText('Tasks · reconnecting')).toBeVisible();
    expect(
      screen.getByRole('link', { name: 'View task for Continuous Optimization: Running' }),
    ).toBeVisible();
    const disconnected = fetch.mock.calls.length;
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    fireEvent(window, new Event('online'));
    await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(disconnected));
    expect(screen.getByText('1 running · 0 queued')).toBeVisible();
  });
  it('notifies only a confirmed transition, does not replay historical completions, and deduplicates notices', async () => {
    vi.spyOn(document, 'hasFocus').mockReturnValue(true);
    const complete = { ...task, status: 'completed', finished_at: '2026-11-09T12:30:00Z' };
    const fetch = vi.fn(async (url: string) =>
      response(url.includes('/tasks/task-a') ? complete : summary([task])),
    );
    vi.stubGlobal('fetch', fetch);
    const { client } = wrap(
      <TaskLiveProvider>
        <GlobalTaskIndicator />
      </TaskLiveProvider>,
    );
    await screen.findByText('1 running · 0 queued');
    expect(screen.queryByRole('status')).toBeNull();
    act(() => {
      client.setQueryData(['tasks', 'summary'], summary([]));
    });
    await screen.findByText('Continuous Optimization: completed.');
    expect(screen.getByRole('link', { name: 'View task' })).toHaveAttribute(
      'href',
      '/tasks/task-a',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
    act(() => {
      window.dispatchEvent(new CustomEvent(taskMutationEvent, { detail: { task } }));
      client.setQueryData(['tasks', 'summary'], summary([]));
    });
    await waitFor(() =>
      expect(
        fetch.mock.calls.filter((call) => String(call[0]).includes('/tasks/task-a')).length,
      ).toBeGreaterThanOrEqual(1),
    );
    expect(await claimTaskNotification('task-a:completed:2026-11-09T12:30:00Z')).toBe(false);
    expect(screen.queryByText('Continuous Optimization: completed.')).toBeNull();
  });
});
