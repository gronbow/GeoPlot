mod commands;
mod import;
mod project_store;
mod sidecar;
mod workflow;

use commands::AppState;
use project_store::ProjectStore;
use sidecar::BridgeRunner;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let store = ProjectStore::from_app(app.handle())?;
            if let Err(error) = store.initialize() {
                eprintln!("GeoPlot project-store initialization error: {error:?}");
                return Err(error.into());
            }
            let bridge = BridgeRunner::for_app()?;
            app.manage(AppState { store, bridge });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::create_project,
            commands::list_projects,
            commands::rename_project,
            commands::remove_project,
            commands::list_removed_projects,
            commands::restore_project,
            commands::get_project_summary,
            commands::import_source_file,
            commands::select_sheet,
            commands::select_layout,
            commands::get_capabilities,
            commands::inspect_project,
            commands::save_project_recipe,
            commands::create_execution_plan,
            commands::get_current_plan,
            commands::run_execution_plan,
            commands::run_sio2_screening,
            commands::list_generated_artifacts,
            commands::get_generated_artifact,
        ])
        .run(tauri::generate_context!())
        .expect("GeoPlot failed to start");
}
