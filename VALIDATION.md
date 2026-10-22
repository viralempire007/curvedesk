# CurveDesk 0.1 validation

## Completed in the development environment

- 26 Python tests: monetary multipliers, lot/depth conversion, physical balancing, long/short signs, fees, unknown margin, malformed input, stale/skewed/crossed books, single-leg movement, no duplicate/out-of-order recording, volume reset, missing intervals, indicator warmup, structural filters, frozen manual levels, one-open-position guard, alert deduplication, backup/restore, credentials exclusion and local HTTP security.
- Chromium UI integration: terminal chart/depth/ratio rendering, new basket creation, scenario economics, persistent draft/settings, unchanged margin edits across polling, page navigation and mobile viewport.
- Python compilation, JavaScript syntax and shell syntax checks.
- Bandit: no medium/high findings after replacing dynamic SQL table interpolation with fixed queries and using a fixed loopback HTTP health check.
- Pinned application dependency audit: no known vulnerabilities reported by pip-audit at validation time.
- Linux PyInstaller executable build and smoke test: bundled static assets, local server, per-user writable data directory and zero order calls.

## Not yet verified

- A live Dhan account, actual market-data entitlement, MCX depth quantity semantics and account-specific charges. These require the user's connection and confirmed specifications.
- Native Windows executable/installer and Ubuntu 22.04-targeted deb. GitHub Actions configuration is included; the workflow cannot run until the GitHub integration has write access to `viralempire007/curvedesk` and source is uploaded.
- Trading profitability, strategy calibration, complete historical tick/depth coverage and guaranteed execution. No such claims are made.

The local Linux executable is a build-environment smoke test, not proof of Ubuntu 22.04 binary compatibility. The configured Ubuntu packaging job builds on Ubuntu 22.04 for that compatibility target.
