import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { selectionBounds, SourceWorkbench } from './SourceWorkbench';
import { ExportPreview } from './ExportPreview';
import { datasetPayload, ReportValues } from './Evaluation';
import { BulkReview, revisionFields, useReviewKeys, VerificationFindings } from './CardReview';
import { Pagination } from './Pagination';
import { ProcessingPreferences } from './ProcessingPreferences';
import { RestoreDialog } from './BackupRestore';
import type { Json } from '../services/types';

afterEach(() => vi.unstubAllGlobals());
function wrap(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      {node}
    </QueryClientProvider>,
  );
}
function response(data: unknown) {
  return { ok: true, status: 200, json: async () => data };
}
describe('source selection coordinates', () => {
  it('inverts display zoom and orders reverse drag coordinates', () =>
    expect(selectionBounds([500, 1000], [100, 200], 2, 600, 2000)).toEqual([50, 100, 250, 500]));
  it('clamps selection to original page bounds including very tall pages', () =>
    expect(selectionBounds([-30, 1000], [900, 15000], 0.5, 600, 12000)).toEqual([
      0, 2000, 600, 12000,
    ]));
  it('rejects non-finite scale and zero-area selections', () => {
    expect(selectionBounds([0, 0], [20, 20], 0, 600, 800)).toBeNull();
    expect(selectionBounds([20, 20], [20, 20], 1, 600, 800)).toBeNull();
  });
});
it('serializes only the strict dataset input contract, preserving explicit synthetic provenance', () => {
  expect(
    datasetPayload({
      id: 'read-only',
      created_at: 'now',
      schema_version: '1',
      name: 'fixture',
      provenance: 'synthetic',
      reviewer: 'Controlled browser',
      reference_concepts: [],
      version: 3,
      source_manifest: {},
    }),
  ).toEqual({
    schema_version: '1',
    name: 'fixture',
    provenance: 'synthetic',
    reviewer: 'Controlled browser',
    reference_concepts: [],
    version: 3,
  });
});
it('identifies changed card fields, tags and source evidence separately', () => {
  const diff = revisionFields(
    { question: 'old', answer: 'same', tags: ['a'], sources: [] },
    {
      question: 'new',
      answer: 'same',
      tags: ['b'],
      sources: [{ document_id: 'd', page_number: 2 }],
    },
  );
  expect(diff.filter((x) => x.changed).map((x) => x.field)).toEqual([
    'question',
    'tags',
    'sources',
  ]);
});
it('keyboard shortcuts pause during typing, modifier keys and nested confirmation dialogs', () => {
  const flip = vi.fn();
  function Keys() {
    useReviewKeys({ f: flip }, true, true);
    return (
      <>
        <input aria-label="Typing" />
        <div contentEditable suppressContentEditableWarning data-testid="editable">
          text
        </div>
      </>
    );
  }
  render(<Keys />);
  fireEvent.keyDown(window, { key: 'f' });
  expect(flip).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(screen.getByLabelText('Typing'), { key: 'f' });
  fireEvent.keyDown(screen.getByTestId('editable'), { key: 'f' });
  fireEvent.keyDown(window, { key: 'f', ctrlKey: true });
  expect(flip).toHaveBeenCalledTimes(1);
  const one = document.createElement('dialog');
  one.open = true;
  const two = one.cloneNode() as HTMLDialogElement;
  document.body.append(one, two);
  fireEvent.keyDown(window, { key: 'f' });
  expect(flip).toHaveBeenCalledTimes(1);
  one.remove();
  two.remove();
});
it('pagination bounds the next and previous offsets without loading the whole collection', () => {
  const change = vi.fn();
  render(<Pagination offset={24} total={1500} limit={24} onChange={change} />);
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
  expect(change).toHaveBeenLastCalledWith(48);
  fireEvent.click(screen.getByRole('button', { name: 'Previous page' }));
  expect(change).toHaveBeenLastCalledWith(0);
});
it('bulk actions submit exact explicit IDs and selected revision guards after rationale and confirmation', async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    response({ updated: 2 }),
  );
  vi.stubGlobal('fetch', fetch);
  wrap(
    <BulkReview
      courseId="course"
      selection={
        new Map([
          ['one', 2],
          ['two', 5],
        ])
      }
      onClear={() => {}}
      concepts={[]}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Review bulk action' }));
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Confirm selected action' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Reason / regeneration guidance'), {
    target: { value: 'Checked both original sources.' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm selected action' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(JSON.parse(String(fetch.mock.calls[0][1]!.body))).toMatchObject({
    card_ids: ['one', 'two'],
    expected_revisions: { one: 2, two: 5 },
    action: 'approve',
    confirm: true,
    reason: 'Checked both original sources.',
    overwrite_manual: false,
  });
});
it('processing controls retain bounded settings and permit removing a prompt override without saving', () => {
  function Harness() {
    const [value, setValue] = useState<Json>({});
    const [prompts, setPrompts] = useState<Record<string, string>>({
      generation: 'Versioned alternate prompt',
    });
    return (
      <ProcessingPreferences
        value={value}
        prompts={prompts}
        onChange={setValue}
        onPrompts={setPrompts}
      />
    );
  }
  render(<Harness />);
  fireEvent.change(screen.getByLabelText('Per-pipeline request limit'), { target: { value: '3' } });
  expect(screen.getByLabelText('Per-pipeline request limit')).toHaveValue(3);
  expect(screen.getByLabelText('Input tokens per bounded request')).toHaveAttribute(
    'max',
    '128000',
  );
  fireEvent.change(screen.getByLabelText('Prompt override'), { target: { value: '' } });
  expect(screen.getByLabelText('Prompt override')).toHaveValue('');
});
it('restore validates the uploaded archive and requires an explicit typed confirmation', async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    response({
      token: 'validated-token',
      version_compatible: true,
      summary: { courses: 2, cards: 50 },
      warnings: [],
    }),
  );
  vi.stubGlobal('fetch', fetch);
  wrap(<RestoreDialog onClose={() => {}} />);
  expect(screen.getByRole('button', { name: 'Validate backup' })).toBeDisabled();
  const file = new File(['zip'], 'backup.zip', { type: 'application/zip' });
  const input = document.querySelector('input[type=file]')!;
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getByRole('button', { name: 'Validate backup' }));
  await screen.findByText('Validation passed');
  expect(fetch.mock.calls[0][1]!.body).toBeInstanceOf(FormData);
  expect(screen.getByRole('button', { name: 'Restore validated backup' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Type RESTORE to confirm'), {
    target: { value: 'RESTORE' },
  });
  expect(screen.getByRole('button', { name: 'Restore validated backup' })).toBeEnabled();
});

it('verified source correction requires replacement permission and sends the revision originally opened', async () => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
  const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) =>
    response(
      init?.method === 'POST'
        ? {}
        : {
            document_id: 'doc',
            source_sha256: 'immutable',
            corrections: [],
            pages: [
              {
                page_number: 1,
                width: 600,
                height: 800,
                original_text: 'original',
                effective_text: 'verified text',
                correction_revision: 4,
                human_verified: true,
                regions: [],
                corrections: [],
              },
            ],
          },
    ),
  );
  vi.stubGlobal('fetch', fetch);
  wrap(<SourceWorkbench documentId="doc" onClose={() => {}} />);
  const text = await screen.findByLabelText('Corrected transcription');
  await waitFor(() => expect(text).toHaveValue('verified text'));
  fireEvent.change(text, { target: { value: 'Corrected \\(a^2+b^2=c^2\\)' } });
  fireEvent.change(screen.getByLabelText('Correction rationale'), {
    target: { value: 'Original evidence checked; fix the symbol.' },
  });
  expect(screen.getByRole('button', { name: 'Save transcription correction' })).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/I explicitly allow replacing/));
  fireEvent.click(screen.getByRole('button', { name: 'Save transcription correction' }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
  );
  const posted = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!;
  expect(JSON.parse(String(posted[1]?.body))).toMatchObject({
    expected_revision: 4,
    replace_verified: true,
    verified: true,
    text: 'Corrected \\(a^2+b^2=c^2\\)',
  });
});

it('export preview blocks export while uncertainty exists and exposes complete category counts', async () => {
  const blocked = vi.fn();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({
        counts: { new: 5, matching: 9, modified: 3, uncertain: 2, missing: 1, duplicates: 0 },
        export_blocked: true,
        uncertain: [],
        pagination: { offset: 0, limit: 25, has_more: false },
        limitations: [],
      }),
    ),
  );
  wrap(<ExportPreview courseId="course" selection={null} onBlocked={blocked} />);
  await screen.findByText(/Resolve uncertain identity matches/);
  expect(blocked).toHaveBeenLastCalledWith(true);
  expect(screen.getByText('Modified (3)')).toBeVisible();
});

it('incompatible backups remain blocked even after typing the confirmation', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({
        token: 'bad',
        version_compatible: false,
        summary: { schema_version: 999 },
        warnings: ['Unsupported schema'],
      }),
    ),
  );
  wrap(<RestoreDialog onClose={() => {}} />);
  fireEvent.change(document.querySelector('input[type=file]')!, {
    target: { files: [new File(['bad'], 'future.zip')] },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Validate backup' }));
  await screen.findByText('Backup cannot be restored');
  fireEvent.change(screen.getByLabelText('Type RESTORE to confirm'), {
    target: { value: 'RESTORE' },
  });
  expect(screen.getByRole('button', { name: 'Restore validated backup' })).toBeDisabled();
});

it('renders evaluation denominators and unknown results without implying unmeasured success', () => {
  render(
    <ReportValues
      value={{
        review_progress: { numerator: 0, denominator: 4, value: 0 },
        acceptance: { numerator: 0, denominator: 0, value: null },
      }}
    />,
  );
  expect(screen.getByText('0 / 4')).toBeVisible();
  expect(screen.getByText('0%')).toBeVisible();
  expect(screen.getByText('0 / 0')).toBeVisible();
  expect(screen.getByText('Not measured')).toBeVisible();
});
it('labels bounded symbolic calculations separately from model judgments and displays their limits', () => {
  render(
    <VerificationFindings
      verifications={[
        {
          stage: 'symbolic',
          model: 'sympy-bounded-ast',
          verdict: 'pass',
          details: {
            checks: [
              {
                operation: 'differentiate',
                verdict: 'pass',
                reason: 'Equal derivative under the stated real-variable domain.',
              },
            ],
            formal_proof: false,
          },
        },
      ]}
      issues={[]}
    />,
  );
  expect(
    screen.getByText('Equal derivative under the stated real-variable domain.', { exact: true }),
  ).toBeVisible();
  expect(screen.queryByText(/Model judgment/)).toBeNull();
  expect(screen.getByText(/does not establish a general theorem/)).toBeVisible();
});

it('ignores server-generated source links when comparing immutable revision evidence', () => {
  const before = { sources: [{ document_id: 'doc', page_number: 1 }] };
  const after = {
    sources: [
      {
        page_number: 1,
        document_id: 'doc',
        source_url: '/api/documents/doc/source',
        image_url: '/api/region',
      },
    ],
  };
  expect(revisionFields(before, after).find((item) => item.field === 'sources')?.changed).toBe(
    false,
  );
});
