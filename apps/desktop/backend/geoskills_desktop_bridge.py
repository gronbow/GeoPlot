#!/usr/bin/env python3
"""Narrow source-mode command bridge for GeoPlot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn


BACKEND_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = (
    Path(getattr(sys, "_MEIPASS"))
    if getattr(sys, "frozen", False)
    else BACKEND_DIR.parents[2]
)
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "geoskills" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from contract import (  # noqa: E402
    ContractError,
    envelope,
    issue,
    load_request,
    project_member,
)
from data_inspection import inspect_project  # noqa: E402
from geoskills_core.errors import GeoSkillsError  # noqa: E402
from geoskills_core.registry import (  # noqa: E402
    DIAGRAM_API_VERSION,
    diagram_ids,
    registry_snapshot,
)
from geoskills_core.version import VERSION  # noqa: E402
from geoskills_core.workflow import create_plan, execute_plan  # noqa: E402
from recipe_builder import build_recipe  # noqa: E402
from screening import screen_project  # noqa: E402


def engine_record() -> dict[str, str]:
    return {
        "name": "GeoSkills",
        "version": VERSION,
        "diagram_api_version": DIAGRAM_API_VERSION,
    }


def bridge_mode() -> str:
    return "frozen" if getattr(sys, "frozen", False) else "source"


def _emit(document: dict[str, Any]) -> None:
    print(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        operation = (
            sys.argv[1]
            if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
            else "unknown"
        )
        _emit(
            envelope(
                operation,
                "error",
                engine=engine_record(),
                issues=[issue("D900", "error", message)],
            )
        )
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="GeoPlot local bridge",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("version", allow_abbrev=False)
    commands.add_parser("capabilities", allow_abbrev=False)
    for operation in ("inspect", "recipe", "plan", "run", "screen"):
        command = commands.add_parser(operation, allow_abbrev=False)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--request", type=Path, required=True)
    return parser


def _validate_selected_tasks(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ContractError(
            "D050",
            "selected_task_ids must be null or a non-empty list.",
            "selected_task_ids",
        )
    tasks: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(
                "D050",
                "selected_task_ids must contain non-empty text values.",
                "selected_task_ids",
            )
        tasks.append(item.strip())
    if len(tasks) != len(set(tasks)):
        raise ContractError(
            "D050", "selected_task_ids cannot contain duplicates.", "selected_task_ids"
        )
    return tasks


def _workflow_status(value: Any) -> str:
    status = str(value)
    if status in {"ready", "needs_confirmation", "review", "blocked", "error"}:
        return status
    return "error"


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    operation = str(args.operation)
    engine = engine_record()
    if operation == "version":
        return envelope(
            operation,
            "ready",
            engine=engine,
            result={
                "tool_version": VERSION,
                "diagram_api_version": DIAGRAM_API_VERSION,
                "bridge_mode": bridge_mode(),
            },
        )
    if operation == "capabilities":
        return envelope(
            operation,
            "ready",
            engine=engine,
            result={
                "diagram_ids": list(diagram_ids()),
                "diagrams": registry_snapshot(),
            },
        )
    project, request = load_request(args.project, args.request, operation)
    if operation == "inspect":
        status, result, issues = inspect_project(project, request)
        return envelope(operation, status, engine=engine, result=result, issues=issues)
    if operation == "recipe":
        status, result, issues = build_recipe(project, request)
        return envelope(operation, status, engine=engine, result=result, issues=issues)
    if operation == "screen":
        status, result, issues = screen_project(project, request)
        return envelope(operation, status, engine=engine, result=result, issues=issues)
    recipe_path = project_member(
        project, request["recipe"], "recipe", must_exist=True, expect_file=True
    )
    plan_path = project_member(
        project,
        request["plan"],
        "plan",
        must_exist=operation == "run",
        expect_file=operation == "run",
    )
    overwrite = request["overwrite"]
    if not isinstance(overwrite, bool):
        raise ContractError("D044", "overwrite must be true or false.", "overwrite")
    if operation == "plan":
        report = create_plan(
            recipe_path,
            plan_path,
            selected_task_ids=_validate_selected_tasks(request["selected_task_ids"]),
            overwrite=overwrite,
        )
    else:
        report = execute_plan(recipe_path, plan_path, overwrite=overwrite)
    status = _workflow_status(report.get("status"))
    result = {
        str(key): value
        for key, value in report.items()
        if key not in {"status", "issues"}
    }
    issues = [dict(item) for item in report.get("issues", [])]
    if status == "error" and str(report.get("status")) != "error":
        issues.append(issue("D051", "error", "GeoSkills returned an unknown status."))
    return envelope(operation, status, engine=engine, result=result, issues=issues)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        document = dispatch(args)
    except ContractError as exc:
        document = envelope(
            str(args.operation),
            "error",
            engine=engine_record(),
            issues=[exc.to_issue()],
        )
    except GeoSkillsError as exc:
        document = envelope(
            str(args.operation),
            "blocked",
            engine=engine_record(),
            issues=[exc.to_issue()],
        )
    except Exception:
        document = envelope(
            str(args.operation),
            "error",
            engine=engine_record(),
            issues=[
                issue(
                    "D999",
                    "error",
                    "GeoPlot encountered an unexpected local error.",
                )
            ],
        )
    _emit(document)
    print(
        f"GeoPlot {args.operation}: {document['status']}.",
        file=sys.stderr,
    )
    return 0 if document["status"] == "ready" else (2 if document["status"] in {"needs_confirmation", "review", "blocked"} else 1)


if __name__ == "__main__":
    raise SystemExit(main())
