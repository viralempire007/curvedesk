# CurveDesk

A local Windows and Ubuntu workspace for MCX calendar spreads and quantity-aware ratio research. Connect your own Dhan market-data account inside the app. **Research and manual position tracking only: there are no broker order endpoints.**

## Install and open

Open [Actions → Test and build CurveDesk](https://github.com/viralempire007/curvedesk/actions/workflows/build.yml), choose the latest **successful** run, and download the artifact for your computer:

| Computer | Artifact / file | Open |
|---|---|---|
| Windows 10/11 x64 | `CurveDesk-Windows-x64` / `CurveDesk-Windows-x64-Setup.exe` | Run the installer; use the desktop shortcut |
| Ubuntu 22.04+ amd64 desktop | `CurveDesk-Ubuntu-amd64` / `CurveDesk-Ubuntu-amd64.deb` | Open with your software installer; launch CurveDesk from Applications |

GitHub artifacts download as a ZIP containing the installer and SHA256 checksum. A GitHub sign-in may be required. Installers bundle Python and dependencies; no Node.js, terminal, domain or VPS is required. Initial unsigned builds may display the operating system's publisher warning. Do not claim an installer is tested until its build job has succeeded. Native installer builds run on GitHub Windows/Ubuntu runners, not on the developer's other operating system.

CurveDesk opens `http://127.0.0.1:8876` in your browser. It is local-only. Closing the browser does not stop recording while the application process remains running. Exiting the application, signing out, suspending the computer or losing data connectivity interrupts observations. This version has no background auto-start service.

## First setup

1. Open **Connection & settings**. Enter your DhanHQ Client ID and generated access token, then **Save connection** and **Test profile**. Token connection is not an embedded Dhan password/OAuth login.
2. **Refresh catalogue**. Only active MCX `FUTCOM` contracts from Dhan are loaded. Labels include variant and expiry date. The WebSocket reconnects after catalogue/credential changes.
3. Confirm each variant's current **₹ per price point per lot**, **physical quantity**, **unit** and **broker depth quantity units per lot**. Built-in values are suggestions, not verified specifications. Quotation units and physical quantity units are different; do not assume displayed price multiplied by physical lot size is the right monetary multiplier.
4. Enter actual charge assumptions and research filters. The editable ₹1,200/crore initial value is not a verified Dhan tariff. This release models turnover-based brokerage plus other roundtrip charges per leg-lot, rather than an exhaustive statutory fee engine.
5. Open **Build a basket**, choose near/far expiries and lots, and save. Fresh paired quotes start the recorder. Indicators and structural research need their own completed local history; no fake backfill is generated.

A working Dhan trading account does not by itself prove Data API entitlement. Profile verification and live feed access are separate. HTTP 401/403, disconnects, missing books and stale quotes remain visible. Regular full packets provide five levels; this app does not promise MCX 20/200-level depth.

## One convention everywhere

`Spread reference = near price − far price`.

For baskets, each price is multiplied by that leg's own monetary multiplier and selected lots:

`Basket value ₹ = near price × near multiplier × near lots − far price × far multiplier × far lots`.

- **LONG** = buy near, sell far. Benefits when the weighted A−B value rises.
- **SHORT** = sell near, buy far. Benefits when it falls.
- Standard/mini variants can have different quotation units and physical exposure. Physical balancing does not guarantee risk neutrality.
- Ratios such as 1:2 or 2:3 leave outright commodity exposure unless actual physical quantities offset. They are not automatically better calendar hedges.

Monetary P&L is the sum of the two actual leg P&Ls minus fees. Scenario fill prices already include execution; bid–ask/slippage is not deducted twice. Unknown basket margin remains unknown. No margin offsets are fabricated.

## Included features

| Feature | Behaviour |
|---|---|
| Live Dhan feed | Read-only WebSocket full packets, reconnect/backoff, safe error messages, five-level depth, volume/OI and receipt/trade timestamps |
| Basket builder | Same underlying commodity, ordered expiries, independent 1–10,000 whole lots, up to 20 persistent baskets |
| Spread chart | Sampled weighted midpoint plus quantity-aware buy/sell quote lines; gaps are not joined |
| Executable estimates | Walk visible depth for each selected leg size; refuse insufficient quantity instead of extrapolating invisible liquidity |
| Movement | About-60-second weighted price change and hypothetical net marked movement using observed books |
| Indicators | Wilder ATR14, EMA20/slope and rolling Z-score on each basket's own completed sampled bars |
| Data integrity | Quote receipt ≤10 seconds and receipt skew ≤2 seconds; locked/crossed books rejected; cached duplicate observations rejected |
| Ratio analysis | User ratio, 1:1, 1:2, 2:3 and feasible quantity-balanced ratio; separate multipliers, physical exposure and immediate reversal costs |
| Scenario calculator | Explicit leg entry/exit fills, net costs, minimum-profit check, optional broker margin and return on margin |
| Structural research | Clearly labelled mean-reversion research candidate after ≥60 consecutive completed bars, reversal evidence, liquidity and configured cost/risk filters |
| Journal & alerts | Actual user-entered fills, one open position per basket, frozen candidate levels, indicative depth-weighted exit P&L, TP/SL and early-exit review alerts |
| History | Observed samples/bars, replay window JSON export, individual-contract historical candle export from Dhan |
| Backup | Consistent SQLite snapshot, checksum verification, credentials excluded, schema checks and pre-restore recovery backup |
| Desktop packaging | Windows per-user installer and Ubuntu deb; separate data directory survives normal app upgrades |

TP2 research target is the recent spread mean; TP1 is halfway along that opportunity. Stop is beyond the observed window extreme by observed ATR. These are hypotheses, not calibrated forecasts or a validated trading strategy. Estimated risk filters are not guaranteed maximum loss. Future execution costs, spread behaviour and liquidity can change.

Recorded levels freeze when **Trade taken** is recorded. The application never claims those levels were filled automatically. Early-exit review is triggered at half the adverse distance from the frozen quoted entry to its stop; it is a review rule, not an AI forecast. Alerts are deduplicated by trade and alert kind. Sound requires browser permission and an open browser. Closing a manual trade requires actual exit fills and total actual fees.

## Data limitations

- WebSocket receipt time is not exchange depth-update time. Two fresh receipts do not prove simultaneous exchange books or atomic fills. Last trade time is reported separately and may be old in a quiet contract.
- A quote update is not a trade. Every actual trade has a buyer and seller. A single-leg trade can move the spread legitimately. High volume with little net movement is not necessarily fake.
- Leg volume deltas are not confirmed exchange spread volume. This data cannot establish participant identity, wash trading, spoofing intent or a manipulation verdict.
- Bars are built from sampled paired midpoint observations, not from independent leg highs/lows. They are **not tick-complete exchange candles**. Same-bar missing observations can still reduce measured range.
- Missing completed intervals restart indicator warmup. Statistical deviations do not guarantee reversion; expiry, seasonality and supply/demand can shift the relationship.
- Raw observations are retained for at most **24 hours / 100,000 globally**; sampled bars for **90 days / 100,000 globally**. The earliest cap applies. Retention pruning runs approximately every minute. No unseen depth or offline price history is invented.
- Replay JSON contains the displayed window, up to 900 raw samples and 1,000 bars. Historical Dhan contract candles are a separate export, not substitute spread/depth history.
- No performance backtest, validated win probability, global-news agents, warehouse feeds, automatic broker margin API, cloud/mobile hosting or auto-execution is claimed in this release. Optional news/macro expansion must not replace the numerical measurement engine.

## Security and local data

| Platform | Default directory |
|---|---|
| Windows | `%LOCALAPPDATA%\CurveDesk` |
| Ubuntu | `$XDG_DATA_HOME/curvedesk`, or `~/.local/share/curvedesk` |

Dhan token is stored in a separate private local JSON file, not in SQLite backups, frontend responses, repository files or request logs. The token is **not encrypted at rest**; protect your OS account. App does not save the broker password. Local binding, Host/Origin checks, custom-header mutation protection and CSP reduce browser cross-site exposure. Do not expose port 8876 to a network or reverse proxy.

Override the data location with `CURVEDESK_DATA_DIR` and the port with `CURVEDESK_PORT` when needed. CurveDesk uses its own names, port, database and installer identity and does not migrate another app's data.

## Source setup (optional)

Python 3.11+ is required for source installs. Packaged installers do not require a separate Python installation.

- Windows: double-click `scripts/install-windows.cmd`; afterwards use `scripts/start-windows.cmd` or the created desktop shortcut.
- Ubuntu source development: `bash scripts/install-ubuntu.sh` (requires Python venv support). Afterwards use the Applications shortcut or `bash scripts/start-ubuntu.sh`.

Developer checks:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q curvedesk
node --check static/app.js
```

Optional browser test (isolated synthetic fixture, never a live broker account):

```sh
npm install --no-save playwright@1.56.1
npx playwright install chromium
node tests/browser.cjs
```

CI tests on Windows and Ubuntu, runs a Chromium UI check, then builds both native installers. Test fixtures are only imported by tests and are never started by the production launcher.

Official integration references: [Dhan full market feed](https://dhanhq.co/docs/v2/live-market-feed/), [instrument catalogue](https://dhanhq.co/docs/v2/instruments/), [historical data](https://dhanhq.co/docs/v2/historical-data/), [MCX](https://www.mcxindia.com/).
