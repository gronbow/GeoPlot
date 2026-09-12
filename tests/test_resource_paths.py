from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "geoskills" / "scripts"))

from geoskills_core.resources import ResourcePathError, skill_root


def test_source_resource_root_contains_the_scientific_assets() -> None:
    root = skill_root()
    assert root.name == "geoskills"
    assert (root / "assets" / "normalization" / "chondrite-sm89.json").is_file()
    assert (root / "assets" / "classification" / "tas-lemaitre-2002.json").is_file()


def test_frozen_resource_root_uses_only_the_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundled = tmp_path / "skills" / "geoskills" / "assets"
    (bundled / "normalization").mkdir(parents=True)
    (bundled / "classification").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert skill_root() == tmp_path / "skills" / "geoskills"


def test_frozen_resource_root_fails_closed_when_assets_are_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(ResourcePathError):
        skill_root()
