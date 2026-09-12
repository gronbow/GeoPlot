# GeoPlot

<p align="center">
  <img src="apps/desktop/src/assets/geoplot-icon-master.png" alt="GeoPlot icon" width="144">
</p>

GeoPlot is a local-first Windows desktop application for reviewing geochemical
tables, confirming analyte mappings and units, and producing reproducible plots.
It provides a graphical interface around the reviewed GeoSkills scientific
engine while keeping imported research data on the user's computer.

## Current status

GeoPlot 0.1.0 is the first standalone desktop release candidate. The source
repository and the Windows installer are produced independently of the
GeoSkills repository.

The Windows installer is currently unsigned. Verify its published SHA-256
checksum before opening it; Windows SmartScreen may show an unrecognized-app
warning until code signing is introduced.

## What it does

- Imports XLSX, CSV, and TXT files up to 20 MiB into private app-managed storage.
- Detects a fixed registry of 47 analytes: 12 major elements in wt% and 35 trace
  elements in ppm.
- Keeps unit conflicts visible and requires human review instead of guessing or
  inferring units from numerical magnitude.
- Supports project rename, soft removal, and restoration without touching the
  original external data file.
- Uses a responsive single-page layout without root-level horizontal scrolling
  at the supported window sizes.
- Creates a reviewed recipe, a deterministic plan, and only then runs plotting.

## Safety model

- Local processing only; plotting does not require a cloud service.
- Original imported files remain unchanged.
- Recipes are never marked confirmed without an explicit user action.
- Explicit unit conflicts fail closed.
- Plans are invalidated when relevant input, recipe, version, task, style, or
  scientific assets change.
- Failed multi-task runs do not leave a partial replacement output directory.

## Repository layout

```text
apps/desktop/                 React + Tauri desktop application
skills/geoskills/scripts/     bundled scientific engine
skills/geoskills/assets/      reviewed scientific reference assets
skills/geoskills/examples/    synthetic examples used by tests
tests/                        scientific and safety regression suite
```

The product name is **GeoPlot**. Internal engine schemas and the bundled bridge
retain the **GeoSkills** name so that reviewed scientific contracts remain
compatible and auditable.

## Development

Requirements:

- Windows 10 or 11
- Python 3.11 or newer
- Node.js 22 or newer
- Rust 1.85 or newer
- Visual Studio Build Tools 2022 with the Desktop development with C++ workload

Install and test:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
Set-Location apps\desktop
npm ci
npm test
npm run build
cargo test --manifest-path src-tauri\Cargo.toml
Set-Location ..\..
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest apps\desktop\backend\tests -q
```

Package the bundled Python bridge before running the Tauri installer build:

```powershell
.\.venv\Scripts\python -m pip install pyinstaller -r apps\desktop\backend\requirements-build.txt
.\.venv\Scripts\python -m PyInstaller --clean --noconfirm apps\desktop\backend\pyinstaller\geoskills-desktop-bridge.spec
Copy-Item .\dist\geoskills-desktop-bridge-x86_64-pc-windows-msvc.exe .\apps\desktop\src-tauri\binaries\
Set-Location apps\desktop
npm run tauri build
```

Build products, installers, sidecar executables, local data, and caches are
excluded from source control.

## License and attribution

The bundled scientific engine is derived from GeoSkills and remains covered by
the repository's MIT license and original copyright notice. The GeoPlot product
name and icon identify this standalone desktop distribution.

## Security

Please read [SECURITY.md](SECURITY.md) before reporting a vulnerability. Never
attach unpublished measurements, sample identifiers, credentials, or private
paths to a public issue.
