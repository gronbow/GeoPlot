from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from mixed_unit_fixture import (
    mixed_public_contract,
    write_mixed_unit_transposed_workbook,
)


ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "apps" / "desktop" / "backend"
BRIDGE = BACKEND / "geoskills_desktop_bridge.py"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
REQUEST_SCHEMA_VERSION = "geoskills.desktop-request/v1"
FROZEN_VALUE = os.environ.get("GEOSKILLS_FROZEN_BRIDGE")

pytestmark = pytest.mark.skipif(
    not FROZEN_VALUE,
    reason="Set GEOSKILLS_FROZEN_BRIDGE to run source/frozen parity.",
)


def _command(executable: Path | None, operation: str) -> list[str]:
    if executable is None:
        return [sys.executable, str(BRIDGE), operation]
    return [str(executable), operation]


def _run(
    executable: Path | None,
    operation: str,
    project: Path | None = None,
    request: Path | None = None,
) -> dict[str, Any]:
    arguments = _command(executable, operation)
    if project is not None and request is not None:
        arguments.extend(["--project", str(project), "--request", str(request)])
    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=360,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, (completed.returncode, completed.stdout, completed.stderr)
    report = json.loads(lines[0])
    assert completed.returncode in {0, 2}, (report, completed.stderr)
    return report


def _request(project: Path, name: str, document: dict[str, Any]) -> Path:
    path = project / "requests" / f"{name}.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _new_project(root: Path) -> Path:
    (root / "requests").mkdir(parents=True)
    (root / "plans").mkdir()
    (root / "outputs").mkdir()
    (root / "cache").mkdir()
    (root / "data").mkdir()
    return root


def _review_from_example(example: dict[str, Any]) -> dict[str, Any]:
    review = {
        "sample_id": example["columns"]["sample_id"],
        "group": example["columns"]["group"],
        "mapping": example["columns"]["mapping"],
        "units": example["columns"]["units"],
        "output_directory": "outputs/current",
        "report_profile": "shareable",
        "presets": example.get("presets", {}),
        "confirmations": example["confirmations"],
        "tasks": example["tasks"],
    }
    for optional in ("quality", "derived_variables", "data_basis"):
        if optional in example:
            review[optional] = example[optional]
    return review


def _scenario(
    executable: Path | None,
    root: Path,
    example_name: str,
) -> dict[str, Any]:
    project = _new_project(root)
    example = yaml.safe_load((EXAMPLES / example_name).read_text(encoding="utf-8"))
    source = EXAMPLES / example["input"]["file"]
    stored_source = project / "data" / f"source{source.suffix.lower()}"
    shutil.copyfile(source, stored_source)
    recipe_report = _run(
        executable,
        "recipe",
        project,
        _request(
            project,
            "recipe",
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "recipe",
                "source": f"data/{stored_source.name}",
                "sheet": example["input"]["sheet"],
                "layout": example["input"]["layout"],
                "recipe": "current.yaml",
                "review": _review_from_example(example),
                "overwrite": False,
            },
        ),
    )
    assert recipe_report["status"] == "ready"
    plan_report = _run(
        executable,
        "plan",
        project,
        _request(
            project,
            "plan",
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "plan",
                "recipe": "current.yaml",
                "plan": "plans/current.json",
                "selected_task_ids": [task["id"] for task in example["tasks"]],
                "overwrite": False,
            },
        ),
    )
    assert plan_report["status"] == "ready"
    screen_report = _run(
        executable,
        "screen",
        project,
        _request(
            project,
            "screen",
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "screen",
                "recipe": "current.yaml",
            },
        ),
    )
    assert screen_report["status"] == "ready"
    run_report = _run(
        executable,
        "run",
        project,
        _request(
            project,
            "run",
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "run",
                "recipe": "current.yaml",
                "plan": "plans/current.json",
                "overwrite": False,
            },
        ),
    )
    assert run_report["status"] in {"ready", "review"}
    plan = json.loads((project / "plans" / "current.json").read_text(encoding="utf-8"))
    task_reports: dict[str, dict[str, Any]] = {}
    png_hashes: dict[str, str] = {}
    for task in example["tasks"]:
        task_root = project / "outputs" / "current" / task["id"]
        report_path = task_root / f"{task['stem']}.report.json"
        png_path = task_root / f"{task['stem']}.png"
        task_reports[task["id"]] = json.loads(report_path.read_text(encoding="utf-8"))
        png_hashes[task["id"]] = hashlib.sha256(png_path.read_bytes()).hexdigest()
    return {
        "recipe": recipe_report,
        "plan_report": plan_report,
        "screen_report": screen_report,
        "run_report": run_report,
        "plan": plan,
        "task_reports": task_reports,
        "png_hashes": png_hashes,
    }


def _plan_signature(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": plan["schema_version"],
        "status": plan["status"],
        "tool": plan["tool"],
        "column_mapping": plan["column_mapping"],
        "data_processing": plan["data_processing"],
        "tasks": [
            {
                "id": task["id"],
                "diagram": task["diagram"],
                "parameters": task["parameters"],
                "confirmations": task["confirmations"],
                "inspection": task["inspection"],
                "assets": task["assets"],
                "expected_outputs": task["expected_outputs"],
            }
            for task in plan["tasks"]
        ],
    }


def _report_signature(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "status": report["status"],
        "operation": report["operation"],
        "review_required": report["review_required"],
        "source": report["source"],
        "issues": report["issues"],
        "qa": report["qa"],
        "details": report.get("details", {}),
        "privacy": report["privacy"],
        "output_filenames": [item["filename"] for item in report["outputs"]],
    }


def test_frozen_version_capabilities_and_csv_xlsx_inspection_match(tmp_path: Path) -> None:
    frozen = Path(str(FROZEN_VALUE))
    assert frozen.is_file()
    for operation in ("version", "capabilities"):
        source = _run(None, operation)
        bundled = _run(frozen, operation)
        assert bundled["status"] == source["status"]
        assert bundled["engine"] == source["engine"]
        if operation == "version":
            assert source["result"]["bridge_mode"] == "source"
            assert bundled["result"]["bridge_mode"] == "frozen"
            assert bundled["result"]["tool_version"] == source["result"]["tool_version"]
            assert bundled["result"]["diagram_api_version"] == source["result"]["diagram_api_version"]
        else:
            assert bundled["result"] == source["result"]

    for suffix in ("csv", "xlsx"):
        source_project = _new_project(tmp_path / f"source-{suffix}")
        frozen_project = _new_project(tmp_path / f"frozen-{suffix}")
        frame = pd.read_csv(EXAMPLES / "synthetic_major_element_data.csv")
        if suffix == "csv":
            frame.to_csv(source_project / "data" / "source.csv", index=False)
            frame.to_csv(frozen_project / "data" / "source.csv", index=False)
        else:
            with pd.ExcelWriter(source_project / "data" / "source.xlsx") as writer:
                frame.to_excel(writer, sheet_name="Major", index=False)
                frame.head(2).to_excel(writer, sheet_name="Notes", index=False)
            shutil.copyfile(
                source_project / "data" / "source.xlsx",
                frozen_project / "data" / "source.xlsx",
            )
        document = {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "inspect",
            "source": f"data/source.{suffix}",
            "sheet": None,
            "layout": "auto",
        }
        source = _run(None, "inspect", source_project, _request(source_project, "inspect", document))
        bundled = _run(frozen, "inspect", frozen_project, _request(frozen_project, "inspect", document))
        assert bundled["status"] == source["status"]
        assert bundled["engine"] == source["engine"]
        assert bundled["result"] == source["result"]


def test_source_and_frozen_mixed_unit_public_contract_match(tmp_path: Path) -> None:
    frozen = Path(str(FROZEN_VALUE))
    source_project = _new_project(tmp_path / "source-mixed-unit")
    frozen_project = _new_project(tmp_path / "frozen-mixed-unit")
    source_workbook = source_project / "data" / "source.xlsx"
    frozen_workbook = frozen_project / "data" / "source.xlsx"
    write_mixed_unit_transposed_workbook(source_workbook)
    shutil.copyfile(source_workbook, frozen_workbook)
    document = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "operation": "inspect",
        "source": "data/source.xlsx",
        "sheet": None,
        "layout": "auto",
    }

    source = _run(
        None,
        "inspect",
        source_project,
        _request(source_project, "mixed-inspect", document),
    )
    bundled = _run(
        frozen,
        "inspect",
        frozen_project,
        _request(frozen_project, "mixed-inspect", document),
    )

    assert source["status"] == bundled["status"] == "ready"
    source_contract = mixed_public_contract(source["result"])
    bundled_contract = mixed_public_contract(bundled["result"])
    assert bundled_contract == source_contract
    records = bundled_contract["recognized_analytes"]
    assert len(records) == 47
    assert all(record["canonical"].strip() for record in records)
    assert sum(record["explicit_unit"] == "wt%" for record in records) == 12
    assert sum(record["explicit_unit"] == "ppm" for record in records) == 35


@pytest.mark.parametrize(
    "example_name",
    [
        "geoskills_ree_workflow.yaml",
        "geoskills_spider_workflow.yaml",
        "geoskills_major_workflow.yaml",
        "geoskills_xy_workflow.yaml",
    ],
)
def test_source_and_frozen_plan_run_scientific_parity(
    tmp_path: Path,
    example_name: str,
) -> None:
    frozen = Path(str(FROZEN_VALUE))
    source = _scenario(None, tmp_path / f"source-{example_name}", example_name)
    bundled = _scenario(frozen, tmp_path / f"frozen-{example_name}", example_name)
    for operation in ("recipe", "plan_report", "screen_report", "run_report"):
        assert bundled[operation]["status"] == source[operation]["status"]
        assert bundled[operation]["engine"] == source[operation]["engine"]
    assert bundled["screen_report"]["result"] == source["screen_report"]["result"]
    assert _plan_signature(bundled["plan"]) == _plan_signature(source["plan"])
    assert bundled["png_hashes"] == source["png_hashes"]
    assert bundled["task_reports"].keys() == source["task_reports"].keys()
    for task_id in source["task_reports"]:
        assert _report_signature(bundled["task_reports"][task_id]) == _report_signature(
            source["task_reports"][task_id]
        )
