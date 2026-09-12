use std::fs::{self, File};
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};

use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;

use crate::project_store::{ProjectRecord, ProjectStore, StoreError};
use crate::sidecar::{BridgeError, BridgeOperation, BridgeReport, BridgeRunner};

const REQUEST_SCHEMA: &str = "geoskills.desktop-request/v1";
const PLAN_SCHEMA: &str = "geoskills.plan/v1";
const RECIPE_FILE: &str = "current.yaml";
const PLAN_FILE: &str = "plans/current.json";
const OUTPUT_DIRECTORY: &str = "outputs/current";
const MAX_PLAN_BYTES: u64 = 4 * 1024 * 1024;
const MAX_SVG_BYTES: u64 = 8 * 1024 * 1024;
const MAX_QA_BYTES: u64 = 1024 * 1024;
const MAX_REPORT_BYTES: u64 = 2 * 1024 * 1024;

#[derive(Debug, Error)]
pub enum WorkflowError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Bridge(#[from] BridgeError),
    #[error("The temporary local request could not be cleaned up.")]
    RequestCleanup,
    #[error("The saved execution plan is missing or invalid.")]
    InvalidPlan,
    #[error("Review the current plan before running it.")]
    PlanReviewRequired,
    #[error("The requested generated artifact is unavailable.")]
    ArtifactUnavailable,
    #[error("The generated SVG did not pass the local display safety check.")]
    UnsafeSvg,
    #[error("A generated artifact exceeded its local display limit.")]
    ArtifactTooLarge,
    #[error("Local workflow data could not be read safely.")]
    Io,
}

#[derive(Clone, Debug, Serialize)]
pub struct PlanResult {
    pub report: BridgeReport,
    pub plan: Value,
    pub project: ProjectRecord,
}

#[derive(Clone, Debug, Serialize)]
pub struct RunResult {
    pub report: BridgeReport,
    pub artifacts: Vec<ArtifactSummary>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactSummary {
    pub task_id: String,
    pub diagram: String,
    pub svg_available: bool,
    pub qa_available: bool,
    pub report_available: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct ArtifactBundle {
    pub task_id: String,
    pub diagram: String,
    pub svg_data_url: String,
    pub qa_markdown: String,
    pub report: Value,
}

fn invoke_request(
    store: &ProjectStore,
    bridge: &BridgeRunner,
    project_id: &str,
    operation: BridgeOperation,
    request: &Value,
) -> Result<BridgeReport, WorkflowError> {
    let request_path = store.write_request(project_id, request)?;
    let project_dir = store.project_dir(project_id)?;
    let response = bridge.invoke(operation, Some(&project_dir), Some(&request_path));
    let cleanup = fs::remove_file(&request_path);
    match (response, cleanup) {
        (Ok(report), Ok(())) => Ok(report),
        (Ok(_), Err(_)) => Err(WorkflowError::RequestCleanup),
        (Err(error), _) => Err(error.into()),
    }
}

pub fn save_recipe(
    store: &ProjectStore,
    bridge: &BridgeRunner,
    project_id: &str,
    review: Value,
    overwrite: bool,
) -> Result<BridgeReport, WorkflowError> {
    let project = store.read_project(project_id)?;
    let source = project.source.as_ref().ok_or(StoreError::InvalidSource)?;
    let request = json!({
        "schema_version": REQUEST_SCHEMA,
        "operation": "recipe",
        "source": format!("data/{}", source.stored_filename),
        "sheet": project.selected_sheet,
        "layout": project.selected_layout,
        "recipe": RECIPE_FILE,
        "review": review,
        "overwrite": overwrite,
    });
    invoke_request(store, bridge, project_id, BridgeOperation::Recipe, &request)
}

pub fn create_current_plan(
    store: &ProjectStore,
    bridge: &BridgeRunner,
    project_id: &str,
    selected_task_ids: Vec<String>,
    overwrite: bool,
) -> Result<PlanResult, WorkflowError> {
    if selected_task_ids.is_empty()
        || selected_task_ids
            .iter()
            .any(|value| value.trim().is_empty())
    {
        return Err(WorkflowError::InvalidPlan);
    }
    let request = json!({
        "schema_version": REQUEST_SCHEMA,
        "operation": "plan",
        "recipe": RECIPE_FILE,
        "plan": PLAN_FILE,
        "selected_task_ids": selected_task_ids,
        "overwrite": overwrite,
    });
    let report = invoke_request(store, bridge, project_id, BridgeOperation::Plan, &request)?;
    let plan = read_current_plan(store, project_id)?;
    let plan_id = plan
        .get("plan_id")
        .and_then(Value::as_str)
        .ok_or(WorkflowError::InvalidPlan)?
        .to_owned();
    let project = store.set_latest_plan_id(project_id, Some(plan_id))?;
    Ok(PlanResult {
        report,
        plan,
        project,
    })
}

pub fn run_current_plan(
    store: &ProjectStore,
    bridge: &BridgeRunner,
    project_id: &str,
    plan_reviewed: bool,
    overwrite: bool,
) -> Result<RunResult, WorkflowError> {
    if !plan_reviewed {
        return Err(WorkflowError::PlanReviewRequired);
    }
    let project = store.read_project(project_id)?;
    let plan = read_current_plan(store, project_id)?;
    if project.latest_plan_id.as_deref() != plan.get("plan_id").and_then(Value::as_str) {
        return Err(WorkflowError::InvalidPlan);
    }
    let request = json!({
        "schema_version": REQUEST_SCHEMA,
        "operation": "run",
        "recipe": RECIPE_FILE,
        "plan": PLAN_FILE,
        "overwrite": overwrite,
    });
    let report = invoke_request(store, bridge, project_id, BridgeOperation::Run, &request)?;
    let artifacts = if matches!(report.status.as_str(), "ready" | "review") {
        list_artifacts(store, project_id)?
    } else {
        Vec::new()
    };
    Ok(RunResult { report, artifacts })
}

pub fn run_screening(
    store: &ProjectStore,
    bridge: &BridgeRunner,
    project_id: &str,
) -> Result<BridgeReport, WorkflowError> {
    let project = store.read_project(project_id)?;
    let plan = read_current_plan(store, project_id)?;
    let current_plan_id = plan
        .get("plan_id")
        .and_then(Value::as_str)
        .ok_or(WorkflowError::InvalidPlan)?;
    if project.latest_plan_id.as_deref() != Some(current_plan_id)
        || plan.get("status").and_then(Value::as_str) != Some("ready")
    {
        return Err(WorkflowError::InvalidPlan);
    }
    let request = json!({
        "schema_version": REQUEST_SCHEMA,
        "operation": "screen",
        "recipe": RECIPE_FILE,
    });
    invoke_request(store, bridge, project_id, BridgeOperation::Screen, &request)
}

pub fn read_current_plan(store: &ProjectStore, project_id: &str) -> Result<Value, WorkflowError> {
    let path = existing_project_member(store, project_id, PLAN_FILE)?;
    let plan: Value = read_json_bounded(&path, MAX_PLAN_BYTES)?;
    let valid = plan.get("schema_version").and_then(Value::as_str) == Some(PLAN_SCHEMA)
        && plan.get("plan_id").and_then(Value::as_str).is_some()
        && plan.get("tasks").and_then(Value::as_array).is_some();
    if !valid {
        return Err(WorkflowError::InvalidPlan);
    }
    Ok(plan)
}

pub fn list_artifacts(
    store: &ProjectStore,
    project_id: &str,
) -> Result<Vec<ArtifactSummary>, WorkflowError> {
    let plan = read_current_plan(store, project_id)?;
    let tasks = plan["tasks"].as_array().ok_or(WorkflowError::InvalidPlan)?;
    tasks
        .iter()
        .map(|task| {
            let task_id = task
                .get("id")
                .and_then(Value::as_str)
                .ok_or(WorkflowError::InvalidPlan)?;
            let diagram = task
                .get("diagram")
                .and_then(Value::as_str)
                .ok_or(WorkflowError::InvalidPlan)?;
            let outputs = expected_outputs(task, task_id)?;
            Ok(ArtifactSummary {
                task_id: task_id.to_owned(),
                diagram: diagram.to_owned(),
                svg_available: existing_output_path(store, project_id, outputs.svg.as_str())
                    .is_ok(),
                qa_available: existing_output_path(store, project_id, outputs.qa.as_str()).is_ok(),
                report_available: existing_output_path(store, project_id, outputs.report.as_str())
                    .is_ok(),
            })
        })
        .collect()
}

pub fn load_artifact(
    store: &ProjectStore,
    project_id: &str,
    task_id: &str,
) -> Result<ArtifactBundle, WorkflowError> {
    let plan = read_current_plan(store, project_id)?;
    let task = plan["tasks"]
        .as_array()
        .and_then(|tasks| {
            tasks
                .iter()
                .find(|task| task.get("id").and_then(Value::as_str) == Some(task_id))
        })
        .ok_or(WorkflowError::ArtifactUnavailable)?;
    let diagram = task
        .get("diagram")
        .and_then(Value::as_str)
        .ok_or(WorkflowError::InvalidPlan)?;
    let outputs = expected_outputs(task, task_id)?;
    let svg_path = existing_output_path(store, project_id, &outputs.svg)?;
    let qa_path = existing_output_path(store, project_id, &outputs.qa)?;
    let report_path = existing_output_path(store, project_id, &outputs.report)?;
    let svg = read_text_bounded(&svg_path, MAX_SVG_BYTES)?;
    validate_svg(&svg)?;
    let qa_markdown = read_text_bounded(&qa_path, MAX_QA_BYTES)?;
    let report = read_json_bounded(&report_path, MAX_REPORT_BYTES)?;
    Ok(ArtifactBundle {
        task_id: task_id.to_owned(),
        diagram: diagram.to_owned(),
        svg_data_url: format!(
            "data:image/svg+xml;base64,{}",
            BASE64_STANDARD.encode(svg.as_bytes())
        ),
        qa_markdown,
        report,
    })
}

struct ExpectedOutputs {
    svg: String,
    qa: String,
    report: String,
}

fn expected_outputs(task: &Value, task_id: &str) -> Result<ExpectedOutputs, WorkflowError> {
    if !safe_task_id(task_id) {
        return Err(WorkflowError::InvalidPlan);
    }
    let outputs = task
        .get("expected_outputs")
        .and_then(Value::as_array)
        .ok_or(WorkflowError::InvalidPlan)?;
    let find = |suffix: &str| {
        outputs
            .iter()
            .filter_map(Value::as_str)
            .find(|value| value.starts_with(&format!("{task_id}/")) && value.ends_with(suffix))
            .map(str::to_owned)
            .ok_or(WorkflowError::ArtifactUnavailable)
    };
    Ok(ExpectedOutputs {
        svg: find(".svg")?,
        qa: find(".qa.md")?,
        report: find(".report.json")?,
    })
}

fn safe_task_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 100
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn existing_output_path(
    store: &ProjectStore,
    project_id: &str,
    expected_output: &str,
) -> Result<PathBuf, WorkflowError> {
    existing_project_member(
        store,
        project_id,
        &format!("{OUTPUT_DIRECTORY}/{expected_output}"),
    )
}

fn existing_project_member(
    store: &ProjectStore,
    project_id: &str,
    relative: &str,
) -> Result<PathBuf, WorkflowError> {
    let lexical = project_member(store, project_id, relative)?;
    let project = store.project_dir(project_id)?;
    let canonical_project = fs::canonicalize(&project).map_err(|_| WorkflowError::Io)?;
    let canonical_member =
        fs::canonicalize(&lexical).map_err(|_| WorkflowError::ArtifactUnavailable)?;
    if !canonical_member.starts_with(&canonical_project) {
        return Err(WorkflowError::ArtifactUnavailable);
    }
    Ok(canonical_member)
}

fn project_member(
    store: &ProjectStore,
    project_id: &str,
    relative: &str,
) -> Result<PathBuf, WorkflowError> {
    let root = store.project_dir(project_id)?;
    let relative_path = Path::new(relative);
    if relative_path.is_absolute()
        || relative_path.components().any(|component| {
            matches!(
                component,
                std::path::Component::ParentDir | std::path::Component::Prefix(_)
            )
        })
    {
        return Err(WorkflowError::InvalidPlan);
    }
    let path = root.join(relative_path);
    if !path.starts_with(&root) {
        return Err(WorkflowError::InvalidPlan);
    }
    Ok(path)
}

fn read_text_bounded(path: &Path, limit: u64) -> Result<String, WorkflowError> {
    let metadata = fs::symlink_metadata(path).map_err(|_| WorkflowError::Io)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(WorkflowError::ArtifactUnavailable);
    }
    if metadata.len() > limit {
        return Err(WorkflowError::ArtifactTooLarge);
    }
    let mut text = String::with_capacity(metadata.len() as usize);
    BufReader::new(File::open(path).map_err(|_| WorkflowError::Io)?)
        .take(limit + 1)
        .read_to_string(&mut text)
        .map_err(|_| WorkflowError::Io)?;
    if text.len() as u64 > limit {
        return Err(WorkflowError::ArtifactTooLarge);
    }
    Ok(text)
}

fn read_json_bounded(path: &Path, limit: u64) -> Result<Value, WorkflowError> {
    let text = read_text_bounded(path, limit)?;
    serde_json::from_str(&text).map_err(|_| WorkflowError::InvalidPlan)
}

fn validate_svg(svg: &str) -> Result<(), WorkflowError> {
    let lower = svg.to_ascii_lowercase();
    if !lower.contains("<svg")
        || [
            "<script",
            "<foreignobject",
            "<!entity",
            "<?xml-stylesheet",
            "javascript:",
            "@import",
        ]
        .iter()
        .any(|token| lower.contains(token))
    {
        return Err(WorkflowError::UnsafeSvg);
    }
    let href = Regex::new(r#"(?i)(?:xlink:)?href\s*=\s*["']([^"']+)["']"#)
        .map_err(|_| WorkflowError::UnsafeSvg)?;
    if href
        .captures_iter(svg)
        .any(|capture| !capture[1].starts_with('#'))
    {
        return Err(WorkflowError::UnsafeSvg);
    }
    for (index, _) in lower.match_indices("url(") {
        let target = lower[index + 4..].trim_start_matches(|character: char| {
            character.is_ascii_whitespace() || matches!(character, '\'' | '"')
        });
        if !target.starts_with('#') {
            return Err(WorkflowError::UnsafeSvg);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::process::Command;

    fn source_bridge() -> BridgeRunner {
        BridgeRunner::for_app_mode(true).unwrap()
    }

    fn write_mixed_unit_workbook(repository: &Path, target: &Path) {
        let python = option_env!("GEOSKILLS_DESKTOP_SOURCE_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("python"));
        let tests = repository
            .join("apps")
            .join("desktop")
            .join("backend")
            .join("tests");
        let script = concat!(
            "import sys; from pathlib import Path; ",
            "sys.path.insert(0, sys.argv[2]); ",
            "from test_bridge_contract import write_mixed_unit_transposed_workbook; ",
            "write_mixed_unit_transposed_workbook(Path(sys.argv[1]))"
        );
        let status = Command::new(python)
            .arg("-c")
            .arg(script)
            .arg(target)
            .arg(tests)
            .status()
            .expect("the source-mode Python interpreter should start");
        assert!(
            status.success(),
            "the mixed-unit workbook fixture should be created"
        );
    }

    fn sha256(path: &Path) -> String {
        let bytes = fs::read(path).unwrap();
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        format!("{:x}", hasher.finalize())
    }

    fn inspect_current_source(
        store: &ProjectStore,
        bridge: &BridgeRunner,
        project_id: &str,
    ) -> BridgeReport {
        let project = store.read_project(project_id).unwrap();
        let source = project.source.as_ref().unwrap();
        let request = json!({
            "schema_version": REQUEST_SCHEMA,
            "operation": "inspect",
            "source": format!("data/{}", source.stored_filename),
            "sheet": project.selected_sheet,
            "layout": project.selected_layout,
        });
        invoke_request(
            store,
            bridge,
            project_id,
            BridgeOperation::Inspect,
            &request,
        )
        .unwrap()
    }

    #[test]
    fn svg_display_check_allows_fragments_and_rejects_external_links() {
        assert!(validate_svg(r##"<svg><use xlink:href="#glyph" /></svg>"##).is_ok());
        assert!(
            validate_svg(r#"<svg><image href="https://example.invalid/a.png" /></svg>"#).is_err()
        );
        assert!(validate_svg(r#"<svg><script>alert(1)</script></svg>"#).is_err());
    }

    #[test]
    fn artifact_lookup_rejects_path_like_task_ids() {
        assert!(!safe_task_id("../outside"));
        assert!(!safe_task_id("C:\\outside"));
        assert!(safe_task_id("ree-main_1"));
    }

    #[test]
    fn source_mode_review_plan_run_and_artifact_round_trip() {
        let repository = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .and_then(Path::parent)
            .unwrap()
            .to_path_buf();
        let synthetic = repository
            .join("skills")
            .join("geoskills")
            .join("examples")
            .join("synthetic_ree_data.csv");
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("managed-data"));
        store.initialize().unwrap();
        let project = store.create_project("Gate 3 REE").unwrap();
        store.import_source(&project.id, &synthetic, false).unwrap();
        store.select_layout(&project.id, "row-per-sample").unwrap();
        let mapping = ["La", "Ce", "Pr", "Nd", "Sm"]
            .into_iter()
            .map(|element| (element.to_owned(), Value::String(format!("{element}_ppm"))))
            .collect::<serde_json::Map<String, Value>>();
        let review = json!({
            "sample_id": "Sample",
            "group": "Group",
            "mapping": mapping,
            "units": {
                "La": "ppm", "Ce": "ppm", "Pr": "ppm", "Nd": "ppm", "Sm": "ppm"
            },
            "output_directory": OUTPUT_DIRECTORY,
            "report_profile": "shareable",
            "presets": {},
            "confirmations": {
                "input_structure_reviewed": true,
                "column_mapping_reviewed": true,
                "units_reviewed": true,
                "plotted_data_export_reviewed": true
            },
            "tasks": [{
                "id": "ree-main",
                "diagram": "ree",
                "stem": "figure-ree",
                "preset": "review-preview",
                "parameters": {
                    "reference": "chondrite-sm89",
                    "elements": ["La", "Ce", "Pr", "Nd", "Sm"],
                    "groups": "all"
                },
                "confirmations": {}
            }]
        });
        let bridge = source_bridge();

        let recipe_report = save_recipe(&store, &bridge, &project.id, review, false).unwrap();
        assert_eq!(recipe_report.status, "ready");
        assert!(
            store
                .project_dir(&project.id)
                .unwrap()
                .join(RECIPE_FILE)
                .is_file()
        );

        let planned = create_current_plan(
            &store,
            &bridge,
            &project.id,
            vec!["ree-main".to_owned()],
            false,
        )
        .unwrap();
        assert_eq!(planned.report.status, "ready");
        assert_eq!(planned.plan["status"], "ready");
        let screening = run_screening(&store, &bridge, &project.id).unwrap();
        assert_eq!(screening.status, "ready");
        assert_eq!(screening.result["available"], false);
        assert_eq!(screening.result["x"], "SiO2");
        assert_eq!(screening.result["maximum_variables"], 32);
        assert_eq!(screening.result["maximum_results"], 8);
        assert!(matches!(
            run_current_plan(&store, &bridge, &project.id, false, false),
            Err(WorkflowError::PlanReviewRequired)
        ));

        let completed = run_current_plan(&store, &bridge, &project.id, true, false).unwrap();
        assert_eq!(completed.report.status, "ready");
        assert_eq!(completed.artifacts.len(), 1);
        let artifact = load_artifact(&store, &project.id, "ree-main").unwrap();
        assert!(
            artifact
                .svg_data_url
                .starts_with("data:image/svg+xml;base64,")
        );
        assert!(artifact.qa_markdown.starts_with('#'));
        assert!(artifact.qa_markdown.len() > 100);
        assert_eq!(artifact.report["status"], "ready");
    }

    #[test]
    fn round2_source_mode_mixed_units_and_project_lifecycle_end_to_end() {
        let repository = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .and_then(Path::parent)
            .unwrap()
            .to_path_buf();
        let temp = tempfile::tempdir().unwrap();
        let managed_root = temp.path().join("managed-data");
        let external_source = temp.path().join("mixed-units.xlsx");
        write_mixed_unit_workbook(&repository, &external_source);
        let external_hash = sha256(&external_source);

        let store = ProjectStore::new(managed_root.clone());
        store.initialize().unwrap();
        let created = store.create_project("Round 2 mixed units").unwrap();
        let renamed = store
            .rename_project(&created.id, "Round 2 renamed mixed-unit project")
            .unwrap();
        assert_eq!(renamed.id, created.id);
        assert_eq!(renamed.title, "Round 2 renamed mixed-unit project");
        assert!(store.rename_project(&created.id, " \n ").is_err());

        let restarted = ProjectStore::new(managed_root.clone());
        assert_eq!(restarted.list_projects().unwrap(), vec![renamed.clone()]);
        let (imported, replaced) = restarted
            .import_source(&created.id, &external_source, false)
            .unwrap();
        assert!(!replaced);
        assert_eq!(imported.source.as_ref().unwrap().sha256, external_hash);

        let bridge = source_bridge();
        let inspected = inspect_current_source(&restarted, &bridge, &created.id);
        assert_eq!(inspected.status, "ready");
        assert_eq!(
            inspected.result["source"]["layout"],
            "column_per_sample_transposed"
        );
        let recognized = inspected.result["recognized_analytes"].as_array().unwrap();
        assert_eq!(recognized.len(), 47);
        let wt_count = recognized
            .iter()
            .filter(|item| {
                item["explicit_unit"] == "wt%" && item["unit_status"] == "confirmed_from_header"
            })
            .count();
        let ppm_count = recognized
            .iter()
            .filter(|item| {
                item["explicit_unit"] == "ppm" && item["unit_status"] == "confirmed_from_header"
            })
            .count();
        assert_eq!((wt_count, ppm_count), (12, 35));
        assert_eq!(inspected.result["quality"]["unknown_unit_count"], 0);
        assert_eq!(inspected.result["quality"]["unit_conflict_count"], 0);

        let mut mapping = serde_json::Map::new();
        let mut units = serde_json::Map::new();
        for item in recognized {
            let canonical = item["canonical"].as_str().unwrap();
            mapping.insert(canonical.to_owned(), item["source_column"].clone());
            units.insert(canonical.to_owned(), item["explicit_unit"].clone());
        }
        let review = json!({
            "sample_id": inspected.result["sample_column_suggestion"],
            "group": inspected.result["group_column_candidates"][0],
            "mapping": mapping,
            "units": units,
            "output_directory": OUTPUT_DIRECTORY,
            "report_profile": "shareable",
            "presets": {},
            "confirmations": {
                "input_structure_reviewed": true,
                "column_mapping_reviewed": true,
                "units_reviewed": true,
                "plotted_data_export_reviewed": true
            },
            "tasks": [{
                "id": "harker-main",
                "diagram": "harker",
                "stem": "figure-harker",
                "preset": "review-preview",
                "parameters": {
                    "x": "SiO2",
                    "y": ["TiO2", "Al2O3"],
                    "groups": "all"
                },
                "confirmations": {}
            }]
        });

        let recipe = save_recipe(&restarted, &bridge, &created.id, review, false).unwrap();
        assert_eq!(recipe.status, "ready");
        let planned = create_current_plan(
            &restarted,
            &bridge,
            &created.id,
            vec!["harker-main".to_owned()],
            false,
        )
        .unwrap();
        assert_eq!(planned.plan["status"], "ready");
        assert_eq!(planned.plan["column_mapping"].as_array().unwrap().len(), 47);
        assert!(matches!(
            run_current_plan(&restarted, &bridge, &created.id, false, false),
            Err(WorkflowError::PlanReviewRequired)
        ));

        let completed = run_current_plan(&restarted, &bridge, &created.id, true, false).unwrap();
        assert_eq!(completed.report.status, "ready");
        assert_eq!(completed.artifacts.len(), 1);
        let artifact = load_artifact(&restarted, &created.id, "harker-main").unwrap();
        assert!(
            artifact
                .svg_data_url
                .starts_with("data:image/svg+xml;base64,")
        );
        assert!(artifact.qa_markdown.starts_with('#'));
        assert_eq!(artifact.report["status"], "ready");

        let removed = restarted.remove_project(&created.id).unwrap();
        assert_eq!(removed.id, created.id);
        assert!(restarted.list_projects().unwrap().is_empty());
        assert_eq!(
            restarted.list_removed_projects().unwrap(),
            vec![removed.clone()]
        );
        let restored = restarted.restore_project(&created.id).unwrap();
        assert_eq!(restored.id, created.id);
        assert_eq!(restored.title, renamed.title);
        assert_eq!(restarted.list_projects().unwrap(), vec![restored]);
        assert!(load_artifact(&restarted, &created.id, "harker-main").is_ok());
        assert_eq!(sha256(&external_source), external_hash);
    }
}
