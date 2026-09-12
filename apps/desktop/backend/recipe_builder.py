"""Build and double-validate GeoSkills recipes from reviewed UI state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from contract import ContractError, project_member
from geoskills_core.io import validate_input_file
from geoskills_core.recipe import (
    RECIPE_SCHEMA_VERSION,
    load_recipe,
    validate_recipe,
)


REVIEW_FIELDS = frozenset(
    {
        "sample_id",
        "group",
        "mapping",
        "units",
        "quality",
        "derived_variables",
        "data_basis",
        "output_directory",
        "report_profile",
        "presets",
        "confirmations",
        "tasks",
    }
)
REVIEW_REQUIRED = frozenset(
    {
        "sample_id",
        "group",
        "mapping",
        "units",
        "output_directory",
        "report_profile",
        "presets",
        "confirmations",
        "tasks",
    }
)


def _atomic_yaml(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=".geoskills-desktop-recipe-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            yaml.safe_dump(
                dict(document),
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _review_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("D040", "review must be an object.", "review")
    review = dict(value)
    unknown = sorted(str(key) for key in set(review) - set(REVIEW_FIELDS))
    missing = sorted(REVIEW_REQUIRED - set(review))
    if unknown:
        raise ContractError(
            "D041",
            "review contains unknown fields: " + ", ".join(unknown) + ".",
            "review",
        )
    if missing:
        raise ContractError(
            "D041",
            "review is missing fields: " + ", ".join(missing) + ".",
            "review",
        )
    return review


def _recipe_status(validation: Mapping[str, Any]) -> str:
    if validation["status"] == "invalid":
        return "blocked"
    codes = {str(item.get("code", "")) for item in validation["issues"]}
    if "R312" in codes:
        return "needs_confirmation"
    if validation["status"] == "needs_review":
        return "review"
    return "ready"


def build_recipe(
    project: Path,
    request: Mapping[str, Any],
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Create a recipe from review state, then validate it before and after write."""

    source_path = project_member(
        project, request["source"], "source", must_exist=True, expect_file=True
    )
    validate_input_file(source_path)
    recipe_path = project_member(project, request["recipe"], "recipe")
    if recipe_path.suffix.lower() not in {".yaml", ".yml"}:
        raise ContractError("D042", "recipe must use .yaml or .yml.", "recipe")
    try:
        source_relative = source_path.relative_to(recipe_path.parent).as_posix()
    except ValueError as exc:
        raise ContractError(
            "D043",
            "The source must be inside the recipe directory or one of its subdirectories.",
            "source",
        ) from exc
    overwrite = request["overwrite"]
    if not isinstance(overwrite, bool):
        raise ContractError("D044", "overwrite must be true or false.", "overwrite")
    if recipe_path.exists():
        if not overwrite:
            raise ContractError("D045", "Recipe already exists; explicit replacement is required.")
        if recipe_path.is_symlink() or not recipe_path.is_file():
            raise ContractError("D045", "Only a regular recipe file may be replaced.")
        if load_recipe(recipe_path)["status"] == "invalid":
            raise ContractError("D045", "An unrecognized existing file will not be replaced.")
    review = _review_mapping(request["review"])
    layout = request["layout"]
    if layout not in {"auto", "row-per-sample", "analyte-per-row"}:
        raise ContractError("D030", "Unsupported input layout.", "layout")
    document: dict[str, Any] = {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "input": {
            "file": source_relative,
            "sheet": request["sheet"],
            "layout": layout,
        },
        "columns": {
            "sample_id": review["sample_id"],
            "group": review["group"],
            "mapping": review["mapping"],
            "units": review["units"],
        },
        "output": {
            "directory": review["output_directory"],
            "report_profile": review["report_profile"],
        },
        "presets": review["presets"],
        "confirmations": review["confirmations"],
        "tasks": review["tasks"],
    }
    for optional in ("quality", "derived_variables", "data_basis"):
        if optional in review:
            document[optional] = review[optional]
    first = validate_recipe(document)
    status = _recipe_status(first)
    if first["recipe"] is None:
        return status, {"recipe": request["recipe"], "written": False}, list(first["issues"])
    _atomic_yaml(recipe_path, first["recipe"])
    second = load_recipe(recipe_path)
    if second["recipe"] is None:
        raise ContractError("D046", "Recipe failed validation after atomic write.")
    second_status = _recipe_status(second)
    if second_status != status or second["recipe"] != first["recipe"]:
        raise ContractError("D046", "Recipe changed during validation round-trip.")
    return (
        status,
        {
            "recipe": str(request["recipe"]),
            "written": True,
            "validation_status": str(second["status"]),
            "normalized_recipe": second["recipe"],
        },
        list(second["issues"]),
    )


__all__ = ["REVIEW_FIELDS", "build_recipe"]

