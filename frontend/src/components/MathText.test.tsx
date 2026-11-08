import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MathText } from './MathText';
describe('source-safe mathematical content', () => {
  it('renders KaTeX while keeping imported HTML inert', () => {
    const { container } = render(
      <MathText text={'For \\(x>0\\), <img src=x onerror=alert(1) />'} />,
    );
    expect(container.querySelector('.katex')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/<img/)).toBeInTheDocument();
  });
  it('hides cloze answers and reveals them with valid math', () => {
    const { rerender, container } = render(
      <MathText text={'For independent events, {{c1::\\(P(A)P(B)\\)::product}}.'} cloze />,
    );
    expect(screen.getByText(/\[product\]/)).toBeInTheDocument();
    expect(container.querySelector('.katex')).toBeNull();
    rerender(
      <MathText text={'For independent events, {{c1::\\(P(A)P(B)\\)::product}}.'} cloze reveal />,
    );
    expect(container.querySelector('.katex')).toBeInTheDocument();
    expect(screen.queryByText(/\[product\]/)).toBeNull();
  });
  it('rejects trusted HTML commands in mathematics', () => {
    const { container } = render(<MathText text={'\\(\\href{javascript:alert(1)}{bad}\\)'} />);
    expect(container.querySelector('a')).toBeNull();
  });
});
