import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Crop, Hand, History, RefreshCw, Save, ZoomIn, ZoomOut, ShieldCheck } from 'lucide-react';
import { api, list, write } from '../services/api';
import type { Card, Concept, Json, Page, Region } from '../services/types';
import {
  Badge,
  ErrorPanel,
  Loading,
  Modal,
  SectionHead,
  formatDate,
  useToast,
} from '../components/UI';
import { MathText } from '../components/MathText';
interface CorrectedPage extends Page {
  original_text?: string;
  effective_text?: string;
  correction_revision?: number;
  human_verified?: boolean;
  corrections?: Json[];
}
interface Interpretation {
  document_id: string;
  source_sha256: string;
  pages: CorrectedPage[];
  corrections: Json[];
}
export function selectionBounds(
  start: [number, number],
  end: [number, number],
  scale: number,
  width: number,
  height: number,
): number[] | null {
  if (!Number.isFinite(scale) || scale <= 0) return null;
  const x0 = Math.max(0, Math.min(width, Math.min(start[0], end[0]) / scale));
  const y0 = Math.max(0, Math.min(height, Math.min(start[1], end[1]) / scale));
  const x1 = Math.max(0, Math.min(width, Math.max(start[0], end[0]) / scale));
  const y1 = Math.max(0, Math.min(height, Math.max(start[1], end[1]) / scale));
  return x1 - x0 < 1 || y1 - y0 < 1 ? null : [x0, y0, x1, y1];
}
export function SourceWorkbench({
  documentId,
  documentName,
  courseId,
  initialPage = 1,
  onClose,
}: {
  documentId: string;
  documentName?: string;
  courseId?: string;
  initialPage?: number;
  onClose: () => void;
}) {
  const [pageNumber, setPageNumber] = useState(initialPage);
  const [text, setText] = useState('');
  const [baseRevision, setBaseRevision] = useState(0);
  const dirty = useRef(false);
  const [reason, setReason] = useState('');
  const [verified, setVerified] = useState(false);
  const [replace, setReplace] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [mode, setMode] = useState<'crop' | 'pan'>('crop');
  const [selection, setSelection] = useState<number[] | null>(null);
  const [savedRegion, setSavedRegion] = useState<Region | null>(null);
  const [label, setLabel] = useState('Supporting source evidence');
  const [dpi, setDpi] = useState(200);
  const [consent, setConsent] = useState(false);
  const [retryMode, setRetryMode] = useState('extract');
  const [showHistory, setShowHistory] = useState(false);
  const [cardId, setCardId] = useState('');
  const [cardSearch, setCardSearch] = useState('');
  const [conceptId, setConceptId] = useState('');
  const viewport = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const [availableWidth, setAvailableWidth] = useState(550);
  const drag = useRef<{ start: [number, number]; scroll?: [number, number] } | null>(null);
  const client = useQueryClient();
  const toast = useToast();
  const interpretation = useQuery({
    queryKey: ['interpretation', documentId],
    queryFn: () => api<Interpretation>(`/documents/${documentId}/interpretation`),
  });
  const page = interpretation.data?.pages.find((item) => item.page_number === pageNumber);
  useEffect(() => {
    if (page && !dirty.current) {
      setBaseRevision(page.correction_revision ?? 0);
      setText(page.effective_text ?? page.text ?? '');
      setVerified(!!page.human_verified);
      setSelection(null);
      setSavedRegion(null);
      setReplace(false);
    }
  }, [pageNumber, page?.correction_revision]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setAvailableWidth(element.clientWidth - 30));
    observer.observe(element);
    setAvailableWidth(element.clientWidth - 30);
    return () => observer.disconnect();
  }, [interpretation.data]);
  const scale = page ? (Math.min(1, availableWidth / (page.width || 600)) * zoom) / 100 : 1;
  const width = page?.width || 600;
  const height = page?.height || 800;
  const save = useMutation({
    mutationFn: () =>
      write(`/documents/${documentId}/pages/${pageNumber}/corrections`, {
        text,
        verified,
        reason,
        expected_revision: baseRevision,
        replace_verified: replace,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      dirty.current = false;
      toast('Human correction saved. Original extraction and revision history are preserved.');
      setReason('');
    },
  });
  const crop = useMutation({
    mutationFn: () =>
      write<Region>(`/documents/${documentId}/regions`, {
        page_number: pageNumber,
        bbox: selection,
        dpi,
        label,
      }),
    onSuccess: (region) => {
      setSavedRegion(region);
      client.invalidateQueries();
      toast('High-resolution evidence region saved in original page coordinates.');
    },
  });
  const reprocess = useMutation({
    mutationFn: () =>
      write(`/documents/${documentId}/reprocess`, {
        page_numbers: savedRegion ? [] : [pageNumber],
        region_ids: savedRegion ? [savedRegion.id] : [],
        mode: retryMode,
        consent: retryMode === 'interpret' && consent,
        replace_human: replace,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Selected source reprocessing queued; unaffected sources remain reusable.');
    },
  });
  const cardChoices = useQuery({
    queryKey: ['crop-card-choices', courseId, cardSearch],
    queryFn: async () => {
      const result = await api<{ items: Card[] }>(
        `/courses/${courseId}/cards-page?offset=0&limit=100&q=${encodeURIComponent(cardSearch)}`,
      );
      return result.items;
    },
    enabled: !!courseId && !!savedRegion,
  });
  const concepts = useQuery({
    queryKey: ['concepts', courseId],
    queryFn: async () => list<Concept>(await api(`/courses/${courseId}/concepts`)),
    enabled: !!courseId && !!savedRegion,
  });
  const associate = useMutation({
    mutationFn: () =>
      write(`/documents/${documentId}/regions/${savedRegion!.id}/associate`, {
        ...(cardId ? { card_id: cardId } : {}),
        ...(conceptId ? { concept_id: conceptId } : {}),
        expected_revision: cardChoices.data?.find((c) => c.id === cardId)?.revision_number,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Saved crop attached. Changed cards require a fresh review.');
    },
  });
  function point(e: PointerEvent) {
    const rect = canvas.current!.getBoundingClientRect();
    return [
      ((e.clientX - rect.left) * width) / rect.width,
      ((e.clientY - rect.top) * height) / rect.height,
    ] as [number, number];
  }
  function down(e: PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current =
      mode === 'crop'
        ? { start: point(e) }
        : {
            start: [e.clientX, e.clientY],
            scroll: [viewport.current!.scrollLeft, viewport.current!.scrollTop],
          };
    if (mode === 'crop') setSelection(null);
  }
  function move(e: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    if (mode === 'crop')
      setSelection(selectionBounds(drag.current.start, point(e), 1, width, height));
    else {
      viewport.current!.scrollLeft = drag.current.scroll![0] - (e.clientX - drag.current.start[0]);
      viewport.current!.scrollTop = drag.current.scroll![1] - (e.clientY - drag.current.start[1]);
    }
  }
  return (
    <Modal
      title={`Correct and inspect · ${documentName || 'Source document'}`}
      onClose={onClose}
      wide
    >
      {interpretation.isPending ? (
        <Loading />
      ) : interpretation.error ? (
        <ErrorPanel error={interpretation.error} />
      ) : page ? (
        <>
          <div className="source-workbench-tools">
            <label>
              Page
              <select
                value={pageNumber}
                onChange={(e) => {
                  dirty.current = false;
                  setPageNumber(Number(e.target.value));
                }}
              >
                {interpretation.data.pages.map((p) => (
                  <option key={p.page_number} value={p.page_number}>
                    {p.page_number}
                  </option>
                ))}
              </select>
            </label>
            <button
              className={`button small ${mode === 'crop' ? 'primary' : ''}`}
              onClick={() => setMode('crop')}
            >
              <Crop size={14} />
              Select region
            </button>
            <button
              className={`button small ${mode === 'pan' ? 'primary' : ''}`}
              onClick={() => setMode('pan')}
            >
              <Hand size={14} />
              Pan
            </button>
            <button
              className="icon-button"
              aria-label="Zoom out source"
              onClick={() => setZoom((z) => Math.max(25, z - 25))}
            >
              <ZoomOut size={18} />
            </button>
            <output>{zoom}%</output>
            <button
              className="icon-button"
              aria-label="Zoom in source"
              onClick={() => setZoom((z) => Math.min(400, z + 25))}
            >
              <ZoomIn size={18} />
            </button>
            <Badge tone={page.human_verified ? 'green' : 'amber'}>
              {page.human_verified
                ? 'Human-verified transcription'
                : 'Transcription needs assessment'}
            </Badge>
          </div>
          <div className="source-workbench">
            <section>
              <div ref={viewport} className={`source-crop-viewport ${mode}`}>
                <div
                  ref={canvas}
                  className="source-page-canvas"
                  style={{ width: width * scale, height: height * scale }}
                  onPointerDown={down}
                  onPointerMove={move}
                  onPointerUp={() => {
                    drag.current = null;
                  }}
                  onPointerCancel={() => {
                    drag.current = null;
                  }}
                >
                  {page.regions?.map((region) => {
                    const box = region.bbox || [0, 0, width, height];
                    return (
                      <img
                        key={region.id}
                        draggable={false}
                        loading="lazy"
                        src={
                          region.image_url || `/api/documents/${documentId}/regions/${region.id}`
                        }
                        alt={`Original page ${pageNumber} tile`}
                        style={{
                          left: box[0] * scale,
                          top: box[1] * scale,
                          width: (box[2] - box[0]) * scale,
                          height: (box[3] - box[1]) * scale,
                        }}
                      />
                    );
                  })}
                  {selection && (
                    <div
                      data-testid="crop-selection"
                      className="crop-selection"
                      style={{
                        left: selection[0] * scale,
                        top: selection[1] * scale,
                        width: (selection[2] - selection[0]) * scale,
                        height: (selection[3] - selection[1]) * scale,
                      }}
                    />
                  )}
                </div>
              </div>
              <p className="field-help">
                Drag a rectangle to choose evidence. Zoom changes presentation; saved coordinates
                remain in original page units. Pan mode and scroll support tall pages.
              </p>
              {selection && (
                <section className="reference-editor">
                  <strong>
                    Selected original bounds: {selection.map((n) => n.toFixed(1)).join(', ')}
                  </strong>
                  <div className="form-grid">
                    <label>
                      Region label
                      <input value={label} onChange={(e) => setLabel(e.target.value)} />
                    </label>
                    <label>
                      Crop resolution (DPI)
                      <input
                        type="number"
                        min="72"
                        max="300"
                        value={dpi}
                        onChange={(e) => setDpi(Number(e.target.value))}
                      />
                    </label>
                  </div>
                  <button
                    className="button"
                    disabled={crop.isPending}
                    onClick={() => crop.mutate()}
                  >
                    <Crop size={15} />
                    Save evidence crop
                  </button>
                </section>
              )}
              {savedRegion && (
                <section className="reference-editor">
                  <h3>Saved source region</h3>
                  <img
                    className="saved-crop-preview"
                    src={
                      savedRegion.image_url ||
                      `/api/documents/${documentId}/regions/${savedRegion.id}`
                    }
                    alt="Saved high-resolution evidence crop"
                  />
                  {courseId && (
                    <>
                      <label>
                        Find card to attach
                        <input
                          value={cardSearch}
                          onChange={(e) => {
                            setCardSearch(e.target.value);
                            setCardId('');
                          }}
                          placeholder="Search card question, answer or tags"
                        />
                      </label>
                      <div className="form-grid">
                        <label>
                          Attach to card
                          <select
                            aria-label="Attach to card"
                            value={cardId}
                            onChange={(e) => setCardId(e.target.value)}
                          >
                            <option value="">No card attachment</option>
                            {cardChoices.data?.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.question.slice(0, 110)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Associate with concept
                          <select
                            aria-label="Associate with concept"
                            value={conceptId}
                            onChange={(e) => setConceptId(e.target.value)}
                          >
                            <option value="">No concept attachment</option>
                            {concepts.data?.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.title}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <button
                        className="button"
                        disabled={associate.isPending || (!cardId && !conceptId)}
                        onClick={() => associate.mutate()}
                      >
                        Attach selected evidence
                      </button>
                    </>
                  )}
                </section>
              )}
              {(crop.error || associate.error) && (
                <ErrorPanel error={crop.error || associate.error} />
              )}
            </section>
            <section>
              <SectionHead
                title="Effective transcription"
                action={
                  <button className="text-link" onClick={() => setShowHistory(!showHistory)}>
                    <History size={14} />
                    Correction history
                  </button>
                }
              />
              <label>
                Corrected text and mathematical notation
                <textarea
                  aria-label="Corrected transcription"
                  rows={13}
                  value={text}
                  onChange={(e) => {
                    dirty.current = true;
                    setText(e.target.value);
                  }}
                />
              </label>
              <label>
                Correction rationale
                <textarea
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="What was misread or omitted?"
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={verified}
                  onChange={(e) => setVerified(e.target.checked)}
                />
                <ShieldCheck size={14} />I independently checked this transcription against the
                original
              </label>
              {page.human_verified && (
                <label className="consent-label">
                  <input
                    type="checkbox"
                    checked={replace}
                    onChange={(e) => setReplace(e.target.checked)}
                  />
                  <span>
                    I explicitly allow replacing the previous human-verified correction. Its history
                    remains available.
                  </span>
                </label>
              )}
              <button
                className="button primary"
                disabled={save.isPending || !reason.trim() || (page.human_verified && !replace)}
                onClick={() => save.mutate()}
              >
                <Save size={15} />
                Save transcription correction
              </button>
              {save.error && <ErrorPanel error={save.error} />}
              <h3 className="preview-label">Rendered mathematical preview</h3>
              <MathText text={text} />
              {!!page.warnings?.length && (
                <div className="warning-note">{page.warnings.join(' · ')}</div>
              )}
              <details>
                <summary>Original untouched extraction</summary>
                <pre>{page.original_text ?? page.text}</pre>
              </details>
              {showHistory && (
                <div className="revision-list">
                  {(
                    page.corrections ||
                    interpretation.data.corrections?.filter(
                      (item) => item.page_number === pageNumber,
                    ) ||
                    []
                  ).map((correction, i) => (
                    <article key={i}>
                      <Badge>
                        {correction.verified ? 'Human verified' : 'Unverified correction'}
                      </Badge>
                      <small>{formatDate(String(correction.created_at || ''))}</small>
                      <MathText text={String(correction.text || '')} />
                      <p>{String(correction.reason || correction.rationale || '')}</p>
                    </article>
                  ))}
                </div>
              )}
              <hr />
              <h3>Reprocess only affected evidence</h3>
              <label>
                Processing mode
                <select value={retryMode} onChange={(e) => setRetryMode(e.target.value)}>
                  <option value="extract">Local extraction of selected page</option>
                  <option value="interpret">Vision interpretation of saved crop or page</option>
                </select>
              </label>
              {retryMode === 'interpret' && (
                <label className="consent-label">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  <span>
                    I approve sending the selected source regions and text to OpenAI for vision
                    interpretation.
                  </span>
                </label>
              )}
              <p className="field-help">
                Human-verified corrections are preserved unless replacement above is explicitly
                enabled.
              </p>
              <button
                className="button"
                disabled={reprocess.isPending || (retryMode === 'interpret' && !consent)}
                onClick={() => reprocess.mutate()}
              >
                <RefreshCw size={15} />
                Reprocess {savedRegion ? 'saved region' : `page ${pageNumber}`}
              </button>
              {reprocess.error && <ErrorPanel error={reprocess.error} />}
            </section>
          </div>
        </>
      ) : (
        <p>No extracted page is available. Run local extraction first.</p>
      )}
    </Modal>
  );
}
