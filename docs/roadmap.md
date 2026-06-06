# Part III — Sixteen-Step Implementation Roadmap
> Source: `industrial_roadmap_volatility_infrastructure_v4.pdf`, pages 10–21

Steps are ordered deliberately. Do not skip ahead — later stages depend on decisions made earlier.

---

## Step 1 — Access, Environments, and Security

**Objective:** Create a safe, repeatable foundation before writing any analytics code.

**Tasks:**
- Install Python and pin versions; produce a reproducible lock file
- Stand up IB Gateway (preferred over TWS for unattended operation)
- Configure a client ID convention so multiple services don't collide
- Build secret loading via environment variables or a secret manager — never hard-coded strings
- Create config files for exchanges, instruments, calendars, and QC thresholds
- Add basic health checks: API reachable, login valid, market-data entitlement present, clock sync within tolerance
- Decide and document where logs and artifacts will be written in each environment

**Outputs:** Reproducible Python environment, running IBKR session reachable from code, config package under version control, bootstrap script that proves end-to-end connectivity without placing orders.

**Acceptance criteria:** New machine can be provisioned from documentation; bootstrap script succeeds; secrets not in the repo; simple connectivity job can run from the scheduler without manual intervention.

**Junior note:** Start with the smallest useful smoke test. Resolve one contract, request one quote, write one JSON line to disk. Once that works, only then add complexity.

---

## Step 2 — Instrument Master and Universe Discovery

**Objective:** Build the canonical instrument master — the single source of truth for underlyings, option contracts, multipliers, currencies, exchanges, and expiries.

**Tasks:**
- Define the canonical schema for underlying and option instruments
- Implement contract-resolution helpers that map human-readable requests into broker contract IDs
- Use option-chain discovery APIs to obtain expiries, strikes, trading class, and multiplier
- Normalize expiries into a consistent date format and strikes into numeric values
- Persist both the raw broker response and the normalized canonical representation
- Add data-quality checks for duplicate contracts, impossible multipliers, or missing fields
- Version the discovered universe by date and config so any trading day can be reconstructed

**Outputs:** Canonical instrument master table + helper methods: `get_underlying()`, `get_option_chain()`, `resolve_contract()`, `load_active_universe()`.

**Acceptance criteria:** Same active option universe reproducible on repeated runs; duplicates removed deterministically; multiplier and currency always populated; unresolved contracts surface as explicit exceptions.

**Junior note:** Treat the broker's contract ID as an external foreign key, not your only identifier. Store raw contract payloads — future debugging depends on seeing exactly what the broker returned at discovery time.

---

## Step 3 — Market-Data Ingestion Layer

**Objective:** Capture raw underlying and option observations robustly — the raw layer is the evidentiary record. It must be append-only and loss-aware.

**Tasks:**
- Decide which subscriptions are persistent streaming vs. snapshots
- Create a collector for underlying quotes and one for options (or a unified collector with explicit partitioning)
- Normalize incoming ticks into a common event structure: `instrument_key`, `field_name`, `value`, `exchange_ts`, `receipt_ts`, `collector_ts`
- Persist every event to the raw layer with a session identifier
- Add reconnect logic with backoff and heartbeat monitoring
- Detect market-data pacing or entitlement failures and log them as structured events
- Build daily collector summaries: event counts, missing intervals, reconnect count, coverage ratios

**Outputs:** Append-only raw event store, collector service process, health metrics, session summary report.

**Acceptance criteria:** Collector runs an entire session without manual supervision; disconnects produce warnings and controlled recovery; synthetic kill-and-restart does not corrupt the raw store; one day of data can be replayed from disk without reaching back to the broker.

**Junior note:** Never compute analytics inside the collector callback. The callback should only normalize, stamp, and persist. Heavy logic inside callbacks is the fastest path to dropped events.

---

## Step 4 — Persistent Storage and Data Model

**Objective:** Define durable storage for immutable raw data and curated analytics, supporting both live incremental writes and historical backfills with identical schemas.

**Tasks:**
- Choose a metadata store for configuration, jobs, and reference entities
- Choose a columnar partitioned store for large raw and derived datasets
- Design partitioning by trade date, underlying, and data layer
- Create schema definitions for: raw events, normalized snapshots, forwards, IV points, surface parameters, model prices, Greeks, scenarios, positions, QC results
- Enforce schema evolution rules and backfill compatibility
- Decide retention policy for raw tick data, normalized snapshots, and derived analytics
- Add write-ahead validation so malformed records are rejected early

**Outputs:** Versioned schemas, migration scripts, partitioned datasets, documented data lineage from raw events through curated analytics.

**Acceptance criteria:** All required tables exist; partitioning supports efficient daily queries; replay and live writes land in identical schemas; deleting one derived partition does not require rewriting the raw layer.

**Junior note:** Use simple, explicit schemas. Avoid nested structures unless they materially reduce complexity. Do not mix timestamps in different time zones in the same field.

---

## Step 5 — Spot Builder and Market-State Snapshots

**Objective:** Transform raw ticks into coherent, time-aligned, quality-labeled market-state snapshots — the deterministic inputs to all downstream analytics.

**Tasks:**
- Define snapshot frequency or trigger (every N seconds, every material update, or on demand)
- Compute reference spot using mid-price when reliable, documented fallbacks otherwise
- Store bid, ask, last, spread %, and the chosen reference-type flag
- Join options into the same snapshot with the most recent eligible quote not older than a configurable age threshold
- Add market-state flags: open/closed, stale underlying, stale option, fallback spot
- Build snapshot completeness metrics per underlying and maturity

**Outputs:** Normalized market-state dataset keyed by `(timestamp, underlying, option contract)` with all fields required by pricing and surface layers.

**Acceptance criteria:** Same raw events + same snapshot parameters → identical rows on repeated runs. Stale-option logic visible in flags. Spot fallbacks labeled, not hidden.

**Junior note:** Keep the snapshot builder pure: raw events in, snapshots out. Do not call external services from inside it. That purity makes replay and unit testing easy.

---

## Step 6 — Forward and Implied Carry Engine

**Objective:** Compute a robust forward for each maturity and derive an implied carry/dividend curve. This is foundational — it determines the moneyness coordinate used by IV and surface modules.

**Tasks:**
- For each maturity, identify eligible call-put pairs near the money
- Compute call and put mids, then parity forward per strike: `F_i = K + e^(r·T) · (C - P)`
- Weight forward candidates by liquidity and quote quality
- Remove outliers using robust statistics (MAD or parity residual thresholds)
- Fit or smooth the forward term structure across maturities
- If a rate curve is available, derive implied carry/dividend yield and compare with expectations
- Persist both the chosen forward and all diagnostics

**Outputs:** Forward curve dataset by `(underlying, maturity)` + diagnostics listing candidate strikes, weights, residuals, quality labels.

**Acceptance criteria:** Forward stable across small perturbations in the eligible strike set; outlier pairs don't dominate; diagnostics explain why a maturity was flagged poor quality.

**Junior note:** Debug the forward engine first on a handful of liquid maturities before scaling. When a maturity fails, inspect the raw quotes — most forward errors originate in quote quality, not the formula.

---

## Step 7 — Quote Normalization and Quality Control

**Objective:** Establish a defensible process for deciding which option quotes may enter the solver and surface layers. Maximize economically meaningful, consistent, tradable quotes — not raw count.

**Tasks:**
- Compute quote-quality features: spread %, bid positivity, quote age, open interest, volume, monotonicity hints
- Mark quotes as `usable`, `caution`, or `reject`
- Detect crossed/locked markets, impossible prices vs. intrinsic value, stale last prices
- Apply robust outlier statistics to parity residuals or preliminary IVs
- Store the reason code for each rejected quote
- Keep both the full raw snapshot and the filtered snapshot so QC decisions are auditable

**Outputs:** Filtered quote set ready for inversion + QC table explaining every rejection or downgrade.

**Acceptance criteria:** Same quote consistently accepted or rejected under a fixed threshold version. QC reason codes exhaustive and understandable. Filtered chain retains enough points for a stable surface while removing obvious garbage.

**Junior note:** Do not implement QC as a monolithic if-statement. Break it into named checks and log each check separately — this makes threshold tuning and postmortem analysis far easier.

---

## Step 8 — Implied-Volatility Inversion Engine

**Objective:** Convert filtered option prices into implied volatilities using robust numerical methods, with full diagnostics on every solve.

**Tasks:**
- Implement European inversion using a **bracketed root solver** (not pure Newton — can diverge near intrinsic)
- For American options, either invert through the chosen American pricer or compute proxy IV under a documented convention
- Use intrinsic-value and no-arbitrage bounds to detect unsolvable inputs before entering the solver
- Record: convergence status, iteration count, final residual, lower/upper bracket, pricing model used
- Expose fallback behavior for short-dated or near-intrinsic cases
- Build a batch interface that can solve an entire chain efficiently

**Outputs:** Table of IV points with coordinates: `strike`, `log_moneyness`, `maturity`, `delta` (if available), and extensive diagnostics.

**Acceptance criteria:** Most liquid quotes converge cleanly; pathological cases explicitly labeled; solver passes reference examples; finite perturbations in input price produce plausible IV changes.

**Junior note:** Write the scalar solver first, then the vectorized batch wrapper. Keep the scalar path readable and test it thoroughly — most production bugs are easiest to find before optimization layers are added.

---

## Step 9 — Surface Engine and Parameter Storage

**Objective:** Build volatility surfaces by maturity and across maturities, keeping raw solved points and the final fitted representation separate.

**Tasks:**
- Group IV points by maturity
- Transform into log-moneyness and total variance space: `w = σ² · T`
- Fit the chosen parameterization slice by slice (SVI recommended) or apply nonparametric smoothing
- Interpolate across maturities in variance space
- Compute goodness-of-fit metrics and no-arbitrage diagnostics (calendar monotonicity check)
- Save both fitted parameters and reconstructed grid values
- Store rejected points and fit warnings so operators can see whether a smooth surface was built on sparse input

**Outputs:** Surface parameter tables, regularized surface grid, fit diagnostics, quality flags by maturity and underlying.

**Acceptance criteria:** Fitted surface reproduces accepted market points within tolerance; diagnostics reveal sparse/poor-quality fits; repeated runs under same inputs return same parameters; at least one plotting utility to visualize raw points vs. fitted slices.

**Junior note:** Never discard the raw solved points after the fit. Operators must be able to compare the fitted surface with the exact points that entered calibration — essential for debugging suspicious Greeks or scenarios later.

---

## Step 10 — Pricing Engine

**Objective:** Provide reusable pricing services for European and American options. Centralizing this logic prevents drift across notebooks and services.

**Tasks:**
- Implement a **European pricer** consistent with the inversion engine (Black-Scholes / Black-76)
- Implement an **American pricer** suitable for single-name use (lattice or Bjerksund-Stensland)
- Expose first-order and second-order Greeks, analytically when available or numerically with documented finite-difference settings
- Create a clean Python API with typed input/output objects
- Add benchmark tests and performance tests
- Document unit conventions rigorously (delta w.r.t. spot, vega per vol point, theta per calendar day)

**Outputs:** Pricing package with scalar and vectorized interfaces, docstrings, examples, and benchmark fixtures.

**Acceptance criteria:** Reference cases match expected values; European and American engines agree in regimes where they should; unit tests cover sign conventions and limiting cases.

**Junior note:** Avoid embedding pricing logic in dataframes or notebooks. Keep the pricer a clean library with tests — the clearer this boundary, the safer later refactors.

---

## Step 11 — Greeks and Per-Position Risk Analytics

**Objective:** Turn the pricing layer into a per-contract and per-position risk service — the canonical risk snapshot used everywhere else, including scenario analysis and dashboards.

**Tasks:**
- Define the sensitivity set required at instrument level and portfolio level
- Pull in the latest positions (or hypothetical positions) from the source of record
- Join positions to analytics snapshots; compute per-line price, Greeks, and monetized sensitivities
- Aggregate by instrument, maturity, underlying, and any desk-defined grouping keys
- Compute reconciliation checks against broker-returned Greeks if available
- Publish both line-level and aggregate outputs

**Key formulas:**
- `dollar_gamma = Γ · S² · multiplier`
- `dollar_vega = ν · multiplier`
- `local_PnL ≈ Δ·dS + ½·Γ·dS² + ν·dσ + θ·dt`

**Outputs:** Position-level risk tables, aggregated risk tables, reconciliation reports.

**Acceptance criteria:** Same positions on same analytics snapshot always produce same aggregate risk; dollar gamma and dollar vega conventions documented and stable; reconciliation discrepancies beyond threshold surfaced automatically.

**Junior note:** Store both contract-level and aggregate outputs. If a total Greek looks wrong and the line-level breakdown is missing, the system becomes opaque immediately.

---

## Step 12 — Scenario Engine and Margin-Style Diagnostics

**Objective:** Build a scenario framework approximating worst-case losses under configured spot, volatility, and time shocks. Generic risk control — no strategy logic.

**Tasks:**
- Define versioned scenario grids: spot up/down moves, vol shifts, curve rotations, time roll-down
- Reprice the full portfolio under every scenario
- Attribute PnL by line, underlying, and scenario family
- Compute worst-case loss, top contributors, and pathwise diagnostics
- Support both **full repricing** (source of truth) and **local Greeks-based approximations** (speed)
- Persist the exact scenario set used for every report

**Outputs:** Scenario result tables, worst-case summaries, margin-style approximation reports.

**Acceptance criteria:** Report can be regenerated exactly given positions, analytics snapshot, and scenario version. Worst-case contributors explainable. Repricing and Greeks approximations agree within documented limits for small shocks.

**Junior note:** Version the scenario grid — do not leave it as a mutable notebook cell. The scenario definition is part of the data lineage and must be queryable alongside the output.

---

## Step 13 — Historical Reconstruction and Replay

**Objective:** Enable the system to reconstruct historical analytics from stored raw data using the same code path as live analytics. This turns the infrastructure into a real research and audit platform.

**Tasks:**
- Define how a historical day is replayed: raw events → snapshots → forwards + surfaces → risk
- Ensure all derived jobs can run in batch mode over a date range
- Detect missing raw partitions and create partial-data flags
- Store restated outputs in versioned partitions so newer code versions don't silently overwrite older analytics
- Compare replay outputs with live outputs for overlapping periods

**Outputs:** Replay scripts, backfill jobs, replay QA reports, historical archive of derived analytics.

**Acceptance criteria:** At least one historical month can be reconstructed end to end. Replay and live outputs align on overlapping dates with the same code version. Missing data flagged, not masked by interpolation.

**Junior note:** The replay code path must call the same libraries as live processing. Resist the temptation to fork a separate "historical only" implementation — dual code paths always drift.

---

## Step 14 — Validation Framework and Anomaly Detection

**Objective:** Create automated controls that determine whether each daily analytics run is trustworthy. Validation is a product, not a last-minute dashboard.

**Tasks:**
- Define validation checks for: coverage, stale-data rates, forward stability, solver convergence, surface smoothness, no-arbitrage diagnostics, reconciliation deltas
- Build daily reports summarizing pass/warn/fail outcomes
- Add anomaly detection against rolling baselines for key metrics (quote counts, forward residuals, fit errors, scenario losses)
- Write every failed record to a triage table with enough context to investigate
- Define escalation thresholds and notification policy

**Outputs:** QC reports, anomaly tables, validation dashboard, triage views for failed instruments or maturities.

**Acceptance criteria:** A daily operator can identify failing underlyings or maturities within minutes. Every failed validation has a reason code and supporting context. Historical trends of QC metrics visible for regression monitoring.

**Junior note:** A good validation framework is specific. Operators need to know which maturity failed, which quote count collapsed, which solver residual blew out — and where to look next.

---

## Step 15 — Orchestration, Logging, and Observability

**Objective:** Turn the build into an operable system with schedules, retries, metrics, and alerting. A correct algorithm that cannot be monitored is not production-ready.

**Tasks:**
- Define jobs for: universe refresh, live collection, incremental analytics, end-of-day reconciliation, replay, QC
- Add structured logging with correlation IDs linking collector sessions to analytics jobs
- Expose metrics: event rates, stale ratios, forward failures, solver failure counts, scenario run times
- Create alerts for: collector death, missing partitions, elevated failure rates, QC fails
- Implement restart procedures that do not duplicate or corrupt records
- Build simple dashboards answering: Is data flowing? Are surfaces building? Are QC checks passing? Are scenario reports current?

**Outputs:** Scheduled jobs, logs, dashboards, alert routes.

**Acceptance criteria:** Simulated failure of collector or analytics service detected within a documented interval. Restarting a failed job does not silently duplicate outputs. Operators can identify the last healthy run instantly.

**Junior note:** Prefer fewer well-labeled metrics over many opaque ones.

---

## Step 16 — Production Hardening, Documentation, and Handover

**Objective:** Finish the infrastructure as a maintainable product so another person can operate, support, and extend the platform without reverse-engineering it.

**Tasks:**
- Freeze interface contracts and publish them in documentation
- Create onboarding notes, runbooks, deployment instructions, and a release checklist
- Record known limitations and future enhancements
- Add ownership and support expectations
- Define change-management rules for schema changes, threshold changes, and model changes
- Conduct a handover walkthrough: demonstrate from environment setup through QC interpretation

**Outputs:** Maintained documentation set, release checklist, SOPs, support model.

**Acceptance criteria:** A new engineer can set up the environment, run a connectivity smoke test, trigger a replay, read the QC report, and explain where to investigate a failed surface build — without any support from the original author.

**Junior note:** Documentation is not an afterthought. Treat it like code. Every module should have a README, every public function should have docstrings, and every recurring operational procedure should exist as a runbook.
