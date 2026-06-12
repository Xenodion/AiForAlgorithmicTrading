"""
Read-only repository for the persisted instrument master (Step 2).

Operates on data/analytics/universe_<YYYY-MM-DD>.json — no IBKR client,
no network calls. This is the API later steps / the dashboard use to look
up resolved contracts without re-discovering them on every rerun.
"""

from __future__ import annotations

import json
from pathlib import Path

UNIVERSE_DIR = Path(__file__).parent.parent.parent / "data" / "analytics"


class UnresolvedContractError(Exception):
    """A requested expiry/contract is not present in the active universe."""


def load_active_universe(trade_date: str | None = None) -> dict:
    """
    Load the normalized universe record for trade_date (YYYY-MM-DD), or the
    most recent one if trade_date is None. Filenames sort chronologically.
    """
    if trade_date:
        path = UNIVERSE_DIR / f"universe_{trade_date}.json"
        if not path.exists():
            raise FileNotFoundError(f"No universe file for trade_date={trade_date}: {path}")
    else:
        candidates = sorted(UNIVERSE_DIR.glob("universe_*.json"))
        if not candidates:
            raise FileNotFoundError(f"No universe files found in {UNIVERSE_DIR}")
        path = candidates[-1]

    return json.loads(path.read_text(encoding="utf-8"))


def get_underlying(universe: dict | None = None) -> dict:
    universe = universe or load_active_universe()
    return universe["underlying"]


def get_option_chain(universe: dict | None = None, expiry_month: str | None = None) -> list[dict]:
    """All option chain entries, or those matching expiry_month (YYYYMM)."""
    universe = universe or load_active_universe()
    chain = universe["option_chain"]
    if expiry_month is None:
        return chain

    matches = [entry for entry in chain if entry["expiry_month"] == expiry_month]
    if not matches:
        raise UnresolvedContractError(f"No option chain entry for expiry_month={expiry_month!r}")
    return matches


def resolve_contract(universe: dict | None = None, *, sec_type: str, expiry_month: str) -> dict:
    """
    Look up chain-level contract metadata for a given expiry month.
    sec_type="OPT" -> option_chain entry (strikes, multiplier, currency, trading_class).
    sec_type="FUT" -> futures_chain entry; requires a resolved conid.
    """
    universe = universe or load_active_universe()

    if sec_type == "OPT":
        matches = [e for e in universe["option_chain"] if e["expiry_month"] == expiry_month]
        if not matches:
            raise UnresolvedContractError(f"No option chain entry for expiry_month={expiry_month!r}")
        return matches[0]

    if sec_type == "FUT":
        matches = [e for e in universe["futures_chain"] if e["expiry_month"] == expiry_month]
        if not matches or matches[0].get("conid") is None:
            raise UnresolvedContractError(f"No resolved futures contract for expiry_month={expiry_month!r}")
        return matches[0]

    raise ValueError(f"Unsupported sec_type: {sec_type!r}")
