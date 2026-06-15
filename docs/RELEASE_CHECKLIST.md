# Release Checklist

Use this checklist before considering the platform ready for a demo or handoff.

## Backend

- `python3 -m compileall src` passes.
- `/api/status` returns `connected=true` after gateway login.
- `/api/options?notional=10` returns option rows with QC fields.
- `/api/forwards?notional=10` returns parity or fallback source by maturity.
- `/api/surface?notional=10` returns `grid`, `ivPoints`, and diagnostics.
- `/api/runs/latest` returns the latest persisted artifact manifest.
- `/api/validation/latest` returns pass/warn/fail checks.
- `/api/orders/dry-run` accepts a valid ticket and confirms no broker order was sent.

## Frontend

- `npm run build` passes from `frontend/`.
- Data tab loads spot, history, futures, forwards, option chain, and surface preview.
- Risk tab prices options, builds a portfolio, runs scenarios, and backtests positions.
- Orders tab validates and dry-runs tickets while live routing stays disabled.
- Surface tab shows the 3D surface, smile, ATM term structure, diagnostics, and source fields.
- Ops tab shows latest run health, validation checks, model versions, and artifact paths.
- Layout remains readable at desktop and narrow widths.

## Data Quality

- Quote QC rejects crossed, empty, below-intrinsic, stale, or implausible rows.
- Surface eligibility is based on accepted QC rows.
- Forward source is visible by maturity.
- Calendar-arbitrage violations are counted and visible.
- Sparse slices are warned instead of silently plotted as clean surfaces.

## Safety

- Live order routing is disabled.
- No credentials are committed.
- Generated analytics artifacts remain under `data/analytics/` and are git-ignored.
