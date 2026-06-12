"""
Universe discovery (Step 2).

Builds the canonical instrument-master record (see schema.py) by querying
IBKR discovery endpoints. Pure functions returning (normalized, raw) pairs
— no file I/O here, that's scripts/build_universe.py.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from src.connectivity.session import IBKRClient
from src.data.fetcher import resolve_index, _num
from src.universe.dq_checks import run_all_checks

logger = logging.getLogger(__name__)


# ── Expiry / maturity helpers ───────────────────────────────────────────────

def _normalize_expiry(maturity_date) -> str | None:
    """'20260918' -> '2026-09-18'."""
    if not maturity_date:
        return None
    s = str(maturity_date)
    if len(s) != 8:
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _yyyymm_to_index(yyyymm: str) -> int:
    """'202609' -> 2026*12 + 8 (0-based month) -> sortable integer."""
    year, month = int(yyyymm[:4]), int(yyyymm[4:6])
    return year * 12 + (month - 1)


def _select_maturity_months(all_months: list[str], windows_months: list[int]) -> list[str]:
    """
    For each target N in windows_months, pick the month from all_months
    closest to (today + N months). Dedupe + sort the results, so the
    returned list is small, deterministic, and bounded regardless of how
    many months the broker lists.
    """
    if not all_months:
        return []
    today_index = _yyyymm_to_index(date.today().strftime("%Y%m"))
    selected = set()
    for n in windows_months:
        target_index = today_index + n
        closest = min(all_months, key=lambda m: abs(_yyyymm_to_index(m) - target_index))
        selected.add(closest)
    return sorted(selected)


# ── Underlying ───────────────────────────────────────────────────────────────

def discover_underlying(client: IBKRClient, cfg_underlying: dict) -> tuple[dict, dict]:
    """Resolve the underlying index and reshape into an UnderlyingRecord."""
    info = resolve_index(client)
    raw_search = client.search_contract(info["symbol"])

    record = {
        "conid": info["conid"],
        "symbol": info["symbol"],
        "name": info["name"],
        "sec_type": cfg_underlying.get("sec_type", "IND"),
        "exchange": cfg_underlying.get("exchange", "EUREX"),
        "currency": cfg_underlying.get("currency", "EUR"),
        "opt_months": info["opt_months"],
        "fut_months": info["fut_months"],
    }
    raw = {"underlying_search": raw_search}
    return record, raw


# ── Option chain ───────────────────────────────────────────────────────────

def discover_option_chain_entry(
    client: IBKRClient, underlying: dict, month: str,
    exchange: str, option_trading_class: str | None,
) -> tuple[dict, dict]:
    """
    Build one OptionChainEntry for a given expiry month: strikes via
    /iserver/secdef/strikes, then probe one mid-strike contract via
    /iserver/secdef/info for multiplier/currency/trading_class/expiry_date.
    """
    underlying_conid = underlying["conid"]

    strikes_raw = client.get("/iserver/secdef/strikes", params={
        "conid": underlying_conid, "sectype": "OPT", "month": month, "exchange": exchange,
    })
    strikes = []
    if isinstance(strikes_raw, dict):
        strikes = sorted(set((strikes_raw.get("call") or []) + (strikes_raw.get("put") or [])))

    entry = {
        "underlying_conid": underlying_conid,
        "underlying_symbol": underlying["symbol"],
        "expiry_month": month,
        "expiry_date": None,
        "trading_class": None,
        "currency": None,
        "multiplier": None,
        "exchange": exchange,
        "strikes": strikes,
        "n_strikes": len(strikes),
        "sample_conid": None,
        "quality_flags": [],
    }
    raw = {"strikes_raw": strikes_raw, "probe": None}

    if not strikes:
        entry["quality_flags"].append("empty_strikes")
        return entry, raw

    sample_strike = strikes[len(strikes) // 2]
    probe = client.get("/iserver/secdef/info", params={
        "conid": underlying_conid, "sectype": "OPT", "month": month,
        "strike": sample_strike, "right": "C", "exchange": exchange,
    })
    raw["probe"] = probe

    probe_contract = probe[0] if isinstance(probe, list) and probe else None
    if not probe_contract:
        entry["quality_flags"].append("probe_failed")
        return entry, raw

    entry["sample_conid"] = probe_contract.get("conid")
    entry["trading_class"] = probe_contract.get("tradingClass")
    entry["currency"] = probe_contract.get("currency")
    entry["multiplier"] = _num(probe_contract.get("multiplier"))
    entry["expiry_date"] = _normalize_expiry(probe_contract.get("maturityDate"))

    if option_trading_class and entry["trading_class"] != option_trading_class:
        entry["quality_flags"].append("trading_class_mismatch")

    return entry, raw


# ── Futures chain ────────────────────────────────────────────────────────────

def discover_futures_chain_entry(
    client: IBKRClient, underlying: dict, month: str,
    exchange: str, future_trading_class: str | None,
) -> tuple[dict, dict]:
    """
    Build one FuturesChainEntry for a given expiry month via
    /iserver/secdef/info, selecting the candidate whose tradingClass
    matches future_trading_class (e.g. "FESX", multiplier=10) instead
    of blindly taking the first result (which for ESTX50 can be "FSXE",
    multiplier=1).
    """
    underlying_conid = underlying["conid"]

    info = client.get("/iserver/secdef/info", params={
        "conid": underlying_conid, "sectype": "FUT", "month": month, "exchange": exchange,
    })
    candidates = info if isinstance(info, list) else ([info] if isinstance(info, dict) else [])

    entry = {
        "underlying_conid": underlying_conid,
        "underlying_symbol": underlying["symbol"],
        "expiry_month": month,
        "expiry_date": None,
        "trading_class": None,
        "currency": None,
        "multiplier": None,
        "exchange": exchange,
        "conid": None,
        "candidates": candidates,
        "quality_flags": [],
    }
    raw = {"info": info}

    if not candidates:
        entry["quality_flags"].append("no_candidates")
        return entry, raw

    selected = next((c for c in candidates if c.get("tradingClass") == future_trading_class), None)
    if selected is None:
        selected = candidates[0]
        entry["quality_flags"].append("trading_class_not_found")

    entry["conid"] = selected.get("conid")
    entry["trading_class"] = selected.get("tradingClass")
    entry["currency"] = selected.get("currency")
    entry["multiplier"] = _num(selected.get("multiplier"))
    entry["expiry_date"] = _normalize_expiry(selected.get("maturityDate"))

    return entry, raw


# ── Top-level orchestration ─────────────────────────────────────────────────

def build_universe(client: IBKRClient, config: dict, config_hash: str) -> tuple[dict, dict]:
    """
    Discover the underlying, its option chain, and its futures chain for
    the maturity windows configured in configs/universe.yaml. Returns
    (universe_record, raw_payloads).
    """
    cfg_underlying = config["underlyings"][0]
    exchange = cfg_underlying.get("exchange", "EUREX")
    option_trading_class = cfg_underlying.get("option_trading_class")
    future_trading_class = cfg_underlying.get("future_trading_class")

    underlying, raw_underlying = discover_underlying(client, cfg_underlying)
    logger.info("Underlying: %s (conid=%s)", underlying["symbol"], underlying["conid"])

    opt_windows = config["option_chain"]["maturity_windows_months"]
    fut_windows = config["futures"]["maturity_windows_months"]

    opt_months = _select_maturity_months(underlying["opt_months"], opt_windows)
    fut_months = _select_maturity_months(underlying["fut_months"], fut_windows)
    logger.info("Option chain months: %s", opt_months)
    logger.info("Futures chain months: %s", fut_months)

    option_chain, option_raw = [], {}
    for month in opt_months:
        entry, raw = discover_option_chain_entry(client, underlying, month, exchange, option_trading_class)
        option_chain.append(entry)
        option_raw[month] = raw
        logger.info(
            "Option %s: %d strikes, multiplier=%s, currency=%s, trading_class=%s, flags=%s",
            month, entry["n_strikes"], entry["multiplier"], entry["currency"],
            entry["trading_class"], entry["quality_flags"],
        )

    futures_chain, futures_raw = [], {}
    for month in fut_months:
        entry, raw = discover_futures_chain_entry(client, underlying, month, exchange, future_trading_class)
        futures_chain.append(entry)
        futures_raw[month] = raw
        logger.info(
            "Future %s: conid=%s, multiplier=%s, currency=%s, trading_class=%s, flags=%s",
            month, entry["conid"], entry["multiplier"], entry["currency"],
            entry["trading_class"], entry["quality_flags"],
        )

    quality = run_all_checks(option_chain, futures_chain)

    universe = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "trade_date": date.today().isoformat(),
        "config_hash": config_hash,
        "raw_payload_file": "",  # filled in by build_universe.py
        "underlying": underlying,
        "option_chain": option_chain,
        "futures_chain": futures_chain,
        "quality": quality,
    }
    raw_payloads = {
        "underlying": raw_underlying,
        "option_chain": option_raw,
        "futures_chain": futures_raw,
    }
    return universe, raw_payloads
