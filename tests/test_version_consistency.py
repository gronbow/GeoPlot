from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_versions import (  # noqa: E402
    VersionCheckError,
    main,
    read_product_versions,
    require_consistent_versions,
)


def _write_versions(root: Path, *, npm: str, cargo: str, tauri: str) -> None:
    desktop = root / "apps" / "desktop"
    tauri_root = desktop / "src-tauri"
    tauri_root.mkdir(parents=True)
    (desktop / "package.json").write_text(
        json.dumps({"name": "geoplot", "version": npm}),
        encoding="utf-8",
    )
    (tauri_root / "Cargo.toml").write_text(
        f'[package]\nname = "geoplot"\nversion = "{cargo}"\n',
        encoding="utf-8",
    )
    (tauri_root / "tauri.conf.json").write_text(
        json.dumps({"productName": "GeoPlot", "version": tauri}),
        encoding="utf-8",
    )


def test_repository_product_versions_are_consistent() -> None:
    versions = read_product_versions(ROOT)
    assert set(versions) == {"npm", "cargo", "tauri"}
    assert len(set(versions.values())) == 1
    assert require_consistent_versions(ROOT) == versions["npm"]


def test_divergent_product_versions_fail_closed(tmp_path: Path) -> None:
    _write_versions(tmp_path, npm="0.2.0", cargo="0.2.0", tauri="0.1.0")
    with pytest.raises(VersionCheckError, match="versions diverge"):
        require_consistent_versions(tmp_path)
    assert main(["--repo-root", str(tmp_path)]) == 1


def test_missing_version_fails_closed(tmp_path: Path) -> None:
    _write_versions(tmp_path, npm="0.2.0", cargo="0.2.0", tauri="0.2.0")
    (tmp_path / "apps" / "desktop" / "package.json").write_text(
        json.dumps({"name": "geoplot"}),
        encoding="utf-8",
    )
    with pytest.raises(VersionCheckError, match="Missing product version"):
        require_consistent_versions(tmp_path)
