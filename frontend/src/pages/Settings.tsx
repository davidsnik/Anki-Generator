import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  Database,
  Download,
  Eye,
  EyeOff,
  FlaskConical,
  KeyRound,
  LockKeyhole,
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
import { ModelPreferences } from '../features/ModelPreferences';
import { generationPresets } from '../services/generationPresets';
import { api, downloadBackup, write } from '../services/api';
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
      test.reset();
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
      test.reset();
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
  const storageLabels: Record<string, string> = {
    session: 'Until this application closes',
    keyring: 'Saved securely on this computer',
    environment: 'Provided by your environment',
  };
  return (
    <div className="key-setup">
      <div className="key-status">
        <Badge tone={status.configured ? 'green' : 'amber'}>
          <span className="status-dot" />
          {status.configured ? 'Key configured' : 'No API key configured'}
        </Badge>
        {full.storage && full.storage !== 'none' && (
          <span className="muted">{storageLabels[full.storage] || 'Stored securely'}</span>
        )}
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
            onChange={(e) => {
              setKey(e.target.value);
              test.reset();
            }}
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
        {full.persistent_available || status.secure_storage_available
          ? 'Optional: save securely in your operating system’s credential store so you can reconnect next time.'
          : 'Your key stays in memory until the application closes. A secure system credential store is not available in this session.'}
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
      {test.data && (
        <p className="key-connection-result" role="status" data-ok={test.data.ok}>
          {test.data.ok ? 'Connected. ' : 'Connection needs attention. '}
          {test.data.message}
        </p>
      )}
      {!status.configured && (
        <p className="field-help">
          Get a key from your OpenAI API account. API usage is billed separately from a ChatGPT
          subscription. You can import, inspect, edit and export your material without connecting.
        </p>
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
export function CriteriaForm({
  value,
  onChange,
  compact = false,
}: {
  value: Json;
  onChange: (v: Json) => void;
  compact?: boolean;
}) {
  const [advanced, setAdvanced] = useState(!compact);
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
      <details
        open={advanced}
        onToggle={(event) => setAdvanced(event.currentTarget.open)}
        className="settings-details"
      >
        <summary>Customize subjects, card styles & examples</summary>
        <div className="range-grid advanced-limits">
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
                  disabled={
                    (data.card_types as string[]).length === 1 &&
                    (data.card_types as string[]).includes(type)
                  }
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
      </details>
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
  const client = useQueryClient();
  const draft = client.getQueryData<{ settings: Json; baseline: string }>(['settings-draft']);
  const [settings, setSettings] = useState<Json>(draft?.settings ?? bootstrap.settings);
  const [baseline, setBaseline] = useState(draft?.baseline ?? JSON.stringify(bootstrap.settings));
  const baselineRef = useRef(baseline);
  const toast = useToast();
  const dirty = JSON.stringify(settings) !== baseline;
  useEffect(() => {
    client.setQueryDefaults(['settings-draft'], { gcTime: Infinity });
    client.setQueryData(['settings-draft'], { settings, baseline });
  }, [client, settings, baseline]);
  useEffect(() => {
    setSettings((current) =>
      JSON.stringify(current) === baselineRef.current ? bootstrap.settings : current,
    );
    if (!dirty) {
      const next = JSON.stringify(bootstrap.settings);
      baselineRef.current = next;
      setBaseline(next);
    }
    // Background bootstrap refreshes must never replace an edited form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootstrap.settings]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const save = useMutation({
    mutationFn: (snapshot: Json) => write('/settings', snapshot, 'PATCH'),
    onSuccess: (_, snapshot) => {
      const next = JSON.stringify(snapshot);
      baselineRef.current = next;
      setBaseline(next);
      void client.invalidateQueries({ queryKey: ['bootstrap'] });
      toast('Workspace preferences saved. New runs will use these choices.');
    },
  });
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        if (dirty && !save.isPending) save.mutate(settings);
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [dirty, save, settings]);
  const backup = useMutation({
    mutationFn: downloadBackup,
    onSuccess: () => toast('Data backup downloaded.'),
  });
  const update = (key: string, value: unknown) => {
    setSettings((current) => ({ ...current, [key]: value }));
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
  const discard = () => {
    const saved = JSON.parse(baseline) as Json;
    setSettings(saved);
    const theme = String(saved.theme || 'system');
    const resolved =
      theme === 'system'
        ? matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light'
        : theme;
    document.documentElement.dataset.theme = resolved;
    localStorage.setItem('anki-theme', resolved);
    window.dispatchEvent(new CustomEvent('anki-theme-change', { detail: resolved }));
  };
  const role = (settings.role_influence || {}) as Record<string, number>;
  const extraction = (settings.extraction || {}) as Record<string, number>;
  const saveButton = (
    <button
      className="button primary"
      onClick={() => save.mutate(settings)}
      disabled={!dirty || save.isPending}
    >
      <Save size={16} />
      {save.isPending ? 'Saving…' : 'Save preferences'}
    </button>
  );
  return (
    <>
      <PageTitle
        eyebrow="YOUR WORKSPACE"
        title="Settings"
        description="Connect OpenAI, choose your study preferences and keep your courses safe."
        actions={saveButton}
      />
      <nav className="settings-shortcuts" aria-label="Settings sections">
        <a href="#openai-connection">OpenAI connection</a>
        <a href="#model-preferences">Models</a>
        <a href="#generation-defaults">Study preferences</a>
        <a href="#data-storage">Backups & storage</a>
      </nav>
      {save.error && <ErrorPanel error={save.error} />}
      <div className="settings-layout">
        <div className="settings-main">
          <section className="panel" id="openai-connection">
            <SectionHead title="OpenAI connection" action={<KeyRound size={21} />}>
              Connect once to use AI generation and verification. Your key stays on the local
              processing service; each run asks before sending course material.
            </SectionHead>
            <KeySetup status={bootstrap.key_status} />
          </section>
          <ModelPreferences
            value={settings}
            configured={bootstrap.key_status.configured}
            onChange={update}
          />
          <section className="panel" id="generation-defaults">
            <SectionHead title="Default study preferences" action={<SlidersHorizontal size={21} />}>
              Choose a starting point for new courses. You can tailor these preferences in each
              course.
            </SectionHead>
            <CriteriaForm
              value={(settings.criteria || {}) as Json}
              onChange={(value) => update('criteria', value)}
              compact
            />
          </section>
          <SchedulerPreferences
            value={(settings.tasks || {}) as Json}
            onChange={(value) => update('tasks', value)}
          />
          <details className="panel settings-advanced-section">
            <summary className="settings-section-summary">
              <SectionHead title="Source importance">
                Choose how lecture material, exercises and other sources influence coverage.
              </SectionHead>
            </summary>
            <div className="settings-section-content">
              <p className="field-help">
                Normal influence (1×) is a balanced starting point. Higher values give a source role
                more emphasis; they never establish correctness.
              </p>
              <div className="range-grid">
                {(
                  [
                    ['lecture', 'Lecture material'],
                    ['personal_notes', 'Personal notes'],
                    ['exercises', 'Exercises'],
                    ['solutions', 'Worked solutions'],
                    ['reference', 'Other references'],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <span className="range-control">
                      <input
                        type="range"
                        min="0"
                        max="3"
                        step="0.1"
                        value={role[key] ?? 1}
                        onChange={(event) =>
                          update('role_influence', { ...role, [key]: Number(event.target.value) })
                        }
                      />
                      <output>{(role[key] ?? 1).toFixed(1)}×</output>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </details>
          <details className="panel settings-advanced-section">
            <summary className="settings-section-summary">
              <SectionHead title="Document processing">
                Standard extraction works for most PDFs, scans and notes.
              </SectionHead>
            </summary>
            <div className="settings-section-content">
              <label>
                Page image quality
                <select
                  value={extraction.render_dpi ?? 144}
                  onChange={(event) =>
                    update('extraction', { ...extraction, render_dpi: Number(event.target.value) })
                  }
                >
                  {![96, 144, 200, 300].includes(extraction.render_dpi ?? 144) && (
                    <option value={extraction.render_dpi}>
                      {extraction.render_dpi} DPI · custom
                    </option>
                  )}
                  <option value="96">Compact · smaller images</option>
                  <option value="144">Standard · recommended</option>
                  <option value="200">Detailed · small text and notation</option>
                  <option value="300">Maximum · larger files</option>
                </select>
              </label>
              <p className="field-help">
                Very tall pages are split into overlapping images. Unclear extraction stays visible
                for review. Higher image quality uses more memory and storage.
              </p>
              <details className="settings-details">
                <summary>Advanced extraction limits</summary>
                <div className="form-grid advanced-limits">
                  <label>
                    Maximum pages per file
                    <input
                      type="number"
                      min="1"
                      max="10000"
                      value={extraction.max_pages ?? 2000}
                      onChange={(event) =>
                        update('extraction', {
                          ...extraction,
                          max_pages: Number(event.target.value),
                        })
                      }
                    />
                  </label>
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
                          onChange={(event) =>
                            update('extraction', {
                              ...extraction,
                              [key]: Number(event.target.value),
                            })
                          }
                        />
                      </label>
                    ))}
                </div>
              </details>
            </div>
          </details>
          <ProcessingPreferences
            value={(settings.processing || {}) as Json}
            prompts={(settings.prompt_overrides || {}) as Record<string, string>}
            onChange={(value) => update('processing', value)}
            onPrompts={(value) => update('prompt_overrides', value)}
          />
        </div>
        <aside className="settings-aside">
          <section className="panel">
            <div className="aside-icon">
              <ShieldCheck />
            </div>
            <h3>Your material, your choice</h3>
            <p className="muted">
              AI processing may send source text, metadata and page images to OpenAI. Each run asks
              for your consent.
            </p>
            <p className="muted">
              Importing, inspecting, editing, human review and export work locally without sending
              course material.
            </p>
          </section>
          <section className="panel" id="data-storage">
            <SectionHead title="Appearance" />
            <label>
              Color theme
              <select
                aria-label="Color theme"
                value={String(settings.theme || 'system')}
                onChange={(event) => update('theme', event.target.value)}
              >
                <option value="system">Follow system</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </label>
            <hr />
            <SectionHead title="Data & storage" action={<Database size={19} />} />
            <p className="muted">
              Create a private backup of your courses, original documents, revisions and
              preferences. API keys are excluded.
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
          <details className="panel diagnostics">
            <summary className="settings-section-summary">
              <SectionHead title="Troubleshooting details" />
            </summary>
            <div className="settings-section-content">
              {Object.entries(bootstrap.diagnostics || {}).map(([key, value]) => (
                <div key={key}>
                  <span>{human(key)}</span>
                  <code>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</code>
                </div>
              ))}
              <p className="field-help">Diagnostics exclude API secrets and document contents.</p>
            </div>
          </details>
        </aside>
      </div>
      {dirty && (
        <div className="settings-save-bar" role="status">
          <div>
            <strong>You have unsaved preferences</strong>
            <p>
              Your draft stays here when you switch pages. Save to apply it to new runs. Ctrl/Cmd+S
              saves.
            </p>
          </div>
          <div className="inline-actions">
            <button className="button" disabled={save.isPending} onClick={discard}>
              Discard changes
            </button>
            {saveButton}
          </div>
        </div>
      )}
    </>
  );
}
