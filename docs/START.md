# How to Start the App

## Every time you want to work

### Step 1 — Start the IBKR Gateway
Open a CMD window (not Git Bash) and run:
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
Open a Git Bash terminal in the project folder and run:
```bash
.venv/Scripts/python app.py
```

### Step 4 — Open the dashboard
Go to: **http://localhost:8050**

---

## Notes
- The gateway CMD window (Step 1) must stay open the whole time
- The Git Bash terminal (Step 3) must stay open the whole time
- The session stays alive automatically — no need to re-login while the app is running
- IBKR paper trading is **offline on weekends** — work Monday to Friday only
- If you get a 401 error, your session expired — go back to Step 2 and log in again
