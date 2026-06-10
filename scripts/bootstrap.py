"""
Bootstrap smoke test — Client Portal REST API version.

Proves end-to-end connectivity WITHOUT placing any orders:
  1. Check gateway authentication
  2. Print accounts
  3. Resolve the Eurostoxx 50 index (SX5E)
  4. Request spot price snapshot and check market-data entitlement
  5. Write a JSON proof record to data/raw/

Run from repo root:
    .venv\\Scripts\\python scripts\\bootstrap.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.connectivity.session import IBKRClient
from src.data.fetcher import _num

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("bootstrap")

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "broker.yaml"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# last, bid, ask, high, low, chg, chg%, market-data-availability
SPOT_FIELDS = ["31", "84", "86", "70", "71", "82", "83", "6509"]


def section(title: str) -> None:
    logger.info("─" * 55)
    logger.info("  %s", title)
    logger.info("─" * 55)


def main() -> None:
    client = IBKRClient.from_config(str(CONFIG_PATH))

    section("1 — Auth check")
    auth = client.check_auth()
    logger.info("Status: %s", auth)

    section("2 — Accounts")
    accounts = client.get_accounts()
    logger.info("Accounts: %s", accounts)

    section("3 — Resolve Eurostoxx 50 index")
    conid = None
    for symbol in ["ESTX50", "SX5E", "STOXX50E", "IBEX"]:
        results = client.search_contract(symbol)
        logger.info("Search '%s' → %s", symbol, results)
        if isinstance(results, list) and results:
            contract = results[0]
            conid = contract.get("conid")
            logger.info("Found: %s  conId=%s", contract.get("companyName", symbol), conid)
            break
    if not conid:
        raise RuntimeError("Could not resolve index — see search results above.")

    section("4 — Spot price snapshot + market-data entitlement")
    snaps = client.snapshot([conid], SPOT_FIELDS)
    snap = snaps[0] if snaps else {}

    last  = _num(snap.get("31"))
    chg   = _num(snap.get("82"))
    chg_p = _num(snap.get("83"))
    close = round(last - chg, 2) if last is not None and chg is not None else None
    availability = snap.get("6509")

    logger.info(
        "last=%s  bid=%s  ask=%s  high=%s  low=%s  close=%s  chg=%s (%s%%)",
        last, snap.get("84"), snap.get("86"), snap.get("70"), snap.get("71"),
        close, chg, chg_p,
    )
    logger.info("Market data availability (field 6509): %s", availability)

    if last is None:
        logger.warning(
            "No 'last' price returned — check market-data entitlement, "
            "or the snapshot subscription may need a moment to warm up."
        )
    elif availability and "R" not in str(availability):
        logger.warning(
            "Market data may not be real-time (availability=%s). "
            "Expected 'R' for real-time entitlement.", availability,
        )
    else:
        logger.info("Market data entitlement OK.")

    section("5 — Write proof record")
    record = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "auth": auth,
        "accounts": accounts,
        "contract": {"conid": conid, "raw": contract},
        "snapshot": {
            "raw": snap,
            "last": last, "close": close, "chg": chg, "chg_p": chg_p,
            "bid": _num(snap.get("84")), "ask": _num(snap.get("86")),
            "high": _num(snap.get("70")), "low": _num(snap.get("71")),
            "market_data_availability": availability,
        },
    }
    out = RAW_DIR / f"bootstrap_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(record, indent=2, default=str))
    logger.info("Written: %s", out)

    client.unsubscribe_all()
    section("BOOTSTRAP COMPLETE")


if __name__ == "__main__":
    main()
