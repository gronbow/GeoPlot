"""Deterministic, bounded exploratory screening for reviewed desktop recipes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from contract import issue, project_member
from geoskills_core.adapters import prepare_mapped_input
from geoskills_core.recipe import load_recipe


MIN_PAIR_COUNT = 8
MAX_SCREENING_VARIABLES = 32
MAX_SCREENING_RESULTS = 8
SCREENING_DISCLAIMER = (
    "Exploratory screening only. Correlation strength is not statistical proof "
    "and does not identify a geochemical process."
)


def rank_sio2_covariation(
    frame: pd.DataFrame,
    canonical_columns: Mapping[str, str],
    *,
    max_variables: int = MAX_SCREENING_VARIABLES,
    max_results: int = MAX_SCREENING_RESULTS,
) -> dict[str, Any]:
    """Rank finite pairwise Spearman correlations with SiO2 as fixed X."""

    sio2_column = canonical_columns.get("SiO2")
    if sio2_column is None or sio2_column not in frame.columns:
        return {
            "available": False,
            "reason": "sio2_not_mapped",
            "x": "SiO2",
            "variables_considered": [],
            "variables_capped": False,
            "results": [],
        }

    candidate_names = sorted(
        (
            canonical
            for canonical, column in canonical_columns.items()
            if canonical != "SiO2" and column in frame.columns
        ),
        key=lambda value: (value.casefold(), value),
    )
    selected_names = candidate_names[:max_variables]
    x = pd.to_numeric(frame[sio2_column], errors="coerce").to_numpy(dtype=float)
    pairs: list[dict[str, Any]] = []
    for canonical in selected_names:
        y = pd.to_numeric(
            frame[canonical_columns[canonical]], errors="coerce"
        ).to_numpy(dtype=float)
        finite = np.isfinite(x) & np.isfinite(y)
        count = int(finite.sum())
        if count < MIN_PAIR_COUNT:
            continue
        x_rank = pd.Series(x[finite]).rank(method="average").to_numpy(dtype=float)
        y_rank = pd.Series(y[finite]).rank(method="average").to_numpy(dtype=float)
        if np.ptp(x_rank) == 0 or np.ptp(y_rank) == 0:
            continue
        rho = float(np.corrcoef(x_rank, y_rank)[0, 1])
        if not np.isfinite(rho):
            continue
        pairs.append({"variable": canonical, "rho": rho, "n": count})

    pairs.sort(key=lambda item: (-abs(float(item["rho"])), str(item["variable"])))
    return {
        "available": True,
        "reason": None,
        "x": "SiO2",
        "variables_considered": selected_names,
        "variables_capped": len(candidate_names) > max_variables,
        "results": pairs[:max_results],
    }


def screen_project(
    project: Path,
    request: Mapping[str, Any],
) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    """Screen only the full, safely mapped data from one reviewed recipe."""

    recipe_path = project_member(
        project,
        request["recipe"],
        "recipe",
        must_exist=True,
        expect_file=True,
    )
    loaded = load_recipe(recipe_path)
    if loaded["status"] != "ready" or loaded["recipe"] is None:
        return (
            "blocked",
            {},
            [
                issue(
                    "D060",
                    "error",
                    "Screening requires a fully reviewed, valid recipe.",
                    field="recipe",
                )
            ],
        )

    cache = project_member(project, "cache", "cache", must_exist=True)
    with tempfile.TemporaryDirectory(prefix="screening-", dir=cache) as directory:
        prepared = prepare_mapped_input(
            loaded["recipe"],
            recipe_path=recipe_path,
            work_dir=Path(directory),
        )
        frame = pd.read_csv(prepared.path)
        canonical_columns = {
            mapping.canonical_analyte: (
                f"{mapping.canonical_analyte}_{mapping.unit}"
            )
            for mapping in prepared.mappings
        }
        result = rank_sio2_covariation(frame, canonical_columns)

    result.update(
        {
            "method": "spearman_rank_then_pearson",
            "minimum_pair_count": MIN_PAIR_COUNT,
            "maximum_variables": MAX_SCREENING_VARIABLES,
            "maximum_results": MAX_SCREENING_RESULTS,
            "data_scope": "full_reviewed_mapped_dataset",
            "disclaimer": SCREENING_DISCLAIMER,
        }
    )
    issues: list[dict[str, str]] = []
    if not result["available"]:
        issues.append(
            issue(
                "D061",
                "info",
                "SiO2 is not mapped. Choose explicit X and Y variables in the XY workflow instead.",
                field="columns.mapping.SiO2",
            )
        )
    return "ready", result, issues


__all__ = [
    "MAX_SCREENING_RESULTS",
    "MAX_SCREENING_VARIABLES",
    "MIN_PAIR_COUNT",
    "SCREENING_DISCLAIMER",
    "rank_sio2_covariation",
    "screen_project",
]
