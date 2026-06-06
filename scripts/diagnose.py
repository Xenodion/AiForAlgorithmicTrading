"""
Diagnostic script — prints raw API responses at every step.
Run: .venv\\Scripts\\python scripts\\diagnose.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.connectivity.session import IBKRClient

client = IBKRClient.from_config("configs/broker.yaml")
client.check_auth()
print("Auth OK\n")

# 1. Try every symbol variant
print("=== CONTRACT SEARCH ===")
for sym in ["ESTX50", "SX5E", "STOXX50E", "SPX", "INDU"]:
    r = client.search_contract(sym)
    print(f"{sym}: {json.dumps(r, default=str)[:200]}")

print()

# 2. Pick the first successful conid
conid = None
for sym in ["ESTX50", "SX5E", "STOXX50E", "SPX"]:
    r = client.search_contract(sym)
    if isinstance(r, list) and r and r[0].get("conid"):
        conid = r[0]["conid"]
        print(f"Using conid={conid} ({sym})")
        break

if not conid:
    print("No conid found — stopping.")
    sys.exit(1)

# 3. Spot snapshot
print("\n=== SPOT SNAPSHOT ===")
snaps = client.snapshot([conid], ["31","84","85","70","71","7284"])
print(json.dumps(snaps, default=str))

# 4. Try different option chain endpoints
print("\n=== OPTION CHAIN DISCOVERY ===")

# Approach A: search with OPT secType
print("-- A: POST secdef/search OPT --")
try:
    r = client.post("/iserver/secdef/search", json={"symbol": "ESTX50", "secType": "OPT", "name": False})
    print(json.dumps(r, default=str)[:600])
except Exception as e:
    print(f"Error: {e}")

# Approach B: secdefbyconid
print("\n-- B: GET secdefbyconid --")
try:
    r = client.get("/iserver/secdef/secdefbyconid", params={"conids": conid})
    print(json.dumps(r, default=str)[:400])
except Exception as e:
    print(f"Error: {e}")

# Approach C: strikes with a guessed current month
import datetime
this_month = datetime.date.today().strftime("%Y%m")
next_month = (datetime.date.today().replace(day=1) + datetime.timedelta(days=32)).strftime("%Y%m")
print(f"\n-- C: strikes for {this_month} and {next_month} --")
for m in [this_month, next_month]:
    try:
        r = client.get("/iserver/secdef/strikes", params={
            "conid": conid, "sectype": "OPT", "month": m, "exchange": "EUREX"
        })
        print(f"  {m}: {json.dumps(r, default=str)[:300]}")
    except Exception as e:
        print(f"  {m}: Error {e}")
