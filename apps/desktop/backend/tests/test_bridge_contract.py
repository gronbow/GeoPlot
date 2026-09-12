from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "apps" / "desktop" / "backend"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
BRIDGE = BACKEND / "geoskills_desktop_bridge.py"
sys.path.insert(0, str(BACKEND))

from contract import MAX_REQUEST_BYTES, REQUEST_SCHEMA_VERSION  # noqa: E402
from mixed_unit_fixture import (  # noqa: E402
    mixed_public_contract,
    write_mixed_unit_transposed_workbook,
)
MIXED_INSPECT_GOLDEN = (
    ROOT / "apps" / "desktop" / "tests" / "fixtures" / "mixed-unit-inspect.json"
)


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "requests").mkdir(parents=True)
    (project / "workspace").mkdir()
    return project


def write_request(project: Path, name: str, document: dict) -> Path:
    path = project / "requests" / f"{name}.json"
    path.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    return path


def inspect_request(source: str, *, sheet=None, layout: str = "auto") -> dict:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "operation": "inspect",
        "source": source,
        "sheet": sheet,
        "layout": layout,
    }


def run_bridge(
    operation: str, project: Path | None = None, request: Path | None = None
) -> tuple[subprocess.CompletedProcess[str], dict]:
    arguments = [sys.executable, str(BRIDGE), operation]
    if project is not None:
        arguments.extend(["--project", str(project)])
    if request is not None:
        arguments.extend(["--request", str(request)])
    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, completed.stdout
    return completed, json.loads(lines[0])


def issue_codes(report: dict) -> set[str]:
    return {str(item["code"]) for item in report["issues"]}


def test_version_and_capabilities_are_source_mode_json() -> None:
    version_process, version = run_bridge("version")
    capabilities_process, capabilities = run_bridge("capabilities")

    assert version_process.returncode == 0
    assert version["schema_version"] == "geoskills.desktop-report/v1"
    assert version["result"]["bridge_mode"] == "source"
    assert capabilities_process.returncode == 0
    assert capabilities["result"]["diagram_ids"] == [
        "ree",
        "spider",
        "harker",
        "tas",
        "k2o-sio2",
        "xy",
    ]


def test_valid_csv_inspect_is_bounded_and_keeps_full_counts(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "input.csv"
    shutil.copyfile(EXAMPLES / "synthetic_ree_data.csv", source)
    request = write_request(
        project, "inspect", inspect_request("workspace/input.csv")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 0
    assert report["status"] == "ready"
    result = report["result"]
    assert result["row_count"] == 3
    assert result["sample_column_suggestion"] == "Sample"
    assert len(result["recognized_analytes"]) == 14
    assert len(result["preview"]["rows"]) == 3
    assert len(result["preview"]["columns"]) == 16
    assert "La" in result["mapping_suggestions"]
    candidates = {item["diagram"]: item for item in result["figure_candidates"]}
    assert candidates["ree"]["state"] == "AVAILABLE_AFTER_REVIEW"
    assert candidates["xy"]["state"] == "NEEDS_PARAMETER"


def test_preview_is_capped_at_30_rows_and_40_columns(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "wide.csv"
    columns = ["Sample", *[f"Column_{index}" for index in range(45)]]
    rows = [[f"S-{row}", *range(45)] for row in range(35)]
    pd.DataFrame(rows, columns=columns).to_csv(source, index=False)
    request = write_request(
        project, "inspect", inspect_request("workspace/wide.csv")
    )

    _, report = run_bridge("inspect", project, request)

    preview = report["result"]["preview"]
    assert report["result"]["row_count"] == 35
    assert report["result"]["column_count"] == 46
    assert len(preview["rows"]) == 30
    assert len(preview["columns"]) == 40
    assert preview["preview_truncated_rows"] is True
    assert preview["preview_truncated_columns"] is True


def test_valid_single_sheet_xlsx_inspect(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "input.xlsx"
    frame = pd.read_csv(EXAMPLES / "synthetic_ree_data.csv")
    frame.to_excel(source, sheet_name="REE", index=False)
    request = write_request(
        project, "inspect", inspect_request("workspace/input.xlsx")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 0
    assert report["status"] == "ready"
    assert report["result"]["source"]["selected_sheet"] == "REE"


def test_mixed_unit_transposed_contract_matches_frontend_golden(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "mixed-units.xlsx"
    write_mixed_unit_transposed_workbook(source)
    request = write_request(
        project, "inspect", inspect_request("workspace/mixed-units.xlsx")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 0
    assert report["status"] == "ready"
    result = report["result"]
    recognized = result["recognized_analytes"]
    assert result["source"]["layout"] == "column_per_sample_transposed"
    assert len(recognized) == 47
    assert len({item["canonical"] for item in recognized}) == 47
    assert all(item["canonical"].strip() for item in recognized)
    assert all(
        set(item) == {
            "canonical", "kind", "required_unit", "source_label",
            "explicit_unit", "source_column", "unit_status",
        }
        for item in recognized
    )
    assert sum(
        item["required_unit"] == item["explicit_unit"] == "wt%"
        and item["unit_status"] == "confirmed_from_header"
        for item in recognized
    ) == 12
    assert sum(
        item["required_unit"] == item["explicit_unit"] == "ppm"
        and item["unit_status"] == "confirmed_from_header"
        for item in recognized
    ) == 35
    assert result["quality"]["unknown_unit_count"] == 0
    assert result["quality"]["unit_conflict_count"] == 0

    # This checked-in frontend fixture is a real source-mode bridge result,
    # not a separately invented TypeScript schema.
    golden = json.loads(MIXED_INSPECT_GOLDEN.read_text(encoding="utf-8"))
    assert mixed_public_contract(result) == golden


def test_multi_sheet_xlsx_requires_explicit_selection(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "input.xlsx"
    frame = pd.read_csv(EXAMPLES / "synthetic_ree_data.csv")
    with pd.ExcelWriter(source) as writer:
        frame.to_excel(writer, sheet_name="First", index=False)
        frame.to_excel(writer, sheet_name="Second", index=False)
    request = write_request(
        project, "inspect", inspect_request("workspace/input.xlsx")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 2
    assert report["status"] == "needs_confirmation"
    assert report["result"]["source"]["sheet_names"] == ["First", "Second"]
    assert report["result"]["preview"] is None
    assert issue_codes(report) == {"D101"}


def test_unsupported_suffix_is_blocked_before_parser(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "input.json"
    source.write_text("{}", encoding="utf-8")
    request = write_request(
        project, "inspect", inspect_request("workspace/input.json")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 2
    assert report["status"] == "blocked"
    assert report["issues"]


def test_oversized_input_is_blocked_before_pandas(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "large.csv"
    with source.open("wb") as stream:
        stream.truncate(20 * 1024 * 1024 + 1)
    request = write_request(
        project, "inspect", inspect_request("workspace/large.csv")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 2
    assert report["status"] == "blocked"
    assert report["issues"]


def test_ambiguous_sample_columns_require_review(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "ambiguous.csv"
    source.write_text(
        "Sample,Sample_ID,La_ppm,Ce_ppm,Pr_ppm\nA,A,1,2,3\n",
        encoding="utf-8",
    )
    request = write_request(
        project, "inspect", inspect_request("workspace/ambiguous.csv")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 2
    assert report["status"] == "needs_confirmation"
    assert report["result"]["sample_column_suggestion"] is None
    assert len(report["result"]["sample_column_candidates"]) == 2
    assert "D103" in issue_codes(report)


def test_unknown_units_are_reported_and_never_inferred_from_values(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "unknown-units.csv"
    source.write_text(
        "Sample,La,Ce,Pr,Nd,Sm\nA,1,2,3,4,5\n",
        encoding="utf-8",
    )
    request = write_request(
        project, "inspect", inspect_request("workspace/unknown-units.csv")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 2
    assert report["status"] == "needs_confirmation"
    assert report["result"]["quality"]["unknown_unit_count"] == 5
    assert "D106" in issue_codes(report)
    ree = next(
        item
        for item in report["result"]["figure_candidates"]
        if item["diagram"] == "ree"
    )
    assert "units_review_required" in ree["requirements"]


def test_explicit_unit_conflict_is_blocked_fail_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "conflicting-units.csv"
    source.write_text(
        "Sample,La_wt%,Ce_ppm,Pr_ppm,Nd_ppm,Sm_ppm\nA,1,2,3,4,5\n",
        encoding="utf-8",
    )
    request = write_request(
        project, "inspect", inspect_request("workspace/conflicting-units.csv")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 2
    assert report["status"] == "blocked"
    assert report["result"]["quality"]["unit_conflict_count"] == 1
    assert "D105" in issue_codes(report)
    lanthanum = next(
        item
        for item in report["result"]["recognized_analytes"]
        if item["canonical"] == "La"
    )
    assert lanthanum["required_unit"] == "ppm"
    assert lanthanum["explicit_unit"] == "wt%"
    assert lanthanum["unit_status"] == "conflict"


def test_unrecognized_columns_are_visible_not_silently_mapped(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "unknown.csv"
    source.write_text(
        "Sample,La_ppm,Ce_ppm,Pr_ppm,Note,SecretSauce\nA,1,2,3,x,9\n",
        encoding="utf-8",
    )
    request = write_request(
        project, "inspect", inspect_request("workspace/unknown.csv")
    )

    _, report = run_bridge("inspect", project, request)

    assert report["result"]["unrecognized_columns"] == ["Note", "SecretSauce"]


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda request: request.update(schema_version="wrong/v1"), "D001"),
        (lambda request: request.update(unexpected=True), "D005"),
        (lambda request: request.update(source="C:/data/input.csv"), "D022"),
        (lambda request: request.update(source="../input.csv"), "D022"),
        (lambda request: request.update(source="file://input.csv"), "D022"),
        (lambda request: request.update(source="*.csv"), "D022"),
        (lambda request: request.update(source="CON.csv"), "D022"),
    ],
)
def test_invalid_requests_fail_closed(
    tmp_path: Path, mutator, expected_code: str
) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "input.csv"
    shutil.copyfile(EXAMPLES / "synthetic_ree_data.csv", source)
    document = inspect_request("workspace/input.csv")
    mutator(document)
    request = write_request(project, "invalid", document)

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 1
    assert report["status"] == "error"
    assert expected_code in issue_codes(report)


def test_request_must_be_inside_requests_directory(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    request = project / "outside.json"
    request.write_text(
        json.dumps(inspect_request("workspace/input.csv")), encoding="utf-8"
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 1
    assert report["status"] == "error"
    assert issue_codes(report) == {"D024"}


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    request = project / "requests" / "duplicate.json"
    request.write_text(
        '{"schema_version":"geoskills.desktop-request/v1",'
        '"operation":"inspect","operation":"run",'
        '"source":"workspace/input.csv","sheet":null,"layout":"auto"}',
        encoding="utf-8",
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 1
    assert report["status"] == "error"
    assert issue_codes(report) == {"D003"}


def test_request_size_limit_is_enforced(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    request = project / "requests" / "large.json"
    with request.open("wb") as stream:
        stream.truncate(MAX_REQUEST_BYTES + 1)

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 1
    assert report["status"] == "error"
    assert issue_codes(report) == {"D025"}


def test_major_candidates_expose_scientific_gates(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "workspace" / "major.csv"
    shutil.copyfile(EXAMPLES / "synthetic_major_element_data.csv", source)
    request = write_request(
        project, "inspect", inspect_request("workspace/major.csv")
    )

    completed, report = run_bridge("inspect", project, request)

    assert completed.returncode == 0
    candidates = {
        item["diagram"]: item for item in report["result"]["figure_candidates"]
    }
    assert candidates["harker"]["state"] == "AVAILABLE_AFTER_REVIEW"
    assert candidates["harker"]["suggestions"]["x"] == "SiO2"
    assert candidates["tas"]["state"] == "NEEDS_SCIENTIFIC_CONFIRMATION"
    assert candidates["k2o-sio2"]["state"] == "NEEDS_SCIENTIFIC_CONFIRMATION"
    assert "volcanic_samples" in candidates["tas"]["requirements"]
    assert "composition_basis_reviewed" in candidates["tas"]["requirements"]
