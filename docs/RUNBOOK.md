# Operations Runbook

This runbook keeps the platform diagnosable from gateway login to volatility surface publication.

## Start

1. Start and authenticate the IBKR Client Portal Gateway.
2. Start the API:

```bash
uvicorn src.api.server:app --reload --port 8000
```

3. Start the frontend:

```bash
cd frontend
npm run dev
```

4. Open `http://localhost:5173`.

## Health Checks

Use the Ops tab first.

| Check | Pass means | Action if warning/fail |
|-------|------------|------------------------|
| `run_freshness` | Latest stored analytics run is recent | Refresh Data or Surface; re-authenticate gateway if stale |
| `surface_accepted_points` | Enough IV points survived QC | Inspect option chain quote quality and market hours |
| `quote_reject_ratio` | Rejected quotes are under control | Check bid/ask availability, stale last-only rows, and entitlement |
| `calendar_arbitrage` | Total variance is monotonic across maturities | Review sparse expiries and rejected maturities |
| `surface_common_domain` | Display grid has enough common strikes | Use only overlapping strike domain or reduce displayed maturities |
| `surface_slice_quality` | Each maturity has enough points | Remove or flag sparse slices |
| `usable_quote_count` | The chain has enough usable quotes | Refresh during EUREX hours or authenticate market data |

## Empty Data

If the app shows no option or surface data:

1. Open `http://localhost:8000/api/status`.
2. If `connected=false`, log in again at the gateway URL from `configs/broker.yaml`.
3. Open `http://localhost:8000/api/options/diagnostics?notional=10`.
4. If rows are empty during weekends or holidays, this is expected for EUREX.
5. If rows exist but surface is empty, inspect `QC Reasons` in the options table.

## Surface Holes

The displayed surface must use the model grid returned by `/api/surface`, not a raw global strike matrix. Holes usually come from:

- no common strike domain across all selected maturities;
- missing bid/ask quotes;
- last-only rows rejected by quote QC;
- sparse far maturities;
- IV solver fallback rejected because residuals are too large.

The current model uses forward log-moneyness and then maps the display back to strikes on a common domain. If holes appear again, validate `surface_common_domain` and `surface_slice_quality` first.

## Order Safety

Real order routing is disabled by default.

- `/api/orders/validate` validates ticket shape and risk flags.
- `/api/orders/dry-run` creates an audit preview without sending anything.
- `/api/orders/submit` is intentionally blocked until routing is explicitly enabled in a future controlled release.

Do not enable live routing without adding account selection, permissions, size limits, cancel/replace audit logs, and a paper-trading acceptance test.
