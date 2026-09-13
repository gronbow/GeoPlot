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

Status: local implementation complete; remote exit evidence pending.

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

Gate 1 cannot exit until the branch is pushed, a pull request runs all five
checks successfully, and `main` requires those status checks. No remote branch,
pull request, or protection setting has been changed yet.

## Gate 2 — platform-neutral sidecar packaging

Status: not started.

## Gate 3 — native macOS build

Status: not started; requires a native macOS environment.

## Gate 4 — clean Windows install smoke test

Status: not started; requires a clean Windows VM or clean local account.

## Gates 5–6

Status: not started.
