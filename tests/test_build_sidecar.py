from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_sidecar


@pytest.mark.parametrize(
    ("system_name", "machine_name", "expected"),
    [
        ("Windows", "AMD64", "x86_64-pc-windows-msvc"),
        ("Darwin", "x86_64", "x86_64-apple-darwin"),
        ("Darwin", "arm64", "aarch64-apple-darwin"),
    ],
)
def test_detect_native_target_allowlist(
    system_name: str,
    machine_name: str,
    expected: str,
) -> None:
    assert build_sidecar.detect_native_target(system_name, machine_name, 64) == expected


@pytest.mark.parametrize(
    ("system_name", "machine_name", "pointer_bits"),
    [
        ("Linux", "x86_64", 64),
        ("Windows", "ARM64", 64),
        ("Darwin", "mips", 64),
        ("Windows", "AMD64", 32),
    ],
)
def test_detect_native_target_rejects_unsupported_hosts(
    system_name: str,
    machine_name: str,
    pointer_bits: int,
) -> None:
    with pytest.raises(build_sidecar.SidecarBuildError):
        build_sidecar.detect_native_target(system_name, machine_name, pointer_bits)


def test_validate_native_target_rejects_unknown_and_cross_compile() -> None:
    native = "x86_64-pc-windows-msvc"
    with pytest.raises(build_sidecar.SidecarBuildError, match="unsupported target triple"):
        build_sidecar.validate_native_target("x86_64-unknown-linux-gnu", native)
    with pytest.raises(build_sidecar.SidecarBuildError, match="cross-compiling"):
        build_sidecar.validate_native_target("aarch64-apple-darwin", native)


@pytest.mark.parametrize(
    ("target", "generic", "tauri"),
    [
        (
            "x86_64-pc-windows-msvc",
            "geoskills-desktop-bridge.exe",
            "geoskills-desktop-bridge-x86_64-pc-windows-msvc.exe",
        ),
        (
            "x86_64-apple-darwin",
            "geoskills-desktop-bridge",
            "geoskills-desktop-bridge-x86_64-apple-darwin",
        ),
        (
            "aarch64-apple-darwin",
            "geoskills-desktop-bridge",
            "geoskills-desktop-bridge-aarch64-apple-darwin",
        ),
    ],
)
def test_artifact_names_are_exact(target: str, generic: str, tauri: str) -> None:
    assert build_sidecar.generic_artifact_name(target) == generic
    assert build_sidecar.tauri_artifact_name(target) == tauri


def test_build_sidecar_uses_generic_spec_and_copies_native_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "x86_64-pc-windows-msvc"
    spec = (
        tmp_path
        / "apps"
        / "desktop"
        / "backend"
        / "pyinstaller"
        / "geoskills-desktop-bridge.spec"
    )
    spec.parent.mkdir(parents=True)
    spec.write_text("# reviewed spec\n", encoding="utf-8")
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_runner(command: list[str], *, cwd: Path, check: bool) -> object:
        calls.append((command, cwd, check))
        artifact = cwd / "dist" / "geoskills-desktop-bridge.exe"
        artifact.parent.mkdir()
        artifact.write_bytes(b"frozen-bridge")
        return object()

    monkeypatch.setattr(build_sidecar, "detect_native_target", lambda: target)
    destination = build_sidecar.build_sidecar(
        tmp_path,
        requested_target=target,
        runner=fake_runner,
    )

    assert destination.name == f"geoskills-desktop-bridge-{target}.exe"
    assert destination.read_bytes() == b"frozen-bridge"
    assert len(calls) == 1
    command, cwd, check = calls[0]
    assert command[:3] == [build_sidecar.sys.executable, "-m", "PyInstaller"]
    assert command[-1] == str(spec)
    assert cwd == tmp_path
    assert check is True


def test_build_sidecar_fails_if_pyinstaller_does_not_emit_expected_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "x86_64-pc-windows-msvc"
    spec = (
        tmp_path
        / "apps"
        / "desktop"
        / "backend"
        / "pyinstaller"
        / "geoskills-desktop-bridge.spec"
    )
    spec.parent.mkdir(parents=True)
    spec.write_text("# reviewed spec\n", encoding="utf-8")
    monkeypatch.setattr(build_sidecar, "detect_native_target", lambda: target)

    with pytest.raises(build_sidecar.SidecarBuildError, match="expected native artifact"):
        build_sidecar.build_sidecar(
            tmp_path,
            requested_target=target,
            runner=lambda *args, **kwargs: object(),
        )
