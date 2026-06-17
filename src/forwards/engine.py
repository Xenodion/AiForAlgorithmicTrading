"""
Parity forward engine with diagnostics.

The engine prefers call-put parity candidates by maturity and falls back to a
documented spot/rate proxy when no usable pair exists.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import exp, isfinite
from typing import Any


FORWARD_MODEL_VERSION = "parity-forward-v1"


def maturity_years(month: str, today: date | None = None) -> float:
    today = today or date.today()
    year = int(str(month)[:4])
    month_num = int(str(month)[4:6])
    if month_num == 12:
        expiry = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        expiry = date(year, month_num + 1, 1) - timedelta(days=1)
    return max((expiry - today).days / 365.0, 1 / 365.0)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _price(row: dict[str, Any]) -> float | None:
    for key in ("Mid", "IV Price"):
        value = _as_float(row.get(key))
        if value is not None and value > 0:
            return value
    bid = _as_float(row.get("Bid"))
    ask = _as_float(row.get("Ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    return None


def _weight(row: dict[str, Any]) -> float:
    quality = row.get("Quote Quality")
    qc_status = row.get("QC Status")
    base = {
        "tight": 1.0,
        "wide": 0.6,
        "very wide": 0.25,
        "last only": 0.1,
    }.get(str(quality), 0.15)
    if qc_status == "usable":
        return base
    if qc_status == "caution":
        return base * 0.5
    return 0.0


def build_forward_curve(
    option_rows: list[dict[str, Any]],
    spot: float,
    rate: float = 0.03,
) -> dict[str, Any]:
    grouped: dict[tuple[str, float], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in option_rows:
        maturity = row.get("Maturity")
        strike = _as_float(row.get("Strike"))
        right = str(row.get("Right") or "").upper()
        if not maturity or strike is None or right not in {"C", "P"}:
            continue
        grouped[(str(maturity), strike)][right] = row

    candidates_by_maturity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (maturity, strike), pair in grouped.items():
        call = pair.get("C")
        put = pair.get("P")
        if not call or not put:
            continue
        call_price = _price(call)
        put_price = _price(put)
        if call_price is None or put_price is None:
            continue
        t = maturity_years(maturity)
        forward = strike + exp(rate * t) * (call_price - put_price)
        weight = min(_weight(call), _weight(put))
        if weight <= 0:
            continue
        candidates_by_maturity[maturity].append({
            "maturity": maturity,
            "strike": strike,
            "callPrice": call_price,
            "putPrice": put_price,
            "forward": forward,
            "weight": weight,
            "callQuality": call.get("Quote Quality"),
            "putQuality": put.get("Quote Quality"),
            "callStatus": call.get("QC Status"),
            "putStatus": put.get("QC Status"),
        })

    maturities = sorted({str(row.get("Maturity")) for row in option_rows if row.get("Maturity")})
    forwards = {}
    rows = []
    diagnostics = {
        "modelVersion": FORWARD_MODEL_VERSION,
        "spot": spot,
        "rate": rate,
        "maturities": [],
        "warnings": [],
    }

    for maturity in maturities:
        t = maturity_years(maturity)
        candidates = candidates_by_maturity.get(maturity, [])
        if candidates:
            weight_sum = sum(candidate["weight"] for candidate in candidates)
            forward = sum(candidate["forward"] * candidate["weight"] for candidate in candidates) / weight_sum
            source = "call_put_parity"
            residuals = [candidate["forward"] - forward for candidate in candidates]
            max_abs_residual = max((abs(value) for value in residuals), default=None)
        else:
            forward = spot * exp(rate * t)
            source = "spot_rate_fallback"
            max_abs_residual = None
            diagnostics["warnings"].append(f"forward_fallback:{maturity}")

        forwards[maturity] = forward
        row = {
            "Maturity": maturity,
            "Maturity Years": t,
            "Forward": forward,
            "Source": source,
            "Candidate Count": len(candidates),
            "Max Abs Residual": max_abs_residual,
            "Candidates": candidates,
        }
        rows.append(row)
        diagnostics["maturities"].append(row)

    return {
        "modelVersion": FORWARD_MODEL_VERSION,
        "spot": spot,
        "rate": rate,
        "forwards": forwards,
        "rows": rows,
        "diagnostics": diagnostics,
    }

