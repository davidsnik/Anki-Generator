export const modelStages = [
  ['interpretation', 'Document interpretation'],
  ['knowledge', 'Knowledge extraction'],
  ['generation', 'Flashcard generation'],
  ['factual', 'Factual verification'],
  ['pedagogical', 'Teaching quality review'],
  ['coverage', 'Coverage review'],
] as const;
export type ModelStage = (typeof modelStages)[number][0] | 'embeddings';
export type ModelCompatibility = 'supported' | 'unsupported' | 'unknown';
export interface AvailableModel {
  id: string;
  name: string;
  group: 'general' | 'embeddings' | 'unverified';
  available: boolean | null;
  capabilities: {
    responses: boolean | null;
    structured_outputs: boolean | null;
    vision: boolean | null;
    embeddings: boolean | null;
    reasoning_efforts: string[] | null;
  };
  compatibility: Partial<Record<ModelStage, ModelCompatibility>>;
  recommended_for: string[];
  documentation: string | null;
  verified_on: string | null;
}
export interface ModelCatalogue {
  status: 'ready' | 'missing_key' | 'error';
  models: AvailableModel[];
  defaults: Record<string, string>;
  default_embedding_model: string;
  recommendation: string;
  fetched_at: string | null;
  cached: boolean;
  cache_expires_at: string | null;
  error: { kind: string; message: string; retryable: boolean } | null;
  catalogue_verified_on: string;
  notice: string;
}
export interface ModelValidation {
  valid: boolean;
  issues: {
    stage: string;
    model: string;
    severity: 'error' | 'warning';
    code: string;
    message: string;
  }[];
  checked_at: string;
}
