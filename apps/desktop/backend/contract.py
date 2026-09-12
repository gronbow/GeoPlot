"""Versioned request and report contracts for the desktop trust boundary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping


REQUEST_SCHEMA_VERSION = "geoskills.desktop-request/v1"
REPORT_SCHEMA_VERSION = "geoskills.desktop-report/v1"
PROJECT_SCHEMA_VERSION = "geoskills.desktop-project/v1"
MAX_REQUEST_BYTES = 256 * 1024

ALLOWED_STATUSES = frozenset(
    {"ready", "needs_confirmation", "review", "blocked", "error"}
)
REQUEST_FIELDS: Mapping[str, frozenset[str]] = {
    "inspect": frozenset(
        {"schema_version", "operation", "source", "sheet", "layout"}
    ),
    "recipe": frozenset(
        {
            "schema_version",
            "operation",
            "source",
            "sheet",
            "layout",
            "recipe",
            "review",
            "overwrite",
        }
    ),
    "plan": frozenset(
        {
            "schema_version",
            "operation",
            "recipe",
            "plan",
            "selected_task_ids",
            "overwrite",
        }
    ),
    "run": frozenset(
        {"schema_version", "operation", "recipe", "plan", "overwrite"}
    ),
    "screen": frozenset({"schema_version", "operation", "recipe"}),
}
REQUEST_REQUIRED: Mapping[str, frozenset[str]] = {
    "inspect": frozenset({"schema_version", "operation", "source", "sheet", "layout"}),
    "recipe": frozenset(
        {
            "schema_version",
            "operation",
            "source",
            "sheet",
            "layout",
            "recipe",
            "review",
            "overwrite",
        }
    ),
    "plan": frozenset(
        {"schema_version", "operation", "recipe", "plan", "selected_task_ids", "overwrite"}
    ),
    "run": frozenset(
        {"schema_version", "operation", "recipe", "plan", "overwrite"}
    ),
    "screen": frozenset({"schema_version", "operation", "recipe"}),
}

_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_GLOB_CHARS = frozenset("*?[]{}")
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


@dataclass(frozen=True)
class ContractError(Exception):
    """A request cannot cross the desktop trust boundary safely."""

    code: str
    message: str
    field: str | None = None

    def to_issue(self) -> dict[str, str]:
        issue = {
            "code": self.code,
            "severity": "error",
            "message": self.message,
        }
        if self.field is not None:
            issue["field"] = self.field
        return issue


def issue(
    code: str,
    severity: str,
    message: str,
    *,
    field: str | None = None,
) -> dict[str, str]:
    """Return one stable, user-safe issue record."""

    result = {"code": code, "severity": severity, "message": message}
    if field is not None:
        result["field"] = field
    return result


def envelope(
    operation: str,
    status: str,
    *,
    engine: Mapping[str, Any],
    result: Mapping[str, Any] | None = None,
    issues: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one JSON-safe bridge response."""

    if status not in ALLOWED_STATUSES:
        raise ContractError(
            "D006",
            "The bridge produced an unsupported status.",
            "status",
        )
    document = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "operation": operation,
        "status": status,
        "engine": dict(engine),
        "result": dict(result or {}),
        "issues": [dict(item) for item in (issues or [])],
    }
    try:
        json.dumps(document, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError(
            "D007",
            "The bridge response was not valid finite JSON.",
        ) from exc
    return document


def resolve_project_root(value: str | Path) -> Path:
    """Resolve one existing, non-linked project directory."""

    project = Path(value)
    try:
        resolved = project.resolve(strict=True)
    except OSError as exc:
        raise ContractError("D020", "Project directory was not found.") from exc
    if project.is_symlink() or not resolved.is_dir():
        raise ContractError("D020", "Project must be a regular directory.")
    return resolved


def _safe_relative_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("D021", "Project path must be non-empty text.", field)
    text = value.strip()
    windows = PureWindowsPath(text)
    normalized = text.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    unsafe = (
        "\x00" in text
        or any(ord(character) < 32 for character in text)
        or _URI_PATTERN.match(text) is not None
        or windows.is_absolute()
        or bool(windows.drive)
        or text.startswith(("/", "\\"))
        or any(character in text for character in _GLOB_CHARS)
        or any(character in text for character in '<>:"|')
        or any(
            part in {"", ".."}
            or part.startswith("~")
            or part.endswith((" ", "."))
            or part.split(".", 1)[0].rstrip(" .").upper() in _WINDOWS_RESERVED
            for part in parts
        )
    )
    if unsafe:
        raise ContractError(
            "D022",
            "Path must be a safe project-relative path without URI, glob, drive, absolute path, or '..'.",
            field,
        )
    cleaned = "/".join(part for part in parts if part != ".")
    if not cleaned:
        raise ContractError("D022", "Path cannot name the project root.", field)
    return cleaned


def project_member(
    project: Path,
    relative_value: Any,
    field: str,
    *,
    must_exist: bool = False,
    expect_file: bool = False,
) -> Path:
    """Resolve a safe member and prove that it remains inside the project."""

    relative = _safe_relative_text(relative_value, field)
    member = project.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = member.resolve(strict=must_exist)
        resolved.relative_to(project)
    except (OSError, ValueError) as exc:
        raise ContractError(
            "D023",
            "Resolved path is outside the project or does not exist.",
            field,
        ) from exc
    if must_exist and expect_file and (member.is_symlink() or not resolved.is_file()):
        raise ContractError("D023", "Expected a regular project file.", field)
    return resolved


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(
                "D003",
                "Request JSON contains a duplicate object key.",
                key,
            )
        result[key] = value
    return result


def load_request(
    project_value: str | Path,
    request_value: str | Path,
    expected_operation: str,
) -> tuple[Path, dict[str, Any]]:
    """Load one strict request file located under ``project/requests``."""

    if expected_operation not in REQUEST_FIELDS:
        raise ContractError("D004", "Unknown bridge operation.", "operation")
    project = resolve_project_root(project_value)
    request_path = Path(request_value)
    try:
        resolved_request = request_path.resolve(strict=True)
        requests_root = (project / "requests").resolve(strict=True)
        resolved_request.relative_to(requests_root)
    except (OSError, ValueError) as exc:
        raise ContractError(
            "D024",
            "Request file must be a regular file inside project/requests.",
        ) from exc
    if request_path.is_symlink() or not resolved_request.is_file():
        raise ContractError(
            "D024",
            "Request file must be a regular file inside project/requests.",
        )
    if resolved_request.stat().st_size > MAX_REQUEST_BYTES:
        raise ContractError("D025", "Request file exceeds the size limit.")
    try:
        document = json.loads(
            resolved_request.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_object,
        )
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("D002", "Request must be valid UTF-8 JSON.") from exc
    if not isinstance(document, dict):
        raise ContractError("D002", "Request root must be a JSON object.")
    if document.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ContractError(
            "D001",
            f"Request schema must be {REQUEST_SCHEMA_VERSION}.",
            "schema_version",
        )
    if document.get("operation") != expected_operation:
        raise ContractError(
            "D004",
            "Request operation does not match the invoked bridge command.",
            "operation",
        )
    allowed = REQUEST_FIELDS[expected_operation]
    unknown = sorted(str(key) for key in set(document) - set(allowed))
    if unknown:
        raise ContractError(
            "D005",
            "Request contains unknown fields: " + ", ".join(unknown) + ".",
        )
    missing = sorted(REQUEST_REQUIRED[expected_operation] - set(document))
    if missing:
        raise ContractError(
            "D005",
            "Request is missing fields: " + ", ".join(missing) + ".",
        )
    return project, document


__all__ = [
    "ALLOWED_STATUSES",
    "ContractError",
    "MAX_REQUEST_BYTES",
    "PROJECT_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "REQUEST_SCHEMA_VERSION",
    "envelope",
    "issue",
    "load_request",
    "project_member",
    "resolve_project_root",
]
