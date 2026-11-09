import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ModelPicker } from './ModelPicker';
import type { AvailableModel } from '../services/models';

export const fixtureModels: AvailableModel[] = [
  {
    id: 'gpt-6-astra',
    name: 'GPT-6 Astra',
    group: 'general',
    available: true,
    capabilities: {
      responses: true,
      structured_outputs: true,
      vision: true,
      embeddings: false,
      reasoning_efforts: ['low', 'medium', 'high'],
    },
    compatibility: { interpretation: 'supported', generation: 'supported' },
    recommended_for: ['interpretation', 'generation'],
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
      structured_outputs: true,
      vision: true,
      embeddings: false,
      reasoning_efforts: [],
    },
    compatibility: { interpretation: 'supported', generation: 'supported' },
    recommended_for: [],
    documentation: null,
    verified_on: '2026-11-09',
  },
  {
    id: 'private-model',
    name: 'Private model',
    group: 'unverified',
    available: true,
    capabilities: {
      responses: null,
      structured_outputs: null,
      vision: null,
      embeddings: null,
      reasoning_efforts: null,
    },
    compatibility: { interpretation: 'unknown', generation: 'unknown' },
    recommended_for: [],
    documentation: null,
    verified_on: null,
  },
  {
    id: 'unavailable',
    name: 'Unavailable model',
    group: 'general',
    available: false,
    capabilities: {
      responses: true,
      structured_outputs: true,
      vision: true,
      embeddings: false,
      reasoning_efforts: [],
    },
    compatibility: { interpretation: 'supported' },
    recommended_for: [],
    documentation: null,
    verified_on: null,
  },
  {
    id: 'text-embedding-3-small',
    name: 'Text Embedding 3 Small',
    group: 'embeddings',
    available: true,
    capabilities: {
      responses: false,
      structured_outputs: false,
      vision: false,
      embeddings: true,
      reasoning_efforts: [],
    },
    compatibility: { interpretation: 'unsupported', embeddings: 'supported' },
    recommended_for: ['embeddings'],
    documentation: null,
    verified_on: '2026-11-09',
  },
];
describe('model combobox', () => {
  it('searches human names and exact identifiers and selects with the keyboard', () => {
    function Harness() {
      const [value, setValue] = useState('gpt-6-astra');
      return (
        <ModelPicker
          label="Processing model"
          value={value}
          models={fixtureModels}
          stage="interpretation"
          onChange={setValue}
        />
      );
    }
    render(<Harness />);
    const input = screen.getByRole('combobox', { name: 'Processing model' });
    expect(input).toHaveValue('GPT-6 Astra');
    fireEvent.focus(input);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('option', { name: /Text Embedding/ })).toBeNull();
    fireEvent.change(input, { target: { value: 'gpt-4.1' } });
    expect(screen.getAllByRole('option')).toHaveLength(1);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toHaveValue('GPT-4.1');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(input);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(input, { key: 'Escape' });
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input).toHaveValue('GPT-4.1');
  });
  it('preserves a saved unknown model while searching and exposes explicit custom selection', () => {
    const change = vi.fn();
    render(
      <ModelPicker
        label="Processing model"
        value="new-snapshot"
        models={fixtureModels}
        stage="generation"
        onChange={change}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveValue('new-snapshot');
    expect(screen.getByText(/Saved custom model/)).toBeVisible();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'does-not-exist' } });
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' });
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByText(/No matching models/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Advanced: custom model' }));
    fireEvent.change(screen.getByLabelText('Custom model ID'), {
      target: { value: '  future-model  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Use model' }));
    expect(change).toHaveBeenCalledWith('future-model');
  });
  it('labels unknown capability without claiming support and prevents unavailable selection', () => {
    const change = vi.fn();
    render(
      <ModelPicker
        label="Processing model"
        value="gpt-6-astra"
        models={[...fixtureModels].reverse()}
        stage="interpretation"
        onChange={change}
      />,
    );
    fireEvent.focus(screen.getByRole('combobox'));
    expect(screen.getAllByRole('option')[0]).toHaveTextContent('GPT-6 Astra');
    expect(screen.getByRole('option', { name: /Private model/ })).toHaveTextContent(
      'Compatibility unverified',
    );
    const unavailable = screen.getByRole('option', { name: /Unavailable model/ });
    expect(unavailable).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(unavailable);
    expect(change).not.toHaveBeenCalled();
  });
  it('offers embedding models only for semantic search and rejects whitespace custom IDs', () => {
    render(
      <ModelPicker
        label="Semantic search"
        value="text-embedding-3-small"
        models={fixtureModels}
        stage="embeddings"
        onChange={() => {}}
      />,
    );
    fireEvent.focus(screen.getByRole('combobox'));
    expect(screen.queryByRole('option', { name: /GPT-6/ })).toBeNull();
    expect(screen.getByRole('option', { name: /Text Embedding/ })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Advanced: custom model' }));
    fireEvent.change(screen.getByLabelText('Custom model ID'), {
      target: { value: 'invalid model' },
    });
    expect(screen.getByRole('button', { name: 'Use model' })).toBeDisabled();
  });
});
