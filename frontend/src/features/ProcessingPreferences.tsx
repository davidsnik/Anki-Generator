import { useState } from 'react';
import type { Json } from '../services/types';
import { SectionHead, human } from '../components/UI';
const limits: [string, string, number, number, number, number][] = [
  ['concurrency', 'Independent stage workers per task', 2, 1, 8, 1],
  ['api_concurrency', 'Per-pipeline request limit', 2, 1, 8, 1],
  ['input_token_budget', 'Input tokens per bounded request', 24000, 4000, 128000, 1000],
  ['output_token_budget', 'Output tokens per request', 12000, 1000, 64000, 1000],
  ['coverage_rounds', 'Targeted coverage repair rounds', 1, 0, 3, 1],
  ['coverage_batch_size', 'Coverage targets per batch', 8, 1, 24, 1],
  ['source_chunk_characters', 'Source chunk characters', 10000, 1000, 24000, 1000],
  ['vision_batch_images', 'Images per vision batch', 4, 1, 12, 1],
  ['semantic_candidates', 'Semantic comparison candidates', 12, 2, 50, 1],
  ['embedding_dimensions', 'Embedding dimensions', 512, 64, 3072, 1],
  ['embedding_batch_size', 'Embedding batch size', 32, 1, 128, 1],
  ['identity_similarity', 'Identity similarity threshold', 0.92, 0.8, 1, 0.01],
  ['identity_margin', 'Identity ambiguity margin', 0.07, 0, 0.3, 0.01],
];
const stages = [
  'interpretation',
  'knowledge',
  'consolidation',
  'generation',
  'factual',
  'pedagogical',
  'mathematical',
  'revision',
  'deduplication',
  'coverage',
  'source_audit',
  'source_matching',
  'target_coverage',
  'identity',
];
export function ProcessingPreferences({
  value,
  prompts,
  onChange,
  onPrompts,
}: {
  value: Json;
  prompts: Record<string, string>;
  onChange: (value: Json) => void;
  onPrompts: (value: Record<string, string>) => void;
}) {
  const [stage, setStage] = useState('generation');
  return (
    <section className="panel">
      <SectionHead title="Bounded processing & reproducibility">
        These limits govern independent stages within each task, alongside the shared limits above.
        Each run records its configuration; changing preferences affects new runs.
      </SectionHead>
      <div className="form-grid">
        {limits.map(([key, label, fallback, min, max, step]) => (
          <label key={key}>
            {label}
            <input
              type="number"
              min={min}
              max={
                key === 'embedding_dimensions' && value.embedding_model !== 'text-embedding-3-large'
                  ? 1536
                  : max
              }
              step={step}
              value={Number(value[key] ?? fallback)}
              onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })}
            />
          </label>
        ))}
        <label>
          Semantic embedding model
          <select
            value={String(value.embedding_model ?? 'text-embedding-3-small')}
            onChange={(e) => onChange({ ...value, embedding_model: e.target.value })}
          >
            <option>text-embedding-3-small</option>
            <option>text-embedding-3-large</option>
          </select>
        </label>
      </div>
      <label className="check-label">
        <input
          type="checkbox"
          checked={value.source_audit !== false}
          onChange={(e) => onChange({ ...value, source_audit: e.target.checked })}
        />
        Independently audit source coverage against learning targets
      </label>
      <details>
        <summary>Advanced versioned prompt overrides</summary>
        <p className="field-help">
          An override replaces that stage’s default prompt for new runs. Source material remains
          untrusted data. Empty text restores the default. Save preferences to apply; experiments
          can compare overrides without changing these defaults.
        </p>
        <label>
          Prompt stage
          <select value={stage} onChange={(e) => setStage(e.target.value)}>
            {stages.map((s) => (
              <option key={s} value={s}>
                {human(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Prompt override
          <textarea
            rows={8}
            maxLength={50000}
            value={prompts[stage] ?? ''}
            placeholder="Use the versioned default prompt"
            onChange={(e) => {
              const next = { ...prompts };
              if (e.target.value.trim()) next[stage] = e.target.value;
              else delete next[stage];
              onPrompts(next);
            }}
          />
        </label>
      </details>
      <p className="field-help">
        Higher concurrency can increase simultaneous API usage. Similarity proposes candidates; it
        does not independently establish correctness or permission to replace reviewed content.
      </p>
    </section>
  );
}
