import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunDetail } from './Processing';
import { setCsrfToken } from '../services/api';
import type { Run } from '../services/types';
afterEach(() => vi.unstubAllGlobals());
describe('durable processing controls', () => {
  for (const [status, label, action] of [
    ['running', 'Pause at checkpoint', 'pause'],
    ['paused', 'Resume', 'resume'],
    ['failed', 'Retry saved work', 'retry'],
  ]) {
    it(`requests ${action} with the local CSRF token`, async () => {
      const request = vi
        .fn()
        .mockResolvedValue({ ok: true, status: 200, json: async () => ({ status }) });
      vi.stubGlobal('fetch', request);
      setCsrfToken('local-session-token');
      const run: Run = {
        id: 'run-1',
        course_id: 'course-1',
        status,
        created_at: '2026-01-01T12:00:00Z',
        stages: [],
      };
      render(
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
        >
          <RunDetail run={run} />
        </QueryClientProvider>,
      );
      fireEvent.click(screen.getByRole('button', { name: label }));
      await waitFor(() => expect(request).toHaveBeenCalledOnce());
      const [url, options] = request.mock.calls[0];
      expect(url).toBe(`/api/runs/run-1/${action}`);
      expect(options.method).toBe('POST');
      expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('local-session-token');
    });
  }
  it('does not expose pause or cancel on completed jobs', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RunDetail
          run={{
            id: 'done',
            course_id: 'c',
            status: 'completed',
            created_at: '2026-01-01T12:00:00Z',
          }}
        />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole('button', { name: 'Pause at checkpoint' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });
});
