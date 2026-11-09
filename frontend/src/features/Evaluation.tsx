import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FlaskConical,
  Plus,
  Download,
  Upload,
  Save,
  EyeOff,
  CheckCheck,
  BookOpen,
} from 'lucide-react';
import { api, write, list } from '../services/api';
import type { Bootstrap, Card, Json, Source } from '../services/types';
import {
  Badge,
  Empty,
  ErrorPanel,
  Loading,
  Modal,
  PageTitle,
  SectionHead,
  human,
  useToast,
  formatDate,
} from '../components/UI';
import { MathText } from '../components/MathText';
import { Pagination } from './Pagination';
import type { PageResult } from './Pagination';
import { SourcePreview } from '../pages/Documents';
interface Dataset extends Json {
  id: string;
  name: string;
  description: string;
  course_id?: string;
  provenance: string;
  reference_concepts: Json[];
  reference_cards: Json[];
  annotations: Json[];
}
interface Experiment extends Json {
  id: string;
  name: string;
  status?: string;
  dataset_id: string;
  created_at?: string;
  report?: Json;
  metrics?: Json;
  variants?: Json[];
}
const datasetKeys = [
  'schema_version',
  'name',
  'description',
  'course_id',
  'provenance',
  'reference_concepts',
  'reference_cards',
  'annotations',
  'sources',
  'reviewer',
  'version',
];
export function datasetPayload(value: Json) {
  return Object.fromEntries(Object.entries(value).filter(([key]) => datasetKeys.includes(key)));
}
interface EvaluationCase extends Json {
  case_id: string;
  card?: Card;
  snapshot?: Card;
  judgment?: Json;
  label?: string;
}
const labels = [
  ['correct_useful', 'Correct and useful'],
  ['needs_improvement', 'Correct, needs improvement'],
  ['incorrect', 'Incorrect'],
  ['ambiguous', 'Ambiguous'],
  ['redundant', 'Redundant'],
  ['not_worth_memorizing', 'Not worth memorizing'],
];
export function EvaluationPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const [dataset, setDataset] = useState<Dataset | 'new' | null>(null);
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [createRun, setCreateRun] = useState<Dataset | null>(null);
  const client = useQueryClient();
  const toast = useToast();
  const datasets = useQuery({
    queryKey: ['evaluation-datasets'],
    queryFn: async () => list<Dataset>(await api('/evaluations/datasets')),
  });
  const experiments = useQuery({
    queryKey: ['evaluation-experiments'],
    queryFn: async () => list<Experiment>(await api('/evaluations/experiments')),
    refetchInterval: 5000,
  });
  const importing = useMutation({
    mutationFn: (data: unknown) => write('/evaluations/datasets/import', data),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Benchmark dataset imported. Review its provenance before drawing conclusions.');
    },
  });
  async function importFile(file?: File) {
    if (!file) return;
    try {
      importing.mutate(JSON.parse(await file.text()));
    } catch {
      toast('Choose a valid evaluation dataset JSON file.', 'error');
    }
  }
  return (
    <>
      <PageTitle
        eyebrow="EVIDENCE OVER CONFIDENCE"
        title="Measure what your cards really teach."
        description="Reproducible experiments, independent human judgments, and explicit unknowns. Model opinions remain separate from reference evidence."
        actions={
          <button className="button primary" onClick={() => setDataset('new')}>
            <Plus size={16} />
            Create benchmark
          </button>
        }
      />
      <div className="inline-note">
        <FlaskConical size={20} />
        <span>
          Synthetic fixtures demonstrate the evaluation machinery. Only independently reviewed
          labels establish human-validated quality; unreviewed cards stay in the denominator.
        </span>
      </div>
      <SectionHead
        title="Benchmark datasets"
        action={
          <label className="button small file-button">
            <Upload size={14} />
            Import dataset
            <input
              type="file"
              hidden
              accept=".json"
              onChange={(e) => {
                importFile(e.target.files?.[0]);
                e.target.value = '';
              }}
            />
          </label>
        }
      />
      {importing.error && <ErrorPanel error={importing.error} />}
      <div className="evaluation-datasets">
        {datasets.isPending ? (
          <Loading />
        ) : datasets.error ? (
          <ErrorPanel error={datasets.error} />
        ) : datasets.data.length ? (
          datasets.data.map((item) => (
            <section className="panel" key={item.id}>
              <div className="section-head">
                <h3>{item.name}</h3>
                <Badge tone={item.provenance === 'human_reference' ? 'green' : 'amber'}>
                  {human(item.provenance)}
                </Badge>
              </div>
              <p className="muted">
                {item.description ||
                  'A versioned inventory of targets, examples, and interpretation annotations.'}
              </p>
              <div className="course-stats">
                <span>{item.reference_concepts?.length ?? 0} reference targets</span>
                <span>{item.reference_cards?.length ?? 0} example cards</span>
              </div>
              <div className="inline-actions wrap">
                <button className="button small" onClick={() => setDataset(item)}>
                  Maintain dataset
                </button>
                <button className="button primary small" onClick={() => setCreateRun(item)}>
                  <FlaskConical size={14} />
                  Compare configurations
                </button>
                <a className="button small" href={`/api/evaluations/datasets/${item.id}/export`}>
                  <Download size={14} />
                  Export
                </a>
              </div>
            </section>
          ))
        ) : (
          <Empty icon={BookOpen} title="Start with the things students should know">
            Link a course, annotate important targets, and preserve good and deliberately flawed
            card examples.
          </Empty>
        )}
      </div>
      <SectionHead title="Evaluation experiments" />
      <section className="panel">
        {experiments.isPending ? (
          <Loading />
        ) : experiments.error ? (
          <ErrorPanel error={experiments.error} />
        ) : experiments.data.length ? (
          <div className="activity-list">
            {experiments.data.map((item) => (
              <button className="experiment-row" key={item.id} onClick={() => setExperiment(item)}>
                <FlaskConical size={20} />
                <div>
                  <strong>{item.name}</strong>
                  <small>{formatDate(item.created_at)}</small>
                </div>
                <Badge>{human(item.status || 'recorded')}</Badge>
                <span>Inspect report →</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">
            Run paired configurations against the same source versions. Each experiment retains its
            settings and card snapshots.
          </p>
        )}
      </section>
      {dataset && (
        <DatasetEditor
          dataset={dataset === 'new' ? undefined : dataset}
          courses={bootstrap.courses}
          onClose={() => setDataset(null)}
        />
      )}{' '}
      {createRun && (
        <ExperimentDialog
          dataset={createRun}
          courses={bootstrap.courses}
          onClose={() => setCreateRun(null)}
          onCreated={(value) => {
            setCreateRun(null);
            setExperiment(value);
          }}
        />
      )}
      {experiment && (
        <ExperimentReport experiment={experiment} onClose={() => setExperiment(null)} />
      )}
    </>
  );
}
function DatasetEditor({
  dataset,
  courses,
  onClose,
}: {
  dataset?: Dataset;
  courses: Bootstrap['courses'];
  onClose: () => void;
}) {
  const [value, setValue] = useState<Json>(
    dataset || {
      name: '',
      description: '',
      course_id: courses[0]?.id || null,
      provenance: 'unreviewed',
      reference_concepts: [],
      reference_cards: [],
      annotations: [],
    },
  );
  const [annotation, setAnnotation] = useState<Json>({
    kind: 'missing_concept',
    label: '',
    expected: '',
    actual: '',
    rationale: '',
    source: {},
  });
  const client = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () =>
      write(
        dataset ? `/evaluations/datasets/${dataset.id}` : '/evaluations/datasets',
        { ...datasetPayload(value), ...(dataset ? { expected_version: dataset.version } : {}) },
        dataset ? 'PATCH' : 'POST',
      ),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Reference dataset saved with its declared provenance.');
      onClose();
    },
  });
  const annotate = useMutation({
    mutationFn: () => write(`/evaluations/datasets/${dataset!.id}/annotations`, annotation),
    onSuccess: () => {
      client.invalidateQueries();
      setAnnotation({ ...annotation, label: '', expected: '', actual: '', rationale: '' });
      toast('Reference annotation recorded.');
    },
  });
  const targets = (value.reference_concepts || []) as Json[];
  const examples = (value.reference_cards || []) as Json[];
  function updateTarget(index: number, key: string, data: unknown) {
    setValue({
      ...value,
      reference_concepts: targets.map((v, i) => (i === index ? { ...v, [key]: data } : v)),
    });
  }
  function updateExample(index: number, changes: Json) {
    setValue({
      ...value,
      reference_cards: examples.map((example, i) =>
        i === index ? { ...example, ...changes } : example,
      ),
    });
  }
  return (
    <Modal
      title={dataset ? 'Maintain reference evidence' : 'Create a benchmark dataset'}
      wide
      onClose={onClose}
    >
      <div className="form-grid">
        <label>
          Dataset name
          <input
            value={String(value.name || '')}
            onChange={(e) => setValue({ ...value, name: e.target.value })}
          />
        </label>
        <label>
          Reference provenance
          <select
            value={String(value.provenance)}
            onChange={(e) => setValue({ ...value, provenance: e.target.value })}
          >
            <option value="unreviewed">Unreviewed — no independent labels</option>
            <option value="synthetic">Synthetic test fixture</option>
            <option value="human_reference">Independently human-reviewed reference</option>
          </select>
        </label>
        <label>
          Linked source course
          <select
            value={String(value.course_id || '')}
            onChange={(e) => setValue({ ...value, course_id: e.target.value || null })}
          >
            <option value="">No linked course</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Reference reviewer
          <input
            value={String(value.reviewer || '')}
            onChange={(e) => setValue({ ...value, reviewer: e.target.value })}
            placeholder="Required for human-reference provenance"
          />
        </label>
        <label>
          Description
          <textarea
            rows={2}
            value={String(value.description || '')}
            onChange={(e) => setValue({ ...value, description: e.target.value })}
          />
        </label>
      </div>
      <p className="field-help">
        Declare human-reference provenance only after an independent person has validated these
        sources and labels. The application never supplies that review for you.
      </p>
      <SectionHead
        title="Expected knowledge and competencies"
        action={
          <button
            className="button small"
            onClick={() =>
              setValue({
                ...value,
                reference_concepts: [
                  ...targets,
                  {
                    id: crypto.randomUUID(),
                    label: '',
                    topic: '',
                    kind: 'concept',
                    importance: 1,
                    assumptions: [],
                    competencies: [],
                    source: {},
                  },
                ],
              })
            }
          >
            <Plus size={14} />
            Add reference target
          </button>
        }
      />
      {targets.map((target, i) => (
        <section className="reference-editor" key={String(target.id || i)}>
          <div className="form-grid">
            <label>
              Target label
              <input
                value={String(target.label || '')}
                onChange={(e) => updateTarget(i, 'label', e.target.value)}
              />
            </label>
            <label>
              Topic
              <input
                value={String(target.topic || '')}
                onChange={(e) => updateTarget(i, 'topic', e.target.value)}
              />
            </label>
            <label>
              Target kind
              <select
                value={String(target.kind || 'concept')}
                onChange={(e) => updateTarget(i, 'kind', e.target.value)}
              >
                {[
                  'concept',
                  'definition',
                  'theorem',
                  'assumption',
                  'method',
                  'competency',
                  'exercise_pattern',
                ].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <label>
              Importance
              <input
                type="number"
                min="0"
                max="3"
                step="0.1"
                value={Number(target.importance ?? 1)}
                onChange={(e) => updateTarget(i, 'importance', Number(e.target.value))}
              />
            </label>
            <label>
              Assumptions (one per line)
              <textarea
                value={((target.assumptions || []) as string[]).join('\n')}
                onChange={(e) =>
                  updateTarget(i, 'assumptions', e.target.value.split('\n').filter(Boolean))
                }
              />
            </label>
            <label>
              Competencies (one per line)
              <textarea
                value={((target.competencies || []) as string[]).join('\n')}
                onChange={(e) =>
                  updateTarget(i, 'competencies', e.target.value.split('\n').filter(Boolean))
                }
              />
            </label>
          </div>
          <SourceFields
            courseId={String(value.course_id || '')}
            value={(target.source || {}) as Json}
            onChange={(source) => updateTarget(i, 'source', source)}
          />
          <button
            className="text-link"
            onClick={() =>
              setValue({ ...value, reference_concepts: targets.filter((_, j) => j !== i) })
            }
          >
            Remove target from draft
          </button>
        </section>
      ))}
      <SectionHead
        title="Reference and deliberately flawed cards"
        action={
          <button
            className="button small"
            onClick={() =>
              setValue({
                ...value,
                reference_cards: [
                  ...examples,
                  {
                    id: crypto.randomUUID(),
                    question: '',
                    answer: '',
                    expected_label: 'correct_useful',
                    label_origin: value.provenance === 'synthetic' ? 'synthetic' : 'human',
                    dimensions: {},
                    rationale: '',
                  },
                ],
              })
            }
          >
            <Plus size={14} />
            Add example card
          </button>
        }
      />
      {examples.map((example, i) => (
        <section className="reference-editor" key={i}>
          <div className="form-grid">
            {['question', 'answer', 'rationale'].map((key) => (
              <label key={key}>
                {human(key)}
                <textarea
                  value={String(example[key] || '')}
                  onChange={(e) =>
                    setValue({
                      ...value,
                      reference_cards: examples.map((v, j) =>
                        i === j ? { ...v, [key]: e.target.value } : v,
                      ),
                    })
                  }
                />
              </label>
            ))}
            <label>
              Label origin
              <select
                value={String(example.label_origin || 'synthetic')}
                onChange={(e) =>
                  setValue({
                    ...value,
                    reference_cards: examples.map((v, j) =>
                      i === j ? { ...v, label_origin: e.target.value } : v,
                    ),
                  })
                }
              >
                <option value="human">Human-entered reference label</option>
                <option value="synthetic">Synthetic fixture label</option>
                <option value="model">Model opinion</option>
              </select>
            </label>
            <label>
              Reference quality label
              <select
                value={String(example.expected_label)}
                onChange={(e) =>
                  setValue({
                    ...value,
                    reference_cards: examples.map((v, j) =>
                      i === j ? { ...v, expected_label: e.target.value } : v,
                    ),
                  })
                }
              >
                {labels.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <details>
            <summary>Reference dimensions, source evidence and independent reviewer</summary>
            <div className="form-grid">
              <label>
                Example reviewer
                <input
                  value={String(example.reviewer || '')}
                  onChange={(e) => updateExample(i, { reviewer: e.target.value })}
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={example.independent === true}
                  onChange={(e) => updateExample(i, { independent: e.target.checked })}
                />
                This example was independently checked against original evidence
              </label>
              {[
                'factual_correct',
                'mathematical_correct',
                'assumptions_complete',
                'atomic',
                'source_correct',
                'useful',
                'unambiguous',
              ].map((key) => (
                <label key={key}>
                  {human(key)}
                  <select
                    value={
                      (example.dimensions as Json)?.[key] === true
                        ? 'yes'
                        : (example.dimensions as Json)?.[key] === false
                          ? 'no'
                          : 'unknown'
                    }
                    onChange={(e) =>
                      updateExample(i, {
                        dimensions: {
                          ...((example.dimensions as Json) || {}),
                          [key]: e.target.value === 'unknown' ? null : e.target.value === 'yes',
                        },
                      })
                    }
                  >
                    <option value="unknown">Not independently assessed</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>
              ))}
            </div>
            <div className="checkbox-row">
              {targets.map((target) => (
                <label className="check-label" key={String(target.id)}>
                  <input
                    type="checkbox"
                    checked={((example.concept_ids || []) as string[]).includes(String(target.id))}
                    onChange={(e) =>
                      updateExample(i, {
                        concept_ids: e.target.checked
                          ? [...((example.concept_ids || []) as string[]), String(target.id)]
                          : ((example.concept_ids || []) as string[]).filter(
                              (id) => id !== target.id,
                            ),
                      })
                    }
                  />
                  {String(target.label)}
                </label>
              ))}
            </div>
            <SourceFields
              courseId={String(value.course_id || '')}
              value={((example.sources || []) as Json[])[0] || {}}
              onChange={(source) =>
                updateExample(i, {
                  sources: [source, ...((example.sources || []) as Json[]).slice(1)],
                })
              }
            />
          </details>
          <button
            className="text-link"
            onClick={() =>
              setValue({ ...value, reference_cards: examples.filter((_, j) => j !== i) })
            }
          >
            Remove example from draft
          </button>
        </section>
      ))}
      {dataset && (
        <details>
          <summary>Annotate a missing concept or source interpretation error</summary>
          <div className="form-grid">
            <label>
              Annotation type
              <select
                value={String(annotation.kind)}
                onChange={(e) => setAnnotation({ ...annotation, kind: e.target.value })}
              >
                <option value="missing_concept">Missing concept</option>
                <option value="interpretation_error">Interpretation error</option>
              </select>
            </label>
            {['label', 'expected', 'actual', 'rationale'].map((key) => (
              <label key={key}>
                {human(key)}
                <textarea
                  value={String(annotation[key] || '')}
                  onChange={(e) => setAnnotation({ ...annotation, [key]: e.target.value })}
                />
              </label>
            ))}
          </div>
          <SourceFields
            courseId={String(value.course_id || '')}
            value={(annotation.source || {}) as Json}
            onChange={(source) => setAnnotation({ ...annotation, source })}
          />
          <button
            className="button"
            disabled={annotate.isPending || !annotation.label}
            onClick={() => annotate.mutate()}
          >
            Record reference annotation
          </button>
          {annotate.error && <ErrorPanel error={annotate.error} />}
        </details>
      )}
      {save.error && <ErrorPanel error={save.error} />}
      <div className="form-actions">
        <button className="button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="button primary"
          disabled={save.isPending || !String(value.name || '').trim()}
          onClick={() => save.mutate()}
        >
          <Save size={15} />
          Save dataset
        </button>
      </div>
    </Modal>
  );
}
function SourceFields({
  value,
  onChange,
  courseId,
}: {
  value: Json;
  onChange: (v: Json) => void;
  courseId?: string;
}) {
  const docs = useQuery({
    queryKey: ['documents', courseId],
    queryFn: async () =>
      list<{ id: string; filename: string }>(await api(`/courses/${courseId}/documents`)),
    enabled: !!courseId,
  });
  return (
    <div className="form-grid">
      <label>
        Supporting source document
        {courseId ? (
          <select
            value={String(value.document_id || '')}
            onChange={(e) => onChange({ ...value, document_id: e.target.value })}
          >
            <option value="">Choose actual imported source</option>
            {docs.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>
        ) : (
          <input
            value={String(value.document_id || '')}
            onChange={(e) => onChange({ ...value, document_id: e.target.value })}
            placeholder="Link a course above to select its source documents"
          />
        )}
      </label>
      <label>
        Source page
        <input
          type="number"
          min="1"
          value={Number(value.page_number || 1)}
          onChange={(e) => onChange({ ...value, page_number: Number(e.target.value) })}
        />
      </label>
      <label>
        Supporting quotation
        <textarea
          value={String(value.quote || '')}
          onChange={(e) => onChange({ ...value, quote: e.target.value })}
        />
      </label>
    </div>
  );
}
function ExperimentDialog({
  dataset,
  courses,
  onClose,
  onCreated,
}: {
  dataset: Dataset;
  courses: Bootstrap['courses'];
  onClose: () => void;
  onCreated: (e: Experiment) => void;
}) {
  const [name, setName] = useState(`${dataset.name} comparison`);
  const [course, setCourse] = useState(dataset.course_id || courses[0]?.id || '');
  const [variants, setVariants] = useState([
    { name: 'Configuration A', run_id: '', config: '{}' },
    { name: 'Configuration B', run_id: '', config: '{}' },
  ]);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState('');
  const client = useQueryClient();
  const runs = useQuery({
    queryKey: ['runs', course],
    queryFn: async () => list<Json>(await api(`/courses/${course}/runs`)),
    enabled: !!course,
  });
  const start = useMutation({
    mutationFn: () => {
      let values;
      try {
        values = variants.map((v) => ({
          name: v.name,
          config: JSON.parse(v.config),
          ...(v.run_id ? { run_id: v.run_id } : {}),
        }));
      } catch {
        throw new Error('Each configuration must contain valid JSON.');
      }
      return write<Experiment>(`/evaluations/datasets/${dataset.id}/experiments`, {
        name,
        course_id: course,
        variants: values,
        consent,
        blind: true,
      });
    },
    onSuccess: (result) => {
      client.invalidateQueries();
      onCreated(result);
    },
  });
  const live = variants.some((v) => !v.run_id);
  return (
    <Modal title="A paired, reproducible experiment" onClose={onClose} wide>
      <p className="muted">
        Use the same source course and reference dataset. New runs use isolated copies. Capturing a
        completed run records the current course cards without new model calls and requires
        unchanged source versions. Captures are labeled separately from isolated pipeline outputs.
        Blind cases hide configuration labels during judgment.
      </p>
      <div className="form-grid">
        <label>
          Experiment name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Source course
          <select
            value={course}
            onChange={(e) => {
              setCourse(e.target.value);
              setVariants((v) => v.map((item) => ({ ...item, run_id: '' })));
            }}
          >
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="paired-variants">
        {variants.map((variant, i) => (
          <section className="reference-editor" key={i}>
            <label>
              Variant name
              <input
                value={variant.name}
                onChange={(e) =>
                  setVariants((v) =>
                    v.map((item, j) => (j === i ? { ...item, name: e.target.value } : item)),
                  )
                }
              />
            </label>
            <label>
              Reuse completed run
              <select
                value={variant.run_id}
                onChange={(e) =>
                  setVariants((v) =>
                    v.map((item, j) => (j === i ? { ...item, run_id: e.target.value } : item)),
                  )
                }
              >
                <option value="">Run a new isolated configuration</option>
                {runs.data
                  ?.filter((r) => r.status === 'completed')
                  .map((r) => (
                    <option key={String(r.id)} value={String(r.id)}>
                      {String(r.id).slice(0, 8)} · {String(r.mode)} ·{' '}
                      {formatDate(String(r.created_at))}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Configuration overrides (JSON)
              <textarea
                rows={6}
                disabled={!!variant.run_id}
                value={variant.config}
                onChange={(e) => {
                  setVariants((v) =>
                    v.map((item, j) => (j === i ? { ...item, config: e.target.value } : item)),
                  );
                  setError('');
                }}
                placeholder={'{"models":{"generation":"model-id"},"reasoning_effort":"high"}'}
              />
            </label>
            <p className="field-help">
              Overrides can select stage models, reasoning, criteria, extraction settings and
              processing strategy. Exact effective settings and prompt versions are retained by the
              experiment.
            </p>
          </section>
        ))}
      </div>
      {live && (
        <label className="consent-label">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I approve sending the source course text, metadata, rendered evidence and semantic
            embedding inputs (learning targets, cards and assumptions) to OpenAI for these new
            evaluation runs. API usage may incur charges.
          </span>
        </label>
      )}
      {(start.error || error) && <ErrorPanel error={start.error || error} />}
      <div className="form-actions">
        <button className="button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="button primary"
          disabled={start.isPending || !course || (live && !consent)}
          onClick={() => start.mutate()}
        >
          Create paired experiment
        </button>
      </div>
    </Modal>
  );
}
export function ReportValues({ value }: { value: unknown }) {
  if (!value || typeof value !== 'object') return <span>{String(value ?? 'Not measured')}</span>;
  const metric = value as Json;
  if ('numerator' in metric && 'denominator' in metric && 'value' in metric)
    return (
      <span className="metric-ratio">
        <strong>
          {String(metric.numerator)} / {String(metric.denominator)}
        </strong>
        {metric.value === null
          ? 'Not measured'
          : `${Math.round(Number(metric.value) * 1000) / 10}%`}
      </span>
    );
  if (Array.isArray(value) && value.every((item) => typeof item === 'string'))
    return value.length ? (
      <ul>
        {value.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    ) : (
      <span>None recorded</span>
    );

  return (
    <div className="report-values">
      {Object.entries(value).map(([key, v]) => (
        <div key={key}>
          <strong>{human(key)}</strong>
          {v && typeof v === 'object' ? (
            <ReportValues value={v} />
          ) : (
            <span>{typeof v === 'number' ? v.toLocaleString() : String(v ?? 'Not measured')}</span>
          )}
        </div>
      ))}
    </div>
  );
}
function ExperimentReport({
  experiment,
  onClose,
}: {
  experiment: Experiment;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [caseOffset, setCaseOffset] = useState(0);
  const [source, setSource] = useState<Source | null>(null);
  const [label, setLabel] = useState('correct_useful');
  const [rationale, setRationale] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [dimensions, setDimensions] = useState<Json>({});
  const [targets, setTargets] = useState<string[]>([]);
  const [independent, setIndependent] = useState(false);
  const [origin, setOrigin] = useState('human');
  const [showResults, setShowResults] = useState(false);
  const [savedHumanCase, setSavedHumanCase] = useState('');
  const client = useQueryClient();
  const toast = useToast();
  const detail = useQuery({
    queryKey: ['evaluation-experiment', experiment.id],
    queryFn: () => api<Experiment>(`/evaluations/experiments/${experiment.id}`),
    initialData: experiment,
    refetchInterval: 3000,
  });
  const cases = useQuery({
    queryKey: ['evaluation-cases', experiment.id, caseOffset],
    queryFn: () =>
      api<PageResult<EvaluationCase>>(
        `/evaluations/experiments/${experiment.id}/cases?blind=true&offset=${caseOffset}&limit=25`,
      ),
    refetchInterval: 5000,
  });
  const dataset = useQuery({
    queryKey: ['evaluation-dataset', experiment.dataset_id],
    queryFn: () => api<Dataset>(`/evaluations/datasets/${experiment.dataset_id}`),
    enabled: !!experiment.dataset_id,
  });
  const current = cases.data?.items[index];
  const card = (current?.card || current?.snapshot || current) as Card | undefined;
  const judge = useMutation({
    mutationFn: () =>
      write(`/evaluations/experiments/${experiment.id}/judgments`, {
        case_id: current!.case_id,
        label,
        dimensions,
        reference_concept_ids: targets,
        rationale,
        reviewer,
        independent,
        origin,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Judgment saved with its declared reviewer, provenance and independence.');
      setSavedHumanCase(origin === 'human' ? current!.case_id : '');
      setRationale('');
      setDimensions({});
      setTargets([]);
    },
  });
  const promote = useMutation({
    mutationFn: () =>
      write(`/evaluations/experiments/${experiment.id}/promote`, {
        case_ids: [current!.case_id],
        confirm: true,
        reviewer,
      }),
    onSuccess: () => {
      client.invalidateQueries();
      toast(
        'Reviewed snapshot saved as a new benchmark version. Earlier experiments retain their frozen references.',
      );
    },
  });
  const report = (detail.data.report || detail.data.metrics || {}) as Json;
  return (
    <Modal title={experiment.name} onClose={onClose} wide>
      <div className="inline-note">
        <EyeOff size={18} />
        <span>
          Blind review hides model/configuration labels. Human judgments are separate from
          deterministic counts and model opinions. Missing labels are not counted as correct.
        </span>
      </div>
      <button className="button" onClick={() => setShowResults(!showResults)}>
        {showResults ? 'Return to blind review' : 'Reveal comparison results and configurations'}
      </button>
      {showResults && (
        <>
          <div className="evaluation-report-grid">
            {((report.variants || []) as Json[]).map((variant) => (
              <section className="panel" key={String(variant.id)}>
                <h3>{String(variant.name)}</h3>
                <p className="field-help">
                  {detail.data.variants?.find((v) => v.id === variant.id)?.execution === 'captured'
                    ? 'Current course cards captured under the completed run configuration'
                    : 'Isolated pipeline output'}
                </p>
                <h4>Automatic structure and coverage counts</h4>
                <ReportValues
                  value={Object.fromEntries(
                    Object.entries((variant.automatic || {}) as Json).filter(
                      ([key]) => key !== 'missing_reference_concepts',
                    ),
                  )}
                />
                <h4>Model judgments — not ground truth</h4>
                <ReportValues value={variant.model_judgments} />
                <ReportValues value={variant.model_dimensions} />
                <details>
                  <summary>Failure categories and reference decision agreement</summary>
                  <ReportValues
                    value={{
                      failure_categories: variant.failure_categories,
                      reference_decision_agreement: variant.reference_decision_agreement,
                    }}
                  />
                </details>
                <h4>Human results and explicit unreviewed denominators</h4>
                <p className="field-help">
                  Marked independently checked:{' '}
                  {String(((variant.reviews as Json)?.human as Json)?.independent_judgments ?? 0)}{' '}
                  judgments. Other human-origin labels do not imply independent evidence review.
                </p>
                <ReportValues value={(variant.reviews as Json)?.human} />
                <details>
                  <summary>Synthetic and model review labels</summary>
                  <ReportValues
                    value={{
                      synthetic: (variant.reviews as Json)?.synthetic,
                      model: (variant.reviews as Json)?.model,
                    }}
                  />
                </details>
                <details>
                  <summary>Source/topic weaknesses and failed cases</summary>
                  <ReportValues
                    value={{
                      automatic_missing_reference_concepts: (variant.automatic as Json)
                        ?.missing_reference_concepts,
                      topic_weaknesses: variant.topic_weaknesses,
                      failed_case_ids: variant.failed_case_ids,
                    }}
                  />
                </details>
              </section>
            ))}
          </div>
          <SectionHead title="Paired reference-target comparisons" />
          <ReportValues value={report.comparisons} />
          <details>
            <summary>Full reproducibility report and limitations</summary>
            <ReportValues value={report} />
            <pre>
              {JSON.stringify(
                { variants: detail.data.variants, status: detail.data.status },
                null,
                2,
              )}
            </pre>
          </details>
          <a className="button small" href={`/api/evaluations/experiments/${experiment.id}/report`}>
            <Download size={14} />
            Download reproducible report
          </a>
        </>
      )}
      {detail.error && <ErrorPanel error={detail.error} />}
      <SectionHead
        title="Independent card judgments"
        action={
          <span>
            {caseOffset + index + 1} / {cases.data?.total ?? 0} blind cases
          </span>
        }
      />
      {cases.isPending ? (
        <Loading />
      ) : cases.error ? (
        <ErrorPanel error={cases.error} />
      ) : card && current ? (
        <div className="paired-variants">
          <section className="panel">
            <Badge>Blind case {String(current.case_id).slice(0, 10)}</Badge>
            {Array.isArray(current.judgments) && current.judgments.length > 0 && (
              <details>
                <summary>{current.judgments.length} recorded judgments on this case</summary>
                {(current.judgments as Json[]).map((j, i) => (
                  <article key={i}>
                    <Badge>
                      {String(j.origin)} · {j.independent ? 'independent' : 'not independent'}
                    </Badge>
                    <p>
                      {human(String(j.label))} · {String(j.reviewer)}
                    </p>
                    <p>{String(j.rationale)}</p>
                  </article>
                ))}
              </details>
            )}
            <h3>Question</h3>
            <MathText text={card.question} cloze={card.card_type === 'cloze'} />
            <hr />
            <h3>Answer</h3>
            <MathText
              text={card.card_type === 'cloze' ? card.question : card.answer}
              cloze={card.card_type === 'cloze'}
              reveal
            />
            <h3>Explanation</h3>
            <MathText text={card.explanation} />
            <div className="source-chips">
              {card.sources?.map((ref, i) => (
                <button key={i} onClick={() => setSource(ref)}>
                  {ref.document_name || 'Original source'} · p.{ref.page_number || 1}
                </button>
              ))}
            </div>
          </section>
          <section>
            <label>
              Independent quality judgment
              <select value={label} onChange={(e) => setLabel(e.target.value)}>
                {labels.map(([id, title]) => (
                  <option key={id} value={id}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-grid">
              {[
                'factual_correct',
                'mathematical_correct',
                'assumptions_complete',
                'atomic',
                'source_correct',
                'useful',
                'unambiguous',
              ].map((key) => (
                <label key={key}>
                  {human(key)}
                  <select
                    value={
                      dimensions[key] === true
                        ? 'yes'
                        : dimensions[key] === false
                          ? 'no'
                          : 'unknown'
                    }
                    onChange={(e) =>
                      setDimensions({
                        ...dimensions,
                        [key]: e.target.value === 'unknown' ? null : e.target.value === 'yes',
                      })
                    }
                  >
                    <option value="unknown">Not independently assessed</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>
              ))}
            </div>
            <label>
              Reference targets covered
              <div className="checkbox-row">
                {(
                  (detail.data.reference_snapshot as Dataset | undefined)?.reference_concepts ||
                  dataset.data?.reference_concepts
                )?.map((target) => (
                  <label className="check-label" key={String(target.id)}>
                    <input
                      type="checkbox"
                      checked={targets.includes(String(target.id))}
                      onChange={(e) =>
                        setTargets((v) =>
                          e.target.checked
                            ? [...v, String(target.id)]
                            : v.filter((id) => id !== target.id),
                        )
                      }
                    />
                    {String(target.label)}
                  </label>
                ))}
              </div>
            </label>
            <div className="form-grid">
              <label>
                Judgment provenance
                <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
                  <option value="human">Human judgment</option>
                  <option value="synthetic">Synthetic test label</option>
                  <option value="model">Model judgment</option>
                </select>
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={independent}
                  onChange={(e) => setIndependent(e.target.checked)}
                />
                I independently checked the original evidence
              </label>
            </div>
            <label>
              Reviewer name
              <input
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="Who independently checked this case?"
              />
            </label>
            <label>
              Evidence and rationale
              <textarea rows={3} value={rationale} onChange={(e) => setRationale(e.target.value)} />
            </label>
            <div className="inline-actions">
              <button className="button" disabled={!index} onClick={() => setIndex(index - 1)}>
                Previous case
              </button>
              <button
                className="button primary"
                disabled={judge.isPending || !reviewer.trim() || !rationale.trim()}
                onClick={() => judge.mutate()}
              >
                <CheckCheck size={15} />
                Save quality judgment
              </button>
              <button
                className="button"
                disabled={index + 1 >= (cases.data?.items.length ?? 0)}
                onClick={() => setIndex(index + 1)}
              >
                Skip for now
              </button>
            </div>
            {judge.error && <ErrorPanel error={judge.error} />}
            <button
              className="button small"
              disabled={
                promote.isPending ||
                !reviewer.trim() ||
                origin !== 'human' ||
                savedHumanCase !== current.case_id
              }
              onClick={() => promote.mutate()}
            >
              Save reviewed example to benchmark
            </button>
            <p className="field-help">
              Only an already saved human judgment can be promoted. The backend verifies its
              provenance and preserves the immutable reviewed snapshot.
            </p>
            {promote.error && <ErrorPanel error={promote.error} />}
          </section>
        </div>
      ) : (
        <Empty title="Cases appear after the paired runs complete">
          Run progress and pending judgments remain visible; no results are implied while generation
          is incomplete.
        </Empty>
      )}
      <Pagination
        offset={caseOffset}
        total={cases.data?.total ?? 0}
        limit={25}
        onChange={(offset) => {
          setCaseOffset(offset);
          setIndex(0);
        }}
      />
      {source && (
        <SourcePreview
          documentId={source.document_id}
          source={source}
          onClose={() => setSource(null)}
        />
      )}
    </Modal>
  );
}
