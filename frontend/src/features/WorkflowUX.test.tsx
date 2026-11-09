import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { RunDialog } from '../pages/Processing';
import { ExportsPage } from '../pages/Exports';
import { SourceWorkbench } from './SourceWorkbench';
import type { Course } from '../services/types';

const course: Course = {
  id: 'course',
  name: 'Analysis',
  description: '',
  deck_name: 'Analysis',
  language: 'English',
  archived: false,
  criteria: {},
};
const document = {
  id: 'doc',
  filename: 'Lecture.pdf',
  category: 'lecture',
  authority: 'primary',
  status: 'ready',
};
const response = (value: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => value,
});
function wrap(children: ReactNode) {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
          })
        }
      >
        {children}
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
function stubRun({
  documents = [document],
  configured = true,
  valid = true,
  issues = [],
}: { documents?: unknown[]; configured?: boolean; valid?: boolean; issues?: unknown[] } = {}) {
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith('/documents')) return response(documents);
    if (url.endsWith('/settings')) return response({ key_status: { configured } });
    if (url.endsWith('/models/validate')) return response({ valid, issues });
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
afterEach(() => vi.unstubAllGlobals());

describe('processing readiness', () => {
  it('offers local extraction with no key while preventing a model run', async () => {
    const fetch = stubRun({ configured: false });
    wrap(<RunDialog course={course} onClose={() => {}} />);
    await screen.findByText(/Add your OpenAI API key to generate cards/);
    fireEvent.click(screen.getByLabelText(/I approve sending this course material/));
    expect(screen.getByRole('button', { name: 'Start processing' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Extract documents locally only'));
    expect(screen.getByRole('button', { name: 'Start local extraction' })).toBeEnabled();
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/models/validate'))).toBe(false);
  });
  it('requires documents even for local-only extraction and links to import', async () => {
    stubRun({ documents: [] });
    wrap(<RunDialog course={course} mode="extract" onClose={() => {}} />);
    await screen.findByText(/Import at least one source document first/);
    expect(screen.getByRole('link', { name: 'Open Documents' })).toHaveAttribute(
      'href',
      '/courses/course/documents',
    );
    expect(screen.getByRole('button', { name: 'Start local extraction' })).toBeDisabled();
  });
  it('explains inaccessible selections and prevents consent from bypassing preflight', async () => {
    stubRun({
      valid: false,
      issues: [{ severity: 'error', message: 'The saved generation model is unavailable.' }],
    });
    wrap(<RunDialog course={course} onClose={() => {}} />);
    await screen.findByText('The saved generation model is unavailable.');
    fireEvent.click(screen.getByLabelText(/I approve sending this course material/));
    expect(screen.getByRole('button', { name: 'Start processing' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Review models in Settings' })).toHaveAttribute(
      'href',
      '/settings',
    );
  });
  it('shows unverified custom capabilities and still requires consent', async () => {
    const fetch = stubRun({
      issues: [
        { severity: 'warning', message: 'Custom model capabilities have not been verified.' },
      ],
    });
    wrap(<RunDialog course={course} onClose={() => {}} />);
    await screen.findByText('Custom model capabilities have not been verified.');
    expect(screen.getByRole('button', { name: 'Start processing' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I approve sending this course material/));
    expect(screen.getByRole('button', { name: 'Start processing' })).toBeEnabled();
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/runs'))).toBe(false);
  });
});
function stubSource() {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({
        document_id: 'doc',
        source_sha256: 'hash',
        corrections: [],
        pages: [
          {
            page_number: 1,
            text: 'First original',
            effective_text: 'First original',
            width: 600,
            height: 800,
            regions: [],
          },
          {
            page_number: 2,
            text: 'Second original',
            effective_text: 'Second original',
            width: 600,
            height: 800,
            regions: [],
          },
        ],
      }),
    ),
  );
}
describe('transcription changes', () => {
  it('keeps unsaved text when closing is cancelled and requires explicit discard', async () => {
    stubSource();
    const close = vi.fn();
    wrap(<SourceWorkbench documentId="doc" onClose={close} />);
    const text = await screen.findByLabelText('Corrected transcription');
    await waitFor(() => expect(text).toHaveValue('First original'));
    fireEvent.change(text, { target: { value: 'Carefully corrected mathematical notation' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    const confirmation = screen.getByRole('dialog', {
      name: 'Discard unsaved transcription changes?',
    });
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole('button', { name: 'Keep editing' }));
    expect(text).toHaveValue('Carefully corrected mathematical notation');
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes and close' }));
    expect(close).toHaveBeenCalledOnce();
  });
  it('guards page changes when only the rationale changed', async () => {
    stubSource();
    wrap(<SourceWorkbench documentId="doc" onClose={() => {}} />);
    const text = await screen.findByLabelText('Corrected transcription');
    await waitFor(() => expect(text).toHaveValue('First original'));
    fireEvent.change(screen.getByLabelText('Correction rationale'), {
      target: { value: 'Checked the sign against the original' },
    });
    fireEvent.change(screen.getByLabelText('Page'), { target: { value: '2' } });
    expect(text).toHaveValue('First original');
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes and switch page' }));
    await waitFor(() => expect(text).toHaveValue('Second original'));
    expect(screen.getByLabelText('Correction rationale')).toHaveValue('');
  });
});

describe('export scope and destination', () => {
  function stubExports() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/cards-page'))
          return response({
            items: [
              {
                id: 'approved',
                question: 'A question',
                answer: 'An answer',
                explanation: '',
                card_type: 'basic',
                tags: [],
                review_status: 'approved',
                verification_status: 'verified',
              },
            ],
            total: 1,
            offset: 0,
            limit: 25,
          });
        if (url.includes('/identity-proposals')) return response({ items: [], total: 0 });
        if (url.includes('/export-preview'))
          return response({
            counts: { new: 1 },
            export_blocked: false,
            limitations: [],
            pagination: { offset: 0, limit: 25, has_more: false },
          });
        if (url.endsWith('/exports')) return response([]);
        throw new Error(`Unexpected request ${url}`);
      }),
    );
  }
  it('distinguishes an empty explicit selection from a course with no approved cards', async () => {
    stubExports();
    wrap(<ExportsPage course={{ ...course, stats: { approved: 1 } }} />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Save Anki package (.apkg)' })).toBeEnabled(),
    );
    expect(screen.getByText(/Saving a file here/)).toHaveTextContent(
      'does not import it into Anki',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(screen.getByRole('button', { name: 'Save Anki package (.apkg)' })).toBeDisabled();
    expect(screen.getByText(/Select cards on the right/)).toBeVisible();
    expect(screen.queryByText(/No cards are approved yet/)).toBeNull();
  });
  it('shows Anki-only identity and deck controls only for an Anki package', async () => {
    stubExports();
    wrap(<ExportsPage course={{ ...course, stats: { approved: 1 } }} />);
    await screen.findByRole('heading', { name: 'Identity and update preview' });
    fireEvent.click(screen.getByRole('button', { name: /Structured data/ }));
    expect(screen.queryByLabelText('Deck name in Anki')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Identity and update preview' })).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Save JSON file' })).toBeEnabled(),
    );
  });
});
