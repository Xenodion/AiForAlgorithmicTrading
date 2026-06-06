"""
Bootstrap smoke test — Client Portal REST API version.

Proves end-to-end connectivity WITHOUT placing any orders:
  1. Check gateway authentication
  2. Print accounts
  3. Resolve the Eurostoxx 50 index (SX5E)
  4. Request spot price snapshot
  5. List available option expiry months
  6. Write a JSON proof record to data/raw/

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

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("bootstrap")

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "broker.yaml"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SPOT_FIELDS = ["31", "84", "85", "70", "71", "7284"]  # last, bid, ask, high, low, close


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

    section("4 — Spot price snapshot")
    snaps = client.snapshot([conid], SPOT_FIELDS)
    snap = snaps[0] if snaps else {}
    logger.info(
        "bid=%s  ask=%s  last=%s  high=%s  low=%s",
        snap.get("84"), snap.get("85"), snap.get("31"),
        snap.get("70"), snap.get("71"),
    )

    section("5 — Write proof record")
    record = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "auth": auth,
        "accounts": accounts,
        "contract": {"conid": conid, "raw": contract},
        "snapshot": snap,
    }
    out = RAW_DIR / f"bootstrap_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(record, indent=2, default=str))
    logger.info("Written: %s", out)

    client.unsubscribe_all()
    section("BOOTSTRAP COMPLETE")


if __name__ == "__main__":
    main()
