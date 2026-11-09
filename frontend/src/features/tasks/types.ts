import type { Json, Run } from '../../services/types';
export interface TaskLimits {
  max_concurrent_jobs: number;
  api_concurrency: number;
  local_concurrency: number;
  per_job_api_concurrency: number;
  per_model_concurrency: Record<string, number>;
}
export interface TaskStatistics {
  concepts_extracted?: number | null;
  cards_generated?: number | null;
  cards_reused?: number | null;
  cards_verified?: number | null;
  documents_total?: number;
  documents_processed?: number;
  pages_processed?: number;
  concepts_current?: number;
  cards_current?: number;
  cards_verified_current?: number;
}
export interface TaskEvent {
  id?: string;
  created_at?: string;
  occurred_at?: string;
  kind?: string;
  event_type?: string;
  message?: string;
  details?: Json;
}
export interface TaskEventPage {
  items: TaskEvent[];
  total: number;
  offset: number;
  limit: number;
}
export interface Task extends Omit<Run, 'events'> {
  warnings_total?: number;
  course_name: string;
  priority: number;
  queue_position?: number | null;
  elapsed_seconds?: number;
  statistics?: TaskStatistics;
  allowed_actions?: string[];
  events?: TaskEventPage;
  outputs?: { cards_url?: string; concepts_url?: string; exports_url?: string };
}
export interface TaskSummary {
  counts: Record<string, number>;
  limits: TaskLimits;
  active_runs: Task[];
  server_time?: string;
  connection_time?: string;
}
export interface TaskPage {
  items: Task[];
  total: number;
  offset: number;
  limit: number;
  summary: Record<string, number>;
}
export const activeTaskStatuses = ['queued', 'running', 'pausing', 'cancelling', 'recovering'];
export const hasActiveTasks = (counts: Record<string, number>) =>
  activeTaskStatuses.some((status) => (counts[status] || 0) > 0);
export function taskActions(task: Pick<Task, 'status' | 'allowed_actions'>): string[] {
  if (task.allowed_actions) return task.allowed_actions;
  const actions: Record<string, string[]> = {
    queued: ['pause', 'cancel'],
    running: ['pause', 'cancel'],
    pausing: ['cancel'],
    paused: ['resume', 'cancel'],
    failed: ['retry', 'cancel'],
    interrupted: ['cancel'],
    prepared: ['cancel'],
    recovering: ['cancel'],
  };
  return actions[task.status] || [];
}
export function elapsedTime(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return value >= 3600
    ? `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`
    : `${Math.floor(value / 60)}m ${value % 60}s`;
}
