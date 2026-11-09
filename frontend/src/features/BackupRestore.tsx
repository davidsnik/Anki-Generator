import { useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ArchiveRestore, FileCheck, Upload } from 'lucide-react';
import { api, write } from '../services/api';
import type { Json } from '../services/types';
import { ErrorPanel, Modal, human } from '../components/UI';
export function BackupRestore() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="button" onClick={() => setOpen(true)}>
        <ArchiveRestore size={16} />
        Validate & restore backup
      </button>
      {open && <RestoreDialog onClose={() => setOpen(false)} />}
    </>
  );
}
export function RestoreDialog({ onClose }: { onClose: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Json | null>(null);
  const [mode, setMode] = useState('clean');
  const [confirm, setConfirm] = useState('');
  const [restored, setRestored] = useState<Json | null>(null);
  const validate = useMutation({
    mutationFn: () => {
      const data = new FormData();
      data.append('file', file!);
      return api<Json>('/backup/validate', { method: 'POST', body: data });
    },
    onSuccess: setReport,
  });
  const restore = useMutation({
    mutationFn: () =>
      write<Json>('/backup/restore', {
        token: report?.token || report?.validation_token,
        mode,
        confirm: true,
      }),
    onSuccess: setRestored,
  });
  const warnings = (report?.warnings || []) as string[];
  const compatible =
    report?.valid !== false && report?.compatible !== false && report?.version_compatible !== false;
  if (restored)
    return (
      <Modal title="Backup restored successfully" onClose={() => window.location.assign('/')}>
        <p>
          Courses, original evidence, revisions and stable note identities have been restored.
          Review the restored workspace before resuming processing.
        </p>
        <div className="restore-summary">
          {Object.entries((restored.counts || {}) as Json)
            .filter(([, v]) => typeof v === 'number')
            .map(([key, value]) => (
              <p key={key}>
                <strong>{human(key)}</strong>: {String(value)}
              </p>
            ))}
        </div>
        {typeof restored.recovery_backup === 'string' &&
          restored.recovery_backup.startsWith('/api/backup/recovery/') && (
            <a
              className="button"
              href={restored.recovery_backup}
              download="anki-generator-recovery.zip"
            >
              Download pre-restore recovery backup
            </a>
          )}
        <div className="form-actions">
          <button className="button primary" onClick={() => window.location.assign('/')}>
            Open restored workspace
          </button>
        </div>
      </Modal>
    );
  return (
    <Modal title="Validate before restoring" onClose={onClose}>
      <p className="muted">
        Restore courses, originals, card revisions, review decisions, source evidence and stable
        Anki identities. API keys are excluded. Existing data is replaced only after explicit
        confirmation; a recovery backup is retained by the backend.
      </p>
      <input
        ref={input}
        type="file"
        hidden
        accept=".zip"
        onChange={(e) => {
          setFile(e.target.files?.[0] || null);
          setReport(null);
          setConfirm('');
        }}
      />
      <button className="button" onClick={() => input.current?.click()}>
        <Upload size={16} />
        {file ? file.name : 'Choose application backup ZIP'}
      </button>
      <button
        className="button"
        disabled={!file || validate.isPending}
        onClick={() => validate.mutate()}
      >
        <FileCheck size={16} />
        {validate.isPending ? 'Validating archive…' : 'Validate backup'}
      </button>
      {validate.error && <ErrorPanel error={validate.error} />}{' '}
      {report && (
        <>
          <div className="restore-summary">
            <h3>{compatible ? 'Validation passed' : 'Backup cannot be restored'}</h3>
            {Object.entries((report.summary || report) as Json)
              .filter(
                ([key, v]) =>
                  !['token', 'validation_token', 'warnings'].includes(key) && typeof v !== 'object',
              )
              .map(([key, value]) => (
                <p key={key}>
                  <strong>{human(key)}</strong>: {String(value)}
                </p>
              ))}
          </div>
          {!!warnings.length && (
            <div className="warning-note">
              <div>
                {warnings.map((warning, i) => (
                  <p key={i}>{warning}</p>
                ))}
              </div>
            </div>
          )}
          <label>
            Restoration policy
            <select
              value={mode}
              onChange={(e) => {
                setMode(e.target.value);
                setConfirm('');
              }}
            >
              <option value="clean">Restore into a clean application state</option>
              <option value="replace">
                Replace current application data after creating recovery backup
              </option>
            </select>
          </label>
          <label>
            Type RESTORE to confirm
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="off"
            />
          </label>
          <p className="field-help">
            Active jobs must be stopped before restoration. The backend checks archive paths, schema
            compatibility and data integrity before changing live state. Merging is not performed.
          </p>
          {restore.error && <ErrorPanel error={restore.error} />}
          <div className="form-actions">
            <button className="button" onClick={onClose}>
              Cancel
            </button>
            <button
              className="button danger"
              disabled={!compatible || confirm !== 'RESTORE' || restore.isPending}
              onClick={() => restore.mutate()}
            >
              {restore.isPending ? 'Restoring safely…' : 'Restore validated backup'}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
