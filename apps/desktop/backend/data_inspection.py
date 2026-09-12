"""Bounded local inspection for GeoPlot projects."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from contract import ContractError, issue, project_member
from geoskills_core.analytes import (
    GROUP_NAME_ALIASES,
    REE_ORDER,
    SAMPLE_NAME_ALIASES,
    SPIDER_ELEMENT_ORDER,
    clean_name,
    match_analyte,
)
from geoskills_core.io import adapt_transposed_table, read_table
from geoskills_core.registry import registry_snapshot


PREVIEW_ROW_LIMIT = 30
PREVIEW_COLUMN_LIMIT = 40
FIGURE_STATES = frozenset(
    {
        "AVAILABLE_AFTER_REVIEW",
        "NEEDS_PARAMETER",
        "NEEDS_SCIENTIFIC_CONFIRMATION",
        "NOT_AVAILABLE",
        "BLOCKED",
    }
)


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _preview(frame: pd.DataFrame) -> dict[str, Any]:
    view = frame.iloc[:PREVIEW_ROW_LIMIT, :PREVIEW_COLUMN_LIMIT]
    return {
        "columns": [str(column) for column in view.columns],
        "rows": [
            [_json_value(value) for value in row]
            for row in view.itertuples(index=False, name=None)
        ],
        "preview_row_limit": PREVIEW_ROW_LIMIT,
        "preview_column_limit": PREVIEW_COLUMN_LIMIT,
        "preview_truncated_rows": int(frame.shape[0]) > PREVIEW_ROW_LIMIT,
        "preview_truncated_columns": int(frame.shape[1]) > PREVIEW_COLUMN_LIMIT,
        "notice": (
            "Preview only. GeoSkills inspection and plotting use the complete "
            "dataset and do not sample scientific calculations."
        ),
    }


def _column_analysis(frame: pd.DataFrame) -> dict[str, Any]:
    sample_candidates = [
        str(column)
        for column in frame.columns
        if clean_name(column) in SAMPLE_NAME_ALIASES
    ]
    group_candidates = [
        str(column)
        for column in frame.columns
        if clean_name(column) in GROUP_NAME_ALIASES
    ]
    matches: list[dict[str, Any]] = []
    by_canonical: dict[str, list[dict[str, Any]]] = {}
    for column in frame.columns:
        matched = match_analyte(column)
        if matched is None:
            continue
        unit_status = (
            "unknown"
            if matched.explicit_unit == "unknown"
            else (
                "confirmed_from_header"
                if matched.explicit_unit == matched.required_unit
                else "conflict"
            )
        )
        # This is the desktop transport contract.  Keep it explicit instead of
        # forwarding the core ``AnalyteMatch.to_dict()`` schema, whose public
        # key is intentionally ``analyte`` for existing CLI consumers.
        record = {
            "canonical": matched.canonical,
            "kind": matched.kind,
            "required_unit": matched.required_unit,
            "source_label": matched.source_label,
            "explicit_unit": matched.explicit_unit,
            "source_column": str(column),
            "unit_status": unit_status,
        }
        matches.append(record)
        by_canonical.setdefault(matched.canonical, []).append(record)
    ambiguous = {
        canonical: [str(item["source_column"]) for item in records]
        for canonical, records in by_canonical.items()
        if len(records) > 1
    }
    unique = {
        canonical: records[0]
        for canonical, records in by_canonical.items()
        if len(records) == 1
    }
    metadata_columns = set(sample_candidates) | set(group_candidates)
    matched_columns = {str(item["source_column"]) for item in matches}
    unrecognized = [
        str(column)
        for column in frame.columns
        if str(column) not in metadata_columns | matched_columns
    ]
    return {
        "sample_column_candidates": sample_candidates,
        "sample_column_suggestion": (
            sample_candidates[0] if len(sample_candidates) == 1 else None
        ),
        "group_column_candidates": group_candidates,
        "group_column_suggestion": (
            group_candidates[0] if len(group_candidates) == 1 else None
        ),
        "recognized_analytes": matches,
        "mapping_suggestions": {
            canonical: str(record["source_column"])
            for canonical, record in sorted(unique.items())
        },
        "ambiguous_analytes": ambiguous,
        "unrecognized_columns": unrecognized,
        "_unique": unique,
    }


def _quality_counts(frame: pd.DataFrame, columns: Mapping[str, Any]) -> dict[str, int]:
    recognized_columns = [
        str(item["source_column"])
        for item in columns["recognized_analytes"]
    ]
    missing = int(frame.isna().sum().sum())
    below_detection = 0
    non_numeric = 0
    non_positive = 0
    for column in recognized_columns:
        series = frame[column]
        text = series.astype("string").str.strip()
        detected = text.str.startswith("<", na=False)
        below_detection += int(detected.sum())
        numeric = pd.to_numeric(series.where(~detected), errors="coerce")
        source_present = series.notna() & text.ne("") & ~detected
        non_numeric += int((source_present & numeric.isna()).sum())
        finite = numeric.notna() & np.isfinite(numeric)
        non_positive += int((finite & numeric.le(0)).sum())
    duplicate_samples = 0
    blank_samples = 0
    candidates = columns["sample_column_candidates"]
    if len(candidates) == 1:
        sample = frame[candidates[0]].astype("string").str.strip()
        blank_samples = int((sample.isna() | sample.eq("")).sum())
        duplicate_samples = int(sample.dropna().duplicated(keep=False).sum())
    unknown_units = sum(
        item["unit_status"] == "unknown"
        for item in columns["recognized_analytes"]
    )
    unit_conflicts = sum(
        item["unit_status"] == "conflict"
        for item in columns["recognized_analytes"]
    )
    return {
        "missing_value_count": missing,
        "below_detection_limit_count": below_detection,
        "non_numeric_count": non_numeric,
        "non_positive_count": non_positive,
        "duplicate_sample_id_count": duplicate_samples,
        "blank_sample_id_count": blank_samples,
        "unknown_unit_count": int(unknown_units),
        "unit_conflict_count": int(unit_conflicts),
    }


def _unit_requirements(
    analytes: set[str], unique: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    requirements: list[str] = []
    if any(unique[name]["unit_status"] == "unknown" for name in analytes):
        requirements.append("units_review_required")
    if any(unique[name]["unit_status"] == "conflict" for name in analytes):
        requirements.append("unit_conflict_must_be_resolved")
    return requirements


def _candidate_record(
    spec: Mapping[str, Any],
    state: str,
    requirements: list[str],
    *,
    suggestions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in FIGURE_STATES:
        raise ValueError("Unsupported figure state")
    return {
        "diagram": str(spec["id"]),
        "display_name_en": str(spec["display_name_en"]),
        "display_name_zh": str(spec["display_name_zh"]),
        "input_profile": str(spec["input_profile"]),
        "state": state,
        "requirements": requirements,
        "required_confirmations": list(spec["required_confirmations"]),
        "required_assets": list(spec["required_assets"]),
        "parameter_schema": dict(spec["scientific_parameter_schema"]),
        "suggestions": dict(suggestions or {}),
    }


def figure_candidates(columns: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive preliminary UI states from the reviewed registry and mappings."""

    unique: Mapping[str, Mapping[str, Any]] = columns["_unique"]
    available = set(unique)
    ree = available.intersection(REE_ORDER)
    spider = available.intersection(SPIDER_ELEMENT_ORDER)
    spider.update(
        element
        for element, oxide in {"K": "K2O", "P": "P2O5", "Ti": "TiO2"}.items()
        if oxide in available
    )
    records: list[dict[str, Any]] = []
    for spec in registry_snapshot():
        diagram = str(spec["id"])
        requirements: list[str] = []
        suggestions: dict[str, Any] = {}
        state = "NOT_AVAILABLE"
        relevant: set[str] = set()
        if diagram == "ree":
            relevant = set(ree)
            if len(ree) >= int(spec["scientific_parameter_schema"]["elements"]["minimum_items"]):
                state = "AVAILABLE_AFTER_REVIEW"
                suggestions = {"elements": [name for name in REE_ORDER if name in ree]}
        elif diagram == "spider":
            relevant = {name for name in available if name in SPIDER_ELEMENT_ORDER}
            if len(spider) >= int(spec["scientific_parameter_schema"]["elements"]["minimum_items"]):
                state = "NEEDS_PARAMETER"
                requirements.append("normalization_reference_required")
                suggestions = {"elements": [name for name in SPIDER_ELEMENT_ORDER if name in spider]}
        elif diagram == "harker":
            relevant = set(available)
            other = [name for name in available if name != "SiO2"]
            if "SiO2" in available and other:
                state = "AVAILABLE_AFTER_REVIEW"
                common_y = [
                    name
                    for name in (
                        "TiO2", "Al2O3", "Fe2O3T", "MgO", "CaO",
                        "Na2O", "K2O", "P2O5",
                    )
                    if name in available
                ][:9]
                suggestions = {"x": "SiO2", "y": common_y or sorted(other)[:9]}
            elif len(available) >= 2:
                state = "NEEDS_PARAMETER"
                requirements.append("manual_x_and_y_required")
        elif diagram == "tas":
            relevant = {"SiO2", "Na2O", "K2O"}.intersection(available)
            if relevant == {"SiO2", "Na2O", "K2O"}:
                state = "NEEDS_SCIENTIFIC_CONFIRMATION"
                requirements.extend(
                    ["volcanic_samples", "composition_basis_reviewed"]
                )
        elif diagram == "k2o-sio2":
            relevant = {"SiO2", "K2O"}.intersection(available)
            if relevant == {"SiO2", "K2O"}:
                state = "NEEDS_SCIENTIFIC_CONFIRMATION"
                requirements.extend(
                    [
                        "volcanic_samples",
                        "composition_basis_reviewed",
                        "data_basis_reviewed",
                    ]
                )
        elif diagram == "xy" and len(available) >= 2:
            relevant = set(available)
            state = "NEEDS_PARAMETER"
            requirements.append("manual_x_and_y_required")
        requirements.extend(_unit_requirements(relevant, unique))
        if "unit_conflict_must_be_resolved" in requirements:
            state = "BLOCKED"
        records.append(
            _candidate_record(
                spec,
                state,
                list(dict.fromkeys(requirements)),
                suggestions=suggestions,
            )
        )
    return records


def inspect_project(project: Path, request: Mapping[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    """Inspect one project-owned source table without creating confirmations."""

    source_path = project_member(
        project, request["source"], "source", must_exist=True, expect_file=True
    )
    layout = request["layout"]
    if layout not in {"auto", "row-per-sample", "analyte-per-row"}:
        raise ContractError(
            "D030",
            "layout must be auto, row-per-sample, or analyte-per-row.",
            "layout",
        )
    sheet = request["sheet"]
    if not (
        sheet is None
        or (isinstance(sheet, str) and bool(sheet.strip()))
        or (isinstance(sheet, int) and not isinstance(sheet, bool) and sheet >= 0)
    ):
        raise ContractError("D031", "sheet must be text, an index, or null.", "sheet")
    transposer = None if layout == "row-per-sample" else adapt_transposed_table
    frame, metadata = read_table(
        source_path,
        requested_sheet=sheet,
        transposer=transposer,
    )
    source = {
        "stored_filename": source_path.name,
        "sha256": str(metadata["file_sha256"]),
        "size_bytes": int(metadata["size_bytes"]),
        "format": str(metadata["format"]),
        "sheet_names": list(metadata.get("sheet_names", [])),
        "selected_sheet": metadata.get("sheet"),
        "layout": metadata.get("layout"),
        "transformation": metadata.get("transformation"),
    }
    if frame is None:
        return (
            "needs_confirmation",
            {
                "source": source,
                "row_count": None,
                "column_count": None,
                "sample_column_candidates": [],
                "group_column_candidates": [],
                "recognized_analytes": [],
                "quality": {},
                "preview": None,
                "figure_candidates": [],
            },
            [
                issue(
                    "D101",
                    "review",
                    "This workbook contains multiple sheets. Choose one to continue.",
                    field="sheet",
                )
            ],
        )
    if layout == "analyte-per-row" and metadata.get("layout") != "column_per_sample_transposed":
        return (
            "blocked",
            {"source": source},
            [
                issue(
                    "D102",
                    "error",
                    "The declared analyte-per-row layout was not recognized unambiguously.",
                    field="layout",
                )
            ],
        )
    columns = _column_analysis(frame)
    quality = _quality_counts(frame, columns)
    issues: list[dict[str, str]] = []
    if len(columns["sample_column_candidates"]) != 1:
        issues.append(
            issue(
                "D103",
                "review",
                "Select exactly one sample identifier column.",
                field="sample_column",
            )
        )
    if columns["ambiguous_analytes"]:
        issues.append(
            issue(
                "D104",
                "review",
                "Multiple source columns map to the same canonical analyte.",
                field="mapping",
            )
        )
    if quality["unit_conflict_count"]:
        issues.append(
            issue(
                "D105",
                "error",
                "One or more explicit header units conflict with the analyte contract.",
                field="units",
            )
        )
    if quality["unknown_unit_count"]:
        issues.append(
            issue(
                "D106",
                "review",
                "One or more recognized analytes require explicit unit review.",
                field="units",
            )
        )
    status = (
        "blocked"
        if any(item["severity"] == "error" for item in issues)
        else ("needs_confirmation" if issues else "ready")
    )
    public_columns = {key: value for key, value in columns.items() if not key.startswith("_")}
    result = {
        "source": source,
        "row_count": int(frame.shape[0]),
        "column_count": int(frame.shape[1]),
        **public_columns,
        "quality": quality,
        "quality_issue_count": sum(value for value in quality.values()),
        "preview": _preview(frame),
        "figure_candidates": figure_candidates(columns),
    }
    return status, result, issues


__all__ = [
    "FIGURE_STATES",
    "PREVIEW_COLUMN_LIMIT",
    "PREVIEW_ROW_LIMIT",
    "figure_candidates",
    "inspect_project",
]
