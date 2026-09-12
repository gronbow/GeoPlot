use std::fs;
use std::path::PathBuf;

use serde_json::{Value, json};
use tauri::State;

use crate::import::ImportResult;
use crate::project_store::{ProjectRecord, ProjectStore};
use crate::sidecar::{BridgeOperation, BridgeReport, BridgeRunner};
use crate::workflow::{
    ArtifactBundle, ArtifactSummary, PlanResult, RunResult, create_current_plan, list_artifacts,
    load_artifact, read_current_plan, run_current_plan, run_screening, save_recipe,
};

pub struct AppState {
    pub store: ProjectStore,
    pub bridge: BridgeRunner,
}

fn safe_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[tauri::command]
pub fn create_project(state: State<'_, AppState>, title: String) -> Result<ProjectRecord, String> {
    state.store.create_project(&title).map_err(safe_error)
}

#[tauri::command]
pub fn list_projects(state: State<'_, AppState>) -> Result<Vec<ProjectRecord>, String> {
    state.store.list_projects().map_err(safe_error)
}

#[tauri::command]
pub fn rename_project(
    state: State<'_, AppState>,
    project_id: String,
    title: String,
) -> Result<ProjectRecord, String> {
    state
        .store
        .rename_project(&project_id, &title)
        .map_err(safe_error)
}

#[tauri::command]
pub fn remove_project(
    state: State<'_, AppState>,
    project_id: String,
) -> Result<ProjectRecord, String> {
    state.store.remove_project(&project_id).map_err(safe_error)
}

#[tauri::command]
pub fn list_removed_projects(state: State<'_, AppState>) -> Result<Vec<ProjectRecord>, String> {
    state.store.list_removed_projects().map_err(safe_error)
}

#[tauri::command]
pub fn restore_project(
    state: State<'_, AppState>,
    project_id: String,
) -> Result<ProjectRecord, String> {
    state.store.restore_project(&project_id).map_err(safe_error)
}

#[tauri::command]
pub fn get_project_summary(
    state: State<'_, AppState>,
    project_id: String,
) -> Result<ProjectRecord, String> {
    state.store.read_project(&project_id).map_err(safe_error)
}

#[tauri::command]
pub fn import_source_file(
    state: State<'_, AppState>,
    project_id: String,
    source_path: String,
    replace: bool,
) -> Result<ImportResult, String> {
    let path = PathBuf::from(source_path);
    let (project, replaced) = state
        .store
        .import_source(&project_id, &path, replace)
        .map_err(safe_error)?;
    Ok(ImportResult { project, replaced })
}

#[tauri::command]
pub fn select_sheet(
    state: State<'_, AppState>,
    project_id: String,
    sheet: Option<Value>,
) -> Result<ProjectRecord, String> {
    state
        .store
        .select_sheet(&project_id, sheet)
        .map_err(safe_error)
}

#[tauri::command]
pub fn select_layout(
    state: State<'_, AppState>,
    project_id: String,
    layout: String,
) -> Result<ProjectRecord, String> {
    state
        .store
        .select_layout(&project_id, &layout)
        .map_err(safe_error)
}

#[tauri::command]
pub fn get_capabilities(state: State<'_, AppState>) -> Result<BridgeReport, String> {
    state
        .bridge
        .invoke(BridgeOperation::Capabilities, None, None)
        .map_err(safe_error)
}

#[tauri::command]
pub fn inspect_project(
    state: State<'_, AppState>,
    project_id: String,
) -> Result<BridgeReport, String> {
    let project = state.store.read_project(&project_id).map_err(safe_error)?;
    let source = project
        .source
        .as_ref()
        .ok_or_else(|| "Import a local source before inspection.".to_owned())?;
    let request = json!({
        "schema_version": "geoskills.desktop-request/v1",
        "operation": "inspect",
        "source": format!("data/{}", source.stored_filename),
        "sheet": project.selected_sheet,
        "layout": project.selected_layout
    });
    let request_path = state
        .store
        .write_request(&project_id, &request)
        .map_err(safe_error)?;
    let project_dir = state.store.project_dir(&project_id).map_err(safe_error)?;
    let response = state.bridge.invoke(
        BridgeOperation::Inspect,
        Some(&project_dir),
        Some(&request_path),
    );
    let cleanup = fs::remove_file(&request_path);
    match (response, cleanup) {
        (Ok(report), Ok(())) => Ok(report),
        (Ok(_), Err(_)) => Err("The temporary local request could not be cleaned up.".to_owned()),
        (Err(error), _) => Err(safe_error(error)),
    }
}

#[tauri::command]
pub fn save_project_recipe(
    state: State<'_, AppState>,
    project_id: String,
    review: Value,
    overwrite: bool,
) -> Result<BridgeReport, String> {
    save_recipe(&state.store, &state.bridge, &project_id, review, overwrite).map_err(safe_error)
}

#[tauri::command]
pub fn create_execution_plan(
    state: State<'_, AppState>,
    project_id: String,
    selected_task_ids: Vec<String>,
    overwrite: bool,
) -> Result<PlanResult, String> {
    create_current_plan(
        &state.store,
        &state.bridge,
        &project_id,
        selected_task_ids,
        overwrite,
    )
    .map_err(safe_error)
}

#[tauri::command]
pub fn get_current_plan(state: State<'_, AppState>, project_id: String) -> Result<Value, String> {
    read_current_plan(&state.store, &project_id).map_err(safe_error)
}

#[tauri::command]
pub fn run_execution_plan(
    state: State<'_, AppState>,
    project_id: String,
    plan_reviewed: bool,
    overwrite: bool,
) -> Result<RunResult, String> {
    run_current_plan(
        &state.store,
        &state.bridge,
        &project_id,
        plan_reviewed,
        overwrite,
    )
    .map_err(safe_error)
}

#[tauri::command]
pub fn run_sio2_screening(
    state: State<'_, AppState>,
    project_id: String,
) -> Result<BridgeReport, String> {
    run_screening(&state.store, &state.bridge, &project_id).map_err(safe_error)
}

#[tauri::command]
pub fn list_generated_artifacts(
    state: State<'_, AppState>,
    project_id: String,
) -> Result<Vec<ArtifactSummary>, String> {
    list_artifacts(&state.store, &project_id).map_err(safe_error)
}

#[tauri::command]
pub fn get_generated_artifact(
    state: State<'_, AppState>,
    project_id: String,
    task_id: String,
) -> Result<ArtifactBundle, String> {
    load_artifact(&state.store, &project_id, &task_id).map_err(safe_error)
}
