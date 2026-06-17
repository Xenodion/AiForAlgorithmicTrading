"""
Surface construction from accepted IV points.

The fitted grid is intentionally simple for now: linear interpolation by
maturity slice in total variance space, with no strike extrapolation.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from math import exp, isfinite, log, sqrt
from typing import Any


SURFACE_MODEL_VERSION = "forward-total-variance-v2"


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


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if isfinite(v)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def build_iv_points(
    option_rows: list[dict[str, Any]],
    spot: float,
    rate: float = 0.03,
    forwards_by_maturity: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    forwards_by_maturity = forwards_by_maturity or {}
    points = []
    for row in option_rows:
        strike = _as_float(row.get("Strike"))
        iv_pct = _as_float(row.get("IV %"))
        if not row.get("Surface Eligible") or strike is None or iv_pct is None:
            continue

        maturity = str(row.get("Maturity"))
        t = maturity_years(maturity)
        sigma = iv_pct / 100.0
        forward = forwards_by_maturity.get(maturity) or spot * exp(rate * t)
        log_moneyness = log(strike / forward) if strike > 0 and forward > 0 else None
        total_variance = sigma * sigma * t

        points.append({
            "Maturity": maturity,
            "Strike": strike,
            "Type": row.get("Type"),
            "Right": row.get("Right"),
            "Delta": row.get("Delta"),
            "IV %": iv_pct,
            "Implied Vol": sigma,
            "Maturity Years": t,
            "Forward": forward,
            "Forward Source": "curve" if maturity in forwards_by_maturity else "spot_rate_fallback",
            "Log Moneyness": log_moneyness,
            "Total Variance": total_variance,
            "Mid": row.get("Mid"),
            "Quote Quality": row.get("Quote Quality"),
            "QC Status": row.get("QC Status"),
            "QC Reasons": row.get("QC Reasons") or [],
            "IV Source": row.get("IV Source"),
            "IV Status": row.get("IV Status"),
            "IV Model": row.get("IV Model"),
            "IV Iterations": row.get("IV Iterations"),
            "IV Residual": row.get("IV Residual"),
            "Surface Eligible": row.get("Surface Eligible"),
        })
    return points


def _interpolate_total_variance(curve: list[dict[str, Any]], strike: float) -> tuple[float | None, str]:
    exact = [point["Total Variance"] for point in curve if point["Strike"] == strike]
    exact_value = _mean(exact)
    if exact_value is not None:
        return exact_value, "observed"

    lower = next((point for point in reversed(curve) if point["Strike"] < strike), None)
    upper = next((point for point in curve if point["Strike"] > strike), None)
    if not lower or not upper:
        return None, "outside_slice"

    weight = (strike - lower["Strike"]) / (upper["Strike"] - lower["Strike"])
    total_variance = lower["Total Variance"] + weight * (upper["Total Variance"] - lower["Total Variance"])
    return total_variance, "interpolated"


def _calendar_diagnostics(grid_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_strike: dict[float, list[dict[str, Any]]] = {}
    for row in grid_rows:
        if row.get("Total Variance") is None:
            continue
        by_strike.setdefault(row["Strike"], []).append(row)

    violations = []
    for strike, rows in by_strike.items():
        ordered = sorted(rows, key=lambda row: row["Maturity Years"])
        for prev, curr in zip(ordered, ordered[1:]):
            if curr["Total Variance"] + 1e-8 < prev["Total Variance"]:
                violations.append({
                    "strike": strike,
                    "fromMaturity": prev["Maturity"],
                    "toMaturity": curr["Maturity"],
                    "fromTotalVariance": prev["Total Variance"],
                    "toTotalVariance": curr["Total Variance"],
                })

    return {
        "checkedStrikes": len(by_strike),
        "violationCount": len(violations),
        "violations": violations[:20],
    }


def build_surface(
    option_rows: list[dict[str, Any]],
    spot: float,
    rate: float = 0.03,
    forwards_by_maturity: dict[str, float] | None = None,
    forward_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forwards_by_maturity = forwards_by_maturity or {}
    iv_points = build_iv_points(
        option_rows,
        spot=spot,
        rate=rate,
        forwards_by_maturity=forwards_by_maturity,
    )
    maturities = sorted({point["Maturity"] for point in iv_points})
    strikes = sorted({point["Strike"] for point in iv_points})

    by_maturity = {
        maturity: sorted(
            [point for point in iv_points if point["Maturity"] == maturity],
            key=lambda point: point["Strike"],
        )
        for maturity in maturities
    }

    grid_rows = []
    z_full = []
    fit_source_counts = Counter()
    slice_diagnostics = []

    for strike in strikes:
        z_row = []
        for maturity in maturities:
            curve = by_maturity[maturity]
            t = maturity_years(maturity)
            total_variance, fit_source = _interpolate_total_variance(curve, strike)
            fit_source_counts[fit_source] += 1
            if total_variance is None:
                iv_pct = None
                log_moneyness = None
            else:
                iv_pct = sqrt(max(total_variance / t, 0.0)) * 100.0
                forward = forwards_by_maturity.get(maturity) or spot * exp(rate * t)
                log_moneyness = log(strike / forward)

            z_row.append(iv_pct)
            grid_rows.append({
                "Maturity": maturity,
                "Strike": strike,
                "IV %": iv_pct,
                "Total Variance": total_variance,
                "Maturity Years": t,
                "Forward": forwards_by_maturity.get(maturity) or spot * exp(rate * t),
                "Log Moneyness": log_moneyness,
                "Fit Source": fit_source,
            })
        z_full.append(z_row)

    complete_strikes = [
        strike
        for strike, z_row in zip(strikes, z_full)
        if z_row and all(value is not None for value in z_row)
    ]
    display_strikes = complete_strikes or strikes
    display_strike_set = set(display_strikes)
    display_rows = [row for row in grid_rows if row["Strike"] in display_strike_set]
    z = [z_row for strike, z_row in zip(strikes, z_full) if strike in display_strike_set]

    for maturity, points in by_maturity.items():
        point_errors = []
        for point in points:
            fitted_total_variance, _ = _interpolate_total_variance(by_maturity[maturity], point["Strike"])
            if fitted_total_variance is not None:
                fitted_iv = sqrt(max(fitted_total_variance / point["Maturity Years"], 0.0)) * 100.0
                point_errors.append(fitted_iv - point["IV %"])
        rmse = sqrt(sum(error * error for error in point_errors) / len(point_errors)) if point_errors else None
        max_abs_error = max((abs(error) for error in point_errors), default=None)
        slice_diagnostics.append({
            "maturity": maturity,
            "acceptedPoints": len(points),
            "strikeMin": min((point["Strike"] for point in points), default=None),
            "strikeMax": max((point["Strike"] for point in points), default=None),
            "fitMethod": "linear interpolation in total variance",
            "rmse": rmse,
            "maxAbsError": max_abs_error,
            "forward": forwards_by_maturity.get(maturity),
            "quality": "usable" if len(points) >= 4 else "sparse",
            "warnings": [] if len(points) >= 4 else ["sparse_slice"],
        })

    calendar = _calendar_diagnostics(grid_rows)
    warnings = []
    if not iv_points:
        warnings.append("no_surface_eligible_points")
    if calendar["violationCount"]:
        warnings.append("calendar_total_variance_decrease")
    if iv_points and not complete_strikes:
        warnings.append("no_complete_common_strike_domain")

    return {
        "modelVersion": SURFACE_MODEL_VERSION,
        "coordinateSystem": "common strike grid; forward log-moneyness; fitted in total variance",
        "spot": spot,
        "rate": rate,
        "forwardModel": forward_diagnostics.get("modelVersion") if forward_diagnostics else "spot * exp(rate * T) proxy",
        "forwardDiagnostics": forward_diagnostics or {},
        "ivPoints": iv_points,
        "grid": {
            "maturities": maturities,
            "strikes": display_strikes,
            "z": z,
            "rows": display_rows,
        },
        "diagnosticGrid": {
            "maturities": maturities,
            "strikes": strikes,
            "z": z_full,
            "rows": grid_rows,
        },
        "diagnostics": {
            "rawRows": len(option_rows),
            "acceptedPoints": len(iv_points),
            "rejectedRows": len(option_rows) - len(iv_points),
            "fitSourceCounts": dict(fit_source_counts),
            "displayGrid": {
                "strikeCount": len(display_strikes),
                "strikeMin": min(display_strikes, default=None),
                "strikeMax": max(display_strikes, default=None),
                "excludedOutsideCommonDomain": len(strikes) - len(display_strikes),
            },
            "slices": slice_diagnostics,
            "calendar": calendar,
            "warnings": warnings,
        },
    }
