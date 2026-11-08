import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, Check, ChevronRight, LoaderCircle, X, Sparkles, Search } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
export const ToastContext = createContext<(message: string, tone?: 'success' | 'error') => void>(
  () => {},
);
export function useToast() {
  return useContext(ToastContext);
}
export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<{ text: string; tone: string } | null>(null);
  useEffect(() => {
    if (message) {
      const t = setTimeout(() => setMessage(null), 6000);
      return () => clearTimeout(t);
    }
  }, [message]);
  return (
    <ToastContext.Provider value={(text, tone = 'success') => setMessage({ text, tone })}>
      {children}
      {message && (
        <div role="status" className={`toast ${message.tone}`}>
          {message.tone === 'error' ? <AlertCircle size={19} /> : <Check size={19} />}
          <span>{message.text}</span>
          <button aria-label="Dismiss notification" onClick={() => setMessage(null)}>
            <X size={16} />
          </button>
        </div>
      )}
    </ToastContext.Provider>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-title">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="title-actions">{actions}</div>}
    </header>
  );
}
export function Empty({
  icon: Icon = Sparkles,
  title,
  children,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={28} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <div className="loading-heading">
        <LoaderCircle className="spin" size={22} />
        <span>Loading your workspace…</span>
      </div>
      <div className="loading-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}
export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="error-panel" role="alert">
      <AlertCircle />
      <div>
        <strong>We couldn’t complete that request</strong>
        <p>{error instanceof Error ? error.message : String(error)}</p>
        {retry && (
          <button className="button small" onClick={retry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? 'wide' : ''}`}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}
export function Confirm({
  title,
  children,
  onConfirm,
  onClose,
  danger = true,
}: {
  title: string;
  children: ReactNode;
  onConfirm: () => void;
  onClose: () => void;
  danger?: boolean;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="muted">{children}</p>
      <div className="form-actions">
        <button className="button" onClick={onClose}>
          Keep it
        </button>
        <button className={`button ${danger ? 'danger' : 'primary'}`} onClick={onConfirm}>
          Confirm {danger ? 'deletion' : 'action'}
        </button>
      </div>
    </Modal>
  );
}
export function SearchInput({
  value,
  onChange,
  placeholder = 'Search…',
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="search-input">
      <Search size={17} />
      <input
        aria-label={placeholder}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
export function SectionHead({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {children && <p>{children}</p>}
      </div>
      {action}
    </div>
  );
}
export function Arrow() {
  return <ChevronRight size={16} />;
}
export function formatDate(date?: string) {
  if (!date) return '—';
  const d = new Date(date);
  return Number.isNaN(d.getTime())
    ? date
    : d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
}
export function human(value?: string) {
  return (value || 'pending').replace(/_/g, ' ').replace(/^./, (s) => s.toUpperCase());
}
export function statusTone(status?: string) {
  if (['completed', 'approved', 'verified', 'passed', 'covered', 'ready'].includes(status ?? ''))
    return 'green';
  if (['failed', 'rejected', 'error', 'blocked'].includes(status ?? '')) return 'red';
  if (
    ['running', 'queued', 'pending', 'needs_review', 'partial', 'paused', 'unresolved'].includes(
      status ?? '',
    )
  )
    return 'amber';
  return 'neutral';
}
