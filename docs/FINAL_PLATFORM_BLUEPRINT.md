# Final Platform Blueprint

This document is the target design for the volatility infrastructure platform.
It translates the industrial 16-step roadmap and the teacher notes into a
concrete product, architecture, UI, and delivery plan.

The final goal is not only a live dashboard. The final goal is a reproducible
risk and volatility platform:

- data is sourced from IBKR and kept auditable;
- quotes are normalized and quality-controlled before analytics;
- implied vol and volatility surfaces are built with diagnostics;
- portfolios can be priced, shocked, and backtested;
- order routing remains controlled, explicit, and disabled by default until the
  safety layer is complete;
- every result can be explained from raw input to final dashboard number.

---

## 1. Product Target

### 1.1 User promise

The platform must let a user answer five questions quickly:

1. Is the IBKR connection alive and is market data usable?
2. What does the Euro STOXX 50 market look like now: spot, futures, options,
   components, and volatility surface?
3. Which option quotes entered the IV and surface calculation, and why were the
   others rejected?
4. What is the risk of a chosen portfolio under spot, volatility, and time
   shocks?
5. Can a backtest or replay reproduce the same analytics from stored data?

### 1.2 Required tabs

The teacher notes require three core areas. The final app can keep a dedicated
Surface tab, but the product contract stays:

| Required area | Final screen | Purpose |
|---|---|---|
| Data | Data tab + Surface drilldown | Show IBKR data clearly, without strategy assumptions |
| Risk | Risk tab + Backtest subview | Select options/stocks, shock values, see PnL and Greeks |
| Orders | Orders tab | Preview and control orders; routing disabled until safe |

### 1.3 Non-goals for the final school-ready version

- No autonomous trading.
- No hidden data repair that cannot be audited.
- No production order routing without explicit enablement, dry-run preview,
  account checks, and kill switch.
- No separate historical-only analytics path that drifts from live analytics.

---

## 2. Current State

The repo already has a useful foundation:

- FastAPI backend in `src/api/server.py`.
- React dashboard in `frontend/`.
- IBKR Client Portal REST wrapper in `src/connectivity/session.py`.
- Live spot, history, futures, options, components.
- Delta ladder around `-30D` to `+30D` in 5D steps, with explicit ATM call and
  ATM put rows.
- Quote QC status and reason codes.
- Bracketed IV solver with diagnostics in `src/iv/solver.py`.
- Backend surface engine in `src/surfaces/engine.py` with raw IV points,
  common strike display grid, diagnostic grid, total variance, log-moneyness,
  and calendar checks.
- Basic pricer, Greeks, scenario grid, portfolio builder, and simple backtest.
- Orders UI preview, but routing is disabled.

Main missing pieces:

- durable storage for raw events, snapshots, IV points, surfaces, scenarios, and
  backtests;
- deterministic snapshot builder;
- forward curve engine;
- stronger QC with quote age, volume/open interest where available, parity
  residuals, and outlier logic;
- fitted surface model v2, ideally SVI or robust nonparametric smoothing;
- proper historical replay;
- validation reports;
- portfolio persistence and real position import;
- safe order workflow.

---

## 3. Architecture Target

### 3.1 High-level flow

```text
IBKR Gateway
    |
    v
Connectivity Client
    |
    v
Raw Collectors ---------------> Raw Event Store
    |                                  |
    v                                  v
Universe Discovery ------------> Instrument Master
    |
    v
Snapshot Builder --------------> Normalized Market Snapshots
    |
    v
Forward Engine ----------------> Forward Curve + Diagnostics
    |
    v
Quote QC ----------------------> Filtered Quotes + QC Reasons
    |
    v
IV Solver ---------------------> IV Points + Solver Diagnostics
    |
    v
Surface Engine ----------------> Surface Grid/Params + Fit Diagnostics
    |
    +---------> Pricing / Greeks / Risk / Scenarios / Backtest
                                      |
                                      v
                                  FastAPI
                                      |
                                      v
                                  React UI
```

### 3.2 Code module target

| Layer | Target modules | Responsibility |
|---|---|---|
| Config | `configs/`, `src/config/` | Broker, universe, calendars, thresholds, scenario versions |
| Connectivity | `src/connectivity/` | IBKR auth, requests, retry, health checks |
| Universe | `src/universe/` | Canonical instruments, contract resolution, expiry/strike discovery |
| Collection | `src/collectors/` | Raw quote/event collection, session summaries |
| Storage | `src/storage/` | Typed read/write APIs for raw and derived partitions |
| Snapshots | `src/snapshots/` | Deterministic market-state snapshots |
| Forwards | `src/forwards/` | Parity forward, carry diagnostics |
| QC | `src/qc/` | Named quote checks, reason codes, filter versions |
| IV | `src/iv/` | Scalar and batch IV inversion, diagnostics |
| Surfaces | `src/surfaces/` | Raw IV points, fitted slices, grids, no-arb checks |
| Pricing | `src/pricing/` | European/American pricing API, Greeks, unit conventions |
| Risk | `src/risk/` | Positions, aggregation, scenario PnL, reconciliation |
| Replay | `src/replay/` | Historical reconstruction using the same live code path |
| Orders | `src/orders/` | Preview, validation, dry-run, eventual routing |
| API | `src/api/` | Stable frontend contracts |
| Frontend | `frontend/src/` | Operational dashboard UI |

---

## 4. Storage Design

The roadmap requires replayability and auditability. The platform needs a
storage layer before backtests can be trusted.

### 4.1 Recommended local-first storage

For this project size:

- JSONL for raw broker proof/debug records.
- Parquet for tabular raw events and derived analytics.
- SQLite for metadata, jobs, portfolio definitions, and run manifests.

This keeps setup simple while matching the industrial design.

### 4.2 Directory layout

```text
data/
  raw/
    trade_date=YYYY-MM-DD/
      ibkr_events.parquet
      collector_sessions.jsonl
  reference/
    universe_YYYY-MM-DD.json
  snapshots/
    trade_date=YYYY-MM-DD/
      market_state.parquet
  analytics/
    trade_date=YYYY-MM-DD/
      forwards.parquet
      quote_qc.parquet
      iv_points.parquet
      surfaces.parquet
      surface_grids.parquet
      validation.parquet
  risk/
    trade_date=YYYY-MM-DD/
      positions.parquet
      scenarios.parquet
      backtests.parquet
  meta/
    platform.sqlite
```

### 4.3 Core tables

#### Raw event

| Column | Type | Notes |
|---|---|---|
| `run_id` | string | Collector session id |
| `receipt_ts` | timestamp | Local receipt timestamp |
| `exchange_ts` | timestamp/null | Broker/exchange timestamp when available |
| `instrument_key` | string | Internal canonical id |
| `broker_conid` | int/null | IBKR foreign key |
| `field_name` | string | bid, ask, last, iv, delta, volume, etc. |
| `field_value` | float/string/null | Raw value |
| `source` | string | IBKR endpoint/field |
| `raw_payload_ref` | string/null | Optional pointer to raw JSON |

#### Market snapshot

| Column | Type | Notes |
|---|---|---|
| `snapshot_id` | string | Deterministic run/snapshot id |
| `snapshot_ts` | timestamp | Snapshot time |
| `underlying_key` | string | Example: SX5E |
| `instrument_key` | string | Underlying, future, option, component |
| `bid` | float/null | Latest eligible bid |
| `ask` | float/null | Latest eligible ask |
| `last` | float/null | Latest last price |
| `mid` | float/null | Chosen mid |
| `reference_price` | float/null | Chosen analytics price |
| `reference_type` | string | mid, last, close, fallback |
| `quote_age_seconds` | float/null | Staleness check |
| `market_state_flags` | string/list | open, closed, stale, fallback |

#### Quote QC

| Column | Type | Notes |
|---|---|---|
| `qc_version` | string | Example: `quote-qc-v2` |
| `snapshot_id` | string | Input snapshot |
| `instrument_key` | string | Option contract |
| `status` | string | usable, caution, reject |
| `surface_eligible` | bool | Can enter surface |
| `reason_codes` | list/string | Exhaustive reason list |
| `spread_pct` | float/null | QC feature |
| `parity_residual` | float/null | Forward/QC feature |
| `quote_age_seconds` | float/null | QC feature |
| `volume` | float/null | If available |
| `open_interest` | float/null | If available |

#### IV point

| Column | Type | Notes |
|---|---|---|
| `iv_run_id` | string | Solver run |
| `instrument_key` | string | Option contract |
| `maturity` | string/date | Expiry |
| `strike` | float | Strike coordinate |
| `right` | string | C/P |
| `price_used` | float/null | Input to solver |
| `price_source` | string | mid, last, fallback |
| `forward` | float | Forward used |
| `log_moneyness` | float | log(K/F) |
| `maturity_years` | float | T |
| `implied_vol` | float/null | Decimal vol |
| `iv_percent` | float/null | Display vol |
| `delta` | float/null | Broker or model delta |
| `solver_status` | string | converged, not_solved, max_iter |
| `solver_reason` | string/null | Failure reason |
| `solver_residual` | float/null | Final price residual |
| `model_version` | string | Pricing/solver version |

#### Surface

| Column | Type | Notes |
|---|---|---|
| `surface_run_id` | string | Surface build id |
| `underlying_key` | string | SX5E |
| `surface_version` | string | v1 linear, v2 SVI |
| `coordinate_system` | string | strike/log-moneyness/total variance |
| `maturity` | string/date | Slice |
| `fit_method` | string | SVI, smoothing, linear |
| `params_json` | string/null | Fitted params |
| `rmse` | float/null | Fit error |
| `max_abs_error` | float/null | Fit error |
| `accepted_points` | int | Slice coverage |
| `rejected_points` | int | Slice rejects |
| `quality` | string | usable, sparse, failed |
| `warnings` | list/string | Fit warnings |

---

## 5. Analytics Design

### 5.1 Universe and instrument master

Final behavior:

- Discover Euro STOXX 50 index, options, futures, and components.
- Persist raw broker responses and normalized canonical records.
- Use internal keys, not only IBKR `conid`.
- Support future addition of SPX without rewriting the platform.

Acceptance:

- repeated discovery produces the same active universe under the same config;
- duplicate expiries and wrong multipliers are explicit warnings/errors;
- unresolved contracts fail loudly.

### 5.2 Market data ingestion

Final behavior:

- Collector writes append-only raw observations.
- API dashboard can still request on-demand snapshots, but analytics should be
  based on stored snapshots when possible.
- Collector summary reports data coverage and errors.

Acceptance:

- one live session can be replayed without calling IBKR again;
- reconnects and 401 events are visible in logs;
- weekend/off-hours empty data is labelled, not treated as a bug.

### 5.3 Snapshot builder

Final behavior:

- Build a coherent market state at a timestamp.
- Choose reference price with a deterministic priority:
  1. valid bid/ask mid;
  2. valid last if explicitly allowed;
  3. close/reference fallback with flag.
- Attach quote age and market state flags.

Acceptance:

- same raw events + same snapshot config = same snapshot rows;
- every fallback is visible in the UI and diagnostics.

### 5.4 Forward engine

Final behavior:

- For each maturity, compute call-put parity candidates near the money:

```text
F_i = K + exp(r * T) * (C - P)
```

- Weight candidates by quote quality.
- Reject outliers using robust statistics.
- Produce a forward curve and diagnostics.

Acceptance:

- forward diagnostics show candidate pairs and residuals;
- surface log-moneyness uses the forward, not raw spot;
- poor maturities are flagged.

### 5.5 Quote QC

The current QC is a good first version. The final version should be modular.

Target checks:

| Check | Reason code |
|---|---|
| Missing bid/ask | `missing_bid_ask` |
| Non-positive bid/ask | `non_positive_bid_ask` |
| Crossed market | `crossed_market` |
| Locked market | `locked_market` |
| Extreme spread | `extreme_spread` |
| Wide spread | `wide_spread` |
| Price below intrinsic | `below_intrinsic` |
| Missing IV and unsolvable price | `missing_iv_unsolved` |
| Stale quote | `stale_quote` |
| Last-only quote | `last_only` |
| Parity outlier | `parity_outlier` |
| Monotonicity issue | `monotonicity_warning` |
| Low volume/open interest | `low_liquidity` |

Acceptance:

- QC version is attached to every decision;
- every rejected row has at least one reason;
- raw rows and filtered rows are both available.

### 5.6 IV solver

Current v1 is a bracketed Black-Scholes bisection solver. Final additions:

- batch interface for a full option chain;
- unit tests with known reference prices;
- perturbation tests: small price move gives plausible IV move;
- optional Black-76 convention for index/futures-based options if selected;
- explicit model convention in every output.

Acceptance:

- liquid quotes converge;
- near-intrinsic failures are labelled;
- residuals and brackets are visible in API/UI.

### 5.7 Surface engine

Current v1:

- accepted raw IV points are separated from fitted/display grid;
- surface uses total variance;
- display grid uses common strike domain to avoid holes;
- diagnostic grid keeps outside-slice gaps visible.

Final v2:

- use forward-based log-moneyness coordinate;
- fit each maturity slice using SVI or robust smoothing;
- interpolate across maturities in total variance space;
- compute fit error per slice;
- compute calendar monotonicity diagnostics;
- expose raw points vs fitted slice overlay.

Surface UI should show:

- 3D fitted surface;
- raw IV points as markers;
- smile by maturity;
- ATM term structure;
- diagnostics table by maturity;
- warnings when a maturity is sparse or outside common strike domain.

Acceptance:

- no unexplained holes in the main display grid;
- diagnostic grid preserves all gaps;
- raw solved points are never discarded;
- repeated build with same inputs returns same grid.

### 5.8 Pricing and Greeks

Final behavior:

- Central pricing package, not dataframe-specific logic.
- European Black-Scholes / Black-76 consistent with IV solver.
- American pricer for single-name options if single-name options are traded.
- Greeks documented:
  - delta: per 1 index point;
  - gamma: convention clearly stated;
  - vega: per 1 vol point;
  - theta: per calendar day;
  - monetized Greeks use multiplier.

Acceptance:

- benchmark tests pass;
- sign conventions tested for calls and puts;
- dashboard labels match units.

### 5.9 Risk and scenarios

Final behavior:

- User builds or imports a portfolio of index options and components.
- Risk engine computes line-level price and Greeks.
- Aggregates by underlying, maturity, right, and custom book.
- Scenario engine supports:
  - spot shocks;
  - vol parallel shifts;
  - vol skew/term shocks;
  - time roll-down;
  - combined stress grid.

Acceptance:

- scenario definition is versioned;
- worst-case PnL and top contributors are shown;
- full repricing and local Greeks approximation are both displayed;
- residual/error between methods is visible.

### 5.10 Backtest and replay

The current backtest is a useful demo, but the final version must be replay-based.

Final behavior:

```text
historical raw events
    -> historical snapshots
    -> historical forwards
    -> historical QC
    -> historical IV points
    -> historical surfaces
    -> historical portfolio risk
    -> backtest PnL
```

Acceptance:

- one historical month can be reconstructed end to end;
- missing partitions produce partial-data flags;
- backtest never silently fills missing market data;
- live and replay outputs align for overlapping dates under the same code version.

### 5.11 Orders

Final behavior:

- Orders tab is safe by default.
- User can create a draft order from selected instruments.
- System validates:
  - account connected;
  - paper/live mode;
  - order size;
  - price bounds;
  - risk impact;
  - market open state.
- Preview is available before routing.
- Real routing requires explicit config flag and UI confirmation.

Acceptance:

- routing disabled by default;
- every outbound order has an audit record;
- cancellation and open-order state are visible;
- no order is sent by merely loading the dashboard.

---

## 6. API Contract Target

The frontend should call stable API resources. Backend internals can change as
long as these contracts remain stable.

### 6.1 System and bootstrap

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Auth, gateway, market data state |
| `GET /api/bootstrap` | Index, components, supported tenors |
| `GET /api/health/deep` | Connectivity, data entitlement, clock sync |
| `GET /api/runs/latest` | Latest collector/analytics run state |

### 6.2 Market data

| Endpoint | Purpose |
|---|---|
| `GET /api/spot` | Underlying spot snapshot |
| `GET /api/history` | Price history |
| `GET /api/futures` | Futures tenor curve |
| `GET /api/options` | Full option chain with QC/IV diagnostics |
| `GET /api/options/diagnostics` | Chain coverage and reason counts |
| `GET /api/components` | Index component spot table |
| `GET /api/component/{symbol}` | Component detail |

### 6.3 Analytics

| Endpoint | Purpose |
|---|---|
| `GET /api/forwards` | Forward curve and parity diagnostics |
| `GET /api/iv-points` | Accepted and rejected IV point table |
| `GET /api/surface` | Fitted/display surface + raw points |
| `GET /api/surface/diagnostics` | Surface quality and warnings |
| `GET /api/validation/latest` | Pass/warn/fail analytics report |

### 6.4 Risk

| Endpoint | Purpose |
|---|---|
| `GET /api/risk/pricer` | Scalar pricing check |
| `POST /api/risk/portfolio` | Price and Greek a portfolio |
| `POST /api/risk/scenarios` | Full scenario grid |
| `POST /api/risk/backtest` | Replay/backtest request |
| `GET /api/risk/reports/{id}` | Stored risk report |

### 6.5 Orders

| Endpoint | Purpose |
|---|---|
| `GET /api/orders/preview` | Account, positions, open orders, routing flag |
| `POST /api/orders/validate` | Validate draft order |
| `POST /api/orders/dry-run` | Broker preview or internal simulated order |
| `POST /api/orders/submit` | Disabled unless routing explicitly enabled |
| `POST /api/orders/cancel` | Cancel routed order |

---

## 7. Frontend Product Design

The final UI should be an operational cockpit, not a marketing page.
The visual direction should be inspired by Finary: premium dark finance UI,
clear wealth/risk metrics, compact left navigation, elegant time-series charts,
and calm allocation/performance panels. The app must not copy Finary branding,
logo, exact colors, or wording. The goal is to reuse the product feeling:
trustworthy, modern, data-rich, and easy to scan.

### 7.1 Finary-inspired design direction

What to borrow as inspiration:

- dark premium background with warm accent highlights;
- left navigation with few high-level sections;
- top-level portfolio/risk numbers immediately visible;
- large central performance or surface chart;
- compact period/filter controls close to the chart;
- allocation/performance style breakdowns for risk contributors;
- status and action buttons that feel calm, not noisy;
- strong hierarchy: one main story per screen, supporting details below.

What to adapt for this platform:

- replace "wealth tracking" with "volatility and risk cockpit";
- replace Finary's asset allocation with risk allocation:
  - by underlying;
  - by maturity;
  - by option right;
  - by Greek contribution;
  - by scenario loss contributor;
- replace simple portfolio performance with:
  - index spot performance;
  - volatility surface diagnostics;
  - PnL under shocks;
  - replay/backtest curve;
- keep the feeling premium, but make tables denser because this is an
  institutional analytics workflow.

Design tokens:

| Token | Target |
|---|---|
| Page background | near-black with subtle warm depth |
| Panel background | slightly lifted dark grey, not blue-heavy |
| Primary accent | warm gold/amber for active states and key values |
| Secondary accent | teal/green for live/usable/positive |
| Danger accent | muted red for rejects/loss/fail |
| Text primary | soft off-white |
| Text secondary | muted grey |
| Border | low-contrast warm grey |
| Radius | 8px max for panels/buttons |
| Shadows | very subtle, used for hierarchy only |

Suggested palette:

```text
--bg: #090907
--bg-elevated: #12110f
--panel: #181715
--panel-soft: #201f1b
--border: #34302a
--text: #f4f1ea
--muted: #9f9a90
--gold: #f2bd75
--gold-soft: #8a6335
--green: #56d68a
--teal: #61d0c3
--red: #ef6f61
--violet: #a99cff
```

Typography:

- use a clean sans-serif like Inter;
- avoid oversized hero typography inside the app;
- KPI values can be large, but tables and diagnostics must stay compact;
- use tabular numbers where possible for financial tables.

Chart style:

- line charts: warm gold for primary performance, muted grid lines;
- positive bars: green/teal;
- negative bars: muted red;
- surface chart: keep perceptual color scale, but avoid neon saturation;
- raw points: amber markers;
- diagnostic/fail points: red markers;
- no decorative gradients or unrelated illustrations.

### 7.2 Global layout

- Left sidebar for tabs.
- Topbar with current underlying, session state, and refresh control.
- Dense panels with 8px radius max.
- Tables optimized for scan/comparison.
- Charts full-width inside panels.
- Diagnostics visible near the chart they explain.
- No hidden magic: when data is missing, show the reason.

### 7.3 Visual language

| Element | Design rule |
|---|---|
| Background | Finary-like near-black, warm and premium |
| Accent | gold for primary active/selected, teal/green for live/usable, amber for caution, red for fail |
| Cards/panels | thin borders, compact spacing, no nested decorative cards |
| Tables | sticky header, dense rows, reason badges |
| Charts | transparent background, consistent color scale |
| Buttons | icon + label for actions; icon-only only for universal actions |
| Status | pass/warn/fail pills with explicit labels |

### 7.4 Data tab

Purpose: show broker data agnostically.

Sections:

1. Connection and market state summary.
2. Spot panel.
3. Price history.
4. Futures curve for `10d`, `1m`, `2m`, `3m`, `6m`, `9m`, `12m`,
   `18m`, `24m`, `36m`.
5. Options chain:
   - maturities;
   - ATM call and ATM put;
   - delta ladder from `-30D` to `+30D` by 5D;
   - bid, ask, last, mid, spread;
   - IV source/status/reason;
   - Greeks and monetized Greeks.
6. Surface preview.
7. Index components table.

Finary-inspired layout:

- first row: large spot/KPI block, session status, latest run health;
- second row: main history chart with period chips;
- third row: futures and options side by side if screen width allows;
- lower rows: surface preview and components.

### 7.5 Surface tab

Purpose: diagnose and trust the volatility surface.

Sections:

1. 3D fitted surface over common strike domain.
2. Raw IV points overlay.
3. Smile by maturity.
4. ATM term structure.
5. Maturity diagnostics:
   - accepted points;
   - rejected points;
   - fit method;
   - strike range;
   - RMSE;
   - calendar violations;
   - warnings.
6. Toggle:
   - display grid;
   - diagnostic grid;
   - raw points only.

Finary-inspired layout:

- top summary similar to a wealth dashboard, but for risk:
  - portfolio mark;
  - day PnL;
  - delta EUR;
  - vega EUR;
  - worst scenario loss;
- main panel: scenario/backtest performance chart;
- side panel: risk allocation donut or horizontal bars by maturity/Greek;
- lower panel: line-level positions and diagnostics.

### 7.6 Risk tab

Purpose: build a portfolio and understand PnL.

Sections:

1. Instrument selector:
   - options from chain;
   - index futures;
   - component stocks.
2. Position ticket:
   - side;
   - quantity;
   - multiplier;
   - price source;
   - add/remove.
3. Portfolio risk table:
   - price;
   - delta/gamma/vega/theta;
   - monetized sensitivities;
   - aggregation.
4. Scenario grid:
   - spot shock;
   - vol shock;
   - time shock;
   - full repricing PnL;
   - Greeks approximation;
   - error.
5. Backtest/replay:
   - date range;
   - data coverage;
   - PnL chart;
   - missing data flags.

### 7.7 Orders tab

Purpose: controlled order workflow.

Sections:

1. Account status.
2. Current positions.
3. Open orders.
4. Draft order ticket.
5. Risk impact preview.
6. Broker/internal dry-run response.
7. Submit button disabled unless routing is explicitly enabled.

Design rule:

- orders should look more restrained than the rest of the app;
- destructive or live-routing actions require confirmation and a clear visual
  state;
- paper/live environment must be visible at all times.

### 7.8 Operations/Diagnostics view

This can be a hidden advanced panel or a fifth tab later.

Sections:

1. Gateway state.
2. Latest collector session.
3. Latest analytics run.
4. QC pass/warn/fail.
5. Surface build status.
6. Validation report.
7. Logs and run ids.

---

## 8. Implementation Roadmap

### Phase 0 - Stabilize the current app

Goal: make the current React/FastAPI app reliable enough to extend.

Tasks:

- Keep Streamlit removed.
- Ensure `docs/START.md` matches the actual startup commands.
- Add smoke tests for API import and frontend build.
- Add small unit tests for `src/iv/solver.py` and `src/surfaces/engine.py`.
- Keep `/api/options/diagnostics` and `/api/surface/diagnostics` working.

Done when:

- `python3 -m compileall src` passes;
- frontend build passes;
- API starts cleanly;
- surface diagnostics explain empty data on weekends/off-hours.

### Phase 1 - Storage and schemas

Goal: make data replayable.

Tasks:

- Add `src/storage/` with typed writers/readers.
- Create Parquet/SQLite schema definitions.
- Write raw IBKR snapshots and normalized option/future/component tables.
- Write analytics outputs: QC, IV points, surface grid, validation report.
- Add run manifest with config versions.

Done when:

- one live data pull writes a complete run folder;
- `/api/runs/latest` exposes the latest stored run;
- dashboard can read latest stored analytics if IBKR is unavailable.

### Phase 2 - Snapshot and forward engine

Goal: stop using ad hoc live values as analytics inputs.

Tasks:

- Implement deterministic snapshot builder.
- Add quote age and market state flags.
- Build parity forward per maturity.
- Use forward in IV/surface log-moneyness.
- Expose `/api/forwards`.

Done when:

- every surface point has forward and log-moneyness from the forward engine;
- bad forward maturities are flagged.

### Phase 3 - QC/IV/surface v2

Goal: meet the roadmap's analytics quality requirements.

Tasks:

- Move QC checks to `src/qc/` as named checks.
- Add volume/open interest/quote age fields where IBKR provides them.
- Add parity residual and monotonicity checks.
- Add IV batch solver and tests.
- Implement SVI or robust smoothing surface v2.
- Persist fit parameters and diagnostics.

Done when:

- quote decisions are explainable by named checks;
- solver tests pass;
- surface fit error and warnings are visible by maturity;
- raw points vs fitted slices can be compared.

### Phase 4 - Risk, portfolio, and backtest

Goal: make the risk tab satisfy the teacher notes.

Tasks:

- Portfolio builder from live option chain/components.
- Persist hypothetical portfolios.
- Price line-level and aggregate Greeks.
- Add versioned scenario grids.
- Implement replay-based backtest from stored analytics.
- Show full repricing vs Greeks approximation.

Done when:

- user can select options/actions, shock them, and see PnL;
- backtest report includes data coverage and missing-data flags;
- one stored month can be replayed.

### Phase 5 - Validation and operations

Goal: make failures obvious.

Tasks:

- Build validation checks:
  - quote coverage;
  - stale ratios;
  - solver convergence rate;
  - surface common-domain size;
  - calendar total variance breaks;
  - scenario runtime.
- Store pass/warn/fail output.
- Add operations dashboard.
- Add structured logs with run ids.

Done when:

- latest run health is visible in the app;
- failed maturity/quote/run can be investigated in minutes.

### Phase 6 - Safe order workflow

Goal: complete the orders tab without creating trading risk.

Tasks:

- Implement order draft schema.
- Add server-side validation.
- Add dry-run/preview endpoint.
- Add account and position import.
- Keep real submit disabled by default.
- Add explicit config flag and confirmation path for real routing.

Done when:

- user can prepare and validate an order;
- no order can be submitted accidentally;
- every order action is logged.

### Phase 7 - Documentation and handover

Goal: make the project defendable and maintainable.

Tasks:

- Update README and START.
- Document schemas and API contracts.
- Add runbook:
  - start gateway;
  - diagnose 401;
  - diagnose empty options;
  - diagnose bad surface;
  - run replay;
  - read validation.
- Add release checklist.

Done when:

- a new user can install, run, read a QC report, and explain a bad surface
  without asking the original author.

---

## 9. Acceptance Matrix

| Requirement | Current state | Final acceptance |
|---|---|---|
| IBKR API instead of TWS | Implemented via Client Portal Gateway | Health checks and runbook complete |
| Data tab with spot | Implemented | Stored snapshot + fallback flags |
| Futures 10d to 3y | Mostly implemented | Tenor mapping persisted and diagnosed |
| Option chain with puts/calls | Implemented | Full QC, quote age, stored raw/filtered |
| Delta ladder | Implemented `-30D` to `+30D` by 5D | Configurable and documented |
| ATM call and ATM put | Implemented | Used in term structure diagnostics |
| IV and Greeks | Implemented v1 | Solver tests, conventions documented |
| Vol surface | Implemented backend v1 | Surface v2 with fit params/errors |
| Components | Implemented | Stored and replayable |
| Risk tab | Implemented demo | Portfolio persistence + scenario reports |
| Backtest | Implemented demo | Replay-based from stored analytics |
| Orders tab | Preview only | Validated dry-run, submit disabled by default |
| Auditability | Partial diagnostics | Raw to dashboard lineage complete |
| Validation | Partial diagnostics | Pass/warn/fail reports |
| Documentation | Basic | Runbooks + API/schema docs |

---

## 10. Engineering Standards

### 10.1 Version every decision that affects analytics

Examples:

- `quote_qc_version`
- `iv_solver_version`
- `surface_model_version`
- `scenario_set_version`
- `snapshot_builder_version`
- `config_hash`

### 10.2 Keep raw and fitted data separate

Never overwrite raw points with fitted values. Surface charts should be able to
show:

- raw accepted points;
- raw rejected points;
- fitted grid;
- diagnostic grid.

### 10.3 Prefer deterministic pure functions

The following modules should be pure where possible:

- snapshot builder;
- forward engine;
- QC checks;
- IV solver;
- surface engine;
- pricing and risk.

External calls should stay in connectivity/collectors/API boundary code.

### 10.4 Error states are product states

The app should have designed states for:

- IBKR offline;
- 401 expired session;
- weekend/off-hours;
- missing option chain;
- sparse maturity;
- solver failures;
- surface build warnings;
- replay partial data.

---

## 11. Testing Strategy

### 11.1 Unit tests

Must cover:

- Black-Scholes reference prices;
- IV solver reference inversions;
- below-intrinsic rejection;
- quote QC reason codes;
- maturity and log-moneyness calculations;
- surface common-domain handling;
- calendar total variance diagnostics;
- Greeks sign conventions.

### 11.2 Integration tests

Must cover:

- API starts without IBKR when mocked;
- `/api/options` with fixture payload;
- `/api/surface` with fixture option chain;
- portfolio scenario run with fixture positions;
- storage writer/reader round trip.

### 11.3 UI tests

Must cover:

- Data tab renders with fixture data;
- Surface tab renders no-hole display grid;
- Risk scenario table fits mobile/desktop;
- order submit remains disabled unless enabled by config.

### 11.4 Manual acceptance demo

Before final handover, demonstrate:

1. Start gateway and app.
2. Load live data.
3. Inspect option chain QC.
4. Explain a rejected option.
5. Show surface raw points vs fitted grid.
6. Build a small option portfolio.
7. Run scenario shocks.
8. Run a replay/backtest.
9. Show validation report.
10. Show orders preview disabled/safe.

---

## 12. Recommended Next Implementation Task

The most valuable next build step is Phase 1: storage and schemas.

Reason:

- it unlocks real replay/backtest;
- it makes diagnostics persistent;
- it reduces dependency on live IBKR availability;
- it satisfies the roadmap's auditability requirement;
- it gives the UI a stable latest-run source.

Minimum Phase 1 deliverable:

1. Add `src/storage/`.
2. Add `RunManifest` schema.
3. Write one option-chain analytics run to disk:
   - full option rows;
   - QC diagnostics;
   - IV points;
   - surface payload;
   - surface diagnostics.
4. Add `GET /api/runs/latest`.
5. Add a small Operations panel showing latest stored run.

After that, build the forward engine and QC v2.
