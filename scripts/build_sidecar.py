#!/usr/bin/env python3
"""Build the GeoPlot Python sidecar for the current native platform."""

from __future__ import annotations

import argparse
import platform
import shutil
import struct
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


BRIDGE_STEM = "geoskills-desktop-bridge"
SUPPORTED_TARGETS = (
    "x86_64-pc-windows-msvc",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
)
_HOST_TARGETS = {
    ("windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("darwin", "aarch64"): "aarch64-apple-darwin",
}
_MACHINE_ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}


class SidecarBuildError(RuntimeError):
    """Raised when a native sidecar build cannot be performed safely."""


def detect_native_target(
    system_name: str | None = None,
    machine_name: str | None = None,
    pointer_bits: int | None = None,
) -> str:
    """Return the allowlisted target matching the running Python interpreter."""

    system_value = (system_name or platform.system()).strip().lower()
    machine_value = (machine_name or platform.machine()).strip().lower()
    normalized_machine = _MACHINE_ALIASES.get(machine_value, machine_value)
    interpreter_bits = pointer_bits or struct.calcsize("P") * 8

    if interpreter_bits != 64:
        raise SidecarBuildError(
            f"unsupported {interpreter_bits}-bit Python interpreter; a native 64-bit "
            "interpreter is required"
        )

    target = _HOST_TARGETS.get((system_value, normalized_machine))
    if target is None:
        raise SidecarBuildError(
            "unsupported native platform "
            f"{system_value or '<unknown>'}/{normalized_machine or '<unknown>'}; "
            f"allowed targets: {', '.join(SUPPORTED_TARGETS)}"
        )
    return target


def validate_native_target(requested_target: str, native_target: str) -> str:
    """Reject unknown targets and all cross-compilation requests."""

    if requested_target not in SUPPORTED_TARGETS:
        raise SidecarBuildError(
            f"unsupported target triple {requested_target!r}; allowed targets: "
            f"{', '.join(SUPPORTED_TARGETS)}"
        )
    if requested_target != native_target:
        raise SidecarBuildError(
            "cross-compiling frozen Python sidecars is not supported: "
            f"requested {requested_target}, native interpreter is {native_target}"
        )
    return requested_target


def generic_artifact_name(target: str) -> str:
    """Return the filename emitted by the generic PyInstaller spec."""

    return f"{BRIDGE_STEM}.exe" if target.endswith("windows-msvc") else BRIDGE_STEM


def tauri_artifact_name(target: str) -> str:
    """Return the exact external-binary filename expected by Tauri."""

    suffix = ".exe" if target.endswith("windows-msvc") else ""
    return f"{BRIDGE_STEM}-{target}{suffix}"


def build_sidecar(
    repo_root: Path,
    requested_target: str | None = None,
    *,
    runner: Callable[..., object] = subprocess.run,
) -> Path:
    """Build a generic frozen bridge, then copy it to Tauri's native name."""

    root = repo_root.resolve()
    native_target = detect_native_target()
    target = validate_native_target(requested_target or native_target, native_target)
    spec = (
        root
        / "apps"
        / "desktop"
        / "backend"
        / "pyinstaller"
        / "geoskills-desktop-bridge.spec"
    )
    if not spec.is_file():
        raise SidecarBuildError(f"PyInstaller spec not found: {spec}")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec),
    ]
    runner(command, cwd=root, check=True)

    generic_artifact = root / "dist" / generic_artifact_name(target)
    if not generic_artifact.is_file():
        raise SidecarBuildError(
            f"PyInstaller completed without the expected native artifact: {generic_artifact}"
        )

    binaries = root / "apps" / "desktop" / "src-tauri" / "binaries"
    binaries.mkdir(parents=True, exist_ok=True)
    destination = binaries / tauri_artifact_name(target)
    shutil.copy2(generic_artifact, destination)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the reviewed Python bridge for the current native platform and "
            "place it under Tauri's required target-triple filename."
        )
    )
    parser.add_argument(
        "--target",
        help="native Rust target triple; defaults to the running Python platform",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        destination = build_sidecar(repo_root, args.target)
    except SidecarBuildError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Built native sidecar: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
