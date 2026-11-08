import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronRight,
  EyeOff,
  Layers,
  Network,
  Plus,
  SearchCheck,
} from 'lucide-react';
import type { Card, Concept, Course, Source } from '../services/types';
import { api, list, write } from '../services/api';
import {
  Badge,
  Empty,
  ErrorPanel,
  human,
  Loading,
  SearchInput,
  SectionHead,
  statusTone,
  useToast,
} from '../components/UI';
import { MathText } from '../components/MathText';
import { RunDialog } from './Processing';
import { SourcePreview } from './Documents';
export function KnowledgePage({ course }: { course: Course }) {
  const [search, setSearch] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const [topic, setTopic] = useState<Concept | null>(null);
  const concepts = useQuery({
    queryKey: ['concepts', course.id],
    queryFn: async () => list<Concept>(await api(`/courses/${course.id}/concepts`)),
    refetchInterval: 5000,
  });
  const cards = useQuery({
    queryKey: ['cards', course.id],
    queryFn: async () => list<Card>(await api(`/courses/${course.id}/cards`)),
    refetchInterval: 5000,
  });
  const inventory = concepts.data?.map((concept) => ({
    ...concept,
    card_count:
      cards.data?.filter(
        (card) => card.concept_id === concept.id || card.concept_ids?.includes(concept.id),
      ).length ?? 0,
    assumptions:
      concept.assumptions || (concept.metadata_json?.assumptions as string[] | undefined),
  }));
  const filtered =
    inventory?.filter((c) =>
      `${c.title} ${c.description} ${c.kind}`.toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  const roots = search
    ? filtered
    : filtered.filter((c) => !c.parent_id || !filtered.some((p) => p.id === c.parent_id));
  const covered = filtered.filter((c) => !c.excluded && c.coverage_status === 'covered').length;
  const gaps = filtered.filter(
    (c) => !c.excluded && ['uncovered', 'partial'].includes(c.coverage_status || 'uncovered'),
  ).length;
  return (
    <>
      <SectionHead
        title="See how the ideas connect"
        action={<SearchInput value={search} onChange={setSearch} placeholder="Search concepts…" />}
      >
        A course-wide inventory grounded in the sources, not a collection of disconnected chunks.
      </SectionHead>
      <div className="coverage-strip">
        <div>
          <Network size={20} />
          <strong>{filtered.length}</strong>
          <span>knowledge items</span>
        </div>
        <div>
          <Layers size={20} />
          <strong>{covered}</strong>
          <span>covered in last audit</span>
        </div>
        <div>
          <SearchCheck size={20} />
          <strong>{gaps}</strong>
          <span>coverage gaps</span>
        </div>
      </div>
      {concepts.isPending ? (
        <Loading />
      ) : concepts.error ? (
        <ErrorPanel error={concepts.error} />
      ) : !filtered.length ? (
        <section className="panel">
          <Empty
            icon={Network}
            title={search ? 'No matching ideas' : 'Make the bigger picture visible'}
          >
            {search
              ? 'Try a broader search.'
              : 'Run course processing to identify topics, definitions, methods, assumptions, and the recurring techniques in your exercises.'}
          </Empty>
        </section>
      ) : (
        <section className="panel knowledge-tree">
          {roots.map((concept) => (
            <ConceptNode
              key={concept.id}
              concept={concept}
              all={search ? [] : filtered}
              level={0}
              onSource={setSource}
              onGenerate={setTopic}
            />
          ))}
        </section>
      )}
      <div className="inline-note">
        <Network size={18} />
        <span>
          Coverage compares explicit concepts with their mapped cards. An extracted concept is
          evidence of scope, never proof that its claims are correct. Coverage reflects the last
          processing audit; card counts show the current collection.
        </span>
      </div>
      {source && (
        <SourcePreview
          documentId={source.document_id}
          documentName={source.document_name || source.filename}
          source={source}
          onClose={() => setSource(null)}
        />
      )}{' '}
      {topic && (
        <RunDialog
          course={course}
          mode="topic"
          extra={{
            topic_id: topic.id,
            instruction:
              'Generate additional distinct source-supported cards for this topic, emphasizing uncovered learning targets.',
          }}
          onClose={() => setTopic(null)}
        />
      )}
    </>
  );
}
function ConceptNode({
  concept,
  all,
  level,
  onSource,
  onGenerate,
}: {
  concept: Concept;
  all: Concept[];
  level: number;
  onSource: (source: Source) => void;
  onGenerate: (concept: Concept) => void;
}) {
  const [open, setOpen] = useState(level === 0);
  const children = all.filter((c) => c.parent_id === concept.id);
  const client = useQueryClient();
  const toast = useToast();
  const exclude = useMutation({
    mutationFn: () => write(`/concepts/${concept.id}`, { excluded: !concept.excluded }, 'PATCH'),
    onSuccess: () => {
      client.invalidateQueries();
      toast(
        concept.excluded
          ? 'Topic restored to generation scope.'
          : 'Topic excluded from future generation.',
      );
    },
  });
  return (
    <div
      className={`concept-node ${concept.excluded ? 'excluded' : ''}`}
      style={{ '--level': level } as React.CSSProperties}
    >
      <button className="concept-row" onClick={() => setOpen(!open)}>
        <span className="concept-chevron">
          {open ? <ChevronDown size={17} /> : <ChevronRight size={17} />}
        </span>
        <span className={`concept-kind ${concept.kind}`}>
          <Network size={17} />
        </span>
        <span className="concept-title">
          <strong>{concept.title || concept.name}</strong>
          <small>
            {human(concept.kind)} · Importance {Number(concept.importance || 0).toFixed(1)}
          </small>
        </span>
        <Badge tone={concept.excluded ? 'neutral' : statusTone(concept.coverage_status)}>
          {concept.excluded
            ? 'Excluded'
            : human(concept.coverage_status || (concept.card_count ? 'covered' : 'gap'))}
        </Badge>
        <span className="concept-card-count">{concept.card_count ?? 0} cards</span>
      </button>
      {open && (
        <div className="concept-content">
          <MathText text={concept.description} />
          {!!concept.assumptions?.length && (
            <p className="field-help">Assumptions: {concept.assumptions.join('; ')}</p>
          )}
          {concept.metadata_json?.importance_reason ? (
            <p className="field-help">
              Why it matters: {String(concept.metadata_json.importance_reason)}
            </p>
          ) : null}
          {!!(concept.metadata_json?.conflicts as string[] | undefined)?.length && (
            <div className="warning-note">
              <div>
                <strong>Unresolved source conflict</strong>
                {(concept.metadata_json?.conflicts as string[]).map((conflict, i) => (
                  <p key={i}>{conflict}</p>
                ))}
              </div>
            </div>
          )}
          {concept.metadata_json?.uncertain ? (
            <p className="warning-text">
              This concept contains unresolved interpretation or evidence uncertainty.
            </p>
          ) : null}
          {!!concept.relationships?.length && (
            <p className="field-help">
              Related ideas:{' '}
              {concept.relationships
                .map((id) => all.find((c) => c.id === id)?.title || String(id))
                .join(' · ')}
            </p>
          )}
          {!!concept.exercise_analysis?.length && (
            <details className="exercise-analysis">
              <summary>
                Relevant exercises & reusable methods ({concept.exercise_analysis.length})
              </summary>
              {concept.exercise_analysis.map((exercise, i) => (
                <article key={i}>
                  <strong>{String(exercise.label || 'Exercise')}</strong>
                  <p>{String(exercise.reusable_strategy || '')}</p>
                  {Array.isArray(exercise.techniques) && (
                    <p>Techniques: {exercise.techniques.map(String).join('; ')}</p>
                  )}
                  {Array.isArray(exercise.pitfalls) && (
                    <p>Watch for: {exercise.pitfalls.map(String).join('; ')}</p>
                  )}
                </article>
              ))}
            </details>
          )}
          <div className="source-chips">
            {concept.sources?.map((s, i) => (
              <button key={i} onClick={() => onSource(s)}>
                {s.document_name || s.filename || 'Source'}
                {s.page_number ? ` · p. ${s.page_number}` : ''}
                <ChevronRight size={12} />
              </button>
            ))}
          </div>
          <div className="inline-actions">
            <button className="button small" onClick={() => onGenerate(concept)}>
              <Plus size={14} />
              More cards for this topic
            </button>
            <button className="button small" onClick={() => exclude.mutate()}>
              <EyeOff size={14} />
              {concept.excluded ? 'Include topic' : 'Exclude topic'}
            </button>
          </div>
          {exclude.error && <ErrorPanel error={exclude.error} />}{' '}
          {children.map((child) => (
            <ConceptNode
              key={child.id}
              concept={child}
              all={all}
              level={level + 1}
              onSource={onSource}
              onGenerate={onGenerate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
