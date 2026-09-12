"""Single fail-closed locator for bundled GeoSkills scientific resources."""

from __future__ import annotations

import sys
from pathlib import Path


class ResourcePathError(RuntimeError):
    """The immutable scientific resource tree is unavailable."""


def skill_root() -> Path:
    """Return the verified GeoSkills root in source or PyInstaller mode."""

    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise ResourcePathError("Frozen GeoSkills resource root is unavailable.")
        root = Path(bundle_root) / "skills" / "geoskills"
    else:
        root = Path(__file__).resolve().parents[2]
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ResourcePathError("GeoSkills resource root is unavailable.") from exc
    required = (
        resolved / "assets" / "normalization",
        resolved / "assets" / "classification",
    )
    if any(path.is_symlink() or not path.is_dir() for path in required):
        raise ResourcePathError("GeoSkills scientific asset directories are unavailable.")
    return resolved


__all__ = ["ResourcePathError", "skill_root"]
