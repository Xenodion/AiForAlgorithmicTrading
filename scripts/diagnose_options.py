"""
Targeted diagnostic for options and futures resolution.
Run: .venv/Scripts/python scripts/diagnose_options.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.connectivity.session import IBKRClient
from src.data.fetcher import _parse_months

client = IBKRClient.from_config("configs/broker.yaml")
client.check_auth()
print("Auth OK\n")

# ── 1. Get index and available months ─────────────────────────────────────────
print("=== INDEX SEARCH ===")
r = client.search_contract("ESTX50")
contract = r[0] if isinstance(r, list) and r else {}
CONID = contract.get("conid")
print(f"conid = {CONID}")

opt_months, fut_months = [], []
for s in contract.get("sections", []):
    months = _parse_months(s.get("months", ""))
    if s.get("secType") == "OPT": opt_months = months
    if s.get("secType") == "FUT": fut_months = months

print(f"opt_months: {opt_months[:4]}")
print(f"fut_months: {fut_months[:4]}")

OPT_MONTH = opt_months[0] if opt_months else "202606"
FUT_MONTH = fut_months[0] if fut_months else "202606"

# ── 2. Strikes ────────────────────────────────────────────────────────────────
print(f"\n=== STRIKES for {OPT_MONTH} ===")
r2 = client.get("/iserver/secdef/strikes", params={
    "conid": CONID, "sectype": "OPT", "month": OPT_MONTH, "exchange": ""
})
print(json.dumps(r2, default=str)[:400])

calls = r2.get("call", []) if isinstance(r2, dict) else []
ATM = sorted(calls, key=lambda k: abs(k - 5000))[0] if calls else 5000
print(f"ATM strike chosen: {ATM}")

# ── 3. secdef/info for OPTION ─────────────────────────────────────────────────
print(f"\n=== secdef/info OPT month={OPT_MONTH} strike={ATM} right=C ===")
try:
    r3 = client.get("/iserver/secdef/info", params={
        "conid": CONID, "sectype": "OPT",
        "month": OPT_MONTH, "right": "C", "strike": ATM,
    })
    print(json.dumps(r3, default=str)[:600])
except Exception as e:
    print(f"ERROR: {e}")

# ── 4. secdef/info for FUTURES ────────────────────────────────────────────────
print(f"\n=== secdef/info FUT month={FUT_MONTH} ===")
try:
    r4 = client.get("/iserver/secdef/info", params={
        "conid": CONID, "sectype": "FUT", "month": FUT_MONTH,
    })
    print(json.dumps(r4, default=str)[:600])
except Exception as e:
    print(f"ERROR: {e}")

# ── 5. Try searching OESX (EUREX option root symbol) ─────────────────────────
print("\n=== SEARCH OESX (EUREX option symbol) ===")
try:
    r5 = client.post("/iserver/secdef/search", json={
        "symbol": "OESX", "secType": "OPT", "name": False
    })
    print(json.dumps(r5, default=str)[:600])
except Exception as e:
    print(f"ERROR: {e}")

# ── 6. Try searching FESX (EUREX futures symbol) ─────────────────────────────
print("\n=== SEARCH FESX (EUREX futures symbol) ===")
try:
    r6 = client.post("/iserver/secdef/search", json={
        "symbol": "FESX", "secType": "FUT", "name": False
    })
    print(json.dumps(r6, default=str)[:600])
except Exception as e:
    print(f"ERROR: {e}")
