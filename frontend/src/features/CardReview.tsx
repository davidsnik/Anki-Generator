import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckCheck, Undo2 } from 'lucide-react';
import { write } from '../services/api';
import type { Card, Concept, Json, Revision } from '../services/types';
import { Badge, Confirm, ErrorPanel, Modal, human, useToast } from '../components/UI';
import { MathText } from '../components/MathText';
export function useReviewKeys(
  actions: Record<string, () => void>,
  enabled = true,
  allowDialog = false,
) {
  useEffect(() => {
    if (!enabled) return;
    function key(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const dialogs = document.querySelectorAll('dialog[open]');
      if (dialogs.length && (!allowDialog || dialogs.length > 1)) return;
      if (
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        (target instanceof Element &&
          target.closest('input,textarea,select,[contenteditable="true"]'))
      )
        return;
      const action = actions[event.key.toLowerCase()];
      if (action) {
        event.preventDefault();
        action();
      }
    }
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [actions, enabled, allowDialog]);
}
export function ShortcutHelp() {
  return (
    <details className="shortcut-help">
      <summary>Keyboard review shortcuts</summary>
      <p>
        <kbd>←</kbd>/<kbd>→</kbd> previous / next · <kbd>Space</kbd>/<kbd>f</kbd> flip ·{' '}
        <kbd>a</kbd> approve · <kbd>r</kbd> reject · <kbd>e</kbd> edit · <kbd>g</kbd> regenerate ·{' '}
        <kbd>x</kbd> select · <kbd>s</kbd> original evidence. Shortcuts pause while typing or while
        a confirmation dialog is open.
      </p>
    </details>
  );
}
export function BulkReview({
  courseId,
  selection,
  onClear,
  concepts,
}: {
  courseId: string;
  selection: Map<string, number>;
  onClear: () => void;
  concepts: Concept[];
}) {
  const [action, setAction] = useState('approve');
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState('');
  const [add, setAdd] = useState('');
  const [remove, setRemove] = useState('');
  const [topic, setTopic] = useState('');
  const [consent, setConsent] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const client = useQueryClient();
  const toast = useToast();
  const mutation = useMutation({
    mutationFn: () =>
      write<Json>(`/courses/${courseId}/cards/bulk`, {
        card_ids: Array.from(selection.keys()),
        expected_revisions: Object.fromEntries(selection),
        action,
        reason,
        confirm: true,
        tags_add: add
          .split(',')
          .map((v) => v.trim())
          .filter(Boolean),
        tags_remove: remove
          .split(',')
          .map((v) => v.trim())
          .filter(Boolean),
        concept_id: topic || null,
        consent,
        overwrite_manual: overwrite,
        instruction: reason,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      setConfirm(false);
      onClear();
      toast('Bulk action applied to the explicitly selected card revisions.');
    },
  });
  if (!selection.size) return null;
  return (
    <>
      <div className="bulk-review-bar">
        <strong>{selection.size} cards explicitly selected</strong>
        {selection.size > 500 && (
          <span className="warning-text">Select up to 500 cards per action.</span>
        )}
        <select
          aria-label="Bulk card action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        >
          {[
            ['approve', 'Approve selected'],
            ['reject', 'Reject selected'],
            ['pending', 'Mark for human attention'],
            ['regenerate', 'Regenerate selected'],
            ['tags', 'Apply / remove tags'],
            ['topic', 'Change topic'],
          ].map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <button
          className="button primary small"
          disabled={selection.size > 500}
          onClick={() => setConfirm(true)}
        >
          Review bulk action
        </button>
        <button className="text-link" onClick={onClear}>
          Clear selection
        </button>
      </div>
      {confirm && (
        <Modal
          title={`${human(action)} ${selection.size} selected revisions?`}
          onClose={() => setConfirm(false)}
        >
          <p className="muted">
            Only the IDs explicitly selected in the browser are affected. If any revision changed
            since selection, the backend rejects the stale operation.
          </p>
          <label>
            Reason / regeneration guidance
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
          </label>
          {action === 'tags' && (
            <div className="form-grid">
              <label>
                Add tags
                <input
                  value={add}
                  onChange={(e) => setAdd(e.target.value)}
                  placeholder="Comma-separated tags"
                />
              </label>
              <label>
                Remove tags
                <input value={remove} onChange={(e) => setRemove(e.target.value)} />
              </label>
            </div>
          )}
          {action === 'topic' && (
            <label>
              Assign topic
              <select value={topic} onChange={(e) => setTopic(e.target.value)}>
                <option value="">No assigned topic</option>
                {concepts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            </label>
          )}
          {action === 'regenerate' && (
            <>
              <label className="consent-label">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                <span>
                  I approve sending selected cards and their original supporting source
                  excerpts/regions and semantic embedding inputs to OpenAI. API usage may incur
                  charges.
                </span>
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={overwrite}
                  onChange={(e) => setOverwrite(e.target.checked)}
                />
                Explicitly allow replacing manually edited selected cards; previous revisions remain
                in history.
              </label>
            </>
          )}
          {action === 'approve' && (
            <p className="field-help">
              Failed or duplicate cards remain blocked. Approval of otherwise unverified cards
              requires an explicit human rationale.
            </p>
          )}
          {mutation.error && <ErrorPanel error={mutation.error} />}
          <details>
            <summary>Exact selection</summary>
            <ul>
              {Array.from(selection).map(([id, revision]) => (
                <li key={id}>
                  {id} · revision {revision}
                </li>
              ))}
            </ul>
          </details>
          <div className="form-actions">
            <button className="button" onClick={() => setConfirm(false)}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                mutation.isPending || (action === 'regenerate' && !consent) || !reason.trim()
              }
              onClick={() => mutation.mutate()}
            >
              <CheckCheck size={15} />
              Confirm selected action
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
function revisionValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(revisionValue);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !['image_url', 'source_url'].includes(key))
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, entry]) => [key, revisionValue(entry)]),
    );
  return value ?? '';
}
export function revisionFields(previous: Partial<Card>, current: Partial<Card>) {
  return [
    'question',
    'answer',
    'explanation',
    'card_type',
    'kind',
    'concept_id',
    'tags',
    'sources',
    'image_refs',
  ].map((field) => ({
    field,
    before: previous[field as keyof Card],
    after: current[field as keyof Card],
    changed:
      JSON.stringify(revisionValue(previous[field as keyof Card])) !==
      JSON.stringify(revisionValue(current[field as keyof Card])),
  }));
}
export function RevisionComparison({ card, revisions }: { card: Card; revisions: Revision[] }) {
  const [index, setIndex] = useState(() =>
    Math.max(
      0,
      revisions.findIndex((r) => (r.revision_number ?? r.revision) !== card.revision_number),
    ),
  );
  const [confirm, setConfirm] = useState(false);
  const client = useQueryClient();
  const toast = useToast();
  const revision = revisions[index];
  const snapshot = revision?.snapshot || revision?.content || revision || {};
  const restore = useMutation({
    mutationFn: () =>
      write(`/cards/${card.id}/restore`, {
        revision_number: revision.revision_number ?? revision.revision,
        expected_revision: card.revision_number,
        confirm: true,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      setConfirm(false);
      toast(
        'Earlier content restored as a new human revision. Stable Anki identity was preserved; verification must be repeated.',
      );
    },
  });
  return (
    <section className="revision-comparison">
      <label>
        Compare earlier revision to current
        <select value={index} onChange={(e) => setIndex(Number(e.target.value))}>
          {revisions.map((r, i) => (
            <option key={r.id || i} value={i}>
              Revision {r.revision_number ?? r.revision ?? i + 1} ·{' '}
              {r.origin || r.actor || 'Recorded origin'} · {r.created_at}
            </option>
          ))}
        </select>
      </label>
      {revisionFields(snapshot, card).map(({ field, before, after, changed }) => (
        <div className={`revision-field ${changed ? 'changed' : ''}`} key={field}>
          <div className="section-head">
            <h3>{human(field)}</h3>
            <Badge tone={changed ? 'amber' : 'neutral'}>{changed ? 'Changed' : 'Unchanged'}</Badge>
          </div>
          <div className="revision-columns">
            <div>
              <small>Earlier revision</small>
              {typeof before === 'string' ? (
                <MathText text={before} />
              ) : (
                <pre>{JSON.stringify(before || [], null, 2)}</pre>
              )}
            </div>
            <div>
              <small>Current revision</small>
              {typeof after === 'string' ? (
                <MathText text={after} />
              ) : (
                <pre>{JSON.stringify(after || [], null, 2)}</pre>
              )}
            </div>
          </div>
        </div>
      ))}
      <button
        className="button"
        disabled={
          !revision ||
          restore.isPending ||
          (revision.revision_number ?? revision.revision) === card.revision_number
        }
        onClick={() => setConfirm(true)}
      >
        <Undo2 size={15} />
        Restore selected revision
      </button>
      {restore.error && <ErrorPanel error={restore.error} />}{' '}
      {confirm && (
        <Confirm
          danger={false}
          title="Restore earlier content as a new revision?"
          onClose={() => setConfirm(false)}
          onConfirm={() => restore.mutate()}
        >
          This explicitly restores the selected snapshot’s question, answer, explanation, note type,
          topic, tags, source references and images. Current content remains in history; prior
          machine checks do not automatically apply.
        </Confirm>
      )}
    </section>
  );
}
export function VerificationFindings({
  verifications,
  issues,
}: {
  verifications: Json[];
  issues: unknown[];
}) {
  return (
    <section className="verification-findings">
      <h3>What was checked</h3>
      {!verifications.length && (
        <p className="field-help">
          No verification evidence is recorded for this revision. A plausible answer is not a
          verified claim.
        </p>
      )}
      {verifications.map((v, i) => (
        <article key={String(v.id || i)}>
          <div className="section-head">
            <strong>{human(String(v.stage || v.kind || 'Check'))}</strong>
            <Badge tone={v.verdict === 'pass' ? 'green' : 'amber'}>
              {human(String(v.verdict || 'unresolved'))}
            </Badge>
          </div>
          <p className="field-help">
            {v.model && v.stage !== 'symbolic' && !String(v.model).startsWith('sympy')
              ? `Model judgment · ${v.model} · not independent human ground truth`
              : 'Deterministic / recorded calculation — inspect its stated domain and assumptions'}
          </p>
          {!!v.details && (
            <p>
              {String(
                (v.details as Json).reasoning ||
                  (v.details as Json).reason ||
                  (v.details as Json).message ||
                  'No narrative rationale was recorded.',
              )}
            </p>
          )}
          {Array.isArray((v.details as Json)?.checked_assumptions) && (
            <p>
              <strong>Assumptions checked: </strong>
              {((v.details as Json).checked_assumptions as string[]).join('; ') ||
                'None explicitly recorded'}
            </p>
          )}
          {Array.isArray((v.details as Json)?.checks) &&
            ((v.details as Json).checks as Json[]).map((check, j) => (
              <div className="finding" key={j}>
                <strong>
                  {human(String(check.operation || check.kind || 'Bounded calculation'))} ·{' '}
                  {human(String(check.verdict || 'unresolved'))}
                </strong>
                <p>
                  {String(
                    check.reason || check.message || 'Inspect the recorded supported domain.',
                  )}
                </p>
                {!!check.assumptions && (
                  <p>
                    Explicit assumptions:{' '}
                    {typeof check.assumptions === 'string'
                      ? check.assumptions
                      : JSON.stringify(check.assumptions)}
                  </p>
                )}
                <details>
                  <summary>Calculation inputs, result and limitations</summary>
                  <pre>{JSON.stringify(check, null, 2)}</pre>
                </details>
              </div>
            ))}
          {v.stage === 'symbolic' && (
            <p className="field-help">
              This bounded calculation does not establish a general theorem or formal proof.
            </p>
          )}
          {Array.isArray(v.issues) && v.issues.map((issue, j) => <Finding key={j} issue={issue} />)}
          {Array.isArray(v.evidence) && !!v.evidence.length && (
            <details>
              <summary>Original evidence consulted</summary>
              {v.evidence.map((ref, j) => (
                <p key={j}>{typeof ref === 'string' ? ref : JSON.stringify(ref)}</p>
              ))}
            </details>
          )}
        </article>
      ))}
      {issues.map((issue, i) => (
        <Finding key={i} issue={issue} />
      ))}
    </section>
  );
}
function Finding({ issue }: { issue: unknown }) {
  if (typeof issue === 'string') return <p className="finding">{issue}</p>;
  const value = (issue || {}) as Json;
  return (
    <div className={`finding ${value.severity === 'error' ? 'critical' : ''}`}>
      <strong>{human(String(value.category || value.kind || 'Review finding'))}</strong>
      <p>{String(value.message || value.reason || value.description || 'Unresolved finding')}</p>
      {!!value.instruction && <p>Next step: {String(value.instruction)}</p>}
      {!!value.assumptions && <p>Assumptions: {JSON.stringify(value.assumptions)}</p>}
    </div>
  );
}
