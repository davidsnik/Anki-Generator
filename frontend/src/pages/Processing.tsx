import { useState } from 'react';
import { Link } from 'react-router-dom';
import { elapsedTime, taskActions } from '../features/tasks/types';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileText,
  Layers,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Square,
  Workflow,
} from 'lucide-react';
import type { Course, Document, Json, KeyStatus, Run, Stage } from '../services/types';
import { api, list, write } from '../services/api';
import type { ModelValidation } from '../services/models';
import {
  Badge,
  Empty,
  ErrorPanel,
  formatDate,
  human,
  Loading,
  Modal,
  SectionHead,
  statusTone,
  useToast,
} from '../components/UI';
const activeStatuses = ['queued', 'running', 'pausing', 'recovering', 'cancelling'];
export function RunDialog({
  course,
  onClose,
  mode = 'generate',
  extra = {},
}: {
  course: Course;
  onClose: () => void;
  mode?: string;
  extra?: Json;
}) {
  const [consent, setConsent] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [local, setLocal] = useState(mode === 'extract');
  const client = useQueryClient();
  const toast = useToast();
  const [intent] = useState(() => crypto.randomUUID());
  const documents = useQuery({
    queryKey: ['documents', course.id],
    queryFn: async () => list<Document>(await api(`/courses/${course.id}/documents`)),
  });
  const settings = useQuery({
    queryKey: ['run-settings'],
    queryFn: () => api<Json & { key_status: KeyStatus }>('/settings'),
    enabled: !local,
    staleTime: 0,
  });
  const modelCheck = useQuery({
    queryKey: [
      'run-model-preflight',
      course.id,
      settings.data?.models,
      settings.data?.reasoning_effort,
      settings.data?.processing,
    ],
    queryFn: () => write<ModelValidation>('/settings/models/validate'),
    enabled: !local && !!settings.data?.key_status?.configured,
    retry: false,
    staleTime: 0,
  });
  const hasDocuments = !!documents.data?.length;
  const ready =
    hasDocuments &&
    !documents.isPending &&
    !documents.isError &&
    (local ||
      (!settings.isPending &&
        !settings.isError &&
        !!settings.data?.key_status?.configured &&
        modelCheck.data?.valid === true &&
        !modelCheck.isFetching &&
        !modelCheck.isError));
  const start = useMutation({
    mutationFn: () =>
      write<Run>(`/courses/${course.id}/runs`, {
        mode: local ? 'extract' : mode,
        consent: local ? false : consent,
        overwrite_manual: overwrite,
        ...extra,
        idempotency_key: intent,
      }),
    onSuccess: (run) => {
      client.invalidateQueries();
      window.dispatchEvent(
        new CustomEvent('anki-task-change', {
          detail: { task: { ...run, course_name: course.name, priority: 0 } },
        }),
      );
      onClose();
      toast(`${course.name}: task ${run.status}. You can keep using your workspace.`, 'success', {
        label: 'View task',
        to: `/tasks/${run.id}`,
      });
    },
  });
  return (
    <Modal
      title={
        mode === 'revise'
          ? 'Improve this card'
          : mode === 'topic'
            ? 'Deepen this topic'
            : 'Connect your course. Create your deck.'
      }
      onClose={() => {
        if (!start.isPending) onClose();
      }}
    >
      <section className="run-readiness" aria-label="Processing readiness" aria-live="polite">
        {documents.isPending ? (
          <p>Checking course documents…</p>
        ) : documents.error ? (
          <ErrorPanel error={documents.error} retry={() => documents.refetch()} />
        ) : !hasDocuments ? (
          <div className="warning-note">
            <FileText size={18} />
            <span>
              Import at least one source document first.{' '}
              <Link to={`/courses/${course.id}/documents`} onClick={onClose}>
                Open Documents
              </Link>
            </span>
          </div>
        ) : (
          <p>
            <Check size={15} /> {documents.data!.length} source document
            {documents.data!.length === 1 ? '' : 's'} ready
          </p>
        )}
        {!local &&
          (settings.isPending ? (
            <p>Checking API configuration…</p>
          ) : settings.error ? (
            <ErrorPanel error={settings.error} retry={() => settings.refetch()} />
          ) : !settings.data?.key_status?.configured ? (
            <div className="warning-note">
              <ShieldCheck size={18} />
              <span>
                Add your OpenAI API key to generate cards.{' '}
                <Link to="/settings" onClick={onClose}>
                  Open Settings
                </Link>
                . You can still extract documents locally.
              </span>
            </div>
          ) : modelCheck.isFetching ? (
            <p>
              <LoaderCircle size={15} className="spin" /> Checking saved model access and
              compatibility…
            </p>
          ) : modelCheck.error ? (
            <ErrorPanel error={modelCheck.error} retry={() => modelCheck.refetch()} />
          ) : (
            modelCheck.data && (
              <div className={modelCheck.data.valid ? 'field-help' : 'warning-note'}>
                <ShieldCheck size={16} />
                <div>
                  <strong>
                    {modelCheck.data.valid
                      ? 'Model configuration checked'
                      : 'Update your model configuration before starting'}
                  </strong>
                  {!!modelCheck.data.issues.length && (
                    <ul>
                      {modelCheck.data.issues.map((issue, index) => (
                        <li key={index}>{issue.message}</li>
                      ))}
                    </ul>
                  )}
                  {!modelCheck.data.valid && (
                    <Link to="/settings" onClick={onClose}>
                      Review models in Settings
                    </Link>
                  )}
                  {modelCheck.data.valid && (
                    <p>
                      Account visibility and known capabilities checked without generating content.
                      Actual API permissions and charges depend on your account.
                    </p>
                  )}
                  <button className="text-link" onClick={() => modelCheck.refetch()}>
                    Check again
                  </button>
                </div>
              </div>
            )
          ))}
      </section>
      <p className="muted">
        {local
          ? 'Extract source text and original visual regions locally. No course material is sent to OpenAI.'
          : 'Your sources become a course map, then candidates, independent reviews, targeted improvements, and a coverage audit.'}
      </p>
      {mode === 'generate' && (
        <label className="check-label">
          <input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} />{' '}
          Extract documents locally only
        </label>
      )}
      <div className="run-disclosure">
        <div className="disclosure-icon">
          <ShieldCheck size={21} />
        </div>
        <div>
          <strong>{local ? 'Local processing' : 'Before your material leaves this device'}</strong>
          <p>
            {local
              ? 'Extraction preserves originals and records uncertainty for later review.'
              : 'This run can send extracted course text, educational roles, source metadata, semantic embedding inputs (learning targets, cards and assumptions), and rendered source regions (including handwriting and diagrams) to the OpenAI API. API usage may incur charges. Your API key stays on the server.'}
          </p>
          <details>
            <summary>{documents.data?.length ?? 0} source documents in this course</summary>
            <ul>
              {documents.data?.map((d) => (
                <li key={d.id}>
                  {d.filename} · {human(d.category)}
                </li>
              ))}
            </ul>
          </details>
          {!local && (
            <a
              href="https://platform.openai.com/docs/guides/your-data"
              target="_blank"
              rel="noreferrer"
            >
              OpenAI API data controls <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>
      {!local && (
        <label className="consent-label">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I approve sending this course material to OpenAI for the processing described above.
          </span>
        </label>
      )}
      {mode === 'revise' && (
        <label className="check-label">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
          />{' '}
          Allow replacing this manually edited card. Its previous revision is preserved.
        </label>
      )}
      <p className="field-help">
        Progress and intermediate results are saved. You can pause at a safe checkpoint and resume
        later.
      </p>
      {start.error && <ErrorPanel error={start.error} />}
      <div className="form-actions">
        <button className="button" disabled={start.isPending} onClick={onClose}>
          Cancel
        </button>
        <button
          className="button primary"
          disabled={start.isPending || !ready || (!local && !consent)}
          onClick={() => start.mutate()}
        >
          <Play size={16} />
          {start.isPending ? 'Starting…' : local ? 'Start local extraction' : 'Start processing'}
        </button>
      </div>
    </Modal>
  );
}
export function ProcessingPage({ course }: { course: Course }) {
  const [start, setStart] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const runs = useQuery({
    queryKey: ['runs', course.id],
    queryFn: async () => list<Run>(await api(`/courses/${course.id}/runs`)),
    refetchInterval: 2000,
  });
  const currentId = selected || runs.data?.[0]?.id;
  const detail = useQuery({
    queryKey: ['run', currentId],
    queryFn: () => api<Run>(`/runs/${currentId}`),
    enabled: !!currentId,
    refetchInterval: 2000,
  });
  return (
    <>
      <SectionHead
        title="From raw material to real understanding"
        action={
          <button className="button primary" onClick={() => setStart(true)}>
            <Play size={16} />
            New processing run
          </button>
        }
      >
        Every stage is saved. Every uncertainty stays visible.{' '}
        <Link className="text-link" to={`/tasks?course_id=${course.id}`}>
          Open complete task history
        </Link>
      </SectionHead>
      {runs.isPending ? (
        <Loading />
      ) : runs.error ? (
        <ErrorPanel error={runs.error} />
      ) : !runs.data.length ? (
        <section className="panel">
          <Empty
            icon={Workflow}
            title="Let’s connect the dots"
            action={
              <button className="button primary" onClick={() => setStart(true)}>
                <Play size={16} />
                Start a run
              </button>
            }
          >
            Your sources are the beginning. A processing run builds the knowledge map, generates
            cards, and checks their quality independently.
          </Empty>
        </section>
      ) : (
        <div className="processing-layout">
          <div>
            {detail.isPending ? (
              <Loading />
            ) : detail.error ? (
              <ErrorPanel error={detail.error} />
            ) : (
              detail.data && <RunDetail run={detail.data} />
            )}
          </div>
          <aside className="panel run-history">
            <SectionHead title="Run history" />
            {runs.data.map((run) => (
              <button
                className={run.id === currentId ? 'selected' : ''}
                key={run.id}
                onClick={() => setSelected(run.id)}
              >
                <div>
                  <strong>
                    {human(
                      run.mode ||
                        (run.config?.mode as string) ||
                        run.current_stage ||
                        'Course processing',
                    )}
                  </strong>
                  <span>{formatDate(run.created_at)}</span>
                </div>
                <Badge tone={statusTone(run.status)}>{human(run.status)}</Badge>
                <ChevronRight size={14} />
              </button>
            ))}
          </aside>
        </div>
      )}
      {start && <RunDialog course={course} onClose={() => setStart(false)} />}
    </>
  );
}
export function RunDetail({ run, controls = true }: { run: Run; controls?: boolean }) {
  const client = useQueryClient();
  const toast = useToast();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const available = taskActions({ status: run.status, allowed_actions: run.allowed_actions });
  const [retryStage, setRetryStage] = useState<string | null>(null);
  const [retryConsent, setRetryConsent] = useState(false);
  const retry = useMutation({
    mutationFn: () =>
      write(`/runs/${run.id}/retry-stage`, {
        stage: retryStage,
        consent: run.mode === 'extract' ? false : retryConsent,
        replace_human: false,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      setRetryStage(null);
      setRetryConsent(false);
      toast('Selected stage queued as a new reproducible run; valid unrelated work is reused.');
    },
  });
  const action = useMutation({
    mutationFn: (name: string) => write(`/runs/${run.id}/${name}`),
    onSuccess: () => {
      client.invalidateQueries();
      setConfirmCancel(false);
      toast('Processing control updated. Changes take effect at a safe checkpoint.');
    },
  });
  const stages: Stage[] = Array.isArray(run.stages)
    ? run.stages
    : Object.entries(run.stages || {}).map(([name, value]) => ({
        ...value,
        name: value.name || name,
      }));
  const complete = stages.filter((s) => s.status === 'completed').length;
  const metrics = { ...run.progress, ...run.metrics, ...run.usage };
  const startTime = new Date(run.started_at || run.created_at).getTime();
  const endTime = run.finished_at || run.completed_at;
  const seconds = Math.max(
    0,
    Math.round(((endTime ? new Date(endTime).getTime() : Date.now()) - startTime) / 1000),
  );
  const elapsed =
    typeof run.elapsed_seconds === 'number'
      ? elapsedTime(run.elapsed_seconds)
      : Number.isFinite(seconds)
        ? `${Math.floor(seconds / 60)}m ${seconds % 60}s`
        : '—';
  return (
    <>
      <section className="panel pipeline-panel">
        <div className="run-heading">
          <div>
            <div className="eyebrow">PROCESSING RUN · {run.id.slice(0, 8)}</div>
            <h2>{human(run.current_stage || run.stage || run.status)}</h2>
            <span
              className="muted"
              title={
                run.elapsed_basis ||
                'Wall time since the first start; active intervals were not recorded.'
              }
            >
              <Clock3 size={14} /> Started {formatDate(run.started_at || run.created_at)} ·{' '}
              {typeof run.elapsed_seconds === 'number' && !run.elapsed_basis?.startsWith('Legacy')
                ? 'Processing'
                : 'Wall time'}{' '}
              {elapsed}
            </span>
          </div>
          <Badge tone={statusTone(run.status)}>
            {activeStatuses.includes(run.status) && <LoaderCircle className="spin" size={12} />}{' '}
            {human(run.status)}
          </Badge>
        </div>
        {!!stages.length && (
          <div className="pipeline-summary">
            <span>
              {complete} of {stages.length} stages completed
            </span>
            <div className="stage-count-bar">
              {stages.map((s, i) => (
                <span
                  title={`${human(s.name || s.stage)}: ${s.status}`}
                  key={i}
                  className={s.status}
                />
              ))}
            </div>
          </div>
        )}
        {controls && (
          <div className="run-controls">
            {available.includes('pause') && (
              <button
                className="button"
                disabled={action.isPending}
                onClick={() => action.mutate('pause')}
              >
                <Pause size={15} />
                Pause at checkpoint
              </button>
            )}
            {available.includes('resume') && (
              <button
                className="button primary"
                disabled={action.isPending}
                onClick={() => action.mutate('resume')}
              >
                <Play size={15} />
                Resume
              </button>
            )}
            {available.includes('retry') && (
              <button
                className="button"
                disabled={action.isPending}
                onClick={() => action.mutate('retry')}
              >
                <RefreshCw size={15} />
                Retry saved work
              </button>
            )}
            {available.includes('cancel') && (
              <button
                className="button"
                disabled={action.isPending}
                onClick={() => setConfirmCancel(true)}
              >
                <Square size={14} />
                Cancel
              </button>
            )}
          </div>
        )}
        {controls && action.error && <ErrorPanel error={action.error} />}
        <div className="pipeline-stages">
          {stages.map((stage, i) => (
            <div className={`pipeline-stage ${stage.status}`} key={stage.name || i}>
              <span className="stage-bullet">
                {stage.status === 'completed' ? (
                  <Check size={16} />
                ) : stage.status === 'running' ? (
                  <LoaderCircle size={16} className="spin" />
                ) : stage.status === 'failed' ? (
                  <AlertTriangle size={15} />
                ) : (
                  i + 1
                )}
              </span>
              <div>
                <strong>{human(stage.name || stage.stage || `Stage ${i + 1}`)}</strong>
                <p>
                  {stage.message ||
                    (stage as Stage & { error?: string }).error ||
                    human(stage.status)}
                </p>
                {stage.total !== undefined && (
                  <span className="stage-items">
                    {stage.completed ?? 0} / {stage.total} items
                  </span>
                )}
              </div>
              <div className="inline-actions wrap">
                <Badge tone={statusTone(stage.status)}>{human(stage.status)}</Badge>
                {!activeStatuses.includes(run.status) && stage.status !== 'pending' && (
                  <button
                    className="button small"
                    onClick={() => {
                      setRetryStage(stage.name || stage.stage || '');
                      setRetryConsent(false);
                    }}
                  >
                    Retry this stage
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        {!stages.length && (
          <p className="muted">Stage checkpoints will appear when the worker begins this run.</p>
        )}
      </section>
      {!!Object.keys(metrics).length && (
        <section className="panel">
          <SectionHead title="Observed progress" />
          <div className="run-metrics">
            {Object.entries(metrics)
              .filter(([, value]) => typeof value !== 'object')
              .map(([key, value]) => (
                <div key={key}>
                  <span>{human(key)}</span>
                  <strong>
                    {typeof value === 'number' ? value.toLocaleString() : String(value)}
                  </strong>
                </div>
              ))}
          </div>
          <p className="field-help">
            Usage reflects provider responses. Cost estimates, when present, are estimates rather
            than actual billed charges.
          </p>
        </section>
      )}
      {Array.isArray(metrics.coverage_gaps) && metrics.coverage_gaps.length > 0 && (
        <section className="panel">
          <SectionHead title="Coverage that still needs attention" />
          <div className="coverage-findings">
            {metrics.coverage_gaps.map((gap, index) => {
              const item = gap as Json;
              return (
                <article key={index}>
                  <strong>
                    {String(item.title || item.concept_key || 'Uncovered learning target')}
                  </strong>
                  <p>
                    {String(item.reason || 'This target needs additional distinct verified cards.')}
                  </p>
                </article>
              );
            })}
          </div>
        </section>
      )}
      {run.error && <ErrorPanel error={run.error} />}{' '}
      {!!run.warnings?.length && (
        <section className="warning-note">
          <AlertTriangle size={20} />
          <div>
            <strong>Items that need attention</strong>
            {run.warnings.map((w, i) => (
              <p key={i}>{w}</p>
            ))}
          </div>
        </section>
      )}
      {confirmCancel && (
        <Modal title="Cancel this task?" onClose={() => setConfirmCancel(false)}>
          <p>
            Completed work stays saved. Future processing stops at a safe checkpoint; a provider
            request already in flight may finish.
          </p>
          <div className="form-actions">
            <button className="button" onClick={() => setConfirmCancel(false)}>
              Keep processing
            </button>
            <button
              className="button danger"
              disabled={action.isPending || !available.includes('cancel')}
              onClick={() => action.mutate('cancel')}
            >
              Cancel this task
            </button>
          </div>
          {action.error && <ErrorPanel error={action.error} />}
        </Modal>
      )}
      {retryStage && (
        <Modal title={`Retry ${human(retryStage)} only?`} onClose={() => setRetryStage(null)}>
          <p>
            The backend reuses the original configuration and valid unrelated checkpoints. Changed
            sources and protected human revisions are checked before processing.
          </p>
          {run.mode !== 'extract' && (
            <label className="consent-label">
              <input
                type="checkbox"
                checked={retryConsent}
                onChange={(e) => setRetryConsent(e.target.checked)}
              />
              <span>
                I approve sending the source text, semantic embedding inputs (learning targets,
                cards and assumptions), original regions and selected stage inputs to OpenAI for
                this retry. API usage may incur charges.
              </span>
            </label>
          )}
          {retry.error && <ErrorPanel error={retry.error} />}
          <div className="form-actions">
            <button className="button" onClick={() => setRetryStage(null)}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={retry.isPending || (run.mode !== 'extract' && !retryConsent)}
              onClick={() => retry.mutate()}
            >
              Confirm stage retry
            </button>
          </div>
        </Modal>
      )}
      <section className="panel">
        <details>
          <summary>Reproducibility & processing record</summary>
          <div className="record-grid">
            <div>
              <FileText size={17} />
              <strong>Input documents</strong>
              <pre>{JSON.stringify(run.inputs || run.input_documents || [], null, 2)}</pre>
            </div>
            <div>
              <Layers size={17} />
              <strong>Models & configuration</strong>
              <pre>{JSON.stringify({ models: run.models, ...run.config }, null, 2)}</pre>
            </div>
          </div>
        </details>
      </section>
    </>
  );
}
