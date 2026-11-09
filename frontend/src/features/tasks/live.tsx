import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, LoaderCircle, WifiOff } from 'lucide-react';
import { api, ApiError } from '../../services/api';
import { useToast, human } from '../../components/UI';
import type { Task, TaskSummary } from './types';
import { activeTaskStatuses, hasActiveTasks } from './types';
interface LiveState {
  data?: TaskSummary;
  online: boolean;
  failed: boolean;
  updatedAt: number;
  refresh: () => void;
}
const TasksContext = createContext<LiveState>({
  online: true,
  failed: false,
  updatedAt: 0,
  refresh: () => {},
});
export const useTasks = () => useContext(TasksContext);
export const taskMutationEvent = 'anki-task-change';
function changeMessage(task: Task) {
  return `${task.course_name}: ${task.status === 'running' ? 'processing started' : human(task.status).toLowerCase()}.`;
}
export async function claimTaskNotification(key: string): Promise<boolean> {
  function claim() {
    try {
      const values = JSON.parse(
        localStorage.getItem('anki-task-notifications') || '[]',
      ) as string[];
      if (values.includes(key)) return false;
      localStorage.setItem('anki-task-notifications', JSON.stringify([...values.slice(-99), key]));
      return true;
    } catch {
      return true;
    }
  }
  return navigator.locks ? navigator.locks.request('anki-task-notifications', claim) : claim();
}
export function TaskLiveProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const toast = useToast();
  const [online, setOnline] = useState(navigator.onLine);
  const observed = useRef<Map<string, Task> | null>(null);
  const summary = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: () => api<TaskSummary>('/tasks/summary'),
    refetchInterval: (query) =>
      query.state.data && hasActiveTasks(query.state.data.counts) ? 1500 : 5000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: 1,
  });
  useEffect(() => {
    const channel =
      typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('anki-tasks');
    const refresh = () => {
      void client.invalidateQueries({ queryKey: ['tasks'] });
    };
    const changed = (event: Event) => {
      const task = (event as CustomEvent<{ task?: Task }>).detail?.task;
      if (task) {
        if (!observed.current) observed.current = new Map();
        observed.current.set(task.id, task);
      }
      refresh();
      channel?.postMessage({ task });
    };
    const connected = () => {
      setOnline(navigator.onLine);
      if (navigator.onLine) refresh();
    };
    const visible = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    if (channel)
      channel.onmessage = (event) => {
        const task = event.data?.task as Task | undefined;
        if (task) {
          if (!observed.current) observed.current = new Map();
          observed.current.set(task.id, task);
        }
        refresh();
      };
    window.addEventListener(taskMutationEvent, changed);
    window.addEventListener('online', connected);
    window.addEventListener('offline', connected);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      channel?.close();
      window.removeEventListener(taskMutationEvent, changed);
      window.removeEventListener('online', connected);
      window.removeEventListener('offline', connected);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [client]);
  useEffect(() => {
    if (!summary.data) return;
    const current = new Map(summary.data.active_runs.map((task) => [task.id, task]));
    if (!observed.current) {
      observed.current = current;
      return;
    }
    if (document.visibilityState !== 'visible' || !document.hasFocus()) return;
    let alive = true;
    const previous = observed.current;
    const changes = [...current.values()].filter(
      (task) => previous.has(task.id) && previous.get(task.id)!.status !== task.status,
    );
    const missing = [...previous.values()].filter(
      (task) => !current.has(task.id) && activeTaskStatuses.includes(task.status),
    );
    void Promise.allSettled(
      missing.slice(0, 32).map((task) => api<Task>(`/tasks/${task.id}`)),
    ).then(async (results) => {
      if (!alive) return;
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          if (result.value.status !== missing[index].status) changes.push(result.value);
          if (activeTaskStatuses.includes(result.value.status))
            current.set(result.value.id, result.value);
        } else if (!(result.reason instanceof ApiError && result.reason.status === 404))
          current.set(missing[index].id, missing[index]);
      });
      observed.current = current;
      for (const task of changes) {
        if (
          !['running', 'completed', 'failed', 'paused', 'interrupted', 'cancelled'].includes(
            task.status,
          )
        )
          continue;
        const key = `${task.id}:${task.status}:${task.finished_at || task.updated_at || task.created_at}`;
        if (await claimTaskNotification(key)) {
          if (!alive) return;
          toast(
            changeMessage(task),
            ['failed', 'interrupted'].includes(task.status) ? 'error' : 'success',
            {
              label: 'View task',
              to: `/tasks/${task.id}`,
            },
          );
        }
      }
    });
    return () => {
      alive = false;
    };
  }, [summary.data, summary.dataUpdatedAt, toast]);
  return (
    <TasksContext.Provider
      value={{
        data: summary.data,
        online,
        failed: summary.isError,
        updatedAt: summary.dataUpdatedAt,
        refresh: () => {
          void client.invalidateQueries({ queryKey: ['tasks'] });
        },
      }}
    >
      {children}
    </TasksContext.Provider>
  );
}
export function GlobalTaskIndicator() {
  const { data, online, failed } = useTasks();
  const active = data && hasActiveTasks(data.counts);
  return (
    <Link
      className={`global-task-indicator ${active ? 'active' : ''}`}
      to="/tasks"
      aria-label={
        !online || failed
          ? 'Tasks reconnecting; showing last known processing state'
          : data
            ? `${data.counts.running || 0} running · ${data.counts.queued || 0} queued tasks`
            : 'Open tasks'
      }
    >
      {!online || failed ? (
        <WifiOff size={15} />
      ) : active ? (
        <LoaderCircle className="spin" size={15} />
      ) : (
        <Activity size={15} />
      )}
      <span>
        {!online || failed
          ? 'Tasks · reconnecting'
          : data
            ? `${data.counts.running || 0} running · ${data.counts.queued || 0} queued`
            : 'Tasks'}
      </span>
    </Link>
  );
}
