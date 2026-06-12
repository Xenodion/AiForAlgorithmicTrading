"""
Canonical instrument-master schema (Step 2 of the roadmap).

These TypedDicts document the shape of the records produced by
src/universe/discovery.py and consumed by src/universe/repository.py.
They're plain dicts at runtime (JSON-serializable) — this module is
type-hints only, no logic.
"""

from __future__ import annotations
from typing import TypedDict, Optional


class UnderlyingRecord(TypedDict):
    conid: int
    symbol: str
    name: str
    sec_type: str          # "IND"
    exchange: str          # "EUREX"
    currency: str          # "EUR"
    opt_months: list[str]  # YYYYMM
    fut_months: list[str]  # YYYYMM


class OptionChainEntry(TypedDict):
    underlying_conid: int
    underlying_symbol: str
    expiry_month: str             # YYYYMM
    expiry_date: Optional[str]    # YYYY-MM-DD, from maturityDate
    trading_class: Optional[str]  # e.g. "OESX"
    currency: Optional[str]
    multiplier: Optional[float]
    exchange: str
    strikes: list[float]
    n_strikes: int
    sample_conid: Optional[int]   # probe contract used for multiplier/etc.
    quality_flags: list[str]


class FuturesChainEntry(TypedDict):
    underlying_conid: int
    underlying_symbol: str
    expiry_month: str              # YYYYMM
    expiry_date: Optional[str]     # YYYY-MM-DD
    trading_class: Optional[str]   # e.g. "FESX" (selected)
    currency: Optional[str]
    multiplier: Optional[float]
    exchange: str
    conid: Optional[int]           # selected contract's conid
    candidates: list[dict]         # all secdef/info entries returned (audit)
    quality_flags: list[str]


class UniverseRecord(TypedDict):
    run_ts: str             # ISO8601 UTC timestamp of the discovery run
    trade_date: str         # YYYY-MM-DD this universe represents
    config_hash: str        # short hash of configs/universe.yaml content
    raw_payload_file: str   # filename of the matching data/raw/ dump
    underlying: UnderlyingRecord
    option_chain: list[OptionChainEntry]
    futures_chain: list[FuturesChainEntry]
    quality: dict           # {"errors": [...], "warnings": [...]}
