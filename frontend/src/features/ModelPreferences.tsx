import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleCheck, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { ErrorPanel, SectionHead, human } from '../components/UI';
import { api, write } from '../services/api';
import { modelStages } from '../services/models';
import type { ModelCatalogue, ModelValidation } from '../services/models';
import type { Json } from '../services/types';
import { ModelPicker } from './ModelPicker';

export function ModelPreferences({
  value,
  configured,
  onChange,
}: {
  value: Json;
  configured: boolean;
  onChange: (key: string, value: unknown) => void;
}) {
  const client = useQueryClient();
  const [advanced, setAdvanced] = useState(() => {
    const saved = (value.models || {}) as Record<string, string>;
    return modelStages.some(([stage]) => saved[stage] && saved[stage] !== saved.generation);
  });
  const query = useQuery({
    queryKey: ['models', configured],
    queryFn: () => api<ModelCatalogue>('/settings/models'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const refresh = useMutation({
    mutationFn: () => api<ModelCatalogue>('/settings/models?refresh=true'),
    onSuccess: (catalogue) => {
      client.setQueryData(['models', configured], catalogue);
      validate.reset();
    },
  });
  const catalogue = query.data;
  const stageModels = {
    ...catalogue?.defaults,
    ...((value.models || {}) as Record<string, string>),
  };
  const primary = stageModels.generation || catalogue?.recommendation || 'gpt-6-astra';
  const overrides = modelStages.some(
    ([stage]) => stageModels[stage] && stageModels[stage] !== primary,
  );
  const processing = (value.processing || {}) as Json;
  const validate = useMutation({
    mutationFn: () =>
      write<ModelValidation>('/settings/models/validate', {
        models: stageModels,
        reasoning_effort: value.reasoning_effort ?? 'high',
        processing,
      }),
  });
  const resetValidation = validate.reset;
  useEffect(() => {
    resetValidation();
  }, [catalogue?.status, catalogue?.fetched_at, catalogue?.error?.message, resetValidation]);
  const update = (key: string, next: unknown) => {
    validate.reset();
    onChange(key, next);
  };
  const models = catalogue?.models || [];
  const supportedEfforts = modelStages
    .map(
      ([stage]) =>
        models.find((model) => model.id === stageModels[stage])?.capabilities.reasoning_efforts,
    )
    .filter((efforts): efforts is string[] => !!efforts?.length);
  const efforts = ['low', 'medium', 'high', 'xhigh', 'max'].filter((effort) =>
    supportedEfforts.every((supported) => supported.includes(effort)),
  );
  const currentEffort = String(value.reasoning_effort ?? 'high');
  const validationError = catalogue?.error?.message;
  return (
    <section className="panel model-preferences" id="model-preferences">
      <SectionHead title="Models for your courses" action={<Sparkles size={21} />}>
        One model handles documents, card creation and independent review by default. Choose
        stage-specific models only when you need them.
      </SectionHead>
      <div className="model-discovery-status">
        <div role="status">
          {query.isFetching || refresh.isPending
            ? 'Loading models available to your account…'
            : !configured
              ? 'Add an API key above to discover your account’s models.'
              : catalogue?.status === 'ready'
                ? `${models.filter((model) => model.available === true).length} account models · ${catalogue.cached ? 'cached list' : 'refreshed list'}`
                : 'The account model list is unavailable.'}
          {catalogue?.fetched_at && (
            <small>Last checked {new Date(catalogue.fetched_at).toLocaleString()}</small>
          )}
        </div>
        <button
          type="button"
          className="button small"
          onClick={() => refresh.mutate()}
          disabled={!configured || query.isFetching || refresh.isPending}
        >
          <RefreshCw size={14} className={refresh.isPending ? 'spin' : ''} />
          {refresh.isPending ? 'Refreshing…' : 'Refresh models'}
        </button>
      </div>
      {(query.error || refresh.error || validationError) && (
        <ErrorPanel
          error={query.error || refresh.error || validationError}
          retry={configured ? () => refresh.mutate() : undefined}
        />
      )}
      <ModelPicker
        label="Default processing model"
        value={primary}
        models={models}
        stage="interpretation"
        onChange={(model) =>
          update('models', Object.fromEntries(modelStages.map(([stage]) => [stage, model])))
        }
      />
      <p className="field-help">
        Changing the default applies it to all six stages.{' '}
        {overrides
          ? 'Your saved stage-specific choices are currently preserved below.'
          : 'Independent review still uses separate requests and evidence.'}
      </p>
      <details
        open={advanced}
        onToggle={(event) => setAdvanced(event.currentTarget.open)}
        className="settings-details"
      >
        <summary>
          Choose different models by stage{overrides ? ' · custom choices active' : ''}
        </summary>
        <div className="form-grid advanced-models">
          {modelStages.map(([stage, label]) => (
            <ModelPicker
              key={stage}
              label={label}
              value={stageModels[stage] || primary}
              models={models}
              stage={stage}
              onChange={(model) => update('models', { ...stageModels, [stage]: model })}
            />
          ))}
        </div>
      </details>
      <details className="settings-details">
        <summary>Reasoning, revisions & semantic search</summary>
        <div className="form-grid advanced-limits">
          <label>
            Reasoning effort
            <select
              value={currentEffort}
              onChange={(event) => update('reasoning_effort', event.target.value)}
            >
              {!efforts.includes(currentEffort) && (
                <option value={currentEffort}>
                  {human(currentEffort)} · incompatible selection
                </option>
              )}
              {efforts.map((effort) => (
                <option key={effort} value={effort}>
                  {
                    {
                      low: 'Low · quicker',
                      medium: 'Medium · balanced',
                      high: 'High · thorough',
                      xhigh: 'Extra high',
                      max: 'Maximum',
                    }[effort]
                  }
                </option>
              ))}
            </select>
          </label>
          <label>
            Maximum revision attempts
            <select
              value={Number(value.max_revisions ?? 2)}
              onChange={(event) => update('max_revisions', Number(event.target.value))}
            >
              {[0, 1, 2, 3, 4, 5].map((count) => (
                <option value={count} key={count}>
                  {count === 0
                    ? 'No automatic revisions'
                    : `${count} ${count === 1 ? 'attempt' : 'attempts'}${count === 2 ? ' · recommended default' : ''}`}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="field-help">
          Models without adjustable reasoning ignore this setting. More reasoning and revisions can
          increase processing time and API usage; reaching a limit never approves a card.
        </p>
        <ModelPicker
          label="Semantic search model"
          value={String(
            processing.embedding_model ??
              catalogue?.default_embedding_model ??
              'text-embedding-3-small',
          )}
          models={models}
          stage="embeddings"
          onChange={(model) => update('processing', { ...processing, embedding_model: model })}
        />
      </details>
      <div className="model-validation-actions">
        <button
          type="button"
          className="button small"
          disabled={!configured || validate.isPending || query.isFetching}
          onClick={() => validate.mutate()}
        >
          <ShieldCheck size={15} />
          {validate.isPending ? 'Checking models…' : 'Check model setup'}
        </button>
        <span className="field-help">
          Checks account access and documented compatibility without generating cards.
        </span>
      </div>
      {validate.error && <ErrorPanel error={validate.error} />}
      {validate.data && (
        <div
          className={`model-validation ${validate.data.valid ? 'valid' : 'invalid'}`}
          role="status"
        >
          <strong>
            <CircleCheck size={16} />
            {validate.data.valid ? 'Model setup checked' : 'Model setup needs attention'}
          </strong>
          {validate.data.issues.length ? (
            <ul>
              {validate.data.issues.map((issue, index) => (
                <li key={index}>
                  <strong>{human(issue.stage)}:</strong> {issue.message}
                </li>
              ))}
            </ul>
          ) : (
            <p>Selected models are available and their required capabilities are documented.</p>
          )}
        </div>
      )}
      <p className="field-help model-catalogue-note">
        {catalogue?.notice ||
          'The account list shows access, not capabilities or prices. Task labels come from a maintained, dated documentation catalogue. Unrecognized models remain explicitly unverified.'}
      </p>
    </section>
  );
}
