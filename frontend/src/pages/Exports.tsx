import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CheckCheck,
  Download,
  FileJson,
  History,
  Layers,
  PackageCheck,
  ShieldCheck,
} from 'lucide-react';
import type { Card, Course, ExportRecord } from '../services/types';
import { api, list, write } from '../services/api';
import {
  Badge,
  Empty,
  ErrorPanel,
  formatDate,
  human,
  Loading,
  SectionHead,
  useToast,
} from '../components/UI';
import { ExportPreview } from '../features/ExportPreview';
import { Pagination } from '../features/Pagination';
import type { PageResult } from '../features/Pagination';
import { MathText } from '../components/MathText';
export function ExportsPage({ course }: { course: Course }) {
  const [format, setFormat] = useState('apkg');
  const [deck, setDeck] = useState(course.deck_name || course.name);
  const [selection, setSelection] = useState<Set<string> | null>(null);
  const [offset, setOffset] = useState(0);
  const [blocked, setBlocked] = useState(true);
  const client = useQueryClient();
  const toast = useToast();
  const cards = useQuery({
    queryKey: ['export-cards-page', course.id, offset],
    queryFn: () =>
      api<PageResult<Card>>(`/courses/${course.id}/cards-page?offset=${offset}&limit=25`),
  });
  const history = useQuery({
    queryKey: ['exports', course.id],
    queryFn: async () => list<ExportRecord>(await api(`/courses/${course.id}/exports`)),
  });
  const eligible = (cards.data?.items || []).filter(
    (c) =>
      c.review_status === 'approved' &&
      !['failed', 'rejected', 'duplicate'].includes(c.verification_status),
  );
  const selected =
    selection ?? new Set((format === 'apkg' ? eligible : cards.data?.items || []).map((c) => c.id));
  const selectedCount =
    selection?.size ??
    (format === 'apkg' ? (course.stats?.approved ?? 0) : (cards.data?.total ?? 0));
  const exportCards = useMutation({
    mutationFn: () =>
      write<ExportRecord>(`/courses/${course.id}/exports`, {
        format,
        deck_name: deck,
        ...(selection ? { card_ids: Array.from(selection) } : {}),
      }),
    onSuccess: (record) => {
      client.invalidateQueries({ queryKey: ['exports', course.id] });
      toast(`${format.toUpperCase()} file prepared. Your save or download will now open.`);
      window.location.assign(record.download_url || `/api/exports/${record.id}/download`);
    },
  });
  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelection(next);
  }
  return (
    <>
      <SectionHead title="Take your understanding with you">
        A real Anki deck. Stable identities. Your original evidence along for the ride.
      </SectionHead>
      {format === 'apkg' && (
        <ExportPreview
          courseId={course.id}
          selection={selection ? Array.from(selection) : null}
          onBlocked={setBlocked}
        />
      )}
      <div className="export-layout">
        <section className="panel export-builder">
          <div className="export-icon">
            <PackageCheck size={30} />
          </div>
          <h2>{format === 'apkg' ? 'Save a deck for Anki' : 'Save card records'}</h2>
          <p className="muted">
            Approved cards without unresolved verification failures enter the Anki deck. Unverified
            cards require an explicit human review rationale. JSON and CSV retain the records you
            select for inspection and backup.
          </p>
          <div className="format-options">
            {[
              { id: 'apkg', name: 'Anki deck', extension: '.apkg', icon: Layers },
              { id: 'json', name: 'Structured data', extension: '.json', icon: FileJson },
              { id: 'csv', name: 'Spreadsheet', extension: '.csv', icon: FileJson },
            ].map((item) => (
              <button
                key={item.id}
                className={format === item.id ? 'selected' : ''}
                onClick={() => {
                  setFormat(item.id);
                  if (item.id === 'apkg') setSelection(null);
                }}
              >
                <item.icon size={23} />
                <strong>{item.name}</strong>
                <span>{item.extension}</span>
              </button>
            ))}
          </div>
          {format === 'apkg' && (
            <label>
              Deck name in Anki
              <input value={deck} onChange={(e) => setDeck(e.target.value)} required />
            </label>
          )}
          <div className="export-stats">
            <div>
              <strong>{selectedCount}</strong>
              <span>
                {selection === null
                  ? format === 'apkg'
                    ? 'approved cards in course'
                    : 'records in course'
                  : 'cards explicitly selected'}
              </span>
            </div>
            <div>
              <strong>
                {
                  new Set(
                    (cards.data?.items || [])
                      .filter((c) => selected.has(c.id))
                      .flatMap((c) => c.concept_ids || [c.concept_id])
                      .filter(Boolean),
                  ).size
                }
              </strong>
              <span>concepts on displayed page</span>
            </div>
            <div>
              <strong>{Math.ceil((selectedCount * 15) / 60)} min</strong>
              <span>estimated initial review</span>
            </div>
          </div>
          <button
            className="button primary export-button"
            disabled={
              exportCards.isPending ||
              !selectedCount ||
              (format === 'apkg' && !deck.trim()) ||
              (format === 'apkg' && blocked)
            }
            onClick={() => exportCards.mutate()}
          >
            <Download size={17} />
            {exportCards.isPending
              ? 'Building package…'
              : format === 'apkg'
                ? 'Save Anki package (.apkg)'
                : `Save ${format.toUpperCase()} file`}
          </button>
          {exportCards.error && <ErrorPanel error={exportCards.error} />}
          {format === 'apkg' && (
            <p className="field-help">
              Save the package, then open it in Anki or choose File → Import. Saving a file here
              does not import it into Anki.
            </p>
          )}
          {format === 'apkg' &&
            selection === null &&
            !selectedCount &&
            !cards.isPending &&
            !cards.isError && (
              <p className="warning-note">
                No cards are approved yet.{' '}
                <Link to={`/courses/${course.id}/cards`}>Review and approve flashcards</Link> before
                creating your deck.
              </p>
            )}
          {selection !== null && !selectedCount && (
            <p className="field-help">
              Select cards on the right, or choose all eligible cards across this course.
            </p>
          )}
          {format === 'apkg' && blocked && !!selectedCount && (
            <p className="field-help">
              Anki export becomes available after the identity and update checks above pass.
            </p>
          )}
          <div className="field-help">
            <ShieldCheck size={15} /> Stable note identifiers are reused across exports. Anki import
            options determine updates; existing collection contents are never changed directly.
          </div>
        </section>
        <section className="panel">
          <SectionHead
            title="Choose your cards"
            action={
              <button
                className="text-link"
                onClick={() =>
                  setSelection(
                    selection === null || selected.size
                      ? new Set()
                      : new Set(
                          (format === 'apkg' ? eligible : cards.data?.items || []).map((c) => c.id),
                        ),
                  )
                }
              >
                {selection === null || selected.size
                  ? 'Clear selection'
                  : `Select ${format === 'apkg' ? 'eligible cards' : 'records'} on this page`}
              </button>
            }
          />
          <label className="check-label">
            <input
              type="checkbox"
              checked={selection === null}
              onChange={(e) => setSelection(e.target.checked ? null : new Set())}
            />
            All {format === 'apkg' ? 'eligible approved cards' : 'records'} across this course
          </label>
          <p className="field-help">
            For a specific selection, turn off the all-course selection and check individual cards.
          </p>
          <p className="field-help">
            {eligible.length} approved cards on this page pass the review filter.{' '}
            <Link to={`/courses/${course.id}/cards`}>Review flashcards</Link> to inspect findings
            and approve more cards. Identity checks can still block a package.
          </p>
          {cards.isPending ? (
            <Loading />
          ) : cards.error ? (
            <ErrorPanel error={cards.error} />
          ) : !cards.data.items.length ? (
            <Empty icon={CheckCheck} title="Your deck starts with a good question">
              Generate or add cards, then inspect and approve them before exporting.
            </Empty>
          ) : (
            <div className="export-card-selection">
              {cards.data.items.map((card) => {
                const allowed = format !== 'apkg' || eligible.some((c) => c.id === card.id);
                return (
                  <label className={!allowed ? 'disabled' : ''} key={card.id}>
                    <input
                      type="checkbox"
                      disabled={!allowed || selection === null}
                      checked={selected.has(card.id)}
                      onChange={() => toggle(card.id)}
                    />
                    <div>
                      <MathText text={card.question} cloze={card.card_type === 'cloze'} />
                      <small>
                        {human(card.review_status)} · {human(card.verification_status)}
                      </small>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
          <Pagination
            offset={offset}
            total={cards.data?.total ?? 0}
            limit={25}
            onChange={setOffset}
          />
          <p className="field-help">
            Review burden is a planning estimate of 15 seconds per card, not measured study
            performance.
          </p>
        </section>
      </div>
      <section className="panel export-history">
        <SectionHead title="Export history" action={<History size={19} />}>
          Every package, with its card count and creation time.
        </SectionHead>
        {history.isPending ? (
          <Loading />
        ) : history.error ? (
          <ErrorPanel error={history.error} />
        ) : !history.data.length ? (
          <p className="muted">Your first export will appear here.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Package</th>
                  <th>Format</th>
                  <th>Cards</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {history.data.map((record) => (
                  <tr key={record.id}>
                    <td>
                      <strong>{record.deck_name || course.deck_name || course.name}</strong>
                    </td>
                    <td>
                      <Badge>{record.format.toUpperCase()}</Badge>
                    </td>
                    <td>{record.card_count}</td>
                    <td>{formatDate(record.created_at)}</td>
                    <td>
                      <a
                        className="button small"
                        href={record.download_url || `/api/exports/${record.id}/download`}
                      >
                        <Download size={14} />
                        Save again
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="inline-note">
        <ShieldCheck size={18} />
        <span>
          Back up your Anki collection before importing updates. Keep the same note type and enable
          updates for existing notes. Review history behavior depends on your Anki version and
          import settings.
        </span>
      </div>
    </>
  );
}
