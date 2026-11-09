import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ModelPreferences } from './ModelPreferences';
import type { ModelCatalogue } from '../services/models';
import type { Json } from '../services/types';

const stages = ['interpretation', 'knowledge', 'generation', 'factual', 'pedagogical', 'coverage'];
const catalogue: ModelCatalogue = {
  status: 'ready',
  models: [
    {
      id: 'gpt-6-astra',
      name: 'GPT-6 Astra',
      group: 'general',
      available: true,
      capabilities: {
        responses: true,
        vision: true,
        structured_outputs: true,
        embeddings: false,
        reasoning_efforts: ['low', 'medium', 'high'],
      },
      compatibility: Object.fromEntries(stages.map((stage) => [stage, 'supported'])),
      recommended_for: stages,
      documentation: null,
      verified_on: '2026-11-09',
    },
    {
      id: 'gpt-4.1',
      name: 'GPT-4.1',
      group: 'general',
      available: true,
      capabilities: {
        responses: true,
        vision: true,
        structured_outputs: true,
        embeddings: false,
        reasoning_efforts: [],
      },
      compatibility: Object.fromEntries(stages.map((stage) => [stage, 'supported'])),
      recommended_for: [],
      documentation: null,
      verified_on: '2026-11-09',
    },
  ],
  defaults: Object.fromEntries(stages.map((stage) => [stage, 'gpt-6-astra'])),
  default_embedding_model: 'text-embedding-3-small',
  recommendation: 'gpt-6-astra',
  fetched_at: '2026-11-09T12:00:00Z',
  cached: true,
  cache_expires_at: '2026-11-09T12:05:00Z',
  error: null,
  catalogue_verified_on: '2026-11-09',
  notice: 'Capabilities come from dated documentation; the account endpoint only lists access.',
};
function wrap(configured = true, initial: Json = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Harness() {
    const [value, setValue] = useState<Json>(initial);
    return (
      <>
        <ModelPreferences
          value={value}
          configured={configured}
          onChange={(key, next) => setValue((current) => ({ ...current, [key]: next }))}
        />
        <output data-testid="preferences">{JSON.stringify(value)}</output>
      </>
    );
  }
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    ),
  };
}
afterEach(() => vi.unstubAllGlobals());
it('discovers automatically, uses cached results and refreshes without overwriting saved choices', async () => {
  const request = vi.fn(
    async (url: string) =>
      new Response(JSON.stringify({ ...catalogue, cached: !url.includes('refresh=true') })),
  );
  vi.stubGlobal('fetch', request);
  wrap(true, { models: { ...catalogue.defaults, generation: 'custom-saved' } });
  await screen.findByText(/2 account models · cached list/);
  expect(screen.getByRole('combobox', { name: 'Default processing model' })).toHaveValue(
    'custom-saved',
  );
  expect(screen.getByRole('combobox', { name: 'Document interpretation' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh models' }));
  await screen.findByText(/2 account models · refreshed list/);
  expect(request).toHaveBeenCalledWith('/api/settings/models?refresh=true', expect.anything());
  expect(screen.getByRole('combobox', { name: 'Default processing model' })).toHaveValue(
    'custom-saved',
  );
  expect(screen.getByTestId('preferences')).toHaveTextContent('custom-saved');
});
it('applies a chosen default to all stages but keeps advanced custom choices available', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(catalogue))),
  );
  wrap();
  await screen.findByText(/2 account models/);
  const model = screen.getByRole('combobox', { name: 'Default processing model' });
  fireEvent.change(model, { target: { value: '4.1' } });
  fireEvent.keyDown(model, { key: 'Enter' });
  const saved = JSON.parse(screen.getByTestId('preferences').textContent || '{}');
  expect(Object.keys(saved.models)).toHaveLength(6);
  expect(Object.values(saved.models).every((id) => id === 'gpt-4.1')).toBe(true);
  fireEvent.click(screen.getByText(/Reasoning, revisions & semantic search/));
  expect(screen.getByRole('option', { name: 'Maximum' })).toBeVisible();
});
it('explains missing credentials and displays real validation errors and warnings', async () => {
  const request = vi.fn(
    async (url: string) =>
      new Response(
        JSON.stringify(
          url.includes('/validate')
            ? {
                valid: false,
                issues: [
                  {
                    stage: 'generation',
                    model: 'gpt-6-astra',
                    severity: 'error',
                    code: 'unavailable',
                    message: 'This account cannot use the selected model.',
                  },
                ],
                checked_at: 'now',
              }
            : catalogue,
        ),
      ),
  );
  vi.stubGlobal('fetch', request);
  const view = wrap(false);
  await screen.findByText(/Add an API key above/);
  expect(screen.getByRole('button', { name: 'Refresh models' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Check model setup' })).toBeDisabled();
  view.unmount();
  wrap(true);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Check model setup' })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Check model setup' }));
  await screen.findByText('Model setup needs attention');
  expect(screen.getByText(/This account cannot use/)).toBeVisible();
  expect(request.mock.calls.some(([url]) => url.includes('/validate'))).toBe(true);
});
it('displays loading and sanitized discovery failure without resetting the saved model', async () => {
  let complete!: (response: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          complete = resolve;
        }),
    ),
  );
  wrap(true, { models: { generation: 'saved-custom' } });
  expect(screen.getByText(/Loading models available/)).toBeVisible();
  complete(
    new Response(
      JSON.stringify({
        ...catalogue,
        status: 'error',
        error: {
          kind: 'invalid_key',
          message: 'The API key was rejected. Check it in OpenAI connection.',
          retryable: false,
        },
      }),
    ),
  );
  await screen.findByText(/The API key was rejected/);
  expect(screen.getByRole('combobox', { name: 'Default processing model' })).toHaveValue(
    'saved-custom',
  );
});

it('withdraws a previous validation result when credentials produce a different catalogue state', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.includes('/validate') ? { valid: true, issues: [], checked_at: 'now' } : catalogue,
          ),
        ),
    ),
  );
  const { client } = wrap();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Check model setup' })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Check model setup' }));
  await screen.findByText('Model setup checked');
  act(() =>
    client.setQueryData(['models', true], {
      ...catalogue,
      status: 'error',
      error: {
        kind: 'authentication',
        message: 'The replacement key was rejected.',
        retryable: false,
      },
    }),
  );
  await screen.findByText('The replacement key was rejected.');
  expect(screen.queryByText('Model setup checked')).toBeNull();
});
