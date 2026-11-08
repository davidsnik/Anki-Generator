import { useState } from 'react';
import type { Json } from '../services/types';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { KeySetup, CriteriaForm } from './Settings';
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
