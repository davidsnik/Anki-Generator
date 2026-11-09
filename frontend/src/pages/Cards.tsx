import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ArrowRight,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  Columns2,
  Expand,
  FileText,
  Grid2X2,
  History,
  Layers,
  List,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Sparkles,
  X,
} from 'lucide-react';
import type { Card, Concept, Course, Json, Page, Revision, Source } from '../services/types';
import { api, list, write } from '../services/api';
import {
  Badge,
  Confirm,
  Empty,
  ErrorPanel,
  human,
  Loading,
  Modal,
  SearchInput,
  SectionHead,
  statusTone,
  useToast,
} from '../components/UI';
import { MathText } from '../components/MathText';
import { SourcePreview } from './Documents';
import { RunDialog } from './Processing';
import { Pagination } from '../features/Pagination';
import type { PageResult } from '../features/Pagination';
import { readCardFilters, rememberCardFilters } from '../services/cardFilters';
import {
  BulkReview,
  RevisionComparison,
  ShortcutHelp,
  useReviewKeys,
  VerificationFindings,
} from '../features/CardReview';
export function getSources(card: Card) {
  return card.sources || card.evidence || card.source_references || [];
}
function cleanSource(source: Source) {
  return Object.fromEntries(
    Object.entries(source).filter(([key]) =>
      [
        'document_id',
        'document_name',
        'page_number',
        'region_id',
        'bbox',
        'quote',
        'section',
      ].includes(key),
    ),
  );
}
function cardImages(card: Card) {
  return (card.image_refs || card.media || [])
    .map((item) => {
      if (typeof item === 'string') return item.startsWith('/api/') ? item : '';
      const image = item as Json;
      return String(
        image.image_url ||
          image.url ||
          (image.document_id && image.region_id
            ? `/api/documents/${image.document_id}/regions/${image.region_id}`
            : ''),
      );
    })
    .filter((url) => url.startsWith('/api/'));
}
export function Flashcard({
  card,
  flipped,
  onFlip,
  compact = false,
}: {
  card: Card;
  flipped: boolean;
  onFlip: () => void;
  compact?: boolean;
}) {
  return (
    <button
      className={`flashcard ${flipped ? 'flipped' : ''} ${compact ? 'compact' : ''}`}
      onClick={onFlip}
      aria-label={flipped ? 'Show question' : 'Reveal answer'}
    >
      <div className="flashcard-top">
        <span>{flipped ? 'THE ANSWER' : 'THINK IT THROUGH'}</span>
        <Badge>{human(card.card_type)}</Badge>
      </div>
      <div className="flashcard-content">
        <MathText
          text={
            flipped ? (card.card_type === 'cloze' ? card.question : card.answer) : card.question
          }
          cloze={card.card_type === 'cloze'}
          reveal={flipped}
        />
        {cardImages(card).map((src, i) => (
          <img src={src} key={i} alt="Source diagram supporting this card" loading="lazy" />
        ))}
      </div>
      <div className="flashcard-bottom">
        <span>
          <RotateCcw size={14} />
          {flipped ? 'Click to see the question' : 'Click to reveal the answer'}
        </span>
        <span className="mini-logo">
          a<span>✦</span>
        </span>
      </div>
    </button>
  );
}
export function CardsPage({ course }: { course: Course }) {
  const [savedFilters] = useState(() => readCardFilters(course.id));
  const [search, setSearch] = useState(savedFilters.search);
  const [status, setStatus] = useState(savedFilters.status);
  const [verification, setVerification] = useState(savedFilters.verification);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState(savedFilters.search);
  const [selection, setSelection] = useState<Map<string, number>>(new Map());
  const [navigation, setNavigation] = useState<{ edge: 'first' | 'last'; offset: number } | null>(
    null,
  );
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 200);
    return () => clearTimeout(timer);
  }, [search]);
  const [type, setType] = useState(savedFilters.type);
  const [topic, setTopic] = useState(savedFilters.topic);
  const [sourceFilter, setSourceFilter] = useState(savedFilters.sourceFilter);
  const [sort, setSort] = useState(savedFilters.sort);
  useEffect(() => setOffset(0), [query, status, verification, type, topic, sourceFilter, sort]);
  const [view, setView] = useState(savedFilters.view);
  useEffect(
    () =>
      rememberCardFilters(course.id, {
        search,
        status,
        verification,
        type,
        topic,
        sourceFilter,
        sort,
        view,
      }),
    [course.id, search, status, verification, type, topic, sourceFilter, sort, view],
  );
  const hasFilters =
    !!search || [status, verification, type, topic, sourceFilter].some((value) => value !== 'all');
  function clearFilters() {
    setSearch('');
    setQuery('');
    setStatus('all');
    setVerification('all');
    setType('all');
    setTopic('all');
    setSourceFilter('all');
  }
  const [selected, setSelected] = useState<Card | null>(null);
  const [editing, setEditing] = useState<Card | 'new' | null>(null);
  const [flipped, setFlipped] = useState<Set<string>>(new Set());
  const parameters = new URLSearchParams({
    offset: String(offset),
    limit: '24',
    q: query,
    sort,
    ...(status === 'all' ? {} : { review_status: status }),
    ...(verification === 'all' ? {} : { verification_status: verification }),
    ...(type === 'all' ? {} : { card_type: type }),
    ...(topic === 'all' ? {} : { concept_id: topic }),
    ...(sourceFilter === 'all' ? {} : { document_id: sourceFilter }),
  });
  const cards = useQuery({
    queryKey: ['cards-page', course.id, parameters.toString()],
    queryFn: () => api<PageResult<Card>>(`/courses/${course.id}/cards-page?${parameters}`),
    refetchInterval: 5000,
  });
  const concepts = useQuery({
    queryKey: ['concepts', course.id],
    queryFn: async () => list<Concept>(await api(`/courses/${course.id}/concepts`)),
  });
  const filtered = cards.data?.items || [];
  useEffect(() => {
    if (navigation && cards.data?.offset === navigation.offset && cards.data.items.length) {
      setSelected(
        navigation.edge === 'first'
          ? cards.data.items[0]
          : cards.data.items[cards.data.items.length - 1],
      );
      setNavigation(null);
    }
  }, [navigation, cards.data]);
  const types = ['basic', 'cloze'];
  const sources = ((cards.data?.facets?.sources || []) as { id: string; name: string }[]).map(
    (v) => [v.id, v.name],
  );
  function selectCard(card: Card) {
    setSelection((previous) => {
      const next = new Map(previous);
      if (next.has(card.id)) next.delete(card.id);
      else next.set(card.id, card.revision_number ?? 1);
      return next;
    });
  }
  function selectVisible() {
    setSelection((previous) => {
      const next = new Map(previous);
      const all = filtered.every((c) => next.has(c.id));
      for (const card of filtered) {
        if (all) next.delete(card.id);
        else next.set(card.id, card.revision_number ?? 1);
      }
      return next;
    });
  }
  useReviewKeys(
    {
      arrowright: () => {
        if (filtered[0]) setSelected(filtered[0]);
      },
      arrowleft: () => {
        if (filtered.length) setSelected(filtered[filtered.length - 1]);
      },
    },
    !selected && !editing && view !== 'study',
  );
  const toggle = (id: string) =>
    setFlipped((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <>
      <SectionHead
        title="Small cards. Deeper understanding."
        action={
          <button className="button primary" onClick={() => setEditing('new')}>
            <Plus size={16} />
            Add a card
          </button>
        }
      >
        Inspect the question. Check the evidence. Make it yours.
      </SectionHead>
      <div className="card-toolbar">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search questions, answers, or tags…"
        />
        <div className="view-switch" aria-label="Card view">
          <button
            className={view === 'grid' ? 'active' : ''}
            aria-label="Grid view"
            aria-pressed={view === 'grid'}
            onClick={() => setView('grid')}
          >
            <Grid2X2 size={17} />
          </button>
          <button
            className={view === 'list' ? 'active' : ''}
            aria-label="List view"
            aria-pressed={view === 'list'}
            onClick={() => setView('list')}
          >
            <List size={17} />
          </button>
          <button
            className={view === 'study' ? 'active' : ''}
            aria-label="Immersive study view"
            aria-pressed={view === 'study'}
            onClick={() => setView('study')}
          >
            <Expand size={17} />
          </button>
        </div>
      </div>
      <div className="review-shortcuts" aria-label="Quick review filters">
        <button className="button small" aria-pressed={!hasFilters} onClick={clearFilters}>
          All cards
        </button>
        <button
          className="button small"
          aria-pressed={status === 'pending' && verification === 'all'}
          onClick={() => {
            clearFilters();
            setStatus('pending');
          }}
        >
          Awaiting review
        </button>
        <button
          className="button small"
          aria-pressed={verification === 'needs_attention'}
          onClick={() => {
            clearFilters();
            setVerification('needs_attention');
          }}
        >
          Needs attention
        </button>
        <button
          className="button small"
          aria-pressed={status === 'approved' && verification === 'all'}
          onClick={() => {
            clearFilters();
            setStatus('approved');
          }}
        >
          Approved cards
        </button>
      </div>
      <div className="filter-row">
        <select
          aria-label="Review status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All review statuses</option>
          <option value="pending">Awaiting review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        <select aria-label="Card type" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="all">All card types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {human(t)}
            </option>
          ))}
        </select>
        <select aria-label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
          <option value="all">All topics</option>
          {concepts.data?.map((c) => (
            <option value={c.id} key={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <select
          aria-label="Source document"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
        >
          <option value="all">All sources</option>
          {sources.map(([id, name]) => (
            <option value={id} key={id}>
              {name}
            </option>
          ))}
        </select>
        <select aria-label="Sort cards" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="newest">Newest first</option>
          <option value="question">Question A–Z</option>
          <option value="status">Review status</option>
        </select>
        <select
          aria-label="Verification outcome"
          value={verification}
          onChange={(e) => setVerification(e.target.value)}
        >
          <option value="all">All verification outcomes</option>
          {[
            'needs_attention',
            'verified',
            'unverified',
            'needs_review',
            'failed',
            'rejected',
            'duplicate',
          ].map((v) => (
            <option key={v} value={v}>
              {human(v)}
            </option>
          ))}
        </select>
        <span>{cards.data?.total ?? 0} cards</span>
        {hasFilters && (
          <button className="text-link" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>
      <div className="inline-actions selection-controls">
        <button className="button small" disabled={!filtered.length} onClick={selectVisible}>
          {filtered.length && filtered.every((c) => selection.has(c.id))
            ? 'Deselect displayed page'
            : 'Select displayed page'}
        </button>
        <span className="field-help">
          Selection spans only cards you explicitly check, including earlier pages.
        </span>
      </div>
      <ShortcutHelp />
      <BulkReview
        courseId={course.id}
        selection={selection}
        onClear={() => setSelection(new Map())}
        concepts={concepts.data || []}
      />
      {cards.isPending ? (
        <Loading />
      ) : cards.error ? (
        <ErrorPanel error={cards.error} />
      ) : !filtered.length ? (
        <section className="panel">
          <Empty
            icon={Layers}
            title={
              hasFilters
                ? 'No cards match these filters'
                : 'Good questions are the start of understanding'
            }
            action={
              hasFilters ? (
                <button className="button" onClick={clearFilters}>
                  Clear filters
                </button>
              ) : (
                <button className="button" onClick={() => setEditing('new')}>
                  <Plus size={16} /> Write your own card
                </button>
              )
            }
          >
            {hasFilters
              ? 'Try a different search or clear the filters to see all cards in this course.'
              : 'Generate a source-supported deck from your documents, or add a card by hand.'}
          </Empty>
        </section>
      ) : view === 'study' ? (
        <StudyView cards={filtered} onEdit={setEditing} />
      ) : view === 'list' ? (
        <div className="card-list">
          {filtered.map((card) => (
            <div className="card-list-row" key={card.id}>
              <input
                aria-label={`Select card ${card.id}`}
                type="checkbox"
                checked={selection.has(card.id)}
                onChange={() => selectCard(card)}
              />
              <button onClick={() => setSelected(card)}>
                <span className="list-card-icon">
                  <Layers size={18} />
                </span>
                <div>
                  <MathText text={card.question} cloze={card.card_type === 'cloze'} />
                  <small>{card.tags?.join(' · ') || human(card.card_type)}</small>
                </div>
                <Badge tone={statusTone(card.review_status)}>{human(card.review_status)}</Badge>
                <Badge tone={statusTone(card.verification_status)}>
                  {human(card.verification_status)}
                </Badge>
                <ChevronRight size={17} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="cards-grid">
          {filtered.map((card) => (
            <article className="card-tile" key={card.id}>
              <label className="card-select">
                <input
                  aria-label={`Select card ${card.id}`}
                  type="checkbox"
                  checked={selection.has(card.id)}
                  onChange={() => selectCard(card)}
                />
                Select revision {card.revision_number ?? 1}
              </label>
              <Flashcard
                card={card}
                compact
                flipped={flipped.has(card.id)}
                onFlip={() => toggle(card.id)}
              />
              <div className="card-tile-details">
                <div className="tag-row">
                  {card.tags?.slice(0, 3).map((tag) => (
                    <span className="tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="card-tile-footer">
                  <Badge tone={statusTone(card.review_status)}>{human(card.review_status)}</Badge>
                  <button className="text-link" onClick={() => setSelected(card)}>
                    Inspect & review <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
      <Pagination
        offset={offset}
        total={cards.data?.total ?? 0}
        limit={24}
        loading={cards.isFetching}
        onChange={setOffset}
      />
      {selected && (
        <CardInspector
          course={course}
          key={selected.id}
          cardId={selected.id}
          position={
            filtered.some((card) => card.id === selected.id)
              ? offset + filtered.findIndex((card) => card.id === selected.id) + 1
              : 0
          }
          total={cards.data?.total || 0}
          isSelected={selection.has(selected.id)}
          onPrevious={() => {
            const i = filtered.findIndex((c) => c.id === selected.id);
            if (i > 0) setSelected(filtered[i - 1]);
            else if (offset) {
              setNavigation({ edge: 'last', offset: Math.max(0, offset - 24) });
              setOffset(Math.max(0, offset - 24));
              setSelected(null);
            }
          }}
          onNext={() => {
            const i = filtered.findIndex((c) => c.id === selected.id);
            if (i + 1 < filtered.length) setSelected(filtered[i + 1]);
            else if (offset + 24 < (cards.data?.total || 0)) {
              setNavigation({ edge: 'first', offset: offset + 24 });
              setOffset(offset + 24);
              setSelected(null);
            }
          }}
          onToggleSelection={() => selectCard(selected)}
          initial={selected}
          onClose={() => setSelected(null)}
          onEdit={(card) => {
            setSelected(null);
            setEditing(card);
          }}
        />
      )}
      {editing && (
        <CardEditor
          course={course}
          card={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
function StudyView({ cards, onEdit }: { cards: Card[]; onEdit: (card: Card) => void }) {
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const safeIndex = Math.min(index, cards.length - 1);
  const card = cards[safeIndex];
  useReviewKeys({
    f: () => setFlipped((v) => !v),
    ' ': () => setFlipped((v) => !v),
    arrowleft: () => {
      setIndex(Math.max(0, safeIndex - 1));
      setFlipped(false);
    },
    arrowright: () => {
      setIndex(Math.min(cards.length - 1, safeIndex + 1));
      setFlipped(false);
    },
    e: () => onEdit(card),
  });
  return (
    <section className="study-mode">
      <div className="study-top">
        <span>TAKE A MOMENT. THINK IT THROUGH.</span>
        <span>
          {safeIndex + 1} of {cards.length}
        </span>
      </div>
      <Flashcard card={card} flipped={flipped} onFlip={() => setFlipped(!flipped)} />
      {flipped && card.explanation && (
        <div className="study-explanation">
          <h3>The thinking behind it</h3>
          <MathText text={card.explanation} />
        </div>
      )}
      <div className="study-controls">
        <button
          className="button"
          disabled={safeIndex === 0}
          onClick={() => {
            setIndex(safeIndex - 1);
            setFlipped(false);
          }}
        >
          <ArrowLeft size={16} />
          Previous
        </button>
        <button className="button" onClick={() => onEdit(card)}>
          <Pencil size={15} />
          Edit card
        </button>
        <button
          className="button primary"
          disabled={safeIndex === cards.length - 1}
          onClick={() => {
            setIndex(safeIndex + 1);
            setFlipped(false);
          }}
        >
          Next card
          <ArrowRight size={16} />
        </button>
      </div>
    </section>
  );
}
function CardInspector({
  course,
  cardId,
  initial,
  onClose,
  onEdit,
  onPrevious,
  onNext,
  onToggleSelection,
  position,
  total,
  isSelected,
}: {
  position: number;
  total: number;
  isSelected: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onToggleSelection: () => void;
  course: Course;
  cardId: string;
  initial: Card;
  onClose: () => void;
  onEdit: (card: Card) => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [flipped, setFlipped] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [reason, setReason] = useState('');
  const [instruction, setInstruction] = useState(
    'Make this question more precise and include the relevant assumptions.',
  );
  const [regenerate, setRegenerate] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const detail = useQuery({
    queryKey: ['card', cardId],
    queryFn: () => api<Card>(`/cards/${cardId}`),
    initialData: initial,
  });
  const revisions = useQuery({
    queryKey: ['revisions', cardId],
    queryFn: async () => list<Revision>(await api(`/cards/${cardId}/revisions`)),
    enabled: showHistory,
  });
  const review = useMutation({
    mutationFn: (decision: string) => write(`/cards/${cardId}/review`, { decision, reason }),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Your review decision has been saved.');
    },
  });
  const card = detail.data;
  const sources = getSources(card);
  useReviewKeys(
    {
      ' ': () => setFlipped((v) => !v),
      f: () => setFlipped((v) => !v),
      arrowleft: onPrevious,
      arrowright: onNext,
      x: onToggleSelection,
      e: () => onEdit(card),
      g: () => setRegenerate(true),
      s: () => {
        if (sources[0]) setSource(sources[0]);
      },
      a: () => {
        if (card.verification_status === 'verified' || reason.trim()) review.mutate('approved');
      },
      r: () => review.mutate('rejected'),
    },
    !regenerate,
    true,
  );
  return (
    <Modal title="A closer look" onClose={onClose} wide>
      <div className={`inspector-layout ${source ? 'has-source' : ''}`}>
        <div className="inspector-card">
          <div className="inline-actions">
            <span className="review-position" aria-live="polite">
              {position ? `Card ${position} of ${total}` : 'No longer matches these filters'}
            </span>
            <button className="button small" disabled={position <= 1} onClick={onPrevious}>
              ← Previous card
            </button>
            <button className="button small" disabled={position >= total} onClick={onNext}>
              Next card →
            </button>
            <button className="button small" aria-pressed={isSelected} onClick={onToggleSelection}>
              {isSelected ? 'Remove from selection' : 'Select card'}
            </button>
          </div>
          <ShortcutHelp />
          <div className="inspector-badges">
            <Badge tone={statusTone(card.review_status)}>{human(card.review_status)}</Badge>
            <Badge tone={statusTone(card.verification_status)}>
              {human(card.verification_status)}
            </Badge>
            {card.manually_edited && <Badge>Human edited</Badge>}
          </div>
          <Flashcard card={card} flipped={flipped} onFlip={() => setFlipped(!flipped)} />
          <div className="inspector-section">
            <h3>The explanation</h3>
            <MathText text={card.explanation || 'No additional explanation provided.'} />
          </div>
          {card.generation_rationale && (
            <div className="inspector-section">
              <h3>Why this card exists</h3>
              <MathText text={card.generation_rationale} />
            </div>
          )}
          <div className="inspector-section">
            <h3>Evidence & original material</h3>
            {sources.length ? (
              <div className="source-chips">
                {sources.map((s, i) => (
                  <button key={i} onClick={() => setSource(s)}>
                    <FileText size={14} />
                    {s.document_name || s.filename || 'Source document'}
                    {s.page_number ? ` · p. ${s.page_number}` : ''}
                    <ChevronRight size={13} />
                  </button>
                ))}
              </div>
            ) : (
              <p className="warning-text">
                No supporting source is attached. This card needs evidence before it can be
                considered source verified.
              </p>
            )}
          </div>
          <VerificationFindings
            verifications={((card as Card & { verifications?: Json[] }).verifications || []).filter(
              (v) => v.revision_number === undefined || v.revision_number === card.revision_number,
            )}
            issues={card.issues || []}
          />
          <div className="tag-row">
            {card.tags?.map((tag) => (
              <span className="tag" key={tag}>
                {tag}
              </span>
            ))}
          </div>
          <div className="review-box">
            <h3>Your judgment matters</h3>
            <label>
              Review rationale <span className="optional">required for unverified approval</span>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Required rationale to approve a card without automatic verification"
              />
            </label>
            <div className="inline-actions wrap">
              <button
                className="button approve"
                disabled={
                  review.isPending ||
                  (card.verification_status !== 'verified' && !reason.trim()) ||
                  ['failed', 'rejected', 'duplicate'].includes(card.verification_status)
                }
                onClick={() => review.mutate('approved')}
              >
                <CheckCheck size={16} />
                Approve
              </button>
              <button
                className="button"
                disabled={review.isPending}
                onClick={() => review.mutate('pending')}
              >
                <RotateCcw size={15} />
                Needs review
              </button>
              <button
                className="button text-danger"
                disabled={review.isPending}
                onClick={() => review.mutate('rejected')}
              >
                <X size={16} />
                Reject
              </button>
              <button className="button" onClick={() => onEdit(card)}>
                <Pencil size={15} />
                Edit card
              </button>
            </div>
            {review.error && <ErrorPanel error={review.error} />}
          </div>
          <div className="inspector-section">
            <h3>Make it better</h3>
            <div className="improvement-presets">
              {[
                'Make the answer shorter.',
                'Include the relevant assumptions.',
                'This card is mathematically incorrect.',
                'This card is redundant.',
              ].map((text) => (
                <button key={text} onClick={() => setInstruction(text)}>
                  {text}
                </button>
              ))}
            </div>
            <label>
              Specific improvement
              <textarea
                rows={2}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
              />
            </label>
            <button className="button" onClick={() => setRegenerate(true)}>
              <RefreshCw size={15} />
              Regenerate with feedback
            </button>
          </div>
          <button className="text-link history-toggle" onClick={() => setShowHistory(!showHistory)}>
            <History size={16} /> {showHistory ? 'Hide' : 'Compare'} previous revisions
            <ChevronDown size={14} />
          </button>
          {showHistory &&
            (revisions.isPending ? (
              <Loading />
            ) : revisions.error ? (
              <ErrorPanel error={revisions.error} />
            ) : (
              <RevisionComparison card={card} revisions={revisions.data || []} />
            ))}
        </div>
        {source && (
          <div className="inspector-source">
            <div className="section-head">
              <h3>{source.document_name || source.filename || 'Original source'}</h3>
              <button
                aria-label="Close source panel"
                className="icon-button"
                onClick={() => setSource(null)}
              >
                <X size={17} />
              </button>
            </div>
            <SourcePreview
              embedded
              documentId={source.document_id}
              source={source}
              onClose={() => setSource(null)}
            />
          </div>
        )}
      </div>
      {regenerate && (
        <RunDialog
          course={course}
          mode="revise"
          extra={{ card_id: card.id, instruction }}
          onClose={() => setRegenerate(false)}
        />
      )}
    </Modal>
  );
}
export function CardEditor({
  course,
  card,
  onClose,
}: {
  course: Course;
  card?: Card;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState(card?.question || '');
  const [answer, setAnswer] = useState(card?.answer || '');
  const [explanation, setExplanation] = useState(card?.explanation || '');
  const [tags, setTags] = useState(card?.tags?.join(', ') || '');
  const [type, setType] = useState(card?.card_type || 'basic');
  const [kind, setKind] = useState(card?.kind || 'conceptual');
  const [concept, setConcept] = useState(card?.concept_id || '');
  const [flipped, setFlipped] = useState(false);
  const [sourceDocument, setSourceDocument] = useState(
    getSources(card || ({} as Card))[0]?.document_id || '',
  );
  const [page, setPage] = useState(getSources(card || ({} as Card))[0]?.page_number || 1);
  const [imageRefs, setImageRefs] = useState<Source[]>(
    (card?.image_refs || []).filter(
      (v): v is Source => !!v && typeof v === 'object' && 'document_id' in v,
    ),
  );
  const [discard, setDiscard] = useState(false);
  const [originalDraft] = useState(() =>
    JSON.stringify([
      question,
      answer,
      explanation,
      tags,
      type,
      kind,
      concept,
      sourceDocument,
      page,
      imageRefs,
    ]),
  );
  const dirty =
    originalDraft !==
    JSON.stringify([
      question,
      answer,
      explanation,
      tags,
      type,
      kind,
      concept,
      sourceDocument,
      page,
      imageRefs,
    ]);
  const valid =
    !!question.trim() &&
    (type === 'cloze' ? /\{\{c\d+::[^}]+\}\}/.test(question) : !!answer.trim());
  useEffect(() => {
    if (!dirty) return;
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [dirty]);
  const pages = useQuery({
    queryKey: ['pages', sourceDocument],
    queryFn: async () => list<Page>(await api(`/documents/${sourceDocument}/pages`)),
    enabled: !!sourceDocument,
  });
  const originalSource = card ? getSources(card)[0] : undefined;
  const client = useQueryClient();
  const toast = useToast();
  const concepts = useQuery({
    queryKey: ['concepts', course.id],
    queryFn: async () => list<Concept>(await api(`/courses/${course.id}/concepts`)),
  });
  const documents = useQuery({
    queryKey: ['documents', course.id],
    queryFn: async () =>
      list<{ id: string; filename: string }>(await api(`/courses/${course.id}/documents`)),
  });
  const save = useMutation({
    mutationFn: () =>
      write(
        card ? `/cards/${card.id}` : `/courses/${course.id}/cards`,
        {
          question,
          answer,
          explanation,
          kind,
          expected_revision: card?.revision_number,
          tags: tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
          card_type: type,
          concept_id: concept || null,
          image_refs: imageRefs.map(cleanSource),
          sources: sourceDocument
            ? [
                originalSource?.document_id === sourceDocument &&
                originalSource.page_number === page
                  ? cleanSource(originalSource)
                  : { document_id: sourceDocument, page_number: page },
                ...(card ? getSources(card).slice(1).map(cleanSource) : []),
              ]
            : [],
        },
        card ? 'PATCH' : 'POST',
      ),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Card saved. Human edits are preserved in revision history.');
      onClose();
    },
  });
  const preview = {
    ...card,
    id: card?.id || 'preview',
    question,
    answer,
    explanation,
    tags: tags.split(','),
    card_type: type,
    image_refs: imageRefs,
    review_status: card?.review_status || 'pending',
    verification_status: card?.verification_status || 'unverified',
  } as Card;
  function requestClose() {
    if (save.isPending) return;
    if (dirty) setDiscard(true);
    else onClose();
  }
  return (
    <Modal
      title={card ? 'Refine this card' : 'Write a thoughtful question'}
      onClose={requestClose}
      wide
    >
      <div className="editor-layout">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid && !save.isPending) save.mutate();
          }}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              event.currentTarget.requestSubmit();
            }
          }}
        >
          <div className="form-grid">
            <label>
              Card type
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {['basic', 'cloze'].map((t) => (
                  <option key={t} value={t}>
                    {human(t)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Learning target
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {[
                  'conceptual',
                  'definition',
                  'theorem',
                  'procedure',
                  'assumption',
                  'misconception',
                ].map((k) => (
                  <option key={k} value={k}>
                    {human(k)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Knowledge topic
              <select value={concept} onChange={(e) => setConcept(e.target.value)}>
                <option value="">No topic assigned</option>
                {concepts.data?.map((c) => (
                  <option value={c.id} key={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            {type === 'cloze' ? 'Cloze text' : 'Question'}
            <textarea
              autoFocus
              required
              rows={4}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                type === 'cloze'
                  ? 'A compact subset of Euclidean space is {{c1::closed and bounded}}.'
                  : 'Ask one clear, self-contained question.'
              }
            />
          </label>
          {type === 'cloze' && (
            <p className="field-help">
              Hide the answer with {'{{c1::answer}}'}. The preview shows what you will recall.
            </p>
          )}
          <label>
            Answer
            <textarea
              required={type !== 'cloze'}
              rows={4}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Be concise. Keep the assumptions that make the statement true."
            />
          </label>
          <label>
            Explanation
            <textarea
              rows={3}
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              placeholder="Optional intuition, example, or derivation."
            />
          </label>
          <label>
            Tags
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="Separate tags with commas"
            />
          </label>
          <div className="form-grid">
            <label>
              Supporting source
              <select
                value={sourceDocument}
                onChange={(e) => {
                  setSourceDocument(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">No source attached</option>
                {documents.data?.map((d) => (
                  <option value={d.id} key={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Page number
              <input
                type="number"
                min="1"
                value={page}
                onChange={(e) => setPage(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="image-reference-picker">
            <label>Original source regions for this card</label>
            {!sourceDocument ? (
              <p className="field-help">
                Select a supporting source above to attach a diagram or visual evidence.
              </p>
            ) : pages.isPending ? (
              <Loading />
            ) : !pages.data?.find((p) => p.page_number === page)?.regions?.length ? (
              <p className="field-help">
                No rendered regions on this page. Run local extraction first.
              </p>
            ) : (
              <div className="source-region-options">
                {pages.data
                  ?.find((p) => p.page_number === page)
                  ?.regions?.map((region) => (
                    <label key={region.id}>
                      <input
                        type="checkbox"
                        checked={imageRefs.some(
                          (ref) =>
                            ref.document_id === sourceDocument && ref.region_id === region.id,
                        )}
                        onChange={(e) =>
                          setImageRefs((refs) =>
                            e.target.checked
                              ? [
                                  ...refs,
                                  {
                                    document_id: sourceDocument,
                                    page_number: page,
                                    region_id: region.id,
                                    bbox: region.bbox,
                                  },
                                ]
                              : refs.filter(
                                  (ref) =>
                                    !(
                                      ref.document_id === sourceDocument &&
                                      ref.region_id === region.id
                                    ),
                                ),
                          )
                        }
                      />
                      <img
                        src={
                          region.image_url ||
                          `/api/documents/${sourceDocument}/regions/${region.id}`
                        }
                        alt={`Attach original ${region.kind || 'source region'} from page ${page}`}
                      />
                      <span>
                        {human(region.kind || 'original evidence')} · p. {page}
                      </span>
                    </label>
                  ))}
              </div>
            )}
          </div>
          <p className="field-help">
            A source link is traceability, not a verification claim. Content changes require fresh
            review.
          </p>
          {save.error && <ErrorPanel error={save.error} />}
          <div className="form-actions">
            <button
              className="button"
              type="button"
              disabled={save.isPending}
              onClick={requestClose}
            >
              Cancel
            </button>
            <button className="button primary" disabled={save.isPending || !valid}>
              <Save size={16} />
              {save.isPending ? 'Saving…' : 'Save card'}
            </button>
          </div>
          <p className="field-help">
            {dirty ? 'Unsaved changes · ' : ''}Ctrl/⌘ + Enter saves this card.
          </p>
        </form>
        <aside className="editor-preview">
          <div className="eyebrow">
            <Sparkles size={15} /> LIVE PREVIEW
          </div>
          <Flashcard card={preview} flipped={flipped} onFlip={() => setFlipped(!flipped)} />
          {explanation && (
            <div className="preview-explanation">
              <h3>Explanation</h3>
              <MathText text={explanation} />
            </div>
          )}
          <p className="field-help">
            Use \( … \) for inline mathematics and \[ … \] for displayed equations. Raw HTML is
            rendered as text.
          </p>
          {sourceDocument && (
            <details>
              <summary>
                <Columns2 size={15} /> Inspect supporting original
              </summary>
              <SourcePreview
                documentId={sourceDocument}
                source={{ document_id: sourceDocument, page_number: page }}
                embedded
                onClose={() => {}}
              />
            </details>
          )}
        </aside>
      </div>
      {discard && (
        <Confirm
          title="Discard your card changes?"
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          onClose={() => setDiscard(false)}
          onConfirm={onClose}
        >
          Your saved card and revision history stay intact. These unsaved edits will be lost.
        </Confirm>
      )}
    </Modal>
  );
}
