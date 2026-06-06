# How to Start the App

## Every time you want to work

### Step 1 — Start the IBKR Gateway
Open a **CMD** window (not PowerShell, not Git Bash) and run:
```
cd C:\ibkr-gateway
bin\run.bat root\conf.yaml
```
Keep this window open. You should see:
```
Open https://localhost:5000 to login
```

### Step 2 — Log in
Open your browser and go to: **https://localhost:5000**

- Accept the SSL warning (click Advanced → Proceed)
- Enter your IBKR username and password
- Select **Paper Trading**
- Wait for "Client login succeeds"

### Step 3 — Run the dashboard
Open a **PowerShell** terminal in the project folder and run:
```powershell
.venv/Scripts/streamlit run app.py
```

### Step 4 — Open the dashboard
Streamlit opens it automatically. If not, go to: **http://localhost:8501**

---

## Notes
- The gateway CMD window (Step 1) must stay open the whole time
- The PowerShell terminal (Step 3) must stay open the whole time
- The session stays alive automatically (background keepalive every 55s) — no need to re-login while the app is running
- IBKR paper trading is **offline on weekends** — options chain and futures will be empty Saturday/Sunday, this is normal
- If you get a 401 error, your session expired — go back to Step 2 and log in again
- Futures prices and options chain only populate on weekdays (EUREX hours)

---

## First-time setup (once only)
```powershell
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

If you add a new dependency:
```powershell
.venv/Scripts/pip install <package>
.venv/Scripts/pip freeze > requirements.txt
```
