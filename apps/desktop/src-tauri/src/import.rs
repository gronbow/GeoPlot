use serde::Serialize;

use crate::project_store::ProjectRecord;

#[derive(Debug, Serialize)]
pub struct ImportResult {
    pub project: ProjectRecord,
    pub replaced: bool,
}
