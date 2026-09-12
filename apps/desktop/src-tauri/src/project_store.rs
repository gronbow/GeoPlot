use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use chrono::{SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};
use thiserror::Error;
use uuid::Uuid;

#[cfg(test)]
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

pub const PROJECT_SCHEMA_VERSION: &str = "geoskills.desktop-project/v1";
pub const INDEX_SCHEMA_VERSION: &str = "geoskills.desktop-index/v1";
pub const MAX_INPUT_BYTES: u64 = 20 * 1024 * 1024;
pub const MAX_REQUEST_BYTES: usize = 256 * 1024;
const MAX_METADATA_BYTES: u64 = 512 * 1024;
const ALLOWED_EXTENSIONS: [&str; 3] = ["csv", "txt", "xlsx"];

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("Project identifier is invalid.")]
    InvalidProjectId,
    #[error("Project title must contain 1 to 120 visible characters.")]
    InvalidTitle,
    #[error("The local project was not found.")]
    ProjectNotFound,
    #[error("The local project entry is linked or uses a Windows reparse point.")]
    LinkedProject,
    #[error("The project move was rolled back because the project index could not be updated.")]
    ConsistencyRollback,
    #[error(
        "The project index update and directory rollback both failed; manual recovery is required."
    )]
    ConsistencyRollbackFailed,
    #[error("The selected source must be a regular, non-linked file.")]
    InvalidSource,
    #[error("Only XLSX, CSV, and TXT files are supported.")]
    UnsupportedExtension,
    #[error("The selected source exceeds the 20 MiB input limit.")]
    InputTooLarge,
    #[error("This project already contains a source. Explicit replacement is required.")]
    ReplacementRequired,
    #[error("The selected sheet value is invalid.")]
    InvalidSheet,
    #[error("The local project metadata is invalid or incompatible.")]
    InvalidMetadata,
    #[error("The request is too large.")]
    RequestTooLarge,
    #[error("Local project storage failed safely.")]
    Io(#[from] std::io::Error),
    #[error("Local project metadata could not be encoded.")]
    Json(#[from] serde_json::Error),
    #[error("The user-local managed data directory is unavailable.")]
    ManagedDataUnavailable,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SourceRecord {
    pub stored_filename: String,
    pub original_basename: String,
    pub sha256: String,
    pub size_bytes: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ProjectRecord {
    pub schema_version: String,
    pub id: String,
    pub title: String,
    pub created_at: String,
    pub updated_at: String,
    pub source: Option<SourceRecord>,
    pub selected_sheet: Option<Value>,
    #[serde(default = "default_layout")]
    pub selected_layout: String,
    pub latest_plan_id: Option<String>,
}

fn default_layout() -> String {
    "auto".to_owned()
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectIndex {
    schema_version: String,
    project_ids: Vec<String>,
    #[serde(default)]
    removed_project_ids: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct ProjectStore {
    root: PathBuf,
    #[cfg(test)]
    fail_next_index_write: Arc<AtomicBool>,
}

impl ProjectStore {
    pub fn from_app(app: &AppHandle) -> Result<Self, StoreError> {
        let scoped_local_data = app
            .path()
            .app_local_data_dir()
            .map_err(|_| StoreError::ManagedDataUnavailable)?;
        #[cfg(windows)]
        let managed_root = {
            let local_data = scoped_local_data
                .parent()
                .ok_or(StoreError::ManagedDataUnavailable)?;
            let programs = local_data.join("Programs");
            let metadata =
                fs::symlink_metadata(&programs).map_err(|_| StoreError::ManagedDataUnavailable)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(StoreError::ManagedDataUnavailable);
            }
            programs.join("GeoSkillsDesktopData")
        };
        #[cfg(not(windows))]
        let managed_root = scoped_local_data.join("GeoSkillsDesktop");
        Ok(Self::new(managed_root))
    }

    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            #[cfg(test)]
            fail_next_index_write: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn initialize(&self) -> Result<(), StoreError> {
        fs::create_dir_all(self.projects_root())?;
        fs::create_dir_all(self.removed_root())?;
        let index_path = self.index_path();
        if !index_path.exists() {
            self.write_index(&ProjectIndex {
                schema_version: INDEX_SCHEMA_VERSION.to_owned(),
                project_ids: Vec::new(),
                removed_project_ids: Vec::new(),
            })?;
        } else {
            self.read_index()?;
        }
        Ok(())
    }

    pub fn create_project(&self, title: &str) -> Result<ProjectRecord, StoreError> {
        let title = validate_title(title)?;
        self.initialize()?;
        let id = Uuid::new_v4().hyphenated().to_string();
        let project_dir = self.project_dir(&id)?;
        fs::create_dir(&project_dir)?;
        for directory in ["data", "recipe", "plans", "outputs", "requests", "cache"] {
            fs::create_dir(project_dir.join(directory))?;
        }
        let now = timestamp();
        let record = ProjectRecord {
            schema_version: PROJECT_SCHEMA_VERSION.to_owned(),
            id: id.clone(),
            title,
            created_at: now.clone(),
            updated_at: now,
            source: None,
            selected_sheet: None,
            selected_layout: default_layout(),
            latest_plan_id: None,
        };
        atomic_json_write(&project_dir.join("project.json"), &record)?;
        let mut index = self.read_index()?;
        index.project_ids.insert(0, id);
        self.write_index(&index)?;
        Ok(record)
    }

    pub fn list_projects(&self) -> Result<Vec<ProjectRecord>, StoreError> {
        self.initialize()?;
        let index = self.read_index()?;
        index
            .project_ids
            .iter()
            .map(|id| self.read_project(id))
            .collect()
    }

    pub fn list_removed_projects(&self) -> Result<Vec<ProjectRecord>, StoreError> {
        self.initialize()?;
        let index = self.read_index()?;
        index
            .removed_project_ids
            .iter()
            .map(|id| self.read_project_from(&self.removed_root(), id))
            .collect()
    }

    pub fn read_project(&self, project_id: &str) -> Result<ProjectRecord, StoreError> {
        self.read_project_from(&self.projects_root(), project_id)
    }

    pub fn rename_project(
        &self,
        project_id: &str,
        title: &str,
    ) -> Result<ProjectRecord, StoreError> {
        let title = validate_title(title)?;
        let mut project = self.read_project(project_id)?;
        project.title = title;
        project.updated_at = timestamp();
        self.write_project(&project)?;
        Ok(project)
    }

    pub fn remove_project(&self, project_id: &str) -> Result<ProjectRecord, StoreError> {
        self.initialize()?;
        validate_project_id(project_id)?;
        let mut index = self.read_index()?;
        let position = index
            .project_ids
            .iter()
            .position(|id| id == project_id)
            .ok_or(StoreError::ProjectNotFound)?;
        let source = self.project_dir(project_id)?;
        let target = self.removed_project_dir(project_id)?;
        validate_project_entry(&source)?;
        if target.exists() {
            return Err(StoreError::InvalidMetadata);
        }
        let project = self.read_project(project_id)?;

        fs::rename(&source, &target)?;
        index.project_ids.remove(position);
        index.removed_project_ids.insert(0, project_id.to_owned());
        if self.write_index(&index).is_err() {
            return match fs::rename(&target, &source) {
                Ok(()) => Err(StoreError::ConsistencyRollback),
                Err(_) => Err(StoreError::ConsistencyRollbackFailed),
            };
        }
        Ok(project)
    }

    pub fn restore_project(&self, project_id: &str) -> Result<ProjectRecord, StoreError> {
        self.initialize()?;
        validate_project_id(project_id)?;
        let mut index = self.read_index()?;
        let position = index
            .removed_project_ids
            .iter()
            .position(|id| id == project_id)
            .ok_or(StoreError::ProjectNotFound)?;
        let source = self.removed_project_dir(project_id)?;
        let target = self.project_dir(project_id)?;
        validate_project_entry(&source)?;
        if target.exists() {
            return Err(StoreError::InvalidMetadata);
        }
        let project = self.read_project_from(&self.removed_root(), project_id)?;

        fs::rename(&source, &target)?;
        index.removed_project_ids.remove(position);
        index.project_ids.insert(0, project_id.to_owned());
        if self.write_index(&index).is_err() {
            return match fs::rename(&target, &source) {
                Ok(()) => Err(StoreError::ConsistencyRollback),
                Err(_) => Err(StoreError::ConsistencyRollbackFailed),
            };
        }
        Ok(project)
    }

    fn read_project_from(
        &self,
        root: &Path,
        project_id: &str,
    ) -> Result<ProjectRecord, StoreError> {
        let path = project_dir_from(root, project_id)?.join("project.json");
        if !path.is_file() {
            return Err(StoreError::ProjectNotFound);
        }
        let record: ProjectRecord = read_bounded_json(&path)?;
        if record.schema_version != PROJECT_SCHEMA_VERSION || record.id != project_id {
            return Err(StoreError::InvalidMetadata);
        }
        Ok(record)
    }

    pub fn import_source(
        &self,
        project_id: &str,
        source_path: &Path,
        replace: bool,
    ) -> Result<(ProjectRecord, bool), StoreError> {
        let mut project = self.read_project(project_id)?;
        let source_metadata =
            fs::symlink_metadata(source_path).map_err(|_| StoreError::InvalidSource)?;
        if source_metadata.file_type().is_symlink() || !source_metadata.is_file() {
            return Err(StoreError::InvalidSource);
        }
        if source_metadata.len() > MAX_INPUT_BYTES {
            return Err(StoreError::InputTooLarge);
        }
        let extension = source_path
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            .filter(|value| ALLOWED_EXTENSIONS.contains(&value.as_str()))
            .ok_or(StoreError::UnsupportedExtension)?;
        let previous = project.source.clone();
        if previous.is_some() && !replace {
            return Err(StoreError::ReplacementRequired);
        }
        let stored_filename = format!("source.{extension}");
        let project_dir = self.project_dir(project_id)?;
        let target = contained_member(&project_dir, &PathBuf::from("data").join(&stored_filename))?;
        let (size_bytes, sha256) = atomic_copy_with_hash(source_path, &target)?;
        if size_bytes > MAX_INPUT_BYTES {
            return Err(StoreError::InputTooLarge);
        }
        if let Some(old) = previous.as_ref() {
            if old.stored_filename != stored_filename {
                let old_target = contained_member(
                    &project_dir,
                    &PathBuf::from("data").join(&old.stored_filename),
                )?;
                if old_target.is_file() {
                    fs::remove_file(old_target)?;
                }
            }
        }
        let original_basename = source_path
            .file_name()
            .and_then(|value| value.to_str())
            .filter(|value| !value.chars().any(char::is_control))
            .unwrap_or("source")
            .chars()
            .take(255)
            .collect();
        project.source = Some(SourceRecord {
            stored_filename,
            original_basename,
            sha256,
            size_bytes,
        });
        project.selected_sheet = None;
        project.selected_layout = default_layout();
        project.latest_plan_id = None;
        project.updated_at = timestamp();
        self.write_project(&project)?;
        Ok((project, previous.is_some()))
    }

    pub fn select_sheet(
        &self,
        project_id: &str,
        selected_sheet: Option<Value>,
    ) -> Result<ProjectRecord, StoreError> {
        let valid = match selected_sheet.as_ref() {
            None => true,
            Some(Value::String(value)) => !value.trim().is_empty() && value.len() <= 128,
            Some(Value::Number(value)) => value.as_u64().is_some(),
            _ => false,
        };
        if !valid {
            return Err(StoreError::InvalidSheet);
        }
        let mut project = self.read_project(project_id)?;
        project.selected_sheet = selected_sheet;
        project.updated_at = timestamp();
        self.write_project(&project)?;
        Ok(project)
    }

    pub fn select_layout(
        &self,
        project_id: &str,
        layout: &str,
    ) -> Result<ProjectRecord, StoreError> {
        if !matches!(layout, "auto" | "row-per-sample" | "analyte-per-row") {
            return Err(StoreError::InvalidMetadata);
        }
        let mut project = self.read_project(project_id)?;
        project.selected_layout = layout.to_owned();
        project.latest_plan_id = None;
        project.updated_at = timestamp();
        self.write_project(&project)?;
        Ok(project)
    }

    pub fn set_latest_plan_id(
        &self,
        project_id: &str,
        plan_id: Option<String>,
    ) -> Result<ProjectRecord, StoreError> {
        if plan_id.as_ref().is_some_and(|value| {
            value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit())
        }) {
            return Err(StoreError::InvalidMetadata);
        }
        let mut project = self.read_project(project_id)?;
        project.latest_plan_id = plan_id;
        project.updated_at = timestamp();
        self.write_project(&project)?;
        Ok(project)
    }

    pub fn project_dir(&self, project_id: &str) -> Result<PathBuf, StoreError> {
        project_dir_from(&self.projects_root(), project_id)
    }

    fn removed_project_dir(&self, project_id: &str) -> Result<PathBuf, StoreError> {
        project_dir_from(&self.removed_root(), project_id)
    }

    pub fn write_request<T: Serialize>(
        &self,
        project_id: &str,
        request: &T,
    ) -> Result<PathBuf, StoreError> {
        let project_dir = self.project_dir(project_id)?;
        if !project_dir.is_dir() {
            return Err(StoreError::ProjectNotFound);
        }
        let bytes = serde_json::to_vec(request)?;
        if bytes.len() > MAX_REQUEST_BYTES {
            return Err(StoreError::RequestTooLarge);
        }
        let path = project_dir
            .join("requests")
            .join(format!("{}.json", Uuid::new_v4().hyphenated()));
        atomic_bytes_write(&path, &bytes)?;
        Ok(path)
    }

    fn projects_root(&self) -> PathBuf {
        self.root.join("projects")
    }

    fn removed_root(&self) -> PathBuf {
        self.root.join("removed")
    }

    fn index_path(&self) -> PathBuf {
        self.root.join("index.json")
    }

    fn read_index(&self) -> Result<ProjectIndex, StoreError> {
        let index: ProjectIndex = read_bounded_json(&self.index_path())?;
        let all_ids = index
            .project_ids
            .iter()
            .chain(index.removed_project_ids.iter());
        let mut unique = std::collections::HashSet::new();
        if index.schema_version != INDEX_SCHEMA_VERSION
            || all_ids.clone().any(|id| validate_project_id(id).is_err())
            || all_ids.into_iter().any(|id| !unique.insert(id))
        {
            return Err(StoreError::InvalidMetadata);
        }
        Ok(index)
    }

    fn write_index(&self, index: &ProjectIndex) -> Result<(), StoreError> {
        #[cfg(test)]
        if self.fail_next_index_write.swap(false, Ordering::SeqCst) {
            return Err(StoreError::Io(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "simulated index failure",
            )));
        }
        atomic_json_write(&self.index_path(), index)
    }

    fn write_project(&self, project: &ProjectRecord) -> Result<(), StoreError> {
        let path = self.project_dir(&project.id)?.join("project.json");
        atomic_json_write(&path, project)
    }
}

pub fn validate_project_id(value: &str) -> Result<Uuid, StoreError> {
    let parsed = Uuid::parse_str(value).map_err(|_| StoreError::InvalidProjectId)?;
    if parsed.hyphenated().to_string() != value.to_ascii_lowercase() {
        return Err(StoreError::InvalidProjectId);
    }
    Ok(parsed)
}

fn project_dir_from(root: &Path, project_id: &str) -> Result<PathBuf, StoreError> {
    validate_project_id(project_id)?;
    let path = root.join(project_id);
    let normalized_root = absolute_normalize(root)?;
    let normalized_path = absolute_normalize(&path)?;
    if normalized_path == normalized_root || !normalized_path.starts_with(&normalized_root) {
        return Err(StoreError::InvalidProjectId);
    }
    Ok(path)
}

fn validate_project_entry(path: &Path) -> Result<(), StoreError> {
    let metadata = fs::symlink_metadata(path).map_err(|_| StoreError::ProjectNotFound)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(StoreError::LinkedProject);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(StoreError::LinkedProject);
        }
    }
    Ok(())
}

fn validate_title(value: &str) -> Result<String, StoreError> {
    let title = value.trim();
    if title.is_empty() || title.chars().count() > 120 || title.chars().any(char::is_control) {
        return Err(StoreError::InvalidTitle);
    }
    Ok(title.to_owned())
}

fn timestamp() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn absolute_normalize(path: &Path) -> Result<PathBuf, StoreError> {
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        Ok(std::env::current_dir()?.join(path))
    }
}

fn contained_member(root: &Path, relative: &Path) -> Result<PathBuf, StoreError> {
    if relative.is_absolute()
        || relative
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err(StoreError::InvalidMetadata);
    }
    let root = absolute_normalize(root)?;
    let member = root.join(relative);
    if !member.starts_with(&root) {
        return Err(StoreError::InvalidMetadata);
    }
    Ok(member)
}

fn read_bounded_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, StoreError> {
    let metadata = fs::metadata(path)?;
    if metadata.len() > MAX_METADATA_BYTES {
        return Err(StoreError::InvalidMetadata);
    }
    let file = File::open(path)?;
    serde_json::from_reader(BufReader::new(file)).map_err(|_| StoreError::InvalidMetadata)
}

fn atomic_json_write<T: Serialize>(path: &Path, value: &T) -> Result<(), StoreError> {
    let bytes = serde_json::to_vec_pretty(value)?;
    if bytes.len() as u64 > MAX_METADATA_BYTES {
        return Err(StoreError::InvalidMetadata);
    }
    atomic_bytes_write(path, &bytes)
}

fn atomic_bytes_write(path: &Path, bytes: &[u8]) -> Result<(), StoreError> {
    let parent = path.parent().ok_or(StoreError::InvalidMetadata)?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(".geoskills-{}.tmp", Uuid::new_v4().hyphenated()));
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    output.write_all(bytes)?;
    output.flush()?;
    output.sync_all()?;
    drop(output);
    atomic_replace(&temporary, path)
}

fn atomic_copy_with_hash(source: &Path, target: &Path) -> Result<(u64, String), StoreError> {
    let parent = target.parent().ok_or(StoreError::InvalidMetadata)?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(
        ".geoskills-import-{}.tmp",
        Uuid::new_v4().hyphenated()
    ));
    let input = File::open(source)?;
    let output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    let mut reader = BufReader::new(input);
    let mut writer = BufWriter::new(output);
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        total = total.saturating_add(count as u64);
        if total > MAX_INPUT_BYTES {
            drop(writer);
            let _ = fs::remove_file(&temporary);
            return Err(StoreError::InputTooLarge);
        }
        hasher.update(&buffer[..count]);
        writer.write_all(&buffer[..count])?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    drop(writer);
    atomic_replace(&temporary, target)?;
    Ok((total, format!("{:x}", hasher.finalize())))
}

fn atomic_replace(temporary: &Path, target: &Path) -> Result<(), StoreError> {
    if !target.exists() {
        fs::rename(temporary, target)?;
        return Ok(());
    }
    let parent = target.parent().ok_or(StoreError::InvalidMetadata)?;
    let backup = parent.join(format!(".geoskills-{}.bak", Uuid::new_v4().hyphenated()));
    fs::rename(target, &backup)?;
    match fs::rename(temporary, target) {
        Ok(()) => {
            fs::remove_file(backup)?;
            Ok(())
        }
        Err(error) => {
            let _ = fs::rename(&backup, target);
            let _ = fs::remove_file(temporary);
            Err(StoreError::Io(error))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_id_validation_rejects_paths_and_noncanonical_ids() {
        assert!(validate_project_id("../../outside").is_err());
        assert!(validate_project_id("C:\\temp\\project").is_err());
        assert!(validate_project_id("not-a-uuid").is_err());
        let id = Uuid::new_v4().hyphenated().to_string();
        assert_eq!(validate_project_id(&id).unwrap().to_string(), id);
    }

    #[test]
    fn project_paths_remain_below_the_store_root() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Safe project").unwrap();
        let path = store.project_dir(&project.id).unwrap();
        assert!(path.starts_with(temp.path().join("app-data").join("projects")));
    }

    #[test]
    fn import_copies_data_and_never_records_the_absolute_path() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Import test").unwrap();
        let source = temp.path().join("private-lab-file.csv");
        fs::write(&source, b"Sample,SiO2_wt%\nA,50\n").unwrap();

        let (updated, replaced) = store.import_source(&project.id, &source, false).unwrap();

        assert!(!replaced);
        let record = updated.source.unwrap();
        assert_eq!(record.original_basename, "private-lab-file.csv");
        assert_eq!(record.stored_filename, "source.csv");
        let metadata =
            fs::read_to_string(store.project_dir(&project.id).unwrap().join("project.json"))
                .unwrap();
        assert!(!metadata.contains(source.to_string_lossy().as_ref()));
        assert_eq!(
            fs::read(
                store
                    .project_dir(&project.id)
                    .unwrap()
                    .join("data")
                    .join("source.csv")
            )
            .unwrap(),
            b"Sample,SiO2_wt%\nA,50\n"
        );
    }

    #[test]
    fn import_rejects_unknown_extension_and_oversized_file() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Limits").unwrap();
        let unsupported = temp.path().join("data.json");
        fs::write(&unsupported, b"{}").unwrap();
        assert!(matches!(
            store.import_source(&project.id, &unsupported, false),
            Err(StoreError::UnsupportedExtension)
        ));

        let large = temp.path().join("large.csv");
        let file = File::create(&large).unwrap();
        file.set_len(MAX_INPUT_BYTES + 1).unwrap();
        assert!(matches!(
            store.import_source(&project.id, &large, false),
            Err(StoreError::InputTooLarge)
        ));
    }

    #[test]
    fn metadata_writes_leave_no_temporary_files() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Atomic metadata").unwrap();
        let project_dir = store.project_dir(&project.id).unwrap();
        assert!(project_dir.join("project.json").is_file());
        assert!(fs::read_dir(&project_dir).unwrap().all(|entry| {
            !entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with('.')
        }));
    }

    #[test]
    fn request_size_limit_is_enforced() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Request limit").unwrap();
        let large = "x".repeat(MAX_REQUEST_BYTES);
        assert!(matches!(
            store.write_request(&project.id, &serde_json::json!({"value": large})),
            Err(StoreError::RequestTooLarge)
        ));
    }

    #[test]
    fn rename_remove_restore_preserve_identity_content_and_original_source() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Lifecycle").unwrap();
        let original = temp.path().join("external-source.csv");
        fs::write(&original, b"Sample,SiO2_wt%\nA,50\n").unwrap();
        let original_hash = format!("{:x}", Sha256::digest(fs::read(&original).unwrap()));
        store.import_source(&project.id, &original, false).unwrap();
        let active = store.project_dir(&project.id).unwrap();
        fs::write(active.join("recipe").join("current.yaml"), b"recipe-state").unwrap();
        fs::create_dir_all(active.join("outputs").join("current")).unwrap();
        fs::write(
            active.join("outputs").join("current").join("result.txt"),
            b"output-state",
        )
        .unwrap();

        let renamed = store
            .rename_project(&project.id, "  Renamed lifecycle  ")
            .unwrap();
        assert_eq!(renamed.id, project.id);
        assert_eq!(renamed.title, "Renamed lifecycle");
        assert!(matches!(
            store.rename_project(&project.id, " \n "),
            Err(StoreError::InvalidTitle)
        ));

        let removed = store.remove_project(&project.id).unwrap();
        assert_eq!(removed.id, project.id);
        assert!(store.list_projects().unwrap().is_empty());
        assert_eq!(
            store.list_removed_projects().unwrap(),
            vec![renamed.clone()]
        );
        let removed_dir = store.removed_project_dir(&project.id).unwrap();
        assert!(!active.exists());
        assert_eq!(
            fs::read(removed_dir.join("data").join("source.csv")).unwrap(),
            b"Sample,SiO2_wt%\nA,50\n"
        );
        assert_eq!(
            fs::read(removed_dir.join("recipe").join("current.yaml")).unwrap(),
            b"recipe-state"
        );
        assert_eq!(
            fs::read(
                removed_dir
                    .join("outputs")
                    .join("current")
                    .join("result.txt")
            )
            .unwrap(),
            b"output-state"
        );

        let restored = store.restore_project(&project.id).unwrap();
        assert_eq!(restored, renamed);
        assert_eq!(store.list_projects().unwrap(), vec![restored]);
        assert!(store.list_removed_projects().unwrap().is_empty());
        assert!(store.read_index().is_ok());
        let restarted = ProjectStore::new(temp.path().join("app-data"));
        restarted.initialize().unwrap();
        assert_eq!(restarted.list_projects().unwrap(), vec![renamed]);
        assert!(original.is_file());
        assert_eq!(
            format!("{:x}", Sha256::digest(fs::read(&original).unwrap())),
            original_hash
        );
    }

    #[test]
    fn remove_restore_reject_unknown_and_path_like_identifiers() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let unknown = Uuid::new_v4().hyphenated().to_string();
        assert!(matches!(
            store.remove_project(&unknown),
            Err(StoreError::ProjectNotFound)
        ));
        assert!(matches!(
            store.restore_project(&unknown),
            Err(StoreError::ProjectNotFound)
        ));
        for invalid in ["../outside", "C:\\outside", "\\\\server\\share"] {
            assert!(matches!(
                store.remove_project(invalid),
                Err(StoreError::InvalidProjectId)
            ));
            assert!(matches!(
                store.restore_project(invalid),
                Err(StoreError::InvalidProjectId)
            ));
        }
    }

    #[test]
    fn remove_rolls_back_when_index_write_fails() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Rollback").unwrap();
        store.fail_next_index_write.store(true, Ordering::SeqCst);

        assert!(matches!(
            store.remove_project(&project.id),
            Err(StoreError::ConsistencyRollback)
        ));
        assert_eq!(store.list_projects().unwrap(), vec![project.clone()]);
        assert!(store.list_removed_projects().unwrap().is_empty());
        assert!(store.project_dir(&project.id).unwrap().is_dir());
        assert!(!store.removed_project_dir(&project.id).unwrap().exists());

        store.remove_project(&project.id).unwrap();
        store.fail_next_index_write.store(true, Ordering::SeqCst);
        assert!(matches!(
            store.restore_project(&project.id),
            Err(StoreError::ConsistencyRollback)
        ));
        assert!(store.list_projects().unwrap().is_empty());
        assert_eq!(store.list_removed_projects().unwrap(), vec![project]);
    }

    #[test]
    fn linked_project_entry_is_rejected_when_links_are_supported() {
        let temp = tempfile::tempdir().unwrap();
        let store = ProjectStore::new(temp.path().join("app-data"));
        store.initialize().unwrap();
        let project = store.create_project("Linked entry").unwrap();
        let project_dir = store.project_dir(&project.id).unwrap();
        let backing = temp.path().join("linked-backing");
        fs::rename(&project_dir, &backing).unwrap();

        #[cfg(windows)]
        let linked = std::os::windows::fs::symlink_dir(&backing, &project_dir);
        #[cfg(unix)]
        let linked = std::os::unix::fs::symlink(&backing, &project_dir);
        #[cfg(not(any(windows, unix)))]
        let linked: Result<(), std::io::Error> = Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "directory links unavailable",
        ));
        if linked.is_err() {
            return;
        }
        assert!(matches!(
            store.remove_project(&project.id),
            Err(StoreError::LinkedProject)
        ));
    }
}
