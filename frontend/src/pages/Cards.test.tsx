import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Flashcard } from './Cards';
import type { Card } from '../services/types';
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
