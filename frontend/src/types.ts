export type Row = Record<string, string | number | null | undefined>;
export interface Metrics {
  total_records: number; generated_mutants: number; module_baseline_records: number; scored_mutants: number;
  killed_assert: number; killed_error: number; survived: number;
  mutation_score: number | null; assertion_score: number | null;
  status_counts: Record<string, number>; excluded_statuses: Record<string, number>;
}
export interface Summary {
  schema_version: number; overall: Metrics;
  by_repo: Record<string, Metrics>; by_category: Record<string, Metrics>; by_operator: Record<string, Metrics>;
  validation_problems: string[];
}
export type FilterKey = 'repo' | 'category' | 'operator' | 'status' | 'q';
export type Filters = Record<FilterKey, string>;
export interface DatasetInfo {
  id: string; name: string; created_at: string;
  provenance: { kind: 'verified' | 'historical' | 'imported' | 'unverified'; message: string };
  summary: Summary;
}
export interface Dataset extends DatasetInfo {
  rows: Row[]; metadata: Record<string, unknown>;
  filter_options: Record<Exclude<FilterKey, 'q'>, string[]>;
  selection: { total_rows: number; filtered_rows: number };
}
export interface Operator { id: string; category: string; description: string }
export interface Bootstrap {
  version: string; operators: Operator[]; categories: string[];
  sources: { id: string; name: string; description: string; kind: 'historical' }[];
  limits: Record<string, number>; capabilities: { terraform: boolean; tofu: boolean };
}
export interface RunConfig {
  target_path: string; engine: 'terraform' | 'tofu'; operators: string[]; test_directory: string;
  max_mutants: number; budget_seconds: number; timeout: number; init_timeout: number; init_attempts: number;
  acknowledge_execution: boolean;
}
export interface Preview {
  modules: string[]; mutants: { id: string; operator_id: string; file: string; line: number; original: string; mutated: string; diff: string }[];
  warnings: string[]; truncated: boolean;
}
export interface Job {
  snapshot_revision: number;
  id: string; state: 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  config: RunConfig; created_at: string; started_at: string | null; finished_at: string | null;
  dataset_id: string | null; error: string | null;
  progress: { phase: string; completed_commands: number }; log_tail: string; duration_seconds: number;
}
