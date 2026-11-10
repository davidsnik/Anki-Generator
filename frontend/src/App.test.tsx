import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./services/api', async (original) => ({
  ...(await original<typeof import('./services/api')>()),
  bootstrap: async () => ({
    csrf_token: 'synthetic',
    settings: {},
    key_status: { configured: true },
    courses: [],
    recent_runs: [],
    diagnostics: {},
  }),
}));
vi.mock('./features/tasks/live', () => ({
  TaskLiveProvider: ({ children }: { children: ReactNode }) => children,
  GlobalTaskIndicator: () => null,
  useTasks: () => ({ online: true, failed: false }),
}));

function workspace(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <App />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

it('keeps ordinary course, task and settings navigation without research screens', async () => {
  workspace('/');
  expect(await screen.findByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/');
  expect(screen.getByRole('link', { name: /My courses/ })).toHaveAttribute('href', '/courses');
  expect(screen.getByRole('link', { name: 'Tasks' })).toHaveAttribute('href', '/tasks');
  expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings');
  expect(screen.queryByRole('link', { name: /evaluation|benchmark|experiment/i })).toBeNull();
});

it('treats the retired research route as an unknown page', async () => {
  workspace('/evaluation');
  expect(await screen.findByRole('heading', { name: 'A fresh start' })).toBeVisible();
  expect(
    screen.queryByRole('button', { name: /Create benchmark|Compare configurations/i }),
  ).toBeNull();
  expect(screen.getByRole('link', { name: 'Back to overview' })).toHaveAttribute('href', '/');
});
