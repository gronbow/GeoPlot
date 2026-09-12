from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "apps" / "desktop" / "backend"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
BRIDGE = BACKEND / "geoskills_desktop_bridge.py"
REQUEST_SCHEMA_VERSION = "geoskills.desktop-request/v1"
REE_ELEMENTS = ["La", "Ce", "Pr", "Nd", "Sm"]


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "requests").mkdir(parents=True)
    (project / "workspace" / "plans").mkdir(parents=True)
    shutil.copyfile(
        EXAMPLES / "synthetic_ree_data.csv",
        project / "workspace" / "input.csv",
    )
    return project


def write_request(project: Path, name: str, document: dict) -> Path:
    path = project / "requests" / f"{name}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run_bridge(operation: str, project: Path, request: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            operation,
            "--project",
            str(project),
            "--request",
            str(request),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, completed.stdout
    return completed.returncode, json.loads(lines[0])


def review(*, confirmed: bool = True, invalid: bool = False) -> dict:
    mapping = {element: f"{element}_ppm" for element in REE_ELEMENTS}
    if invalid:
        mapping.pop("Sm")
    return {
        "sample_id": "Sample",
        "group": "Group",
        "mapping": mapping,
        "units": {"major_oxides": "wt%", "trace_elements": "ppm"},
        "output_directory": "outputs",
        "report_profile": "shareable",
        "presets": {},
        "confirmations": {
            "input_structure_reviewed": confirmed,
            "column_mapping_reviewed": True,
            "units_reviewed": True,
            "plotted_data_export_reviewed": True,
        },
        "tasks": [
            {
                "id": "ree-main",
                "diagram": "ree",
                "stem": "figure-ree",
                "preset": "review-preview",
                "parameters": {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": "all",
                },
                "confirmations": {},
            }
        ],
    }


def recipe_request(*, confirmed: bool = True, invalid: bool = False) -> dict:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "operation": "recipe",
        "source": "workspace/input.csv",
        "sheet": None,
        "layout": "row-per-sample",
        "recipe": "workspace/recipe.yaml",
        "review": review(confirmed=confirmed, invalid=invalid),
        "overwrite": False,
    }


def test_recipe_build_double_validates_and_preserves_false_confirmation(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    request = write_request(
        project, "recipe-pending", recipe_request(confirmed=False)
    )

    exit_code, report = run_bridge("recipe", project, request)

    assert exit_code == 2
    assert report["status"] == "needs_confirmation"
    assert report["result"]["written"] is True
    assert (
        report["result"]["normalized_recipe"]["confirmations"]
        ["input_structure_reviewed"]
        is False
    )
    assert (project / "workspace" / "recipe.yaml").is_file()


def test_invalid_recipe_review_is_blocked_and_not_written(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    request = write_request(
        project, "recipe-invalid", recipe_request(invalid=True)
    )

    exit_code, report = run_bridge("recipe", project, request)

    assert exit_code == 2
    assert report["status"] == "blocked"
    assert report["result"]["written"] is False
    assert not (project / "workspace" / "recipe.yaml").exists()


def test_source_mode_recipe_plan_run_round_trip(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    recipe_path = write_request(project, "recipe", recipe_request())
    recipe_exit, recipe_report = run_bridge("recipe", project, recipe_path)
    assert recipe_exit == 0
    assert recipe_report["status"] == "ready"

    plan_request = write_request(
        project,
        "plan",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "plan",
            "recipe": "workspace/recipe.yaml",
            "plan": "workspace/plans/current.json",
            "selected_task_ids": ["ree-main"],
            "overwrite": False,
        },
    )
    plan_exit, plan_report = run_bridge("plan", project, plan_request)
    assert plan_exit == 0
    assert plan_report["status"] == "ready"
    assert (project / "workspace" / "plans" / "current.json").is_file()

    run_request = write_request(
        project,
        "run",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "run",
            "recipe": "workspace/recipe.yaml",
            "plan": "workspace/plans/current.json",
            "overwrite": False,
        },
    )
    run_exit, run_report = run_bridge("run", project, run_request)

    assert run_exit == 0
    assert run_report["status"] == "ready"
    output = project / "workspace" / "outputs"
    task_output = output / "ree-main"
    assert (task_output / "figure-ree.svg").is_file()
    assert (task_output / "figure-ree.report.json").is_file()
    assert (task_output / "figure-ree.qa.md").is_file()


def test_plan_does_not_bypass_pending_confirmation(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    request = write_request(
        project, "recipe-pending", recipe_request(confirmed=False)
    )
    _, recipe_report = run_bridge("recipe", project, request)
    assert recipe_report["status"] == "needs_confirmation"

    plan_request = write_request(
        project,
        "plan-pending",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "plan",
            "recipe": "workspace/recipe.yaml",
            "plan": "workspace/plans/current.json",
            "selected_task_ids": None,
            "overwrite": False,
        },
    )
    plan_exit, plan_report = run_bridge("plan", project, plan_request)

    assert plan_exit == 2
    assert plan_report["status"] in {"needs_confirmation", "blocked"}
    assert (project / "workspace" / "plans" / "current.json").is_file()

    run_request = write_request(
        project,
        "run-pending",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "run",
            "recipe": "workspace/recipe.yaml",
            "plan": "workspace/plans/current.json",
            "overwrite": False,
        },
    )
    run_exit, run_report = run_bridge("run", project, run_request)
    assert run_exit == 2
    assert run_report["status"] in {"needs_confirmation", "blocked"}
    assert not (project / "workspace" / "outputs").exists()


def test_recipe_builder_rejects_unknown_review_fields(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    document = recipe_request()
    document["review"]["automatic_scientific_approval"] = True
    request = write_request(project, "recipe-unknown", document)

    exit_code, report = run_bridge("recipe", project, request)

    assert exit_code == 1
    assert report["status"] == "error"
    assert {item["code"] for item in report["issues"]} == {"D041"}


@pytest.mark.parametrize(
    "example_name,expected_diagrams",
    [
        ("geoskills_ree_workflow.yaml", {"ree"}),
        ("geoskills_spider_workflow.yaml", {"spider"}),
        ("geoskills_major_workflow.yaml", {"harker", "tas", "k2o-sio2"}),
        ("geoskills_xy_workflow.yaml", {"xy"}),
    ],
)
def test_source_mode_registry_scenarios_create_reviewed_outputs(
    tmp_path: Path,
    example_name: str,
    expected_diagrams: set[str],
) -> None:
    example = yaml.safe_load((EXAMPLES / example_name).read_text(encoding="utf-8"))
    project = tmp_path / "project"
    (project / "requests").mkdir(parents=True)
    (project / "workspace" / "plans").mkdir(parents=True)
    source_example = EXAMPLES / example["input"]["file"]
    source_relative = f"workspace/input{source_example.suffix.lower()}"
    shutil.copyfile(source_example, project / source_relative)
    review_document = {
        "sample_id": example["columns"]["sample_id"],
        "group": example["columns"]["group"],
        "mapping": example["columns"]["mapping"],
        "units": example["columns"]["units"],
        "output_directory": "outputs",
        "report_profile": "shareable",
        "presets": example.get("presets", {}),
        "confirmations": example["confirmations"],
        "tasks": example["tasks"],
    }
    for optional in ("quality", "derived_variables", "data_basis"):
        if optional in example:
            review_document[optional] = example[optional]
    recipe_request_path = write_request(
        project,
        "scenario-recipe",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "recipe",
            "source": source_relative,
            "sheet": example["input"]["sheet"],
            "layout": example["input"]["layout"],
            "recipe": "workspace/recipe.yaml",
            "review": review_document,
            "overwrite": False,
        },
    )
    recipe_exit, recipe_report = run_bridge("recipe", project, recipe_request_path)
    assert recipe_exit == 0, recipe_report
    assert recipe_report["status"] == "ready"

    task_ids = [task["id"] for task in example["tasks"]]
    plan_request = write_request(
        project,
        "scenario-plan",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "plan",
            "recipe": "workspace/recipe.yaml",
            "plan": "workspace/plans/current.json",
            "selected_task_ids": task_ids,
            "overwrite": False,
        },
    )
    plan_exit, plan_report = run_bridge("plan", project, plan_request)
    assert plan_exit == 0, plan_report
    assert plan_report["status"] == "ready"

    run_request = write_request(
        project,
        "scenario-run",
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "run",
            "recipe": "workspace/recipe.yaml",
            "plan": "workspace/plans/current.json",
            "overwrite": False,
        },
    )
    run_exit, run_report = run_bridge("run", project, run_request)
    assert run_exit in {0, 2}, run_report
    assert run_report["status"] in {"ready", "review"}
    diagrams = {task["diagram"] for task in example["tasks"]}
    assert diagrams == expected_diagrams
    for task in example["tasks"]:
        task_dir = project / "workspace" / "outputs" / task["id"]
        assert (task_dir / f"{task['stem']}.svg").is_file()
        assert (task_dir / f"{task['stem']}.report.json").is_file()
        assert (task_dir / f"{task['stem']}.qa.md").is_file()
