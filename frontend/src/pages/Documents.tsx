import { useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Archive,
  ExternalLink,
  File,
  FileText,
  FolderUp,
  Image,
  Link2,
  Pencil,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { Course, Document, Page, Region, Source } from '../services/types';
import { suggestDocumentRole } from '../services/documentRoles';
import { sourceHighlight } from '../services/geometry';
import { api, list, upload, write } from '../services/api';
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
export const categories = [
  ['lecture', 'Lecture material'],
  ['personal_notes', 'Personal notes'],
  ['exercises', 'Exercises'],
  ['solutions', 'Worked solutions'],
  ['reference', 'Other reference'],
];
const authorityOptions = [
  ['unknown', 'Unknown authority'],
  ['official', 'Official / instructor'],
  ['student', 'Student-produced'],
];
export function DocumentsPage({ course }: { course: Course }) {
  const client = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [category, setCategory] = useState('lecture');
  const [authority, setAuthority] = useState('unknown');
  const [progress, setProgress] = useState(0);
  const [fileRoles, setFileRoles] = useState<Record<string, string>>({});
  const [uploadStates, setUploadStates] = useState<Record<string, string>>({});
  const [search, setSearch] = useState('');
  const [preview, setPreview] = useState<Document | null>(null);
  const [editing, setEditing] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState<Document | null>(null);
  const documents = useQuery({
    queryKey: ['documents', course.id],
    queryFn: async () => list<Document>(await api(`/courses/${course.id}/documents`)),
    refetchInterval: 5000,
  });
  const mutation = useMutation({
    mutationFn: async () => {
      const totalBytes = files.reduce((n, f) => n + f.size, 0) || 1;
      let completedBytes = 0;
      for (const file of files) {
        const path = file.webkitRelativePath || file.name;
        setUploadStates((previous) => ({ ...previous, [path]: 'uploading' }));
        try {
          await upload(course.id, [file], fileRoles[path] || category, authority, (n) =>
            setProgress(Math.round(((completedBytes + (file.size * n) / 100) / totalBytes) * 100)),
          );
          completedBytes += file.size;
          setUploadStates((previous) => ({ ...previous, [path]: 'imported' }));
        } catch (error) {
          setUploadStates((previous) => ({ ...previous, [path]: 'failed' }));
          throw error;
        }
      }
    },
    onSuccess: () => {
      client.invalidateQueries();
      setFiles([]);
      setFileRoles({});
      setUploadStates({});
      setProgress(0);
      toast('Materials imported. Review each document’s role before processing.');
    },
  });
  const del = useMutation({
    mutationFn: () => api(`/documents/${deleting!.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      client.invalidateQueries();
      setDeleting(null);
      toast('Source document removed.');
    },
  });
  const reprocess = useMutation({
    mutationFn: (id: string) => write(`/documents/${id}`, { reprocess: true }, 'PATCH'),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Extraction invalidated. Start local extraction to rebuild it.');
    },
  });
  const extract = useMutation({
    mutationFn: () => write(`/courses/${course.id}/runs`, { mode: 'extract', consent: false }),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Local extraction started. Follow progress in Processing.');
    },
  });
  function addFiles(selected: File[]) {
    if (mutation.isPending) return;
    setFileRoles((current) => {
      const next = { ...current };
      for (const file of selected) {
        const path = file.webkitRelativePath || file.name;
        const suggested = suggestDocumentRole(file.name);
        if (suggested && !next[path]) next[path] = suggested;
      }
      return next;
    });
    setFiles((current) =>
      [...current, ...selected].filter(
        (file, index, all) =>
          all.findIndex(
            (f) =>
              (f.webkitRelativePath || f.name) === (file.webkitRelativePath || file.name) &&
              f.size === file.size,
          ) === index,
      ),
    );
  }
  function drop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    addFiles(Array.from(e.dataTransfer.files));
  }
  const filtered =
    documents.data?.filter((d) =>
      `${d.filename} ${d.category}`.toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  return (
    <>
      <div className="document-toolbar">
        <SectionHead title="The foundation of your understanding">
          Import lectures, notes, and exercises. Every source has a different role.
        </SectionHead>
        <button
          className="button"
          disabled={extract.isPending || !documents.data?.length}
          onClick={() => extract.mutate()}
        >
          <RefreshCw size={16} />
          Extract locally
        </button>
      </div>
      <div
        className={`upload-zone ${drag ? 'dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={drop}
      >
        <div className="upload-icon">
          <Upload size={25} />
        </div>
        <div>
          <h3>Drop your course materials here</h3>
          <p>PDF, images, text, Markdown, LaTeX, DOCX, PPTX, or a ZIP with folders.</p>
          <div className="inline-actions">
            <button className="button primary small" onClick={() => input.current?.click()}>
              <File size={15} /> Choose files
            </button>
            <button className="button small" onClick={() => folder.current?.click()}>
              <FolderUp size={15} />
              Upload folder
            </button>
            <span className="field-help">Folders unavailable? Import a ZIP instead.</span>
          </div>
        </div>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept=".pdf,.png,.jpg,.jpeg,.txt,.md,.tex,.docx,.pptx,.zip"
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []));
            e.target.value = '';
          }}
        />
        <input
          ref={folder}
          type="file"
          multiple
          hidden
          {...{ webkitdirectory: '', directory: '' }}
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []));
            e.target.value = '';
          }}
        />
      </div>
      {!!files.length && (
        <section className="panel import-queue">
          <SectionHead
            title={`${files.length} files ready to import`}
            action={
              <button
                className="icon-button"
                aria-label="Clear import queue"
                onClick={() => setFiles([])}
              >
                <X size={18} />
              </button>
            }
          >
            Roles are suggested from filenames. Review each file below, or choose one role for the
            whole batch. Roles stay editable after import.
          </SectionHead>
          <div className="form-grid">
            <label>
              Educational role
              <select
                value={category}
                disabled={mutation.isPending}
                onChange={(e) => {
                  setCategory(e.target.value);
                  setFileRoles({});
                }}
              >
                {categories.map(([id, label]) => (
                  <option value={id} key={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Source authority
              <select
                value={authority}
                disabled={mutation.isPending}
                onChange={(e) => setAuthority(e.target.value)}
              >
                {authorityOptions.map(([id, label]) => (
                  <option value={id} key={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="queued-files">
            {files.map((f, i) => (
              <div key={`${f.name}${i}`}>
                <FileText size={15} />
                <span>{f.webkitRelativePath || f.name}</span>
                <select
                  aria-label={`Category for ${f.name}`}
                  value={fileRoles[f.webkitRelativePath || f.name] || category}
                  onChange={(e) =>
                    setFileRoles((previous) => ({
                      ...previous,
                      [f.webkitRelativePath || f.name]: e.target.value,
                    }))
                  }
                >
                  {categories.map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
                <small>
                  {uploadStates[f.webkitRelativePath || f.name] ||
                    `${(f.size / 1024).toFixed(0)} KB`}
                </small>
                <button
                  className="icon-button"
                  aria-label={`Remove ${f.name} from queue`}
                  onClick={() => setFiles(files.filter((_, j) => i !== j))}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
          {mutation.isPending && (
            <div className="upload-progress">
              <progress max="100" value={progress} />
              <span>
                {progress === 100 ? 'Validating and saving originals…' : `Uploading ${progress}%`}
              </span>
            </div>
          )}
          <div className="form-actions">
            <button
              className="button primary"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              <Upload size={16} />
              {mutation.isPending ? 'Importing…' : 'Import materials'}
            </button>
          </div>
          {mutation.error && <ErrorPanel error={mutation.error} />}
        </section>
      )}
      <div className="document-summary">
        <span>
          <ShieldCheck size={15} /> Originals stay unchanged
        </span>
        <span>
          <Archive size={15} /> Folder paths preserved
        </span>
        <span>
          <Link2 size={15} /> Link exercises to solutions
        </span>
      </div>
      <div className="section-head">
        <h2>
          Source library <span className="count">{documents.data?.length ?? 0}</span>
        </h2>
        <SearchInput value={search} onChange={setSearch} placeholder="Search documents…" />
      </div>
      {documents.isPending ? (
        <Loading />
      ) : documents.error ? (
        <ErrorPanel error={documents.error} />
      ) : !filtered.length ? (
        <Empty
          icon={FileText}
          title={search ? 'No matching documents' : 'Your ideas need a starting point'}
        >
          {search
            ? 'Try a different filename or category.'
            : 'Import your first lecture, exercise sheet, or notes to begin connecting the dots.'}
        </Empty>
      ) : (
        <div className="document-list">
          {filtered.map((document) => (
            <div className="document-row" key={document.id}>
              <div className={`file-icon ${document.category}`}>
                <FileText size={23} />
              </div>
              <div className="document-info">
                <button className="unstyled document-name" onClick={() => setPreview(document)}>
                  {document.filename}
                </button>
                <div>
                  <span>
                    {document.relative_path || document.original_filename || document.filename}
                  </span>
                  <span>
                    {document.page_count ? `${document.page_count} pages` : 'Not extracted'}
                  </span>
                  <span>
                    {document.size_bytes ? `${(document.size_bytes / 1024).toFixed(0)} KB` : ''}
                  </span>
                </div>
                {!!document.warnings?.length && (
                  <small className="warning-text">{document.warnings.join(' · ')}</small>
                )}
                {document.error && <small className="warning-text">{document.error}</small>}
              </div>
              <div className="document-labels">
                <Badge>
                  {categories.find(([id]) => id === document.category)?.[1] ||
                    human(document.category)}
                </Badge>
                <small>{human(document.authority)} source</small>
              </div>
              <Badge tone={statusTone(document.status)}>{human(document.status)}</Badge>
              <div className="row-actions">
                <button
                  className="icon-button"
                  aria-label={`Preview ${document.filename}`}
                  onClick={() => setPreview(document)}
                >
                  <Image size={17} />
                </button>
                <button
                  className="icon-button"
                  aria-label={`Edit ${document.filename}`}
                  onClick={() => setEditing(document)}
                >
                  <Pencil size={16} />
                </button>
                <button
                  className="icon-button"
                  aria-label={`Reprocess ${document.filename}`}
                  disabled={reprocess.isPending}
                  onClick={() => reprocess.mutate(document.id)}
                >
                  <RefreshCw size={16} />
                </button>
                <button
                  className="icon-button danger-icon"
                  aria-label={`Delete ${document.filename}`}
                  onClick={() => setDeleting(document)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {(extract.error || reprocess.error) && (
        <ErrorPanel error={extract.error || reprocess.error} />
      )}
      <div className="inline-note">
        <ShieldCheck size={18} />
        <span>
          Local extraction reads your files on this device. AI interpretation starts only after you
          approve a generation run.
        </span>
      </div>
      {preview && (
        <SourcePreview
          documentId={preview.id}
          documentName={preview.filename}
          onClose={() => setPreview(null)}
        />
      )}{' '}
      {editing && (
        <EditDocument
          document={editing}
          documents={documents.data ?? []}
          onClose={() => setEditing(null)}
        />
      )}{' '}
      {deleting && (
        <Confirm
          title={`Remove ${deleting.filename}?`}
          onClose={() => setDeleting(null)}
          onConfirm={() => del.mutate()}
        >
          This removes the imported copy and its extraction data. Generated cards may need their
          evidence reviewed.
        </Confirm>
      )}
      {del.error && <ErrorPanel error={del.error} />}
    </>
  );
}
function EditDocument({
  document,
  documents,
  onClose,
}: {
  document: Document;
  documents: Document[];
  onClose: () => void;
}) {
  const [data, setData] = useState(document);
  const client = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () =>
      write(
        `/documents/${document.id}`,
        {
          filename: data.filename,
          category: data.category,
          authority: data.authority,
          linked_document_id: data.linked_document_id || null,
        },
        'PATCH',
      ),
    onSuccess: () => {
      client.invalidateQueries();
      onClose();
      toast('Document details updated.');
    },
  });
  return (
    <Modal title="Source details" onClose={onClose}>
      <label>
        Display name
        <input
          value={data.filename}
          onChange={(e) => setData({ ...data, filename: e.target.value })}
        />
      </label>
      <div className="form-grid">
        <label>
          Educational role
          <select
            value={data.category}
            onChange={(e) => setData({ ...data, category: e.target.value })}
          >
            {categories.map(([id, label]) => (
              <option value={id} key={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Authority
          <select
            value={data.authority}
            onChange={(e) => setData({ ...data, authority: e.target.value })}
          >
            {authorityOptions.map(([id, label]) => (
              <option value={id} key={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Linked exercise or solution
        <select
          value={data.linked_document_id || ''}
          onChange={(e) => setData({ ...data, linked_document_id: e.target.value })}
        >
          <option value="">No linked document</option>
          {documents
            .filter((d) => d.id !== document.id)
            .map((d) => (
              <option value={d.id} key={d.id}>
                {d.filename}
              </option>
            ))}
        </select>
      </label>
      <p className="field-help">
        Authority is evidence context. Even an official solution can contain a mistake.
      </p>
      {save.error && <ErrorPanel error={save.error} />}
      <div className="form-actions">
        <button className="button" onClick={onClose}>
          Cancel
        </button>
        <button className="button primary" disabled={save.isPending} onClick={() => save.mutate()}>
          Save details
        </button>
      </div>
    </Modal>
  );
}
export function SourcePreview({
  documentId,
  documentName,
  source,
  onClose,
  embedded = false,
}: {
  documentId: string;
  documentName?: string;
  source?: Source;
  onClose: () => void;
  embedded?: boolean;
}) {
  const [page, setPage] = useState(source?.page_number ?? source?.page ?? 1);
  const [showText, setShowText] = useState(false);
  const pages = useQuery({
    queryKey: ['pages', documentId],
    queryFn: async () => list<Page>(await api(`/documents/${documentId}/pages`)),
  });
  const selected = pages.data?.find((p) => p.page_number === page);
  const regions = selected?.regions || [];
  const target = source?.region_id ? regions.find((r) => r.id === source.region_id) : null;
  const content = (
    <>
      <div className="source-tools">
        <span>Original evidence</span>
        <label>
          Page
          <select value={page} onChange={(e) => setPage(Number(e.target.value))}>
            {pages.data?.map((p) => (
              <option value={p.page_number} key={p.page_number}>
                {p.page_number}
              </option>
            ))}
            {!pages.data?.length && <option value={1}>1</option>}
          </select>
        </label>
        <button className="button small" onClick={() => setShowText(!showText)}>
          {showText ? 'Visual evidence' : 'Extracted text'}
        </button>
        <a
          className="button small"
          href={`/api/documents/${documentId}/source#page=${page}`}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={14} />
          Original
        </a>
      </div>
      {pages.isPending ? (
        <Loading />
      ) : pages.error ? (
        <ErrorPanel error={pages.error} />
      ) : (
        <div className="source-viewer">
          {showText ? (
            <pre>
              {selected?.text || 'No machine-readable text. Inspect the original visual evidence.'}
            </pre>
          ) : target ? (
            <EvidenceImage documentId={documentId} region={target} source={source} page={page} />
          ) : regions.length ? (
            <div className="source-regions">
              {regions.map((region) => (
                <EvidenceImage
                  key={region.id}
                  documentId={documentId}
                  region={region}
                  source={source}
                  page={page}
                />
              ))}
            </div>
          ) : selected?.render_url || selected?.image_url ? (
            <img src={selected.render_url || selected.image_url} alt={`Original page ${page}`} />
          ) : (
            <Empty icon={FileText} title="Visual evidence is in the original file">
              Open the original above, or run local extraction to create source regions.
            </Empty>
          )}
          {!!selected?.warnings?.length && (
            <div className="warning-note">{selected.warnings.join(' · ')}</div>
          )}
          {source?.quote || source?.text ? (
            <blockquote>{source.quote || source.text}</blockquote>
          ) : null}
        </div>
      )}
    </>
  );
  return embedded ? (
    <div className="embedded-source">{content}</div>
  ) : (
    <Modal title={documentName || 'Supporting source'} onClose={onClose} wide>
      {content}
    </Modal>
  );
}

function EvidenceImage({
  documentId,
  region,
  source,
  page,
}: {
  documentId: string;
  region: Region;
  source?: Source;
  page: number;
}) {
  const highlight = sourceHighlight(
    source?.bbox || (source?.region_id === region.id ? region.bbox : undefined),
    region.bbox,
  );
  return (
    <div className={`source-image ${highlight ? 'highlighted' : ''}`}>
      <div className="source-image-canvas">
        <img
          loading="lazy"
          src={region.image_url || `/api/documents/${documentId}/regions/${region.id}`}
          alt={`Original source page ${page}, ${highlight ? 'supporting location highlighted' : 'rendered region'}`}
        />
        {highlight && <span className="source-highlight" aria-hidden="true" style={highlight} />}
      </div>
      {region.bbox && <small>Original source coordinates: {region.bbox.join(', ')}</small>}
    </div>
  );
}
