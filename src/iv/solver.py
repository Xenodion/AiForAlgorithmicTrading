"""
Bracketed implied-volatility solver with per-contract diagnostics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

from src.analytics.pricer import black_scholes


@dataclass
class IVSolveResult:
    implied_vol: float | None
    status: str
    iterations: int
    residual: float | None
    lower_vol: float
    upper_vol: float
    model: str
    reason: str | None
    intrinsic: float | None
    price: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def intrinsic_value(spot: float, strike: float, option_type: str) -> float:
    if option_type == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def solve_implied_volatility(
    price: float | None,
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    option_type: str,
    low: float = 1e-4,
    high: float = 5.0,
    tol: float = 1e-5,
    max_iter: int = 100,
) -> dict:
    model = "Black-Scholes bisection"

    if price is None:
        return IVSolveResult(None, "not_solved", 0, None, low, high, model, "missing_price", None, price).to_dict()
    if spot <= 0 or strike <= 0 or maturity <= 0:
        return IVSolveResult(None, "not_solved", 0, None, low, high, model, "invalid_inputs", None, price).to_dict()
    if not all(isfinite(v) for v in (price, spot, strike, maturity, rate)):
        return IVSolveResult(None, "not_solved", 0, None, low, high, model, "non_finite_inputs", None, price).to_dict()

    intrinsic = intrinsic_value(spot, strike, option_type)
    if price <= intrinsic:
        return IVSolveResult(
            None,
            "not_solved",
            0,
            price - intrinsic,
            low,
            high,
            model,
            "below_or_at_intrinsic",
            intrinsic,
            price,
        ).to_dict()

    low_price = black_scholes(spot, strike, maturity, rate, low, option_type)
    high_price = black_scholes(spot, strike, maturity, rate, high, option_type)
    if price < low_price:
        return IVSolveResult(
            None,
            "not_solved",
            0,
            price - low_price,
            low,
            high,
            model,
            "below_lower_bracket",
            intrinsic,
            price,
        ).to_dict()
    if price > high_price:
        return IVSolveResult(
            None,
            "not_solved",
            0,
            price - high_price,
            low,
            high,
            model,
            "above_upper_bracket",
            intrinsic,
            price,
        ).to_dict()

    lo, hi = low, high
    residual = None
    mid = None
    for iteration in range(1, max_iter + 1):
        mid = (lo + hi) / 2.0
        mid_price = black_scholes(spot, strike, maturity, rate, mid, option_type)
        residual = mid_price - price
        if abs(residual) < tol:
            return IVSolveResult(
                mid,
                "converged",
                iteration,
                residual,
                low,
                high,
                model,
                None,
                intrinsic,
                price,
            ).to_dict()
        if mid_price < price:
            lo = mid
        else:
            hi = mid

    return IVSolveResult(
        (lo + hi) / 2.0 if mid is not None else None,
        "max_iter",
        max_iter,
        residual,
        low,
        high,
        model,
        "max_iterations_reached",
        intrinsic,
        price,
    ).to_dict()

