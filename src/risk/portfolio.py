"""
Portfolio risk, scenario, and simple replay-style backtest helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from typing import Any

from src.analytics.pricer import black_scholes, greeks, pnl_approximation


SCENARIO_SET_VERSION = "spot-vol-time-grid-v1"
BACKTEST_VERSION = "spot-realized-vol-backtest-v3"
REALIZED_VOL_WINDOW = 20


@dataclass(frozen=True)
class Position:
    label: str
    option_type: str
    strike: float
    maturity: float
    rate: float
    sigma: float
    quantity: int = 1
    multiplier: float = 10.0

    @classmethod
    def from_any(cls, item: Any) -> "Position":
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif hasattr(item, "dict"):
            data = item.dict()
        else:
            data = dict(item)
        return cls(
            label=data.get("label") or f"{data.get('option_type', 'option')} {data.get('strike')}",
            option_type=data["option_type"],
            strike=float(data["strike"]),
            maturity=float(data["maturity"]),
            rate=float(data.get("rate", 0.03)),
            sigma=float(data["sigma"]),
            quantity=int(data.get("quantity", 1)),
            multiplier=float(data.get("multiplier", 10.0)),
        )


def value_position(position: Position, spot: float) -> dict[str, Any]:
    price = black_scholes(
        spot,
        position.strike,
        position.maturity,
        position.rate,
        position.sigma,
        position.option_type,
    )
    g = greeks(
        spot,
        position.strike,
        position.maturity,
        position.rate,
        position.sigma,
        position.option_type,
        position.multiplier,
    )
    market_value = price * position.quantity * position.multiplier
    return {
        "label": position.label,
        "optionType": position.option_type,
        "strike": position.strike,
        "maturity": position.maturity,
        "rate": position.rate,
        "sigma": position.sigma,
        "quantity": position.quantity,
        "multiplier": position.multiplier,
        "price": round(price, 4),
        "marketValue": round(market_value, 2),
        "greeks": g,
        "euroGreeks": {
            "delta": round(g["dollar_delta"] * position.quantity, 2),
            "gamma": round(g["dollar_gamma"] * position.quantity, 2),
            "vega": round(g["dollar_vega"] * position.quantity, 2),
            "theta": round(g["dollar_theta"] * position.quantity, 2),
        },
    }


def portfolio_report(positions: list[Any], spot: float) -> dict[str, Any]:
    parsed = [Position.from_any(item) for item in positions]
    lines = [value_position(position, spot) for position in parsed]
    totals = {
        "marketValue": round(sum(line["marketValue"] for line in lines), 2),
        "delta": round(sum(line["euroGreeks"]["delta"] for line in lines), 2),
        "gamma": round(sum(line["euroGreeks"]["gamma"] for line in lines), 2),
        "vega": round(sum(line["euroGreeks"]["vega"] for line in lines), 2),
        "theta": round(sum(line["euroGreeks"]["theta"] for line in lines), 2),
    }
    by_maturity: dict[str, dict[str, float]] = {}
    for line in lines:
        key = f"{line['maturity']:.2f}Y"
        bucket = by_maturity.setdefault(key, {"marketValue": 0.0, "delta": 0.0, "vega": 0.0})
        bucket["marketValue"] += line["marketValue"]
        bucket["delta"] += line["euroGreeks"]["delta"]
        bucket["vega"] += line["euroGreeks"]["vega"]

    return {
        "version": "portfolio-risk-v1",
        "spot": spot,
        "lineCount": len(lines),
        "lines": lines,
        "totals": totals,
        "byMaturity": {key: {k: round(v, 2) for k, v in value.items()} for key, value in by_maturity.items()},
    }


def scenario_report(
    positions: list[Any],
    spot: float,
    spot_shocks: list[float] | None = None,
    vol_shocks: list[float] | None = None,
    day_shocks: list[int] | None = None,
) -> dict[str, Any]:
    parsed = [Position.from_any(item) for item in positions]
    spot_shocks = spot_shocks or [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]
    vol_shocks = vol_shocks or [-0.10, -0.05, 0.0, 0.05, 0.10]
    day_shocks = day_shocks or [0]

    base_values = {
        position.label: black_scholes(
            spot,
            position.strike,
            position.maturity,
            position.rate,
            position.sigma,
            position.option_type,
        )
        for position in parsed
    }
    base_total = sum(
        base_values[position.label] * position.quantity * position.multiplier
        for position in parsed
    )

    rows = []
    for spot_shock in spot_shocks:
        for vol_shock in vol_shocks:
            for day_shock in day_shocks:
                shocked_spot = spot * (1 + spot_shock)
                pnl_full = 0.0
                pnl_greeks = 0.0
                contributors = []
                for position in parsed:
                    shocked_sigma = max(position.sigma + vol_shock, 1e-6)
                    shocked_maturity = max(position.maturity - day_shock / 365.0, 1 / 365)
                    shocked_price = black_scholes(
                        shocked_spot,
                        position.strike,
                        shocked_maturity,
                        position.rate,
                        shocked_sigma,
                        position.option_type,
                    )
                    base_price = base_values[position.label]
                    line_pnl = (shocked_price - base_price) * position.quantity * position.multiplier
                    g = greeks(
                        spot,
                        position.strike,
                        position.maturity,
                        position.rate,
                        position.sigma,
                        position.option_type,
                        position.multiplier,
                    )
                    approx = pnl_approximation(
                        g["delta"],
                        g["gamma"],
                        g["vega"],
                        g["theta"],
                        dS=shocked_spot - spot,
                        d_sigma=vol_shock,
                        dt=day_shock,
                        multiplier=position.multiplier,
                    ) * position.quantity
                    pnl_full += line_pnl
                    pnl_greeks += approx
                    contributors.append({"label": position.label, "pnl": round(line_pnl, 2)})

                rows.append({
                    "Scenario Set": SCENARIO_SET_VERSION,
                    "Spot shock": f"{spot_shock:+.0%}",
                    "Vol shock": f"{vol_shock:+.0%}",
                    "Time shock": f"{day_shock}d",
                    "New spot": round(shocked_spot, 2),
                    "P&L (full)": round(pnl_full, 2),
                    "P&L (Greeks)": round(pnl_greeks, 2),
                    "Error": round(pnl_full - pnl_greeks, 2),
                    "Top Contributors": sorted(contributors, key=lambda item: abs(item["pnl"]), reverse=True)[:5],
                })

    worst = min(rows, key=lambda row: row["P&L (full)"], default=None)
    best = max(rows, key=lambda row: row["P&L (full)"], default=None)
    return {
        "version": SCENARIO_SET_VERSION,
        "spot": spot,
        "baseValue": round(base_total, 2),
        "rows": rows,
        "summary": {
            "scenarioCount": len(rows),
            "worst": worst,
            "best": best,
        },
    }


def _historical_vol_proxies(history_rows: list[dict[str, Any]], window: int = REALIZED_VOL_WINDOW) -> list[float | None]:
    closes = [float(row["close"]) if row.get("close") is not None else None for row in history_rows]
    returns: list[float | None] = [None]
    for previous, current in zip(closes, closes[1:]):
        if previous is None or current is None or previous <= 0 or current <= 0:
            returns.append(None)
        else:
            returns.append(log(current / previous))

    proxies: list[float | None] = []
    for index in range(len(closes)):
        sample = [value for value in returns[max(1, index - window + 1): index + 1] if value is not None]
        if len(sample) < 5:
            proxies.append(None)
            continue
        mean_return = sum(sample) / len(sample)
        variance = sum((value - mean_return) ** 2 for value in sample) / max(len(sample) - 1, 1)
        proxies.append(max(sqrt(variance) * sqrt(252), 1e-6))
    return proxies


def _scale_historical_sigma(current_sigma: float, current_proxy: float | None, historical_proxy: float | None) -> float:
    if current_proxy is None or historical_proxy is None or current_proxy <= 0:
        return current_sigma
    scaled = current_sigma * historical_proxy / current_proxy
    return min(max(scaled, 1e-4), 5.0)


def backtest_report(positions: list[Any], history_rows: list[dict[str, Any]], spot_today: float) -> dict[str, Any]:
    parsed = [Position.from_any(item) for item in positions]
    if not history_rows:
        return {
            "version": BACKTEST_VERSION,
            "rows": [],
            "coverage": {"historyRows": 0, "usedRows": 0, "missingRows": 0},
        }

    today_date = history_rows[-1]["date"]
    vol_proxies = _historical_vol_proxies(history_rows)
    current_vol_proxy = next((value for value in reversed(vol_proxies) if value is not None), None)
    rows = []
    missing = 0
    for index, item in enumerate(history_rows):
        historical_spot = item.get("close")
        if historical_spot is None:
            missing += 1
            continue
        days_ago = (today_date - item["date"]).days
        pnl_full = 0.0
        pnl_approx = 0.0
        delta_component = 0.0
        gamma_component = 0.0
        vega_component = 0.0
        theta_component = 0.0
        historical_vol_proxy = vol_proxies[index]
        for position in parsed:
            maturity_then = position.maturity + days_ago / 365
            sigma_then = _scale_historical_sigma(position.sigma, current_vol_proxy, historical_vol_proxy)
            value_then = black_scholes(
                historical_spot,
                position.strike,
                maturity_then,
                position.rate,
                sigma_then,
                position.option_type,
            )
            value_today = black_scholes(
                spot_today,
                position.strike,
                position.maturity,
                position.rate,
                position.sigma,
                position.option_type,
            )
            g = greeks(
                historical_spot,
                position.strike,
                maturity_then,
                position.rate,
                sigma_then,
                position.option_type,
                position.multiplier,
            )
            dS = spot_today - historical_spot
            d_sigma = position.sigma - sigma_then
            line_delta = g["delta"] * dS * position.multiplier * position.quantity
            line_gamma = 0.5 * g["gamma"] * dS ** 2 * position.multiplier * position.quantity
            line_vega = g["vega"] * d_sigma * 100 * position.multiplier * position.quantity
            line_theta = g["theta"] * days_ago * position.multiplier * position.quantity
            pnl_full += (value_today - value_then) * position.quantity * position.multiplier
            pnl_approx += pnl_approximation(
                g["delta"],
                g["gamma"],
                g["vega"],
                g["theta"],
                dS=dS,
                d_sigma=d_sigma,
                dt=days_ago,
                multiplier=position.multiplier,
            ) * position.quantity
            delta_component += line_delta
            gamma_component += line_gamma
            vega_component += line_vega
            theta_component += line_theta

        rows.append({
            "Date": item["date"],
            "Spot": historical_spot,
            "P&L (full)": round(pnl_full, 2),
            "P&L (Greeks)": round(pnl_approx, 2),
            "Delta P&L": round(delta_component, 2),
            "Gamma P&L": round(gamma_component, 2),
            "Vega P&L": round(vega_component, 2),
            "Theta P&L": round(theta_component, 2),
            "Error": round(pnl_full - pnl_approx, 2),
            "Historical Vol Proxy": round(historical_vol_proxy * 100, 2) if historical_vol_proxy is not None else None,
            "Current Vol Proxy": round(current_vol_proxy * 100, 2) if current_vol_proxy is not None else None,
            "Data Quality": "realized_vol_proxy" if historical_vol_proxy is not None else "spot_only_proxy",
        })

    return {
        "version": BACKTEST_VERSION,
        "rows": rows,
        "coverage": {
            "historyRows": len(history_rows),
            "usedRows": len(rows),
            "missingRows": missing,
            "realizedVolWindow": REALIZED_VOL_WINDOW,
            "note": "Uses historical spot and a rolling realized-volatility proxy scaled to the current user IV. It is richer than delta-only, but still not a replay of historical option surfaces.",
        },
    }
