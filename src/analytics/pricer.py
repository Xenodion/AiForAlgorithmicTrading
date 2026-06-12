"""
Black-Scholes / Black-76 European pricer and Greeks.
All Greeks use standard market conventions (delta w.r.t. spot, vega per 1% vol, theta per day).
"""

from __future__ import annotations
from math import log, sqrt, exp, erf, pi as _pi, isfinite


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cdf(x: float) -> float:
    return (1.0 + erf(x / sqrt(2.0))) / 2.0


def _pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * _pi)


# ── Core pricer ────────────────────────────────────────────────────────────────

def black_scholes(S: float, K: float, T: float, r: float, sigma: float,
                  option_type: str = "call") -> float:
    """
    European Black-Scholes price.
    S     : spot price
    K     : strike
    T     : time to expiry in years
    r     : risk-free rate (decimal, e.g. 0.03 for 3%)
    sigma : implied vol (decimal, e.g. 0.20 for 20%)
    option_type: 'call' or 'put'
    """
    if T <= 0:
        return max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if sigma <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        return intrinsic

    d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)

    if option_type == "call":
        return S * _cdf(d1) - K * exp(-r * T) * _cdf(d2)
    else:
        return K * exp(-r * T) * _cdf(-d2) - S * _cdf(-d1)


def implied_volatility(price: float, S: float, K: float, T: float, r: float,
                       option_type: str = "call",
                       low: float = 1e-4, high: float = 5.0,
                       tol: float = 1e-5, max_iter: int = 100) -> float | None:
    """
    Solve Black-Scholes implied volatility by bisection.
    Returns decimal volatility, or None when the market price is not invertible.
    """
    if price is None or S <= 0 or K <= 0 or T <= 0:
        return None
    if not all(isfinite(v) for v in (price, S, K, T, r)):
        return None

    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if price <= intrinsic:
        return None

    low_price = black_scholes(S, K, T, r, low, option_type)
    high_price = black_scholes(S, K, T, r, high, option_type)
    if price < low_price or price > high_price:
        return None

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        mid_price = black_scholes(S, K, T, r, mid, option_type)
        if abs(mid_price - price) < tol:
            return mid
        if mid_price < price:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0


def greeks(S: float, K: float, T: float, r: float, sigma: float,
           option_type: str = "call", multiplier: float = 1.0) -> dict:
    """
    Full Greeks for a European option.
    Returns raw Greeks AND dollar Greeks (multiplied by multiplier and relevant factors).
    """
    if T <= 0 or sigma <= 0:
        return {k: 0.0 for k in
                ["delta", "gamma", "vega", "theta", "rho",
                 "dollar_delta", "dollar_gamma", "dollar_vega", "dollar_theta"]}

    d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)

    # Raw Greeks
    delta  = _cdf(d1)  if option_type == "call" else _cdf(d1) - 1.0
    gamma  = _pdf(d1) / (S * sigma * sqrt(T))
    vega   = S * _pdf(d1) * sqrt(T) / 100.0           # per 1% vol move
    theta  = (-(S * _pdf(d1) * sigma / (2.0 * sqrt(T)))
              - r * K * exp(-r * T) * (_cdf(d2) if option_type == "call" else _cdf(-d2))
             ) / 365.0                                  # per calendar day
    rho    = (K * T * exp(-r * T)
              * (_cdf(d2) if option_type == "call" else -_cdf(-d2))) / 100.0  # per 1% rate

    # Dollar Greeks (road map Step 11 conventions)
    dollar_delta = delta * multiplier                   # € per 1-point spot move
    dollar_gamma = gamma * (S ** 2) * multiplier / 100 # € per 1% spot move²
    dollar_vega  = vega  * multiplier                   # € per 1% vol move
    dollar_theta = theta * multiplier                   # € per day

    return {
        "delta":        round(delta,  6),
        "gamma":        round(gamma,  8),
        "vega":         round(vega,   4),
        "theta":        round(theta,  4),
        "rho":          round(rho,    4),
        "dollar_delta": round(dollar_delta, 2),
        "dollar_gamma": round(dollar_gamma, 2),
        "dollar_vega":  round(dollar_vega,  2),
        "dollar_theta": round(dollar_theta, 2),
    }


def pnl_approximation(delta: float, gamma: float, vega: float, theta: float,
                      dS: float, d_sigma: float, dt: float,
                      multiplier: float = 1.0) -> float:
    """
    Local P&L approximation (Taylor expansion):
    dV ≈ Δ·dS + ½·Γ·dS² + ν·dσ + θ·dt
    All inputs in raw Greek units. Returns € P&L.
    """
    pnl = (delta * dS
           + 0.5 * gamma * dS ** 2
           + vega  * d_sigma * 100   # vega is per 1% vol; d_sigma in decimal
           + theta * dt) * multiplier
    return round(pnl, 2)


def scenario_grid(S: float, K: float, T: float, r: float, sigma: float,
                  option_type: str, multiplier: float,
                  spot_shocks: list[float], vol_shocks: list[float]) -> list[dict]:
    """
    Full repricing under a grid of (spot shock, vol shock) scenarios.
    spot_shocks: list of % moves, e.g. [-0.10, -0.05, 0, 0.05, 0.10]
    vol_shocks:  list of absolute vol moves, e.g. [-0.05, 0, 0.05]
    Returns list of { spot_shock, vol_shock, new_price, pnl, pnl_greeks_approx }.
    """
    base_price = black_scholes(S, K, T, r, sigma, option_type)
    g          = greeks(S, K, T, r, sigma, option_type, multiplier)
    rows = []

    for ds_pct in spot_shocks:
        for dv in vol_shocks:
            S_new     = S * (1 + ds_pct)
            sigma_new = max(sigma + dv, 1e-6)
            new_price = black_scholes(S_new, K, T, r, sigma_new, option_type)
            pnl_full  = round((new_price - base_price) * multiplier, 2)
            pnl_approx = pnl_approximation(
                g["delta"], g["gamma"], g["vega"], g["theta"],
                dS=S * ds_pct, d_sigma=dv, dt=0, multiplier=multiplier,
            )
            rows.append({
                "Spot shock":    f"{ds_pct:+.0%}",
                "Vol shock":     f"{dv:+.0%}",
                "New spot":      round(S_new, 2),
                "New vol":       f"{sigma_new:.1%}",
                "New price":     round(new_price, 4),
                "P&L (full)":    pnl_full,
                "P&L (Greeks)":  pnl_approx,
                "Error":         round(pnl_full - pnl_approx, 2),
            })
    return rows
