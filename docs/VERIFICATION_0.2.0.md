# GeoPlot 0.2.0 engineering verification

Verification started: 2026-09-13

This document records evidence gate by gate. A gate is marked complete only
after its required checks pass. Results that require native macOS or a clean
Windows environment are not inferred from development-machine builds.

## Gate 0 — v0.1.0 protected baseline

Status: complete.

Baseline source and release:

- branch: `main`
- source commit: `af792d2267e0395a59227350a9c8b82b4557266a`
- tag at that commit: `v0.1.0`
- GitHub release: published, non-prerelease, with its original two assets
- product versions: npm `0.1.0`, Cargo `0.1.0`, Tauri `0.1.0`
- worktree before source changes: clean

The local clone initially did not contain the tag created when the GitHub
release was published. `git fetch origin --tags --prune` fetched the existing
remote tag without changing the worktree, release, tag target, or assets.

Local verification:

- Python scientific, safety, and desktop source suite: 336 passed, 7 skipped.
- Frontend: 22 passed.
- Frontend production build: passed.
- Rust/Tauri: 20 passed.
- npm production dependency audit: 0 known vulnerabilities.
- Frozen sidecar parity: 6 passed.

The Rust build reported the existing unused `BridgeOperation::Version` warning
and a Windows linker informational message. Neither was a test failure.

Available v0.1.0 frozen sidecar:

- file: `geoskills-desktop-bridge-x86_64-pc-windows-msvc.exe`
- size: 54,634,269 bytes
- SHA-256: `AE241BB2EF58843FD8E4A0544B37F8840066741A9BAACD6C9608066D14DEC541`

Scientific asset baseline SHA-256:

| Asset | SHA-256 |
| --- | --- |
| `classification/k2o-sio2-pt76-r89-original.json` | `B951F33F0D00A551D7FF16483BB3C8A9E5E4F0D8A9A80D8F9BE241837D0A4113` |
| `classification/tas-lemaitre-2002.json` | `1D1D2B637DE573C640703C9F3451432DF4355521FBCA0653461E415507064637` |
| `normalization/chondrite-sm89.json` | `598F458E05079DB0777F5424448C7A244F8D3FF7BE448E30AFFFCA8938392356` |
| `normalization/nmorb-sm89.json` | `0AF568F7B1861761D36AF5F6501A4E28018320EF714FDE19A1D6377E77042E10` |
| `normalization/primitive-mantle-modified-sm89.json` | `893DC3C42908A0B246B9201ECCB95202AA09B02FAC8A0C02B54EA70884F2C666` |
| `normalization/primitive-mantle-sm89.json` | `7858076F332B82F53ECFE972A1CB05B3C62AA5FA94A7BAD53E3DFA8284B62DF2` |

The `v0.1.0` tag and release assets were not modified or overwritten.

## Gate 1 — CI before features

Status: remote verification in progress.

Added `.github/workflows/ci.yml` with five independent jobs on pull requests and
pushes to `main`:

- Python scientific, safety, and desktop source tests;
- frontend tests, production build, and npm production audit;
- Windows Rust tests using a real PyInstaller-built reviewed sidecar;
- resolved scientific dependency audit with `pip-audit` installed only in CI;
- npm/Cargo/Tauri product-version consistency.

The workflow grants read-only repository-content permission and contains no
installer build, release publication, or release-asset upload step.

Added `scripts/check_versions.py` and fail-closed tests covering a matching
repository, divergent versions, and a missing version.

Local Gate 1 checks:

- product version check: passed at `0.1.0`;
- version consistency tests: 3 passed;
- complete Python suite after adding the tests: 339 passed, 7 skipped;
- CI YAML parsed with all five jobs present;
- `pip-audit 2.10.1 --strict` against the resolved scientific requirements:
  no known vulnerabilities found;
- scientific asset diff from `v0.1.0`: none.

The local pip-audit run emitted a Windows cache rename warning after the audit
tool attempted a cross-volume cache update. The audit itself completed
successfully and reported no known vulnerabilities.

Remote protection and pull-request evidence:

- branch: `codex/v0.2.0-engineering`;
- pull request: `#1`;
- `main` requires all five named jobs with strict up-to-date checks;
- administrator enforcement and conversation resolution are enabled;
- force pushes and branch deletion are disabled;
- the pull request was reported as blocked while required checks were not
  successful.

The first CI run identified one platform-coupling defect before any feature
work began: the frontend manifest directly required
`@tauri-apps/cli-win32-x64-msvc`, so the Ubuntu frontend job failed at
`npm ci` with `EBADPLATFORM`. The direct Windows-only dependency was removed;
the platform-neutral `@tauri-apps/cli` dependency remains responsible for
selecting its optional platform package. After that minimal correction, a
fresh local `npm ci`, all 22 frontend tests, the production build, and the npm
production dependency audit passed.

The second CI run showed that the lockfile entry retained from the former
direct dependency was still marked as mandatory even though the manifest no
longer required it directly. The entry is now explicitly optional, matching
its only remaining relationship under `@tauri-apps/cli`; this allows npm to
skip the Windows binary on non-Windows runners while retaining it on Windows.

Gate 1 cannot exit until the corrected pull-request revision runs all five
required checks successfully. The pull request must not be merged as part of
this gate.

## Gate 2 — platform-neutral sidecar packaging

Status: not started.

## Gate 3 — native macOS build

Status: not started; requires a native macOS environment.

## Gate 4 — clean Windows install smoke test

Status: not started; requires a clean Windows VM or clean local account.

## Gates 5–6

Status: not started.
