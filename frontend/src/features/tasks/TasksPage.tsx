import { useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  CheckCheck,
  Clock3,
  FileText,
  Layers,
  ListTodo,
  LoaderCircle,
  RefreshCw,
  Settings2,
  WifiOff,
} from 'lucide-react';
import { api } from '../../services/api';
import type { Course } from '../../services/types';
import {
  Badge,
  Empty,
  ErrorPanel,
  formatDate,
  human,
  Loading,
  PageTitle,
  SearchInput,
  SectionHead,
  statusTone,
} from '../../components/UI';
import { Pagination } from '../Pagination';
import { RunDetail } from '../../pages/Processing';
import { TaskControls } from './TaskControls';
import { useTasks } from './live';
import { activeTaskStatuses, elapsedTime, hasActiveTasks } from './types';
import type { Task, TaskEventPage, TaskPage } from './types';

export function TaskConnection() {
  const { online, failed, updatedAt, refresh } = useTasks();
  return (
    <div
      className={`task-connection ${!online || failed ? 'disconnected' : ''}`}
      role="status"
      aria-live="off"
    >
      {!online || failed ? <WifiOff size={14} /> : <span className="live-dot" />}
      <span>
        {!online || failed
          ? `Reconnecting · showing last known state${updatedAt ? ` from ${new Date(updatedAt).toLocaleTimeString()}` : ''}`
          : updatedAt
            ? `Live · updated ${new Date(updatedAt).toLocaleTimeString()}`
            : 'Connecting to task updates…'}
      </span>
      {(!online || failed) && (
        <button className="text-link" onClick={refresh}>
          Reconnect
        </button>
      )}
    </div>
  );
}
export function TaskStatistics({ task, compact = false }: { task: Task; compact?: boolean }) {
  const stats = task.statistics;
  const values: [string, number | null | undefined][] = [
    ['Documents processed', stats?.documents_processed],
    ['Pages processed', stats?.pages_processed],
    ['Concepts extracted', stats?.concepts_extracted],
    ['Cards generated', stats?.cards_generated],
    ['Cards reused', stats?.cards_reused],
    ['Cards verified', stats?.cards_verified],
  ];
  return (
    <>
      <div className={compact ? 'task-inline-statistics' : 'task-statistics'}>
        {values
          .filter(([, value]) => value !== undefined)
          .map(([label, value]) => (
            <div key={label}>
              <strong>
                {value === null ? '—' : value?.toLocaleString()}
                {label === 'Documents processed' && stats?.documents_total !== undefined
                  ? ` / ${stats.documents_total}`
                  : ''}
              </strong>
              <span
                title={
                  value === null ? 'This historical task did not record this counter.' : undefined
                }
              >
                {label}
              </span>
            </div>
          ))}
        {!compact && (
          <div>
            <strong>
              {task.elapsed_seconds === undefined ? '—' : elapsedTime(task.elapsed_seconds)}
            </strong>
            <span title={task.elapsed_basis}>
              {task.elapsed_basis?.startsWith('Legacy')
                ? 'Elapsed (legacy wall time)'
                : 'Elapsed processing'}
            </span>
          </div>
        )}
      </div>
      <div className="task-inventory-context" aria-label="Current course inventory">
        {(
          [
            ['Concepts in course', stats?.concepts_current],
            ['Cards in course', stats?.cards_current],
            ['Verified cards in course', stats?.cards_verified_current],
          ] as const
        )
          .filter(([, value]) => value !== undefined)
          .map(([label, value]) => (
            <span key={label}>
              <strong>{value?.toLocaleString()}</strong> {label}
            </span>
          ))}
      </div>
    </>
  );
}
export function TaskUsage({ task }: { task: Task }) {
  const tokens = task.usage?.total_tokens;
  const estimate = task.usage?.estimated_cost_usd;
  return (
    <div className="task-usage">
      <span>
        <Activity size={13} />
        {typeof tokens === 'number'
          ? `${tokens.toLocaleString()} tokens recorded`
          : 'Usage not recorded yet'}
      </span>
      {typeof estimate === 'number' && <span>${estimate.toFixed(4)} estimate</span>}
      {typeof task.usage?.unpriced_calls === 'number' && task.usage.unpriced_calls > 0 && (
        <span>Some requests unpriced</span>
      )}
    </div>
  );
}
export function TaskCard({ task, returnTo = '/tasks' }: { task: Task; returnTo?: string }) {
  const stages = Array.isArray(task.stages) ? task.stages : Object.values(task.stages || {});
  const stage = stages.find((stage) => stage.name === task.current_stage);
  return (
    <article
      className={`task-card ${task.status}`}
      aria-label={`Task ${task.course_name}`}
      data-testid={`task-${task.id}`}
    >
      <div className="task-card-main">
        <div className={`task-symbol ${task.status}`}>
          {task.status === 'running' ? (
            <LoaderCircle className="spin" size={21} />
          ) : task.status === 'completed' ? (
            <CheckCheck size={21} />
          ) : (
            <ListTodo size={21} />
          )}
        </div>
        <div className="task-card-content">
          <div className="task-card-heading">
            <Link state={{ from: returnTo }} to={`/tasks/${task.id}`}>
              <h3>{task.course_name}</h3>
            </Link>
            <Badge tone={statusTone(task.status)}>{human(task.status)}</Badge>
            {task.queue_position != null && (
              <span className="queue-position">Queue #{task.queue_position}</span>
            )}
          </div>
          <div className="task-card-subtitle">
            <span>{human(task.mode || 'generate')}</span>
            <span>·</span>
            <span>{human(task.current_stage || 'Waiting for a worker')}</span>
            {stage?.total !== undefined && (
              <span>
                · {stage.completed ?? 0} / {stage.total} items
              </span>
            )}
          </div>
          <TaskStatistics task={task} compact />
          {task.error && <p className="task-error">{task.error}</p>}
          {!!task.warnings?.length && (
            <p className="task-warning">
              {task.warnings_total ?? task.warnings.length}{' '}
              {(task.warnings_total ?? task.warnings.length) === 1 ? 'warning' : 'warnings'} ·
              inspect task details
            </p>
          )}
        </div>
        <Link
          className="task-open"
          to={`/tasks/${task.id}`}
          state={{ from: returnTo }}
          aria-label={`Open task details for ${task.course_name}`}
        >
          <ArrowUpRight size={20} />
        </Link>
      </div>
      <div className="task-card-footer">
        <span className="task-created" title={task.elapsed_basis}>
          <Clock3 size={13} />
          {task.elapsed_seconds !== undefined && <>{elapsedTime(task.elapsed_seconds)} · </>}
          {formatDate(task.created_at)}
        </span>
        <TaskUsage task={task} />
        <TaskControls task={task} compact />
      </div>
    </article>
  );
}
const statuses = [
  'active',
  'queued',
  'running',
  'pausing',
  'paused',
  'cancelling',
  'cancelled',
  'completed',
  'failed',
  'interrupted',
  'recovering',
];
export function TasksPage({ courses }: { courses: Course[] }) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const { data: summary } = useTasks();
  const [search, setSearch] = useState(params.get('q') || '');
  const urlSearch = params.get('q') || '';
  useEffect(() => setSearch(urlSearch), [urlSearch]);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search === urlSearch) return;
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (search.trim()) next.set('q', search);
          else next.delete('q');
          next.delete('offset');
          return next;
        },
        { replace: true },
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [search, urlSearch, setParams]);
  const update = (key: string, value: string) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value && value !== 'all') next.set(key, value);
      else next.delete(key);
      next.delete('offset');
      return next;
    });
  const offset = Math.max(0, Math.floor(Number(params.get('offset')) || 0));
  const query = new URLSearchParams(params);
  query.set('offset', String(offset));
  query.set('limit', '24');
  for (const [key, end] of [
    ['date_from', false],
    ['date_to', true],
  ] as const) {
    const value = query.get(key);
    if (value && /^\d{4}-\d{2}-\d{2}$/.test(value))
      query.set(key, new Date(`${value}T${end ? '23:59:59.999' : '00:00:00'}`).toISOString());
  }
  const tasks = useQuery({
    queryKey: ['tasks', 'list', query.toString()],
    queryFn: () => api<TaskPage>(`/tasks?${query}`),
    refetchInterval: (state) =>
      hasActiveTasks(state.state.data?.summary || summary?.counts || {}) ? 1500 : 5000,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: 1,
  });
  return (
    <>
      <PageTitle
        eyebrow="A LITTLE LESS WAITING"
        title="Your learning, in motion."
        description="One place for every course task. Follow the work, manage the queue, and keep learning while it runs."
        actions={
          <Link className="button" to="/settings">
            <Settings2 size={16} />
            Concurrency settings
          </Link>
        }
      />
      <div className="task-overview-stats">
        {[
          ['running', 'Running now', 'Independent courses at work'],
          ['queued', 'In the queue', 'Saved and ready for capacity'],
          ['paused', 'Paused', 'Checkpoints safely retained'],
          ['failed', 'Needs attention', 'Inspect errors and recovery'],
        ].map(([status, title, help]) => (
          <button
            key={status}
            className={`task-overview-stat ${status} ${params.get('status') === status ? 'selected' : ''}`}
            onClick={() => update('status', params.get('status') === status ? '' : status)}
          >
            <span>{title}</span>
            <strong>{summary ? (summary.counts[status] ?? 0) : '—'}</strong>
            <small>{help}</small>
          </button>
        ))}
      </div>
      <div className="task-history-heading">
        <SectionHead title="Tasks & history">
          Each course keeps its own configuration, checkpoints and results.
        </SectionHead>
        <TaskConnection />
      </div>
      {summary && (
        <div className="task-capacity">
          <Activity size={15} />
          <span>
            Up to <strong>{summary.limits.max_concurrent_jobs}</strong> course tasks ·{' '}
            <strong>{summary.limits.api_concurrency}</strong> shared API requests ·{' '}
            <strong>{summary.limits.local_concurrency}</strong> local processors
          </span>
          <Link to="/settings">
            Manage limits <ArrowUpRight size={13} />
          </Link>
        </div>
      )}
      <div className="task-filters panel">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search courses or task IDs…"
        />
        <div className="task-filter-selects">
          <label>
            Course
            <select
              aria-label="Task course"
              value={params.get('course_id') || ''}
              onChange={(e) => update('course_id', e.target.value)}
            >
              <option value="">Every course</option>
              {courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select
              aria-label="Task status"
              value={params.get('status') || ''}
              onChange={(e) => update('status', e.target.value)}
            >
              <option value="">Every status</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status === 'active' ? 'All active states' : human(status)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Type
            <select
              aria-label="Task type"
              value={params.get('mode') || ''}
              onChange={(e) => update('mode', e.target.value)}
            >
              <option value="">Every type</option>
              {['generate', 'extract', 'interpret', 'revise', 'topic'].map((mode) => (
                <option key={mode} value={mode}>
                  {human(mode)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sort
            <select
              aria-label="Sort tasks"
              value={params.get('sort') || 'newest'}
              onChange={(e) => update('sort', e.target.value)}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="priority">Priority first</option>
            </select>
          </label>
          <label>
            From
            <input
              aria-label="Tasks from date"
              type="date"
              value={params.get('date_from') || ''}
              onChange={(e) => update('date_from', e.target.value)}
            />
          </label>
          <label>
            Through
            <input
              aria-label="Tasks through date"
              type="date"
              value={params.get('date_to') || ''}
              onChange={(e) => update('date_to', e.target.value)}
            />
          </label>
        </div>
        {params.size > 0 && (
          <button
            className="text-link"
            onClick={() => {
              setSearch('');
              setParams({});
            }}
          >
            Clear filters
          </button>
        )}
      </div>
      {tasks.isError && <ErrorPanel error={tasks.error} retry={() => tasks.refetch()} />}
      {tasks.isPending ? (
        <Loading />
      ) : !tasks.data ? null : !tasks.data.items.length ? (
        <section className="panel">
          <Empty
            icon={ListTodo}
            title="Room for the next idea"
            action={
              <Link className="button primary" to="/courses">
                Open your courses <ArrowUpRight size={15} />
              </Link>
            }
          >
            No tasks match this view. Start processing from a course, or adjust the filters to
            explore its history.
          </Empty>
        </section>
      ) : (
        <div className="task-list">
          {tasks.data.items.map((task) => (
            <TaskCard key={task.id} task={task} returnTo={location.pathname + location.search} />
          ))}
        </div>
      )}
      <Pagination
        offset={offset}
        total={tasks.data?.total || 0}
        limit={24}
        loading={tasks.isFetching}
        onChange={(next) =>
          setParams((previous) => {
            const values = new URLSearchParams(previous);
            values.set('offset', String(next));
            return values;
          })
        }
      />
      <p className="field-help">
        Queue order follows saved priority and scheduler fairness. In-flight provider requests can
        finish after a pause or cancellation request. Counters reflect saved work; no completion
        time is assumed.
      </p>
    </>
  );
}
function TaskEvents({ task }: { task: Task }) {
  const [offset, setOffset] = useState(0);
  const events = useQuery({
    queryKey: ['tasks', 'events', task.id, offset],
    queryFn: () => api<TaskEventPage>(`/tasks/${task.id}/events?offset=${offset}&limit=25`),
    refetchInterval: activeTaskStatuses.includes(task.status) ? 1500 : 5000,
  });
  return (
    <section className="panel task-events">
      <SectionHead title="Recent activity" />
      {events.isPending ? (
        <Loading />
      ) : events.error ? (
        <ErrorPanel error={events.error} />
      ) : (
        <>
          <ol>
            {events.data.items.map((event, index) => (
              <li key={event.id || index}>
                <span className="event-dot" />
                <time>{formatDate(event.created_at || event.occurred_at)}</time>
                <strong>{human(event.kind || event.event_type || 'Task event')}</strong>
                <p>{event.message || 'Saved task transition'}</p>
                {event.details && (
                  <details>
                    <summary>Recorded details</summary>
                    <pre>{JSON.stringify(event.details, null, 2)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
          {!events.data.items.length && (
            <p className="muted">Saved events appear as work begins.</p>
          )}
          <Pagination offset={offset} total={events.data.total} limit={25} onChange={setOffset} />
        </>
      )}
    </section>
  );
}
export function TaskDetailPage() {
  const { taskId } = useParams();
  const location = useLocation();
  const [tab, setTab] = useState('pipeline');
  const detail = useQuery({
    queryKey: ['tasks', 'detail', taskId],
    queryFn: () => api<Task>(`/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (query) =>
      activeTaskStatuses.includes(query.state.data?.status || '') ? 1500 : 5000,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: 1,
  });
  if (detail.isPending) return <Loading />;
  if (detail.isError && !detail.data)
    return (
      <>
        <Link className="back-link" to="/tasks">
          <ArrowLeft size={15} />
          All tasks
        </Link>
        <ErrorPanel error={detail.error} retry={() => detail.refetch()} />
      </>
    );
  const task = detail.data!;
  const from =
    typeof location.state?.from === 'string' && location.state.from.startsWith('/tasks')
      ? location.state.from
      : '/tasks';
  return (
    <>
      <Link className="back-link" to={from}>
        <ArrowLeft size={15} />
        All tasks
      </Link>
      {detail.isError && <ErrorPanel error={detail.error} retry={() => detail.refetch()} />}
      <PageTitle
        eyebrow={`${human(task.mode || 'generate').toUpperCase()} TASK · ${task.id.slice(0, 8)}`}
        title={task.course_name}
        description="A separate course context. Saved work and outcomes you can inspect."
        actions={<Badge tone={statusTone(task.status)}>{human(task.status)}</Badge>}
      />
      <div className="task-detail-toolbar">
        <TaskControls task={task} />
        <TaskConnection />
      </div>
      <TaskStatistics task={task} />
      <div className="task-detail-layout">
        <div>
          <div className="task-detail-tabs" role="tablist" aria-label="Task detail sections">
            {[
              ['pipeline', 'Pipeline', Layers],
              ['activity', 'Activity', Activity],
              ['configuration', 'Configuration', Settings2],
            ].map(([id, label, Icon]) => {
              const Symbol = Icon as typeof Layers;
              return (
                <button
                  key={String(id)}
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => setTab(String(id))}
                >
                  <Symbol size={16} />
                  {String(label)}
                </button>
              );
            })}
          </div>
          {tab === 'pipeline' ? (
            <RunDetail run={{ ...task, events: undefined }} controls={false} />
          ) : tab === 'activity' ? (
            <TaskEvents task={task} />
          ) : (
            <section className="panel task-configuration">
              <SectionHead title="Recorded configuration">
                This task keeps the settings and source versions saved at submission. Changes to
                course criteria affect future tasks.
              </SectionHead>
              <pre>{JSON.stringify({ models: task.models, ...task.config }, null, 2)}</pre>
              <details>
                <summary>Source versions and selection</summary>
                <pre>{JSON.stringify(task.inputs || task.input_documents || [], null, 2)}</pre>
              </details>
            </section>
          )}
        </div>
        <aside>
          <section className="panel task-outputs">
            <div className="aside-icon">
              <BookOpen size={22} />
            </div>
            <h3>Keep learning while it runs.</h3>
            <p className="muted">
              Course results become available independently. Inventory counts show the current
              course, including work from earlier tasks.
            </p>
            <Link className="button" to={`/courses/${task.course_id}/cards`}>
              <Layers size={15} />
              Open course cards
            </Link>
            <Link className="button" to={`/courses/${task.course_id}/knowledge`}>
              <Activity size={15} />
              View knowledge map
            </Link>
            <Link className="button" to={`/courses/${task.course_id}/exports`}>
              <ArrowUpRight size={15} />
              Review & export
            </Link>
            <hr />
            <TaskUsage task={task} />
            {task.queue_position != null && (
              <p className="field-help">
                Saved queue position: {task.queue_position} · priority {task.priority}
              </p>
            )}
            <p className="field-help">
              <FileText size={13} />
              Submitted {formatDate(task.created_at)}
            </p>
            <button className="text-link" onClick={() => detail.refetch()}>
              <RefreshCw size={13} />
              Refresh this task
            </button>
          </section>
        </aside>
      </div>
    </>
  );
}
