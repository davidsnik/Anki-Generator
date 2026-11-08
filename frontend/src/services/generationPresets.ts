import type { Json } from './types';
export interface GenerationPreset {
  id: string;
  name: string;
  description: string;
  criteria: Json;
}
const shared = {
  card_types: ['basic', 'cloze'],
  include_explanations: true,
  include_diagrams: true,
};
/** Preferences only: these never relax evidence, independent review, or export gates. */
export const generationPresets: GenerationPreset[] = [
  {
    id: 'university_exam',
    name: 'Comprehensive university exam',
    description: 'Broad theory, assumptions, and transferable exercise methods.',
    criteria: {
      ...shared,
      coverage: 'comprehensive',
      theory_emphasis: 1.1,
      methods_emphasis: 1.2,
      conceptual_emphasis: 1.1,
      answer_detail: 'concise',
      proof_treatment: 'key_steps',
      example_treatment: 'transfer',
    },
  },
  {
    id: 'conceptual',
    name: 'Conceptual understanding',
    description: 'Connections, intuition, and why the conditions matter.',
    criteria: {
      ...shared,
      coverage: 'balanced',
      theory_emphasis: 0.9,
      methods_emphasis: 0.6,
      conceptual_emphasis: 1.7,
      answer_detail: 'balanced',
      proof_treatment: 'strategies',
      example_treatment: 'include',
    },
  },
  {
    id: 'problem_solving',
    name: 'Problem-solving methods',
    description: 'Method selection, reusable reasoning, and common pitfalls.',
    criteria: {
      ...shared,
      coverage: 'comprehensive',
      theory_emphasis: 0.8,
      methods_emphasis: 1.8,
      conceptual_emphasis: 1.1,
      answer_detail: 'concise',
      proof_treatment: 'key_steps',
      example_treatment: 'transfer',
    },
  },
];
