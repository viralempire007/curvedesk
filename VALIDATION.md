# CurveDesk 0.1 validation

## Completed in the development environment

- 26 Python tests: monetary multipliers, lot/depth conversion, physical balancing, long/short signs, fees, unknown margin, malformed input, stale/skewed/crossed books, single-leg movement, no duplicate/out-of-order recording, volume reset, missing intervals, indicator warmup, structural filters, frozen manual levels, one-open-position guard, alert deduplication, backup/restore, credentials exclusion and local HTTP security.
- Chromium UI integration: terminal chart/depth/ratio rendering, new basket creation, scenario economics, persistent draft/settings, unchanged margin edits across polling, page navigation and mobile viewport.
- Python compilation, JavaScript syntax and shell syntax checks.
- Bandit: no medium/high findings after replacing dynamic SQL table interpolation with fixed queries and using a fixed loopback HTTP health check.
- Pinned application dependency audit: no known vulnerabilities reported by pip-audit at validation time.
- Linux PyInstaller executable build and smoke test: bundled static assets, local server, per-user writable data directory and zero order calls.

## Verified on GitHub Actions — 22 October 2026

[Successful native build and verification run](https://github.com/viralempire007/curvedesk/actions/runs/39730991464), source commit `882eb78f91ffbf54ee748d7242540ae46a14b6dc`:

- 26 tests passed on Windows Server 2025 and Ubuntu 22.04 runners.
- Chromium UI integration passed on GitHub's Ubuntu runner.
- Packaged Windows executable startup smoke passed, including bundled assets and private data directory.
- Packaged Ubuntu executable startup smoke passed on Ubuntu 22.04.
- Windows x64 setup installer and Ubuntu amd64 deb built successfully; artifacts include SHA256 checksums.
- Installation through a human-operated desktop wizard and live Dhan account connection remain user-environment checks.

## Requires account/environment validation

- A live Dhan account, actual market-data entitlement, MCX depth quantity semantics and account-specific charges. These require the user's connection and confirmed specifications.
- Trading profitability, strategy calibration, complete historical tick/depth coverage and guaranteed execution. No such claims are made.

The local Linux build was supplementary. The downloadable Ubuntu package was built and its executable smoke-tested on Ubuntu 22.04. Artifacts are available on the successful run linked above; GitHub retention applies.
