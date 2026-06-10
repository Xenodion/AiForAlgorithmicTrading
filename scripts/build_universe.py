"""
Build the instrument master / universe (Step 2 of the roadmap).

Discovers the configured underlying, its option chain, and its futures
chain via IBKR discovery endpoints, runs data-quality checks, and persists:
  - data/raw/universe_raw_<YYYYMMDD_HHMMSS>.json   (raw broker payloads, audit trail)
  - data/analytics/universe_<YYYY-MM-DD>.json      (normalized, overwritten same-day)

Run from repo root:
    .venv\\Scripts\\python scripts\\build_universe.py
"""

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv
from src.connectivity.session import IBKRClient
from src.universe.discovery import build_universe

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("build_universe")

ROOT = Path(__file__).parent.parent
BROKER_CONFIG_PATH = ROOT / "configs" / "broker.yaml"
UNIVERSE_CONFIG_PATH = ROOT / "configs" / "universe.yaml"
RAW_DIR = ROOT / "data" / "raw"
ANALYTICS_DIR = ROOT / "data" / "analytics"
RAW_DIR.mkdir(parents=True, exist_ok=True)
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)


def section(title: str) -> None:
    logger.info("─" * 55)
    logger.info("  %s", title)
    logger.info("─" * 55)


def main() -> None:
    client = IBKRClient.from_config(str(BROKER_CONFIG_PATH))

    section("1 — Auth check")
    auth = client.check_auth()
    logger.info("Status: %s", auth)

    section("2 — Load universe config")
    config_text = UNIVERSE_CONFIG_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(config_text)
    config_hash = hashlib.sha256(config_text.encode("utf-8")).hexdigest()[:8]
    logger.info("config_hash=%s", config_hash)

    section("3 — Discover universe")
    universe, raw_payloads = build_universe(client, config, config_hash)

    section("4 — Data quality")
    errors = universe["quality"]["errors"]
    warnings = universe["quality"]["warnings"]
    for msg in errors:
        logger.error("ERROR: %s", msg)
    for msg in warnings:
        logger.warning("WARNING: %s", msg)
    if not errors and not warnings:
        logger.info("No issues found.")

    section("5 — Write raw payload dump")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    raw_path = RAW_DIR / f"universe_raw_{ts}.json"
    raw_path.write_text(json.dumps(raw_payloads, indent=2, default=str), encoding="utf-8")
    logger.info("Written: %s", raw_path)

    section("6 — Write normalized universe")
    universe["raw_payload_file"] = raw_path.name
    out_path = ANALYTICS_DIR / f"universe_{universe['trade_date']}.json"
    out_path.write_text(json.dumps(universe, indent=2, default=str), encoding="utf-8")
    logger.info("Written: %s", out_path)

    client.unsubscribe_all()

    if errors:
        section("COMPLETED WITH ERRORS")
        sys.exit(1)

    section("BUILD UNIVERSE COMPLETE")


if __name__ == "__main__":
    main()
