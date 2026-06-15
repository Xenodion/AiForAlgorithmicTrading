# How to Start the App

## Every time you want to work

### Step 1 — Start the IBKR Gateway
Open a **CMD** window (not PowerShell, not Git Bash) and run:
```
cd C:\ibkr-gateway
bin\run.bat root\conf.yaml

mac  : 

cd ~/Desktop/clientportal.gw
./bin/run.sh root/conf.yaml
```
Keep this window open. You should see:
```
Open https://localhost:5050 to login
```

### Step 2 — Log in
Open your browser and go to: **https://localhost:5050**

- Accept the SSL warning (click Advanced → Proceed)
- Enter your IBKR username and password
- Select **Paper Trading**
- Wait for "Client login succeeds"

### Step 3 — Run the dashboard
Open a terminal in the project folder and run the API:
```bash
uvicorn src.api.server:app --reload --port 8000
```

### Step 4 — Run the React frontend
Open a second terminal:
```bash
cd frontend
npm install
npm run dev
```

### Step 5 — Open the dashboard
Go to: **http://localhost:5173**

---

## Notes
- The gateway CMD window (Step 1) must stay open the whole time
- The API terminal and frontend terminal must stay open the whole time
- The session stays alive automatically (background keepalive every 55s) — no need to re-login while the app is running
- IBKR paper trading is **offline on weekends** — options chain and futures will be empty Saturday/Sunday, this is normal
- If you get a 401 error, your session expired — go back to Step 2 and log in again
- Futures prices and options chain only populate on weekdays (EUREX hours)

---

## First-time setup (once only)
```powershell
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cd frontend
npm install
```

If you add a new dependency:
```powershell
.venv/Scripts/pip install <package>
.venv/Scripts/pip freeze > requirements.txt
```
