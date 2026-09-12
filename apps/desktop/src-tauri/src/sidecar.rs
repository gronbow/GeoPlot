use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;
use wait_timeout::ChildExt;

pub const DESKTOP_REPORT_SCHEMA: &str = "geoskills.desktop-report/v1";
pub const INSPECT_TIMEOUT: Duration = Duration::from_secs(30);
pub const SCREEN_TIMEOUT: Duration = Duration::from_secs(90);
pub const PLAN_TIMEOUT: Duration = Duration::from_secs(90);
pub const RUN_TIMEOUT: Duration = Duration::from_secs(300);
pub const STDOUT_LIMIT: usize = 4 * 1024 * 1024;
pub const STDERR_LIMIT: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BridgeOperation {
    Version,
    Capabilities,
    Inspect,
    Recipe,
    Screen,
    Plan,
    Run,
}

impl BridgeOperation {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Version => "version",
            Self::Capabilities => "capabilities",
            Self::Inspect => "inspect",
            Self::Recipe => "recipe",
            Self::Screen => "screen",
            Self::Plan => "plan",
            Self::Run => "run",
        }
    }

    fn timeout(self) -> Duration {
        match self {
            Self::Version | Self::Capabilities | Self::Inspect => INSPECT_TIMEOUT,
            Self::Recipe | Self::Plan => PLAN_TIMEOUT,
            Self::Screen => SCREEN_TIMEOUT,
            Self::Run => RUN_TIMEOUT,
        }
    }
}

#[derive(Clone, Debug)]
enum BridgeExecutable {
    Source { python: PathBuf, script: PathBuf },
    Frozen { executable: PathBuf },
}

#[derive(Clone, Debug)]
pub struct BridgeRunner {
    executable: BridgeExecutable,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BridgeReport {
    pub schema_version: String,
    pub operation: String,
    pub status: String,
    pub engine: Value,
    pub result: Value,
    pub issues: Vec<Value>,
}

#[derive(Debug, Error)]
pub enum BridgeError {
    #[error("The GeoSkills engine could not be started.")]
    Start,
    #[error("The GeoSkills engine exceeded its safe time limit.")]
    Timeout,
    #[error("The GeoSkills engine returned too much output.")]
    OutputOverflow,
    #[error("The GeoSkills engine returned an invalid response.")]
    InvalidResponse,
    #[error("The desktop app and GeoSkills engine use incompatible schemas.")]
    IncompatibleSchema,
    #[error("The GeoSkills engine operation did not match the request.")]
    OperationMismatch,
    #[error("The GeoSkills engine could not read the local request.")]
    Io,
}

#[derive(Debug)]
struct Captured {
    bytes: Vec<u8>,
    overflowed: bool,
}

impl BridgeRunner {
    pub fn source(python: PathBuf, script: PathBuf) -> Self {
        Self {
            executable: BridgeExecutable::Source { python, script },
        }
    }

    pub fn frozen(executable: PathBuf) -> Self {
        Self {
            executable: BridgeExecutable::Frozen { executable },
        }
    }

    pub fn for_app_mode(debug_mode: bool) -> Result<Self, BridgeError> {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if debug_mode {
            let repository = manifest
                .parent()
                .and_then(Path::parent)
                .and_then(Path::parent)
                .ok_or(BridgeError::Start)?;
            let script = repository
                .join("apps")
                .join("desktop")
                .join("backend")
                .join("geoskills_desktop_bridge.py");
            if !script.is_file() {
                return Err(BridgeError::Start);
            }
            let python = option_env!("GEOSKILLS_DESKTOP_SOURCE_PYTHON")
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    let local = repository
                        .join(".venv")
                        .join(if cfg!(windows) { "Scripts" } else { "bin" })
                        .join(if cfg!(windows) {
                            "python.exe"
                        } else {
                            "python"
                        });
                    if local.is_file() {
                        local
                    } else {
                        PathBuf::from("python")
                    }
                });
            Ok(Self::source(python, script))
        } else {
            let executable_name = if cfg!(windows) {
                "geoskills-desktop-bridge.exe"
            } else {
                "geoskills-desktop-bridge"
            };
            let current = std::env::current_exe().map_err(|_| BridgeError::Start)?;
            let executable = current
                .parent()
                .ok_or(BridgeError::Start)?
                .join(executable_name);
            Ok(Self::frozen(executable))
        }
    }

    pub fn for_app() -> Result<Self, BridgeError> {
        Self::for_app_mode(cfg!(debug_assertions))
    }

    pub fn invoke(
        &self,
        operation: BridgeOperation,
        project: Option<&Path>,
        request: Option<&Path>,
    ) -> Result<BridgeReport, BridgeError> {
        let requires_request = matches!(
            operation,
            BridgeOperation::Inspect
                | BridgeOperation::Recipe
                | BridgeOperation::Screen
                | BridgeOperation::Plan
                | BridgeOperation::Run
        );
        if requires_request != (project.is_some() && request.is_some()) {
            return Err(BridgeError::InvalidResponse);
        }
        let mut command = match &self.executable {
            BridgeExecutable::Source { python, script } => {
                let mut command = Command::new(python);
                command.arg(script);
                command
            }
            BridgeExecutable::Frozen { executable } => Command::new(executable),
        };
        command.arg(operation.as_str());
        if let (Some(project), Some(request)) = (project, request) {
            command.arg("--project").arg(project);
            command.arg("--request").arg(request);
        }
        command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command.spawn().map_err(|_| BridgeError::Start)?;
        let stdout = child.stdout.take().ok_or(BridgeError::Io)?;
        let stderr = child.stderr.take().ok_or(BridgeError::Io)?;
        let stdout_reader = thread::spawn(move || read_capped(stdout, STDOUT_LIMIT));
        let stderr_reader = thread::spawn(move || read_capped(stderr, STDERR_LIMIT));

        let status = match child
            .wait_timeout(operation.timeout())
            .map_err(|_| BridgeError::Io)?
        {
            Some(status) => status,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = stdout_reader.join();
                let _ = stderr_reader.join();
                return Err(BridgeError::Timeout);
            }
        };
        let stdout = stdout_reader
            .join()
            .map_err(|_| BridgeError::Io)?
            .map_err(|_| BridgeError::Io)?;
        let stderr = stderr_reader
            .join()
            .map_err(|_| BridgeError::Io)?
            .map_err(|_| BridgeError::Io)?;
        if stdout.overflowed || stderr.overflowed {
            return Err(BridgeError::OutputOverflow);
        }
        let text = std::str::from_utf8(&stdout.bytes).map_err(|_| BridgeError::InvalidResponse)?;
        let report = parse_report(text, operation)?;
        if !status.success() && report.status == "ready" {
            return Err(BridgeError::InvalidResponse);
        }
        Ok(report)
    }
}

fn read_capped<R: Read>(mut reader: R, limit: usize) -> io::Result<Captured> {
    let mut captured = Vec::with_capacity(limit.min(64 * 1024));
    let mut overflowed = false;
    let mut chunk = [0_u8; 16 * 1024];
    loop {
        let count = reader.read(&mut chunk)?;
        if count == 0 {
            break;
        }
        let remaining = limit.saturating_sub(captured.len());
        let keep = remaining.min(count);
        captured.extend_from_slice(&chunk[..keep]);
        if keep < count {
            overflowed = true;
        }
    }
    Ok(Captured {
        bytes: captured,
        overflowed,
    })
}

pub fn parse_report(
    text: &str,
    expected_operation: BridgeOperation,
) -> Result<BridgeReport, BridgeError> {
    let report: BridgeReport =
        serde_json::from_str(text.trim()).map_err(|_| BridgeError::InvalidResponse)?;
    if report.schema_version != DESKTOP_REPORT_SCHEMA {
        return Err(BridgeError::IncompatibleSchema);
    }
    if report.operation != expected_operation.as_str() {
        return Err(BridgeError::OperationMismatch);
    }
    if !matches!(
        report.status.as_str(),
        "ready" | "needs_confirmation" | "review" | "blocked" | "error"
    ) || !report.engine.is_object()
        || !report.result.is_object()
    {
        return Err(BridgeError::InvalidResponse);
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project_store::ProjectStore;

    fn report(status: &str) -> String {
        serde_json::json!({
            "schema_version": DESKTOP_REPORT_SCHEMA,
            "operation": "inspect",
            "status": status,
            "engine": {},
            "result": {},
            "issues": []
        })
        .to_string()
    }

    #[test]
    fn valid_report_schema_is_accepted() {
        assert_eq!(
            parse_report(&report("ready"), BridgeOperation::Inspect)
                .unwrap()
                .status,
            "ready"
        );
    }

    #[test]
    fn unknown_schema_status_and_operation_are_rejected() {
        let wrong_schema = report("ready").replace(DESKTOP_REPORT_SCHEMA, "unknown/v1");
        assert!(matches!(
            parse_report(&wrong_schema, BridgeOperation::Inspect),
            Err(BridgeError::IncompatibleSchema)
        ));
        assert!(matches!(
            parse_report(&report("surprise"), BridgeOperation::Inspect),
            Err(BridgeError::InvalidResponse)
        ));
        assert!(matches!(
            parse_report(&report("ready"), BridgeOperation::Run),
            Err(BridgeError::OperationMismatch)
        ));
    }

    #[test]
    fn non_json_multiple_documents_and_unknown_fields_are_rejected() {
        assert!(parse_report("not json", BridgeOperation::Inspect).is_err());
        assert!(
            parse_report(
                &format!("{}\n{}", report("ready"), report("ready")),
                BridgeOperation::Inspect
            )
            .is_err()
        );
        let extra = report("ready").replace("\"issues\":[]", "\"issues\":[],\"extra\":1");
        assert!(parse_report(&extra, BridgeOperation::Inspect).is_err());
    }

    #[test]
    fn capped_reader_drains_but_does_not_retain_overflow() {
        let bytes = vec![b'x'; 4096];
        let captured = read_capped(bytes.as_slice(), 128).unwrap();
        assert!(captured.overflowed);
        assert_eq!(captured.bytes.len(), 128);
    }

    #[test]
    fn exit_code_two_report_status_is_parseable() {
        let parsed = parse_report(&report("needs_confirmation"), BridgeOperation::Inspect).unwrap();
        assert_eq!(parsed.status, "needs_confirmation");
    }

    #[test]
    fn source_mode_copies_and_inspects_synthetic_data() {
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
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Synthetic REE").unwrap();
        let (project, _) = store.import_source(&project.id, &synthetic, false).unwrap();
        let source = project.source.unwrap();
        let request = serde_json::json!({
            "schema_version": "geoskills.desktop-request/v1",
            "operation": "inspect",
            "source": format!("data/{}", source.stored_filename),
            "sheet": null,
            "layout": "auto"
        });
        let request_path = store.write_request(&project.id, &request).unwrap();
        let project_dir = store.project_dir(&project.id).unwrap();

        let response = BridgeRunner::for_app_mode(true)
            .unwrap()
            .invoke(
                BridgeOperation::Inspect,
                Some(&project_dir),
                Some(&request_path),
            )
            .unwrap();

        assert_eq!(response.status, "ready");
        assert_eq!(response.result["row_count"], 3);
        assert_eq!(response.result["sample_column_suggestion"], "Sample");
        assert_eq!(
            response.result["recognized_analytes"]
                .as_array()
                .unwrap()
                .len(),
            14
        );
    }
}
