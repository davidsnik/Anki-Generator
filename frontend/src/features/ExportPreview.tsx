import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { GitCompareArrows, ShieldCheck } from 'lucide-react';
import { api, write } from '../services/api';
import type { Json } from '../services/types';
import { Confirm, ErrorPanel, Loading, SectionHead, human, useToast } from '../components/UI';
import { Pagination } from './Pagination';
interface Preview extends Json {
  counts: Record<string, number>;
  export_blocked: boolean;
  limitations: string[];
  pagination: { offset: number; limit: number; has_more: boolean };
}
export function ExportPreview({
  courseId,
  selection,
  onBlocked,
}: {
  courseId: string;
  selection: string[] | null;
  onBlocked: (blocked: boolean) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [proposal, setProposal] = useState<Json | null>(null);
  const [proposalOffset, setProposalOffset] = useState(0);
  const proposals = useQuery({
    queryKey: ['identity-proposals', courseId, proposalOffset],
    queryFn: () =>
      api<{ items: Json[]; total: number }>(
        `/courses/${courseId}/identity-proposals?status=pending&offset=${proposalOffset}&limit=25`,
      ),
  });
  const client = useQueryClient();
  const toast = useToast();
  const preview = useQuery({
    queryKey: ['export-preview', courseId, selection, offset],
    queryFn: async () => {
      const result = await write<Preview>(
        `/courses/${courseId}/export-preview?offset=${offset}&limit=25`,
        { format: 'apkg', ...(selection ? { card_ids: selection } : {}) },
      );
      onBlocked(result.export_blocked);
      return result;
    },
  });
  useEffect(() => {
    onBlocked(preview.isPending || preview.isError || !!preview.data?.export_blocked);
  }, [preview.isPending, preview.isError, preview.data, onBlocked]);
  return (
    <section className="panel export-identity-preview">
      <SectionHead title="Identity and update preview" action={<GitCompareArrows size={20} />}>
        Compare the selected notes with the last exported snapshot before building an Anki package.
      </SectionHead>
      {preview.isPending ? (
        <Loading />
      ) : preview.error ? (
        <ErrorPanel error={preview.error} />
      ) : (
        <>
          <div className="identity-counts">
            {Object.entries(preview.data.counts || {}).map(([key, count]) => (
              <div key={key}>
                <strong>{count}</strong>
                <span>{human(key)}</span>
              </div>
            ))}
          </div>
          {preview.data.export_blocked && (
            <div className="warning-note">
              <ShieldCheck size={18} />
              <span>
                Resolve uncertain identity matches or duplicate note identities before export.
                Previously reviewed content is preserved.
              </span>
            </div>
          )}
          {['new', 'matching', 'modified', 'uncertain', 'missing', 'duplicates'].map((category) => (
            <details key={category}>
              <summary>
                {human(category)} ({preview.data.counts?.[category] ?? 0})
              </summary>
              <div className="identity-items">
                {((preview.data[category] || []) as Json[]).map((item, index) => (
                  <article key={String(item.id || item.proposal_id || index)}>
                    <p>
                      {String(
                        item.question ||
                          item.title ||
                          item.reason ||
                          item.note_guid ||
                          'Identity mapping',
                      )}
                    </p>
                    <small>
                      {String(item.id || item.candidate_id || '')}{' '}
                      {item.note_guid ? `· Anki note ${item.note_guid}` : ''}
                    </small>
                    {category === 'missing' && (
                      <p className="field-help">
                        Absence from this generation does not delete an existing Anki note.
                      </p>
                    )}
                  </article>
                ))}
              </div>
            </details>
          ))}
          {preview.data.pagination?.has_more || preview.data.has_more || offset > 0 ? (
            <Pagination
              offset={offset}
              total={Math.max(0, ...Object.values(preview.data.counts || {}))}
              limit={25}
              onChange={setOffset}
            />
          ) : null}
          <div className="inline-note">
            <ShieldCheck size={17} />
            <span>
              {preview.data.limitations?.join(' ') ||
                'The application reuses stable note identities. Actual field updates, scheduling and manual Anki edits depend on Anki import settings and version; this preview does not modify a collection.'}
            </span>
          </div>
        </>
      )}
      <details className="pending-identities">
        <summary>All pending identity decisions ({proposals.data?.total ?? 0})</summary>
        <p className="field-help">
          These include concepts and cards outside the selected export. Inspect candidate content
          and original evidence before deciding.
        </p>
        {proposals.error && <ErrorPanel error={proposals.error} />}{' '}
        {(proposals.data?.items || []).map((item) => (
          <article className="reference-editor" key={String(item.id)}>
            <h3>
              {String(
                (item.candidate_payload as Json)?.question ||
                  (item.candidate_payload as Json)?.title ||
                  item.candidate_id,
              )}
            </h3>
            <p>
              {human(String(item.entity_type))} · {String(item.reason)}
            </p>
            <button className="button small" onClick={() => setProposal(item)}>
              Resolve identity proposal
            </button>
          </article>
        ))}
        <Pagination
          offset={proposalOffset}
          total={proposals.data?.total ?? 0}
          limit={25}
          onChange={setProposalOffset}
        />
      </details>
      {proposal && (
        <IdentityResolution
          proposal={proposal}
          onClose={() => setProposal(null)}
          onResolved={() => {
            client.invalidateQueries();
            setProposal(null);
            toast('Identity decision recorded; stable reviewed content remains protected.');
          }}
        />
      )}
    </section>
  );
}
function IdentityResolution({
  proposal,
  onClose,
  onResolved,
}: {
  proposal: Json;
  onClose: () => void;
  onResolved: () => void;
}) {
  const [decision, setDecision] = useState('new');
  const [existing, setExisting] = useState('');
  const [reason, setReason] = useState('');
  const [replace, setReplace] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const resolve = useMutation({
    mutationFn: () =>
      write(`/identity-proposals/${proposal.proposal_id || proposal.id}/resolve`, {
        decision,
        existing_id: existing || undefined,
        rationale: reason,
        replace_reviewed: replace,
      }),
    onSuccess: onResolved,
  });
  return (
    <div className="identity-resolution">
      <SectionHead title="Resolve an uncertain identity" />
      <p className="muted">
        {String(
          proposal.reason ||
            'Inspect source provenance and existing reviewed targets before confirming a match.',
        )}
      </p>
      <details>
        <summary>Candidate content and original provenance</summary>
        <pre>
          {JSON.stringify(
            {
              candidate: proposal.candidate_payload,
              sources: proposal.sources,
              candidates: proposal.candidates,
            },
            null,
            2,
          )}
        </pre>
      </details>
      <label>
        Decision
        <select value={decision} onChange={(e) => setDecision(e.target.value)}>
          {[
            ['new', 'Keep as a new independent target'],
            ['match', 'Match an existing persistent target'],
            ['split', 'Record a deliberate split'],
            ['merge', 'Record a deliberate merge'],
          ].map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {decision !== 'new' && (
        <label>
          Existing persistent target
          <select value={existing} onChange={(e) => setExisting(e.target.value)}>
            <option value="">Choose an actual candidate</option>
            {((proposal.candidates || []) as Json[]).map((item) => (
              <option key={String(item.id)} value={String(item.id)}>
                {String(item.title || item.question || item.id)} · similarity{' '}
                {String(item.score ?? 'unscored')}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Evidence for this reconciliation
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <label className="consent-label">
        <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
        <span>
          Explicitly allow replacement of existing human-reviewed content, while retaining revision
          history. Leave unchecked to preserve existing human work.
        </span>
      </label>
      <div className="inline-actions">
        <button className="button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="button primary"
          disabled={!reason.trim() || (decision !== 'new' && !existing)}
          onClick={() => setConfirm(true)}
        >
          Review identity decision
        </button>
      </div>
      {resolve.error && <ErrorPanel error={resolve.error} />}{' '}
      {confirm && (
        <Confirm
          danger={false}
          title="Confirm persistent identity decision?"
          onClose={() => setConfirm(false)}
          onConfirm={() => resolve.mutate()}
        >
          This decision affects stable mapping during future generation and export.{' '}
          {replace
            ? 'You explicitly authorized replacing reviewed content.'
            : 'Existing reviewed content remains protected.'}
        </Confirm>
      )}
    </div>
  );
}
