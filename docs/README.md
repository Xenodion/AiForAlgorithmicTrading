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
  broker.yaml           # IBKR gateway URL
  universe.yaml         # Monitored underlyings, option/futures tenors
frontend/
  src/                  # React dashboard
scripts/
  bootstrap.py          # Health-check / connectivity smoke test
src/
  api/
    server.py           # FastAPI backend for the React app
  connectivity/
    session.py          # IBKRClient — REST wrapper + auth
  data/
    fetcher.py          # Spot, futures, options, history, components
  analytics/
    pricer.py           # Black-Scholes pricer + Greeks + scenario grid
data/
  raw/                  # Bootstrap proof records (JSON)
docs/
  START.md              # Short startup cheatsheet
  roadmap.md            # 16-step project roadmap
  FINAL_PLATFORM_BLUEPRINT.md # Final architecture, product, and Finary-inspired UI target
  RUNBOOK.md            # Operations diagnosis guide
  RELEASE_CHECKLIST.md  # Demo and handoff checklist
requirements.txt
```

---

## Dashboard Areas

| Tab | Content |
|-----|---------|
| **Données** | Live spot, 3Y price history, futures curve, options chain with Greeks, vol surface, all 50 SX5E components |
| **Risques** | Black-Scholes pricer, scenario P&L grid (spot × vol), portfolio builder with Greek aggregation |
| **Ordres** | Order ticket validation and dry-run preview, with live routing disabled |
| **Surface** | 3D implied vol surface, vol smile, ATM term structure |
| **Ops** | Latest run validation, model versions, artifacts, and release health |

---

## Important notes

- **Options and futures are only available on weekdays** — EUREX is closed on weekends, so those sections will be empty Saturday/Sunday. This is expected.
- The session stays alive automatically via a background keepalive thread (tickles every 55 seconds).
- If you get a 401 error at any point, go back to Step 2 and log in again.
- Never commit `.env` or any file containing credentials.
