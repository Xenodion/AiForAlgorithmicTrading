# AI for Algorithmic Trading — Volatility Infrastructure

React dashboard and FastAPI backend connected live to the IBKR Client Portal REST API.
Displays real-time data, Greeks, scenario engine, backtests, and vol surface analytics for the Euro STOXX 50.

---

## Prerequisites

| Tool | Notes |
|------|-------|
| Python 3.11+ | [python.org](https://www.python.org/downloads/) |
| Java 21 | Required to run the IBKR Gateway. Set `JAVA_HOME` if needed |
| IBKR Client Portal Gateway | Download from IBKR, extract to a local folder (e.g. `C:\ibkr-gateway`) |
| IBKR paper trading account | Free to create at interactivebrokers.com |

---

## First-time setup

```powershell
# 1. Clone the repo and enter the folder
git clone <repo-url>
cd AIForAlgorithmicTrading

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate it
.venv\Scripts\Activate.ps1

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Install frontend dependencies
cd frontend
npm install
```

> On Windows you may need to run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` once to allow .ps1 activation.

---

## Configure the broker connection

Copy the example config and fill in your gateway URL:

```
configs/broker.yaml
```

Default content (should already work if gateway runs on localhost):

```yaml
connection:
  base_url: "https://localhost:5050/v1/api"
  verify_ssl: false
  timeout_seconds: 10
```

---

## Every time you want to run the app

### Step 1 — Start the IBKR Gateway

Open a **CMD** window (not PowerShell) and run:

```cmd
cd C:\ibkr-gateway
bin\run.bat root\conf.yaml
```

Keep this window open. Wait until you see:
```
Open https://localhost:5050 to login
```

> If you get `'java' is not recognized`, set your Java path in `run.bat`:
> ```bat
> set JAVA_HOME=C:\path\to\your\jdk
> set PATH=%JAVA_HOME%\bin;%PATH%
> ```

### Step 2 — Log in to the gateway

Open your browser → **https://localhost:5050**

- Accept the SSL warning (Advanced → Proceed)
- Log in with your IBKR credentials
- Select **Paper Trading**
- Wait for "Client login succeeds"

### Step 3 — (Optional) Run the health-check / bootstrap script

Verifies the whole connectivity chain end-to-end without placing any orders —
auth, accounts, index resolution, spot snapshot, and market-data entitlement.
Useful after a fresh setup or when something feels off.

```powershell
.venv\Scripts\python scripts\bootstrap.py
```

Expected output: `Auth OK`, your account ID, the resolved Euro STOXX 50 conid,
a spot snapshot with `last`/`close`/`chg`, and a market-data availability code.

> `availability=D` (Delayed) is **normal** for paper trading accounts — `R`
> means real-time. A proof record is written to `data/raw/`.

### Step 4 — Launch the API

```powershell
uvicorn src.api.server:app --reload --port 8000
```

### Step 5 — Launch the React frontend

```powershell
cd frontend
npm install
npm run dev
```

### Step 6 — Open the dashboard

Open **http://localhost:5173**.

---

## Project structure

```
configs/
  broker.yaml           # IBKR gateway URL and connection settings
  universe.yaml         # Monitored underlyings, option/futures tenors, strike selection params
frontend/
  src/
    App.jsx             # React dashboard — all 5 tabs
    styles.css          # Dark-theme component styles
scripts/
  bootstrap.py          # End-to-end connectivity smoke test (no orders placed)
src/
  api/
    server.py           # FastAPI backend — all REST endpoints, TTL cache, startup warmup
  analytics/
    pricer.py           # Black-Scholes pricer, analytic Greeks, scenario and P&L functions
  connectivity/
    session.py          # IBKRClient — REST wrapper, auth, keepalive, positions, orders
  data/
    fetcher.py          # Spot, history, futures curve, options chain, components
  forwards/
    engine.py           # Put-call parity forward engine with diagnostics and fallback
  iv/
    solver.py           # Bracketed IV inversion solver with per-contract diagnostics
  orders/
    safety.py           # Order validation, dry-run, submit-blocked — routing disabled
  qc/
    options.py          # Named option quote quality checks (spread, intrinsic, staleness)
  risk/
    portfolio.py        # Per-position pricing, Greek aggregation, scenario grid, backtest
  snapshots/
    builder.py          # Market-state snapshot builder — labels reference price per row
  storage/
    artifacts.py        # JSON artifact store — persists each analytics run to disk
    strategies.py       # Parquet-backed strategy store — save/load/delete portfolios
  surfaces/
    engine.py           # IV surface builder — common strike grid, calendar checks, diagnostics
  universe/
    discovery.py        # IBKR contract resolution — conids, expiries, strikes, multipliers
    dq_checks.py        # Universe data-quality checks
    repository.py       # Load and query the persisted instrument master
    schema.py           # TypedDicts for underlying and option instrument records
  validation/
    checks.py           # Pass/warn/fail validation report from the latest analytics run
data/
  analytics/            # Persisted analytics runs (option rows, surface, diagnostics, manifest)
  raw/                  # Bootstrap proof records and session logs
docs/
  roadmap.md            # 16-step implementation roadmap (source: industrial_roadmap_v4.pdf)
  FINAL_PLATFORM_BLUEPRINT.md  # Architecture, product contract, delivery plan
  RUNBOOK.md            # Operations diagnosis guide
  RELEASE_CHECKLIST.md  # Demo and handoff checklist
requirements.txt
```

---

## Dashboard tabs

### Tab 1 — Data
*Roadmap steps covered: 2, 5, 6, 7, 8, 9*

The entry point for all live market data. Connects to the IBKR Client Portal and displays:

- **Spot and history** — live Euro STOXX 50 price with 3-year weekly history chart.
- **Futures curve** — front-to-back futures prices by tenor, pulled from IBKR. Demonstrates how the market prices forward delivery.
- **Options chain** — full chain across 6 maturities covering the ±30 delta range in 5-delta steps, with both a put and a call at ATM. Each row carries Bid/Ask/Last, IBKR live IV (field 7636), analytic Greeks (Δ, Γ, ν, θ), root-time vega (ν/√T), and a QC status label (tight / wide / last-only / reject). Quote QC is defined in `src/qc/options.py` and runs on every row before any analytics are computed.
- **Forward curve** — per-maturity forwards computed via put-call parity on the live quotes (`src/forwards/engine.py`). When no usable put-call pair exists, the engine falls back to a documented spot/rate proxy and labels the source.
- **IV surface preview** — a compact 3D surface built from QC-accepted rows using a common strike domain across all maturities (no null cells). IV is solved using a bracketed root solver (`src/iv/solver.py`) with Black-Scholes as a fallback.
- **Index components** — live spot for all 50 Euro STOXX 50 constituents.

---

### Tab 2 — Risk
*Roadmap steps covered: 10, 11, 12*

A complete hypothetical portfolio risk workbench. All positions are user-defined — nothing is pulled from a broker account.

- **Black-Scholes pricer** — single-option pricing for calls and puts. Shows price, Δ, Γ, ν, θ for a chosen spot/strike/maturity/vol/rate. Implemented in `src/analytics/pricer.py` using the standard closed-form solution with analytic Greeks.
- **Scenario grid** — spot × vol shock matrix using full repricing (not a Greeks approximation). Compares full P&L vs. Greeks approximation and shows the error, so the hedging quality of the first- and second-order expansion can be assessed directly.
- **Portfolio builder** — add any mix of calls, puts, or index (delta-1) positions. Each position is valued at current spot. The table shows per-position price, Qty (+ for long, − for short), and monetised Greeks. Aggregates total € Delta, € Gamma, € Vega, and € Theta across the book.
- **Local P&L approximation** — slider-based P&L estimate for the full portfolio under spot move, vol move, and time decay. Uses the Taylor expansion: ΔP ≈ Δ·dS + ½Γ·dS² + ν·dσ + θ·dt.
- **Portfolio backtest** — replays the portfolio P&L over a historical lookback using realized-vol scaling. Not a surface replay — it is a proxy-based P&L attribution that separates delta, gamma, vega, and theta contributions over time.
- **Saved strategies** — save the current portfolio to disk (Parquet) with a name and description. Saved strategies display full position details and can be reloaded to auto-run the backtest.

---

### Tab 3 — Orders
*Roadmap coverage: order safety layer (blueprint section 1.2)*

Demonstrates the order workflow with live routing permanently disabled. The goal is to show a controlled, auditable order process without any risk of accidental execution.

- **Account overview** — shows account type (Paper), routing status (Disabled), open order count, and safety version. Real account balances are not fetched because routing is off.
- **Order ticket** — entry form for underlying, side (BUY / SELL), quantity, order type (LIMIT / MARKET), and limit price. Pre-populated with the live index symbol.
- **Validate** — runs the ticket through `src/orders/safety.py`. Checks for missing fields, invalid side/type, non-positive quantity, large-qty warnings, and missing limit price. Returns a structured result with error codes and warnings.
- **Dry-run** — simulates a full submission flow. Generates a unique dry-run ID and timestamp, runs validation, and returns the normalised ticket showing exactly what would be sent to the broker. No IBKR API call is made. Routing is blocked at the code level (`ROUTING_ENABLED = False` in `safety.py`).
- **Open orders / Positions** — fetches live data from IBKR (`/iserver/account/orders` and `/portfolio/{accountId}/positions/0`). On a paper account with no trades placed, both panels show contextual empty states.

---

### Tab 4 — Surface
*Roadmap steps covered: 7, 8, 9*

A dedicated analytics view for the implied volatility surface.

- **3D surface** — Plotly mesh built from the common strike domain (strikes present across all maturities). Uses IBKR live IV (field 7636) where available, falling back to the bracketed BS solver. Observed quote points are overlaid as a scatter. Calendar-arbitrage violations (total variance decreasing across maturities at the same strike) are detected and counted.
- **Volatility smile** — per-maturity IV smile selectable from a dropdown. Strike on x-axis, IV on y-axis.
- **ATM term structure** — IV at the nearest-to-spot strike plotted against maturity. Averages the put and call IV at the ATM strike to reduce noise.
- **Surface health strip** — key QC metrics at a glance: accepted points, rejected rows, maturity count, common strikes in the display grid, calendar-arbitrage violations.
- **Surface statistics table** — full row-level detail: QC status, QC reason codes, IV source (IBKR live vs. BS fallback), IV convergence status, forward used, log-moneyness, and total variance (σ²·T).

---

### Tab 5 — Operations (Ops)
*Roadmap steps covered: 4, 5, 13, 14, 15*

An operational readiness dashboard. Gives a teacher or operator an immediate answer to "is the system producing trustworthy analytics?"

- **Run health** — metadata for the latest persisted analytics run: run ID, trade date, Quote QC version, surface model version, order safety version, and the file path of the run directory. Every surface build writes a full artifact set to `data/analytics/trade_date=<date>/<run_id>/` — the manifest, option rows, surface, and diagnostics are all stored as JSON.
- **Validation checks** — seven named pass/warn/fail checks on the latest run: run freshness (< 120 min), accepted IV points (≥ 30 = pass), quote reject ratio (≤ 40% = pass), calendar-arbitrage violations (0 = pass), common strike domain (≥ 5 strikes = pass), sparse maturity slices, and usable quote count. Implemented in `src/validation/checks.py`.
- **Market-state snapshot** — output of `src/snapshots/builder.py`. Shows how many option rows used `mid`, `last`, or had a `missing` reference price. Demonstrates Step 5 of the roadmap: each row is labelled with the reference price type before being passed to the pricing layer.
- **Artifacts** — table of file paths for all outputs of the latest run. Demonstrates Step 4 (persistent storage) and Step 13 (auditable analytics record): every run can be reconstructed from its stored JSON files without re-querying IBKR.

---

## Important notes

- **Options and futures are only available on weekdays** — EUREX is closed on weekends, so those sections will be empty Saturday/Sunday. This is expected.
- The session stays alive automatically via a background keepalive thread (tickles every 55 seconds).
- If you get a 401 error at any point, go back to Step 2 and log in again.
- Never commit `.env` or any file containing credentials.
