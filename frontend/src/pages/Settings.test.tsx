import { useState } from 'react';
import type { Bootstrap, Json } from '../services/types';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { KeySetup, CriteriaForm, SettingsPage } from './Settings';
afterEach(() => vi.unstubAllGlobals());
describe('configuration controls', () => {
  it('keeps a new API key masked and explains session storage', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <KeySetup status={{ configured: false }} />
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText('OpenAI API key')).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText('Save in the system credential store')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Show API key' }));
    expect(screen.getByLabelText('OpenAI API key')).toHaveAttribute('type', 'text');
  });
  it('exposes real generation criteria with schema-valid values', () => {
    let change: unknown;
    render(
      <CriteriaForm
        value={{}}
        onChange={(v) => {
          change = v;
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText('Coverage level'), { target: { value: 'focused' } });
    expect(change).toMatchObject({ coverage: 'focused', card_types: ['basic', 'cloze'] });
  });
});

const bootstrap: Bootstrap = {
  csrf_token: 'test',
  settings: {
    theme: 'system',
    models: { generation: 'saved-model' },
    criteria: { instructions: 'Original guidance' },
  },
  key_status: { configured: false },
  courses: [],
  recent_runs: [],
  diagnostics: {},
};
function settingsClient() {
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            status: 'missing_key',
            models: [],
            defaults: {},
            cached: false,
            error: null,
          }),
        ),
    ),
  );
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}
it('keeps edited preferences through background refresh and page remount, then saves with the keyboard', async () => {
  const client = settingsClient();
  const show = (data: Bootstrap) => (
    <QueryClientProvider client={client}>
      <SettingsPage bootstrap={data} />
    </QueryClientProvider>
  );
  const view = render(show(bootstrap));
  expect(screen.getByRole('button', { name: 'Save preferences' })).toBeDisabled();
  fireEvent.change(screen.getByRole('textbox', { name: 'Custom generation guidance' }), {
    target: { value: 'My unsaved guidance' },
  });
  expect(screen.getByText('You have unsaved preferences')).toBeVisible();
  view.rerender(
    show({
      ...bootstrap,
      settings: { ...bootstrap.settings, criteria: { instructions: 'Background value' } },
    }),
  );
  expect(screen.getByRole('textbox', { name: 'Custom generation guidance' })).toHaveValue(
    'My unsaved guidance',
  );
  view.unmount();
  render(show(bootstrap));
  expect(screen.getByRole('textbox', { name: 'Custom generation guidance' })).toHaveValue(
    'My unsaved guidance',
  );
  fireEvent.keyDown(window, { key: 's', ctrlKey: true });
  await waitFor(() => expect(screen.queryByText('You have unsaved preferences')).toBeNull());
  const calls = vi.mocked(fetch).mock.calls;
  expect(
    calls.some(
      ([url, options]) =>
        url === '/api/settings' && String(options?.body).includes('My unsaved guidance'),
    ),
  ).toBe(true);
});
it('discards only unsaved preferences and keeps technical sections collapsed by default', async () => {
  const client = settingsClient();
  render(
    <QueryClientProvider client={client}>
      <SettingsPage bootstrap={bootstrap} />
    </QueryClientProvider>,
  );
  expect(
    screen.getByRole('spinbutton', { name: 'Input tokens per bounded request' }).closest('details'),
  ).not.toHaveAttribute('open');
  expect(
    screen.getByRole('spinbutton', { name: 'Maximum pages per file' }).closest('details'),
  ).not.toHaveAttribute('open');
  fireEvent.change(screen.getByRole('textbox', { name: 'Custom generation guidance' }), {
    target: { value: 'Changed' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
  await waitFor(() => expect(screen.queryByText('You have unsaved preferences')).toBeNull());
  expect(screen.getByRole('textbox', { name: 'Custom generation guidance' })).toHaveValue(
    'Original guidance',
  );
});
it('does not erase new edits made while an earlier settings save is still pending', async () => {
  const client = settingsClient();
  let finish!: (response: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      url === '/api/settings'
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(
            new Response(JSON.stringify({ status: 'missing_key', models: [], error: null })),
          ),
    ),
  );
  render(
    <QueryClientProvider client={client}>
      <SettingsPage bootstrap={bootstrap} />
    </QueryClientProvider>,
  );
  const guidance = screen.getByRole('textbox', { name: 'Custom generation guidance' });
  fireEvent.change(guidance, { target: { value: 'First edit' } });
  fireEvent.click(screen.getAllByRole('button', { name: 'Save preferences' })[0]);
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  fireEvent.change(guidance, { target: { value: 'Newer unsaved edit' } });
  finish(new Response(JSON.stringify({})));
  await waitFor(() =>
    expect(screen.getAllByRole('button', { name: 'Save preferences' })[0]).toBeEnabled(),
  );
  expect(guidance).toHaveValue('Newer unsaved edit');
  expect(screen.getByText('You have unsaved preferences')).toBeVisible();
});
it('shows the real connection-test outcome inline instead of relying on a transient notification', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            ok: false,
            message: 'The account rejected this key. Replace it and test again.',
          }),
        ),
    ),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <KeySetup status={{ configured: true }} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
  await screen.findByText(/Connection needs attention/);
  expect(screen.getByRole('status')).toHaveTextContent('Replace it and test again.');
});

it('applies meaningful named presets while preserving guidance and exclusions without saving', () => {
  const request = vi.fn();
  vi.stubGlobal('fetch', request);
  function Harness() {
    const [criteria, setCriteria] = useState<Json>({
      instructions: 'Retain every theorem assumption.',
      topic_exclusions: ['Appendix'],
      coverage: 'focused',
      card_types: ['basic'],
      include_diagrams: false,
    });
    return <CriteriaForm value={criteria} onChange={setCriteria} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: 'Comprehensive university exam' }));
  expect(screen.getByLabelText('Coverage level')).toHaveValue('comprehensive');
  expect(screen.getByRole('slider', { name: /^Problem-solving methods/ })).toHaveValue('1.2');
  expect(screen.getByLabelText('Answer detail')).toHaveValue('concise');
  expect(screen.getByLabelText('Preserve useful source diagrams')).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Conceptual understanding' }));
  expect(screen.getByLabelText('Coverage level')).toHaveValue('balanced');
  expect(screen.getByRole('slider', { name: /^Conceptual understanding/ })).toHaveValue('1.7');
  expect(screen.getByLabelText('Proof treatment')).toHaveValue('strategies');
  expect(screen.getByLabelText('Example treatment')).toHaveValue('include');
  fireEvent.click(screen.getByRole('button', { name: 'Problem-solving methods' }));
  expect(screen.getByRole('slider', { name: /^Problem-solving methods/ })).toHaveValue('1.8');
  expect(screen.getByRole('slider', { name: /^Theory & definitions/ })).toHaveValue('0.8');
  expect(screen.getByRole('textbox', { name: 'Custom generation guidance' })).toHaveValue(
    'Retain every theorem assumption.',
  );
  expect(screen.getByLabelText('Topic exclusions')).toHaveValue('Appendix');
  expect(screen.getByRole('button', { name: 'Problem-solving methods' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(request).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});
