import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Network, SearchCheck } from 'lucide-react';
import { api } from '../services/api';
import type { Json, Source } from '../services/types';
import { Badge, ErrorPanel, Loading, SectionHead, human } from '../components/UI';
import { MathText } from '../components/MathText';
import { SourcePreview } from '../pages/Documents';
import { Pagination } from './Pagination';
import type { PageResult } from './Pagination';
export function CoverageAudit({ courseId }: { courseId: string }) {
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState('');
  const [status, setStatus] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const targets = useQuery({
    queryKey: ['source-coverage', courseId, offset, kind, status],
    queryFn: () =>
      api<PageResult<Json> & { summary: Json }>(
        `/courses/${courseId}/coverage-targets?offset=${offset}&limit=50&kind=${encodeURIComponent(kind)}&status=${encodeURIComponent(status)}`,
      ),
    refetchInterval: 5000,
  });
  return (
    <section className="panel coverage-audit">
      <SectionHead title="Independent source-grounded coverage" action={<SearchCheck size={20} />}>
        This audit revisits original page evidence to detect learning targets absent from the
        initial concept inventory.
      </SectionHead>
      <div className="filter-row">
        <select
          aria-label="Coverage target kind"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All learning targets</option>
          {[
            'concept',
            'topic',
            'subtopic',
            'theorem',
            'definition',
            'assumption',
            'method',
            'competency',
            'exercise_pattern',
          ].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <select
          aria-label="Coverage target status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All coverage states</option>
          {['covered', 'uncovered', 'unmapped', 'partial', 'unresolved'].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </div>
      {targets.isPending ? (
        <Loading />
      ) : targets.error ? (
        <ErrorPanel error={targets.error} />
      ) : (
        <>
          <div className="coverage-strip">
            <Network size={20} />
            <strong>{targets.data.total}</strong>
            <span>source-grounded targets matching filters</span>
          </div>
          {targets.data.items.map((target, index) => (
            <details className="coverage-target" key={String(target.id || index)}>
              <summary>
                <strong>{String(target.title || target.label || target.key)}</strong>{' '}
                <Badge tone={target.status === 'covered' ? 'green' : 'amber'}>
                  {human(String(target.status || 'unresolved'))}
                </Badge>{' '}
                · {human(String(target.kind || 'concept'))}
              </summary>
              <MathText text={String(target.description || target.statement || '')} />
              <p className="field-help">
                Mapped concepts:{' '}
                {((target.mapped_concept_ids || []) as string[]).join(', ') ||
                  'No concept mapping — possible extraction omission'}
              </p>
              <p className="field-help">
                Verified covering cards: {((target.covered_card_ids || []) as string[]).length}
              </p>
              <div className="source-chips">
                {((target.sources || []) as Source[]).map((ref, i) => (
                  <button key={i} onClick={() => setSource(ref)}>
                    {ref.document_name || 'Original source'} · p.{ref.page_number}
                  </button>
                ))}
              </div>
            </details>
          ))}
          {!targets.data.items.length && (
            <p className="muted">
              No independently inspected targets yet. Start processing to run the source-level
              coverage audit.
            </p>
          )}
          <Pagination offset={offset} total={targets.data.total} limit={50} onChange={setOffset} />
          <details>
            <summary>Coverage denominators and hierarchy summary</summary>
            <pre>{JSON.stringify(targets.data.summary, null, 2)}</pre>
          </details>
        </>
      )}
      {source && (
        <SourcePreview
          documentId={source.document_id}
          source={source}
          onClose={() => setSource(null)}
        />
      )}
    </section>
  );
}
