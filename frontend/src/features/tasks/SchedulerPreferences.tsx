import { Plus, Trash2, Workflow } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../services/api';
import type { ModelCatalogue } from '../../services/models';
import { ModelPicker } from '../ModelPicker';
import type { Json } from '../../services/types';
import { SectionHead } from '../../components/UI';
export const defaultTaskLimits = {
  max_concurrent_jobs: 2,
  api_concurrency: 4,
  local_concurrency: 2,
  per_job_api_concurrency: 2,
  per_model_concurrency: {},
};
export function SchedulerPreferences({
  value,
  onChange,
}: {
  value: Json;
  onChange: (value: Json) => void;
}) {
  const catalogue = useQuery({
    queryKey: ['models', true],
    queryFn: () => api<ModelCatalogue>('/settings/models'),
    enabled: false,
  });
  const data = { ...defaultTaskLimits, ...value };
  const presets = [
    {
      id: 'quiet',
      name: 'Quiet',
      description: 'One course at a time. Lower resource use.',
      limits: {
        max_concurrent_jobs: 1,
        api_concurrency: 2,
        local_concurrency: 1,
        per_job_api_concurrency: 1,
      },
    },
    {
      id: 'balanced',
      name: 'Balanced',
      description: 'Two courses together. Recommended starting point.',
      limits: {
        max_concurrent_jobs: 2,
        api_concurrency: 4,
        local_concurrency: 2,
        per_job_api_concurrency: 2,
      },
    },
    {
      id: 'faster',
      name: 'More parallel work',
      description: 'Up to four courses. Higher simultaneous API usage.',
      limits: {
        max_concurrent_jobs: 4,
        api_concurrency: 8,
        local_concurrency: 2,
        per_job_api_concurrency: 2,
      },
    },
  ];
  const models = (data.per_model_concurrency || {}) as Record<string, number>;
  const update = (key: string, next: unknown) => onChange({ ...data, [key]: next });
  return (
    <section className="panel scheduler-preferences">
      <SectionHead title="Processing speed" action={<Workflow size={21} />}>
        Different courses can progress together. Tasks beyond capacity remain in the persistent
        queue; the same course keeps one active task.
      </SectionHead>
      <div className="settings-preset-grid" aria-label="Processing speed presets">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            aria-pressed={Object.entries(preset.limits).every(
              ([key, count]) => data[key as keyof typeof data] === count,
            )}
            onClick={() => onChange({ ...data, ...preset.limits })}
          >
            <strong>{preset.name}</strong>
            <span>{preset.description}</span>
          </button>
        ))}
      </div>
      <details className="settings-details">
        <summary>Customize shared resource limits</summary>
        <div className="form-grid advanced-limits">
          {[
            ['max_concurrent_jobs', 'Simultaneous course tasks', 8],
            ['api_concurrency', 'Shared OpenAI request limit', 16],
            ['local_concurrency', 'Shared local processing limit', 4],
            ['per_job_api_concurrency', 'OpenAI requests per task', 16],
          ].map(([key, label, max]) => (
            <label key={String(key)}>
              {String(label)}
              <input
                type="number"
                min={1}
                max={Number(max)}
                step={1}
                value={Number(data[String(key) as keyof typeof data])}
                onChange={(e) => update(String(key), Number(e.target.value))}
              />
            </label>
          ))}
        </div>
      </details>
      <p className="field-help">
        Shared limits govern new admissions across all tasks. Lowering a limit lets work already in
        flight finish safely. Per-task workers and context settings below still constrain each
        pipeline.
      </p>
      <details>
        <summary>Optional limits for specific models</summary>
        <p className="field-help">
          A model-specific limit is an additional shared cap. Remove a row to use only the global
          and per-task limits.
        </p>
        {Object.entries(models).map(([model, count], index) => (
          <div className="model-concurrency-row" key={index}>
            <ModelPicker
              label={`Model for limit ${index + 1}`}
              value={model}
              models={catalogue.data?.models || []}
              stage="all"
              onChange={(nextModel) => {
                const next = Object.fromEntries(
                  Object.entries(models).map(([id, limit]) => [
                    id === model ? nextModel : id,
                    limit,
                  ]),
                );
                update('per_model_concurrency', next);
              }}
            />
            <label>
              Concurrent requests
              <input
                type="number"
                aria-label={`Model concurrency ${index + 1}`}
                min={1}
                max={16}
                value={count}
                onChange={(e) =>
                  update('per_model_concurrency', { ...models, [model]: Number(e.target.value) })
                }
              />
            </label>
            <button
              className="icon-button"
              aria-label={`Remove model limit ${model || index + 1}`}
              onClick={() => {
                const next = { ...models };
                delete next[model];
                update('per_model_concurrency', next);
              }}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        <button
          className="button small"
          disabled={Object.hasOwn(models, '')}
          onClick={() => update('per_model_concurrency', { ...models, '': 1 })}
        >
          <Plus size={14} />
          Add model limit
        </button>
      </details>
      <p className="field-help">
        Save preferences to apply these limits. Model rate limits and provider cooldowns can still
        delay requests; available capacity is not a promise of provider throughput.
      </p>
    </section>
  );
}
