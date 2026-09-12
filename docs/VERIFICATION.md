# GeoPlot 0.1.0 verification

Verification date: 2026-09-13

## Scope

This record covers the first standalone GeoPlot repository, product rename,
top-left supplied icon, bundled sidecar, and Windows x86_64 NSIS installer.

## Gate sequence retained

The desktop implementation preserves the completed gated workflow:

1. baseline and scope review;
2. local-first safety contract;
3. frontend shell and managed project storage;
4. source-mode review, plan, run, and output preview;
5. frozen-sidecar parity;
6. Windows packaging verification.

No scientific rule, normalization value, unit inference policy, or confirmation
contract was loosened during the standalone extraction and product rename.

## Automated verification

- Frontend: 22 tests passed.
- Frontend production build: passed.
- Python source-mode suite: 336 passed, 7 skipped. The skips are platform- or
  frozen-binary-gated tests.
- Frozen sidecar parity: 6 passed.
- Rust/Tauri: 20 passed.
- npm dependency audit: 0 known vulnerabilities.
- Local Edge responsive QA passed at 1180 x 760, 900 x 760, and 760 x 560:
  no root horizontal overflow, no clipped controls, all 47 mappings and 47 unit
  controls present, and completed plan/run output visible.
- Rendered screenshots at 1180 x 760 and 760 x 560 were visually inspected.

## Artifacts

Windows installer:

- file: `GeoPlot_0.1.0_x64-setup.exe`
- size: 57,747,936 bytes
- SHA-256: `F594B2D5A54BCB615BBD2151E54E0E3DC667A086ED655308CEAA625010FA610F`
- Authenticode status: `NotSigned`
- embedded product name: `GeoPlot`
- embedded file description: `GeoPlot`

Bundled scientific sidecar:

- file: `geoskills-desktop-bridge-x86_64-pc-windows-msvc.exe`
- size: 54,634,269 bytes
- SHA-256: `AE241BB2EF58843FD8E4A0544B37F8840066741A9BAACD6C9608066D14DEC541`
- Authenticode status: `NotSigned`

Generated binaries and installers are excluded from the source commit. The
installer and its checksum are intended to be attached to a GitHub release.

## Remaining limitations

- The installer is unsigned and may trigger Windows SmartScreen.
- This verification did not perform a fresh installer click-through on a clean
  Windows account.
- The product currently targets Windows x86_64; macOS and Linux packages were
  not built.
