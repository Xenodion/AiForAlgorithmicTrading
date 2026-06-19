"""
Named option quote quality checks.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

import pandas as pd


QUOTE_QC_VERSION = "quote-qc-v2"


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def mid_price(row: Any) -> float | None:
    bid = _as_float(row.get("Bid"))
    ask = _as_float(row.get("Ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2.0


def intrinsic_value(row: Any, spot: float) -> float:
    strike = _as_float(row.get("Strike")) or 0.0
    right = str(row.get("Right") or row.get("Type", "")).upper()
    option_type = "put" if right.startswith("P") else "call"
    return max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)


def _check_bid_ask(row: Any) -> list[str]:
    reasons = []
    bid = _as_float(row.get("Bid"))
    ask = _as_float(row.get("Ask"))
    if bid is None or ask is None:
        reasons.append("missing_bid_ask")
    elif bid <= 0 or ask <= 0:
        reasons.append("non_positive_bid_ask")
    elif ask < bid:
        reasons.append("crossed_market")
    elif ask == bid:
        reasons.append("locked_market")
    return reasons


def _check_reference_price(row: Any, spot: float, mid: float | None) -> list[str]:
    reasons = []
    last = _as_float(row.get("Last"))
    if mid is None:
        if last is not None and last > 0:
            reasons.append("last_only")
        else:
            reasons.append("empty_quote")
        return reasons

    bid = _as_float(row.get("Bid"))
    ask = _as_float(row.get("Ask"))
    spread_pct = (ask - bid) / mid if bid is not None and ask is not None and mid > 0 else None
    if spread_pct is not None:
        if spread_pct > 0.50:
            reasons.append("extreme_spread")
        elif spread_pct > 0.15:
            reasons.append("wide_spread")
    if mid + 1e-9 < intrinsic_value(row, spot):
        reasons.append("below_intrinsic")
    return reasons


def _check_iv(row: Any) -> list[str]:
    iv = _as_float(row.get("IV %"))
    if iv is None:
        return ["missing_iv"]
    if iv <= 0 or iv > 200:
        return ["implausible_iv"]
    return []


# Quotes priced at/near the exchange minimum tick carry no usable information:
# the inversion turns 1-2 ticks of premium into noisy, extreme implied vols
# that distort the surface wings. Reject anything below this premium.
MIN_PREMIUM = 0.5


def _check_min_premium(reference_price: float | None) -> list[str]:
    if reference_price is not None and reference_price < MIN_PREMIUM:
        return ["below_min_premium"]
    return []


def evaluate_quote(row: Any, spot: float) -> dict[str, Any]:
    mid = mid_price(row)
    bid = _as_float(row.get("Bid"))
    ask = _as_float(row.get("Ask"))
    spread_pct = (ask - bid) / mid if bid is not None and ask is not None and mid and mid > 0 else None
    reference_price = mid
    reference_type = "mid" if mid is not None else None
    if reference_price is None:
        last = _as_float(row.get("Last"))
        if last is not None and last > 0:
            reference_price = last
            reference_type = "last"

    reasons = []
    for check in (_check_bid_ask,):
        reasons.extend(check(row))
    reasons.extend(_check_reference_price(row, spot, mid))
    reasons.extend(_check_iv(row))
    reasons.extend(_check_min_premium(reference_price))
    reasons = list(dict.fromkeys(reasons))

    hard_reject = {
        "crossed_market",
        "empty_quote",
        "missing_iv",
        "implausible_iv",
        "below_intrinsic",
        "extreme_spread",
        "below_min_premium",
    }
    caution = {
        "wide_spread",
        "last_only",
        "missing_bid_ask",
        "non_positive_bid_ask",
        "locked_market",
    }

    if any(reason in hard_reject for reason in reasons):
        status = "reject"
        surface_eligible = False
    elif any(reason in caution for reason in reasons):
        status = "caution"
        surface_eligible = mid is not None and _as_float(row.get("IV %")) is not None
    else:
        status = "usable"
        surface_eligible = True

    return {
        "QC Version": QUOTE_QC_VERSION,
        "QC Status": status,
        "QC Reasons": reasons,
        "Surface Eligible": surface_eligible,
        "QC Spread %": spread_pct,
        "QC Reference Price": reference_price,
        "QC Reference Type": reference_type,
        "QC Intrinsic": intrinsic_value(row, spot),
    }


def apply_quote_qc(df: pd.DataFrame, spot: float) -> pd.DataFrame:
    df = df.copy()
    results = [evaluate_quote(row, spot) for _, row in df.iterrows()]
    for column in [
        "QC Version",
        "QC Status",
        "QC Reasons",
        "Surface Eligible",
        "QC Spread %",
        "QC Reference Price",
        "QC Reference Type",
        "QC Intrinsic",
    ]:
        df[column] = [result[column] for result in results]
    return df

