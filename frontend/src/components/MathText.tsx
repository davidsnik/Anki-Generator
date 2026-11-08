import katex from 'katex';
import { useMemo } from 'react';
import type { ReactNode } from 'react';
// Only KaTeX's own escaped, trust:false output is inserted. Course prose is React text.
export function MathText({
  text = '',
  className = '',
  cloze = false,
  reveal = false,
}: {
  text?: string;
  className?: string;
  cloze?: boolean;
  reveal?: boolean;
}) {
  const content = cloze
    ? text.replace(/\{\{c\d+::([\s\S]*?)(?:::(.*?))?\}\}/g, (_m, answer, hint) =>
        reveal ? answer : `[${hint || '…'}]`,
      )
    : text;
  const parts = useMemo(() => {
    const out: ReactNode[] = [];
    const pattern = /(\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|\$\$([\s\S]*?)\$\$|\$([^$\n]+)\$)/g;
    let cursor = 0;
    for (const match of content.matchAll(pattern)) {
      out.push(content.slice(cursor, match.index));
      const expression = match[2] ?? match[3] ?? match[4] ?? match[5];
      try {
        const html = katex.renderToString(expression, {
          throwOnError: false,
          trust: false,
          strict: 'warn',
          displayMode: !!(match[2] || match[4]),
          output: 'htmlAndMathml',
        });
        out.push(
          <span key={match.index} className="math" dangerouslySetInnerHTML={{ __html: html }} />,
        );
      } catch {
        out.push(<code key={match.index}>{match[0]}</code>);
      }
      cursor = match.index! + match[0].length;
    }
    out.push(content.slice(cursor));
    return out;
  }, [content]);
  return <div className={`math-text ${className}`}>{parts}</div>;
}
