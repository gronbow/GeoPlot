import { invoke } from "@tauri-apps/api/core";

import type {
  DesktopReport,
  ArtifactBundle,
  ArtifactSummary,
  ImportResult,
  InputLayout,
  InspectResult,
  PlanResult,
  ProjectSummary,
  RecipeReview,
  RunResult,
  ScreeningResult,
} from "../types/desktop";

export interface DesktopBackend {
  listProjects(): Promise<ProjectSummary[]>;
  createProject(title: string): Promise<ProjectSummary>;
  renameProject(projectId: string, title: string): Promise<ProjectSummary>;
  removeProject(projectId: string): Promise<ProjectSummary>;
  listRemovedProjects(): Promise<ProjectSummary[]>;
  restoreProject(projectId: string): Promise<ProjectSummary>;
  importSourceFile(
    projectId: string,
    sourcePath: string,
    replace: boolean,
  ): Promise<ImportResult>;
  inspectProject(projectId: string): Promise<DesktopReport<InspectResult>>;
  selectSheet(projectId: string, sheet: string | number | null): Promise<ProjectSummary>;
  selectLayout(projectId: string, layout: InputLayout): Promise<ProjectSummary>;
  saveProjectRecipe(
    projectId: string,
    review: RecipeReview,
    overwrite: boolean,
  ): Promise<DesktopReport<Record<string, unknown>>>;
  createExecutionPlan(
    projectId: string,
    selectedTaskIds: string[],
    overwrite: boolean,
  ): Promise<PlanResult>;
  getCurrentPlan(projectId: string): Promise<PlanResult["plan"]>;
  runExecutionPlan(
    projectId: string,
    planReviewed: boolean,
    overwrite: boolean,
  ): Promise<RunResult>;
  runSio2Screening(projectId: string): Promise<DesktopReport<ScreeningResult>>;
  listGeneratedArtifacts(projectId: string): Promise<ArtifactSummary[]>;
  getGeneratedArtifact(projectId: string, taskId: string): Promise<ArtifactBundle>;
}

export const tauriBackend: DesktopBackend = {
  listProjects: () => invoke<ProjectSummary[]>("list_projects"),
  createProject: (title) => invoke<ProjectSummary>("create_project", { title }),
  renameProject: (projectId, title) =>
    invoke<ProjectSummary>("rename_project", { projectId, title }),
  removeProject: (projectId) =>
    invoke<ProjectSummary>("remove_project", { projectId }),
  listRemovedProjects: () => invoke<ProjectSummary[]>("list_removed_projects"),
  restoreProject: (projectId) =>
    invoke<ProjectSummary>("restore_project", { projectId }),
  importSourceFile: (projectId, sourcePath, replace) =>
    invoke<ImportResult>("import_source_file", {
      projectId,
      sourcePath,
      replace,
    }),
  inspectProject: async (projectId) =>
    validateInspectReport(await invoke<unknown>("inspect_project", { projectId })),
  selectSheet: (projectId, sheet) =>
    invoke<ProjectSummary>("select_sheet", { projectId, sheet }),
  selectLayout: (projectId, layout) =>
    invoke<ProjectSummary>("select_layout", { projectId, layout }),
  saveProjectRecipe: (projectId, review, overwrite) =>
    invoke<DesktopReport<Record<string, unknown>>>("save_project_recipe", {
      projectId,
      review,
      overwrite,
    }),
  createExecutionPlan: (projectId, selectedTaskIds, overwrite) =>
    invoke<PlanResult>("create_execution_plan", {
      projectId,
      selectedTaskIds,
      overwrite,
    }),
  getCurrentPlan: (projectId) =>
    invoke<PlanResult["plan"]>("get_current_plan", { projectId }),
  runExecutionPlan: (projectId, planReviewed, overwrite) =>
    invoke<RunResult>("run_execution_plan", {
      projectId,
      planReviewed,
      overwrite,
    }),
  runSio2Screening: (projectId) =>
    invoke<DesktopReport<ScreeningResult>>("run_sio2_screening", { projectId }),
  listGeneratedArtifacts: (projectId) =>
    invoke<ArtifactSummary[]>("list_generated_artifacts", { projectId }),
  getGeneratedArtifact: (projectId, taskId) =>
    invoke<ArtifactBundle>("get_generated_artifact", { projectId, taskId }),
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidInspectContract(detail: string): never {
  throw new Error(
    `Desktop bridge returned an invalid inspect contract: ${detail}. ` +
      "Restart the app or rebuild the bundled bridge so the desktop and engine versions match.",
  );
}

function requireString(record: Record<string, unknown>, field: string, location: string): void {
  if (typeof record[field] !== "string") {
    invalidInspectContract(`${location}.${field} must be a string`);
  }
}

function requireNullableString(
  record: Record<string, unknown>,
  field: string,
  location: string,
): void {
  if (record[field] !== null && typeof record[field] !== "string") {
    invalidInspectContract(`${location}.${field} must be null or a string`);
  }
}

/**
 * Validate the critical Python-to-desktop inspect boundary without duplicating
 * scientific registry rules in TypeScript.
 */
export function validateInspectReport(value: unknown): DesktopReport<InspectResult> {
  if (!isRecord(value) || !isRecord(value.result)) {
    return invalidInspectContract("the response result is missing");
  }
  const recognized = value.result.recognized_analytes;
  if (!Array.isArray(recognized)) {
    return invalidInspectContract("result.recognized_analytes must be an array");
  }
  const sourceIdentities = new Set<string>();
  recognized.forEach((entry, index) => {
    const location = `result.recognized_analytes[${index}]`;
    if (!isRecord(entry)) {
      invalidInspectContract(`${location} must be an object`);
    }
    if (typeof entry.canonical !== "string" || entry.canonical.trim().length === 0) {
      invalidInspectContract(`${location}.canonical must be a non-empty string`);
    }
    requireString(entry, "kind", location);
    requireString(entry, "source_label", location);
    requireString(entry, "source_column", location);
    requireNullableString(entry, "required_unit", location);
    requireNullableString(entry, "explicit_unit", location);
    requireString(entry, "unit_status", location);

    const identity = entry.source_column as string;
    if (sourceIdentities.has(identity)) {
      invalidInspectContract(`${location}.source_column duplicates an earlier source identity`);
    }
    sourceIdentities.add(identity);
  });
  return value as unknown as DesktopReport<InspectResult>;
}

export function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
