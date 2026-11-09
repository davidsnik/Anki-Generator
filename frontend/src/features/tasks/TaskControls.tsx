import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowUp,
  Pause,
  Play,
  RotateCcw,
  Square,
  SlidersHorizontal,
} from 'lucide-react';
import { write } from '../../services/api';
import { ErrorPanel, Modal, human, useToast } from '../../components/UI';
import type { Task } from './types';
import { taskActions } from './types';
export function TaskControls({ task, compact = false }: { task: Task; compact?: boolean }) {
  const [cancel, setCancel] = useState(false);
  const [priority, setPriority] = useState(false);
  const [value, setValue] = useState(task.priority || 0);
  const client = useQueryClient();
  const toast = useToast();
  const update = useMutation({
    mutationFn: (action: string) => write(`/runs/${task.id}/${action}`),
    onSuccess: (_, action) => {
      void client.invalidateQueries({ queryKey: ['tasks'] });
      setCancel(false);
      toast(`${task.course_name}: ${human(action).toLowerCase()} requested.`, 'success', {
        label: 'View task',
        to: `/tasks/${task.id}`,
      });
    },
  });
  const reorder = useMutation({
    mutationFn: (next: number) => write(`/tasks/${task.id}/priority`, { priority: next }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['tasks'] });
      setPriority(false);
      toast('Queue priority saved. Other tasks keep their own progress.');
    },
  });
  const actions = taskActions(task);
  return (
    <>
      <div className={`task-controls ${compact ? 'compact' : ''}`}>
        {actions.includes('pause') && (
          <button
            className="button small"
            disabled={update.isPending}
            onClick={() => update.mutate('pause')}
          >
            <Pause size={14} />
            Pause
          </button>
        )}
        {actions.includes('resume') && (
          <button
            className="button small"
            disabled={update.isPending}
            onClick={() => update.mutate('resume')}
          >
            <Play size={14} />
            Resume
          </button>
        )}
        {actions.includes('retry') && (
          <button
            className="button small"
            disabled={update.isPending}
            onClick={() => update.mutate('retry')}
          >
            <RotateCcw size={14} />
            Retry
          </button>
        )}
        {actions.includes('cancel') && (
          <button
            className="button small"
            disabled={update.isPending}
            onClick={() => setCancel(true)}
          >
            <Square size={13} />
            Cancel
          </button>
        )}
        {task.status === 'queued' && (
          <>
            <button
              className="icon-button"
              aria-label={`Move ${task.course_name} earlier in queue`}
              disabled={reorder.isPending || task.priority >= 100}
              onClick={() => reorder.mutate(Math.min(100, (task.priority || 0) + 1))}
            >
              <ArrowUp size={15} />
            </button>
            <button
              className="icon-button"
              aria-label={`Move ${task.course_name} later in queue`}
              disabled={reorder.isPending || task.priority <= -100}
              onClick={() => reorder.mutate(Math.max(-100, (task.priority || 0) - 1))}
            >
              <ArrowDown size={15} />
            </button>
            <button
              className="button small"
              onClick={() => {
                setValue(task.priority || 0);
                setPriority(true);
              }}
            >
              <SlidersHorizontal size={14} />
              Priority {task.priority || 0}
            </button>
          </>
        )}
      </div>
      {(update.error || reorder.error) && <ErrorPanel error={update.error || reorder.error} />}
      {cancel && (
        <Modal title={`Cancel ${task.course_name}?`} onClose={() => setCancel(false)}>
          <p>
            Only this task stops scheduling future work. Completed checkpoints and course material
            stay available. An OpenAI request already in flight may finish and save its response;
            cancellation is not a claim that the provider cancelled that request.
          </p>
          {!actions.includes('cancel') && (
            <p className="field-help">
              This task is now {human(task.status).toLowerCase()}; cancellation is no longer
              available.
            </p>
          )}
          <div className="form-actions">
            <button className="button" onClick={() => setCancel(false)}>
              Keep processing
            </button>
            <button
              className="button danger"
              disabled={update.isPending || !actions.includes('cancel')}
              onClick={() => update.mutate('cancel')}
            >
              Cancel this task
            </button>
          </div>
          {update.error && <ErrorPanel error={update.error} />}
        </Modal>
      )}
      {priority && (
        <Modal title="Set queue priority" onClose={() => setPriority(false)}>
          <p>
            Higher values request an earlier queue position. Running work is not interrupted; the
            scheduler still enforces course conflicts and global capacity.
          </p>
          <label>
            Priority
            <input
              type="number"
              min={-100}
              max={100}
              value={value}
              onChange={(e) => setValue(Number(e.target.value))}
            />
          </label>
          {task.status !== 'queued' && (
            <p className="warning-text">This task has already left the queue.</p>
          )}
          {reorder.error && <ErrorPanel error={reorder.error} />}
          <div className="form-actions">
            <button className="button" onClick={() => setPriority(false)}>
              Close
            </button>
            <button
              className="button primary"
              disabled={
                reorder.isPending ||
                task.status !== 'queued' ||
                !Number.isInteger(value) ||
                value < -100 ||
                value > 100
              }
              onClick={() => reorder.mutate(value)}
            >
              Save priority
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
