# How to Start the App

## Every time you want to work

### Step 1 — Start the IBKR Gateway

Open a **CMD** window (not PowerShell, not Git Bash) and run:
```
cd C:\ibkr-gateway
bin\run.bat root\conf.yaml
```
Keep this window open. Wait until the console is quiet.

### Step 2 — Log in

Open your browser and go to: **https://localhost:5000**

- Accept the SSL warning (click Advanced → Proceed)
- Enter your IBKR username and password
- Select **Paper Trading**
- Wait for "Client login succeeds"

### Step 3 — Start the Python API

Open a terminal in the project folder:
```bash
.venv/Scripts/uvicorn src.api.server:app --reload --port 8000
```
Sanity check: open **http://localhost:8000/api/status** — should return JSON.

### Step 4 — Start the React frontend

Open a **second** terminal in the project folder:
```bash
cd frontend
npm run dev
```

### Step 5 — Open the dashboard

Go to: **http://localhost:5173**

---

## Notes

- The gateway CMD window (Step 1) must stay open the whole time
- The API terminal (Step 3) and frontend terminal (Step 4) must stay open the whole time
- The session stays alive automatically (background keepalive) — no need to re-login while the app is running
- IBKR paper trading is **offline on weekends** — options chain and futures will be empty Saturday/Sunday, this is normal
- If you get a 401 error, your session expired — go back to Step 2 and log in again
- Futures prices and options chain only populate on weekdays (EUREX hours)
---

## Alternative: Streamlit version (app.py)

If you want to run the original Streamlit dashboard instead of React:

**Steps 1 and 2 are the same** (start the gateway and log in).

Then open a single terminal in the project folder:
```bash
.venv/Scripts/streamlit run app.py
```
Open **http://localhost:8501** — no separate API process needed.

---

## First-time setup (once only)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cd frontend && npm install && cd ..
```

## If new Python packages were added to requirements.txt

```bash
.venv/Scripts/pip install -r requirements.txt
```
