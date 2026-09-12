# GeoPlot desktop application

This directory contains the React and Tauri interface for GeoPlot. The app is a
thin, local-first layer over the bundled GeoSkills scientific engine.

## Product and engine boundaries

- **GeoPlot** is the user-facing application, installer, window, and repository.
- **GeoSkills** remains the internal scientific engine and schema namespace.
- The desktop bridge accepts only allowlisted operations and bounded JSON.
- The frontend does not duplicate scientific unit or classification rules.

## Local project lifecycle

The app creates an internal project copy before inspection. The external source
file is never edited. Project removal is reversible and moves only the managed
copy out of the active list; restoration returns it to the list.

On Windows, the managed project root remains
`%LOCALAPPDATA%\Programs\GeoSkillsDesktopData` for compatibility with earlier
review builds, so existing local projects remain available after installing
GeoPlot. This internal directory name is not the repository or product name.

## Review and execution

1. Import a supported local table.
2. Select the sheet and table orientation where needed.
3. Review every analyte mapping and its expected unit.
4. Resolve errors and explicitly confirm the recipe.
5. Create a deterministic execution plan.
6. Run the current valid plan and inspect the resulting artifacts.

Explicit unit conflicts fail closed. Units are never inferred from numerical
magnitude. Major-element options use wt%; trace-element options use ppm.

## Commands

```powershell
npm ci
npm test
npm run build
cargo test --manifest-path src-tauri\Cargo.toml
```

Use `npm run tauri dev` for source-mode development after installing the Python
requirements from the repository root. A packaged build additionally requires
the PyInstaller sidecar described in the root README.
