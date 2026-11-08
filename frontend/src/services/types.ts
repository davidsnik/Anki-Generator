export type Json = Record<string, unknown>;
export interface Course {
  id: string;
  name: string;
  description: string;
  deck_name: string;
  language: string;
  archived: boolean;
  criteria: Json;
  stats?: {
    documents?: number;
    cards?: number;
    pending_review?: number;
    approved?: number;
    verified?: number;
    concepts?: number;
    last_status?: string;
  };
  created_at?: string;
  document_count?: number;
  card_count?: number;
  pending_count?: number;
  last_run_status?: string;
}
export interface KeyStatus {
  configured: boolean;
  source?: string;
  persistent?: boolean;
  secure_storage_available?: boolean;
  message?: string;
}
export interface Bootstrap {
  csrf_token: string;
  settings: Json;
  key_status: KeyStatus;
  courses: Course[];
  recent_runs: Run[];
  diagnostics: Json;
}
export interface Document {
  id: string;
  filename: string;
  original_filename?: string;
  relative_path?: string;
  category: string;
  authority: string;
  linked_document_id?: string | null;
  status: string;
  page_count?: number;
  size_bytes?: number;
  warnings?: string[];
  error?: string;
  sha256?: string;
}
export interface Region {
  id: string;
  bbox?: number[];
  image_url?: string;
  page_number?: number;
  kind?: string;
  text?: string;
}
export interface Page {
  id?: string;
  page_number: number;
  width?: number;
  height?: number;
  text: string;
  status?: string;
  warnings?: string[];
  regions?: Region[];
  render_url?: string;
  image_url?: string;
}
export interface Source {
  document_id: string;
  document_name?: string;
  filename?: string;
  page_number?: number;
  page?: number;
  region_id?: string;
  bbox?: number[];
  text?: string;
  quote?: string;
}
export interface Card {
  id: string;
  kind?: string;
  revision_number?: number;
  question: string;
  answer: string;
  explanation: string;
  card_type: string;
  tags: string[];
  concept_id?: string;
  concept_ids?: string[];
  review_status: string;
  verification_status: string;
  issues?: unknown[];
  sources?: Source[];
  evidence?: Source[];
  source_references?: Source[];
  image_refs?: unknown[];
  media?: unknown[];
  manually_edited?: boolean;
  created_at?: string;
  updated_at?: string;
  verification?: Json;
  generation_rationale?: string;
}
export interface Concept {
  metadata_json?: Json;
  exercise_analysis?: Json[];
  id: string;
  title: string;
  name?: string;
  kind: string;
  parent_id?: string;
  importance: number;
  description?: string;
  coverage_status?: string;
  card_count?: number;
  excluded?: boolean;
  sources?: Source[];
  assumptions?: string[];
  relationships?: unknown[];
}
export interface Stage {
  name?: string;
  stage?: string;
  status: string;
  message?: string;
  completed?: number;
  total?: number;
  metrics?: Json;
  started_at?: string;
  finished_at?: string;
}
export interface Run {
  id: string;
  course_id: string;
  status: string;
  current_stage?: string;
  stage?: string;
  stages?: Stage[] | Record<string, Stage>;
  progress?: Json;
  metrics?: Json;
  warnings?: string[];
  error?: string;
  created_at: string;
  updated_at?: string;
  started_at?: string;
  completed_at?: string;
  finished_at?: string;
  inputs?: unknown[];
  mode?: string;
  models?: Json;
  config?: Json;
  usage?: Json;
  input_documents?: unknown[];
  events?: unknown[];
}
export interface ExportRecord {
  id: string;
  format: string;
  card_count: number;
  created_at: string;
  download_url?: string;
  deck_name?: string;
  sha256?: string;
}
export interface Revision {
  id: string;
  revision_number?: number;
  origin?: string;
  question?: string;
  answer?: string;
  explanation?: string;
  created_at?: string;
  reason?: string;
  actor?: string;
  content?: Partial<Card>;
  snapshot?: Partial<Card>;
  revision?: number;
}
