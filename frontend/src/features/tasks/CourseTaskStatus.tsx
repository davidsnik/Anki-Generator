import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight, LoaderCircle, Workflow } from 'lucide-react';
import type { Course } from '../../services/types';
import { api } from '../../services/api';
import { human } from '../../components/UI';
import { useTasks } from './live';
import { activeTaskStatuses } from './types';
import type { TaskPage } from './types';
export function CourseTaskStatus({
  courseId,
  courseName,
  compact = false,
  latest = false,
  fallback,
}: {
  courseId: string;
  courseName: string;
  compact?: boolean;
  latest?: boolean;
  fallback?: Course['active_task'];
}) {
  const { data } = useTasks();
  const current =
    data?.active_runs.find((task) => task.course_id === courseId) ||
    (fallback
      ? {
          ...fallback,
          course_id: courseId,
          course_name: courseName,
          priority: 0,
          created_at: '',
          queue_position: null,
        }
      : undefined);
  const previous = useQuery({
    queryKey: ['tasks', 'course-latest', courseId],
    queryFn: () => api<TaskPage>(`/tasks?course_id=${courseId}&offset=0&limit=1&sort=newest`),
    enabled: latest && !current,
    refetchInterval: 5000,
  });
  const task = current || previous.data?.items[0];
  if (!task || (!latest && !activeTaskStatuses.includes(task.status) && task.status !== 'paused'))
    return null;
  return (
    <Link
      className={`course-task-status ${compact ? 'compact' : ''} ${task.status}`}
      to={`/tasks/${task.id}`}
      aria-label={`View task for ${courseName}: ${human(task.status)}`}
    >
      {activeTaskStatuses.includes(task.status) && task.status !== 'queued' ? (
        <LoaderCircle className="spin" size={15} />
      ) : (
        <Workflow size={15} />
      )}
      <span>
        <strong>
          {human(task.mode || 'processing')} · {human(task.status)}
        </strong>
        {!compact && (
          <small>
            {task.queue_position
              ? `Queue position ${task.queue_position}`
              : human(task.current_stage || 'Saved task')}{' '}
            · {task.id.slice(0, 8)}
          </small>
        )}
      </span>
      <ArrowUpRight size={14} />
    </Link>
  );
}
