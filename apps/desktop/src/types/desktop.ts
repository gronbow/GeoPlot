export type DesktopStatus =
  | "ready"
  | "needs_confirmation"
  | "review"
  | "blocked"
  | "error";

export interface DesktopIssue {
  code: string;
  severity: "info" | "review" | "warning" | "error";
  message: string;
  field?: string;
}

export interface DesktopReport<T = Record<string, unknown>> {
  schema_version: "geoskills.desktop-report/v1";
  operation: string;
  status: DesktopStatus;
  engine: {
    name: string;
    version: string;
    diagram_api_version: string;
  };
  result: T;
  issues: DesktopIssue[];
}

export interface SourceRecord {
  stored_filename: string;
  original_basename: string;
  sha256: string;
  size_bytes: number;
}

export interface ProjectSummary {
  schema_version: "geoskills.desktop-project/v1";
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  source: SourceRecord | null;
  selected_sheet: string | number | null;
  selected_layout: "auto" | "row-per-sample" | "analyte-per-row";
  latest_plan_id: string | null;
}

export interface ImportResult {
  project: ProjectSummary;
  replaced: boolean;
}

export interface InspectResult {
  source: {
    stored_filename: string;
    sha256: string;
    size_bytes: number;
    format: string;
    sheet_names: string[];
    selected_sheet: string | number | null;
    layout: string | null;
    transformation: string | null;
  };
  row_count: number | null;
  column_count: number | null;
  sample_column_candidates: string[];
  sample_column_suggestion?: string | null;
  group_column_candidates: string[];
  recognized_analytes: Array<{
    canonical: string;
    kind: string;
    source_label: string;
    source_column: string;
    required_unit: string | null;
    explicit_unit: string | null;
    unit_status: string;
  }>;
  mapping_suggestions?: Record<string, string>;
  unrecognized_columns?: string[];
  quality: Record<string, number>;
  preview: {
    columns: string[];
    rows: unknown[][];
    preview_truncated_rows: boolean;
    preview_truncated_columns: boolean;
    notice: string;
  } | null;
  figure_candidates: FigureCandidate[];
}

export type FigureCandidateState =
  | "AVAILABLE_AFTER_REVIEW"
  | "NEEDS_PARAMETER"
  | "NEEDS_SCIENTIFIC_CONFIRMATION"
  | "NOT_AVAILABLE"
  | "BLOCKED";

export interface FigureCandidate {
  diagram: string;
  display_name_en: string;
  display_name_zh: string;
  state: FigureCandidateState;
  requirements: string[];
  required_confirmations: string[];
  suggestions: Record<string, unknown>;
}

export type InputLayout = "auto" | "row-per-sample" | "analyte-per-row";

export interface ReviewTask {
  id: string;
  diagram: string;
  stem: string;
  preset: string;
  parameters: Record<string, unknown>;
  confirmations: Record<string, boolean>;
}

export interface RecipeReview {
  sample_id: string;
  group: string | null;
  mapping: Record<string, string>;
  units: Record<string, string>;
  output_directory: "outputs/current";
  report_profile: "shareable" | "local-reproducible";
  presets: Record<string, unknown>;
  confirmations: Record<string, boolean>;
  tasks: ReviewTask[];
  data_basis?: Record<string, unknown>;
}

export interface ExecutionPlan {
  schema_version: "geoskills.plan/v1";
  plan_id: string;
  status: DesktopStatus;
  input: Record<string, unknown>;
  column_mapping: Array<Record<string, unknown>>;
  output: Record<string, unknown>;
  confirmations: Record<string, boolean>;
  tasks: Array<{
    id: string;
    diagram: string;
    parameters: Record<string, unknown>;
    confirmations: Record<string, boolean>;
    expected_outputs: string[];
  }>;
  issues: DesktopIssue[];
}

export interface PlanResult {
  report: DesktopReport<Record<string, unknown>>;
  plan: ExecutionPlan;
  project: ProjectSummary;
}

export interface ArtifactSummary {
  task_id: string;
  diagram: string;
  svg_available: boolean;
  qa_available: boolean;
  report_available: boolean;
}

export interface RunResult {
  report: DesktopReport<Record<string, unknown>>;
  artifacts: ArtifactSummary[];
}

export interface ScreeningResult {
  available: boolean;
  reason: string | null;
  x: "SiO2";
  variables_considered: string[];
  variables_capped: boolean;
  results: Array<{
    variable: string;
    rho: number;
    n: number;
  }>;
  method: "spearman_rank_then_pearson";
  minimum_pair_count: 8;
  maximum_variables: 32;
  maximum_results: 8;
  data_scope: "full_reviewed_mapped_dataset";
  disclaimer: string;
}

export interface ArtifactBundle {
  task_id: string;
  diagram: string;
  svg_data_url: string;
  qa_markdown: string;
  report: Record<string, unknown>;
}
