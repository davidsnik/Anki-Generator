import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  Database,
  Download,
  Eye,
  EyeOff,
  FlaskConical,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react';
import type { Bootstrap, Json, KeyStatus } from '../services/types';
import { SchedulerPreferences } from '../features/tasks/SchedulerPreferences';
import { ProcessingPreferences } from '../features/ProcessingPreferences';
import { BackupRestore } from '../features/BackupRestore';
import { DesktopPanel } from '../features/Desktop';
import { generationPresets } from '../services/generationPresets';
import { api, downloadBackup, list, write } from '../services/api';
import {
  Badge,
  Confirm,
  ErrorPanel,
  human,
  PageTitle,
  SectionHead,
  useToast,
} from '../components/UI';
export function KeySetup({ status }: { status: KeyStatus }) {
  const [key, setKey] = useState('');
  const [persist, setPersist] = useState(false);
  const [visible, setVisible] = useState(false);
  const [remove, setRemove] = useState(false);
  const client = useQueryClient();
  const toast = useToast();
  const set = useMutation({
    mutationFn: () => write('/settings/key', { api_key: key, persist }, 'PUT'),
    onSuccess: () => {
      setKey('');
      client.invalidateQueries();
      toast('API key configured securely.');
    },
  });
  const test = useMutation({
    mutationFn: () => write<{ ok: boolean; message: string }>('/settings/test'),
    onSuccess: (result) => toast(result.message, result.ok ? 'success' : 'error'),
  });
  const del = useMutation({
    mutationFn: () => api('/settings/key', { method: 'DELETE' }),
    onSuccess: () => {
      client.invalidateQueries();
      setRemove(false);
      toast('Stored API key removed.');
    },
  });
  const full = status as KeyStatus & {
    storage?: string;
    persistent_available?: boolean;
    notice?: string;
  };
  return (
    <div className="key-setup">
      <div className="key-status">
        <Badge tone={status.configured ? 'green' : 'amber'}>
          <span className="status-dot" />
          {status.configured ? 'Key configured' : 'No API key configured'}
        </Badge>
        {full.storage && <span className="muted">{full.storage} storage</span>}
      </div>
      <label htmlFor="api-key">
        OpenAI API key
        <div className="password-input">
          <KeyRound size={17} />
          <input
            id="api-key"
            autoComplete="off"
            type={visible ? 'text' : 'password'}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={status.configured ? 'Enter a new key to replace the current one' : 'sk-…'}
          />
          <button
            className="icon-button"
            aria-label={visible ? 'Hide API key' : 'Show API key'}
            onClick={() => setVisible(!visible)}
          >
            {visible ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </div>
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          disabled={!full.persistent_available && !status.secure_storage_available}
          checked={persist}
          onChange={(e) => setPersist(e.target.checked)}
        />{' '}
        Save in the system credential store
      </label>
      <p className="field-help">
        <LockKeyhole size={13} />
        {full.notice ||
          status.message ||
          'Keys are held in server memory for this session. Persistent storage is available only with a secure system keyring.'}
      </p>
      <div className="inline-actions wrap">
        <button
          className="button primary"
          disabled={!key.trim() || set.isPending}
          onClick={() => set.mutate()}
        >
          <Check size={15} />
          {set.isPending ? 'Saving…' : 'Save API key'}
        </button>
        <button
          className="button"
          disabled={!status.configured || test.isPending}
          onClick={() => test.mutate()}
        >
          <FlaskConical size={15} />
          {test.isPending ? 'Testing…' : 'Test connection'}
        </button>
        {status.configured && (
          <button className="button text-danger" onClick={() => setRemove(true)}>
            <Trash2 size={15} />
            Remove
          </button>
        )}
      </div>
      {(set.error || test.error || del.error) && (
        <ErrorPanel error={set.error || test.error || del.error} />
      )}
      <p className="field-help">
        Connection testing sends a small test request to OpenAI and may incur API usage. Course
        documents are never sent by this action.
      </p>
      {remove && (
        <Confirm
          title="Remove your API key?"
          onClose={() => setRemove(false)}
          onConfirm={() => del.mutate()}
        >
          Future processing will require a new key. Your courses and cards will remain available.
        </Confirm>
      )}
    </div>
  );
}
const defaultCriteria: Json = {
  coverage: 'comprehensive',
  theory_emphasis: 1,
  methods_emphasis: 1,
  conceptual_emphasis: 1,
  card_types: ['basic', 'cloze'],
  answer_detail: 'concise',
  include_explanations: true,
  proof_treatment: 'key_steps',
  example_treatment: 'transfer',
  include_diagrams: true,
  topic_exclusions: [],
  instructions: '',
};
export function CriteriaForm({ value, onChange }: { value: Json; onChange: (v: Json) => void }) {
  const data = { ...defaultCriteria, ...value };
  const update = (key: string, v: unknown) => onChange({ ...data, [key]: v });
  const selectedPreset = generationPresets.find((preset) =>
    Object.entries(preset.criteria).every(
      ([key, value]) => JSON.stringify(data[key]) === JSON.stringify(value),
    ),
  );
  return (
    <>
      <div className="criteria-presets" aria-label="Generation presets">
        {generationPresets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className={selectedPreset?.id === preset.id ? 'selected' : ''}
            aria-label={preset.name}
            aria-pressed={selectedPreset?.id === preset.id}
            onClick={() =>
              onChange({
                ...data,
                ...preset.criteria,
                instructions: data.instructions,
                topic_exclusions: data.topic_exclusions,
              })
            }
          >
            <strong>{preset.name}</strong>
            <span>{preset.description}</span>
          </button>
        ))}
      </div>
      <p className="field-help">
        Choose a starting point, then tailor the criteria below. Your custom guidance and excluded
        topics stay in place. Use Save to apply these preferences.
      </p>
      <div className="form-grid">
        <label>
          Coverage level
          <select
            value={String(data.coverage)}
            onChange={(e) => update('coverage', e.target.value)}
          >
            <option value="comprehensive">Comprehensive exam preparation</option>
            <option value="balanced">Balanced understanding</option>
            <option value="focused">Essential concepts</option>
          </select>
        </label>
        <label>
          Answer detail
          <select
            value={String(data.answer_detail)}
            onChange={(e) => update('answer_detail', e.target.value)}
          >
            <option value="concise">Concise, with necessary assumptions</option>
            <option value="balanced">Balanced</option>
            <option value="detailed">Detailed</option>
          </select>
        </label>
      </div>
      <div className="range-grid">
        {[
          ['theory_emphasis', 'Theory & definitions'],
          ['methods_emphasis', 'Problem-solving methods'],
          ['conceptual_emphasis', 'Conceptual understanding'],
        ].map(([key, label]) => (
          <label key={key}>
            {label}
            <span className="range-control">
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={Number(data[key])}
                onChange={(e) => update(key, Number(e.target.value))}
              />
              <output>{Number(data[key]).toFixed(1)}×</output>
            </span>
          </label>
        ))}
      </div>
      <div className="form-grid">
        <label>
          Proof treatment
          <select
            value={String(data.proof_treatment)}
            onChange={(e) => update('proof_treatment', e.target.value)}
          >
            <option value="key_steps">Key steps & proof techniques</option>
            <option value="strategies">Proof strategies</option>
            <option value="exclude">Exclude proof recall</option>
          </select>
        </label>
        <label>
          Example treatment
          <select
            value={String(data.example_treatment)}
            onChange={(e) => update('example_treatment', e.target.value)}
          >
            <option value="transfer">Transferable applications</option>
            <option value="include">Illustrative examples</option>
            <option value="exclude">Exclude examples</option>
          </select>
        </label>
      </div>
      <label>
        Preferred card types
        <div className="checkbox-row">
          {['basic', 'cloze'].map((type) => (
            <label key={type} className="check-label">
              <input
                type="checkbox"
                checked={(data.card_types as string[]).includes(type)}
                onChange={(e) =>
                  update(
                    'card_types',
                    e.target.checked
                      ? [...(data.card_types as string[]), type]
                      : (data.card_types as string[]).filter((t) => t !== type),
                  )
                }
              />
              {type}
            </label>
          ))}
        </div>
      </label>
      <div className="checkbox-row">
        <label className="check-label">
          <input
            type="checkbox"
            checked={!!data.include_explanations}
            onChange={(e) => update('include_explanations', e.target.checked)}
          />{' '}
          Include explanations
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={!!data.include_diagrams}
            onChange={(e) => update('include_diagrams', e.target.checked)}
          />{' '}
          Preserve useful source diagrams
        </label>
      </div>
      <label>
        Topic exclusions
        <input
          value={(data.topic_exclusions as string[]).join(', ')}
          onChange={(e) =>
            update(
              'topic_exclusions',
              e.target.value
                .split(',')
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
          placeholder="Separate topics with commas"
        />
      </label>
      <label>
        Custom generation guidance
        <textarea
          rows={4}
          value={String(data.instructions || '')}
          onChange={(e) => update('instructions', e.target.value)}
          placeholder="e.g. Emphasize when a theorem applies. Include the assumptions and focus on recurring exercise techniques."
        />
      </label>
      <p className="field-help">
        Preferences guide generation. Evidence requirements and factual verification always remain
        in effect.
      </p>
    </>
  );
}
export function SettingsPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const [settings, setSettings] = useState<Json>(bootstrap.settings);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const client = useQueryClient();
  const toast = useToast();
  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => api<unknown>('/settings/models'),
    enabled: modelsLoaded,
    retry: false,
  });
  const save = useMutation({
    mutationFn: () => write('/settings', settings, 'PATCH'),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Workspace preferences saved.');
    },
  });
  const backup = useMutation({
    mutationFn: downloadBackup,
    onSuccess: () => toast('Data backup downloaded.'),
  });
  const update = (key: string, value: unknown) => {
    setSettings({ ...settings, [key]: value });
    if (key === 'theme') {
      const resolved =
        value === 'system'
          ? matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light'
          : String(value);
      document.documentElement.dataset.theme = resolved;
      localStorage.setItem('anki-theme', resolved);
      window.dispatchEvent(new CustomEvent('anki-theme-change', { detail: resolved }));
    }
  };
  const stageModels = (settings.models || {}) as Record<string, string>;
  const choices = list<{ id: string } | string>(models.data).map((m) =>
    typeof m === 'string' ? m : m.id,
  );
  const role = (settings.role_influence || {}) as Record<string, number>;
  const extraction = (settings.extraction || {}) as Record<string, number>;
  return (
    <>
      <PageTitle
        eyebrow="MAKE IT YOURS"
        title="A workspace that thinks with you."
        description="Connect your models, refine your criteria, and keep your knowledge safely in your hands."
        actions={
          <button
            className="button primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            <Save size={16} />
            {save.isPending ? 'Saving…' : 'Save preferences'}
          </button>
        }
      />
      {save.error && <ErrorPanel error={save.error} />}
      <div className="settings-layout">
        <div className="settings-main">
          <section className="panel">
            <SectionHead title="OpenAI connection" action={<KeyRound size={21} />}>
              Your key stays on the local backend. Only configured processing runs send course
              material.
            </SectionHead>
            <KeySetup status={bootstrap.key_status} />
          </section>
          <section className="panel">
            <SectionHead
              title="A specialist for every stage"
              action={
                <button
                  className="button small"
                  onClick={() => {
                    setModelsLoaded(true);
                    models.refetch();
                  }}
                  disabled={models.isFetching}
                >
                  <RefreshCw size={14} /> {models.isFetching ? 'Discovering…' : 'Discover models'}
                </button>
              }
            >
              Select models available to your account. Capability errors are reported by the
              processing pipeline.
            </SectionHead>
            <datalist id="model-options">
              {choices.map((id) => (
                <option value={id} key={id} />
              ))}
            </datalist>
            <div className="form-grid">
              {[
                ['interpretation', 'Document interpretation'],
                ['knowledge', 'Knowledge extraction'],
                ['generation', 'Flashcard generation'],
                ['factual', 'Factual verification'],
                ['pedagogical', 'Pedagogical review'],
                ['coverage', 'Coverage review'],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    list="model-options"
                    value={stageModels[key] ?? ''}
                    onChange={(e) => update('models', { ...stageModels, [key]: e.target.value })}
                    placeholder="Choose a supported model ID"
                  />
                </label>
              ))}
              <label>
                Reasoning effort
                <select
                  value={String(settings.reasoning_effort ?? 'high')}
                  onChange={(e) => update('reasoning_effort', e.target.value)}
                >
                  {['low', 'medium', 'high', 'xhigh', 'max'].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                Maximum revision attempts
                <input
                  type="number"
                  min="0"
                  max="5"
                  value={Number(settings.max_revisions ?? 2)}
                  onChange={(e) => update('max_revisions', Number(e.target.value))}
                />
              </label>
            </div>
            {models.error && <ErrorPanel error={models.error} />}
          </section>
          <SchedulerPreferences
            value={(settings.tasks || {}) as Json}
            onChange={(value) => update('tasks', value)}
          />
          <ProcessingPreferences
            value={(settings.processing || {}) as Json}
            prompts={(settings.prompt_overrides || {}) as Record<string, string>}
            onChange={(value) => update('processing', value)}
            onPrompts={(value) => update('prompt_overrides', value)}
          />
          <section className="panel">
            <SectionHead title="Thoughtful by default" action={<SlidersHorizontal size={21} />}>
              Default generation criteria for your courses.
            </SectionHead>
            <CriteriaForm
              value={(settings.criteria || {}) as Json}
              onChange={(v) => update('criteria', v)}
            />
          </section>
          <section className="panel">
            <SectionHead title="How sources shape the deck">
              Source influence guides importance; it never establishes correctness on its own.
            </SectionHead>
            <div className="form-grid">
              {[
                ['lecture', 'Lecture material'],
                ['personal_notes', 'Personal notes'],
                ['exercises', 'Exercises'],
                ['solutions', 'Worked solutions'],
                ['reference', 'Other references'],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    min="0"
                    max="3"
                    step="0.1"
                    value={role[key] ?? 1}
                    onChange={(e) =>
                      update('role_influence', { ...role, [key]: Number(e.target.value) })
                    }
                  />
                </label>
              ))}
            </div>
          </section>
          <section className="panel">
            <SectionHead title="Document processing" />
            <div className="form-grid">
              <label>
                Rendering resolution (DPI)
                <input
                  type="number"
                  min="72"
                  max="300"
                  value={extraction.render_dpi ?? 144}
                  onChange={(e) =>
                    update('extraction', { ...extraction, render_dpi: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Maximum pages per file
                <input
                  type="number"
                  min="1"
                  max="10000"
                  value={extraction.max_pages ?? 2000}
                  onChange={(e) =>
                    update('extraction', { ...extraction, max_pages: Number(e.target.value) })
                  }
                />
              </label>
            </div>
            <details>
              <summary>Advanced extraction resource limits</summary>
              <div className="form-grid advanced-limits">
                {Object.entries(extraction)
                  .filter(([key]) => !['render_dpi', 'max_pages'].includes(key))
                  .map(([key, value]) => (
                    <label key={key}>
                      {human(key)}
                      <input
                        type="number"
                        min={key === 'overlap_points' ? 0 : 1}
                        step={key === 'worker_timeout_seconds' ? 'any' : '1'}
                        value={value}
                        onChange={(e) =>
                          update('extraction', { ...extraction, [key]: Number(e.target.value) })
                        }
                      />
                    </label>
                  ))}
              </div>
            </details>
            <p className="field-help">
              Very tall pages are rendered in overlapping segments. Ambiguous extraction stays
              visible for review.
            </p>
          </section>
        </div>
        <aside className="settings-aside">
          <section className="panel">
            <div className="aside-icon">
              <ShieldCheck />
            </div>
            <h3>Your material, your choice</h3>
            <p className="muted">
              A generation run can send extracted text, source metadata, semantic embedding inputs
              and rendered source regions to OpenAI. Each run asks for explicit consent.
            </p>
            <p className="muted">
              Local extraction, browsing, editing, review, and export work without transmitting
              course material.
            </p>
          </section>
          <section className="panel">
            <SectionHead title="Appearance" />
            <label>
              Color theme
              <select
                value={String(settings.theme || 'system')}
                onChange={(e) => update('theme', e.target.value)}
              >
                <option value="system">Follow system</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </label>
            <hr />
            <SectionHead title="Data & storage" action={<Database size={19} />} />
            <p className="muted">
              Back up your courses, original documents, revisions, and settings. API keys are
              excluded.
            </p>
            <button className="button" onClick={() => backup.mutate()} disabled={backup.isPending}>
              <Download size={16} />
              {backup.isPending ? 'Preparing backup…' : 'Create data backup'}
            </button>
            {backup.error && <ErrorPanel error={backup.error} />}
            <hr />
            <BackupRestore />
          </section>
          <DesktopPanel />
          <section className="panel diagnostics">
            <SectionHead title="Diagnostics" />
            {Object.entries(bootstrap.diagnostics || {}).map(([key, value]) => (
              <div key={key}>
                <span>{key.replace(/_/g, ' ')}</span>
                <code>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</code>
              </div>
            ))}
            <p className="field-help">Diagnostics exclude API secrets and document contents.</p>
          </section>
        </aside>
      </div>
    </>
  );
}
