from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "apps" / "desktop" / "backend"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
BRIDGE = BACKEND / "geoskills_desktop_bridge.py"
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BACKEND))

from contract import REQUEST_SCHEMA_VERSION  # noqa: E402
from screening import (  # noqa: E402
    MAX_SCREENING_RESULTS,
    MAX_SCREENING_VARIABLES,
    MIN_PAIR_COUNT,
    SCREENING_DISCLAIMER,
    rank_sio2_covariation,
)


def test_pairs_below_the_fixed_threshold_are_excluded() -> None:
    frame = pd.DataFrame({"sio2": range(MIN_PAIR_COUNT - 1), "rb": range(7)})
    result = rank_sio2_covariation(frame, {"SiO2": "sio2", "Rb": "rb"})
    assert result["available"] is True
    assert result["results"] == []


def test_only_pairwise_finite_values_are_ranked() -> None:
    frame = pd.DataFrame(
        {
            "sio2": [1, 2, 3, 4, 5, 6, 7, 8, 9, np.inf, 11],
            "rb": [2, 4, 6, 8, 10, 12, 14, 16, np.nan, 20, 22],
        }
    )
    result = rank_sio2_covariation(frame, {"SiO2": "sio2", "Rb": "rb"})
    assert result["results"] == [{"variable": "Rb", "rho": 1.0, "n": 9}]


def test_variable_and_output_counts_are_bounded_and_sorted() -> None:
    frame = pd.DataFrame({"sio2": np.arange(12, dtype=float)})
    columns = {"SiO2": "sio2"}
    for index in range(MAX_SCREENING_VARIABLES + 5):
        name = f"V{index:02d}"
        frame[name] = np.arange(12, dtype=float) + index
        columns[name] = name
    result = rank_sio2_covariation(frame, columns)
    assert len(result["variables_considered"]) == MAX_SCREENING_VARIABLES
    assert result["variables_capped"] is True
    assert len(result["results"]) == MAX_SCREENING_RESULTS
    assert [item["variable"] for item in result["results"]] == [
        f"V{index:02d}" for index in range(MAX_SCREENING_RESULTS)
    ]


def test_no_sio2_returns_no_scan_and_xy_guidance(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "requests").mkdir(parents=True)
    (project / "cache").mkdir()
    recipe = yaml.safe_load(
        (EXAMPLES / "geoskills_ree_workflow.yaml").read_text(encoding="utf-8")
    )
    recipe["input"]["file"] = "synthetic_ree_data.csv"
    shutil.copyfile(EXAMPLES / "synthetic_ree_data.csv", project / "synthetic_ree_data.csv")
    (project / "current.yaml").write_text(
        yaml.safe_dump(recipe, sort_keys=False), encoding="utf-8"
    )
    request = project / "requests" / "screen.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "screen",
                "recipe": "current.yaml",
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            "screen",
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
    assert completed.returncode == 0
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["status"] == "ready"
    assert report["result"]["available"] is False
    assert report["result"]["results"] == []
    assert report["result"]["disclaimer"] == SCREENING_DISCLAIMER
    assert "XY workflow" in report["issues"][0]["message"]


def test_source_mode_screening_uses_reviewed_major_mapping(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "requests").mkdir(parents=True)
    (project / "cache").mkdir()
    recipe = yaml.safe_load(
        (EXAMPLES / "geoskills_major_workflow.yaml").read_text(encoding="utf-8")
    )
    recipe["input"]["file"] = "synthetic_major_element_data.csv"
    shutil.copyfile(
        EXAMPLES / "synthetic_major_element_data.csv",
        project / "synthetic_major_element_data.csv",
    )
    (project / "current.yaml").write_text(
        yaml.safe_dump(recipe, sort_keys=False), encoding="utf-8"
    )
    request = project / "requests" / "screen.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "screen",
                "recipe": "current.yaml",
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            "screen",
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
    assert completed.returncode == 0, completed.stderr
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["status"] == "ready"
    assert report["result"]["available"] is True
    assert 1 <= len(report["result"]["results"]) <= MAX_SCREENING_RESULTS
    assert all(item["n"] >= MIN_PAIR_COUNT for item in report["result"]["results"])
    assert report["result"]["method"] == "spearman_rank_then_pearson"
