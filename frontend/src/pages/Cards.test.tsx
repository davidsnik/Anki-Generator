import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CardEditor, Flashcard } from './Cards';
import type { Card } from '../services/types';
afterEach(() => vi.unstubAllGlobals());
const card: Card = {
  id: '1',
  card_type: 'basic',
  question: 'State the condition \\(x>0\\).',
  answer: 'Strict positivity.',
  explanation: '',
  tags: [],
  review_status: 'pending',
  verification_status: 'unverified',
};
describe('interactive flashcard', () => {
  it('shows only the question before a flip', () => {
    const flip = vi.fn();
    render(<Flashcard card={card} flipped={false} onFlip={flip} />);
    expect(screen.queryByText('Strict positivity.')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Reveal answer' }));
    expect(flip).toHaveBeenCalledOnce();
  });
  it('shows the answer after a flip', () => {
    render(<Flashcard card={card} flipped onFlip={() => {}} />);
    expect(screen.getByText('Strict positivity.')).toBeInTheDocument();
  });
  it('does not load arbitrary external image references', () => {
    const { container } = render(
      <Flashcard
        card={{
          ...card,
          image_refs: ['https://example.org/tracking.png', '/api/documents/1/regions/r1'],
        }}
        flipped={false}
        onFlip={() => {}}
      />,
    );
    expect(container.querySelectorAll('img')).toHaveLength(1);
    expect(container.querySelector('img')).toHaveAttribute('src', '/api/documents/1/regions/r1');
  });
});
describe('protecting card edits', () => {
  function editor() {
    const close = vi.fn();
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    vi.stubGlobal('fetch', fetch);
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <CardEditor
          course={{
            id: 'course',
            name: 'Analysis',
            description: '',
            deck_name: 'Analysis',
            language: 'English',
            archived: false,
            criteria: {},
          }}
          card={card}
          onClose={close}
        />
      </QueryClientProvider>,
    );
    return { close, fetch };
  }
  it('retains a changed draft after Escape or cancel until discarding is explicit', () => {
    const { close } = editor();
    fireEvent.change(screen.getByLabelText('Question'), {
      target: { value: 'Which assumptions are needed?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('dialog', { name: 'Discard your card changes?' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Question')).toHaveValue('Which assumptions are needed?');
    const dialog = screen.getByRole('dialog', { name: 'Refine this card' });
    fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(close).toHaveBeenCalledOnce();
  });
  it('saves with Ctrl+Enter and requires an answer for basic cards', async () => {
    const { close, fetch } = editor();
    fireEvent.change(screen.getByLabelText('Answer'), { target: { value: '' } });
    expect(screen.getByRole('button', { name: 'Save card' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Answer'), {
      target: { value: 'The variable must be strictly positive.' },
    });
    fireEvent.keyDown(screen.getByLabelText('Answer'), { key: 'Enter', ctrlKey: true });
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(
      fetch.mock.calls.some((call) => call[0] === '/api/cards/1' && call[1]?.method === 'PATCH'),
    ).toBe(true);
  });
});
