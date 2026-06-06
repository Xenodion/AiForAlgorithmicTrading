# AI for Algorithmic Trading — Volatility Infrastructure

Streamlit dashboard connected live to IBKR Client Portal REST API.
Displays real-time data, Greeks, scenario engine, and vol surface for the Euro STOXX 50.

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

# 4. Install dependencies
pip install -r requirements.txt
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
base_url: https://localhost:5000
verify_ssl: false
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
Open https://localhost:5000 to login
```

> If you get `'java' is not recognized`, set your Java path in `run.bat`:
> ```bat
> set JAVA_HOME=C:\path\to\your\jdk
> set PATH=%JAVA_HOME%\bin;%PATH%
> ```

### Step 2 — Log in to the gateway

Open your browser → **https://localhost:5000**

- Accept the SSL warning (Advanced → Proceed)
- Log in with your IBKR credentials
- Select **Paper Trading**
- Wait for "Client login succeeds"

### Step 3 — Launch the dashboard

```powershell
.venv\Scripts\streamlit run app.py
```

### Step 4 — Open the dashboard

Goes to **http://localhost:8501** automatically. If not, open it manually.

---

## Project structure

```
app.py                  # Main Streamlit app (3 tabs)
configs/
  broker.yaml           # IBKR gateway URL
src/
  connectivity/
    session.py          # IBKRClient — REST wrapper + auth
  data/
    fetcher.py          # Spot, futures, options, history, components
  analytics/
    pricer.py           # Black-Scholes pricer + Greeks + scenario grid
docs/
  START.md              # Short startup cheatsheet
  roadmap.md            # 16-step project roadmap
requirements.txt
```

---

## Tabs

| Tab | Content |
|-----|---------|
| **Données** | Live spot, 3Y price history, futures curve, options chain with Greeks, vol surface, all 50 SX5E components |
| **Risques** | Black-Scholes pricer, scenario P&L grid (spot × vol), portfolio builder with Greek aggregation |
| **Ordres** | Coming soon |

---

## Important notes

- **Options and futures are only available on weekdays** — EUREX is closed on weekends, so those sections will be empty Saturday/Sunday. This is expected.
- The session stays alive automatically via a background keepalive thread (tickles every 55 seconds).
- If you get a 401 error at any point, go back to Step 2 and log in again.
- Never commit `.env` or any file containing credentials.
