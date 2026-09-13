#!/usr/bin/env python3
"""Fail when the three GeoPlot product-version declarations diverge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib


VERSION_PATHS = {
    "npm": Path("apps/desktop/package.json"),
    "cargo": Path("apps/desktop/src-tauri/Cargo.toml"),
    "tauri": Path("apps/desktop/src-tauri/tauri.conf.json"),
}


class VersionCheckError(ValueError):
    """Raised when a version file is missing, invalid, or inconsistent."""


def _read_json(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VersionCheckError(f"Could not read valid JSON from {path}.") from exc
    if not isinstance(document, dict):
        raise VersionCheckError(f"Expected a JSON object in {path}.")
    return document


def _read_cargo(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise VersionCheckError(f"Could not read valid TOML from {path}.") from exc
    if not isinstance(document, dict):
        raise VersionCheckError(f"Expected a TOML table in {path}.")
    return document


def _version(value: object, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VersionCheckError(f"Missing product version in {path}.")
    return value.strip()


def read_product_versions(repo_root: Path) -> dict[str, str]:
    """Read the npm, Cargo, and Tauri version declarations."""

    root = repo_root.resolve(strict=True)
    paths = {name: root / relative for name, relative in VERSION_PATHS.items()}
    package = _read_json(paths["npm"])
    cargo = _read_cargo(paths["cargo"])
    tauri = _read_json(paths["tauri"])

    cargo_package = cargo.get("package")
    if not isinstance(cargo_package, dict):
        raise VersionCheckError(f"Missing [package] table in {paths['cargo']}.")

    return {
        "npm": _version(package.get("version"), paths["npm"]),
        "cargo": _version(cargo_package.get("version"), paths["cargo"]),
        "tauri": _version(tauri.get("version"), paths["tauri"]),
    }


def require_consistent_versions(repo_root: Path) -> str:
    """Return the shared product version or raise with bounded diagnostics."""

    versions = read_product_versions(repo_root)
    if len(set(versions.values())) != 1:
        details = ", ".join(f"{name}={value}" for name, value in versions.items())
        raise VersionCheckError(f"GeoPlot product versions diverge: {details}.")
    return next(iter(versions.values()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root containing the three product version files.",
    )
    args = parser.parse_args(argv)
    try:
        version = require_consistent_versions(args.repo_root)
    except VersionCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"GeoPlot product versions are consistent: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
