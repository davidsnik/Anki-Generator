import { ArrowLeft, ArrowRight } from 'lucide-react';
export interface PageResult<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  facets?: Record<string, unknown>;
}
export function Pagination({
  offset,
  total,
  limit,
  onChange,
  loading = false,
}: {
  offset: number;
  total: number;
  limit: number;
  onChange: (n: number) => void;
  loading?: boolean;
}) {
  return (
    <div className="pagination">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}`
          : 'No results'}
      </span>
      <div className="inline-actions">
        <button
          className="button small"
          disabled={!offset || loading}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ArrowLeft size={14} />
          Previous page
        </button>
        <button
          className="button small"
          disabled={offset + limit >= total || loading}
          onClick={() => onChange(offset + limit)}
        >
          Next page
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}
